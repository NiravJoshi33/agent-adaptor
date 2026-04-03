"""Wallet loader — resolves which WalletPlugin implementation to use from config."""

from agent_adapter_contracts.wallet import WalletPlugin


async def load_wallet(provider: str, config: dict) -> WalletPlugin:
    """Load and return the configured wallet plugin."""
    raise NotImplementedError(f"Wallet loader not yet implemented for: {provider}")
