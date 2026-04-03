"""PaymentAdapter ABC and related types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaymentChallenge:
    type: str  # "x402", "escrow", "mpp", "free"
    headers: dict[str, str] = field(default_factory=dict)
    platform: str = ""
    task_id: str = ""
    amount: float = 0.0
    session_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentReceipt:
    protocol: str
    amount: float = 0.0
    currency: str = "USDC"
    tx_signature: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentSession:
    job_id: str
    adapter_id: str
    challenge: PaymentChallenge
    receipt: PaymentReceipt | None = None
    status: str = "pending"


class PaymentAdapter(ABC):
    """Abstract base for payment adapters.

    Multiple payment adapters can be active at once.
    The registry resolves which to use per-payment via can_handle().
    """

    @property
    @abstractmethod
    def id(self) -> str: ...

    @abstractmethod
    def can_handle(self, challenge: PaymentChallenge) -> bool: ...

    @abstractmethod
    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt: ...

    @abstractmethod
    async def settle(self, session: PaymentSession) -> None: ...

    @abstractmethod
    async def refund(self, session: PaymentSession, reason: str) -> None: ...
