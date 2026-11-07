"""SQLite-backed limits shared by workers using this application's database."""
import hashlib
import math
import time

from fastapi import HTTPException, Request

from . import db

LIMIT_MESSAGES = {
    "public-signup-ip": "Subscription signup limit reached for this connection (5 attempts per hour).",
    "public-signup-email": "Confirmation email limit reached for this email address (3 per hour).",
    "public-signup-global": "The service's hourly confirmation email limit has been reached.",
    "expensive-api": "Search and preview limit reached (20 requests per minute).",
    "test_digest": "Test email limit reached for this connection (5 per hour).",
    "test-recipient": "Test email limit reached for this email address (3 per hour).",
    "test-global": "The service's hourly test email limit has been reached.",
}


def subject_key(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def limit(bucket: str, subject: str, maximum: int, seconds: int):
    now = time.time()
    blocked = False
    retry = seconds
    with db.session() as conn:
        # Serialize count + insert so concurrent requests cannot exceed a quota.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM api_rate_events WHERE created_at<?", (now - 86400,))
        count, oldest = conn.execute(
            "SELECT COUNT(*), MIN(created_at) FROM api_rate_events WHERE bucket=? AND subject=? AND created_at>?",
            (bucket, subject_key(subject), now - seconds),
        ).fetchone()
        if count >= maximum:
            blocked = True
            retry = max(1, math.ceil(oldest + seconds - now))
        else:
            conn.execute("INSERT INTO api_rate_events VALUES(?,?,?)", (bucket, subject_key(subject), now))
    if blocked:
        message = LIMIT_MESSAGES.get(bucket, "Too many API requests.")
        raise HTTPException(429, message, headers={"Retry-After": str(retry)})


def client_ip(request: Request) -> str:
    # Use the ASGI peer address. Do not read arbitrary X-Forwarded-For headers.
    # Only a configured, trusted Uvicorn proxy may rewrite the peer address.
    return request.client.host if request.client else "unknown"
