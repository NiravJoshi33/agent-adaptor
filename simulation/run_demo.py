"""Full end-to-end demo — Provider API + Task Platform + Agent Adapter.

This script:
1. Starts the provider's weather API (port 8001)
2. Starts the simulated task marketplace (port 8002)
3. Boots the agent adapter (reads config, discovers capabilities, applies pricing)
4. A "requester" posts a weather task to the marketplace
5. The agent autonomously: registers → discovers task → bids → executes → delivers

Prerequisites:
    - Surfpool running on :8899
    - OPENROUTER_API_KEY env var set

Run: uv run python simulation/run_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from typing import Any

import httpx
import uvicorn

# Ensure the repo root is on sys.path for simulation imports
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
    # Wait for server to be ready
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


async def post_task(platform_url: str) -> dict:
    """Requester posts a weather task to the marketplace."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{platform_url}/requester/tasks",
            json={
                "title": "Get current weather in Tokyo",
                "description": "I need the current temperature, conditions, and wind for Tokyo, Japan.",
                "required_capability": "get_current_weather",
                "budget": 0.05,
                "currency": "USDC",
                "input_data": {"location": "Tokyo"},
            },
        )
        resp.raise_for_status()
        return resp.json()


async def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: Set OPENROUTER_API_KEY env var")
        sys.exit(1)

    print("=" * 70)
    print("  Agent Adapter Runtime — Full Demo")
    print("  Provider: WeatherPro API (wraps wttr.in)")
    print("  Platform: TaskNet (simulated marketplace)")
    print("  Agent: openai/gpt-oss-120b via OpenRouter")
    print("=" * 70)
    print()

    # ── 1. Start servers ───────────────────────────────────────────
    from simulation.provider_api.server import app as provider_app
    from simulation.tasknet.server import app as platform_app

    logger.info("Starting provider API on :8001...")
    provider_task = await start_server(provider_app, 8001)

    logger.info("Starting task marketplace on :8002...")
    platform_task = await start_server(platform_app, 8002)

    # ── 2. Boot agent adapter ──────────────────────────────────────
    logger.info("Booting agent adapter...")

    from agent_adapter.config import load_config, apply_pricing_overlay
    from agent_adapter.capabilities.openapi import fetch_and_parse
    from agent_adapter.capabilities.registry import CapabilityRegistry
    from agent_adapter.store.database import Database
    from agent_adapter.store.encryption import WalletDerivedSecretsBackend
    from agent_adapter.store.secrets import SecretsStore
    from agent_adapter.store.state import StateStore
    from agent_adapter.wallet.loader import load_wallet
    from agent_adapter.payments import load_payment_registry
    from agent_adapter.jobs.engine import JobEngine
    from agent_adapter.tools.handlers import ToolHandlers
    from agent_adapter.agent.loop import AgentLoop

    config = load_config("simulation/agent-adapter.yaml")

    # Database
    db_path = os.path.join(tempfile.mkdtemp(), "demo.db")
    db = Database(db_path)
    await db.connect()

    # Wallet
    wallet_cfg = config["wallet"]
    wallet = await load_wallet(wallet_cfg["provider"], wallet_cfg.get("config", {}))
    address = await wallet.get_address()
    logger.info(f"Wallet: {address}")

    # Balance
    balance = await wallet.get_balance()
    logger.info(f"Balance: {balance['sol']} SOL, {balance['usdc']} USDC")

    # Secrets + State
    # For OWS wallet, derive encryption key from signing a deterministic message
    key_material = await wallet.sign_message(b"agent-adapter-encryption-key-derivation")
    backend = WalletDerivedSecretsBackend(key_material)
    secrets = SecretsStore(db, backend)
    state = StateStore(db)

    # Capabilities — discover from provider API
    spec_url = config["capabilities"]["source"]["url"]
    logger.info(f"Fetching OpenAPI spec from {spec_url}...")
    caps, spec_hash = await fetch_and_parse(spec_url)
    registry = CapabilityRegistry()
    for cap in caps:
        registry.register(cap)
    logger.info(f"Discovered {len(caps)} capabilities (hash={spec_hash})")

    # Apply pricing overlay
    pricing = config["capabilities"].get("pricing", {})
    apply_pricing_overlay(registry, pricing)
    priced = registry.list_priced()
    logger.info(f"Enabled + priced: {[c.name for c in priced]}")

    # Payments
    pay_registry = load_payment_registry(config.get("payments"), wallet=wallet)

    # Job engine
    job_engine = JobEngine(db)

    # ── 3. Requester posts a task ──────────────────────────────────
    platform_url = config["platform"]["url"]
    logger.info("Requester posting weather task...")
    task = await post_task(platform_url)
    logger.info(f"Task created: {task['id']} — {task['title']}")
    print()

    # ── 4. Agent runs ──────────────────────────────────────────────
    capabilities_info = [
        {"name": c.name, "description": c.description, "pricing": f"${c.pricing.amount}/call"}
        for c in priced
    ]

    async def whoami():
        active_jobs = await job_engine.list_active()
        earnings = await job_engine.earnings_today()
        return {
            "wallet": address,
            "sol_balance": balance["sol"],
            "usdc_balance": balance["usdc"],
            "registered_platforms": [],
            "capabilities": capabilities_info,
            "active_jobs": len(active_jobs),
            "earnings_today": earnings,
            "payment_adapters": pay_registry.list(),
            "agent_status": "running",
        }

    handlers = ToolHandlers(
        wallet,
        secrets,
        state,
        whoami_fn=whoami,
        capability_registry=registry,
        job_engine=job_engine,
    )
    agent_cfg = config["agent"]

    agent = AgentLoop(
        api_key=api_key,
        model=agent_cfg["model"],
        base_url=agent_cfg.get("base_url", "https://openrouter.ai/api/v1"),
        handlers=handlers,
        system_prompt=f"""You are an autonomous economic agent running the WeatherPro service.

## Your capabilities
You can execute these weather API calls for paying customers:
{chr(10).join(f"- {c['name']}: {c['description']} ({c['pricing']})" for c in capabilities_info)}

## The platform
TaskNet is a task marketplace at {platform_url}. To participate:
1. First read the platform docs: GET {platform_url}/docs.md
2. Register: POST /agents/challenge, then POST /agents/register with your wallet signature
3. Find tasks: GET /tasks?status=open (requires X-API-Key header)
4. Bid on matching tasks: POST /tasks/{{task_id}}/bid
5. Execute your capability by calling your provider API at http://127.0.0.1:8001
6. Deliver results: POST /tasks/{{task_id}}/deliver

## Rules
1. Start with status__whoami to understand your state
2. Register on the platform using wallet-signed challenge-response
3. Store the API key immediately with secrets__store
4. Find open tasks matching your capabilities
5. Bid at or below your configured price
6. Execute capabilities using the matching cap__* tool
7. Deliver the results back to the platform
""",
        max_tool_rounds=20,
        extra_tools=registry.to_tool_definitions(),
    )

    logger.info("Agent starting autonomous loop...")
    print()
    print("-" * 70)
    result = await agent.run_once(
        "Begin your planning loop. Register on the platform, find tasks, and complete them."
    )
    print("-" * 70)
    print()
    print("AGENT FINAL RESPONSE:")
    print(result)
    print()

    # ── 5. Check results ───────────────────────────────────────────
    logger.info("Checking task status on platform...")
    async with httpx.AsyncClient() as client:
        # Get all tasks to find the one we posted
        # We need an API key — check if the agent stored one
        stored_key = await secrets.retrieve("tasknet", "api_key")
        if stored_key:
            resp = await client.get(
                f"{platform_url}/tasks/{task['id']}",
                headers={"X-API-Key": stored_key},
            )
            if resp.status_code == 200:
                final_task = resp.json()
                logger.info(f"Task status: {final_task['status']}")
                if final_task.get("result"):
                    logger.info(f"Task result: {final_task['result']}")
            else:
                logger.info(f"Could not fetch task: {resp.status_code}")
        else:
            logger.info("Agent did not store an API key — checking tasks directly")
            # Read from in-memory state
            from simulation.tasknet.server import tasks as platform_tasks
            if task["id"] in platform_tasks:
                final = platform_tasks[task["id"]]
                logger.info(f"Task status: {final['status']}")
                if final.get("result"):
                    logger.info(f"Task result: {final['result']}")

    # ── Cleanup ────────────────────────────────────────────────────
    await handlers.close()
    await db.close()
    provider_task.cancel()
    platform_task.cancel()

    print()
    print("=" * 70)
    print("  Demo complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
