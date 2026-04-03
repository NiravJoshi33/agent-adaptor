"""FreeAdapter — no-op payment adapter for testing and free-tier APIs."""

from typing import Any

from agent_adapter_contracts.payments import (
    PaymentAdapter,
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)


class FreeAdapter(PaymentAdapter):
    """Always succeeds, charges nothing."""

    @property
    def id(self) -> str:
        return "free"

    def can_handle(self, challenge: PaymentChallenge) -> bool:
        return challenge.type == "free"

    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt:
        return PaymentReceipt(protocol="free", amount=0.0, currency="USDC")

    async def settle(self, session: PaymentSession) -> None:
        pass

    async def refund(self, session: PaymentSession, reason: str) -> None:
        pass
