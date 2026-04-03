"""Shared persistence helpers for inbound operational events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent_adapter.store.database import Database


async def record_inbound_event(
    db: Database,
    *,
    source_type: str,
    source: str,
    channel: str,
    event_type: str,
    payload: Any,
    headers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.conn.execute(
        """
        INSERT INTO inbound_events (
            source_type, source, channel, event_type,
            payload, headers, received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_type,
            source,
            channel,
            event_type,
            json.dumps(payload, default=str),
            json.dumps(headers or {}, default=str),
            now,
        ),
    )
    await db.conn.commit()
    return {
        "id": cursor.lastrowid,
        "source_type": source_type,
        "source": source,
        "channel": channel,
        "event_type": event_type,
        "payload": payload,
        "headers": headers or {},
        "received_at": now,
        "delivered_at": None,
    }


async def list_inbound_events(
    db: Database,
    *,
    source_type: str | None = None,
    channel: str | None = None,
    limit: int = 20,
    pending_only: bool = True,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    if pending_only:
        clauses.append("delivered_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor = await db.conn.execute(
        f"""
        SELECT * FROM inbound_events
        {where}
        ORDER BY received_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    rows = await cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    events = [dict(zip(cols, row)) for row in rows]
    for event in events:
        event["payload"] = _maybe_json(event.get("payload"))
        event["headers"] = _maybe_json(event.get("headers")) or {}
    return events


async def acknowledge_inbound_events(db: Database, event_ids: list[int]) -> None:
    if not event_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ", ".join("?" for _ in event_ids)
    await db.conn.execute(
        f"""
        UPDATE inbound_events
        SET delivered_at = ?
        WHERE id IN ({placeholders})
        """,
        (now, *event_ids),
    )
    await db.conn.commit()


def _maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value
