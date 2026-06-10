"""
Backward-compatible shim — delegates to app.core.database.

New code should import from ``app.core.database`` directly.
"""

from app.core.database import (  # noqa: F401
    DEMO_MODE,
    POSTGRES_CREATE_TABLES_SQL,
    SQLITE_CREATE_TABLES_SQL,
    _ADDED_COLUMNS,
    _existing_columns,
    _ensure_columns,
    create_tables,
    database_available,
    engine,
)
