"""SQLite database — schema initialization and connection management."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS wallet (
    public_key            TEXT PRIMARY KEY,
    encrypted_private_key BLOB NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS secrets (
    platform        TEXT NOT NULL,
    key             TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (platform, key)
);

CREATE TABLE IF NOT EXISTS secret_migration_failures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT NOT NULL,
    key             TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    error           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS state (
    namespace   TEXT NOT NULL,
    key         TEXT NOT NULL,
    data        TEXT NOT NULL,  -- JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (namespace, key)
);

CREATE TABLE IF NOT EXISTS capability_config (
    name               TEXT PRIMARY KEY,
    enabled            INTEGER NOT NULL DEFAULT 0,
    pricing_amount     REAL,
    pricing_currency   TEXT,
    pricing_model      TEXT,
    pricing_item_field TEXT,
    pricing_floor      REAL,
    pricing_ceiling    REAL,
    custom_description TEXT,
    source_hash        TEXT,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id                 TEXT PRIMARY KEY,
    capability         TEXT NOT NULL,
    platform           TEXT NOT NULL DEFAULT '',
    platform_ref       TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'pending',
    input_hash         TEXT,
    output_hash        TEXT,
    payment_protocol   TEXT,
    payment_status     TEXT,
    payment_amount     REAL,
    payment_currency   TEXT,
    llm_input_tokens   INTEGER,
    llm_output_tokens  INTEGER,
    llm_estimated_cost REAL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at       TEXT
);

CREATE TABLE IF NOT EXISTS decision_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    platform    TEXT NOT NULL DEFAULT '',
    detail      TEXT,  -- JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    model            TEXT NOT NULL DEFAULT '',
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    estimated_cost   REAL NOT NULL DEFAULT 0.0,
    currency         TEXT NOT NULL DEFAULT 'USD',
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS inbound_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type  TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',
    channel      TEXT NOT NULL DEFAULT '',
    event_type   TEXT NOT NULL DEFAULT '',
    payload      TEXT NOT NULL DEFAULT '',
    headers      TEXT NOT NULL DEFAULT '{}',
    received_at  TEXT NOT NULL DEFAULT (datetime('now')),
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS platforms (
    base_url            TEXT PRIMARY KEY,
    platform_name       TEXT,
    agent_id            TEXT,
    registration_status TEXT,
    registered_at       TEXT,
    last_active_at      TEXT,
    metadata            TEXT  -- JSON
);
"""


class Database:
    """Async SQLite wrapper with schema initialization."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
