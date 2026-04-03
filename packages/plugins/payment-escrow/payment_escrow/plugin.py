"""EscrowAdapter — Solana escrow via external program IDL. No contract code here."""

from typing import Any

from agent_adapter_contracts.payments import (
    PaymentAdapter,
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)


class EscrowAdapter(PaymentAdapter):
    """Builds and signs escrow transactions against an external Solana program."""

    @property
    def id(self) -> str:
        return "solana_escrow"

    def can_handle(self, challenge: PaymentChallenge) -> bool:
        return challenge.type == "escrow"

    async def execute(
        self, challenge: PaymentChallenge, wallet: Any
    ) -> PaymentReceipt:
        raise NotImplementedError

    async def settle(self, session: PaymentSession) -> None:
        raise NotImplementedError

    async def refund(self, session: PaymentSession, reason: str) -> None:
        raise NotImplementedError
