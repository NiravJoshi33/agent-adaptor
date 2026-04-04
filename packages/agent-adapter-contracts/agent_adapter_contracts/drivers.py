"""Platform driver contracts for optional platform-specific tool plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent_adapter_contracts.runtime import RuntimeAPI
from agent_adapter_contracts.types import ToolDefinition


class PlatformDriver(ABC):
    """Optional plugin that exposes higher-level platform-specific tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def namespace(self) -> str: ...

    @property
    @abstractmethod
    def tools(self) -> list[ToolDefinition]: ...

    @abstractmethod
    async def initialize(self, runtime: RuntimeAPI) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    async def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]: ...
