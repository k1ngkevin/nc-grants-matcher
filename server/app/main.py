"""FastAPI app: JSON API + the built React site.  Run:  uvicorn app.main:app --reload"""
import csv
import html
import io
import logging
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, emailer, evaluate
from .agencies import AGENCIES, AGENCY_BY_ID
from .ingest import pipeline
from .matching import embeddings, explain
from .matching.score import DISMISS_REASONS, WEIGHTS
from .normalize import CATEGORY_LABELS, INSTRUMENT_LABELS, TIMING_LABELS
from .search import DEFAULT_MIN_SCORE, Filters, search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
SEED_SAMPLE_IF_EMPTY = os.getenv("SEED_SAMPLE_IF_EMPTY", "true").lower() == "true"
SCHEDULED_INGEST = os.getenv("SCHEDULED_INGEST", "live")  # live | off


def _scheduled_ingest():
    try:
        pipeline.run(sample=False)
    except Exception:
        log.exception("Scheduled ingest failed; keeping existing data")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if config.EMAIL_ENABLED:
        log.info("Email: sending through %s as %s", emailer.describe_backend(), config.SMTP_FROM)
        for problem in emailer.config_problems():
            log.warning("Email setup: %s", problem)
    else:
        log.info("Email: not configured (no ACS_CONNECTION_STRING or SMTP_HOST), so emails are saved to %s", config.OUTBOX_DIR)
    with db.session() as conn:
        empty = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0
    if empty and SEED_SAMPLE_IF_EMPTY:
        log.info("Database empty: loading the labeled SAMPLE dataset. Run `python -m app.ingest` for live data.")
        pipeline.run(sample=True)
    if config.USE_AZURE_EMBEDDINGS:
        s = embeddings.vector_status()
        if s["with_vector"] < s["total"]:
            log.warning("AI matching: Azure deployment '%s' is configured, but only %s of %s opportunities have a vector, "
                        "so matching uses local text similarity. Run `python -m app.ingest --embed`.",
                        config.AZURE_EMBEDDING_DEPLOYMENT, s["with_vector"], s["total"])
        else:
            log.info("AI matching: Azure OpenAI embeddings (deployment '%s')", config.AZURE_EMBEDDING_DEPLOYMENT)
    else:
        log.info("AI matching: local text similarity (Azure embeddings not configured)")
    log.info("Explanations: %s", f"Azure OpenAI deployment '{config.AZURE_CHAT_DEPLOYMENT}' for the top 10, rule-based otherwise"
             if config.USE_AZURE_CHAT else "rule-based (Azure chat not configured)")
    scheduler = None
    if config.RUN_SCHEDULER:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(emailer.send_due_digests, "interval", minutes=15, id="digests")
        if SCHEDULED_INGEST == "live":
            scheduler.add_job(_scheduled_ingest, "cron", hour=config.DAILY_INGEST_HOUR, minute=7, id="ingest")
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="NC Federal Funds Matchmaker", lifespan=lifespan)


# ---------------- basic hardening ----------------
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def rate_limit(request: Request, bucket: str, limit: int, per_seconds: int = 3600):
    ip = request.client.host if request.client else "unknown"
    key, now = f"{bucket}:{ip}", time.time()
    with _hits_lock:
        q = _hits[key]
        while q and q[0] < now - per_seconds:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many requests. Please try again later.")
        q.append(now)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return resp


def _agency(agency_id: str) -> dict:
    if agency_id not in AGENCY_BY_ID:
        raise HTTPException(404, "Unknown agency")
    return AGENCY_BY_ID[agency_id]


# ---------------- models ----------------
class SearchBody(BaseModel):
    agency_id: str
    min_award: int = config.FINANCIAL_FLOOR
    timing: list[str] | None = None
    q: str = Field("", max_length=200)
    federal_agency: str = Field("", max_length=40)
    no_match_only: bool = False
    include_unknown_amount: bool = True
    min_score: int = Field(DEFAULT_MIN_SCORE, ge=0, le=100)
    include_lower_scores: bool = False
    sort: str = Field("score", pattern="^(score|deadline|amount)$")
    view: str = Field("recommended", pattern="^(recommended|pursue|save|dismiss)$")
    limit: int = Field(25, ge=1, le=200)
    offset: int = Field(0, ge=0)


class DecisionBody(BaseModel):
    agency_id: str
    opportunity_id: str = Field(max_length=80)
    action: str = Field(pattern="^(pursue|save|dismiss|undo)$")
    reason: str | None = Field(None, max_length=40)
    note: str = Field("", max_length=1000)
    route_to: str = Field("", max_length=254)
    reviewer: str = Field("", max_length=100)


class ProjectBody(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=10, max_length=4000)


class DocumentBody(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=50, max_length=300_000)


class SubscribeBody(BaseModel):
    email: str = Field(max_length=254)
    agency_id: str
    frequency: str = Field("weekly", pattern="^(daily|weekly|biweekly|monthly)$")
    top_n: int = Field(10, ge=3, le=25)
    filters: dict = {}


def _filters(body: SearchBody) -> Filters:
    _agency(body.agency_id)
    d = body.model_dump(exclude={"limit", "offset"})
    return Filters.from_dict(d)


# ---------------- API ----------------
@app.get("/api/meta")
def meta():
    last = db.get_meta("last_ingest")
    with db.session() as conn:
        n = conn.execute("SELECT COUNT(*), SUM(is_sample) FROM opportunities").fetchone()
    return {
        "agencies": [{k: a[k] for k in ("id", "short", "name", "applicant")} for a in sorted(AGENCIES, key=lambda a: a["name"])],
        "last_ingest": last,
        "opportunity_count": n[0],
        "sample_data": bool(n[1]),
        "financial_floor": config.FINANCIAL_FLOOR,
        "default_min_score": DEFAULT_MIN_SCORE,
        "email_enabled": config.EMAIL_ENABLED,
        "email_confirmation": config.REQUIRE_EMAIL_CONFIRMATION,
        "allowed_email_domains": config.ALLOWED_EMAIL_DOMAINS,
        "ai": {"embeddings": embeddings.active_backend(), "explanations": "azure-openai" if explain.available() else "rules"},
        "dismiss_reasons": DISMISS_REASONS,
        "weights": WEIGHTS,
        "glossary": {
            "timing": TIMING_LABELS,
            "instruments": {v[0]: v[1] for v in INSTRUMENT_LABELS.values()},
            "competition": {v[0]: v[1] for v in CATEGORY_LABELS.values()},
        },
    }


@app.post("/api/search")
def api_search(body: SearchBody):
    return search(_filters(body), limit=body.limit, offset=body.offset, with_llm=True)


@app.post("/api/export.csv")
def export_csv(body: SearchBody):
    data = search(_filters(body), limit=1000, offset=0)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Score", "Title", "Federal agency", "Opportunity number", "Status", "Timing", "Close date", "Days left",
                "Award (up to / avg)", "Grant type", "Competition", "Match", "Assistance listings", "Why it fits", "Link", "Sample data"])
    for r in data["results"]:
        o, s, g = r["opportunity"], r["signals"], r["grant_type"]
        w.writerow([r["score"], o["title"], o.get("federal_agency"), o.get("number"), o.get("status"), r["timing_label"],
                    o.get("close_date") or "", s["days_left"] if s["days_left"] is not None else "", s["amount"] or "",
                    g["instrument"], g["competition"], g["match"], " ".join(o.get("aln_numbers") or []), r["rationale"],
                    o.get("url"), "yes" if o.get("is_sample") else ""])
    name = f"grants-{data['agency']['id']}-{body.view}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/decisions")
def decide(body: DecisionBody, request: Request):
    rate_limit(request, "decisions", 600)
    _agency(body.agency_id)
    if body.action == "dismiss" and body.reason not in DISMISS_REASONS:
        raise HTTPException(400, "Pick a dismiss reason")
    with db.session() as conn:
        if not conn.execute("SELECT 1 FROM opportunities WHERE id=?", (body.opportunity_id,)).fetchone():
            raise HTTPException(404, "Unknown opportunity")
    routed = None
    if body.action == "pursue" and body.route_to:
        err = emailer.valid_email(body.route_to)
        if err:
            raise HTTPException(400, err)
        match = None
        for view in ("recommended", "save", "pursue", "dismiss"):
            data = search(Filters.from_dict({"agency_id": body.agency_id, "view": view, "include_lower_scores": True}), limit=1000)
            match = next((r for r in data["results"] if r["opportunity"]["id"] == body.opportunity_id), None)
            if match:
                break
        if match:
            routed = emailer.route_to_team(body.route_to, body.agency_id, match, body.note, body.reviewer)
    with db.session() as conn:
        conn.execute("INSERT INTO decisions(agency_id, opportunity_id, action, reason, note) VALUES(?,?,?,?,?)",
                     (body.agency_id, body.opportunity_id, body.action, body.reason, body.note))
    return {"ok": True, "routed": routed}


@app.get("/api/agencies/{agency_id}/projects")
def list_projects(agency_id: str):
    _agency(agency_id)
    with db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT id, title, description, created_at FROM projects WHERE agency_id=? ORDER BY id DESC", (agency_id,))]


@app.post("/api/agencies/{agency_id}/projects")
def add_project(agency_id: str, body: ProjectBody, request: Request):
    rate_limit(request, "projects", 100)
    _agency(agency_id)
    with db.session() as conn:
        cur = conn.execute("INSERT INTO projects(agency_id, title, description) VALUES(?,?,?)", (agency_id, body.title.strip(), body.description.strip()))
    return {"id": cur.lastrowid}


@app.delete("/api/agencies/{agency_id}/projects/{project_id}")
def delete_project(agency_id: str, project_id: int):
    with db.session() as conn:
        conn.execute("DELETE FROM projects WHERE id=? AND agency_id=?", (project_id, agency_id))
    return {"ok": True}


@app.get("/api/agencies/{agency_id}/documents")
def list_documents(agency_id: str):
    _agency(agency_id)
    with db.session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, title, length(content) AS characters, created_at FROM agency_documents WHERE agency_id=? ORDER BY id DESC", (agency_id,))]


@app.post("/api/agencies/{agency_id}/documents")
def add_document(agency_id: str, body: DocumentBody, request: Request):
    rate_limit(request, "documents", 30)
    _agency(agency_id)
    with db.session() as conn:
        cur = conn.execute("INSERT INTO agency_documents(agency_id, title, content) VALUES(?,?,?)", (agency_id, body.title.strip(), body.content))
    return {"id": cur.lastrowid}


@app.delete("/api/agencies/{agency_id}/documents/{doc_id}")
def delete_document(agency_id: str, doc_id: int):
    with db.session() as conn:
        conn.execute("DELETE FROM agency_documents WHERE id=? AND agency_id=?", (doc_id, agency_id))
    return {"ok": True}


@app.post("/api/subscriptions")
def subscribe(body: SubscribeBody, request: Request):
    rate_limit(request, "subscribe", 10)
    _agency(body.agency_id)
    err = emailer.valid_email(body.email)
    if err:
        raise HTTPException(400, err)
    try:
        result = emailer.create_subscription(body.email, body.agency_id, body.filters, body.frequency, body.top_n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not result["confirmed"] and result["delivery"].get("error"):
        raise HTTPException(503, "We couldn't send the confirmation email right now. Please try again in a few minutes.")
    return result


def _page(title: str, message: str, button: str = "", action: str = "") -> HTMLResponse:
    form = (f"""<form method="post" action="{html.escape(action)}"><button type="submit" style="background:#123b68;color:#fff;border:0;
padding:10px 18px;border-radius:6px;font-size:15px;cursor:pointer">{html.escape(button)}</button></form>""" if button else "")
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title></head><body style="font-family:Segoe UI,Arial,sans-serif;background:#f4f6f9;margin:0">
<div style="max-width:520px;margin:12vh auto;background:#fff;padding:28px;border-radius:10px">
<h2 style="color:#123b68;margin-top:0">{html.escape(title)}</h2><p>{message}</p>{form}<p><a href="/" style="color:#123b68">Back to the Matchmaker</a></p></div></body></html>""")


# Links in emails only show a page with a button. The change happens on POST, so mail
# security scanners that open every link can't confirm or unsubscribe anyone by themselves.
@app.get("/api/subscriptions/confirm", response_class=HTMLResponse)
def confirm_page(token: str):
    sub = emailer.find_subscription(token)
    if not sub:
        return _page("Link not valid", "This link isn't valid anymore. It may have been used to unsubscribe.")
    a = html.escape(AGENCY_BY_ID[sub["agency_id"]]["name"])
    if sub["confirmed"]:
        return _page("You're already subscribed", f"You get the top grants for <b>{a}</b> {sub['frequency']}.")
    return _page("Confirm your grant alerts", f"Start getting the top grants for <b>{a}</b> {sub['frequency']}?",
                 "Confirm my subscription", f"/api/subscriptions/confirm?token={quote(token, safe='')}")


@app.post("/api/subscriptions/confirm", response_class=HTMLResponse)
def confirm(token: str):
    sub = emailer.confirm(token)
    if not sub:
        return _page("Link not valid", "This link isn't valid anymore. It may have been used to unsubscribe.")
    a = AGENCY_BY_ID[sub["agency_id"]]
    return _page("You're subscribed", f"You'll get the top grants for <b>{html.escape(a['name'])}</b> {sub['frequency']}. "
                 "The first email is on its way. Every email has an unsubscribe link.")


@app.get("/api/subscriptions/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str):
    sub = emailer.find_subscription(token)
    if not sub:
        return _page("Already unsubscribed", "This address isn't getting alerts from this link.")
    a = html.escape(AGENCY_BY_ID[sub["agency_id"]]["name"])
    return _page("Unsubscribe?", f"Stop the {sub['frequency']} grant alerts for <b>{a}</b> to {html.escape(sub['email'])}?",
                 "Unsubscribe", f"/api/subscriptions/unsubscribe?token={quote(token, safe='')}")


@app.post("/api/subscriptions/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str):
    """Used by the page's button and by mail apps' one-click unsubscribe (List-Unsubscribe-Post)."""
    emailer.unsubscribe(token)
    return _page("You're unsubscribed", "You won't get any more grant alerts at this address.")


@app.post("/api/subscriptions/preview", response_class=HTMLResponse)
def preview(body: SubscribeBody):
    _agency(body.agency_id)
    f = Filters.from_dict({**body.filters, "agency_id": body.agency_id, "view": "recommended", "sort": "score"})
    data = search(f, limit=body.top_n, with_llm=True)
    fake = {"agency_id": body.agency_id, "token": "preview", "frequency": body.frequency}
    return HTMLResponse(emailer.digest_html(fake, data))


@app.get("/api/metrics")
def metrics():
    return {"precision_at_10": evaluate.precision_at_10()}


@app.post("/api/admin/ingest")
def admin_ingest(request: Request, sample: bool = False):
    if not ADMIN_TOKEN or request.headers.get("x-admin-token") != ADMIN_TOKEN:
        raise HTTPException(403, "Set ADMIN_TOKEN and send it in the X-Admin-Token header")
    threading.Thread(target=pipeline.run, kwargs={"sample": sample}, daemon=True).start()
    return {"started": True}


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse({"detail": "Something went wrong on our side."}, status_code=500)


# ---------------- the website ----------------
if config.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (config.WEB_DIST / path).resolve()
        if path and target.is_file() and config.WEB_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(config.WEB_DIST / "index.html")
