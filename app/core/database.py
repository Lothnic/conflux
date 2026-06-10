"""
Database engine, schema, and session management.

This is the single source of truth for all database concerns.
The legacy ``db`` module re-exports from here for backward compatibility.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# ─── Demo mode flag ─────────────────────────────────────────────

DEMO_MODE = settings.demo_mode

# ─── Synchronous engine (worker scripts, legacy code) ───────────

def _postgres_url_with_driver(url: str, driver: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", f"postgresql+{driver}://", 1)
    return url


def _strip_query_keys(url: str, keys: set[str]) -> str:
    parts = urlsplit(url)
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in keys]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _has_required_ssl(url: str) -> bool:
    params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    return params.get("sslmode") in {"require", "verify-ca", "verify-full"}


def create_sync_engine() -> sa.Engine:
    sync_url = _postgres_url_with_driver(settings.database_url, "psycopg")
    engine_kwargs: dict = {}
    if settings.is_sqlite:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_pre_ping"] = True
    return sa.create_engine(sync_url, **engine_kwargs)


engine = create_sync_engine()

# ─── Async engine (FastAPI routes) ──────────────────────────────

def create_async_engine_instance() -> AsyncEngine:
    async_url = settings.database_url
    if async_url.startswith("sqlite:///"):
        async_url = async_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif async_url.startswith("postgresql://"):
        async_url = _postgres_url_with_driver(async_url, "asyncpg")

    engine_kwargs: dict = {}
    if settings.is_sqlite:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_pre_ping"] = True
        if async_url.startswith("postgresql+asyncpg://") and _has_required_ssl(async_url):
            engine_kwargs["connect_args"] = {"ssl": True}
        async_url = _strip_query_keys(async_url, {"sslmode", "channel_binding"})

    return create_async_engine(async_url, **engine_kwargs)


async_engine = create_async_engine_instance()

# ─── Session factories ──────────────────────────────────────────

SyncSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_sync_session():
    """Dependency for synchronous database sessions."""
    with SyncSessionLocal() as session:
        try:
            yield session
        finally:
            session.close()


# ─── Schema DDL ─────────────────────────────────────────────────

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
    step_id      TEXT PRIMARY KEY,
    run_id       TEXT REFERENCES agent_runs(run_id),
    step_name    TEXT,
    tool_name    TEXT,
    status       TEXT,
    input_json   TEXT,
    output_json  TEXT,
    created_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
"""

# Columns added after the initial schema shipped.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "thread_geo": [
        ("location_text", "TEXT"),
        ("location_method", "TEXT"),
        ("location_confidence", "REAL" if settings.is_sqlite else "DOUBLE PRECISION"),
        ("location_precision_meters", "INTEGER"),
        ("geocoder_provider", "TEXT"),
        ("geocoder_query", "TEXT"),
        ("geocoder_raw", "TEXT"),
    ],
    "cluster_results": [
        ("location_confidence", "REAL" if settings.is_sqlite else "DOUBLE PRECISION"),
        ("location_precision_meters", "INTEGER"),
    ],
    "llm_proposals": [
        ("communication_plan", "TEXT"),
        ("responsible_agencies", "TEXT"),
        ("impact_rationale", "TEXT"),
    ],
}


def _existing_columns(conn: sa.Connection, table: str) -> set[str]:
    if settings.is_sqlite:
        rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
        return {r[1] for r in rows}
    rows = conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _ensure_columns() -> None:
    """Add any missing columns to existing tables."""
    for table, columns in _ADDED_COLUMNS.items():
        with engine.begin() as conn:
            present = _existing_columns(conn, table)
        for name, coltype in columns:
            if name in present:
                continue
            with engine.begin() as conn:
                conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))


_db_available: bool | None = None


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


def create_tables() -> None:
    """Create schema and apply idempotent column additions."""
    with engine.begin() as conn:
        if settings.is_sqlite:
            conn.execute(sa.text("PRAGMA foreign_keys = ON"))
        sql = SQLITE_CREATE_TABLES_SQL if settings.is_sqlite else POSTGRES_CREATE_TABLES_SQL
        for stmt in sql.strip().split(";"):
            if stmt.strip():
                conn.execute(sa.text(stmt))
    _ensure_columns()


def init_db_sync() -> bool:
    """Create tables if the database is available. Returns False otherwise."""
    if DEMO_MODE:
        return False
    if not database_available():
        return False
    create_tables()
    return True


# ─── Async lifecycle ────────────────────────────────────────────

async def init_db() -> None:
    """Initialize database tables on startup (async, for lifespan)."""
    if DEMO_MODE:
        return
    with engine.begin() as conn:
        if settings.is_sqlite:
            conn.execute(sa.text("PRAGMA foreign_keys = ON"))
        sql = SQLITE_CREATE_TABLES_SQL if settings.is_sqlite else POSTGRES_CREATE_TABLES_SQL
        for stmt in sql.strip().split(";"):
            if stmt.strip():
                conn.execute(sa.text(stmt))
    _ensure_columns()


@asynccontextmanager
async def lifespan(app):  # type: ignore[no-untyped-def]
    """Application lifespan manager."""
    await init_db()
    yield
    await async_engine.dispose()
