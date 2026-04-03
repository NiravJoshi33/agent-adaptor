"""Full integration test — exercises the entire M1 stack against Surfpool.

Prerequisites:
    surfpool start  (runs local Solana validator on localhost:8899)
    OPENROUTER_API_KEY env var set

Run:
    uv run python tests/test_integration.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

from solana.rpc.async_api import AsyncClient as SolanaClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams

SURFPOOL_RPC = "http://127.0.0.1:8899"


async def wait_for_surfpool(rpc: SolanaClient, retries: int = 10) -> None:
    """Wait until Surfpool is ready."""
    for i in range(retries):
        try:
            resp = await rpc.is_connected()
            if resp:
                print("  Surfpool connected")
                return
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("Surfpool not reachable at " + SURFPOOL_RPC)


async def airdrop_and_confirm(
    rpc: SolanaClient, pubkey: Pubkey, lamports: int
) -> None:
    """Request airdrop and wait for confirmation."""
    resp = await rpc.request_airdrop(pubkey, lamports)
    sig = resp.value
    for _ in range(30):
        status = await rpc.confirm_transaction(sig)
        if status.value and status.value[0]:
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("Airdrop confirmation timeout")


async def main() -> None:
    print("=" * 60)
    print("Agent Adapter Runtime — Full Integration Test")
    print("=" * 60)
    print()

    # ── 1. Database + Persistence ──────────────────────────────────
    print("[1/8] Database & Persistence")
    from agent_adapter.store.database import Database
    from agent_adapter.store.encryption import WalletDerivedSecretsBackend
    from agent_adapter.store.secrets import SecretsStore
    from agent_adapter.store.state import StateStore

    db_path = os.path.join(tempfile.mkdtemp(), "integration_test.db")
    db = Database(db_path)
    await db.connect()
    print("  SQLite initialized with all 7 tables")

    # ── 2. Wallet — solana-raw against Surfpool ────────────────────
    print("[2/8] Wallet (solana-raw) + Surfpool")
    from wallet_solana_raw import SolanaRawWallet

    wallet = SolanaRawWallet.generate(rpc_url=SURFPOOL_RPC, cluster="devnet")
    address = await wallet.get_address()
    print(f"  Generated wallet: {address}")

    rpc = SolanaClient(SURFPOOL_RPC)
    await wait_for_surfpool(rpc)

    # Airdrop 2 SOL
    pubkey = Pubkey.from_string(address)
    await airdrop_and_confirm(rpc, pubkey, 2_000_000_000)

    # Verify balance via wallet plugin (real RPC query)
    balance = await wallet.get_balance()
    print(f"  Balance after airdrop: {balance['sol']} SOL (via get_balance RPC)")
    assert balance["sol"] >= 2.0, f"Expected >= 2 SOL, got {balance['sol']}"
    balance_sol = balance["sol"]

    # Sign and send a real transaction
    recipient = Keypair()
    tx_amount = 100_000_000  # 0.1 SOL
    ix = transfer(
        TransferParams(
            from_pubkey=wallet.keypair.pubkey(),
            to_pubkey=recipient.pubkey(),
            lamports=tx_amount,
        )
    )
    from solders.message import Message
    from solders.transaction import Transaction

    blockhash_resp = await rpc.get_latest_blockhash()
    blockhash = blockhash_resp.value.blockhash
    msg = Message.new_with_blockhash([ix], wallet.keypair.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([wallet.keypair], blockhash)

    send_resp = await rpc.send_transaction(tx)
    print(f"  Transfer tx: {send_resp.value}")

    # Confirm recipient got funds
    await asyncio.sleep(1)
    recip_balance = await rpc.get_balance(recipient.pubkey())
    assert recip_balance.value == tx_amount
    print(f"  Recipient balance: {recip_balance.value / 1e9} SOL ✓")

    # Sign message
    sig = await wallet.sign_message(b"integration test")
    assert len(sig) == 64
    print(f"  sign_message: {len(sig)} bytes ✓")

    # ── 3. Wallet — OWS ───────────────────────────────────────────
    print("[3/8] Wallet (OWS)")
    from wallet_ows import OWSWalletPlugin

    ows_wallet = OWSWalletPlugin(
        wallet_name="integration-test", rpc_url=SURFPOOL_RPC
    )
    await ows_wallet.initialize()
    ows_address = await ows_wallet.get_address()
    print(f"  OWS wallet address: {ows_address}")

    # Airdrop to OWS wallet and verify balance via RPC
    ows_pubkey = Pubkey.from_string(ows_address)
    await airdrop_and_confirm(rpc, ows_pubkey, 1_000_000_000)
    ows_balance = await ows_wallet.get_balance()
    print(f"  OWS balance: {ows_balance['sol']} SOL (via get_balance RPC)")
    assert ows_balance["sol"] >= 1.0, f"Expected >= 1 SOL, got {ows_balance['sol']}"

    ows_sig = await ows_wallet.sign_message(b"integration test")
    assert len(ows_sig) == 64
    print(f"  OWS sign_message: {len(ows_sig)} bytes ✓")

    # Cleanup OWS test wallet
    import ows

    ows.delete_wallet("integration-test")

    # Both implement same ABC
    from agent_adapter_contracts.wallet import WalletPlugin

    assert isinstance(wallet, WalletPlugin)
    assert isinstance(ows_wallet, WalletPlugin)
    print("  Both wallets implement WalletPlugin ABC ✓")

    # ── 4. Secrets (encrypted at rest) ─────────────────────────────
    print("[4/8] Secrets Store (encrypted)")
    backend = WalletDerivedSecretsBackend(wallet.secret_bytes)
    secrets = SecretsStore(db, backend)

    await secrets.store("agicitizens", "api_key", "sk-test-12345")
    retrieved = await secrets.retrieve("agicitizens", "api_key")
    assert retrieved == "sk-test-12345"

    # Verify encrypted at rest
    cursor = await db.conn.execute(
        "SELECT encrypted_value FROM secrets WHERE platform='agicitizens' AND key='api_key'"
    )
    row = await cursor.fetchone()
    assert row[0] != b"sk-test-12345", "Secret stored in plaintext!"
    print("  Store + retrieve + encryption at rest ✓")

    # ── 5. State Store ─────────────────────────────────────────────
    print("[5/8] State Store")
    state = StateStore(db)
    await state.set("platforms", "agicitizens", {"agent_id": "bot1", "status": "active"})
    data = await state.get("platforms", "agicitizens")
    assert data["agent_id"] == "bot1"
    keys = await state.list("platforms")
    assert "agicitizens" in keys
    print("  Set + get + list ✓")

    # ── 6. Capability Registry ─────────────────────────────────────
    print("[6/8] Capability Registry")
    from agent_adapter.capabilities.registry import CapabilityRegistry
    from agent_adapter.capabilities.openapi import fetch_and_parse
    from agent_adapter_contracts.types import PricingConfig

    # Fetch real spec
    caps, spec_hash = await fetch_and_parse(
        "https://petstore3.swagger.io/api/v3/openapi.json"
    )
    registry = CapabilityRegistry()
    for c in caps:
        registry.register(c)
    print(f"  Ingested {len(caps)} capabilities from Petstore (hash={spec_hash})")

    # Enable and price one
    registry.enable("addPet")
    cap = registry.get("addPet")
    cap.pricing = PricingConfig(model="per_call", amount=0.01)
    tools = registry.to_tool_definitions()
    assert len(tools) == 1
    assert tools[0].name == "cap__addPet"
    print(f"  Enabled 'addPet', generated {len(tools)} cap__* tool ✓")

    # ── 7. Payment Adapters ────────────────────────────────────────
    print("[7/8] Payment Adapters")
    from agent_adapter.payments.registry import PaymentRegistry
    from agent_adapter_contracts.payments import PaymentChallenge
    from payment_free import FreeAdapter
    from payment_x402 import X402Adapter
    from payment_escrow import EscrowAdapter

    pay_registry = PaymentRegistry()
    pay_registry.register(FreeAdapter())
    pay_registry.register(X402Adapter())
    pay_registry.register(EscrowAdapter())
    print(f"  Registered: {pay_registry.list()}")

    # Free adapter — full round trip
    free_challenge = PaymentChallenge(type="free")
    adapter = pay_registry.resolve(free_challenge)
    receipt = await adapter.execute(free_challenge, wallet)
    assert receipt.protocol == "free"
    assert receipt.amount == 0.0
    print("  Free adapter: resolve + execute ✓")

    # x402 + escrow resolve correctly
    assert pay_registry.resolve(PaymentChallenge(type="x402")).id == "x402"
    assert pay_registry.resolve(PaymentChallenge(type="escrow")).id == "solana_escrow"
    print("  x402 + escrow: resolve ✓")

    # ── 8. Job Engine ──────────────────────────────────────────────
    print("[8/8] Job Engine")
    from agent_adapter.jobs.engine import JobEngine

    engine = JobEngine(db)
    job_id = await engine.create(
        capability="addPet",
        input_data={"name": "Fido", "status": "available"},
        platform="agicitizens",
        platform_ref="task_001",
        payment_protocol="free",
        payment_amount=0.01,
    )
    print(f"  Created job: {job_id}")

    await engine.mark_executing(job_id)
    await engine.mark_completed(job_id, output_hash="petstore_response_hash")
    job = await engine.get(job_id)
    assert job["status"] == "completed"
    assert job["payment_status"] == "settled"
    earnings = await engine.earnings_today()
    assert earnings == 0.01
    print(f"  Lifecycle: pending → executing → completed ✓")
    print(f"  Earnings today: {earnings} USDC ✓")

    # ── Agent Loop (optional — requires OPENROUTER_API_KEY) ────────
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key:
        print()
        print("[Bonus] Agent Loop (OpenRouter)")
        from agent_adapter.tools.handlers import ToolHandlers
        from agent_adapter.agent.loop import AgentLoop

        async def whoami():
            return {
                "wallet": address,
                "sol_balance": balance_sol,
                "usdc_balance": 0.0,
                "registered_platforms": ["agicitizens"],
                "capabilities": [{"name": "addPet", "pricing": "$0.01/call"}],
                "active_jobs": 0,
                "jobs_completed_today": 1,
                "earnings_today": 0.01,
                "payment_adapters": pay_registry.list(),
                "agent_status": "running",
            }

        handlers = ToolHandlers(wallet, secrets, state, whoami_fn=whoami)
        agent = AgentLoop(
            api_key=api_key,
            model="openai/gpt-oss-120b",
            handlers=handlers,
            max_tool_rounds=3,
        )
        result = await agent.run_once(
            "Check your status and report your wallet address and balance."
        )
        print(f"  Agent response: {result[:200]}")
        await handlers.close()
        print("  Agent loop ✓")
    else:
        print()
        print("[Skip] Agent loop — set OPENROUTER_API_KEY to test")

    # ── Cleanup ────────────────────────────────────────────────────
    await rpc.close()
    await db.close()

    print()
    print("=" * 60)
    print("ALL INTEGRATION TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
