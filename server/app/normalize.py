"""Turn raw source records into one common shape, and the plain-language labels
the UI shows (timing category, grant type, match requirement)."""
import html
import re
from datetime import date, datetime

from .config import STANDARD_MAX_DAYS, URGENT_DAYS

_DATE_FORMATS = [
    "%m/%d/%Y",                 # search2: 12/15/2025
    "%Y-%m-%d",
    "%Y-%m-%d-%H-%M-%S",        # fetchOpportunity *Str fields: 2025-02-28-00-00-00
    "%b %d, %Y %I:%M:%S %p",    # Feb 28, 2025 12:00:00 AM (timezone stripped first)
    "%b %d, %Y",
    "%Y-%m-%dT%H:%M:%S",
]


def parse_date(value) -> str | None:
    """Best-effort parse into ISO yyyy-mm-dd. Returns None if empty/unparseable."""
    if not value:
        return None
    s = str(value).strip()
    s = re.sub(r"\s+(EST|EDT|CST|CDT|MST|MDT|PST|PDT|UTC|GMT)$", "", s)
    s = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", "", s)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_money(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    digits = re.sub(r"[^\d.]", "", str(value))
    if not digits:
        return None
    try:
        n = int(float(digits))
    except ValueError:
        return None
    return n if n > 0 else None


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<(br|p|li|div)[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def days_left(close_date: str | None, today: date | None = None) -> int | None:
    if not close_date:
        return None
    today = today or date.today()
    return (date.fromisoformat(close_date) - today).days


def timing_category(status: str, close_date: str | None, today: date | None = None) -> str | None:
    """Temporal guardrail. Returns None when the opportunity must be dropped (deadline passed).
    Categories: forecasted | urgent (<=14 days) | standard (15-60 days) | later (60+ days or no date)."""
    d = days_left(close_date, today)
    if d is not None and d < 0:
        return None
    if status == "forecasted":
        return "forecasted"
    if d is None:
        return "later"  # posted with no listed close date (often rolling / open until funds run out)
    if d <= URGENT_DAYS:
        return "urgent"
    if d <= STANDARD_MAX_DAYS:
        return "standard"
    return "later"


TIMING_LABELS = {
    "urgent": "Closes within 14 days",
    "standard": "Closes in 15-60 days",
    "later": "Closes in 60+ days",
    "forecasted": "Forecast (not open yet)",
}

INSTRUMENT_LABELS = {
    "G": ("Grant", "Money you don't repay. Your agency runs the project and reports on results."),
    "CA": ("Cooperative agreement", "Like a grant, but the federal agency stays closely involved in the work."),
    "PC": ("Procurement contract", "A federal purchase of services. Different rules than a grant."),
    "O": ("Other", "See the full announcement for the funding type."),
}

CATEGORY_LABELS = {
    "D": ("Competitive", "You submit an application and compete against other applicants."),
    "M": ("Formula / mandatory", "Funds are set by law or formula. Usually requires a state plan or application, not a competition."),
    "C": ("Continuation", "Generally only open to current grantees renewing an existing award."),
    "E": ("Earmark", "Funding directed by Congress to a named recipient."),
    "O": ("Other", "See the announcement for how awards are made."),
}


def grant_type(instruments: list[str], category: str | None, cost_sharing: int | None) -> dict:
    instr = (instruments or ["G"])[0]
    i_label, i_help = INSTRUMENT_LABELS.get(instr, INSTRUMENT_LABELS["O"])
    c_label, c_help = CATEGORY_LABELS.get(category or "D", CATEGORY_LABELS["D"])
    if cost_sharing == 1:
        match = "Requires matching funds"
    elif cost_sharing == 0:
        match = "No match required"
    else:
        match = "Match not stated"
    return {
        "instrument": i_label, "instrument_help": i_help,
        "competition": c_label, "competition_help": c_help,
        "match": match,
    }


def best_award_amount(opp: dict) -> int | None:
    """Financial guardrail input: award ceiling if listed, otherwise the average award
    (estimated total funding / expected number of awards), otherwise None (unknown)."""
    if opp.get("award_ceiling"):
        return opp["award_ceiling"]
    total, n = opp.get("estimated_funding"), opp.get("expected_awards")
    if total and n:
        return total // max(n, 1)
    if total and not n:
        return total
    return None
