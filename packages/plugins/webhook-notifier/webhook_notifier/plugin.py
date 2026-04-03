"""Webhook notification bridge extension for runtime events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from agent_adapter_contracts.extensions import ExtensionHook, RuntimeEvent


class WebhookNotifierExtension:
    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        hooks: list[ExtensionHook] | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._url = url
        self._headers = headers or {}
        self._timeout_seconds = timeout_seconds
        self._runtime = None
        self._client = httpx.AsyncClient(timeout=timeout_seconds)
        self._hooks = hooks or [
            RuntimeEvent.ON_JOB_COMPLETE,
            RuntimeEvent.ON_JOB_FAILED,
            RuntimeEvent.ON_PLATFORM_REGISTERED,
            RuntimeEvent.ON_CAPABILITY_DRIFT,
            RuntimeEvent.ON_AGENT_ERROR,
        ]

    @property
    def name(self) -> str:
        return "webhook-notifier"

    @property
    def hooks(self) -> list[ExtensionHook]:
        return list(self._hooks)

    async def initialize(self, runtime: Any) -> None:
        self._runtime = runtime

    async def shutdown(self) -> None:
        await self._client.aclose()

    async def on_job_complete(self, job: dict[str, Any]) -> None:
        await self._send(RuntimeEvent.ON_JOB_COMPLETE, job)

    async def on_job_failed(self, job: dict[str, Any]) -> None:
        await self._send(RuntimeEvent.ON_JOB_FAILED, job)

    async def on_low_balance(self, payload: dict[str, Any]) -> None:
        await self._send(RuntimeEvent.ON_LOW_BALANCE, payload)

    async def on_platform_registered(self, payload: dict[str, Any]) -> None:
        await self._send(RuntimeEvent.ON_PLATFORM_REGISTERED, payload)

    async def on_agent_error(self, payload: dict[str, Any]) -> None:
        await self._send(RuntimeEvent.ON_AGENT_ERROR, payload)

    async def on_capability_drift(self, payload: dict[str, Any]) -> None:
        await self._send(RuntimeEvent.ON_CAPABILITY_DRIFT, payload)

    async def _send(self, hook: ExtensionHook, payload: Any) -> None:
        runtime_name = None
        if self._runtime is not None:
            runtime_name = self._runtime.config.get("adapter", {}).get(
                "name", "agent-adapter"
            )
        body = {
            "hook": hook.value if isinstance(hook, RuntimeEvent) else str(hook),
            "payload": payload,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "runtime": runtime_name,
        }
        await self._client.post(self._url, json=body, headers=self._headers)
