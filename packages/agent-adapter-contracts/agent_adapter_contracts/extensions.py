"""Extension ABC — the interface for add-on plugins.

Extensions are plugins that add new behaviour without replacing anything.
They subscribe to lifecycle hooks emitted by the core runtime.
Examples: Telegram notifier, Prometheus exporter, custom audit logger.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

ExtensionHook = Literal[
    "on_job_complete",
    "on_job_failed",
    "on_low_balance",
    "on_platform_registered",
    "on_agent_error",
    "on_capability_drift",
]


class Extension(ABC):
    """Abstract base for add-on extension plugins.

    The core never imports extensions — it only emits events.
    Extensions subscribe to the hooks they care about.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def hooks(self) -> list[ExtensionHook]: ...

    @abstractmethod
    async def initialize(self, runtime: Any) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...
