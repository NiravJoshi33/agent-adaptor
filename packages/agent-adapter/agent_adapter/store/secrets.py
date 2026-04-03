"""Secrets store — encrypted credential management scoped by platform."""

from __future__ import annotations

from agent_adapter_contracts.secrets import SecretsBackend

from agent_adapter.store.database import Database


class SecretsStore:
    """CRUD for encrypted secrets in SQLite, scoped by (platform, key)."""

    def __init__(self, db: Database, backend: SecretsBackend) -> None:
        self._db = db
        self._backend = backend

    async def store(self, platform: str, key: str, value: str) -> None:
        encrypted = await self._backend.encrypt(value.encode())
        await self._db.conn.execute(
            """
            INSERT INTO secrets (platform, key, encrypted_value, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(platform, key) DO UPDATE SET
                encrypted_value = excluded.encrypted_value,
                updated_at = datetime('now')
            """,
            (platform, key, encrypted),
        )
        await self._db.conn.commit()

    async def retrieve(self, platform: str, key: str) -> str | None:
        cursor = await self._db.conn.execute(
            "SELECT encrypted_value FROM secrets WHERE platform = ? AND key = ?",
            (platform, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        plaintext = await self._backend.decrypt(row[0])
        return plaintext.decode()

    async def delete(self, platform: str, key: str) -> bool:
        cursor = await self._db.conn.execute(
            "DELETE FROM secrets WHERE platform = ? AND key = ?",
            (platform, key),
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0
