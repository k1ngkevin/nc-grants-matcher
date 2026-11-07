"""Precision@10 from real reviewer decisions (Lane C evaluation).

For each agency with decisions, rank every eligible opportunity (ignoring triage status)
and look at the top 10:
  precision@10        = top-10 items marked Pursue/Save  / 10
  judged precision@10 = top-10 items marked Pursue/Save  / top-10 items that have any decision
Run:  python -m app.evaluate
"""
import json

from . import db, guardrails
from .agencies import AGENCIES
from .matching.score import rank
from .search import latest_decisions, load_agency_context


def precision_at_10() -> list[dict]:
    with db.session() as conn:
        rows = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM opportunities")]
    out = []
    for a in AGENCIES:
        agency, chunks, projects, decisions = load_agency_context(a["id"])
        labels = latest_decisions(decisions)
        if not labels:
            continue
        cands = [o for o in rows if guardrails.check(o, agency)[0]]
        top = rank(agency, cands, chunks, projects, [])[:10]  # no feedback boost: measure the base model
        positives = sum(1 for r in top if labels.get(r["opportunity"]["id"], {}).get("action") in ("pursue", "save"))
        judged = sum(1 for r in top if r["opportunity"]["id"] in labels)
        out.append({"agency": a["short"], "decisions": len(labels), "precision_at_10": round(positives / 10, 2),
                    "judged_precision_at_10": round(positives / judged, 2) if judged else None, "judged_in_top_10": judged})
    return out


if __name__ == "__main__":
    print(json.dumps(precision_at_10(), indent=2))
