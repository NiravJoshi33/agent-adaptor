"""Wallet-derived AES-256-GCM encryption backend for secrets."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256

from agent_adapter_contracts.secrets import SecretsBackend

_SALT = b"agent-adapter-secrets-v1"
_INFO = b"secrets-encryption-key"
_NONCE_LEN = 12


def derive_key(wallet_private_key: bytes) -> bytes:
    """Derive a 256-bit AES key from the wallet private key via HKDF."""
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=_SALT,
        info=_INFO,
    ).derive(wallet_private_key)


class WalletDerivedSecretsBackend(SecretsBackend):
    """Encrypts/decrypts secrets using AES-256-GCM with a key derived from the wallet."""

    def __init__(self, wallet_private_key: bytes) -> None:
        self._aesgcm = AESGCM(derive_key(wallet_private_key))

    async def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext  # nonce prepended for decrypt

    async def decrypt(self, ciphertext: bytes) -> bytes:
        nonce = ciphertext[:_NONCE_LEN]
        return self._aesgcm.decrypt(nonce, ciphertext[_NONCE_LEN:], None)
