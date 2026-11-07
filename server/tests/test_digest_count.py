import html
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config, db, emailer
from app.main import app, _hits
from app.search import Filters, search


@pytest.fixture
def client():
    _hits.clear()
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("address,allowed", [
    ("worker@nc.gov", True), ("worker@deq.nc.gov", True),
    ("staff@unc.edu", True), ("staff@dept.unc.edu", True),
    ("test@gmail.com", False), ("test@fakegov.com", False),
    ("test@unc.edu.attacker.com", False),
])
def test_education_and_government_recipients(monkeypatch, address, allowed):
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", ["edu", "gov"])
    assert (emailer.valid_email(address) is None) == allowed


@pytest.mark.parametrize("count", [1, 7, 100])
def test_preview_uses_custom_count_and_score_order(client, count):
    filters = {"min_score": 0, "sort": "amount"}
    response = client.post("/api/subscriptions/preview", json={
        "agency_id": "deq", "email": "preview@nc.gov", "top_n": count, "filters": filters,
    })
    assert response.status_code == 200
    expected = search(Filters.from_dict({**filters, "agency_id": "deq", "sort": "score"}), limit=count)
    assert response.text.count("Ranking score") == len(expected["results"])
    positions = [response.text.index(html.escape(r["opportunity"]["title"])) for r in expected["results"]]
    assert positions == sorted(positions)
    assert f"requested up to {count} grants" in response.text
    if len(expected["results"]) < count:
        assert f"Only {len(expected['results'])} grants" in response.text


@pytest.mark.parametrize("count", [0, -1, 101, 2.5, True, "7"])
def test_invalid_counts_rejected_by_signup_and_preview(client, count):
    body = {"agency_id": "deq", "email": "count@nc.gov", "top_n": count}
    for path in ("/api/subscriptions", "/api/subscriptions/preview"):
        assert client.post(path, json=body).status_code == 422


def test_updated_count_used_by_scheduled_delivery(client, monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_EMAIL_CONFIRMATION", False)
    sent = []

    def capture(to, subject, body, headers=None):
        sent.append(body)
        return {"delivered": True}

    monkeypatch.setattr(emailer, "send", capture)
    body = {"agency_id": "deq", "email": "custom-digest@nc.gov", "top_n": 1,
            "filters": {"min_score": 0, "sort": "amount"}}
    first = client.post("/api/subscriptions", json=body).json()
    assert first["top_n"] == 1
    assert sent[-1].count("Ranking score") == 1
    updated = client.post("/api/subscriptions", json={**body, "top_n": 2}).json()
    assert updated["id"] == first["id"] and updated["top_n"] == 2
    with db.session() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (first["id"],)).fetchone()
        assert row["top_n"] == 2
        conn.execute("UPDATE subscriptions SET next_send_at='2000-01-01T00:00:00+00:00' WHERE id=?", (first["id"],))
    emailer.send_due_digests()
    expected = search(Filters.from_dict({"agency_id": "deq", "min_score": 0}), limit=2)
    assert len(expected["results"]) == 2
    digest = next(message for message in reversed(sent) if "requested up to 2 grants" in message)
    assert digest.count("Ranking score") == 2
    assert digest.index(html.escape(expected["results"][0]["opportunity"]["title"])) < digest.index(html.escape(expected["results"][1]["opportunity"]["title"]))


def test_test_email_uses_outbox_without_subscribing(client):
    with db.session() as conn:
        before = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
    response = client.post("/api/subscriptions/test", json={
        "email": "local-test@gmail.com", "agency_id": "deq", "top_n": 2, "filters": {"min_score": 0},
    })
    assert response.status_code == 200
    result = response.json()
    assert result["grant_count"] == 2 and result["delivery"]["delivered"] is False
    message = (config.OUTBOX_DIR / result["delivery"]["outbox_file"]).read_text(encoding="utf-8")
    assert message.count("Ranking score") == 2
    assert "one-time test" in message and "Unsubscribe" not in message
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == before


def test_test_email_transport_failure_reported(client, monkeypatch):
    monkeypatch.setattr(emailer, "send", lambda *args: {"delivered": False, "error": "failed"})
    response = client.post("/api/subscriptions/test", json={"email": "fail@gmail.com", "agency_id": "deq", "top_n": 5})
    assert response.status_code == 503


def test_daily_confirmation_schedules_next_day(client, monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_EMAIL_CONFIRMATION", True)
    monkeypatch.setattr(emailer, "send", lambda *args: {"delivered": True})
    response = client.post("/api/subscriptions", json={
        "email": "daily-count@nc.gov", "agency_id": "deq", "top_n": 2, "frequency": "daily", "filters": {"min_score": 0},
    })
    assert response.status_code == 200 and response.json()["frequency"] == "daily"
    with db.session() as conn:
        token = conn.execute("SELECT token FROM subscriptions WHERE id=?", (response.json()["id"],)).fetchone()[0]
    assert client.post(f"/api/subscriptions/confirm?token={token}").status_code == 200
    sub = emailer.find_subscription(token)
    last = datetime.fromisoformat(sub["last_sent_at"])
    next_send = datetime.fromisoformat(sub["next_send_at"])
    assert next_send.date() == (last + timedelta(days=1)).date()
    assert next_send.hour == 12 and next_send.tzinfo == timezone.utc
