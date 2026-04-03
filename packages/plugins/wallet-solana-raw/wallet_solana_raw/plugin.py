"""SolanaRawWallet — implements WalletPlugin using a local Solana keypair via solders.

Simplest possible wallet: one keypair, one chain (Solana).
Used as the fallback when OWS is not available.
"""

from __future__ import annotations

from solders.keypair import Keypair

from agent_adapter_contracts.wallet import WalletPlugin


class SolanaRawWallet(WalletPlugin):
    """Direct Solana keypair wallet using solders."""

    def __init__(self, keypair: Keypair | None = None) -> None:
        self._keypair = keypair or Keypair()

    @classmethod
    def generate(cls) -> SolanaRawWallet:
        return cls(Keypair())

    @classmethod
    def from_bytes(cls, secret: bytes) -> SolanaRawWallet:
        return cls(Keypair.from_bytes(secret))

    @classmethod
    def from_base58(cls, key: str) -> SolanaRawWallet:
        return cls(Keypair.from_base58_string(key))

    @property
    def keypair(self) -> Keypair:
        return self._keypair

    @property
    def secret_bytes(self) -> bytes:
        """Raw 64-byte secret key. Used for deriving the secrets encryption key."""
        return bytes(self._keypair)

    async def get_address(self) -> str:
        return str(self._keypair.pubkey())

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        # Balance checks require an RPC connection — handled by runtime's net tools.
        return {"sol": 0.0, "usdc": 0.0}

    async def sign_message(self, msg: bytes) -> bytes:
        sig = self._keypair.sign_message(msg)
        return bytes(sig)

    async def sign_transaction(self, tx: bytes) -> bytes:
        sig = self._keypair.sign_message(tx)
        return bytes(sig)
