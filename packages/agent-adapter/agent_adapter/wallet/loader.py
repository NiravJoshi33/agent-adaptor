"""Wallet loader — resolves which WalletPlugin implementation to use from config."""

from __future__ import annotations

from typing import Any

from agent_adapter_contracts.wallet import WalletPlugin


async def load_wallet(provider: str, config: dict[str, Any]) -> WalletPlugin:
    """Load and return the configured wallet plugin.

    Args:
        provider: Plugin id from config (e.g. "ows", "solana-raw").
        config: Provider-specific config dict from agent-adapter.yaml.
    """
    if provider == "ows":
        from wallet_ows import OWSWalletPlugin

        plugin = OWSWalletPlugin(
            wallet_name=config.get("wallet_name", "agent-adapter"),
            chain=config.get("chain", "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"),
            passphrase=config.get("passphrase"),
            vault_path=config.get("vault_path"),
        )
        await plugin.initialize()
        return plugin

    if provider == "solana-raw":
        from wallet_solana_raw import SolanaRawWallet

        secret = config.get("secret_key")
        if secret:
            return SolanaRawWallet.from_base58(secret)
        return SolanaRawWallet.generate()

    raise ValueError(
        f'Wallet provider "{provider}" not found. '
        f"Available: ows, solana-raw. Is the plugin installed?"
    )
