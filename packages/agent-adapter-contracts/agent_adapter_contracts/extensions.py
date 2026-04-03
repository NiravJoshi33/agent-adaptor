"""Extension ABC — the interface for add-on plugins.

Extensions are plugins that add new behaviour without replacing anything.
They subscribe to lifecycle hooks emitted by the core runtime.
Examples: Telegram notifier, Prometheus exporter, custom audit logger.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, TypeAlias


class RuntimeEvent(StrEnum):
    ON_JOB_COMPLETE = "on_job_complete"
    ON_JOB_FAILED = "on_job_failed"
    ON_LOW_BALANCE = "on_low_balance"
    ON_PLATFORM_REGISTERED = "on_platform_registered"
    ON_AGENT_ERROR = "on_agent_error"
    ON_CAPABILITY_DRIFT = "on_capability_drift"


ExtensionHook: TypeAlias = RuntimeEvent | str


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
