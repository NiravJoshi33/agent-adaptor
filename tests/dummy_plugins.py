"""Test-only plugin implementations for management/CLI bootstrap tests."""

from __future__ import annotations


class DummyWalletPlugin:
    def __init__(
        self,
        address: str = "dummy-wallet",
        sol: float = 2.5,
        usdc: float = 9.0,
    ) -> None:
        self._address = address
        self._balances = {"sol": sol, "usdc": usdc}
        self.secret_bytes = b"\x22" * 64

    async def initialize(self) -> None:
        return None

    async def get_address(self) -> str:
        return self._address

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        return dict(self._balances)

    async def sign_message(self, msg: bytes) -> bytes:
        return b"\xbb" * 64

    async def sign_transaction(self, tx: bytes) -> bytes:
        return tx + b"-dummy"
