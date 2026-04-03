"""Create a mock USDC token mint on Surfpool and fund wallets.

Returns the mint address so it can be used in x402 network config.
"""

from __future__ import annotations

import asyncio

from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import create_account, CreateAccountParams
from solders.transaction import Transaction
from solders.message import Message
from spl.token.instructions import (
    initialize_mint, InitializeMintParams,
    create_associated_token_account, get_associated_token_address,
    mint_to, MintToParams,
)
from spl.token.constants import TOKEN_PROGRAM_ID

RPC_URL = "http://127.0.0.1:8899"


async def create_usdc_mint(authority: Keypair) -> Pubkey:
    """Create a 6-decimal SPL token mint (mock USDC)."""
    async with AsyncClient(RPC_URL) as rpc:
        mint = Keypair()
        space = 82
        rent = (await rpc.get_minimum_balance_for_rent_exemption(space)).value
        bh = (await rpc.get_latest_blockhash()).value.blockhash

        create_ix = create_account(CreateAccountParams(
            from_pubkey=authority.pubkey(),
            to_pubkey=mint.pubkey(),
            lamports=rent,
            space=space,
            owner=TOKEN_PROGRAM_ID,
        ))
        init_ix = initialize_mint(InitializeMintParams(
            program_id=TOKEN_PROGRAM_ID,
            mint=mint.pubkey(),
            decimals=6,
            mint_authority=authority.pubkey(),
            freeze_authority=authority.pubkey(),
        ))

        msg = Message.new_with_blockhash([create_ix, init_ix], authority.pubkey(), bh)
        tx = Transaction.new_unsigned(msg)
        tx.sign([authority, mint], bh)
        await rpc.send_transaction(tx)
        await asyncio.sleep(2)

        return mint.pubkey()


async def fund_usdc(
    authority: Keypair,
    mint: Pubkey,
    recipient: Pubkey,
    amount: int,
) -> None:
    """Create ATA and mint USDC to a recipient."""
    async with AsyncClient(RPC_URL) as rpc:
        ata = get_associated_token_address(recipient, mint)

        # Create ATA
        bh = (await rpc.get_latest_blockhash()).value.blockhash
        create_ata_ix = create_associated_token_account(
            authority.pubkey(), recipient, mint
        )
        msg = Message.new_with_blockhash([create_ata_ix], authority.pubkey(), bh)
        tx = Transaction.new_unsigned(msg)
        tx.sign([authority], bh)
        await rpc.send_transaction(tx)
        await asyncio.sleep(1)

        # Mint tokens
        bh = (await rpc.get_latest_blockhash()).value.blockhash
        mint_ix = mint_to(MintToParams(
            program_id=TOKEN_PROGRAM_ID,
            mint=mint,
            dest=ata,
            mint_authority=authority.pubkey(),
            amount=amount,
            signers=[authority.pubkey()],
        ))
        msg = Message.new_with_blockhash([mint_ix], authority.pubkey(), bh)
        tx = Transaction.new_unsigned(msg)
        tx.sign([authority], bh)
        await rpc.send_transaction(tx)
        await asyncio.sleep(1)


async def get_usdc_balance(owner: Pubkey, mint: Pubkey) -> float:
    """Get USDC balance for a wallet."""
    async with AsyncClient(RPC_URL) as rpc:
        ata = get_associated_token_address(owner, mint)
        try:
            bal = await rpc.get_token_account_balance(ata)
            return bal.value.ui_amount or 0.0
        except Exception:
            return 0.0
