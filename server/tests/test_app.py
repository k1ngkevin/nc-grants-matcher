from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def top(client, agency, **kw):
    return client.post("/api/search", json={"agency_id": agency, "min_score": 0, **kw}).json()


def test_sample_loaded_and_guardrails_applied(client):
    m = client.get("/api/meta").json()
    assert m["sample_data"] and len(m["agencies"]) >= 25
    titles = [r["opportunity"]["title"] for r in top(client, "deq", limit=200)["results"]]
    assert not any(t.startswith(("EXPIRED", "MICRO-GRANT", "NONPROFIT-ONLY")) for t in titles)


@pytest.mark.parametrize("agency,expected", [
    ("deq", "PFAS"), ("ncdot", "Bridge"), ("dpi", "Mental Health"), ("ports", "Port Infrastructure"),
    ("elections", "Election Security"), ("wildlife", "State Wildlife"), ("ncorr", "Disaster Recovery"),
])
def test_relevant_grant_ranks_first(client, agency, expected):
    assert expected.lower() in top(client, agency)["results"][0]["opportunity"]["title"].lower()


def test_higher_ed_sees_only_university_eligible(client):
    for r in top(client, "unc", limit=200)["results"]:
        assert set(r["opportunity"]["eligibility_codes"]) & {"06", "99", "25"}


def test_score_is_explained(client):
    r = top(client, "dhhs")["results"][0]
    assert 0 <= r["score"] <= 100
    assert set(r["breakdown"]) >= {"semantic", "program", "eligibility", "timing", "size"}
    assert r["rationale"] and r["grant_type"]["competition"]


def test_filters(client):
    res = top(client, "ncdot", timing=["forecasted"])
    assert res["results"] and all(r["signals"]["timing"] == "forecasted" for r in res["results"])
    res = top(client, "ncdot", no_match_only=True)
    assert all(r["opportunity"]["cost_sharing"] != 1 for r in res["results"])
    res = top(client, "ncdot", min_award=50_000_000)
    assert all((r["signals"]["amount"] or 10**12) >= 50_000_000 for r in res["results"])
    assert top(client, "deq", q="pfas")["total"] == 1


def test_project_boosts_match(client):
    before = {r["opportunity"]["id"]: r["score"] for r in top(client, "dncr", limit=200)["results"]}
    client.post("/api/agencies/dncr/projects", json={
        "title": "State Library digitization",
        "description": "Digitize historic newspapers and archives collections at the State Library and expand digital access for libraries."})
    after = top(client, "dncr", limit=200)["results"]
    lib = next(r for r in after if "Librar" in r["opportunity"]["title"])
    assert lib["signals"]["matched_project"]["title"] == "State Library digitization"
    assert lib["score"] >= before[lib["opportunity"]["id"]]


def test_triage_flow_and_feedback(client):
    res = top(client, "dps")
    first, second = res["results"][0]["opportunity"]["id"], res["results"][1]["opportunity"]["id"]
    assert client.post("/api/decisions", json={"agency_id": "dps", "opportunity_id": first, "action": "save"}).status_code == 200
    assert client.post("/api/decisions", json={"agency_id": "dps", "opportunity_id": second, "action": "dismiss"}).status_code == 400  # reason required
    assert client.post("/api/decisions", json={"agency_id": "dps", "opportunity_id": second, "action": "dismiss", "reason": "not_relevant"}).status_code == 200
    counts = top(client, "dps")["counts"]
    assert counts["save"] == 1 and counts["dismiss"] == 1
    client.post("/api/decisions", json={"agency_id": "dps", "opportunity_id": first, "action": "undo"})
    assert top(client, "dps")["counts"]["save"] == 0
    assert client.get("/api/metrics").json()["precision_at_10"]


def test_pursue_routes_email_to_outbox(client):
    oid = top(client, "commerce")["results"][0]["opportunity"]["id"]
    r = client.post("/api/decisions", json={"agency_id": "commerce", "opportunity_id": oid, "action": "pursue",
                                            "route_to": "grants@commerce.nc.gov", "note": "Assign to Sam"}).json()
    assert r["routed"]["outbox_file"]
    assert "Assign to Sam" in (config.OUTBOX_DIR / r["routed"]["outbox_file"]).read_text()


def test_subscription_double_opt_in(client):
    r = client.post("/api/subscriptions", json={"email": "a@agency.nc.gov", "agency_id": "deq", "frequency": "weekly", "top_n": 5}).json()
    assert r["confirmed"] is False and r["dev_confirm_url"]
    page = client.get(r["dev_confirm_url"])
    assert page.status_code == 200 and "subscribed" in page.text
    digests = sorted(Path(config.OUTBOX_DIR).glob("*a_agency_nc_gov.html"))
    assert len(digests) == 2  # confirmation + first digest
    assert "Unsubscribe" in digests[-1].read_text()
    token = r["dev_confirm_url"].split("token=")[1]
    assert "unsubscribed" in client.get(f"/api/subscriptions/unsubscribe?token={token}").text


def test_subscription_validation(client):
    assert client.post("/api/subscriptions", json={"email": "not-an-email", "agency_id": "deq"}).status_code == 400
    assert client.post("/api/subscriptions", json={"email": "a@b.gov", "agency_id": "nope"}).status_code == 404
    assert client.post("/api/subscriptions", json={"email": "a@b.gov", "agency_id": "deq", "frequency": "hourly"}).status_code == 422


def test_due_digests_send(client):
    from app import emailer
    client.post("/api/subscriptions", json={"email": "b@agency.nc.gov", "agency_id": "ncdot", "frequency": "daily"})
    from app import db
    with db.session() as conn:
        conn.execute("UPDATE subscriptions SET confirmed=1, next_send_at='2000-01-01T00:00:00+00:00' WHERE email='b@agency.nc.gov'")
    assert emailer.send_due_digests() >= 1


def test_csv_export(client):
    r = client.post("/api/export.csv", json={"agency_id": "dhhs"})
    assert r.status_code == 200 and r.text.startswith("Score,Title")


def test_security_headers(client):
    r = client.get("/api/meta")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
