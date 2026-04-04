"""Capability registry — normalized store of all discovered capabilities."""

from __future__ import annotations

from copy import deepcopy

from agent_adapter_contracts.types import Capability, ToolDefinition


class CapabilityRegistry:
    """Holds all discovered capabilities regardless of source.

    Capabilities are added via ingestors (OpenAPI, MCP, manual).
    The registry generates cap__* tool definitions for the agent.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        self._capabilities[cap.name] = cap

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def list_all(self) -> list[Capability]:
        return list(self._capabilities.values())

    def list_enabled(self) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.enabled]

    def list_priced(self) -> list[Capability]:
        return [
            c
            for c in self._capabilities.values()
            if c.enabled and c.pricing and self._is_sellable(c)
        ]

    def enable(self, name: str) -> None:
        cap = self._capabilities.get(name)
        if cap:
            cap.enabled = True

    def disable(self, name: str) -> None:
        cap = self._capabilities.get(name)
        if cap:
            cap.enabled = False

    def to_tool_definitions(self) -> list[ToolDefinition]:
        """Generate cap__* tool definitions for the agent from enabled+priced capabilities."""
        tools = []
        for cap in self.list_priced():
            desc = cap.description or f"Execute the {cap.name} capability"
            if cap.base_url and cap.source_ref:
                desc += f"\nEndpoint: {cap.base_url}{cap.source_ref.split(' ', 1)[-1]}"
                desc += f"\nMethod: {cap.source_ref.split(' ', 1)[0]}"
            tools.append(
                ToolDefinition(
                    name=f"cap__{cap.name}",
                    description=desc,
                    input_schema=self._tool_input_schema(cap),
                )
            )
        return tools

    def _is_sellable(self, cap: Capability) -> bool:
        return getattr(cap, "drift_status", "unchanged") not in {
            "schema_changed",
            "stale",
        }

    def _tool_input_schema(self, cap: Capability) -> dict:
        schema = deepcopy(cap.input_schema) if cap.input_schema else {"type": "object"}
        schema.setdefault("type", "object")
        properties = schema.setdefault("properties", {})
        properties["_job_id"] = {
            "type": "string",
            "description": (
                "Optional runtime job identifier returned by jobs__create. "
                "When provided, this execution is recorded against that existing job."
            ),
        }
        return schema
