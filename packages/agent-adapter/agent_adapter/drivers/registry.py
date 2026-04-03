"""Registry for optional platform drivers and their dynamic tools."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_adapter_contracts.drivers import PlatformDriver
from agent_adapter_contracts.types import ToolDefinition


class DriverRegistry:
    def __init__(self) -> None:
        self._drivers: list[PlatformDriver] = []
        self._tool_map: dict[str, PlatformDriver] = {}

    def register(self, driver: PlatformDriver) -> None:
        self._drivers.append(driver)
        for tool in driver.tools:
            self._tool_map[tool.name] = driver

    def to_tool_definitions(self) -> list[ToolDefinition]:
        tools: list[ToolDefinition] = []
        for driver in self._drivers:
            tools.extend(driver.tools)
        return tools

    def list_drivers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": driver.name,
                "namespace": driver.namespace,
                "tool_count": len(driver.tools),
                "tools": [tool.name for tool in driver.tools],
            }
            for driver in self._drivers
        ]

    def resolve_tool(self, tool_name: str) -> PlatformDriver | None:
        return self._tool_map.get(tool_name)

    async def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        driver = self.resolve_tool(tool_name)
        if driver is None:
            raise ValueError(f"Unknown driver tool: {tool_name}")
        return await driver.execute(tool_name, args)

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(driver.shutdown() for driver in self._drivers),
            return_exceptions=True,
        )
