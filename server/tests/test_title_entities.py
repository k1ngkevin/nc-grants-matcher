import pytest

from app import db
from app.ingest import grantsgov


@pytest.mark.parametrize("title, expected", [
    ("Readiness and Recreation Initiative (RARI) &ndash; Recurring 5 Year Notice",
     "Readiness and Recreation Initiative (RARI) – Recurring 5 Year Notice"),
    ("Research &amp; Development &#8212; &#34;Round 2&#34;", 'Research & Development — "Round 2"'),
    ("Research & Development – Round 2", "Research & Development – Round 2"),
    ("Projects < $500,000", "Projects < $500,000"),
])
@pytest.mark.parametrize("from_detail", [False, True])
def test_import_decodes_title_entities(title, expected, from_detail):
    hit = {"id": "title-test"}
    detail = {}
    if from_detail:
        detail["opportunityTitle"] = title
    else:
        hit["title"] = title
    assert grantsgov.normalize(hit, detail)["title"] == expected


def test_startup_repairs_stored_titles_without_reimport():
    titles = {
        "title-encoded": ("RARI &ndash; Notice &amp; Recreation", "RARI – Notice & Recreation"),
        "title-plain": ("Research & Development – Round 2", "Research & Development – Round 2"),
    }
    try:
        with db.session() as conn:
            for oid, (title, _) in titles.items():
                conn.execute("INSERT INTO opportunities (id, source, title) VALUES (?, ?, ?)",
                             (oid, "grants.gov", title))
        db.init_db()
        db.init_db()
        with db.session() as conn:
            for oid, (_, expected) in titles.items():
                row = conn.execute("SELECT title FROM opportunities WHERE id=?", (oid,)).fetchone()
                assert row["title"] == expected
    finally:
        with db.session() as conn:
            for oid in titles:
                conn.execute("DELETE FROM opportunities WHERE id=?", (oid,))
