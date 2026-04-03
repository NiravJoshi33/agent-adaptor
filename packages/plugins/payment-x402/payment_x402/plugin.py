"""X402Adapter — handles HTTP 402 payment-required responses."""

from typing import Any

from agent_adapter_contracts.payments import (
    PaymentAdapter,
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)


class X402Adapter(PaymentAdapter):
    """Handles x402 payment flows: parse 402 response, sign payment, retry with proof."""

    @property
    def id(self) -> str:
        return "x402"

    def can_handle(self, challenge: PaymentChallenge) -> bool:
        return challenge.type == "x402"

    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt:
        raise NotImplementedError

    async def settle(self, session: PaymentSession) -> None:
        raise NotImplementedError

    async def refund(self, session: PaymentSession, reason: str) -> None:
        raise NotImplementedError
