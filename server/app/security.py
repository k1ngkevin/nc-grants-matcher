"""SQLite-backed limits shared by workers using this application's database."""
import hashlib
import math
import time

from fastapi import HTTPException, Request

from . import db


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
        raise HTTPException(429, "Too many requests. Please try again later.", headers={"Retry-After": str(retry)})


def client_ip(request: Request) -> str:
    # Use the ASGI peer address. Do not read arbitrary X-Forwarded-For headers.
    # Only a configured, trusted Uvicorn proxy may rewrite the peer address.
    return request.client.host if request.client else "unknown"
