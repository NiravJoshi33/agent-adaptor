"""OWSWalletPlugin — implements WalletPlugin via Open Wallet Standard.

Uses the OWS Python SDK (Rust FFI) for wallet management.
Keys live in ~/.ows/, encrypted at rest by OWS itself.
Multi-chain support via CAIP-2 chain identifiers.
"""

from __future__ import annotations

import ows

from agent_adapter_contracts.wallet import WalletPlugin

# CAIP-2 chain IDs
SOLANA_MAINNET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
SOLANA_DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"


class OWSWalletPlugin(WalletPlugin):
    """Open Wallet Standard wallet. Multi-chain support via CAIP-2.

    OWS manages key storage and encryption internally (~/.ows/ vault).
    This plugin delegates all crypto ops to the OWS Rust core via FFI.
    """

    def __init__(
        self,
        wallet_name: str = "agent-adapter",
        chain: str = SOLANA_MAINNET,
        passphrase: str | None = None,
        vault_path: str | None = None,
    ) -> None:
        self._wallet_name = wallet_name
        self._chain = chain
        self._passphrase = passphrase
        self._vault_path = vault_path
        self._wallet_info: dict | None = None

    async def initialize(self) -> None:
        """Load or create the OWS wallet."""
        try:
            self._wallet_info = ows.get_wallet(
                self._wallet_name, vault_path_opt=self._vault_path
            )
        except Exception:
            self._wallet_info = ows.create_wallet(
                self._wallet_name,
                passphrase=self._passphrase,
                vault_path_opt=self._vault_path,
            )

    def _ensure_initialized(self) -> dict:
        if self._wallet_info is None:
            raise RuntimeError("Wallet not initialized. Call initialize() first.")
        return self._wallet_info

    def _get_account(self, chain: str | None = None) -> dict:
        """Find the account entry for the given CAIP-2 chain."""
        info = self._ensure_initialized()
        target = chain or self._chain
        for account in info["accounts"]:
            if account["chain_id"] == target:
                return account
        raise ValueError(
            f"No account for chain '{target}' in wallet '{self._wallet_name}'"
        )

    async def get_address(self) -> str:
        account = self._get_account()
        return account["address"]

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        # OWS doesn't provide balance queries — that's an RPC concern.
        # Return zeros; the runtime's net tools handle balance checks.
        return {"sol": 0.0, "usdc": 0.0}

    async def sign_message(self, msg: bytes) -> bytes:
        self._ensure_initialized()
        result = ows.sign_message(
            self._wallet_name,
            self._chain,
            msg.decode("utf-8", errors="replace"),
            passphrase=self._passphrase,
            vault_path_opt=self._vault_path,
        )
        return bytes.fromhex(result["signature"])

    async def sign_transaction(self, tx: bytes) -> bytes:
        self._ensure_initialized()
        result = ows.sign_transaction(
            self._wallet_name,
            self._chain,
            tx.hex(),
            passphrase=self._passphrase,
            vault_path_opt=self._vault_path,
        )
        return bytes.fromhex(result["signature"])
