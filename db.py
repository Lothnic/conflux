"""
Shared database setup for Conflux.
Defaults to SQLite (local) with PostgreSQL as optional target.
"""

import os
from pathlib import Path
import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv(override=True)

DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/conflux.db")
_is_sqlite = DB_URL.startswith("sqlite")

if _is_sqlite and DB_URL != "sqlite:///:memory:":
    db_path = DB_URL.removeprefix("sqlite:///")
    Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

engine_kwargs: dict = {}
if _is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True

engine = sa.create_engine(DB_URL, **engine_kwargs)
_db_available: bool | None = None

SQLITE_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS daily_ingest (
    thread_id     TEXT PRIMARY KEY,
    subreddit     TEXT,
    title         TEXT,
    content       TEXT,
    flair         TEXT,
    upvotes       INTEGER,
    coordinates   TEXT,
    url           TEXT,
    published_at  TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cluster_results (
    cluster_id    TEXT PRIMARY KEY,
    cluster_label INTEGER,
    centroid_lat  REAL,
    centroid_lng  REAL,
    size          INTEGER,
    keywords      TEXT,
    location_confidence REAL,
    location_precision_meters INTEGER,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS thread_geo (
    thread_id    TEXT PRIMARY KEY,
    lat          REAL,
    lng          REAL,
    source       TEXT,
    location_text TEXT,
    location_method TEXT,
    location_confidence REAL,
    location_precision_meters INTEGER,
    geocoder_provider TEXT,
    geocoder_query TEXT,
    geocoder_raw TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS thread_cluster_map (
    thread_id     TEXT REFERENCES daily_ingest(thread_id),
    cluster_id    TEXT REFERENCES cluster_results(cluster_id),
    PRIMARY KEY (thread_id, cluster_id)
);

CREATE TABLE IF NOT EXISTS llm_proposals (
    proposal_id     TEXT PRIMARY KEY,
    cluster_id      TEXT,
    issue_type      TEXT,
    urgency         TEXT,
    summary         TEXT,
    recommendations TEXT,
    funding_sources TEXT,
    estimated_budget TEXT,
    communication_plan   TEXT,
    responsible_agencies TEXT,
    impact_rationale     TEXT,
    centroid_lat    REAL,
    centroid_lng    REAL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      TEXT PRIMARY KEY,
    cluster_id  TEXT,
    status      TEXT,
    started_at  TEXT DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_steps (
    step_id     TEXT PRIMARY KEY,
    run_id      TEXT REFERENCES agent_runs(run_id),
    step_name   TEXT,
    tool_name   TEXT,
    status      TEXT,
    input_json  TEXT,
    output_json TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

POSTGRES_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS daily_ingest (
    thread_id     TEXT PRIMARY KEY,
    subreddit     TEXT,
    title         TEXT,
    content       TEXT,
    flair         TEXT,
    upvotes       INTEGER,
    coordinates   TEXT,
    url           TEXT,
    published_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cluster_results (
    cluster_id    TEXT PRIMARY KEY,
    cluster_label INTEGER,
    centroid_lat  DOUBLE PRECISION,
    centroid_lng  DOUBLE PRECISION,
    size          INTEGER,
    keywords      TEXT,
    location_confidence DOUBLE PRECISION,
    location_precision_meters INTEGER,
    created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS thread_geo (
    thread_id    TEXT PRIMARY KEY,
    lat          DOUBLE PRECISION,
    lng          DOUBLE PRECISION,
    source       TEXT,
    location_text TEXT,
    location_method TEXT,
    location_confidence DOUBLE PRECISION,
    location_precision_meters INTEGER,
    geocoder_provider TEXT,
    geocoder_query TEXT,
    geocoder_raw TEXT,
    created_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS thread_cluster_map (
    thread_id     TEXT REFERENCES daily_ingest(thread_id),
    cluster_id    TEXT REFERENCES cluster_results(cluster_id),
    PRIMARY KEY (thread_id, cluster_id)
);

CREATE TABLE IF NOT EXISTS llm_proposals (
    proposal_id      TEXT PRIMARY KEY,
    cluster_id       TEXT UNIQUE,
    issue_type       TEXT,
    urgency          TEXT,
    summary          TEXT,
    recommendations  TEXT,
    funding_sources  TEXT,
    estimated_budget TEXT,
    communication_plan   TEXT,
    responsible_agencies TEXT,
    impact_rationale     TEXT,
    centroid_lat     DOUBLE PRECISION,
    centroid_lng     DOUBLE PRECISION,
    created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      TEXT PRIMARY KEY,
    cluster_id  TEXT,
    status      TEXT,
    started_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_steps (
    step_id     TEXT PRIMARY KEY,
    run_id      TEXT REFERENCES agent_runs(run_id),
    step_name   TEXT,
    tool_name   TEXT,
    status      TEXT,
    input_json  TEXT,
    output_json TEXT,
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
"""

# Columns added after the initial schema shipped. create_tables() applies these
# idempotently so existing databases (where CREATE TABLE IF NOT EXISTS is a no-op)
# pick up new columns without a migration framework.
_ADDED_COLUMNS = {
    "thread_geo": [
        ("location_text", "TEXT"),
        ("location_method", "TEXT"),
        ("location_confidence", "REAL" if _is_sqlite else "DOUBLE PRECISION"),
        ("location_precision_meters", "INTEGER"),
        ("geocoder_provider", "TEXT"),
        ("geocoder_query", "TEXT"),
        ("geocoder_raw", "TEXT"),
    ],
    "cluster_results": [
        ("location_confidence", "REAL" if _is_sqlite else "DOUBLE PRECISION"),
        ("location_precision_meters", "INTEGER"),
    ],
    "llm_proposals": [
        ("communication_plan", "TEXT"),
        ("responsible_agencies", "TEXT"),
        ("impact_rationale", "TEXT"),
    ],
}


def _existing_columns(conn, table: str) -> set[str]:
    if _is_sqlite:
        rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
        return {r[1] for r in rows}
    rows = conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _ensure_columns():
    """Add any missing columns to existing tables. CREATE TABLE IF NOT EXISTS is a
    no-op on databases that predate these columns, so we reconcile explicitly.
    Each ALTER runs in its own transaction so one failure can't poison the rest."""
    for table, columns in _ADDED_COLUMNS.items():
        with engine.begin() as conn:
            present = _existing_columns(conn, table)
        for name, coltype in columns:
            if name in present:
                continue
            with engine.begin() as conn:
                conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))


def database_available() -> bool:
    global _db_available
    if _db_available is not None:
        return _db_available
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        _db_available = True
    except Exception:
        _db_available = False
    return _db_available


def create_tables():
    with engine.begin() as conn:
        if _is_sqlite:
            conn.execute(sa.text("PRAGMA foreign_keys = ON"))
        sql = SQLITE_CREATE_TABLES_SQL if _is_sqlite else POSTGRES_CREATE_TABLES_SQL
        for stmt in sql.strip().split(";"):
            if stmt.strip():
                conn.execute(sa.text(stmt))
    _ensure_columns()
