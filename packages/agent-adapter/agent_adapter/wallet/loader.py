"""Wallet loader — resolves which WalletPlugin implementation to use from config."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from agent_adapter.plugins.discovery import discover_plugins
from agent_adapter.store.database import Database
from agent_adapter.wallet.persistence import (
    load_persisted_wallet_keypair,
    persist_wallet_keypair,
)
from agent_adapter_contracts.wallet import WalletPlugin


def _load_class(module_name: str, class_name: str) -> type:
    module = import_module(module_name)
    return getattr(module, class_name)


async def load_wallet(
    provider: str,
    config: dict[str, Any],
    *,
    db: Database | None = None,
    data_dir: str | Path | None = None,
    wallet_encryption_key: str | bytes | None = None,
) -> WalletPlugin:
    """Load and return the configured wallet plugin.

    Args:
        provider: Plugin id from config (e.g. "ows", "solana-raw").
        config: Provider-specific config dict from agent-adapter.yaml.
    """
    rpc_url = config.get("rpc_url", "http://127.0.0.1:8899")

    if "module" in config:
        module_name = config["module"]
        class_name = config.get("class_name", "WalletPlugin")
        kwargs = {
            k: v
            for k, v in config.items()
            if k not in {"module", "class_name"}
        }
        plugin = _load_class(module_name, class_name)(**kwargs)
        if hasattr(plugin, "initialize"):
            await plugin.initialize()
        return plugin

    if provider == "ows":
        from wallet_ows import OWSWalletPlugin

        plugin = OWSWalletPlugin(
            wallet_name=config.get("wallet_name", "agent-adapter"),
            chain=config.get("chain", "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"),
            rpc_url=rpc_url,
            passphrase=config.get("passphrase"),
            vault_path=config.get("vault_path"),
        )
        await plugin.initialize()
        return plugin

    if provider == "solana-raw":
        from wallet_solana_raw import SolanaRawWallet

        cluster = config.get("cluster", "devnet")
        secret = config.get("secret_key")
        if secret:
            return SolanaRawWallet.from_base58(secret, rpc_url=rpc_url, cluster=cluster)

        if db is not None and data_dir is not None:
            if not wallet_encryption_key:
                raise ValueError(
                    "Generated solana-raw wallets require adapter.walletEncryptionKey "
                    "or AGENT_ADAPTER_WALLET_ENCRYPTION_KEY."
                )
            persisted = await load_persisted_wallet_keypair(db, wallet_encryption_key)
            if persisted is not None:
                return SolanaRawWallet(
                    persisted,
                    rpc_url=rpc_url,
                    cluster=cluster,
                )

            wallet = SolanaRawWallet.generate(rpc_url=rpc_url, cluster=cluster)
            await persist_wallet_keypair(db, wallet_encryption_key, wallet.keypair)
            return wallet

        return SolanaRawWallet.generate(rpc_url=rpc_url, cluster=cluster)

    discovered = discover_plugins("wallet")
    if provider in discovered:
        spec = discovered[provider]
        plugin = _load_class(spec.module, spec.attr)(**config)
        if hasattr(plugin, "initialize"):
            await plugin.initialize()
        return plugin

    raise ValueError(
        f'Wallet provider "{provider}" not found. '
        f"Available: {', '.join(sorted(set(['ows', 'solana-raw', *discovered.keys()]))) or 'none'}. Is the plugin installed?"
    )
