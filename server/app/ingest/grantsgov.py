"""Grants.gov public REST API (no key needed).

  search2          POST https://api.grants.gov/v1/api/search2
  fetchOpportunity POST https://api.grants.gov/v1/api/fetchOpportunity

Eligibility is filtered at the source (only applicant types NC state entities can
use), and expired opportunities are skipped before we spend calls on details.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

from ..config import STATE_ELIGIBILITY_CODES
from ..normalize import parse_date, parse_money, strip_html

log = logging.getLogger(__name__)
BASE = "https://api.grants.gov/v1/api"
PAGE_SIZE = 250
TIMEOUT = 45


def _post(endpoint: str, body: dict) -> dict:
    r = requests.post(f"{BASE}/{endpoint}", json=body, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    if payload.get("errorcode", 0) not in (0, "0"):
        raise RuntimeError(f"grants.gov {endpoint} error: {payload.get('msg')}")
    return payload.get("data") or {}


def search_hits(max_records: int | None = None) -> list[dict]:
    """All forecasted + posted opportunities open to state governments / public higher ed."""
    hits, start = [], 0
    while True:
        data = _post("search2", {
            "rows": PAGE_SIZE,
            "startRecordNum": start,
            "oppStatuses": "forecasted|posted",
            "eligibilities": "|".join(STATE_ELIGIBILITY_CODES),
        })
        page = data.get("oppHits") or []
        hits.extend(page)
        total = int(data.get("hitCount") or 0)
        start += PAGE_SIZE
        log.info("grants.gov search2: %s / %s", len(hits), total)
        if not page or start >= total or (max_records and len(hits) >= max_records):
            break
    return hits[:max_records] if max_records else hits


def _not_expired(hit: dict) -> bool:
    close = parse_date(hit.get("closeDate"))
    return close is None or close >= date.today().isoformat()


def fetch_detail(opp_id) -> dict | None:
    try:
        return _post("fetchOpportunity", {"opportunityId": int(opp_id)})
    except Exception as e:  # one bad record should not stop the run
        log.warning("fetchOpportunity %s failed: %s", opp_id, e)
        return None


def _codes(items) -> list[str]:
    return [str(i.get("id")) for i in (items or []) if isinstance(i, dict) and i.get("id") is not None]


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return None


def normalize(hit: dict, detail: dict | None) -> dict:
    """Map a search hit + fetchOpportunity detail into our opportunity row.
    Field names are read defensively because forecasts and synopses differ."""
    detail = detail or {}
    status = (hit.get("oppStatus") or "").lower() or ("forecasted" if detail.get("forecast") and not detail.get("synopsis") else "posted")
    body = (detail.get("forecast") if status == "forecasted" else detail.get("synopsis")) or detail.get("synopsis") or detail.get("forecast") or {}

    close = parse_date(_first(body, "responseDateStr", "responseDate", "estApplicationResponseDateStr", "estApplicationResponseDate")) \
        or parse_date(hit.get("closeDate"))
    open_ = parse_date(_first(body, "postingDateStr", "postingDate", "estSynopsisPostingDateStr", "estSynopsisPostingDate")) \
        or parse_date(hit.get("openDate"))

    cost = body.get("costSharing")
    cost_sharing = None if cost is None else (1 if str(cost).lower() in ("true", "y", "yes", "1") else 0)

    alns = [c.get("cfdaNumber") for c in (detail.get("cfdas") or detail.get("alns") or []) if isinstance(c, dict) and c.get("cfdaNumber")]
    if not alns:
        alns = hit.get("alnist") or hit.get("cfdaList") or []
    program_titles = " ".join(c.get("programTitle", "") for c in (detail.get("cfdas") or []) if isinstance(c, dict))

    oid = str(hit.get("id") or detail.get("id"))
    category = (detail.get("opportunityCategory") or {}).get("category")
    description = strip_html(_first(body, "synopsisDesc", "forecastDesc", "description") or "")
    if program_titles:
        description = f"{description} Programs: {program_titles}".strip()

    return {
        "id": f"grantsgov:{oid}",
        "source": "grants.gov",
        "number": hit.get("number") or detail.get("opportunityNumber"),
        "title": hit.get("title") or detail.get("opportunityTitle") or "(untitled)",
        "federal_agency": _first(body, "agencyName") or hit.get("agencyName") or hit.get("agency") or hit.get("agencyCode"),
        "federal_agency_code": hit.get("agencyCode") or detail.get("owningAgencyCode"),
        "description": description,
        "status": status,
        "open_date": open_,
        "close_date": close,
        "award_ceiling": parse_money(_first(body, "awardCeiling")),
        "award_floor": parse_money(_first(body, "awardFloor")),
        "estimated_funding": parse_money(_first(body, "estimatedFunding", "estimatedFundingFormatted")),
        "expected_awards": parse_money(_first(body, "numberOfAwards", "expectedNumberOfAwards")),
        "eligibility_codes": _codes(body.get("applicantTypes")) or [],
        "eligibility_text": strip_html(_first(body, "applicantEligibilityDesc") or ""),
        "funding_instruments": _codes(body.get("fundingInstruments")),
        "competition": category,
        "categories": [c.get("description") for c in (body.get("fundingActivityCategories") or []) if isinstance(c, dict)],
        "aln_numbers": [a for a in alns if a],
        "cost_sharing": cost_sharing,
        "url": f"https://www.grants.gov/search-results-detail/{oid}",
    }


def fetch_all(max_records: int | None = None, workers: int = 8) -> list[dict]:
    hits = [h for h in search_hits(max_records) if _not_expired(h)]
    log.info("grants.gov: fetching details for %s open opportunities", len(hits))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        details = list(pool.map(lambda h: fetch_detail(h.get("id")), hits))
    return [normalize(h, d) for h, d in zip(hits, details)]
