"""Preview wallet plugin bundled with the runtime for local dashboard demos."""

from __future__ import annotations


class PreviewWalletPlugin:
    def __init__(
        self,
        address: str = "preview-wallet-local",
        sol: float = 1.25,
        usdc: float = 42.0,
    ) -> None:
        self._address = address
        self._balances = {"sol": sol, "usdc": usdc}
        self.secret_bytes = b"\x33" * 64

    async def initialize(self) -> None:
        return None

    async def get_address(self) -> str:
        return self._address

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        return dict(self._balances)

    async def sign_message(self, msg: bytes) -> bytes:
        return b"\xcc" * 64

    async def sign_transaction(self, tx: bytes) -> bytes:
        return tx + b"-preview"
