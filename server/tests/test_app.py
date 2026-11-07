import base64
import json
import os
import smtplib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
    page = client.get(r["dev_confirm_url"])  # what a mail scanner opening the link does
    assert page.status_code == 200 and "Confirm my subscription" in page.text
    assert len(list(Path(config.OUTBOX_DIR).glob("*a_agency_nc_gov.html"))) == 1  # not confirmed yet
    page = client.post(r["dev_confirm_url"])  # the person clicks the button
    assert page.status_code == 200 and "re subscribed" in page.text
    digests = sorted(Path(config.OUTBOX_DIR).glob("*a_agency_nc_gov.html"))
    assert len(digests) == 2  # confirmation + first digest
    assert "Unsubscribe" in digests[-1].read_text()
    token = r["dev_confirm_url"].split("token=")[1]
    from app import emailer
    assert "Unsubscribe?" in client.get(f"/api/subscriptions/unsubscribe?token={token}").text
    assert emailer.find_subscription(token)  # opening the link alone changes nothing
    assert "unsubscribed" in client.post(f"/api/subscriptions/unsubscribe?token={token}").text
    assert emailer.find_subscription(token) is None


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


# ---------------- real SMTP path (with a fake mail server) ----------------
@pytest.fixture
def smtp(monkeypatch):
    """Turn real email on and swap smtplib.SMTP for a fake that records or refuses messages."""
    class FakeSMTP:
        sent, fail = [], False

        def __init__(self, host, port, timeout=None):
            if FakeSMTP.fail:
                raise ConnectionRefusedError(61, "Connection refused")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            FakeSMTP.sent.append(msg)

    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def _token(email):
    from app import db
    with db.session() as conn:
        return conn.execute("SELECT token FROM subscriptions WHERE email=? ORDER BY id DESC", (email,)).fetchone()[0]


def test_smtp_delivery_with_one_click_unsubscribe(client, smtp):
    r = client.post("/api/subscriptions", json={"email": "c@agency.nc.gov", "agency_id": "dhhs", "top_n": 5}).json()
    assert r["delivery"] == {"delivered": True} and "dev_confirm_url" not in r
    assert smtp.sent[-1]["Subject"] == "Confirm your NC grant alerts"
    token = _token("c@agency.nc.gov")
    client.post(f"/api/subscriptions/confirm?token={token}")
    digest = smtp.sent[-1]
    assert digest["To"] == "c@agency.nc.gov" and token in digest["List-Unsubscribe"]
    assert digest["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    # As sent on the wire: a plain URL that mail apps can read, not an =?utf-8?q?...?= encoded word.
    assert f"List-Unsubscribe: <{config.PUBLIC_BASE_URL}/api/subscriptions/unsubscribe?token={token}>" in digest.as_string()
    # A mail app's one-click unsubscribe POSTs to that URL with this form body.
    r = client.post(f"/api/subscriptions/unsubscribe?token={token}", data={"List-Unsubscribe": "One-Click"})
    assert r.status_code == 200
    from app import emailer
    assert emailer.find_subscription(token) is None


def test_mail_server_down_does_not_lose_work(client, smtp):
    from app import db, emailer
    smtp.fail = True
    r = client.post("/api/subscriptions", json={"email": "d@agency.nc.gov", "agency_id": "deq"})
    assert r.status_code == 503 and "try again" in r.json()["detail"]

    oid = top(client, "deq")["results"][0]["opportunity"]["id"]
    r = client.post("/api/decisions", json={"agency_id": "deq", "opportunity_id": oid, "action": "pursue", "route_to": "team@deq.nc.gov"})
    assert r.status_code == 200 and r.json()["routed"]["error"]
    with db.session() as conn:  # the Pursue decision is still saved
        assert conn.execute("SELECT action FROM decisions WHERE opportunity_id=? ORDER BY id DESC", (oid,)).fetchone()[0] == "pursue"

    # A digest that fails is retried within the hour instead of skipping a whole period.
    with db.session() as conn:
        conn.execute("UPDATE subscriptions SET confirmed=1, next_send_at='2000-01-01T00:00:00+00:00' WHERE email='d@agency.nc.gov'")
    emailer.send_due_digests()
    with db.session() as conn:
        last, nxt = conn.execute("SELECT last_sent_at, next_send_at FROM subscriptions WHERE email='d@agency.nc.gov'").fetchone()
    assert last is None and datetime.fromisoformat(nxt) < datetime.now(timezone.utc) + timedelta(hours=2)


# ---------------- Azure Communication Services email API ----------------
ACS_KEY = base64.b64encode(b"k" * 64).decode()


def test_acs_signature_matches_official_sdk():
    """Reference values captured from Microsoft's azure-communication-email 1.1.0 for the same request."""
    from app import emailer
    url = "https://demo-acs.unitedstates.communication.azure.com/emails:send?api-version=2025-09-01"
    body = ('{"senderAddress": "DoNotReply@abc.azurecomm.net", "recipients": {"to": [{"address": "x@agency.nc.gov"}]}, '
            '"content": {"subject": "Hi", "plainText": "text", "html": "<p>html</p>"}, "headers": {"List-Unsubscribe": '
            '"<https://site/u?token=t>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}, "userEngagementTrackingDisabled": true}')
    headers = emailer._acs_auth_headers(url, body.encode(), base64.b64decode(ACS_KEY), "Sat, 07 Nov 2026 03:23:42 GMT")
    assert headers["x-ms-content-sha256"] == "3GhDeuc84T4rW8Cvljk7v5Pwr1WTYnAvh5nmbewNupQ="
    assert headers["Authorization"] == ("HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256"
                                        "&Signature=ZerWElFrVemVDAp7T/63YxkILmeQoz6u76cAoR/MBtQ=")


@pytest.fixture
def acs(monkeypatch):
    """Turn on the ACS email API and record requests instead of sending them."""
    from app import emailer

    class Fake:
        calls, status, payload = [], 202, {"id": "op1", "status": "Running"}

        def post(self, url, data=None, headers=None, timeout=None):
            Fake.calls.append({"url": url, "body": json.loads(data), "headers": headers})
            return SimpleNamespace(status_code=Fake.status, json=lambda: Fake.payload, text=json.dumps(Fake.payload))

    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "ACS_CONNECTION_STRING", f"endpoint=https://demo.communication.azure.com/;accesskey={ACS_KEY}")
    monkeypatch.setattr(config, "SMTP_FROM", "NC Matchmaker <DoNotReply@abc.azurecomm.net>")
    monkeypatch.setattr(emailer.requests, "post", Fake().post)
    return Fake


def test_acs_sends_through_email_api(client, acs):
    oid = top(client, "dhhs")["results"][0]["opportunity"]["id"]
    r = client.post("/api/decisions", json={"agency_id": "dhhs", "opportunity_id": oid, "action": "pursue",
                                            "route_to": "team@dhhs.nc.gov", "note": "Look at this"}).json()
    assert r["routed"] == {"delivered": True}
    call = acs.calls[-1]
    assert call["url"] == "https://demo.communication.azure.com/emails:send?api-version=2025-09-01"
    assert call["body"]["senderAddress"] == "DoNotReply@abc.azurecomm.net"  # display name stripped
    assert call["body"]["recipients"] == {"to": [{"address": "team@dhhs.nc.gov"}]}
    assert "Look at this" in call["body"]["content"]["html"] and call["body"]["userEngagementTrackingDisabled"] is True
    assert call["headers"]["Authorization"].startswith("HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature=")


def test_acs_rejection_and_bad_settings_do_not_crash(acs, monkeypatch):
    from app import emailer
    acs.status, acs.payload = 401, {"error": {"code": "Denied", "message": "Denied by the resource provider."}}
    assert emailer.send("a@agency.nc.gov", "Hi", "<p>x</p>") == {"delivered": False, "error": "The email could not be sent."}
    with pytest.raises(emailer.EmailError, match="Denied by the resource provider"):
        emailer._deliver("a@agency.nc.gov", "Hi", "<p>x</p>")
    monkeypatch.setattr(config, "ACS_CONNECTION_STRING", "not a connection string")
    assert emailer.send("a@agency.nc.gov", "Hi", "<p>x</p>")["error"]
    assert any("ACS_CONNECTION_STRING should look like" in p for p in emailer.config_problems())


def test_env_file_is_loaded_and_real_env_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SMTP_HOST=smtp.from-file.test\nSMTP_PORT=2525   # inline comment\nPUBLIC_BASE_URL=https://from-file.test\n")
    env = {k: v for k, v in os.environ.items() if k not in ("SMTP_HOST", "SMTP_PORT")}
    env.update(ENV_FILE=str(env_file), PUBLIC_BASE_URL="https://real-env.test")
    code = "from app import config; print(config.SMTP_HOST, config.SMTP_PORT, config.EMAIL_ENABLED, config.PUBLIC_BASE_URL)"
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent, env=env,
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["smtp.from-file.test", "2525", "True", "https://real-env.test"]


# ---------------- Azure OpenAI matching + explanations (with a fake Azure) ----------------
class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status_code, self.ok, self._payload = status, 200 <= status < 300, payload
        self.headers, self.text = headers or {}, json.dumps(payload)

    def json(self):
        return self._payload


def _fake_vector(text, dim=8):
    import hashlib
    return [b / 255 for b in hashlib.sha256(text.encode()).digest()[:dim]]


@pytest.fixture
def azure(monkeypatch):
    """Azure OpenAI configured, with requests answered by a fake. Set .embed / .chat to change the replies."""
    from app import db
    from app.matching import embeddings, explain

    class Fake:
        embed_calls, chat_calls = [], []
        embed = staticmethod(lambda body: FakeResponse(200, {"data": [
            {"index": i, "embedding": _fake_vector(t)} for i, t in enumerate(body["input"])]}))
        chat = staticmethod(lambda body: FakeResponse(200, {"choices": [{"message": {"content": "AI says it fits."}}]}))

    def post(url, headers=None, json=None, timeout=None):
        if "/embeddings" in url:
            Fake.embed_calls.append(json)
            return Fake.embed(json)
        Fake.chat_calls.append(json)
        return Fake.chat(json)

    for k, v in {"AZURE_OPENAI_ENDPOINT": "https://fake.openai.azure.com", "AZURE_OPENAI_KEY": "k",
                 "AZURE_EMBEDDING_DEPLOYMENT": "emb", "AZURE_CHAT_DEPLOYMENT": "chat",
                 "USE_AZURE_EMBEDDINGS": True, "USE_AZURE_CHAT": False}.items():
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(embeddings.requests, "post", post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: None)
    monkeypatch.setattr(embeddings, "_azure_down_until", 0.0)
    monkeypatch.setattr(explain, "_chat_down_until", 0.0)
    monkeypatch.setattr(explain, "_shape", 0)
    Fake.embed_calls.clear(), Fake.chat_calls.clear()
    yield Fake
    with db.session() as conn:
        conn.execute("UPDATE opportunities SET embedding=NULL")
        conn.execute("DELETE FROM explanations")
    embeddings._indexes.clear()
    embeddings._query_cache.clear()


DEPLOYMENT_NOT_FOUND = FakeResponse(404, {"error": {"code": "DeploymentNotFound", "message": "The API deployment for this resource does not exist."}})


def test_azure_configured_but_no_vectors_uses_local_matching(client, azure):
    """What happened when .env turned Azure on for a database ingested without it: no 500, local matching."""
    r = client.post("/api/search", json={"agency_id": "deq"})
    assert r.status_code == 200 and r.json()["results"]
    assert azure.embed_calls == []  # nothing to compare against, so Azure isn't even asked
    assert client.get("/api/meta").json()["ai"]["embeddings"] == "tfidf"


def test_missing_azure_deployment_does_not_break_search(client, azure, monkeypatch):
    from app.matching import embeddings
    assert embeddings.refresh_opportunity_embeddings() > 0  # vectors stored, so the Azure index is used
    assert client.get("/api/meta").json()["ai"]["embeddings"] == "azure"
    assert client.post("/api/search", json={"agency_id": "dhhs"}).status_code == 200
    calls = len(azure.embed_calls)

    azure.embed = staticmethod(lambda body: DEPLOYMENT_NOT_FOUND)  # deployment deleted / renamed
    r = client.post("/api/search", json={"agency_id": "deq"})
    assert r.status_code == 200
    monkeypatch.setattr(config, "USE_AZURE_EMBEDDINGS", False)  # same ranking as plain local matching
    assert r.json()["results"] == client.post("/api/search", json={"agency_id": "deq"}).json()["results"]
    monkeypatch.setattr(config, "USE_AZURE_EMBEDDINGS", True)
    assert client.post("/api/search", json={"agency_id": "ncdot"}).status_code == 200
    assert len(azure.embed_calls) == calls + 1  # one failed try, then Azure is left alone for a while
    assert client.get("/api/meta").json()["ai"]["embeddings"] == "tfidf"
    assert client.post("/api/export.csv", json={"agency_id": "deq"}).status_code == 200
    assert client.post("/api/subscriptions/preview", json={"email": "x@agency.nc.gov", "agency_id": "deq"}).status_code == 200


def test_embedding_model_change_does_not_break_search(client, azure):
    from app.matching import embeddings
    embeddings.refresh_opportunity_embeddings()
    azure.embed = staticmethod(lambda body: FakeResponse(200, {"data": [
        {"index": i, "embedding": _fake_vector(t, 16)} for i, t in enumerate(body["input"])]}))
    assert client.post("/api/search", json={"agency_id": "deq", "q": "x"}).status_code == 200


def test_ingest_finishes_when_embedding_fails(client, azure):
    from app import db
    from app.ingest import pipeline
    azure.embed = staticmethod(lambda body: DEPLOYMENT_NOT_FOUND)
    db.set_meta("ingest_version", "before")
    summary = pipeline.run(sample=True)
    assert "no deployment named 'emb'" in summary["embedding_error"]
    assert db.get_meta("ingest_version") == summary["ran_at"]  # running servers still pick up the new data


def test_embed_backfill_waits_out_rate_limits_and_keeps_progress(client, azure):
    from app.matching import embeddings
    replies = iter([FakeResponse(429, {"error": {"code": "429"}}, {"retry-after": "1"})])
    ok = azure.embed
    azure.embed = staticmethod(lambda body: next(replies, None) or ok(body))
    assert embeddings.refresh_opportunity_embeddings() == embeddings.vector_status()["total"]

    azure.embed = staticmethod(lambda body: FakeResponse(401, {"error": {"code": "401", "message": "Access denied"}}))
    with pytest.raises(embeddings.EmbeddingError, match="refused the key"):
        embeddings.refresh_opportunity_embeddings(redo_all=True)
    s = embeddings.vector_status()
    assert s["with_vector"] == s["total"]  # the earlier vectors are kept


def test_missing_chat_deployment_falls_back_to_rules_quickly(client, azure, monkeypatch):
    monkeypatch.setattr(config, "USE_AZURE_CHAT", True)
    azure.chat = staticmethod(lambda body: DEPLOYMENT_NOT_FOUND)
    res = client.post("/api/search", json={"agency_id": "deq"}).json()["results"]
    assert res and all(r["rationale_source"] == "rules" and r["rationale"] for r in res)  # not labeled "AI summary"
    assert len(azure.chat_calls) == 1  # not one failing call per card
    assert client.get("/api/meta").json()["ai"]["explanations"] == "rules"


def test_chat_adapts_to_reasoning_models(client, azure, monkeypatch):
    """GPT-5-family models reject max_tokens/temperature; the request switches shape and remembers it."""
    monkeypatch.setattr(config, "USE_AZURE_CHAT", True)
    azure.chat = staticmethod(lambda body: FakeResponse(400, {"error": {"code": "unsupported_parameter", "param": "max_tokens"}})
                              if "max_tokens" in body else FakeResponse(200, {"choices": [{"message": {"content": "Fits PFAS work."}}]}))
    res = client.post("/api/search", json={"agency_id": "deq"}).json()["results"]
    assert res[0]["rationale"] == "Fits PFAS work." and res[0]["rationale_source"] == "ai"
    assert all("max_tokens" not in c for c in azure.chat_calls[2:])  # the working shape is reused
