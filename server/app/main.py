"""FastAPI app: JSON API + the built React site.  Run:  uvicorn app.main:app --reload"""
import csv
import html
import io
import logging
import os
import threading
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import agenda, auth, chat, config, db, emailer, evaluate, public_subscriptions, research, security
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
    auth.validate_config()
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


app = FastAPI(title="NC Federal Funds Matchmaker", lifespan=lifespan,
              dependencies=[Depends(auth.authorize_agency)])
app.include_router(public_subscriptions.router)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path == "/healthz":
        return JSONResponse({"status": "ok"})
    if len(request.scope.get("query_string", b"")) > 4096:
        return JSONResponse({"detail": "Query string is too long."}, status_code=414)
    if request.url.path.startswith("/api/"):
        try:
            security.limit("api-global", "all", 600, 60)
            security.limit("api", security.client_ip(request), 120, 60)
            if request.url.path in {"/api/search", "/api/export.csv", "/api/subscriptions/preview", "/api/calendar", "/api/calendar.ics"}:
                security.limit("expensive-api", security.client_ip(request), 20, 60)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    # Enforce the actual streamed size too: Content-Length alone is forgeable.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        maximum = 16384 if request.url.path.startswith("/api/public/") else 1500000
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > maximum:
                return JSONResponse({"detail": "Request body is too large."}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        origin = request.headers.get("origin")
        token_action = request.method == "POST" and request.url.path in public_subscriptions.TOKEN_ACTION_PATHS
        if origin and origin != config.PUBLIC_BASE_URL and not token_action:
            return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
        if request.url.path in {"/api/public/subscriptions"} and request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"detail": "Use application/json."}, status_code=415)
    if config.AUTH_MODE != "development" and not public_subscriptions.is_public(request):
        try:
            request.state.identity = auth.identity_from_headers(request)
            # Easy Auth uses cookies. Block cross-origin writes and JSON requests
            # submitted as simple HTML forms; do not trust browser-supplied identity.
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if origin and origin != config.PUBLIC_BASE_URL:
                    raise HTTPException(403, "Cross-origin requests are not allowed.")
                if request.url.path.startswith("/api/") and request.url.path not in {
                    "/api/subscriptions/confirm", "/api/subscriptions/unsubscribe", "/api/admin/ingest"
                } and request.headers.get("content-type", "").split(";")[0] != "application/json" and request.method != "DELETE":
                    raise HTTPException(415, "Use application/json.")
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    return await call_next(request)


# ---------------- basic hardening ----------------
def rate_limit(request: Request, bucket: str, limit: int, per_seconds: int = 3600):
    security.limit(bucket, security.client_ip(request), limit, per_seconds)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if "token" in request.query_params:
        resp.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        # setdefault: the notice-PDF route sets its own caching (private, 1 day).
        resp.headers.setdefault("Cache-Control", "no-store")
    # setdefault: a route may set its own framing rules (the notice PDFs are shown in an iframe on this site).
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Content-Security-Policy", (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"))
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
    top_n: int = Field(10, ge=1, le=emailer.MAX_DIGEST_GRANTS, strict=True)
    filters: dict = {}


def _filters(body: SearchBody) -> Filters:
    _agency(body.agency_id)
    d = body.model_dump(exclude={"limit", "offset"})
    return Filters.from_dict(d)


# ---------------- API ----------------
@app.get("/api/meta")
def meta(request: Request):
    last = db.get_meta("last_ingest")
    with db.session() as conn:
        n = conn.execute("SELECT COUNT(*), SUM(is_sample) FROM opportunities").fetchone()
    return {
        "agencies": [{k: a[k] for k in ("id", "short", "name", "applicant")} for a in sorted(AGENCIES, key=lambda a: a["name"])
                     if config.AUTH_MODE == "development" or request.state.identity.allows(a["id"])],
        "last_ingest": last,
        "opportunity_count": n[0],
        "sample_data": bool(n[1]),
        "financial_floor": config.FINANCIAL_FLOOR,
        "default_min_score": DEFAULT_MIN_SCORE,
        "email_enabled": config.EMAIL_ENABLED,
        "email_confirmation": config.REQUIRE_EMAIL_CONFIRMATION,
        "max_digest_grants": emailer.MAX_DIGEST_GRANTS,
        "allowed_email_domains": config.ALLOWED_EMAIL_DOMAINS,
        "ai": {"embeddings": embeddings.active_backend(), "explanations": "azure-openai" if explain.available() else "rules",
               "research": research.available()},
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


@app.post("/api/subscriptions/test")
def test_digest(body: SubscribeBody, request: Request):
    rate_limit(request, "test_digest", 5)
    security.limit("test-recipient", body.email, 3, 3600)
    security.limit("test-global", "all", 50, 3600)
    _agency(body.agency_id)
    err = emailer.valid_email(body.email)
    if err:
        raise HTTPException(400, err)
    if config.AUTH_MODE != "development" and body.email.strip().lower() != request.state.identity.name.lower():
        raise HTTPException(403, "Send test emails only to your signed-in work email.")
    result = emailer.send_test_digest(body.email.strip(), body.agency_id, body.filters, body.top_n)
    if result["delivery"].get("error"):
        raise HTTPException(503, "The test email could not be sent. Check the email provider settings and try again.")
    return result


@app.post("/api/subscriptions/preview", response_class=HTMLResponse)
def preview(body: SubscribeBody):
    _agency(body.agency_id)
    f = Filters.from_dict({**body.filters, "agency_id": body.agency_id, "view": "recommended", "sort": "score"})
    data = search(f, limit=body.top_n, public=True)
    fake = {"agency_id": body.agency_id, "token": "preview", "frequency": body.frequency, "top_n": body.top_n, "public": True, "test": True}
    return HTMLResponse(emailer.digest_html(fake, data))


# ---------------- feedback ----------------

FEEDBACK_KINDS = {"problem": "Something's wrong", "idea": "Idea", "scoring": "Score looks off", "other": "Other"}


class FeedbackBody(BaseModel):
    kind: Literal["problem", "idea", "scoring", "other"]
    message: str = Field(..., min_length=5, max_length=4000)
    email: str = Field("", max_length=254)
    agency_id: str = Field("", max_length=40)
    opportunity_id: str = Field("", max_length=100)
    page: str = Field("", max_length=40)


def _feedback_email(fid: int, body: FeedbackBody) -> None:
    e = html.escape
    agency = AGENCY_BY_ID.get(body.agency_id, {}).get("name", "")
    title = ""
    if body.opportunity_id:
        with db.session() as conn:
            row = conn.execute("SELECT title FROM opportunities WHERE id=?", (body.opportunity_id,)).fetchone()
        title = row["title"] if row else body.opportunity_id
    inner = (f"<p><b>{e(FEEDBACK_KINDS[body.kind])}</b>{' from ' + e(agency) if agency else ''}</p>"
             f"<p style='white-space:pre-wrap'>{e(body.message)}</p>"
             + (f"<p>Grant: {e(title)}</p>" if title else "")
             + (f"<p>Reply to: {e(body.email)}</p>" if body.email else "<p>No reply address given.</p>")
             + f"<p style='color:#666'>Feedback #{fid}, page: {e(body.page or 'unknown')}</p>")
    emailer.send(config.FEEDBACK_EMAIL, f"[Feedback] {FEEDBACK_KINDS[body.kind]}{': ' + agency if agency else ''}",
                 emailer._shell("New feedback", inner))


@app.post("/api/feedback")
def send_feedback(body: FeedbackBody, request: Request):
    rate_limit(request, "feedback", 10)
    email = body.email.strip()
    if email and not emailer.EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address, or leave it blank.")
    if body.agency_id and body.agency_id not in AGENCY_BY_ID:
        raise HTTPException(400, "Unknown agency")
    with db.session() as conn:
        fid = conn.execute(
            "INSERT INTO feedback(kind, message, email, agency_id, opportunity_id, page) VALUES(?,?,?,?,?,?)",
            (body.kind, body.message.strip(), email or None, body.agency_id or None,
             body.opportunity_id or None, body.page or None)).lastrowid
    if config.FEEDBACK_EMAIL:  # don't make the person wait on the mail server
        threading.Thread(target=_feedback_email, args=(fid, body), daemon=True).start()
    return {"ok": True, "id": fid}


@app.get("/api/admin/feedback")
def list_feedback(request: Request, limit: int = 200):
    if not ADMIN_TOKEN or request.headers.get("x-admin-token") != ADMIN_TOKEN:
        raise HTTPException(403, "Set ADMIN_TOKEN and send it in the X-Admin-Token header")
    with db.session() as conn:
        rows = conn.execute(
            """SELECT f.*, o.title AS opportunity_title FROM feedback f
               LEFT JOIN opportunities o ON o.id = f.opportunity_id
               ORDER BY f.id DESC LIMIT ?""", (max(1, min(limit, 1000)),)).fetchall()
    return [dict(r) for r in rows]


# ---------------- in-depth research ----------------

class ResearchBody(BaseModel):
    opportunity_id: str = Field(..., max_length=100)
    agency_id: str = Field(..., max_length=40)
    refresh: bool = False


def _research_error(e: research.ResearchError):
    busy = "in progress" in str(e)
    raise HTTPException(429 if busy else 400, str(e))


@app.post("/api/research")
def start_research(body: ResearchBody, request: Request):
    """Start reading the notice documents for one grant (or return the saved result). Poll the job."""
    if body.agency_id not in AGENCY_BY_ID:
        raise HTTPException(404, "Unknown agency")
    if not research.available():
        raise HTTPException(400, "In-depth research needs Azure OpenAI chat (AZURE_CHAT_DEPLOYMENT) to be configured.")
    if body.refresh or not research.cached(body.opportunity_id, body.agency_id):
        rate_limit(request, "research", 30)  # each run is a long, paid AI call
    try:
        return research.start(body.opportunity_id, body.agency_id, refresh=body.refresh)
    except research.ResearchError as e:
        _research_error(e)


@app.get("/api/research")
def get_research(opportunity_id: str, agency_id: str):
    hit = research.cached(opportunity_id, agency_id)
    return {"status": "done", "result": hit} if hit else {"status": "none"}


@app.get("/api/research/jobs/{job_id}")
def research_job(job_id: str):
    j = research.job(job_id)
    if not j:
        raise HTTPException(404, "That research run has expired. Start it again.")
    return {k: j.get(k) for k in ("id", "status", "phase", "result", "error")}


@app.get("/api/opportunities/{opportunity_id}/documents/{att_id}")
def opportunity_document(opportunity_id: str, att_id: str):
    """Serve a notice attachment from Grants.gov, inline, so the site can show it next to the research."""
    doc = research.known_document(opportunity_id, att_id)
    if not doc:
        try:
            research.list_documents(opportunity_id)
        except research.ResearchError as e:
            raise HTTPException(502, str(e))
        doc = research.known_document(opportunity_id, att_id)
    if not doc:
        raise HTTPException(404, "That document isn't attached to this grant.")
    try:
        data = research.download(att_id)
    except research.ResearchError as e:
        raise HTTPException(502, str(e))
    is_pdf = data[:5] == b"%PDF-"
    name = doc["file_name"] or f"{att_id}.pdf"
    return Response(data, media_type="application/pdf" if is_pdf else (doc["mime"] or "application/octet-stream"), headers={
        "Content-Disposition": f"{'inline' if is_pdf else 'attachment'}; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "private, max-age=86400",
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
    })


# ---------------- calendar ----------------

class CalendarBody(BaseModel):
    agency_id: str = Field(max_length=40)
    include: list[Literal["pursue", "save", "recommended", "research"]] = ["pursue", "save", "research"]
    filters: dict = Field(default_factory=dict)  # search filters for the "recommended" layer
    recommended_limit: int = Field(15, ge=1, le=50)
    opportunity_id: str = Field("", max_length=100)  # just this grant, whatever its status


def _calendar(body: CalendarBody) -> dict:
    _agency(body.agency_id)
    filters = None
    if "recommended" in body.include and not body.opportunity_id:
        try:  # same validation as /api/search
            filters = _filters(SearchBody(**{**body.filters, "agency_id": body.agency_id, "view": "recommended"}))
        except ValidationError as e:
            raise HTTPException(422, "; ".join(err["msg"] for err in e.errors()))
    try:
        return agenda.build(body.agency_id, body.include, filters, body.recommended_limit, body.opportunity_id)
    except LookupError:
        raise HTTPException(404, "Unknown opportunity")


@app.post("/api/calendar")
def calendar_events(body: CalendarBody):
    """Deadlines for the grants an agency tracks, plus dated steps from saved research."""
    return _calendar(body)


@app.post("/api/calendar.ics")
def calendar_ics(body: CalendarBody):
    data = _calendar(body)
    if body.opportunity_id:
        title = next((e["opportunity"]["title"] for e in data["events"]), "grant")
        name, file = f"{data['agency']['short']}: {title}", f"grant-{body.opportunity_id.replace(':', '-')}.ics"
    else:
        name, file = f"{data['agency']['short']} grant deadlines", f"grant-calendar-{body.agency_id}.ics"
    file = "".join(c for c in file if c.isalnum() or c in "-_.")
    return Response(agenda.to_ics(data, name), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{file}"'})


# ---------------- ask about a grant ----------------

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatBody(BaseModel):
    opportunity_id: str = Field(max_length=100)
    agency_id: str = Field(max_length=40)
    question: str = Field(min_length=3, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


@app.post("/api/chat")
def ask_about_grant(body: ChatBody, request: Request):
    """One question about one grant, answered from its notice documents. Nothing is stored."""
    _agency(body.agency_id)
    rate_limit(request, "chat", 60)       # each question is a paid AI call
    security.limit("chat-global", "all", 600, 3600)
    try:
        return chat.ask(body.opportunity_id, body.agency_id, body.question, [t.model_dump() for t in body.history])
    except LookupError:
        raise HTTPException(404, "That grant wasn't found. Reload the page and try again.")
    except chat.ChatError as e:
        raise HTTPException(400, str(e))


@app.get("/api/metrics")
def metrics():
    return {"precision_at_10": evaluate.precision_at_10()}


@app.post("/api/admin/ingest")
def admin_ingest(request: Request, sample: bool = False):
    if config.AUTH_MODE == "development" and (not ADMIN_TOKEN or request.headers.get("x-admin-token") != ADMIN_TOKEN):
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
