"""Persistence helpers for locally managed runtime wallets."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from solders.keypair import Keypair

from agent_adapter.store.database import Database

_KEY_FILENAME = "wallet.key"
_NONCE_LEN = 12


def _key_path(data_dir: Path) -> Path:
    return data_dir / _KEY_FILENAME


def _load_or_create_key(data_dir: Path) -> bytes:
    key_path = _key_path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        return key_path.read_bytes()

    key = AESGCM.generate_key(bit_length=256)
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


def _encrypt_private_key(secret_bytes: bytes, data_dir: Path) -> bytes:
    aesgcm = AESGCM(_load_or_create_key(data_dir))
    nonce = os.urandom(_NONCE_LEN)
    return nonce + aesgcm.encrypt(nonce, secret_bytes, None)


def _decrypt_private_key(ciphertext: bytes, data_dir: Path) -> bytes:
    aesgcm = AESGCM(_load_or_create_key(data_dir))
    nonce = ciphertext[:_NONCE_LEN]
    return aesgcm.decrypt(nonce, ciphertext[_NONCE_LEN:], None)


async def load_persisted_wallet_keypair(
    db: Database, data_dir: Path
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
    secret_bytes = _decrypt_private_key(row[0], data_dir)
    return Keypair.from_bytes(secret_bytes)


async def persist_wallet_keypair(
    db: Database, data_dir: Path, keypair: Keypair
) -> None:
    encrypted = _encrypt_private_key(bytes(keypair), data_dir)
    await db.conn.execute("DELETE FROM wallet")
    await db.conn.execute(
        """
        INSERT INTO wallet (public_key, encrypted_private_key, created_at)
        VALUES (?, ?, datetime('now'))
        """,
        (str(keypair.pubkey()), encrypted),
    )
    await db.conn.commit()
