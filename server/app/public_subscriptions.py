"""Public opt-in subscriptions, separated from staff-only agency information."""
import json
import secrets
import time
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from . import config, db, emailer, security
from .agencies import AGENCIES, AGENCY_BY_ID
from .search import Filters

router = APIRouter()
ASSETS = Path(__file__).parent / "public"
PUBLIC_PATHS = {
    "/subscribe": {"GET"},
    "/public-signup.js": {"GET"},
    "/api/public/subscription-options": {"GET"},
    "/api/public/subscriptions": {"POST"},
    "/api/public/subscriptions/confirm": {"GET", "POST"},
    "/api/subscriptions/unsubscribe": {"GET", "POST"},
}


def is_public(request: Request):
    return request.method in PUBLIC_PATHS.get(request.url.path, set())


class PublicFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_award: int = Field(config.FINANCIAL_FLOOR, ge=config.FINANCIAL_FLOOR, le=10**12)
    min_score: int = Field(50, ge=0, le=100)
    include_lower_scores: bool = False
    q: str = Field("", max_length=200)
    no_match_only: bool = False
    include_unknown_amount: bool = True
    timing: list[Literal["urgent", "standard", "later", "forecasted"]] = Field(
        default_factory=lambda: ["urgent", "standard", "later", "forecasted"], max_length=4)
    federal_agency: str = Field("", max_length=40)


class PublicSignup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    agency_id: str = Field(max_length=40)
    frequency: str = Field("weekly", pattern="^(daily|weekly|biweekly|monthly)$")
    top_n: int = Field(10, strict=True, ge=1, le=emailer.MAX_DIGEST_GRANTS)
    filters: PublicFilters = Field(default_factory=PublicFilters)
    website: str = Field("", max_length=200)  # Honeypot: humans leave this empty.


@router.get("/subscribe", include_in_schema=False)
def signup_page():
    return FileResponse(ASSETS / "subscribe.html")


@router.get("/public-signup.js", include_in_schema=False)
def signup_script():
    return FileResponse(ASSETS / "signup.js", media_type="application/javascript")


@router.get("/api/public/subscription-options")
def options():
    return {"agencies": [{"id": a["id"], "name": a["name"]} for a in sorted(AGENCIES, key=lambda a: a["name"])],
            "max_digest_grants": emailer.MAX_DIGEST_GRANTS, "financial_floor": config.FINANCIAL_FLOOR}


@router.post("/api/public/subscriptions", status_code=202)
def signup(body: PublicSignup, request: Request):
    security.limit("public-signup-ip", security.client_ip(request), 5, 3600)
    response = {"message": "Check your email for a confirmation link. Changes take effect only after you confirm.",
                "email": body.email.strip().lower(), "top_n": body.top_n, "frequency": body.frequency,
                "confirmed": False, "email_enabled": config.EMAIL_ENABLED}
    if body.website:
        return response
    email = body.email.strip().lower()
    # Public subscriptions deliberately do not use the optional staff domain list.
    if not emailer.EMAIL_RE.fullmatch(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if body.agency_id not in AGENCY_BY_ID:
        raise HTTPException(400, "Choose a valid agency.")
    security.limit("public-signup-email", email, 3, 3600)
    security.limit("public-signup-global", "all", 100, 3600)
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db.session() as conn:
        conn.execute("DELETE FROM public_subscription_requests WHERE expires_at<?", (now,))
        conn.execute("INSERT INTO public_subscription_requests VALUES(?,?,?,?,?,?,?)", (
            token, email, body.agency_id, json.dumps(body.filters.model_dump()), body.frequency, body.top_n, now + 86400,
        ))
    url = f"{config.PUBLIC_BASE_URL}/api/public/subscriptions/confirm?token={quote(token, safe='')}"
    import html
    message = emailer._shell("Confirm your public grant alerts", (
        f"<p>Confirm up to {body.top_n} grants {body.frequency} for "
        f"{html.escape(AGENCY_BY_ID[body.agency_id]['name'])}.</p>"
        f"<p><a href='{html.escape(url)}'>Confirm subscription settings</a></p>"
        "<p>This link expires in 24 hours. If you did not request this, ignore it. "
        "Your existing subscriptions will stay unchanged.</p>"))
    result = emailer.send(email, "Confirm your NC grant alerts", message)
    if result.get("error"):
        raise HTTPException(503, "Unable to send confirmation. Please try again later.")
    # Never return the token or expose subscription state, even in outbox mode.
    return response


def confirmation_page(message: str, action: str = ""):
    import html
    button = f'<form method="post" action="{html.escape(action)}"><button>Confirm subscription</button></form>' if action else ""
    return HTMLResponse(f"<!doctype html><html><head><title>Grant alerts</title></head><body><h1>Grant alerts</h1><p>{message}</p>{button}<a href='/subscribe'>Subscription settings</a></body></html>")


@router.get("/api/public/subscriptions/confirm")
def confirm_page(token: str = ""):
    with db.session() as conn:
        row = conn.execute("SELECT 1 FROM public_subscription_requests WHERE token=? AND expires_at>?", (token, time.time())).fetchone()
    if not row:
        return confirmation_page("This link is invalid or expired. Request a new confirmation.")
    return confirmation_page("Click to confirm your email and subscription settings.", f"/api/public/subscriptions/confirm?token={quote(token, safe='')}")


@router.post("/api/public/subscriptions/confirm")
def confirm(token: str = ""):
    with db.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM public_subscription_requests WHERE token=? AND expires_at>?", (token, time.time())).fetchone()
        if not row:
            return confirmation_page("This link is invalid or expired. Request a new confirmation.")
        existing = conn.execute("SELECT s.id FROM subscriptions s JOIN public_subscriptions p ON p.subscription_id=s.id WHERE s.email=? AND s.agency_id=? AND s.active=1", (row["email"], row["agency_id"])).fetchone()
        if existing:
            sub_id = existing["id"]
            conn.execute("UPDATE subscriptions SET filters=?, frequency=?, top_n=?, next_send_at=? WHERE id=?", (row["filters"], row["frequency"], row["top_n"], emailer.next_send_time("daily"), sub_id))
        else:
            count = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE email=? AND active=1", (row["email"],)).fetchone()[0]
            if count >= 10:
                return confirmation_page("This email already has 10 subscriptions. Unsubscribe from one before adding another.")
            cur = conn.execute("INSERT INTO subscriptions(email,agency_id,filters,frequency,top_n,token,confirmed) VALUES(?,?,?,?,?,?,1)", (row["email"], row["agency_id"], row["filters"], row["frequency"], row["top_n"], secrets.token_urlsafe(32)))
            sub_id = cur.lastrowid
            conn.execute("INSERT INTO public_subscriptions VALUES(?)", (sub_id,))
            conn.execute("UPDATE subscriptions SET next_send_at=? WHERE id=?", (emailer.next_send_time("daily"), sub_id))
        # Invalidate all older pending changes for this address/agency.
        conn.execute("DELETE FROM public_subscription_requests WHERE email=? AND agency_id=?", (row["email"], row["agency_id"]))
        sub = db.row_to_dict(conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone())
    emailer.send_digest(sub)
    return confirmation_page("Your subscription is confirmed. You can unsubscribe using the link in each digest.")
