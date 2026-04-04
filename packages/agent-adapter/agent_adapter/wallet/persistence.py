"""Persistence helpers for locally managed runtime wallets."""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from solders.keypair import Keypair

from agent_adapter.store.database import Database

_NONCE_LEN = 12


def _normalize_master_key(master_key: str | bytes) -> bytes:
    if isinstance(master_key, bytes):
        raw = master_key
    else:
        raw = master_key.encode()
    if not raw:
        raise ValueError("Wallet persistence requires a non-empty encryption key")
    return hashlib.sha256(raw).digest()


def _encrypt_private_key(secret_bytes: bytes, master_key: str | bytes) -> bytes:
    aesgcm = AESGCM(_normalize_master_key(master_key))
    nonce = os.urandom(_NONCE_LEN)
    return nonce + aesgcm.encrypt(nonce, secret_bytes, None)


def _decrypt_private_key(ciphertext: bytes, master_key: str | bytes) -> bytes:
    aesgcm = AESGCM(_normalize_master_key(master_key))
    nonce = ciphertext[:_NONCE_LEN]
    return aesgcm.decrypt(nonce, ciphertext[_NONCE_LEN:], None)


async def load_persisted_wallet_keypair(
    db: Database, master_key: str | bytes
) -> Keypair | None:
    cursor = await db.conn.execute(
        """
        SELECT encrypted_private_key
        FROM wallet
        ORDER BY created_at DESC, public_key DESC
        LIMIT 1
        """
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    secret_bytes = _decrypt_private_key(row[0], master_key)
    return Keypair.from_bytes(secret_bytes)


async def persist_wallet_keypair(
    db: Database, master_key: str | bytes, keypair: Keypair
) -> None:
    encrypted = _encrypt_private_key(bytes(keypair), master_key)
    await db.conn.execute("DELETE FROM wallet")
    await db.conn.execute(
        """
        INSERT INTO wallet (public_key, encrypted_private_key, created_at)
        VALUES (?, ?, datetime('now'))
        """,
        (str(keypair.pubkey()), encrypted),
    )
    await db.conn.commit()
