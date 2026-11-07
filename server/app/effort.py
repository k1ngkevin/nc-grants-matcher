"""Effort & match: how much work an application takes, who has to do it, and what the state must put in.

The AI only extracts facts from the notice (which parts the application needs, how many pages or letters,
the cost-share rule), each with a page citation. Everything numeric comes from the rubric below, so the
same notice always gives the same estimate and every hour can be traced to a line a person can check.

Estimates are ranges on purpose: grant offices know their own pace better than any rubric, so the website
lets people change any line.
"""

# Hours (low, high) for each kind of application part. Per-unit kinds multiply by `quantity`.
# Rough planning figures for a state agency that has applied for federal grants before.
RUBRIC = {
    "narrative":    {"label": "Project narrative",                "per": "page",   "hours": (1.0, 2.0),  "default_qty": 10},
    "budget":       {"label": "Budget and budget justification",  "per": None,     "hours": (12, 24)},
    "letters":      {"label": "Letters of support or commitment", "per": "letter", "hours": (1.5, 3.0),  "default_qty": 3},
    "partnerships": {"label": "Partner agreements (MOUs)",        "per": None,     "hours": (8, 20)},
    "data_plan":    {"label": "Data, evaluation or performance plan", "per": None, "hours": (6, 16)},
    "work_plan":    {"label": "Work plan and timeline",           "per": None,     "hours": (4, 10)},
    "registration": {"label": "Registrations (SAM.gov, Grants.gov, agency systems)", "per": None, "hours": (2, 6)},
    "forms":        {"label": "Standard forms and certifications", "per": None,    "hours": (2, 5)},
    "state_plan":   {"label": "State plan or program description", "per": None,    "hours": (16, 40)},
    "technical":    {"label": "Technical attachments (engineering, maps, environmental review)", "per": None, "hours": (8, 24)},
    "other":        {"label": "Other attachment",                 "per": None,     "hours": (2, 6)},
}
KINDS = tuple(RUBRIC)

# Who does each kind of work, as shares of its hours.
ROLES = {
    "grant_writer": "Grant writer",
    "program": "Program expert",
    "finance": "Budget and finance",
    "data": "Data and evaluation",
    "legal": "Legal and contracts",
    "admin": "Grants administration",
    "technical": "Technical specialist",
    "leadership": "Leadership review",
}
ROLE_SPLIT = {
    "narrative":    {"grant_writer": 0.6, "program": 0.4},
    "budget":       {"finance": 0.7, "grant_writer": 0.3},
    "letters":      {"program": 0.7, "grant_writer": 0.3},
    "partnerships": {"program": 0.5, "legal": 0.5},
    "data_plan":    {"data": 0.7, "program": 0.3},
    "work_plan":    {"program": 0.6, "grant_writer": 0.4},
    "registration": {"admin": 1.0},
    "forms":        {"admin": 0.7, "finance": 0.3},
    "state_plan":   {"program": 0.6, "grant_writer": 0.4},
    "technical":    {"technical": 0.8, "program": 0.2},
    "other":        {"grant_writer": 0.5, "program": 0.5},
    "review":       {"leadership": 0.5, "legal": 0.3, "finance": 0.2},
}
# Every application gets internal review and sign-off, whether or not the notice mentions it.
REVIEW = {"kind": "review", "label": "Internal review and approvals", "hours": (6, 12)}

# How the type of award scales the work. Formula and continuation applications are mostly fill-in;
# cooperative agreements need more negotiation over the work plan.
COMPETITION_FACTOR = {"D": (1.0, "competitive"), "M": (0.6, "formula or mandatory"), "C": (0.5, "continuation"),
                      "E": (0.5, "earmark"), "O": (1.0, "other")}
COOPERATIVE_BUMP = 1.15
MAX_QTY = {"page": 200, "letter": 50}


def _round(x: float) -> int:
    """To the nearest 5 hours above 20, otherwise the nearest hour: no false precision."""
    return int(round(x / 5) * 5) if x >= 20 else max(1, int(round(x)))


def _factor(opp: dict) -> tuple[float, list[str]]:
    factor, why = COMPETITION_FACTOR.get(opp.get("competition") or "D", COMPETITION_FACTOR["D"])
    notes = [f"{why.capitalize()} award: hours × {factor:g}."] if factor != 1.0 else []
    if "CA" in (opp.get("funding_instruments") or []):
        factor *= COOPERATIVE_BUMP
        notes.append(f"Cooperative agreement: hours × {COOPERATIVE_BUMP:g} for negotiating the work plan with the federal agency.")
    return factor, notes


def estimate(parts: list[dict], opp: dict) -> dict:
    """Hours per line, per role and in total from the application parts the AI found."""
    factor, notes = _factor(opp)
    lines = []
    seen_kinds = set()
    for p in parts:
        kind = p.get("kind") if p.get("kind") in RUBRIC else "other"
        rule = RUBRIC[kind]
        qty, assumed = None, False
        if rule["per"]:
            try:
                qty = int(p.get("quantity"))
            except (TypeError, ValueError):
                qty = None
            if not qty or qty < 1:
                qty, assumed = rule["default_qty"], True
            qty = min(qty, MAX_QTY[rule["per"]])
        mult = (qty or 1) * factor
        lines.append({
            "id": f"{kind}-{len(lines)}",
            "kind": kind,
            "label": (p.get("item") or rule["label"]).strip()[:120],
            "detail": (p.get("detail") or "").strip()[:300] or None,
            "quantity": qty,
            "unit": rule["per"],
            "quantity_assumed": assumed,
            "low": _round(rule["hours"][0] * mult),
            "high": _round(rule["hours"][1] * mult),
            "roles": ROLE_SPLIT[kind],
            "source": p.get("source"),
        })
        seen_kinds.add(kind)
    if "budget" not in seen_kinds:  # every federal application has a budget, even when the AI misses it
        rule = RUBRIC["budget"]
        lines.append({"id": "budget-assumed", "kind": "budget", "label": rule["label"], "detail": "Assumed: every federal application needs one.",
                      "quantity": None, "unit": None, "quantity_assumed": False,
                      "low": _round(rule["hours"][0] * factor), "high": _round(rule["hours"][1] * factor),
                      "roles": ROLE_SPLIT["budget"], "source": None})
    lines.append({"id": "review", "kind": "review", "label": REVIEW["label"], "detail": "Assumed for every application.",
                  "quantity": None, "unit": None, "quantity_assumed": False,
                  "low": REVIEW["hours"][0], "high": REVIEW["hours"][1], "roles": ROLE_SPLIT["review"], "source": None})
    return {
        "lines": lines,
        "low": sum(line["low"] for line in lines),
        "high": sum(line["high"] for line in lines),
        "by_role": totals_by_role(lines),
        "factor": round(factor, 2),
        "notes": notes,
        "roles": ROLES,
    }


def totals_by_role(lines: list[dict]) -> list[dict]:
    totals: dict[str, list[float]] = {}
    for line in lines:
        for role, share in line["roles"].items():
            t = totals.setdefault(role, [0.0, 0.0])
            t[0] += line["low"] * share
            t[1] += line["high"] * share
    return sorted(({"role": r, "label": ROLES[r], "low": _round(lo), "high": _round(hi)} for r, (lo, hi) in totals.items()),
                  key=lambda x: -x["high"])


def clean_cost_share(raw, cite) -> dict:
    """The cost-share rule as the AI read it. `cite` turns {doc, page} into a checked source or None."""
    raw = raw if isinstance(raw, dict) else {}
    required = raw.get("required") if isinstance(raw.get("required"), bool) else None
    basis = raw.get("basis") if raw.get("basis") in ("federal", "total") else None
    try:  # "1:1 match" is 100% of the federal amount, so federal-basis matches can pass 100
        percent = float(raw.get("percent"))
        percent = percent if 0 < percent < (300 if basis == "federal" else 100) else None
    except (TypeError, ValueError):
        percent = None
    types = [t for t in (raw.get("types") or []) if t in ("cash", "in_kind")] if isinstance(raw.get("types"), list) else []
    if required is False:
        percent, basis = None, None
    return {
        "required": required,
        "percent": percent,
        "basis": basis or ("total" if percent else None),
        "basis_assumed": bool(percent and not basis),
        "types": types,
        "waiver": (str(raw.get("waiver") or "").strip()[:400] or None),
        "detail": (str(raw.get("detail") or "").strip()[:400] or None),
        "source": cite(raw),
    }


def clean_parts(raw, cite) -> list[dict]:
    parts = []
    for p in (raw if isinstance(raw, list) else [])[:14]:
        if not isinstance(p, dict) or not (p.get("item") or p.get("kind")):
            continue
        parts.append({"kind": p.get("kind") if p.get("kind") in KINDS else "other",
                      "item": str(p.get("item") or "").strip(), "detail": str(p.get("detail") or "").strip(),
                      "quantity": p.get("quantity"), "source": cite(p)})
    return parts


def clean_skills(raw, cite) -> list[dict]:
    skills = []
    for s in (raw if isinstance(raw, list) else [])[:6]:
        if isinstance(s, str):
            s = {"skill": s}
        if isinstance(s, dict) and str(s.get("skill") or "").strip():
            skills.append({"skill": str(s["skill"]).strip()[:80], "why": str(s.get("why") or "").strip()[:200] or None,
                           "source": cite(s)})
    return skills
