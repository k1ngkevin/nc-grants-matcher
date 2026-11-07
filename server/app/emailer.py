"""Email: confirmation, scheduled "top grants" digests, and Pursue hand-offs.

Three ways out, picked from settings:
  * ACS_CONNECTION_STRING: Azure Communication Services' email API, signed with the
    resource's access key. No SMTP username needed.
  * SMTP_HOST: any SMTP server (SendGrid, ACS SMTP, an agency relay).
  * Neither: each message is written to data/outbox/ as an .html file so the demo still
    works and nothing leaves the machine.

Check the settings with:  python -m app.emailer you@agency.nc.gov
"""
import base64
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, parseaddr
from urllib.parse import quote, urlparse

import requests

from . import config, db
from .agencies import AGENCY_BY_ID
from .matching.explain import money
from .search import Filters, search

log = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FREQUENCIES = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}
MAX_DIGEST_GRANTS = 100
SEND_HOUR_UTC = 12  # ~8am Eastern
RETRY_AFTER = timedelta(hours=1)  # when a digest fails to send
# Python folds headers at 78 characters and RFC 2047-encodes long URLs to do it, which
# breaks List-Unsubscribe. 998 is the real line limit in RFC 5322.
MAIL_POLICY = policy.default.clone(max_line_length=998)
ACS_API_VERSION = "2025-09-01"  # the version azure-communication-email 1.1.0 uses


class EmailError(Exception):
    """The mail service refused the message, or the email settings are unusable."""


def valid_email(email: str) -> str | None:
    """Return an error message, or None if the address is acceptable."""
    if not EMAIL_RE.match(email or "") or len(email) > 254:
        return "Please enter a valid email address."
    domain = email.rsplit("@", 1)[1].lower()
    if config.ALLOWED_EMAIL_DOMAINS and not any(domain == d or domain.endswith("." + d) for d in config.ALLOWED_EMAIL_DOMAINS):
        return f"Only these email domains can subscribe: {', '.join(config.ALLOWED_EMAIL_DOMAINS)}."
    return None


def config_problems() -> list[str]:
    """Settings that will make real email misbehave. Empty when email is off (outbox mode)."""
    if not config.EMAIL_ENABLED:
        return []
    problems = []
    if config.ACS_CONNECTION_STRING:
        try:
            _acs_credentials()
        except EmailError as e:
            problems.append(str(e))
    if urlparse(config.PUBLIC_BASE_URL).hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        problems.append(f"PUBLIC_BASE_URL is {config.PUBLIC_BASE_URL}, so links in emails only work on this computer. "
                        "Set it to the site's public address.")
    if "@example." in config.SMTP_FROM.lower():
        problems.append(f"SMTP_FROM is a placeholder ({config.SMTP_FROM}). Use an address your mail service is allowed "
                        "to send from, or messages will bounce or land in spam.")
    return problems


def describe_backend() -> str:
    if config.ACS_CONNECTION_STRING:
        try:
            host = urlparse(_acs_credentials()[0]).netloc
        except EmailError:
            host = "connection string not valid"
        return f"Azure Communication Services email API ({host})"
    if config.SMTP_HOST:
        security = "SSL" if config.SMTP_PORT == 465 else ("STARTTLS" if config.SMTP_STARTTLS else "no encryption")
        return f"SMTP {config.SMTP_HOST}:{config.SMTP_PORT} ({security}), login: {config.SMTP_USER or '(none)'}"
    return "nothing (emails are saved to the outbox folder)"


def _plain(html_body: str) -> str:
    return re.sub(r"<[^>]+>", "", html_body)


def _message(to: str, subject: str, html_body: str, headers: dict | None = None) -> EmailMessage:
    msg = EmailMessage(policy=MAIL_POLICY)
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
    for name, value in (headers or {}).items():
        msg[name] = value
    msg.set_content(_plain(html_body))
    msg.add_alternative(html_body, subtype="html")
    return msg


# ---------------- Azure Communication Services email API ----------------
def _acs_credentials() -> tuple[str, bytes]:
    """(endpoint, decoded access key) from 'endpoint=https://...;accesskey=...'."""
    parts = {}
    for piece in config.ACS_CONNECTION_STRING.split(";"):
        if "=" in piece:
            name, value = piece.split("=", 1)  # the key itself can end in '='
            parts[name.strip().lower()] = value.strip()
    endpoint = parts.get("endpoint", "").rstrip("/")
    if not endpoint.startswith("https://") or not parts.get("accesskey"):
        raise EmailError("ACS_CONNECTION_STRING should look like "
                         "endpoint=https://<name>.communication.azure.com/;accesskey=<key>. Copy it again from the Keys page.")
    try:
        return endpoint, base64.b64decode(parts["accesskey"], validate=True)
    except ValueError:
        raise EmailError("The accesskey in ACS_CONNECTION_STRING isn't valid. Copy the connection string again from the Keys page.")


def _acs_auth_headers(url: str, body: bytes, secret: bytes, date: str) -> dict:
    """HMAC-SHA256 request signing, as in Microsoft's 'Sign an HTTP request' tutorial."""
    u = urlparse(url)
    content_hash = base64.b64encode(hashlib.sha256(body).digest()).decode()
    to_sign = f"POST\n{u.path}?{u.query}\n{date};{u.netloc};{content_hash}"
    signature = base64.b64encode(hmac.digest(secret, to_sign.encode(), hashlib.sha256)).decode()
    return {"x-ms-date": date, "x-ms-content-sha256": content_hash,
            "Authorization": f"HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature={signature}"}


def _acs_send(to: str, subject: str, html_body: str, headers: dict | None = None) -> None:
    """Queue one message with ACS. Raises EmailError, or OSError for network problems."""
    endpoint, secret = _acs_credentials()
    url = f"{endpoint}/emails:send?api-version={ACS_API_VERSION}"
    body = json.dumps({
        "senderAddress": parseaddr(config.SMTP_FROM)[1],  # ACS takes the bare address
        "recipients": {"to": [{"address": to}]},
        "content": {"subject": subject, "plainText": _plain(html_body), "html": html_body},
        "headers": headers or {},
        "userEngagementTrackingDisabled": True,  # no tracking pixel, no rewritten links
    }).encode()
    r = requests.post(url, data=body, timeout=30, headers={
        "Content-Type": "application/json", **_acs_auth_headers(url, body, secret, formatdate(usegmt=True))})
    if r.status_code // 100 != 2:
        try:
            detail = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = r.text[:300]
        raise EmailError(f"Azure returned {r.status_code}: {detail}")


def _deliver(to: str, subject: str, html_body: str, headers: dict | None = None) -> None:
    """Hand one message to the configured mail service. Raises on failure."""
    if config.ACS_CONNECTION_STRING:
        _acs_send(to, subject, html_body, headers)
    else:
        _smtp_send(_message(to, subject, html_body, headers))


def _smtp_send(msg: EmailMessage) -> None:
    """Deliver over SMTP. Raises smtplib.SMTPException or OSError on failure."""
    implicit_tls = config.SMTP_PORT == 465
    smtp_class = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
    with smtp_class(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        if config.SMTP_STARTTLS and not implicit_tls:
            s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)


def send(to: str, subject: str, html_body: str, headers: dict | None = None) -> dict:
    """Send one message. A mail-server problem doesn't raise: it's logged and returned as
    {"delivered": False, "error": ...} so the caller can still save its own work."""
    if config.EMAIL_ENABLED:
        try:
            _deliver(to, subject, html_body, headers)
        except (smtplib.SMTPException, OSError, EmailError):
            log.exception("Could not send '%s' to %s through %s", subject, to, describe_backend())
            return {"delivered": False, "error": "The email could not be sent."}
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


def _result_row(r: dict, agency_id: str, public: bool = False) -> str:
    o, s = r["opportunity"], r["signals"]
    e = html.escape
    deadline = "Forecast, not open yet" if s["timing"] == "forecasted" else (
        f"Closes {o['close_date']} ({s['days_left']} days)" if s["days_left"] is not None else "No close date listed")
    urgent = "color:#b42318;font-weight:600" if s["timing"] == "urgent" else "color:#5a6b7d"
    link = f"{config.PUBLIC_BASE_URL}/?agency={agency_id}&opp={o['id']}"
    if public:
        candidate = o.get("url") or ""
        link = candidate if urlparse(candidate).scheme in {"https", "http"} else f"{config.PUBLIC_BASE_URL}/subscribe"
    sample = ' <span style="background:#fff4d6;color:#7a5b00;font-size:11px;padding:1px 6px;border-radius:8px">SAMPLE</span>' if o.get("is_sample") else ""
    return f"""<tr><td style="padding:14px 0;border-top:1px solid #e3e8ef">
<div style="font-size:12px;color:#5a6b7d">{e(o.get('federal_agency') or '')} &middot; Ranking score <b style="color:#123b68">{r['score']}</b></div>
<a href="{e(link)}" style="font-size:16px;font-weight:600;color:#123b68;text-decoration:none">{e(o['title'])}</a>{sample}
<div style="font-size:13px;margin:4px 0;{urgent}">{e(deadline)} &middot; Up to {money(s['amount'])} &middot; {e(r['grant_type']['competition'])} &middot; {e(r['grant_type']['match'])}</div>
<div style="font-size:14px;line-height:1.45">{e(r['rationale'])}</div></td></tr>"""


def unsubscribe_url(sub: dict) -> str:
    return f"{config.PUBLIC_BASE_URL}/api/subscriptions/unsubscribe?token={quote(sub['token'], safe='')}"


def digest_html(sub: dict, data: dict) -> str:
    agency = AGENCY_BY_ID[sub["agency_id"]]
    unsub = unsubscribe_url(sub)
    site = f"{config.PUBLIC_BASE_URL}/?agency={agency['id']}"
    urgent = sum(1 for r in data["results"] if r["signals"]["timing"] == "urgent")
    intro = (f"<p style='margin:0 0 6px'>The top {len(data['results'])} federal opportunities for <b>{html.escape(agency['name'])}</b>"
             f"{f', including <b style=color:#b42318>{urgent} closing within 14 days</b>' if urgent else ''}.</p>"
             f"<p style='margin:0 0 8px'><a href='{site}' style='color:#123b68'>Open the full list, and mark Pursue, Save or Dismiss</a></p>")
    requested = sub.get("top_n", len(data["results"]))
    intro += f"<p>You requested up to {requested} grants, ranked by match score using your saved filters.</p>"
    if len(data["results"]) < requested:
        intro += f"<p>Only {len(data['results'])} grants currently match your filters.</p>"
    if sub.get("public"):
        intro = intro.replace(f"{site}", f"{config.PUBLIC_BASE_URL}/subscribe").replace("Open the full list, and mark Pursue, Save or Dismiss", "Update your public subscription preferences")
    rows = "".join(_result_row(r, agency["id"], public=sub.get("public", False)) for r in data["results"])
    footer = (f"You get this {sub['frequency']} because you subscribed on the Matchmaker site. "
              f"Scores are recommendations; your team decides. <a href='{unsub}' style='color:#5a6b7d'>Unsubscribe</a>")
    if sub.get("test"):
        footer = "This is a one-time test of your selected grants. No subscription was created or changed. Scores are recommendations; your team decides."
    return _shell(f"Top grants for {agency['short']}", intro + f"<table width='100%' cellpadding='0' cellspacing='0'>{rows}</table>", footer)


def send_test_digest(email: str, agency_id: str, filters: dict, top_n: int) -> dict:
    """Use the real digest renderer and transport without changing subscriptions."""
    f = Filters.from_dict({**filters, "agency_id": agency_id, "view": "recommended", "sort": "score"})
    data = search(f, limit=top_n, public=True)
    sub = {"agency_id": agency_id, "top_n": top_n, "frequency": "once", "token": "test", "test": True, "public": True}
    delivery = send(email, f"[Test] {len(data['results'])} federal grants for {data['agency']['short']}", digest_html(sub, data))
    return {"email": email, "top_n": top_n, "grant_count": len(data["results"]),
            "email_enabled": config.EMAIL_ENABLED, "delivery": delivery}


def confirm_html(sub: dict) -> str:
    agency = AGENCY_BY_ID[sub["agency_id"]]
    link = f"{config.PUBLIC_BASE_URL}/api/subscriptions/confirm?token={quote(sub['token'], safe='')}"
    inner = (f"<p>Click below to start getting up to {sub['top_n']} top grants for <b>{html.escape(agency['name'])}</b> {sub['frequency']}.</p>"
             f"<p><a href='{link}' style='display:inline-block;background:#123b68;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none'>Confirm my subscription</a></p>"
             "<p style='font-size:13px;color:#5a6b7d'>If you didn't request this, ignore this email and nothing will be sent.</p>")
    return _shell("Confirm your grant alerts", inner)


# ---------------- subscription lifecycle ----------------
def create_subscription(email: str, agency_id: str, filters: dict, frequency: str, top_n: int) -> dict:
    if type(top_n) is not int or not 1 <= top_n <= MAX_DIGEST_GRANTS:
        raise ValueError(f"Choose a whole number of grants from 1 to {MAX_DIGEST_GRANTS}.")
    email = email.strip().lower()
    f = Filters.from_dict({**filters, "agency_id": agency_id, "view": "recommended", "sort": "score"}).to_dict()
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

    result = {"id": sub["id"], "email": email, "frequency": frequency, "top_n": sub["top_n"], "confirmed": bool(sub["confirmed"]),
              "email_enabled": config.EMAIL_ENABLED}
    if not sub["confirmed"]:
        result["delivery"] = send(email, "Confirm your NC grant alerts", confirm_html(sub))
        if not config.EMAIL_ENABLED:  # demo mode only: let the presenter click through
            result["dev_confirm_url"] = f"/api/subscriptions/confirm?token={sub['token']}"
    else:
        result["delivery"] = send_digest(sub)
    return result


def find_subscription(token: str) -> dict | None:
    """Look up an active subscription by its link token without changing anything."""
    with db.session() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE token=? AND active=1", (token,)).fetchone()
    return db.row_to_dict(row) if row else None


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
    with db.session() as conn:
        public = conn.execute("SELECT 1 FROM public_subscriptions WHERE subscription_id=?", (sub["id"],)).fetchone() is not None
    sub = {**sub, "public": public}
    f = Filters.from_dict({**sub["filters"], "agency_id": sub["agency_id"], "view": "recommended", "sort": "score"})
    data = search(f, limit=sub["top_n"], with_llm=not public, public=public)
    now = datetime.now(timezone.utc)
    result = {"delivered": False, "skipped": "no matches"}
    if data["results"]:
        # List-Unsubscribe lets Gmail/Outlook show their own one-click unsubscribe button (RFC 8058).
        headers = {"List-Unsubscribe": f"<{unsubscribe_url(sub)}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
        result = send(sub["email"], f"{len(data['results'])} federal grants for {data['agency']['short']}",
                      digest_html(sub, data), headers)
    with db.session() as conn:
        if result.get("error"):  # retry soon instead of silently skipping a whole period
            conn.execute("UPDATE subscriptions SET next_send_at=? WHERE id=?",
                         ((now + RETRY_AFTER).isoformat(timespec="seconds"), sub["id"]))
        else:
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
             f"<p><b>Match preview:</b> {e(result.get('rationale', ''))}</p>"
             + (f"<p><b>Reviewer note:</b> {e(note)}</p>" if note else "")
             + f"<p><a href='{e(o.get('url') or '')}' style='color:#123b68'>Full announcement</a></p>")
    return send(to, f"[Pursue] {o['title']}", _shell("New grant to pursue", inner))


# ---------------- setup check:  python -m app.emailer you@agency.nc.gov ----------------
def _main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python -m app.emailer you@agency.nc.gov")
        return 2
    if not config.EMAIL_ENABLED:
        where = f"the environment or {config.ENV_FILE}" if config.ENV_FILE else "the environment"
        print(f"Neither ACS_CONNECTION_STRING nor SMTP_HOST is set in {where}, "
              f"so emails are only written to {config.OUTBOX_DIR}.")
        return 1
    print(f"Sending through: {describe_backend()}\nFrom: {config.SMTP_FROM}")
    for p in config_problems():
        print(f"Warning: {p}")
    body = _shell("Test email", "<p>If you can read this, the Matchmaker can send email.</p>")
    try:
        _deliver(argv[0], "NC Federal Funds Matchmaker test email", body)
    except (smtplib.SMTPException, OSError, EmailError) as e:
        print(f"Failed: {type(e).__name__}: {e}")
        return 1
    print(f"Sent to {argv[0]}. Check that inbox, and the spam folder if it's not there.")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
