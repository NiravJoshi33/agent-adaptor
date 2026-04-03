"""SecretsBackend ABC — the interface for secrets encryption backends.

Default: wallet-derived AES-256-GCM.
Future plugins: Vault, AWS KMS, env-var based, etc.
"""

from abc import ABC, abstractmethod


class SecretsBackend(ABC):
    """Abstract base for secrets encryption backends.

    Swappable core module — one backend active at a time, selected via config.
    """

    @abstractmethod
    async def encrypt(self, plaintext: bytes) -> bytes: ...

    @abstractmethod
    async def decrypt(self, ciphertext: bytes) -> bytes: ...
