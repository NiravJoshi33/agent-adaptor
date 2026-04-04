"""Example tool plugin that packages runtime state into concise ops summaries."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from agent_adapter_contracts.runtime import RuntimeAPI
from agent_adapter_contracts.tool_plugins import ToolPlugin
from agent_adapter_contracts.types import ToolDefinition


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _safe_amount(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _format_price(pricing: dict[str, Any] | None) -> str:
    if not pricing:
        return "unpriced"
    amount = _safe_amount(pricing.get("amount"))
    currency = str(pricing.get("currency") or "USDC")
    model = str(pricing.get("model") or "custom")
    return f"{amount:.4f} {currency} ({model})"


def _format_money(amount: float, currency: str) -> str:
    return f"{amount:.4f} {currency}"


class OpsToolkitPlugin(ToolPlugin):
    """Useful sample plugin for runtime summaries and agent-authored updates."""

    def __init__(
        self,
        *,
        default_job_limit: int = 8,
        default_capability_limit: int = 12,
    ) -> None:
        self._default_job_limit = default_job_limit
        self._default_capability_limit = default_capability_limit
        self._runtime: RuntimeAPI | None = None

    @property
    def name(self) -> str:
        return "ops-toolkit"

    @property
    def namespace(self) -> str:
        return "tool_ops"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="tool_ops__capability_snapshot",
                description=(
                    "Summarize current capabilities, pricing, and blocked states into a concise planning payload."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_blocked": {
                            "type": "boolean",
                            "description": "Whether to include disabled or review-blocked capabilities in the returned list.",
                            "default": False,
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of capabilities to include.",
                            "default": self._default_capability_limit,
                        },
                    },
                },
            ),
            ToolDefinition(
                name="tool_ops__job_digest",
                description=(
                    "Summarize recent runtime job activity, status counts, and tracked payment volume for reports or planning."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of recent jobs to inspect.",
                            "default": self._default_job_limit,
                        }
                    },
                },
            ),
        ]

    async def initialize(self, runtime: RuntimeAPI) -> None:
        self._runtime = runtime

    async def shutdown(self) -> None:
        return None

    async def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self._runtime is None:
            raise RuntimeError("OpsToolkitPlugin has not been initialized")
        if tool_name == "tool_ops__capability_snapshot":
            return await self._capability_snapshot(args)
        if tool_name == "tool_ops__job_digest":
            return await self._job_digest(args)
        raise ValueError(f"Unknown ops toolkit tool: {tool_name}")

    async def _capability_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        assert self._runtime is not None
        capabilities = await self._runtime.list_capabilities()
        include_blocked = bool(args.get("include_blocked", False))
        limit = _clamp_int(
            args.get("limit"),
            default=self._default_capability_limit,
            minimum=1,
            maximum=50,
        )

        active = [item for item in capabilities if item.get("status") == "active"]
        blocked = [item for item in capabilities if item.get("status") != "active"]
        visible = capabilities if include_blocked else active

        summarized = [
            {
                "name": item.get("name", ""),
                "status": item.get("status", "unknown"),
                "drift_status": item.get("drift_status", "unchanged"),
                "pricing": _format_price(item.get("pricing")),
                "description": item.get("description", ""),
            }
            for item in visible[:limit]
        ]
        summary = (
            f"{len(capabilities)} total capabilities: {len(active)} active, "
            f"{len(blocked)} blocked or pending review."
        )
        if summarized:
            summary += " Visible: " + ", ".join(item["name"] for item in summarized[:5]) + "."

        return {
            "summary": summary,
            "counts": {
                "total": len(capabilities),
                "active": len(active),
                "blocked": len(blocked),
            },
            "capabilities": summarized,
        }

    async def _job_digest(self, args: dict[str, Any]) -> dict[str, Any]:
        assert self._runtime is not None
        limit = _clamp_int(
            args.get("limit"),
            default=self._default_job_limit,
            minimum=1,
            maximum=50,
        )
        jobs = await self._runtime.job_engine.list_recent(limit)
        status_counts = Counter(str(job.get("status") or "unknown") for job in jobs)
        payment_volume: dict[str, float] = defaultdict(float)
        recent_jobs: list[dict[str, Any]] = []

        for job in jobs:
            currency = str(job.get("payment_currency") or "USDC")
            amount = _safe_amount(job.get("payment_amount"))
            payment_volume[currency] += amount
            recent_jobs.append(
                {
                    "id": job.get("id", ""),
                    "capability": job.get("capability", ""),
                    "status": job.get("status", "unknown"),
                    "payment": _format_money(amount, currency),
                    "payment_protocol": job.get("payment_protocol") or "unassigned",
                    "platform": job.get("platform") or "local runtime",
                    "created_at": job.get("created_at", ""),
                }
            )

        status_summary = ", ".join(
            f"{count} {status}" for status, count in sorted(status_counts.items())
        ) or "no jobs"
        payment_summary = ", ".join(
            _format_money(amount, currency)
            for currency, amount in sorted(payment_volume.items())
            if amount > 0
        ) or "0.0000 USDC"

        return {
            "summary": (
                f"{len(jobs)} recent jobs tracked: {status_summary}. "
                f"Payment volume: {payment_summary}."
            ),
            "counts": dict(status_counts),
            "payment_volume": dict(payment_volume),
            "jobs": recent_jobs,
        }
