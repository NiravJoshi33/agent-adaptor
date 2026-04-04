"""Job engine — tracks units of economic work through a 4-state lifecycle.

States: pending → executing → completed | failed
The job engine handles the middle step. The agent handles everything around it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from agent_adapter_contracts.extensions import RuntimeEvent
from agent_adapter.store.database import Database
from agent_adapter.extensions.registry import ExtensionRegistry


class JobEngine:
    """CRUD + lifecycle management for jobs in SQLite."""

    def __init__(
        self, db: Database, extensions: ExtensionRegistry | None = None
    ) -> None:
        self._db = db
        self._extensions = extensions

    async def create(
        self,
        capability: str,
        input_data: dict[str, Any],
        platform: str = "",
        platform_ref: str = "",
        payment_protocol: str = "",
        payment_amount: float = 0.0,
        payment_currency: str = "USDC",
    ) -> str:
        """Create a new job in pending state. Returns the job ID."""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """
            INSERT INTO jobs (
                id, capability, platform, platform_ref, status,
                input_hash, payment_protocol, payment_amount,
                payment_currency, payment_status, created_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, 'pending', ?)
            """,
            (
                job_id,
                capability,
                platform,
                platform_ref,
                self._hash_payload(input_data),
                payment_protocol,
                payment_amount,
                payment_currency,
                now,
            ),
        )
        await self._db.conn.commit()
        return job_id

    async def mark_executing(self, job_id: str) -> bool:
        cursor = await self._db.conn.execute(
            "UPDATE jobs SET status = 'executing' WHERE id = ? AND status = 'pending'",
            (job_id,),
        )
        await self._db.conn.commit()
        return bool(cursor.rowcount)

    async def mark_completed(
        self,
        job_id: str,
        output_hash: str = "",
        payment_status: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if payment_status is None:
            await self._db.conn.execute(
                """
                UPDATE jobs SET status = 'completed', output_hash = ?,
                    completed_at = ?
                WHERE id = ? AND status = 'executing'
                """,
                (output_hash, now, job_id),
            )
        else:
            await self._db.conn.execute(
                """
                UPDATE jobs SET status = 'completed', output_hash = ?,
                    payment_status = ?, completed_at = ?
                WHERE id = ? AND status = 'executing'
                """,
                (output_hash, payment_status, now, job_id),
            )
        await self._db.conn.commit()
        if self._extensions:
            job = await self.get(job_id)
            if job:
                await self._extensions.emit(RuntimeEvent.ON_JOB_COMPLETE, job)

    async def mark_failed(
        self, job_id: str, error: str = "", payment_status: str | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if payment_status is None:
            await self._db.conn.execute(
                """
                UPDATE jobs SET status = 'failed', output_hash = ?,
                    completed_at = ?
                WHERE id = ? AND status IN ('pending', 'executing')
                """,
                (error, now, job_id),
            )
        else:
            await self._db.conn.execute(
                """
                UPDATE jobs SET status = 'failed', output_hash = ?,
                    payment_status = ?, completed_at = ?
                WHERE id = ? AND status IN ('pending', 'executing')
                """,
                (error, payment_status, now, job_id),
            )
        await self._db.conn.commit()
        if self._extensions:
            job = await self.get(job_id)
            if job:
                await self._extensions.emit(RuntimeEvent.ON_JOB_FAILED, job)

    async def update_payment(
        self,
        job_id: str,
        *,
        protocol: str | None = None,
        status: str | None = None,
        amount: float | None = None,
        currency: str | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[Any] = []
        if protocol is not None:
            updates.append("payment_protocol = ?")
            params.append(protocol)
        if status is not None:
            updates.append("payment_status = ?")
            params.append(status)
        if amount is not None:
            updates.append("payment_amount = ?")
            params.append(amount)
        if currency is not None:
            updates.append("payment_currency = ?")
            params.append(currency)
        if not updates:
            return
        params.append(job_id)
        await self._db.conn.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        await self._db.conn.commit()

    async def get(self, job_id: str) -> dict[str, Any] | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))

    async def list_active(self) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute(
            "SELECT * FROM jobs WHERE status IN ('pending', 'executing') ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def count_today(self) -> dict[str, int]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cursor = await self._db.conn.execute(
            """
            SELECT status, COUNT(*) FROM jobs
            WHERE created_at >= ? GROUP BY status
            """,
            (today,),
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def earnings_today(self) -> float:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cursor = await self._db.conn.execute(
            """
            SELECT COALESCE(SUM(payment_amount), 0) FROM jobs
            WHERE status = 'completed' AND created_at >= ?
            """,
            (today,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    def hash_payload(self, payload: Any) -> str:
        return self._hash_payload(payload)

    def _hash_payload(self, payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()
