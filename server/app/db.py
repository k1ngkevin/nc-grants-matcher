"""SQLite storage. One file, no server, easy to swap for Azure SQL / Postgres later."""
import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,              -- source:native_id, e.g. grantsgov:357898
    source TEXT NOT NULL,
    number TEXT,
    title TEXT NOT NULL,
    federal_agency TEXT,
    federal_agency_code TEXT,
    description TEXT,
    status TEXT,                      -- forecasted | posted
    open_date TEXT,                   -- ISO yyyy-mm-dd
    close_date TEXT,                  -- ISO yyyy-mm-dd or NULL
    award_ceiling INTEGER,
    award_floor INTEGER,
    estimated_funding INTEGER,
    expected_awards INTEGER,
    eligibility_codes TEXT,           -- JSON list of grants.gov applicant type codes
    eligibility_text TEXT,
    funding_instruments TEXT,         -- JSON list, e.g. ["G","CA"]
    competition TEXT,                 -- grants.gov opportunity category: D discretionary, M mandatory, C continuation...
    categories TEXT,                  -- JSON list
    aln_numbers TEXT,                 -- JSON list of Assistance Listing numbers
    cost_sharing INTEGER,             -- 1 = match required, 0 = no, NULL = unknown
    url TEXT,
    nc_past_funding INTEGER,          -- $ NC recipients received under these ALNs (USAspending)
    is_sample INTEGER DEFAULT 0,
    embedding TEXT,                   -- JSON vector when Azure embeddings are enabled
    first_seen_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS agency_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agency_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agency_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    embedding TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agency_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    action TEXT NOT NULL,             -- pursue | save | dismiss
    reason TEXT,
    note TEXT,
    score REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_decisions_agency ON decisions(agency_id, opportunity_id);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    agency_id TEXT NOT NULL,
    filters TEXT NOT NULL,            -- JSON of the search filters at signup time
    frequency TEXT NOT NULL,          -- daily | weekly | biweekly | monthly
    top_n INTEGER NOT NULL DEFAULT 10,
    token TEXT NOT NULL UNIQUE,       -- used for confirm / unsubscribe links
    confirmed INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    last_sent_at TEXT,
    next_send_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS explanations (
    cache_key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

JSON_FIELDS = ("eligibility_codes", "funding_instruments", "categories", "aln_numbers", "embedding", "filters")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for f in JSON_FIELDS:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                pass
    return d


def get_meta(key: str, default=None):
    with session() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_meta(key: str, value) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
