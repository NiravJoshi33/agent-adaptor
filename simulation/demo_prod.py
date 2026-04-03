"""Production-like demo — all gaps closed.

Real payments:
  - Provider API enforces x402 (returns 402, verifies on-chain via self-hosted facilitator)
  - Agent adapter uses x402HttpxClient (auto-handles 402, signs tx, retries with proof)
  - USDC SPL token minted on Surfpool for payment

Job tracking:
  - Every capability execution creates a job (pending → executing → completed/failed)
  - Job engine tracks payment amounts and status

Decision logging:
  - Every tool call persisted to decision_log table

Platform persistence:
  - Agent registration persisted to platforms table

Prerequisites:
    - Surfpool running on :8899
    - OPENROUTER_API_KEY env var set

Run: uv run python simulation/demo_prod.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from typing import Any

import httpx
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("demo")


async def start_server(app: Any, port: int) -> asyncio.Task:
    """Start a FastAPI app in the background."""
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(30):
        try:
            async with httpx.AsyncClient() as c:
                resp = await c.get(f"http://127.0.0.1:{port}/openapi.json")
                if resp.status_code == 200:
                    return task
        except Exception:
            pass
        await asyncio.sleep(0.3)
    raise RuntimeError(f"Server on port {port} failed to start")


async def fund_wallet_sol(rpc_url: str, address: str, lamports: int) -> None:
    """Airdrop SOL to a wallet via Surfpool."""
    from solana.rpc.async_api import AsyncClient
    from solders.pubkey import Pubkey

    async with AsyncClient(rpc_url) as rpc:
        pubkey = Pubkey.from_string(address)
        resp = await rpc.request_airdrop(pubkey, lamports)
        sig = resp.value
        for _ in range(30):
            status = await rpc.confirm_transaction(sig)
            if status.value and status.value[0]:
                return
            await asyncio.sleep(0.5)


async def post_tasks(platform_url: str) -> list[dict]:
    """Requester posts tasks to the marketplace."""
    task_defs = [
        {
            "title": "Get upcoming public holidays in Japan",
            "description": "Fetch next upcoming public holidays for Japan (JP). Return holiday names and dates.",
            "required_capability": "get_next_holidays",
            "budget": 0.05,
            "input_data": {"country_code": "JP"},
        },
        {
            "title": "Current weather in London",
            "description": "Get the current temperature, conditions, humidity and wind for London, UK.",
            "required_capability": "get_current_weather",
            "budget": 0.05,
            "input_data": {"location": "London"},
        },
    ]

    created = []
    async with httpx.AsyncClient() as client:
        for t in task_defs:
            resp = await client.post(f"{platform_url}/requester/tasks", json=t)
            resp.raise_for_status()
            created.append(resp.json())
    return created


async def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: Set OPENROUTER_API_KEY env var")
        sys.exit(1)

    RPC_URL = "http://127.0.0.1:8899"

    print("=" * 70)
    print("  Agent Adapter Runtime — Production-Like Demo")
    print("  Payment: x402 (on-chain USDC via Surfpool)")
    print("  All gaps closed: jobs, decisions, platform persistence")
    print("=" * 70)
    print()

    # ── 1. Create USDC mint on Surfpool ──────────────────────────
    from simulation.setup_usdc import create_usdc_mint, fund_usdc, get_usdc_balance
    from solders.keypair import Keypair as SoldersKeypair
    from solders.pubkey import Pubkey

    logger.info("Creating USDC mint on Surfpool...")
    mint_authority = SoldersKeypair()

    # Fund mint authority
    await fund_wallet_sol(RPC_URL, str(mint_authority.pubkey()), 5_000_000_000)
    usdc_mint = await create_usdc_mint(mint_authority)
    logger.info(f"USDC mint: {usdc_mint}")

    # ── 2. Start servers ───────────────────────────────────────────
    from simulation.provider_api.paid_server import (
        app as provider_app,
        PROVIDER_ADDRESS,
        PROVIDER_KEYPAIR,
        configure,
    )
    from simulation.tasknet.server import app as platform_app

    # Configure x402 with our USDC mint
    configure(str(usdc_mint))
    logger.info(f"x402 configured: USDC mint={usdc_mint}")

    # Create provider's USDC ATA so it can receive payments
    await fund_usdc(mint_authority, usdc_mint, Pubkey.from_string(PROVIDER_ADDRESS), 0)
    logger.info("Provider ATA created")

    logger.info("Starting x402-paid provider API on :8001...")
    provider_task = await start_server(provider_app, 8001)
    logger.info(f"  Provider wallet: {PROVIDER_ADDRESS}")

    logger.info("Starting task marketplace on :8002...")
    platform_task = await start_server(platform_app, 8002)

    # ── 3. Boot agent adapter ──────────────────────────────────────
    logger.info("Booting agent adapter...")

    from agent_adapter.store.database import Database
    from agent_adapter.store.encryption import WalletDerivedSecretsBackend
    from agent_adapter.store.secrets import SecretsStore
    from agent_adapter.store.state import StateStore
    from agent_adapter.payments.registry import PaymentRegistry
    from agent_adapter.jobs.engine import JobEngine
    from agent_adapter.tools.handlers import ToolHandlers
    from agent_adapter.agent.loop import AgentLoop
    from agent_adapter.extensions.registry import ExtensionRegistry
    from payment_free import FreeAdapter
    from payment_x402 import X402Adapter
    from payment_x402.http_client import X402HttpClient
    from wallet_solana_raw import SolanaRawWallet

    # Database
    db_path = os.path.join(tempfile.mkdtemp(), "prod_demo.db")
    db = Database(db_path)
    await db.connect()

    # Wallet — use solana-raw so we have access to the keypair for x402
    wallet = SolanaRawWallet.generate(rpc_url=RPC_URL, cluster="devnet")
    address = await wallet.get_address()
    logger.info(f"Agent wallet: {address}")

    # Fund wallets with SOL (for tx fees) and USDC (for payments)
    logger.info("Funding wallets...")
    await fund_wallet_sol(RPC_URL, address, 5_000_000_000)
    await fund_wallet_sol(RPC_URL, PROVIDER_ADDRESS, 2_000_000_000)

    # Mint USDC to agent wallet (100 USDC = 100_000_000 smallest units)
    await fund_usdc(mint_authority, usdc_mint, Pubkey.from_string(address), 100_000_000)
    agent_usdc = await get_usdc_balance(Pubkey.from_string(address), usdc_mint)
    logger.info(f"Agent balance: 5.0 SOL, {agent_usdc} USDC")

    # Secrets + State
    backend = WalletDerivedSecretsBackend(wallet.secret_bytes)
    secrets = SecretsStore(db, backend)
    state = StateStore(db)

    # Extensions
    extensions = ExtensionRegistry()

    # Job engine
    job_engine = JobEngine(db, extensions)

    # Payment adapters
    pay_registry = PaymentRegistry()
    pay_registry.register(FreeAdapter())

    # x402 adapter — with the wallet's keypair for signing payments
    x402_adapter = X402Adapter(keypair=wallet.keypair, rpc_url=RPC_URL)
    pay_registry.register(x402_adapter)
    logger.info(f"Payment adapters: {pay_registry.list()}")

    # x402 HTTP client — wraps httpx with automatic 402 handling
    x402_http = X402HttpClient(keypair=wallet.keypair, rpc_url=RPC_URL)

    # ── 3. Requester posts tasks ───────────────────────────────────
    platform_url = "http://127.0.0.1:8002"
    provider_url = "http://127.0.0.1:8001"

    logger.info("Requester posting tasks...")
    posted_tasks = await post_tasks(platform_url)
    for t in posted_tasks:
        logger.info(f"  Task: {t['id']} — {t['title']}")
    print()

    # ── 4. Agent runs ──────────────────────────────────────────────
    async def whoami():
        active = await job_engine.list_active()
        earnings = await job_engine.earnings_today()
        bal = await wallet.get_balance()
        usdc_bal = await get_usdc_balance(Pubkey.from_string(address), usdc_mint)
        return {
            "wallet": address,
            "sol_balance": bal["sol"],
            "usdc_balance": usdc_bal,
            "registered_platforms": [],
            "capabilities": [
                {"name": "get_current_weather", "endpoint": f"{provider_url}/weather/current", "price": "0.01 SOL (x402)"},
                {"name": "get_next_holidays", "endpoint": f"{provider_url}/holidays/next/{{country_code}}", "price": "0.005 SOL (x402)"},
                {"name": "get_country_info", "endpoint": f"{provider_url}/holidays/country/{{country_code}}", "price": "0.003 SOL (x402)"},
            ],
            "active_jobs": len(active),
            "earnings_today": earnings,
            "payment_adapters": pay_registry.list(),
            "agent_status": "running",
        }

    handlers = ToolHandlers(
        wallet=wallet,
        secrets=secrets,
        state=state,
        db=db,
        job_engine=job_engine,
        whoami_fn=whoami,
        x402_http_client=x402_http,
    )

    agent = AgentLoop(
        api_key=api_key,
        model="openai/gpt-oss-120b",
        handlers=handlers,
        system_prompt=f"""You are an autonomous economic agent. You MUST complete all steps below. Do NOT stop early.

## Step-by-step plan (execute ALL steps)
1. Call status__whoami to check your state
2. GET {platform_url}/docs.md to learn the registration flow
3. POST {platform_url}/agents/challenge with your wallet_address
4. Sign the challenge with wallet__sign_message
5. POST {platform_url}/agents/register with wallet_address, signature, name, capabilities
6. Store the API key with secrets__store (platform="tasknet", key="api_key")
7. Store registration with state__set (namespace="platforms", key="tasknet", data with agent_id)
8. GET {platform_url}/tasks?status=open with X-API-Key header to find tasks
9. For EACH open task: POST /tasks/{{task_id}}/bid with a price within budget
10. For EACH accepted task: Execute the capability by calling the provider API
11. For EACH completed task: POST /tasks/{{task_id}}/deliver with output containing the API response

## Your capabilities (provider API endpoints)
- get_current_weather: GET {provider_url}/weather/current?location=<city>
- get_next_holidays: GET {provider_url}/holidays/next/<country_code>
- get_country_info: GET {provider_url}/holidays/country/<country_code>

## x402 payment (IMPORTANT)
The provider API uses x402 payment. Your HTTP client handles this AUTOMATICALLY.
Just make normal GET requests. The 402 → payment → retry flow is transparent.
You have USDC in your wallet. Do NOT worry about payment — just call the endpoints.

## Delivery format
POST /tasks/{{task_id}}/deliver with JSON body: {{"output": <the API response data>}}
""",
        max_tool_rounds=25,
    )

    logger.info("Agent starting autonomous loop...")
    print()
    print("-" * 70)
    result = await agent.run_once(
        "Begin your planning loop. Register on TaskNet, find all open tasks, execute them using the paid provider API, and deliver results."
    )
    print("-" * 70)
    print()
    print("AGENT FINAL RESPONSE:")
    print(result)
    print()

    # ── 5. Verify everything ───────────────────────────────────────
    logger.info("=" * 50)
    logger.info("POST-DEMO VERIFICATION")
    logger.info("=" * 50)

    # Tasks
    from simulation.tasknet.server import tasks as platform_tasks
    for t in posted_tasks:
        final = platform_tasks.get(t["id"], {})
        logger.info(f"Task {t['id']}: {final.get('status', 'unknown')}")
        if final.get("result"):
            r = json.dumps(final["result"])
            logger.info(f"  Result: {r[:300]}...")

    # Wallet balance after payments
    final_balance = await wallet.get_balance()
    logger.info(f"Agent wallet balance: {final_balance['sol']} SOL (started with 5.0)")
    logger.info(f"  SOL spent: {5.0 - final_balance['sol']:.6f} SOL")

    # Decision log
    cursor = await db.conn.execute(
        "SELECT COUNT(*) FROM decision_log"
    )
    count = (await cursor.fetchone())[0]
    logger.info(f"Decision log entries: {count}")

    cursor = await db.conn.execute(
        "SELECT action, detail FROM decision_log ORDER BY id DESC LIMIT 5"
    )
    rows = await cursor.fetchall()
    for action, detail in rows:
        d = json.loads(detail) if detail else {}
        logger.info(f"  [{action}] {d.get('tool', '?')}")

    # Platforms table
    cursor = await db.conn.execute("SELECT * FROM platforms")
    rows = await cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    for row in rows:
        p = dict(zip(cols, row))
        logger.info(f"Platform: {p.get('platform_name')} — agent_id: {p.get('agent_id')}")

    # Jobs
    if job_engine:
        recent = await job_engine.list_recent(10)
        logger.info(f"Jobs tracked: {len(recent)}")
        for j in recent:
            logger.info(f"  {j['id']}: {j['capability']} — {j['status']}")

    # ── Cleanup ────────────────────────────────────────────────────
    await handlers.close()
    await x402_http.aclose()
    await db.close()
    provider_task.cancel()
    platform_task.cancel()

    print()
    print("=" * 70)
    print("  Production-like demo complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
