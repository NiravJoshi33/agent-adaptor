"""Stable runtime API contracts for third-party extensions and drivers."""

from __future__ import annotations

from typing import Any, Protocol


class RuntimeAPI(Protocol):
    """Typed runtime surface exposed to extensions and platform drivers.

    This is intentionally small and structural so plugin authors can depend on a
    stable contract without importing the full runtime implementation.
    """

    config: dict[str, Any]
    wallet: Any
    secrets: Any
    state: Any
    payments: Any
    drivers: Any
    tool_plugins: Any
    handlers: Any
    job_engine: Any

    async def list_capabilities(self) -> list[dict[str, Any]]: ...

    async def list_platforms(self) -> list[dict[str, Any]]: ...

    async def record_inbound_event(
        self,
        *,
        source_type: str,
        source: str,
        channel: str,
        event_type: str,
        payload: Any,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
