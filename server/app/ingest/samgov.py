"""SAM.gov Assistance Listings (needs a free API key from api.sam.gov; set SAM_API_KEY).

Assistance Listings describe every federal assistance *program* (objectives, who can
apply, formula vs. project grants). Many state formula programs never appear as a
Grants.gov opportunity, so we use these descriptions to enrich matching text.

NOTE: this endpoint and response shape were written from the public docs but could not
be tested from the build sandbox. Verify with:  python -m app.ingest --sam-check 66.460
If the URL differs, set SAM_ASSISTANCE_URL.
"""
import logging
import os

import requests

from ..config import SAM_API_KEY
from ..normalize import strip_html

log = logging.getLogger(__name__)
URL = os.getenv("SAM_ASSISTANCE_URL", "https://api.sam.gov/assistance-listings/v1/search")


def _find_records(payload):
    """Return the first list of dicts found in the response, wherever it is nested."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for v in payload.values():
            found = _find_records(v)
            if found:
                return found
    return []


class RateLimited(Exception):
    """SAM.gov returned 429: the key's request quota is used up, so further calls will fail too."""


def lookup(aln: str) -> dict | None:
    """Raises RateLimited on HTTP 429; any other failure is logged and returns None."""
    if not SAM_API_KEY:
        return None
    try:
        r = requests.get(URL, params={"api_key": SAM_API_KEY, "assistanceListingNumber": aln, "limit": 1}, timeout=30)
        if r.status_code == 429:
            raise RateLimited(r.headers.get("Retry-After") or "")
        r.raise_for_status()
    except RateLimited:
        raise
    except Exception as e:
        # requests puts the full URL (including api_key) in its error text; never log the key.
        log.warning("SAM.gov lookup %s failed: %s", aln, str(e).replace(SAM_API_KEY, "<SAM_API_KEY>"))
        return None
    records = _find_records(r.json())
    if not records:
        return None
    rec = records[0]
    text = " ".join(strip_html(str(rec.get(k, ""))) for k in ("title", "objective", "objectives", "programDescription", "overview") if rec.get(k))
    return {"aln": aln, "text": text[:3000]}


def enrich(opps: list[dict], limit: int = 400) -> int:
    """Append program objectives from SAM.gov to each opportunity's description."""
    if not SAM_API_KEY:
        log.info("SAM.gov: skipped (no SAM_API_KEY)")
        return 0
    wanted = list(dict.fromkeys(a for opp in opps for a in opp.get("aln_numbers", [])[:2]))[:limit]
    cache: dict[str, dict | None] = {}
    for aln in wanted:
        try:
            cache[aln] = lookup(aln)
        except RateLimited as e:
            retry = f" (Retry-After: {e})" if str(e) else ""
            log.warning("SAM.gov: rate limit reached (HTTP 429)%s after %s of %s lookups; "
                        "skipping the rest for this run.", retry, len(cache), len(wanted))
            break
    n = 0
    for opp in opps:
        extra = " ".join(c["text"] for a in opp.get("aln_numbers", [])[:2] if (c := cache.get(a)) and c.get("text"))
        if extra:
            opp["description"] = f"{opp['description']} Program objectives (SAM.gov): {extra}"
            n += 1
    log.info("SAM.gov: enriched %s opportunities from %s listings", n, len(cache))
    return n
