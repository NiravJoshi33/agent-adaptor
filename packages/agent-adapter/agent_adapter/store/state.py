"""State store — general-purpose JSON key-value persistence."""

from __future__ import annotations

import json
from typing import Any

from agent_adapter.store.database import Database


class StateStore:
    """CRUD for JSON state in SQLite, scoped by (namespace, key)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def set(self, namespace: str, key: str, data: Any) -> None:
        serialized = json.dumps(data)
        await self._db.conn.execute(
            """
            INSERT INTO state (namespace, key, data, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(namespace, key) DO UPDATE SET
                data = excluded.data,
                updated_at = datetime('now')
            """,
            (namespace, key, serialized),
        )
        await self._db.conn.commit()

    async def get(self, namespace: str, key: str) -> Any | None:
        cursor = await self._db.conn.execute(
            "SELECT data FROM state WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    async def list(self, namespace: str, prefix: str = "") -> list[str]:
        cursor = await self._db.conn.execute(
            "SELECT key FROM state WHERE namespace = ? AND key LIKE ? ORDER BY key",
            (namespace, f"{prefix}%"),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def delete(self, namespace: str, key: str) -> bool:
        cursor = await self._db.conn.execute(
            "DELETE FROM state WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0
