"""Effort & match: the hours rubric, cleaning what the AI extracted, and the estimate on research results."""
import json

from fastapi.testclient import TestClient

from app import db, effort, research
from app.main import app

CITE = lambda it: {"doc_id": "1", "doc_name": "NOFO.pdf", "page": it["page"]} if isinstance(it, dict) and it.get("page") else None


def test_rubric_scales_per_unit_parts_and_always_adds_budget_and_review():
    est = effort.estimate([{"kind": "narrative", "item": "Project Narrative", "quantity": 15, "source": None},
                           {"kind": "letters", "item": "Letters of support", "quantity": None, "source": None}],
                          {"competition": "D", "funding_instruments": ["G"]})
    by_kind = {line["kind"]: line for line in est["lines"]}
    assert (by_kind["narrative"]["low"], by_kind["narrative"]["high"]) == (15, 30)          # 1-2 hours a page
    assert by_kind["letters"]["quantity"] == 3 and by_kind["letters"]["quantity_assumed"]   # default when not stated
    assert by_kind["budget"]["id"] == "budget-assumed" and by_kind["review"]["low"] == 6
    assert est["low"] == sum(line["low"] for line in est["lines"]) and est["low"] < est["high"]
    roles = {r["role"]: r for r in est["by_role"]}
    assert {"grant_writer", "finance", "leadership"} <= set(roles)
    assert est["factor"] == 1.0 and est["notes"] == []


def test_formula_awards_take_less_work_and_cooperative_agreements_more():
    parts = [{"kind": "state_plan", "item": "State plan", "source": None}]
    formula = effort.estimate(parts, {"competition": "M", "funding_instruments": ["G"]})
    coop = effort.estimate(parts, {"competition": "D", "funding_instruments": ["CA"]})
    assert formula["high"] < coop["high"]
    assert formula["factor"] == 0.6 and "Formula" in formula["notes"][0]
    assert coop["factor"] == 1.15 and "Cooperative agreement" in coop["notes"][0]


def test_absurd_quantities_are_capped_and_unknown_kinds_become_other():
    est = effort.estimate([{"kind": "narrative", "quantity": 10_000, "source": None},
                           {"kind": "interpretive dance", "item": "Video", "source": None}], {})
    assert est["lines"][0]["quantity"] == 200
    assert est["lines"][1]["kind"] == "other" and est["lines"][1]["label"] == "Video"


def test_cost_share_cleaning():
    clean = lambda raw: effort.clean_cost_share(raw, CITE)
    full = clean({"required": True, "percent": 25, "basis": "total", "types": ["cash", "in_kind", "bitcoin"],
                  "waiver": "Waived for insular areas.", "detail": "25% of total project cost.", "page": 7})
    assert full["percent"] == 25 and full["basis"] == "total" and full["types"] == ["cash", "in_kind"]
    assert full["source"]["page"] == 7 and not full["basis_assumed"]
    assert clean({"required": True, "percent": 100, "basis": "federal"})["percent"] == 100   # a 1:1 match
    assert clean({"required": True, "percent": 100, "basis": "total"})["percent"] is None    # impossible
    assert clean({"required": True, "percent": 20})["basis_assumed"] is True
    assert clean({"required": False, "percent": 30})["percent"] is None
    assert clean("not a dict") == {"required": None, "percent": None, "basis": None, "basis_assumed": False,
                                   "types": [], "waiver": None, "detail": None, "source": None}


def test_parts_and_skills_cleaning():
    parts = effort.clean_parts([{"kind": "narrative", "item": "Narrative", "quantity": 12, "page": 9},
                                {"kind": "bogus", "item": "Mystery form"}, "junk", {}], CITE)
    assert [p["kind"] for p in parts] == ["narrative", "other"] and parts[0]["source"]["page"] == 9
    skills = effort.clean_skills(["GIS mapping", {"skill": "Benefit-cost analysis", "why": "Required for construction.", "page": 3},
                                  {"skill": ""}], CITE)
    assert [s["skill"] for s in skills] == ["GIS mapping", "Benefit-cost analysis"] and skills[1]["source"]["page"] == 3


def test_research_results_carry_the_estimate_and_old_ones_say_so():
    with TestClient(app):
        with db.session() as conn:
            opp_id = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
            for agency, result in (("deq", {"verdict": "eligible", "application_parts": [{"kind": "narrative", "item": "Narrative",
                                                                                            "quantity": 10, "source": None}]}),
                                   ("dhhs", {"verdict": "eligible"})):  # saved before prompt version 2
                conn.execute("INSERT INTO research(opportunity_id, agency_id, result, created_at) VALUES(?,?,?,?) "
                             "ON CONFLICT(opportunity_id, agency_id) DO UPDATE SET result=excluded.result",
                             (opp_id, agency, json.dumps(result), "2026-11-07T00:00:00+00:00"))
        new = research.cached(opp_id, "deq")
        assert new["effort"]["lines"][0]["kind"] == "narrative" and new["effort"]["high"] > 0
        assert research.cached(opp_id, "dhhs")["effort"] is None


def test_clean_result_keeps_the_new_fields():
    docs = [{"id": "77", "name": "NOFO.pdf", "pages": ["a"] * 10}]
    raw = {"cost_share": {"required": True, "percent": 50, "basis": "federal", "doc": 1, "page": 4},
           "application_parts": [{"kind": "budget", "item": "Budget", "doc": 1, "page": 5}],
           "special_skills": [{"skill": "Engineering estimate", "doc": 1, "page": 99}]}   # page 99 doesn't exist
    out = research._clean_result(raw, docs)
    assert out["cost_share"]["source"] == {"doc_id": "77", "doc_name": "NOFO.pdf", "page": 4}
    assert out["application_parts"][0]["source"]["page"] == 5
    assert out["special_skills"][0]["source"] is None
