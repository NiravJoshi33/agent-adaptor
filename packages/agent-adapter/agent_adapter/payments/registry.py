"""PaymentRegistry — resolves which adapter handles a given payment challenge."""

from agent_adapter_contracts.payments import PaymentAdapter, PaymentChallenge


class PaymentRegistry:
    def __init__(self) -> None:
        self._adapters: list[PaymentAdapter] = []

    def register(self, adapter: PaymentAdapter) -> None:
        self._adapters.append(adapter)

    def resolve(self, challenge: PaymentChallenge) -> PaymentAdapter:
        for adapter in self._adapters:
            if adapter.can_handle(challenge):
                return adapter
        raise ValueError(
            f"No payment adapter can handle challenge type: {challenge.type}"
        )

    def list(self) -> list[str]:
        return [a.id for a in self._adapters]
