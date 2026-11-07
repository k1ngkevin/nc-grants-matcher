"""The four mandatory guardrails, in one place so ingest and search apply the same rules.
Ingest drops what can never qualify; search re-applies the rules daily (dates move)."""
from datetime import date

from .agencies import eligibility_fit
from .config import FINANCIAL_FLOOR
from .normalize import best_award_amount, timing_category


def check(opp: dict, agency: dict | None = None, floor: int = FINANCIAL_FLOOR,
          include_unknown_amount: bool = True, today: date | None = None) -> tuple[bool, str]:
    """Return (keep, reason). `agency` is optional at ingest time."""
    # 1. Temporal: drop anything whose deadline has passed.
    if timing_category(opp.get("status", "posted"), opp.get("close_date"), today) is None:
        return False, "deadline passed"
    # 2. Financial floor: never below $50K; users may raise it, not lower it.
    floor = max(floor, FINANCIAL_FLOOR)
    amount = best_award_amount(opp)
    if amount is None:
        if not include_unknown_amount:
            return False, "award amount not listed"
    elif amount < floor:
        return False, f"award below ${floor:,}"
    # 3. Eligibility pre-screen (before scoring).
    codes = opp.get("eligibility_codes") or []
    if agency is not None:
        fit, _ = eligibility_fit(agency, codes)
        if fit == 0:
            return False, "not eligible"
    elif not set(codes) & {"00", "06", "25", "99"}:
        return False, "not eligible for state government or public higher ed"
    return True, "ok"
