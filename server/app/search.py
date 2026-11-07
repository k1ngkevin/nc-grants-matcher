"""One function the website, the CSV export and the email digests all share:
apply guardrails + filters for an agency, score, explain, and split by triage status."""
from collections import Counter
from dataclasses import dataclass, field

from . import db, guardrails
from .agencies import AGENCY_BY_ID
from .config import FINANCIAL_FLOOR
from .matching import embeddings, explain
from .matching.score import rank
from .normalize import TIMING_LABELS, grant_type

TIMING_ORDER = ["urgent", "standard", "later", "forecasted"]


@dataclass
class Filters:
    agency_id: str
    min_award: int = FINANCIAL_FLOOR
    timing: list[str] = field(default_factory=lambda: list(TIMING_ORDER))
    q: str = ""
    federal_agency: str = ""
    no_match_only: bool = False
    include_unknown_amount: bool = True
    min_score: int = 0
    sort: str = "score"            # score | deadline | amount
    view: str = "recommended"      # recommended | pursue | save | dismiss

    @classmethod
    def from_dict(cls, d: dict) -> "Filters":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and v is not None}
        f = cls(**known)
        f.min_award = max(int(f.min_award or 0), FINANCIAL_FLOOR)
        f.timing = [t for t in f.timing if t in TIMING_ORDER] or list(TIMING_ORDER)
        return f

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def federal_dept(code: str | None) -> str:
    return (code or "Other").split("-")[0]


def load_agency_context(agency_id: str):
    agency = AGENCY_BY_ID[agency_id]
    with db.session() as conn:
        docs = [dict(r) for r in conn.execute("SELECT * FROM agency_documents WHERE agency_id=?", (agency_id,))]
        projects = [dict(r) for r in conn.execute("SELECT id, title, description FROM projects WHERE agency_id=? ORDER BY id", (agency_id,))]
        decisions = [db.row_to_dict(r) for r in conn.execute(
            """SELECT d.*, o.federal_agency_code, o.aln_numbers FROM decisions d
               LEFT JOIN opportunities o ON o.id = d.opportunity_id
               WHERE d.agency_id=? ORDER BY d.id""", (agency_id,))]
    profile_chunks = [f"{agency['name']}. {agency['mission']} Focus areas: {', '.join(agency['keywords'])}."]
    for d in docs:
        profile_chunks.extend(embeddings.chunk(d["content"]))
    return agency, profile_chunks, projects, decisions


def latest_decisions(decisions: list[dict]) -> dict[str, dict]:
    latest = {}
    for d in decisions:
        latest[d["opportunity_id"]] = d  # rows are in id order, so the last one wins
    return {k: v for k, v in latest.items() if v["action"] != "undo"}


def search(f: Filters, limit: int = 50, offset: int = 0, with_llm: bool = False) -> dict:
    agency, profile_chunks, projects, decisions = load_agency_context(f.agency_id)
    status_by_opp = latest_decisions(decisions)

    with db.session() as conn:
        rows = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM opportunities")]

    # Guardrails (strict, agency-specific eligibility) then user filters.
    candidates = []
    for o in rows:
        ok, _ = guardrails.check(o, agency, floor=f.min_award, include_unknown_amount=f.include_unknown_amount)
        if ok:
            candidates.append(o)

    ranked = rank(agency, candidates, profile_chunks, projects, decisions)

    q_words = [w for w in f.q.lower().split() if w]
    counts = {"recommended": 0, "pursue": 0, "save": 0, "dismiss": 0}
    timing_counts, dept_counts = Counter(), Counter()
    out = []
    for r in ranked:
        o, s = r["opportunity"], r["signals"]
        if q_words:
            hay = f"{o['title']} {o.get('description') or ''} {o.get('federal_agency') or ''} {' '.join(o.get('aln_numbers') or [])}".lower()
            if not all(w in hay for w in q_words):
                continue
        if f.no_match_only and o.get("cost_sharing") == 1:
            continue
        if f.federal_agency and federal_dept(o.get("federal_agency_code")) != f.federal_agency:
            continue
        decision = status_by_opp.get(o["id"])
        bucket = decision["action"] if decision else "recommended"
        if bucket == "recommended" and r["score"] < f.min_score:
            continue
        counts[bucket] += 1
        if bucket != f.view:
            continue
        timing_counts[s["timing"]] += 1
        dept_counts[federal_dept(o.get("federal_agency_code"))] += 1
        if s["timing"] not in f.timing:
            continue
        r["decision"] = {k: decision.get(k) for k in ("action", "reason", "note", "created_at")} if decision else None
        out.append(r)

    if f.sort == "deadline":
        out.sort(key=lambda r: (r["signals"]["days_left"] if r["signals"]["days_left"] is not None else 9999, -r["score"]))
    elif f.sort == "amount":
        out.sort(key=lambda r: (-(r["signals"]["amount"] or 0), -r["score"]))

    page = out[offset:offset + limit]
    for i, r in enumerate(page):
        o = r["opportunity"]
        ai_text = explain.llm_rationale(agency, r, projects) if with_llm and i < 10 else None
        r["rationale"] = ai_text or explain.template_rationale(agency, r)
        r["rationale_source"] = "ai" if ai_text else "rules"
        r["grant_type"] = grant_type(o.get("funding_instruments"), o.get("competition"), o.get("cost_sharing"))
        r["timing_label"] = TIMING_LABELS.get(r["signals"]["timing"], "")
        r["match_level"] = "strong" if r["score"] >= 70 else "good" if r["score"] >= 50 else "possible"
        o.pop("embedding", None)

    return {
        "agency": {k: agency[k] for k in ("id", "short", "name", "applicant")},
        "filters": f.to_dict(),
        "total": len(out),
        "results": page,
        "counts": counts,
        "facets": {
            "timing": {t: timing_counts.get(t, 0) for t in TIMING_ORDER},
            "federal_agency": dict(dept_counts.most_common()),
        },
        "projects": projects,
    }
