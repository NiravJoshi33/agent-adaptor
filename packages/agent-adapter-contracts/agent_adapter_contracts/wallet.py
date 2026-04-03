"""WalletPlugin ABC — the interface every wallet plugin must implement."""

from abc import ABC, abstractmethod


class WalletPlugin(ABC):
    """Abstract base for wallet plugins.

    The runtime always needs _a_ wallet — the plugin decides _which_ wallet.
    Only one wallet plugin is active at a time, selected via config.
    """

    @abstractmethod
    async def get_address(self) -> str: ...

    @abstractmethod
    async def get_balance(self, chain: str | None = None) -> dict[str, float]: ...

    @abstractmethod
    async def sign_message(self, msg: bytes) -> bytes: ...

    @abstractmethod
    async def sign_transaction(self, tx: bytes) -> bytes:
        """Return serialized signed transaction bytes for the provided transaction."""
        ...
