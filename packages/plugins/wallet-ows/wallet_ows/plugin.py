"""OWSWalletPlugin — implements WalletPlugin via Open Wallet Standard.

Uses the OWS Python SDK (Rust FFI) for wallet management.
Keys live in ~/.ows/, encrypted at rest by OWS itself.
Multi-chain support via CAIP-2 chain identifiers.
"""

from __future__ import annotations

import ows
from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey

from agent_adapter_contracts.wallet import WalletPlugin

# CAIP-2 chain IDs
SOLANA_MAINNET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
SOLANA_DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"

# Well-known USDC mint addresses
USDC_MINTS: dict[str, str] = {
    SOLANA_MAINNET: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    SOLANA_DEVNET: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
}

TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")


class OWSWalletPlugin(WalletPlugin):
    """Open Wallet Standard wallet. Multi-chain support via CAIP-2.

    OWS manages key storage and encryption internally (~/.ows/ vault).
    This plugin delegates all crypto ops to the OWS Rust core via FFI.
    Balance queries use Solana RPC when the selected chain is Solana.
    """

    def __init__(
        self,
        wallet_name: str = "agent-adapter",
        chain: str = SOLANA_MAINNET,
        rpc_url: str = "http://127.0.0.1:8899",
        passphrase: str | None = None,
        vault_path: str | None = None,
    ) -> None:
        self._wallet_name = wallet_name
        self._chain = chain
        self._rpc_url = rpc_url
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
        target_chain = chain or self._chain

        # Only Solana chains supported for now
        if not target_chain.startswith("solana:"):
            return {"sol": 0.0, "usdc": 0.0}

        address = (await self.get_address()) if chain is None else self._get_account(chain)["address"]
        pubkey = Pubkey.from_string(address)

        async with SolanaClient(self._rpc_url) as rpc:
            # SOL balance
            resp = await rpc.get_balance(pubkey)
            sol = resp.value / 1e9

            # USDC balance (SPL token)
            usdc = 0.0
            usdc_mint_str = USDC_MINTS.get(target_chain)
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
        for key in ("signed_transaction", "transaction", "signedTx"):
            value = result.get(key)
            if value:
                return bytes.fromhex(value)
        if "signature" in result:
            raise RuntimeError(
                "OWS sign_transaction returned only a signature, not signed transaction bytes"
            )
        raise RuntimeError("OWS sign_transaction returned an unexpected payload")
