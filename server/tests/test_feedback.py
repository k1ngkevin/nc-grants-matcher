"""Feedback from the site: saved, validated, optionally emailed, readable by admins only."""
import pytest
from fastapi.testclient import TestClient

from app import config, db
from app import main
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _opp_id():
    with db.session() as conn:
        return conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]


def test_feedback_is_saved_with_its_context(client):
    opp = _opp_id()
    r = client.post("/api/feedback", json={"kind": "scoring", "message": "This scored high but we can't apply.",
                                           "email": "pat@agency.nc.gov", "agency_id": "deq", "opportunity_id": opp,
                                           "page": "recommended"})
    assert r.status_code == 200 and r.json()["ok"]
    with db.session() as conn:
        row = dict(conn.execute("SELECT * FROM feedback WHERE id=?", (r.json()["id"],)).fetchone())
    assert row["kind"] == "scoring" and row["agency_id"] == "deq" and row["opportunity_id"] == opp
    assert row["email"] == "pat@agency.nc.gov"


@pytest.mark.parametrize("body,status", [
    ({"kind": "idea", "message": "hi"}, 422),                                   # too short
    ({"kind": "complaint", "message": "Not a real kind of feedback"}, 422),
    ({"kind": "idea", "message": "A fine idea here", "email": "not-an-email"}, 400),
    ({"kind": "idea", "message": "A fine idea here", "agency_id": "nope"}, 400),
])
def test_feedback_validation(client, body, status):
    assert client.post("/api/feedback", json=body).status_code == status


def test_feedback_email_and_admin_list(client, monkeypatch):
    sent = []
    monkeypatch.setattr(config, "FEEDBACK_EMAIL", "team@example.gov")
    monkeypatch.setattr(main.emailer, "send", lambda to, subject, body, headers=None: sent.append((to, subject, body)))
    monkeypatch.setattr(main.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    r = client.post("/api/feedback", json={"kind": "problem", "message": "The <b>filters</b> reset on reload.", "agency_id": "dit"})
    assert r.status_code == 200
    to, subject, body = sent[0]
    assert to == "team@example.gov" and "Something's wrong" in subject and "Department of Information Technology" in subject
    assert "&lt;b&gt;filters&lt;/b&gt;" in body                                  # message is escaped

    assert client.get("/api/admin/feedback").status_code == 403
    monkeypatch.setattr(main, "ADMIN_TOKEN", "secret")
    rows = client.get("/api/admin/feedback", headers={"X-Admin-Token": "secret"}).json()
    assert rows[0]["message"] == "The <b>filters</b> reset on reload." and rows[0]["agency_id"] == "dit"
