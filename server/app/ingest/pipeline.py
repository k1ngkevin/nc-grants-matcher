"""Daily ingestion: pull -> normalize -> enrich -> guardrails -> store -> embed."""
import json
import logging
from collections import Counter
from datetime import date, datetime, timezone

from .. import db, guardrails
from ..matching import embeddings
from . import grantsgov, samgov, usaspending
from .sample_data import sample_records

log = logging.getLogger(__name__)

COLUMNS = ["id", "source", "number", "title", "federal_agency", "federal_agency_code", "description", "status",
           "open_date", "close_date", "award_ceiling", "award_floor", "estimated_funding", "expected_awards",
           "eligibility_codes", "eligibility_text", "funding_instruments", "competition", "categories",
           "aln_numbers", "cost_sharing", "url", "nc_past_funding", "is_sample"]


def _store(opps: list[dict], source: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.session() as conn:
        existing = {r["id"]: r["first_seen_at"] for r in conn.execute("SELECT id, first_seen_at FROM opportunities WHERE source=?", (source,))}
        keep_ids = {o["id"] for o in opps}
        for o in opps:
            row = {c: o.get(c) for c in COLUMNS}
            for c in ("eligibility_codes", "funding_instruments", "categories", "aln_numbers"):
                row[c] = json.dumps(row[c] or [])
            row["first_seen_at"] = existing.get(o["id"]) or now
            row["updated_at"] = now
            cols = list(row)
            conn.execute(
                f"INSERT INTO opportunities ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in cols if c not in ('id', 'first_seen_at'))}",
                [row[c] for c in cols],
            )
        # Remove opportunities that disappeared from the source, unless a reviewer acted on them.
        decided = {r["opportunity_id"] for r in conn.execute("SELECT DISTINCT opportunity_id FROM decisions")}
        for oid in set(existing) - keep_ids - decided:
            conn.execute("DELETE FROM opportunities WHERE id=?", (oid,))


def run(sample: bool = False, max_records: int | None = None, skip_usaspending: bool = False) -> dict:
    db.init_db()
    if sample:
        opps = [grantsgov.normalize(h, d) for h, d in sample_records()]
        for o in opps:
            o["id"] = o["id"].replace("grantsgov:", "sample:")
            o["source"] = "sample"
            o["is_sample"] = 1
        source = "sample"
    else:
        opps = grantsgov.fetch_all(max_records=max_records)
        samgov.enrich(opps)
        source = "grants.gov"

    if not skip_usaspending and not sample:
        try:
            totals = usaspending.nc_totals_by_aln()
            for o in opps:
                amt = sum(totals.get(a, 0) for a in o.get("aln_numbers", []))
                o["nc_past_funding"] = amt or None
        except Exception as e:
            log.warning("USAspending enrichment skipped: %s", e)

    dropped = Counter()
    kept = []
    for o in opps:
        ok, reason = guardrails.check(o)
        if ok:
            kept.append(o)
        else:
            dropped[reason] += 1

    _store(kept, source)
    if source != "sample":  # live data replaces the demo set (keeping anything a reviewer acted on)
        with db.session() as conn:
            conn.execute("DELETE FROM opportunities WHERE source='sample' AND id NOT IN (SELECT opportunity_id FROM decisions)")
    summary = {
        "source": source,
        "fetched": len(opps),
        "kept": len(kept),
        "dropped": dict(dropped),
    }
    # The data is already stored, so an embedding problem must not stop the ingest from finishing
    # (and bumping ingest_version below); matching uses local TF-IDF until the vectors exist.
    try:
        embeddings.refresh_opportunity_embeddings()
    except embeddings.EmbeddingError as e:
        log.error("Opportunities were saved but not embedded, so matching uses local text similarity. "
                  "Fix the Azure setting, then run `python -m app.ingest --embed`. %s", e)
        summary["embedding_error"] = str(e)
    summary["ran_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary["as_of"] = date.today().isoformat()
    db.set_meta("last_ingest", summary)
    db.set_meta("ingest_version", summary["ran_at"])
    log.info("Ingest summary: %s", summary)
    return summary
