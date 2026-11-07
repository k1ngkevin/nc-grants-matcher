"""Blended, transparent relevance score (0-100).

  45  Semantic fit   cosine similarity vs. agency mission/strategic plans AND active projects
  25  Program fit    federal program (ALN) the agency usually receives + mission keywords in the text
  15  Eligibility    how clearly the agency's applicant type is eligible
  10  Timing         workable deadline (urgent but doable > comfortable > far off > forecast)
   5  Award size     bigger awards rank slightly higher (log scale)
 +/-  Team feedback  learned from this agency's Pursue / Save / Dismiss history (capped)

Every component is returned so the UI can show exactly why something ranked where it did.
"""
import math
import re
from collections import Counter, defaultdict

from ..agencies import eligibility_fit
from ..config import FINANCIAL_FLOOR
from ..normalize import best_award_amount, days_left, timing_category
from . import embeddings

WEIGHTS = {"semantic": 45, "program": 25, "eligibility": 15, "timing": 10, "size": 5}
MATCH_LABELS = {"strong": "Strong match", "good": "Good match", "possible": "Possible match"}


def assess_match(score: int, parts: dict) -> dict:
    """Keep practical points from turning limited relevance into a positive match label.

    The numeric score stays additive so its breakdown and ordering remain transparent.
    Good needs 40% semantic fit and 50% of relevance points; Strong needs 60% and 70%.
    These are screening thresholds, not a prediction of application success.
    """
    relevance_max = WEIGHTS["semantic"] + WEIGHTS["program"]
    practical_max = WEIGHTS["eligibility"] + WEIGHTS["timing"] + WEIGHTS["size"]
    relevance = round(parts["semantic"] + parts["program"], 1)
    practical = round(sum(parts[k] for k in ("eligibility", "timing", "size")), 1)
    enough_relevance = parts["semantic"] >= 0.4 * WEIGHTS["semantic"] and relevance >= 0.5 * relevance_max
    strong_relevance = parts["semantic"] >= 0.6 * WEIGHTS["semantic"] and relevance >= 0.7 * relevance_max
    level = "strong" if score >= 70 and strong_relevance else "good" if score >= 50 and enough_relevance else "possible"
    return {
        "match_level": level,
        "score_preview": {
            "relevance_points": relevance,
            "relevance_max": relevance_max,
            "practical_points": practical,
            "practical_max": practical_max,
            "caution": ("Limited mission or program relevance. Eligibility, timing and award size also contribute to the score."
                        if not enough_relevance else None),
        },
    }

DISMISS_REASONS = {
    "not_relevant": "Not relevant to our mission",
    "match_funds": "Can't meet the match / cost-share",
    "too_small": "Award too small for the effort",
    "deadline": "Deadline too soon",
    "other_agency": "Another agency handles this",
    "already_have": "Already applied / already funded",
    "capacity": "No staff capacity right now",
    "other": "Other",
}


def _kw_hits(keywords: list[str], text: str) -> list[str]:
    t = text.lower()
    return [k for k in keywords if re.search(r"\b" + re.escape(k.lower()) + r"\b", t)]


def _aln_match(prefixes: list[str], alns: list[str]) -> str | None:
    for a in alns or []:
        for p in prefixes:
            if a.startswith(p):
                return a
    return None


def _timing_score(cat: str, d: int | None) -> float:
    if cat == "urgent":
        return 1.0 if (d or 0) >= 7 else 0.6
    return {"standard": 0.9, "later": 0.6, "forecasted": 0.7}.get(cat, 0.5)


def _size_score(amount: int | None) -> float:
    if not amount:
        return 0.3
    return min(1.0, max(0.0, math.log10(amount / FINANCIAL_FLOOR) / math.log10(10_000_000 / FINANCIAL_FLOOR)))


def feedback_model(decisions: list[dict]) -> dict:
    """Summarise an agency's past decisions into simple, explainable adjustments."""
    by_code, by_aln = defaultdict(float), defaultdict(float)
    reasons = Counter()
    for d in decisions:
        w = {"pursue": 3.0, "save": 1.5}.get(d["action"], 0.0)
        if d["action"] == "dismiss":
            reasons[d.get("reason") or "other"] += 1
            if d.get("reason") == "not_relevant":
                w = -4.0
        if w:
            if d.get("federal_agency_code"):
                by_code[d["federal_agency_code"]] += w
            for a in d.get("aln_numbers") or []:
                by_aln[a] += w
    return {"by_code": by_code, "by_aln": by_aln, "reasons": reasons}


def feedback_adjustment(opp: dict, fb: dict, cat: str, amount: int | None) -> tuple[float, list[str]]:
    adj, notes = 0.0, []
    sim = fb["by_code"].get(opp.get("federal_agency_code"), 0) + max(
        [fb["by_aln"].get(a, 0) for a in opp.get("aln_numbers") or []] or [0])
    if sim:
        adj += max(-12, min(8, sim))
        notes.append("your team has pursued similar grants" if sim > 0 else "your team dismissed similar grants as off-mission")
    r = fb["reasons"]
    if r["match_funds"] >= 2 and opp.get("cost_sharing") == 1:
        adj -= 6
        notes.append("requires a match, which your team has passed on before")
    if r["deadline"] >= 2 and cat == "urgent":
        adj -= 4
        notes.append("short deadline, which your team has passed on before")
    if r["too_small"] >= 2 and amount and amount < 250_000:
        adj -= 4
        notes.append("smaller award than your team usually pursues")
    return adj, notes


def rank(agency: dict, opps: list[dict], profile_chunks: list[str], projects: list[dict],
         decisions: list[dict]) -> list[dict]:
    if not opps:
        return []

    def similarities(index):
        cols = [index.pos[o["id"]] for o in opps if o["id"] in index.pos]
        profile_sims = index.similarities(profile_chunks)[:, cols] if profile_chunks else None
        prof = profile_sims.max(axis=0) if profile_sims is not None else [0.0] * len(cols)
        evidence = [profile_chunks[int(k)][:1000] for k in profile_sims.argmax(axis=0)] if profile_sims is not None else [""] * len(cols)
        proj = index.similarities([p["title"] + ". " + p["description"] for p in projects])[:, cols] if projects else None
        return [o for o in opps if o["id"] in index.pos], prof, proj, evidence

    index = embeddings.get_index()
    try:
        opps, prof, proj_sims, mission_evidence = similarities(index)
    except embeddings.EmbeddingError:
        index = embeddings.get_index()  # Azure is cooling down now, so this is the local TF-IDF index
        opps, prof, proj_sims, mission_evidence = similarities(index)
    fb = feedback_model(decisions)

    results = []
    for j, o in enumerate(opps):
        text = f"{o['title']} {o.get('description') or ''}"
        mission = embeddings.calibrate(float(prof[j]), index.kind)
        best_proj, proj_fit = None, 0.0
        if proj_sims is not None and proj_sims.shape[0]:
            k = int(proj_sims[:, j].argmax())
            proj_fit = embeddings.calibrate(float(proj_sims[k, j]), index.kind)
            if proj_fit >= 0.35:
                best_proj = projects[k]
        semantic = mission if proj_fit <= mission else (mission + proj_fit) / 2

        hits = _kw_hits(agency["keywords"], text)
        aln = _aln_match(agency["aln_prefixes"], o.get("aln_numbers"))
        program = (0.6 if aln else 0.0) + 0.4 * min(1.0, len(hits) / 3)

        elig, elig_label = eligibility_fit(agency, o.get("eligibility_codes"))
        cat = timing_category(o["status"], o.get("close_date"))
        d = days_left(o.get("close_date"))
        timing = _timing_score(cat, d)
        amount = best_award_amount(o)
        size = _size_score(amount)

        parts = {
            "semantic": round(WEIGHTS["semantic"] * semantic, 1),
            "program": round(WEIGHTS["program"] * program, 1),
            "eligibility": round(WEIGHTS["eligibility"] * elig, 1),
            "timing": round(WEIGHTS["timing"] * timing, 1),
            "size": round(WEIGHTS["size"] * size, 1),
        }
        adj, fb_notes = feedback_adjustment(o, fb, cat, amount)
        parts["feedback"] = round(adj, 1)
        total = max(0, min(100, round(sum(parts.values()))))

        results.append({
            "opportunity": o,
            "score": total,
            "breakdown": parts,
            **assess_match(total, parts),
            "signals": {
                "mission_fit": round(mission, 2),
                "project_fit": round(proj_fit, 2),
                "mission_evidence": mission_evidence[j],
                "similarity_method": index.kind,
                "matched_project": {"id": best_proj["id"], "title": best_proj["title"]} if best_proj else None,
                "matched_keywords": hits[:6],
                "matched_program": aln,
                "eligibility": elig_label,
                "timing": cat,
                "days_left": d,
                "amount": amount,
                "feedback_notes": fb_notes,
            },
        })
    results.sort(key=lambda r: (-r["score"], r["signals"]["days_left"] if r["signals"]["days_left"] is not None else 999))
    return results
