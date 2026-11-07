"""USAspending.gov (no key): how much federal assistance NC recipients received
under each Assistance Listing last fiscal year. Shown on each grant as
"NC received $X under this program" - a quick signal for 'look at past grants'."""
import logging
from datetime import date

import requests

log = logging.getLogger(__name__)
URL = "https://api.usaspending.gov/api/v2/search/spending_by_category/cfda/"
GRANT_TYPES = ["02", "03", "04", "05"]  # block, formula, project grants, cooperative agreements


def last_fiscal_year() -> tuple[str, str]:
    today = date.today()
    fy_end_year = today.year if today.month >= 10 else today.year - 1
    return f"{fy_end_year - 1}-10-01", f"{fy_end_year}-09-30"


def nc_totals_by_aln(max_pages: int = 30) -> dict[str, int]:
    start, end = last_fiscal_year()
    totals: dict[str, int] = {}
    for page in range(1, max_pages + 1):
        r = requests.post(URL, timeout=60, json={
            "filters": {
                "recipient_locations": [{"country": "USA", "state": "NC"}],
                "time_period": [{"start_date": start, "end_date": end}],
                "award_type_codes": GRANT_TYPES,
            },
            "limit": 100,
            "page": page,
        })
        r.raise_for_status()
        data = r.json()
        for row in data.get("results", []):
            if row.get("code") and row.get("amount"):
                totals[row["code"]] = int(row["amount"])
        if not (data.get("page_metadata") or {}).get("hasNext"):
            break
    log.info("USAspending: NC totals for %s programs (FY %s-%s)", len(totals), start[:4], end[:4])
    return totals
