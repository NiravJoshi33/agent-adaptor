"""Real API demo — Agent Adapter wrapping real free APIs (no mocks).

Provider monetizes:
  - Nager.Date (public holidays) — 5 endpoints
  - Open-Meteo (weather forecasts) — 1 endpoint

Platform: TaskNet (simulated marketplace on :8002)
Agent: autonomously registers, discovers tasks, executes real API calls, delivers.

Prerequisites:
    - Surfpool running on :8899
    - OPENROUTER_API_KEY env var set

Run: uv run python simulation/demo_real_api.py
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("demo")


async def start_platform(port: int) -> asyncio.Task:
    """Start the simulated task marketplace."""
    from simulation.tasknet.server import app

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
    raise RuntimeError("Platform failed to start")


async def post_tasks(platform_url: str) -> list[dict]:
    """Requester posts multiple tasks to the marketplace."""
    task_defs = [
        {
            "title": "Get upcoming public holidays in Japan",
            "description": "I need a list of the next upcoming public holidays in Japan (country code: JP). Return the holiday names and dates.",
            "required_capability": "get__api_v3_NextPublicHolidays_{countryCode}",
            "budget": 0.02,
            "input_data": {"countryCode": "JP"},
        },
        {
            "title": "7-day weather forecast for Paris",
            "description": "Get me a 7-day weather forecast for Paris, France (lat 48.8566, lon 2.3522). Include daily max/min temperature and precipitation.",
            "required_capability": "get__v1_forecast",
            "budget": 0.03,
            "input_data": {"latitude": 48.8566, "longitude": 2.3522},
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

    print("=" * 70)
    print("  Agent Adapter Runtime — Real API Demo")
    print("  APIs: Nager.Date (holidays) + Open-Meteo (weather)")
    print("  Platform: TaskNet (simulated)")
    print("  Agent: openai/gpt-oss-120b via OpenRouter")
    print("=" * 70)
    print()

    # ── 1. Start platform ──────────────────────────────────────────
    logger.info("Starting task marketplace on :8002...")
    platform_task = await start_platform(8002)

    # ── 2. Boot adapter ────────────────────────────────────────────
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

    config = load_config("simulation/demo_real_api.yaml")

    # Database
    db = Database(os.path.join(tempfile.mkdtemp(), "demo_real.db"))
    await db.connect()

    # Wallet
    wallet_cfg = config["wallet"]
    wallet = await load_wallet(wallet_cfg["provider"], wallet_cfg.get("config", {}))
    address = await wallet.get_address()
    logger.info(f"Wallet: {address}")

    # Secrets + State
    key_material = await wallet.sign_message(b"agent-adapter-encryption-key-derivation")
    backend = WalletDerivedSecretsBackend(key_material)
    secrets = SecretsStore(db, backend)
    state = StateStore(db)

    # Capabilities — discover from MULTIPLE real APIs
    registry = CapabilityRegistry()
    sources = config["capabilities"]["sources"]
    for src in sources:
        logger.info(f"Fetching spec from {src['url']}...")
        caps, h = await fetch_and_parse(src["url"], base_url=src.get("base_url", ""))
        for cap in caps:
            registry.register(cap)
        logger.info(f"  → {len(caps)} capabilities (hash={h})")

    # Apply pricing
    pricing = config["capabilities"].get("pricing", {})
    apply_pricing_overlay(registry, pricing)
    priced = registry.list_priced()
    logger.info(f"Enabled + priced: {len(priced)} capabilities")
    for c in priced:
        logger.info(f"  {c.name}: ${c.pricing.amount}/call — {c.base_url}{c.source_ref.split(' ', 1)[-1]}")

    # Payments
    pay_registry = load_payment_registry(config.get("payments"), wallet=wallet)

    # Job engine
    job_engine = JobEngine(db)

    # ── 3. Requester posts tasks ───────────────────────────────────
    platform_url = config["platform"]["url"]
    logger.info("Requester posting tasks...")
    posted_tasks = await post_tasks(platform_url)
    for t in posted_tasks:
        logger.info(f"  Task: {t['id']} — {t['title']}")
    print()

    # ── 4. Agent runs ──────────────────────────────────────────────
    capabilities_info = [
        {
            "name": c.name,
            "description": c.description,
            "endpoint": f"{c.base_url}{c.source_ref.split(' ', 1)[-1]}",
            "method": c.source_ref.split(" ", 1)[0],
            "pricing": f"${c.pricing.amount}/call",
            "params": list(c.input_schema.get("properties", {}).keys()),
        }
        for c in priced
    ]

    async def whoami():
        return {
            "wallet": address,
            "registered_platforms": [],
            "capabilities": capabilities_info,
            "active_jobs": len(await job_engine.list_active()),
            "earnings_today": await job_engine.earnings_today(),
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

    cap_summary = "\n".join(
        f"- {c['name']}: {c['description']} ({c['pricing']})\n"
        f"  Endpoint: {c['method']} {c['endpoint']}\n"
        f"  Params: {c['params']}"
        for c in capabilities_info
    )

    agent = AgentLoop(
        api_key=api_key,
        model=config["agent"]["model"],
        base_url=config["agent"].get("base_url", "https://openrouter.ai/api/v1"),
        handlers=handlers,
        system_prompt=f"""You are an autonomous economic agent monetizing real APIs.

## Your capabilities (real API endpoints you can call)
{cap_summary}

## How to execute capabilities
Use the matching cap__* tool for API execution. The runtime will build the HTTP request for you.

Examples:
- Holidays: GET https://date.nager.at/api/v3/NextPublicHolidays/JP
- Weather: GET https://api.open-meteo.com/v1/forecast?latitude=48.85&longitude=2.35&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto

## The platform
TaskNet is at {platform_url}.
1. GET {platform_url}/docs.md for registration flow
2. Register with wallet-signed challenge
3. GET /tasks?status=open to find work
4. POST /tasks/{{id}}/bid to bid
5. Execute the capability via the matching cap__* tool
6. POST /tasks/{{id}}/deliver with the output

## Rules
1. Start with status__whoami
2. Store API keys immediately with secrets__store
3. Match tasks to your capabilities by required_capability field
4. Execute capabilities using the matching cap__* tool
5. Deliver the actual API response data to the platform
""",
        max_tool_rounds=25,
        extra_tools=registry.to_tool_definitions(),
    )

    logger.info("Agent starting autonomous loop...")
    print()
    print("-" * 70)
    result = await agent.run_once(
        "Begin your planning loop. Register on TaskNet, find all open tasks, and complete them."
    )
    print("-" * 70)
    print()
    print("AGENT FINAL RESPONSE:")
    print(result)
    print()

    # ── 5. Verify results ──────────────────────────────────────────
    logger.info("Verifying task results...")
    from simulation.tasknet.server import tasks as platform_tasks

    for t in posted_tasks:
        final = platform_tasks.get(t["id"], {})
        status = final.get("status", "unknown")
        logger.info(f"  {t['id']} ({t['title'][:40]}): {status}")
        if final.get("result"):
            import json
            result_str = json.dumps(final["result"], indent=2)
            # Truncate long results
            if len(result_str) > 500:
                result_str = result_str[:500] + "\n    ... (truncated)"
            logger.info(f"  Result: {result_str}")

    await handlers.close()
    await db.close()
    platform_task.cancel()

    print()
    print("=" * 70)
    print("  Demo complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
