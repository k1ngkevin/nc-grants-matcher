"""Regression coverage for score labels, grounded previews and persistent AI caching."""
from copy import deepcopy
import hashlib
import json

import numpy as np
import pytest

from app import config, db
from app.agencies import AGENCY_BY_ID
from app.ingest import pipeline
from app.matching import embeddings, explain
from app.matching.score import assess_match, rank
from app.search import Filters, search


@pytest.fixture
def matching_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "matching.db")
    monkeypatch.setattr(config, "USE_AZURE_EMBEDDINGS", False)
    monkeypatch.setattr(embeddings, "_indexes", {})
    monkeypatch.setattr(embeddings, "_query_cache", {})
    db.init_db()
    pipeline.run(sample=True)


@pytest.mark.parametrize("semantic,program,practical,expected", [
    (14, 24, 30, "possible"),  # a high total with weak semantic relevance
    (32, 1, 30, "possible"),   # similarity alone without enough combined relevance
    (18, 17, 30, "good"),     # exactly at the good relevance thresholds
    (27, 22, 21, "strong"),   # exactly at the strong thresholds, total 70
    (26.9, 22.1, 21, "good"), # total 70, but insufficient semantic relevance for Strong
    (27, 22, 20, "good"),     # strong relevance, total below 70
    (18, 17, 14, "possible"), # good relevance, total below 50
])
def test_match_labels_require_relevance(semantic, program, practical, expected):
    parts = {"semantic": semantic, "program": program, "eligibility": practical / 2,
             "timing": practical / 3, "size": practical / 6, "feedback": 0}
    score = round(sum(parts.values()))
    assessment = assess_match(score, parts)
    assert assessment["match_level"] == expected
    assert assessment["score_preview"]["relevance_points"] == semantic + program
    assert assessment["score_preview"]["practical_points"] == practical


def test_feedback_cannot_make_a_weak_relevance_match_strong():
    parts = {"semantic": 14, "program": 24, "eligibility": 15, "timing": 10, "size": 5, "feedback": 8}
    assessment = assess_match(76, parts)
    assert assessment["match_level"] == "possible"
    assert assessment["score_preview"]["caution"]


def test_search_preview_keeps_the_numeric_breakdown(matching_db):
    rows = search(Filters(agency_id="dit"), limit=200)["results"]
    assert rows
    for r in rows:
        assert r["score"] == max(0, min(100, round(sum(r["breakdown"].values()))))
        preview = r["score_preview"]
        assert r["score"] == max(0, min(100, round(
            preview["relevance_points"] + preview["practical_points"] + r["breakdown"]["feedback"])))
        assert f"{r['score']}/100" in r["rationale"]
        assert r["rationale_source"] == "rules"
        if preview["caution"]:
            assert r["match_level"] == "possible"


def test_rank_includes_the_plan_excerpt_that_contributed_to_mission_fit(monkeypatch):
    chunks = ["Agency operates statewide IT.", "Strategic plan: assess rural health information systems."]

    class Index:
        kind, pos = "tfidf", {"rural-health": 0}

        def similarities(self, texts):
            return np.array([[0.03], [0.20]])

    monkeypatch.setattr(embeddings, "get_index", lambda: Index())
    result = rank(AGENCY_BY_ID["dit"], [{
        "id": "rural-health", "title": "Rural health IT assessment", "description": "Health information systems",
        "status": "forecasted", "eligibility_codes": ["00"], "award_ceiling": 1_000_000,
    }], chunks, [], [])[0]
    assert result["signals"]["mission_evidence"] == chunks[1]
    facts = json.loads(explain._messages(AGENCY_BY_ID["dit"], result, [])[1]["content"])
    assert facts["signals"]["mission_evidence"] == chunks[1]


@pytest.fixture
def captured_chat(matching_db, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "USE_AZURE_CHAT", True)
    monkeypatch.setattr(explain, "_chat_down_until", 0)

    def chat(messages):
        calls.append(messages)
        return "The listing has some shared topics. The score includes practical factors. Confirm the funded activities."

    monkeypatch.setattr(explain, "_chat", chat)
    return calls


def test_ai_prompt_explains_score_and_persists_for_repeat_search(captured_chat):
    first = search(Filters(agency_id="dit"), limit=20, with_llm=True)["results"]
    assert len(captured_chat) == min(5, len(first))
    facts = json.loads(captured_chat[0][1]["content"])
    assert facts["score"] == first[0]["score"]
    assert facts["breakdown"] == first[0]["breakdown"]
    assert facts["score_preview"] == first[0]["score_preview"]
    assert facts["signals"]["similarity_method"] == "tfidf"
    assert facts["active_projects"] == []
    assert "not force your assessment to agree" in captured_chat[0][0]["content"]
    assert "missing context, not evidence of a poor fit" in captured_chat[0][0]["content"]
    assert all(r["rationale_source"] == "rules" for r in first[5:])
    # A second search reads the explanations from SQLite, without another chat call.
    count = len(captured_chat)
    second = search(Filters(agency_id="dit"), limit=20, with_llm=True)["results"]
    assert len(captured_chat) == count
    assert [r["rationale"] for r in second] == [r["rationale"] for r in first]
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM explanations").fetchone()[0] == count


@pytest.mark.parametrize("changed", ["listing", "mission", "project_description", "plan", "score", "deployment", "prompt"])
def test_ai_cache_refreshes_when_explanation_inputs_change(captured_chat, monkeypatch, changed):
    agency = deepcopy(AGENCY_BY_ID["dit"])
    result = search(Filters(agency_id="dit"), limit=1)["results"][0]
    projects = [{"id": 42, "title": "Modernize IT", "description": "Inventory older systems."}]
    # An explanation from the old agency/id/project-title cache must not be reused.
    legacy_key = hashlib.sha1(f"dit:{result['opportunity']['id']}:Modernize IT".encode()).hexdigest()
    with db.session() as conn:
        conn.execute("INSERT INTO explanations(cache_key, text) VALUES (?, 'Old optimistic summary')", (legacy_key,))
    explain.llm_rationale(agency, result, projects)
    assert len(captured_chat) == 1
    explain.llm_rationale(agency, result, projects)
    assert len(captured_chat) == 1
    if changed == "listing":
        result["opportunity"]["description"] = "Only funds rural health research."
    elif changed == "mission":
        agency["mission"] += " Expand rural connectivity."
    elif changed == "project_description":
        projects[0]["description"] = "Assess health information systems."
    elif changed == "plan":
        result["signals"]["mission_evidence"] = "New strategic plan: rural digital infrastructure."
    elif changed == "score":
        result["breakdown"]["feedback"] += 3
        result["score"] += 3
    elif changed == "deployment":
        monkeypatch.setattr(config, "AZURE_CHAT_DEPLOYMENT", "updated-model")
    else:
        original = explain._messages

        def updated_messages(*args):
            messages = original(*args)
            messages[0]["content"] += " Updated preview guidance."
            return messages

        monkeypatch.setattr(explain, "_messages", updated_messages)
    explain.llm_rationale(agency, result, projects)
    assert len(captured_chat) == 2


def test_matched_project_beyond_first_eight_is_grounded(captured_chat):
    result = search(Filters(agency_id="dit"), limit=1)["results"][0]
    projects = [{"id": i, "title": f"Project {i}", "description": f"Work for project {i}"} for i in range(10)]
    result["signals"]["matched_project"] = {"id": 9, "title": "Project 9"}
    explain.llm_rationale(AGENCY_BY_ID["dit"], result, projects)
    facts = json.loads(captured_chat[0][1]["content"])
    assert len(facts["active_projects"]) == 8
    assert facts["active_project_count"] == 10
    assert facts["matched_project_details"]["description"] == "Work for project 9"
