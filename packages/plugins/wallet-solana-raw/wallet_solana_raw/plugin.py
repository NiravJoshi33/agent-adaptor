"""SolanaRawWallet — implements WalletPlugin using a local Solana keypair."""

from agent_adapter_contracts.wallet import WalletPlugin


class SolanaRawWallet(WalletPlugin):
    """Direct Solana keypair wallet. Simplest possible implementation."""

    async def get_address(self) -> str:
        raise NotImplementedError

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        raise NotImplementedError

    async def sign_message(self, msg: bytes) -> bytes:
        raise NotImplementedError

    async def sign_transaction(self, tx: bytes) -> bytes:
        raise NotImplementedError
