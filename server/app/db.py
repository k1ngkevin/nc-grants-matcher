"""Storage. PostgreSQL when DATABASE_URL is set (docker compose), otherwise a SQLite file.

The rest of the app writes SQLite-style SQL (`?` placeholders, `cur.lastrowid`, rows readable by
index or column name). For Postgres, a thin wrapper below translates that, so call sites don't change.
Stick to SQL both databases understand (e.g. INSERT ... ON CONFLICT, not INSERT OR REPLACE).
`BEGIN IMMEDIATE` is the one SQLite statement translated (to a Postgres transaction lock).
"""
import json
import re
import sqlite3
from contextlib import contextmanager
from decimal import Decimal

from .config import DATABASE_URL, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_rate_events (
    bucket TEXT NOT NULL,
    subject TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_rate ON api_rate_events(bucket, subject, created_at);
CREATE INDEX IF NOT EXISTS idx_api_rate_created ON api_rate_events(created_at);
CREATE TABLE IF NOT EXISTS public_subscription_requests (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    agency_id TEXT NOT NULL,
    filters TEXT NOT NULL,
    frequency TEXT NOT NULL,
    top_n INTEGER NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS public_subscriptions (
    subscription_id INTEGER PRIMARY KEY
);
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
CREATE TABLE IF NOT EXISTS research (     -- in-depth research results, one per grant and agency
    opportunity_id TEXT NOT NULL,
    agency_id TEXT NOT NULL,
    result TEXT NOT NULL,             -- JSON
    created_at TEXT,
    PRIMARY KEY (opportunity_id, agency_id)
);
CREATE TABLE IF NOT EXISTS opportunity_documents (  -- notice attachments, so the PDF proxy only serves real ones
    opportunity_id TEXT NOT NULL,
    att_id TEXT NOT NULL,
    file_name TEXT,
    mime TEXT,
    size INTEGER,
    PRIMARY KEY (opportunity_id, att_id)
);
CREATE TABLE IF NOT EXISTS feedback (     -- what people report from the site
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,               -- problem | idea | scoring | other
    message TEXT NOT NULL,
    email TEXT,                       -- optional, for a reply
    agency_id TEXT,
    opportunity_id TEXT,
    page TEXT,                        -- which view they were on
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

JSON_FIELDS = ("eligibility_codes", "funding_instruments", "categories", "aln_numbers", "embedding", "filters")


# ---------------- PostgreSQL ----------------
# Tables whose id is generated, so INSERTs into them get RETURNING id for cur.lastrowid.
_SERIAL_TABLES = {"agency_documents", "projects", "decisions", "subscriptions", "feedback"}
_INSERT_RE = re.compile(r"\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)


def _pg_schema() -> str:
    s = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    s = re.sub(r"\bINTEGER\b", "BIGINT", s)  # SQLite integers are 64-bit; dollar amounts pass 2^31
    s = re.sub(r"\bREAL\b", "DOUBLE PRECISION", s)
    # Same text format SQLite's CURRENT_TIMESTAMP gives, in UTC.
    return s.replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT (to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))")


class Row:
    """Like sqlite3.Row: row[0], row["col"], dict(row), and tuple unpacking all work."""
    __slots__ = ("_keys", "_values")

    def __init__(self, keys, values):
        self._keys = keys
        self._values = values

    def keys(self):
        return list(self._keys)

    def __getitem__(self, k):
        if isinstance(k, (int, slice)):
            return self._values[k]
        return self._values[self._keys.index(k)]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


def _pg_value(v):
    if isinstance(v, Decimal):  # SUM() of integers comes back as numeric
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _pg_row_factory(cursor):
    keys = tuple(c.name for c in cursor.description or ())
    return lambda values: Row(keys, tuple(_pg_value(v) for v in values))


def _pg_sql(sql: str) -> str:
    return sql.replace("%", "%%").replace("?", "%s")


def _pg_params(params):
    return [int(p) if isinstance(p, bool) else p for p in params]


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class _PgConnection:
    """Gives a psycopg connection the parts of the sqlite3.Connection API the app uses."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            # SQLite's "take the write lock now". psycopg already opened a transaction, so take a
            # transaction-wide lock instead; it's released at commit/rollback, like SQLite's.
            sql = "SELECT pg_advisory_xact_lock(4243)"
        m = _INSERT_RE.match(sql)
        wants_id = bool(m and m.group(1).lower() in _SERIAL_TABLES and "RETURNING" not in sql.upper())
        if wants_id:
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor()
        if params:
            cur.execute(_pg_sql(sql), _pg_params(params))
        else:
            cur.execute(sql)  # no params: psycopg leaves % and ? alone
        return _PgCursor(cur, cur.fetchone()[0] if wants_id else None)

    def executemany(self, sql: str, seq):
        cur = self._conn.cursor()
        cur.executemany(_pg_sql(sql), [_pg_params(p) for p in seq])
        return _PgCursor(cur)

    def executescript(self, script: str):
        self._conn.execute(script)

    def commit(self):
        self._conn.commit()


_pool = None


def _pg_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True,
                               kwargs={"row_factory": _pg_row_factory})
    return _pool


# ---------------- SQLite ----------------
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def session():
    if DATABASE_URL:
        with _pg_pool().connection() as raw:  # commits on success, rolls back on error
            yield _PgConnection(raw)
        return
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        if DATABASE_URL:
            conn.execute("SELECT pg_advisory_xact_lock(4242)")  # api + ingest starting together
            conn.executescript(_pg_schema())
        else:
            conn.executescript(SCHEMA)


def row_to_dict(row) -> dict:
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
