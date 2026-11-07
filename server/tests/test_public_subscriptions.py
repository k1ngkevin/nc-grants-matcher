import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import config, db, emailer, security
from app.main import app
from app.search import Filters, search


@pytest.fixture
def public_client(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "development")
    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.delenv("CONTAINER_APP_NAME", raising=False)
    sent = []
    monkeypatch.setattr(emailer, "send", lambda *args: sent.append(args) or {"delivered": True})
    with TestClient(app) as client:
        monkeypatch.setattr(config, "AUTH_MODE", "entra")
        monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", ["gov"])
        yield client, sent


def signup(client, email="public-test@gmail.com", count=2):
    return client.post("/api/public/subscriptions", json={"email": email, "agency_id": "deq", "top_n": count, "filters": {"min_score": 0}})


def pending(email="public-test@gmail.com"):
    with db.session() as conn:
        return dict(conn.execute("SELECT * FROM public_subscription_requests WHERE email=? ORDER BY expires_at DESC LIMIT 1", (email,)).fetchone())


def test_public_page_and_signup_but_staff_api_protected(public_client):
    client, sent = public_client
    assert client.get("/subscribe").status_code == 200
    assert client.get("/public-signup.js").status_code == 200
    assert client.get("/api/public/subscription-options").status_code == 200
    for path in ("/api/meta", "/api/agencies/deq/projects", "/api/metrics"):
        assert client.get(path).status_code == 401
    result = signup(client)
    assert result.status_code == 202
    row = pending()
    assert row["token"] not in result.text
    assert len(sent) == 1 and "Confirm" in sent[0][1]


def test_confirmation_only_on_post_and_public_digest(public_client):
    client, sent = public_client
    assert signup(client, "confirmed-public@gmail.com").status_code == 202
    token = pending("confirmed-public@gmail.com")["token"]
    path = f"/api/public/subscriptions/confirm?token={token}"
    assert client.get(path).status_code == 200
    assert len(sent) == 1
    assert client.post(path).status_code == 200
    assert len(sent) == 2 and sent[-1][2].count("Ranking score") == 2
    assert "mark Pursue" not in sent[-1][2]
    assert client.post(path).status_code == 200 and len(sent) == 2
    with db.session() as conn:
        sub = conn.execute("SELECT * FROM subscriptions WHERE email='confirmed-public@gmail.com'").fetchone()
    assert sub["confirmed"] == 1 and sub["top_n"] == 2
    unsubscribe = f"/api/subscriptions/unsubscribe?token={sub['token']}"
    assert client.get(unsubscribe).status_code == 200
    assert emailer.find_subscription(sub["token"])
    assert client.post(unsubscribe).status_code == 200
    assert emailer.find_subscription(sub["token"]) is None


def test_existing_public_subscription_requires_fresh_confirmation(public_client):
    client, sent = public_client
    email = "update-public@gmail.com"
    signup(client, email, 1)
    client.post(f"/api/public/subscriptions/confirm?token={pending(email)['token']}")
    signup(client, email, 7)
    with db.session() as conn:
        assert conn.execute("SELECT top_n FROM subscriptions WHERE email=?", (email,)).fetchone()[0] == 1
    client.post(f"/api/public/subscriptions/confirm?token={pending(email)['token']}")
    with db.session() as conn:
        rows = conn.execute("SELECT top_n FROM subscriptions WHERE email=?", (email,)).fetchall()
    assert len(rows) == 1 and rows[0][0] == 7


def test_expired_links_do_not_subscribe(public_client):
    client, sent = public_client
    signup(client, "expired-public@gmail.com")
    token = pending("expired-public@gmail.com")["token"]
    with db.session() as conn:
        conn.execute("UPDATE public_subscription_requests SET expires_at=? WHERE token=?", (time.time() - 1, token))
    assert "expired" in client.post(f"/api/public/subscriptions/confirm?token={token}").text
    assert len(sent) == 1


def test_recipient_and_ip_limits(public_client):
    client, sent = public_client
    for _ in range(3):
        assert signup(client, "limited-public@gmail.com").status_code == 202
    response = signup(client, "limited-public@gmail.com")
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert "email address (3 per hour)" in response.json()["detail"]
    assert signup(client, "another-public@gmail.com").status_code == 202
    response = signup(client, "third-public@gmail.com")
    assert response.status_code == 429
    assert "connection (5 attempts per hour)" in response.json()["detail"]
    assert len(sent) == 4


def test_honeypot_and_bad_payloads(public_client):
    client, sent = public_client
    body = {"email": "bot@gmail.com", "agency_id": "deq", "website": "spam"}
    assert client.post("/api/public/subscriptions", json=body).status_code == 202 and not sent
    assert client.post("/api/public/subscriptions", content="x" * 17000, headers={"content-type": "application/json"}).status_code == 413
    assert client.post("/api/public/subscriptions", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/api/public/subscriptions", json={**body, "website": ""}, headers={"origin": "https://evil.example"}).status_code == 403


def test_public_search_never_loads_private_context(public_client, monkeypatch):
    import importlib
    module = importlib.import_module("app.search")

    def fail(*args):
        raise AssertionError("Private agency context must not be read")

    monkeypatch.setattr(module, "load_agency_context", fail)
    result = search(Filters(agency_id="deq", min_score=0), limit=5, public=True)
    assert result["projects"] == []
    assert all(r["decision"] is None and r["signals"]["matched_project"] is None for r in result["results"])


def test_atomic_rate_limit():
    def hit(_):
        try:
            security.limit("concurrency-test", "one-client", 3, 60)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(hit, range(10)))
    assert results.count(200) == 3 and results.count(429) == 7


def test_general_api_limit_covers_invalid_requests(public_client):
    client, _ = public_client
    for _ in range(120):
        assert client.get("/api/public/subscription-options").status_code == 200
    result = client.get("/api/public/subscription-options")
    assert result.status_code == 429 and int(result.headers["retry-after"]) > 0


def test_expensive_api_limit_before_body_validation(public_client):
    client, _ = public_client
    # Validation/authentication failures consume the budget too.
    for _ in range(20):
        assert client.post("/api/search", json={}).status_code == 401
    result = client.post("/api/search", json={})
    assert result.status_code == 429


def test_public_confirmation_mandatory_and_streamed_body_limit(public_client, monkeypatch):
    client, sent = public_client
    monkeypatch.setattr(config, "REQUIRE_EMAIL_CONFIRMATION", False)
    email = "always-confirm-public@gmail.com"
    assert signup(client, email).status_code == 202
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM subscriptions WHERE email=?", (email,)).fetchone()[0] == 0
    assert len(sent) == 1
    chunks = (b"x" * 9000 for _ in range(2))
    assert client.post("/api/public/subscriptions", content=chunks, headers={"content-type": "application/json"}).status_code == 413
    token = pending(email)["token"]
    response = client.get(f"/api/public/subscriptions/confirm?token={token}")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("origin", ["null", "https://mail.google.com", "http://127.0.0.1:8000"])
def test_email_link_actions_allow_foreign_origin_with_valid_token(public_client, origin):
    client, sent = public_client
    email = "origin-confirm-public@gmail.com"
    assert signup(client, email).status_code == 202
    token = pending(email)["token"]
    path = f"/api/public/subscriptions/confirm?token={token}"
    response = client.post(path, headers={"origin": origin})
    assert response.status_code == 200 and "Your subscription is confirmed" in response.text
    assert len(sent) == 2
    # An invalid token does not authorize a state change or additional email.
    response = client.post("/api/public/subscriptions/confirm?token=invalid", headers={"origin": origin})
    assert "invalid or expired" in response.text and len(sent) == 2
    with db.session() as conn:
        sub = conn.execute("SELECT token FROM subscriptions WHERE email=? AND active=1 ORDER BY id DESC", (email,)).fetchone()
    assert sub is not None
    response = client.post(f"/api/subscriptions/unsubscribe?token={sub['token']}",
                           data={"List-Unsubscribe": "One-Click"}, headers={"origin": origin})
    assert response.status_code == 200 and emailer.find_subscription(sub["token"]) is None


def test_foreign_origin_signup_still_rejected(public_client):
    client, sent = public_client
    response = client.post("/api/public/subscriptions", json={"email": "cross-origin@gmail.com", "agency_id": "deq"},
                           headers={"origin": "null"})
    assert response.status_code == 403 and not sent
