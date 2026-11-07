"""Email: confirmation, scheduled "top grants" digests, and Pursue hand-offs.

With SMTP_* set, mail goes out over SMTP (Office 365 / SendGrid / Azure Communication
Services SMTP all work). Without it, each message is written to data/outbox/ as an .html
file so the demo still works and nothing leaves the machine.
"""
import html
import json
import logging
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from . import config, db
from .agencies import AGENCY_BY_ID
from .matching.explain import money
from .search import Filters, search

log = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FREQUENCIES = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}
SEND_HOUR_UTC = 12  # ~8am Eastern


def valid_email(email: str) -> str | None:
    """Return an error message, or None if the address is acceptable."""
    if not EMAIL_RE.match(email or "") or len(email) > 254:
        return "Please enter a valid email address."
    domain = email.rsplit("@", 1)[1].lower()
    if config.ALLOWED_EMAIL_DOMAINS and not any(domain == d or domain.endswith("." + d) for d in config.ALLOWED_EMAIL_DOMAINS):
        return f"Only these email domains can subscribe: {', '.join(config.ALLOWED_EMAIL_DOMAINS)}."
    return None


def send(to: str, subject: str, html_body: str) -> dict:
    if config.EMAIL_ENABLED:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
        msg.set_content(re.sub(r"<[^>]+>", "", html_body))
        msg.add_alternative(html_body, subtype="html")
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            if config.SMTP_STARTTLS:
                s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
        log.info("Sent '%s' to %s", subject, to)
        return {"delivered": True}
    config.OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = config.OUTBOX_DIR / f"{stamp}-{re.sub(r'[^a-z0-9]+', '_', to.lower())}.html"
    path.write_text(f"<!-- To: {html.escape(to)} | Subject: {html.escape(subject)} -->\n{html_body}", encoding="utf-8")
    log.info("SMTP not configured; wrote '%s' to %s", subject, path)
    return {"delivered": False, "outbox_file": path.name}


def next_send_time(frequency: str, after: datetime | None = None) -> str:
    after = after or datetime.now(timezone.utc)
    nxt = (after + timedelta(days=FREQUENCIES[frequency])).replace(hour=SEND_HOUR_UTC, minute=0, second=0, microsecond=0)
    return nxt.isoformat(timespec="seconds")


# ---------------- templates ----------------
def _shell(title: str, inner: str, footer: str = "") -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#f4f6f9;font-family:Segoe UI,Arial,sans-serif;color:#1b2a3a">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;background:#fff;border-radius:10px;overflow:hidden">
<tr><td style="background:#123b68;color:#fff;padding:18px 24px;font-size:18px;font-weight:600">NC Federal Funds Matchmaker</td></tr>
<tr><td style="padding:22px 24px"><h2 style="margin:0 0 12px;font-size:20px">{title}</h2>{inner}</td></tr>
<tr><td style="padding:14px 24px;background:#f4f6f9;font-size:12px;color:#5a6b7d">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def _result_row(r: dict, agency_id: str) -> str:
    o, s = r["opportunity"], r["signals"]
    e = html.escape
    deadline = "Forecast, not open yet" if s["timing"] == "forecasted" else (
        f"Closes {o['close_date']} ({s['days_left']} days)" if s["days_left"] is not None else "No close date listed")
    urgent = "color:#b42318;font-weight:600" if s["timing"] == "urgent" else "color:#5a6b7d"
    link = f"{config.PUBLIC_BASE_URL}/?agency={agency_id}&opp={o['id']}"
    sample = ' <span style="background:#fff4d6;color:#7a5b00;font-size:11px;padding:1px 6px;border-radius:8px">SAMPLE</span>' if o.get("is_sample") else ""
    return f"""<tr><td style="padding:14px 0;border-top:1px solid #e3e8ef">
<div style="font-size:12px;color:#5a6b7d">{e(o.get('federal_agency') or '')} &middot; Match score <b style="color:#123b68">{r['score']}</b></div>
<a href="{e(link)}" style="font-size:16px;font-weight:600;color:#123b68;text-decoration:none">{e(o['title'])}</a>{sample}
<div style="font-size:13px;margin:4px 0;{urgent}">{e(deadline)} &middot; Up to {money(s['amount'])} &middot; {e(r['grant_type']['competition'])} &middot; {e(r['grant_type']['match'])}</div>
<div style="font-size:14px;line-height:1.45">{e(r['rationale'])}</div></td></tr>"""


def digest_html(sub: dict, data: dict) -> str:
    agency = AGENCY_BY_ID[sub["agency_id"]]
    unsub = f"{config.PUBLIC_BASE_URL}/api/subscriptions/unsubscribe?token={sub['token']}"
    site = f"{config.PUBLIC_BASE_URL}/?agency={agency['id']}"
    urgent = sum(1 for r in data["results"] if r["signals"]["timing"] == "urgent")
    intro = (f"<p style='margin:0 0 6px'>The top {len(data['results'])} federal opportunities for <b>{html.escape(agency['name'])}</b>"
             f"{f', including <b style=color:#b42318>{urgent} closing within 14 days</b>' if urgent else ''}.</p>"
             f"<p style='margin:0 0 8px'><a href='{site}' style='color:#123b68'>Open the full list, and mark Pursue, Save or Dismiss</a></p>")
    rows = "".join(_result_row(r, agency["id"]) for r in data["results"])
    footer = (f"You get this {sub['frequency']} because you subscribed on the Matchmaker site. "
              f"Scores are recommendations; your team decides. <a href='{unsub}' style='color:#5a6b7d'>Unsubscribe</a>")
    return _shell(f"Top grants for {agency['short']}", intro + f"<table width='100%' cellpadding='0' cellspacing='0'>{rows}</table>", footer)


def confirm_html(sub: dict) -> str:
    agency = AGENCY_BY_ID[sub["agency_id"]]
    link = f"{config.PUBLIC_BASE_URL}/api/subscriptions/confirm?token={sub['token']}"
    inner = (f"<p>Click below to start getting the top grants for <b>{html.escape(agency['name'])}</b> {sub['frequency']}.</p>"
             f"<p><a href='{link}' style='display:inline-block;background:#123b68;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none'>Confirm my subscription</a></p>"
             "<p style='font-size:13px;color:#5a6b7d'>If you didn't request this, ignore this email and nothing will be sent.</p>")
    return _shell("Confirm your grant alerts", inner)


# ---------------- subscription lifecycle ----------------
def create_subscription(email: str, agency_id: str, filters: dict, frequency: str, top_n: int) -> dict:
    email = email.strip().lower()
    f = Filters.from_dict({**filters, "agency_id": agency_id, "view": "recommended"}).to_dict()
    with db.session() as conn:
        existing = conn.execute("SELECT * FROM subscriptions WHERE email=? AND agency_id=? AND active=1", (email, agency_id)).fetchone()
        if existing:  # update instead of duplicating
            conn.execute("UPDATE subscriptions SET filters=?, frequency=?, top_n=? WHERE id=?",
                         (json.dumps(f), frequency, top_n, existing["id"]))
            sub_id = existing["id"]
        else:
            if conn.execute("SELECT COUNT(*) FROM subscriptions WHERE email=? AND active=1", (email,)).fetchone()[0] >= 10:
                raise ValueError("This email already has 10 active subscriptions.")
            cur = conn.execute(
                "INSERT INTO subscriptions(email, agency_id, filters, frequency, top_n, token, confirmed) VALUES(?,?,?,?,?,?,?)",
                (email, agency_id, json.dumps(f), frequency, top_n, secrets.token_urlsafe(24),
                 0 if config.REQUIRE_EMAIL_CONFIRMATION else 1))
            sub_id = cur.lastrowid
        sub = db.row_to_dict(conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone())

    result = {"id": sub["id"], "email": email, "frequency": frequency, "confirmed": bool(sub["confirmed"]),
              "email_enabled": config.EMAIL_ENABLED}
    if not sub["confirmed"]:
        result["delivery"] = send(email, "Confirm your NC grant alerts", confirm_html(sub))
        if not config.EMAIL_ENABLED:  # demo mode only: let the presenter click through
            result["dev_confirm_url"] = f"/api/subscriptions/confirm?token={sub['token']}"
    else:
        result["delivery"] = send_digest(sub)
    return result


def confirm(token: str) -> dict | None:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE token=? AND active=1", (token,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE subscriptions SET confirmed=1 WHERE id=?", (row["id"],))
        sub = db.row_to_dict(conn.execute("SELECT * FROM subscriptions WHERE id=?", (row["id"],)).fetchone())
    if not row["confirmed"]:
        send_digest(sub)  # first digest right away so people see value immediately
    return sub


def unsubscribe(token: str) -> bool:
    with db.session() as conn:
        return conn.execute("UPDATE subscriptions SET active=0 WHERE token=?", (token,)).rowcount > 0


def send_digest(sub: dict) -> dict:
    f = Filters.from_dict({**sub["filters"], "agency_id": sub["agency_id"], "view": "recommended", "sort": "score"})
    data = search(f, limit=sub["top_n"], with_llm=True)
    now = datetime.now(timezone.utc)
    result = {"delivered": False, "skipped": "no matches"}
    if data["results"]:
        result = send(sub["email"], f"{len(data['results'])} federal grants for {data['agency']['short']}", digest_html(sub, data))
    with db.session() as conn:
        conn.execute("UPDATE subscriptions SET last_sent_at=?, next_send_at=? WHERE id=?",
                     (now.isoformat(timespec="seconds"), next_send_time(sub["frequency"], now), sub["id"]))
    return result


def send_due_digests() -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.session() as conn:
        due = [db.row_to_dict(r) for r in conn.execute(
            "SELECT * FROM subscriptions WHERE active=1 AND confirmed=1 AND (next_send_at IS NULL OR next_send_at<=?)", (now,))]
    for sub in due:
        try:
            send_digest(sub)
        except Exception:
            log.exception("Digest for subscription %s failed", sub["id"])
    return len(due)


def route_to_team(to: str, agency_id: str, result: dict, note: str, reviewer: str = "") -> dict:
    """'Pursue' hand-off: email the opportunity to the agency's grant-writing team."""
    o, s = result["opportunity"], result["signals"]
    e = html.escape
    inner = (f"<p>{e(reviewer or 'A reviewer')} marked this opportunity <b>Pursue</b> for {e(AGENCY_BY_ID[agency_id]['name'])}.</p>"
             f"<p style='font-size:16px'><b>{e(o['title'])}</b><br>{e(o.get('federal_agency') or '')} &middot; {e(o.get('number') or '')}</p>"
             f"<p>Deadline: {e(o.get('close_date') or 'not listed')} &middot; Up to {money(s['amount'])} &middot; Score {result['score']}</p>"
             f"<p><b>Why it fits:</b> {e(result.get('rationale', ''))}</p>"
             + (f"<p><b>Reviewer note:</b> {e(note)}</p>" if note else "")
             + f"<p><a href='{e(o.get('url') or '')}' style='color:#123b68'>Full announcement</a></p>")
    return send(to, f"[Pursue] {o['title']}", _shell("New grant to pursue", inner))
