"""Registry for agent-facing tool plugins and their dynamic tools."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_adapter_contracts.tool_plugins import ToolPlugin
from agent_adapter_contracts.types import ToolDefinition


class ToolPluginRegistry:
    def __init__(self) -> None:
        self._plugins: list[ToolPlugin] = []
        self._tool_map: dict[str, ToolPlugin] = {}

    def register(self, plugin: ToolPlugin) -> None:
        self._plugins.append(plugin)
        for tool in plugin.tools:
            self._tool_map[tool.name] = plugin

    def to_tool_definitions(self) -> list[ToolDefinition]:
        tools: list[ToolDefinition] = []
        for plugin in self._plugins:
            tools.extend(plugin.tools)
        return tools

    def list_plugins(self) -> list[dict[str, Any]]:
        return [
            {
                "name": plugin.name,
                "namespace": plugin.namespace,
                "tool_count": len(plugin.tools),
                "tools": [tool.name for tool in plugin.tools],
            }
            for plugin in self._plugins
        ]

    def resolve_tool(self, tool_name: str) -> ToolPlugin | None:
        return self._tool_map.get(tool_name)

    async def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        plugin = self.resolve_tool(tool_name)
        if plugin is None:
            raise ValueError(f"Unknown tool plugin tool: {tool_name}")
        return await plugin.execute(tool_name, args)

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(plugin.shutdown() for plugin in self._plugins),
            return_exceptions=True,
        )
