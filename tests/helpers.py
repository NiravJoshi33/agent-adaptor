"""Shared test helpers for local runtime tests."""

from __future__ import annotations

import asyncio

from solana.rpc.async_api import AsyncClient as SolanaClient
from solders.pubkey import Pubkey

SURFPOOL_RPC = "http://127.0.0.1:8899"


async def wait_for_surfpool(rpc: SolanaClient, retries: int = 10) -> None:
    """Wait until Surfpool is reachable."""
    for _ in range(retries):
        try:
            if await rpc.is_connected():
                return
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError(f"Surfpool not reachable at {SURFPOOL_RPC}")


async def airdrop_and_confirm(
    rpc: SolanaClient, pubkey: Pubkey, lamports: int
) -> None:
    """Request an airdrop and wait for confirmation."""
    resp = await rpc.request_airdrop(pubkey, lamports)
    sig = resp.value
    for _ in range(30):
        status = await rpc.confirm_transaction(sig)
        if status.value and status.value[0]:
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("Airdrop confirmation timeout")
