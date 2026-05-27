"""
Shared database setup for Conflux.
Defaults to SQLite (local) with PostgreSQL as optional target.
"""

import os
import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv(override=True)

DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/conflux.db")
_is_sqlite = DB_URL.startswith("sqlite")

engine_kwargs: dict = {}
if _is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True

engine = sa.create_engine(DB_URL, **engine_kwargs)
_db_available: bool | None = None

CREATE_TABLES_SQL = """
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
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS thread_geo (
    thread_id    TEXT PRIMARY KEY,
    lat          REAL,
    lng          REAL,
    source       TEXT,
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
    centroid_lat    REAL,
    centroid_lng    REAL,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""


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
        for stmt in CREATE_TABLES_SQL.strip().split(";"):
            if stmt.strip():
                conn.execute(sa.text(stmt))
