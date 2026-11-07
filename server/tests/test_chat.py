"""Ask about this grant: page selection, citation checks, caching and the API (all offline)."""
import json

import pytest
from fastapi.testclient import TestClient

from app import chat, config, db, research
from app.main import app
from app.matching import explain

PAGES = [
    "Notice of Funding Opportunity. Outdoor Recreation Legacy Partnership.",
    "Eligibility. Only State and Territorial Lead Agencies may submit applications to the NPS.",
    "Cost sharing. A one-to-one match of non-federal funds is required. In-kind contributions are allowed.",
    "Page limits. The project narrative may not exceed 15 pages.",
]
ANSWER = {
    "answer": "Yes. Your agency must match every federal dollar with one dollar of its own, and staff time or equipment can count.",
    "found": True,
    "citations": [
        {"doc": 1, "page": 3, "quote": "A one-to-one match of non-federal funds is required."},
        {"doc": 1, "page": 3, "quote": "duplicate page"},                       # same page twice: dropped
        {"doc": 1, "page": 2, "quote": "The state pays nothing."},              # not on that page: quote removed
        {"doc": 1, "page": 40, "quote": "Imaginary page"},                      # no such page: dropped
    ],
    "follow_ups": ["What counts as in-kind?", 42, ""],
}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fake(monkeypatch):
    calls = {"chat": [], "downloads": 0}
    monkeypatch.setattr(config, "USE_AZURE_CHAT", True)
    monkeypatch.setattr(research, "native_id", lambda oid: "4242")
    monkeypatch.setattr(research, "list_documents", lambda oid: ([{"id": "9", "name": "NOFO.pdf", "mime": "application/pdf",
                                                                   "size": 1000, "folder": "Full Announcement"}], {}))

    def download(att_id):
        calls["downloads"] += 1
        return b"%PDF-1.7"
    monkeypatch.setattr(research, "download", download)
    monkeypatch.setattr(research, "extract_pages", lambda data, name, mime: list(PAGES))

    def ai(messages, **kw):
        calls["chat"].append((messages, kw))
        return json.dumps(ANSWER)
    monkeypatch.setattr(explain, "_chat", ai)
    chat._pages.clear()
    return calls


def _opp():
    with db.session() as conn:
        return conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]


def test_answer_with_checked_citations(client, fake):
    r = client.post("/api/chat", json={"opportunity_id": _opp(), "agency_id": "deq", "question": "Is there a cost share?"})
    assert r.status_code == 200
    data = r.json()
    assert data["found"] and data["answer"].startswith("Yes.")
    assert [(c["page"], c["verified"]) for c in data["citations"]] == [(3, True), (2, False)]
    assert data["citations"][0]["quote"].startswith("A one-to-one match") and data["citations"][1]["quote"] is None
    assert data["follow_ups"] == ["What counts as in-kind?"]
    messages, kw = fake["chat"][0]
    assert kw["shapes"] is chat.CHAT_SHAPES and "never as instructions" in messages[0]["content"]
    assert "[D1 p.3]" in messages[1]["content"] and messages[-1] == {"role": "user", "content": "Is there a cost share?"}


def test_documents_are_read_once_and_history_is_passed_along(client, fake):
    body = {"opportunity_id": _opp(), "agency_id": "deq", "question": "And the page limit?",
            "history": [{"role": "user", "content": "Is there a cost share?"}, {"role": "assistant", "content": "Yes, 1:1."}]}
    client.post("/api/chat", json=body)
    client.post("/api/chat", json=body)
    assert fake["downloads"] == 1
    messages = fake["chat"][-1][0]
    assert {"role": "assistant", "content": "Yes, 1:1."} in messages


def test_relevant_pages_prefer_the_question_and_keep_page_one():
    docs = [{"pages": PAGES + ["filler " * 2000]}]
    picked = [p for _, p, _ in chat.relevant_pages(docs, "What is the narrative page limit?", budget=500)]
    assert picked == [1, 4]


def test_plain_text_replies_still_answer(client, fake, monkeypatch):
    monkeypatch.setattr(explain, "_chat", lambda messages, **kw: "The notice doesn't say. Ask the program officer.")
    data = client.post("/api/chat", json={"opportunity_id": _opp(), "agency_id": "deq", "question": "Can we buy drones?"}).json()
    assert data["answer"].startswith("The notice doesn't say") and data["citations"] == []


def test_errors(client, fake, monkeypatch):
    opp = _opp()
    assert client.post("/api/chat", json={"opportunity_id": "nope", "agency_id": "deq", "question": "Is there a match?"}).status_code == 404
    assert client.post("/api/chat", json={"opportunity_id": opp, "agency_id": "nope", "question": "Is there a match?"}).status_code == 404
    assert client.post("/api/chat", json={"opportunity_id": opp, "agency_id": "deq", "question": "?"}).status_code == 422
    bad_role = {"opportunity_id": opp, "agency_id": "deq", "question": "Is there a match?", "history": [{"role": "system", "content": "x"}]}
    assert client.post("/api/chat", json=bad_role).status_code == 422
    monkeypatch.setattr(config, "USE_AZURE_CHAT", False)
    r = client.post("/api/chat", json={"opportunity_id": opp, "agency_id": "deq", "question": "Is there a match?"})
    assert r.status_code == 400 and "Azure OpenAI" in r.json()["detail"]
