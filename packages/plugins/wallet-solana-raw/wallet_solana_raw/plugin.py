"""SolanaRawWallet — implements WalletPlugin using a local Solana keypair via solders.

Simplest possible wallet: one keypair, one chain (Solana).
Used as the fallback when OWS is not available.
"""

from __future__ import annotations

from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from agent_adapter_contracts.wallet import WalletPlugin

# Well-known USDC mint addresses
USDC_MINTS: dict[str, str] = {
    "mainnet": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "devnet": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
}

# SPL Token program
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")


class SolanaRawWallet(WalletPlugin):
    """Direct Solana keypair wallet using solders."""

    def __init__(
        self,
        keypair: Keypair | None = None,
        rpc_url: str = "http://127.0.0.1:8899",
        cluster: str = "devnet",
    ) -> None:
        self._keypair = keypair or Keypair()
        self._rpc_url = rpc_url
        self._cluster = cluster

    @classmethod
    def generate(
        cls, rpc_url: str = "http://127.0.0.1:8899", cluster: str = "devnet"
    ) -> SolanaRawWallet:
        return cls(Keypair(), rpc_url=rpc_url, cluster=cluster)

    @classmethod
    def from_bytes(
        cls, secret: bytes, rpc_url: str = "http://127.0.0.1:8899", cluster: str = "devnet"
    ) -> SolanaRawWallet:
        return cls(Keypair.from_bytes(secret), rpc_url=rpc_url, cluster=cluster)

    @classmethod
    def from_base58(
        cls, key: str, rpc_url: str = "http://127.0.0.1:8899", cluster: str = "devnet"
    ) -> SolanaRawWallet:
        return cls(Keypair.from_base58_string(key), rpc_url=rpc_url, cluster=cluster)

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
        async with SolanaClient(self._rpc_url) as rpc:
            pubkey = self._keypair.pubkey()

            # SOL balance
            resp = await rpc.get_balance(pubkey)
            sol = resp.value / 1e9

            # USDC balance (SPL token)
            usdc = 0.0
            usdc_mint_str = USDC_MINTS.get(self._cluster)
            if usdc_mint_str:
                try:
                    usdc_mint = Pubkey.from_string(usdc_mint_str)
                    token_resp = await rpc.get_token_accounts_by_owner(
                        pubkey, TokenAccountOpts(mint=usdc_mint)
                    )
                    for account in token_resp.value:
                        data = account.account.data
                        if hasattr(data, "parsed"):
                            amount = data.parsed["info"]["tokenAmount"]["uiAmount"]
                            usdc += amount or 0.0
                except Exception:
                    pass  # RPC doesn't support token queries (e.g. bare simnet)

            return {"sol": sol, "usdc": usdc}

    async def sign_message(self, msg: bytes) -> bytes:
        sig = self._keypair.sign_message(msg)
        return bytes(sig)

    async def sign_transaction(self, tx: bytes) -> bytes:
        sig = self._keypair.sign_message(tx)
        return bytes(sig)
