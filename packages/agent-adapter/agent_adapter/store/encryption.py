"""AES-256-GCM backends for provider secrets."""

from __future__ import annotations

import os
from typing import Awaitable, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256

from agent_adapter_contracts.secrets import SecretsBackend
from agent_adapter.store.database import Database

_SALT = b"agent-adapter-secrets-v1"
_INFO = b"secrets-encryption-key"
_NONCE_LEN = 12


def derive_key(secret_material: bytes | str) -> bytes:
    """Derive a 256-bit AES key from external or wallet-provided material."""
    if isinstance(secret_material, str):
        raw = secret_material.encode()
    else:
        raw = secret_material
    if not raw:
        raise ValueError("Secrets encryption requires non-empty key material")
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=_SALT,
        info=_INFO,
    ).derive(raw)


class DerivedSecretsBackend(SecretsBackend):
    """Encrypts/decrypts secrets using AES-256-GCM with derived key material."""

    def __init__(self, secret_material: bytes | str) -> None:
        self._aesgcm = AESGCM(derive_key(secret_material))

    async def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext  # nonce prepended for decrypt

    async def decrypt(self, ciphertext: bytes) -> bytes:
        nonce = ciphertext[:_NONCE_LEN]
        return self._aesgcm.decrypt(nonce, ciphertext[_NONCE_LEN:], None)


class WalletDerivedSecretsBackend(DerivedSecretsBackend):
    """Legacy wallet-derived secrets backend kept for compatibility and migration."""


class ExternalSecretsBackend(DerivedSecretsBackend):
    """Secrets backend keyed from provider-managed config or environment material."""


async def migrate_legacy_wallet_secrets(
    db: Database,
    *,
    legacy_wallet_key_material_loader: Callable[[], Awaitable[bytes]],
    target_backend: SecretsBackend,
) -> int:
    """Re-encrypt legacy wallet-derived secrets with the configured external key."""
    legacy_backend: WalletDerivedSecretsBackend | None = None
    cursor = await db.conn.execute(
        "SELECT platform, key, encrypted_value FROM secrets"
    )
    rows = await cursor.fetchall()
    migrated = 0
    for platform, key, encrypted_value in rows:
        try:
            await target_backend.decrypt(encrypted_value)
            continue
        except Exception:
            pass

        if legacy_backend is None:
            legacy_backend = WalletDerivedSecretsBackend(
                await legacy_wallet_key_material_loader()
            )
        plaintext = await legacy_backend.decrypt(encrypted_value)
        reencrypted = await target_backend.encrypt(plaintext)
        await db.conn.execute(
            """
            UPDATE secrets
            SET encrypted_value = ?, updated_at = datetime('now')
            WHERE platform = ? AND key = ?
            """,
            (reencrypted, platform, key),
        )
        migrated += 1

    if migrated:
        await db.conn.commit()
    return migrated
