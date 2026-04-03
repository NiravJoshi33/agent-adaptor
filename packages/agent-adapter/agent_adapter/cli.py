"""CLI entrypoint for agent-adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import uvicorn
import yaml

from agent_adapter.management import create_management_app
from agent_adapter.runtime import create_runtime


DEFAULT_SYSTEM_PROMPT = """## Provider Instructions

- Review discovered capabilities and set pricing before going live.
- Keep credentials in the runtime secrets store.
- Prefer direct capability execution through cap__* tools.
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-adapter")
    parser.add_argument("--config", default="agent-adapter.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--adapter-name", default="my-agent")
    init.add_argument("--data-dir", default="./data")
    init.add_argument("--wallet-provider", default="solana-raw")
    init.add_argument("--dashboard-port", type=int, default=9090)
    init.add_argument("--dashboard-bind", default="127.0.0.1")

    start = sub.add_parser("start")
    start.add_argument("--once", action="store_true")
    start.add_argument("--api-only", action="store_true")

    sub.add_parser("status")

    wallet = sub.add_parser("wallet")
    wallet_sub = wallet.add_subparsers(dest="wallet_command", required=True)
    wallet_sub.add_parser("balance")

    agent = sub.add_parser("agent")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_sub.add_parser("pause")
    agent_sub.add_parser("resume")
    decisions = agent_sub.add_parser("decisions")
    decisions.add_argument("--limit", type=int, default=20)

    caps = sub.add_parser("capabilities")
    caps_sub = caps.add_subparsers(dest="caps_command", required=True)
    caps_sub.add_parser("list")
    caps_sub.add_parser("refresh")
    for name in ("enable", "disable"):
        cmd = caps_sub.add_parser(name)
        cmd.add_argument("capability")
    price = caps_sub.add_parser("price")
    price.add_argument("capability")
    price.add_argument("--amount", type=float, required=True)
    price.add_argument("--model", required=True)
    price.add_argument("--currency", default="USDC")
    price.add_argument("--item-field", default="")
    price.add_argument("--floor", type=float, default=0.0)
    price.add_argument("--ceiling", type=float, default=0.0)
    return parser


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _write_init_files(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config).resolve()
    root = config_path.parent
    data_dir = (root / args.data_dir).resolve()
    prompts_dir = root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = prompts_dir / "system.md"
    prompt_path.write_text(DEFAULT_SYSTEM_PROMPT)

    config = {
        "adapter": {
            "name": args.adapter_name,
            "dataDir": str(data_dir),
            "dashboard": {
                "port": args.dashboard_port,
                "bind": args.dashboard_bind,
            },
        },
        "wallet": {
            "provider": args.wallet_provider,
            "config": {},
        },
        "agent": {
            "provider": "openrouter",
            "model": "openai/gpt-oss-120b",
            "base_url": "https://openrouter.ai/api/v1",
            "systemPromptFile": str(prompt_path),
            "appendToDefault": True,
            "loopInterval": 30,
        },
        "capabilities": {
            "source": {"type": "manual"},
            "definitions": [],
        },
        "payments": [{"type": "free"}],
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))

    from agent_adapter.store.database import Database

    db = Database(data_dir / "adapter.db")
    asyncio.run(db.connect())
    asyncio.run(db.close())
    return {
        "config": str(config_path),
        "database": str(data_dir / "adapter.db"),
        "prompt": str(prompt_path),
    }


async def _run_status(args: argparse.Namespace) -> dict[str, Any]:
    runtime = await create_runtime(args.config)
    try:
        return await runtime.whoami()
    finally:
        await runtime.close()


async def _run_wallet_balance(args: argparse.Namespace) -> dict[str, Any]:
    runtime = await create_runtime(args.config)
    try:
        return {"address": await runtime.wallet.get_address(), "balances": await runtime.wallet.get_balance()}
    finally:
        await runtime.close()


async def _run_capabilities(args: argparse.Namespace) -> Any:
    runtime = await create_runtime(args.config)
    try:
        if args.caps_command == "list":
            return {"capabilities": await runtime.list_capabilities()}
        if args.caps_command == "refresh":
            return {"capabilities": await runtime.refresh_capabilities()}
        if args.caps_command == "enable":
            return await runtime.set_capability_enabled(args.capability, True)
        if args.caps_command == "disable":
            return await runtime.set_capability_enabled(args.capability, False)
        if args.caps_command == "price":
            return await runtime.set_capability_pricing(
                args.capability,
                model=args.model,
                amount=args.amount,
                currency=args.currency,
                item_field=args.item_field,
                floor=args.floor,
                ceiling=args.ceiling,
            )
        raise ValueError(f"Unknown capabilities command: {args.caps_command}")
    finally:
        await runtime.close()


async def _run_agent_command(args: argparse.Namespace) -> Any:
    runtime = await create_runtime(args.config)
    try:
        if args.agent_command == "pause":
            return await runtime.pause_agent()
        if args.agent_command == "resume":
            return await runtime.resume_agent()
        if args.agent_command == "decisions":
            return {"decisions": await runtime.list_decisions(args.limit)}
        raise ValueError(f"Unknown agent command: {args.agent_command}")
    finally:
        await runtime.close()


async def _run_start(args: argparse.Namespace) -> None:
    runtime = await create_runtime(args.config)
    app = create_management_app(runtime)
    dashboard = runtime.config.get("adapter", {}).get("dashboard", {})
    host = dashboard.get("bind", "127.0.0.1")
    port = int(dashboard.get("port", 9090))

    if args.once:
        try:
            _print(
                {
                    "management_api": f"http://{host}:{port}",
                    "agent_result": await runtime.run_agent_once(),
                }
            )
        finally:
            await runtime.close()
        return

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info")
    )
    tasks = [asyncio.create_task(server.serve())]
    if not args.api_only:
        tasks.append(asyncio.create_task(runtime.run_agent_forever()))

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await runtime.close()


def app(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "init":
        _print(_write_init_files(args))
        return
    if args.command == "status":
        _print(asyncio.run(_run_status(args)))
        return
    if args.command == "wallet":
        _print(asyncio.run(_run_wallet_balance(args)))
        return
    if args.command == "capabilities":
        _print(asyncio.run(_run_capabilities(args)))
        return
    if args.command == "agent":
        _print(asyncio.run(_run_agent_command(args)))
        return
    if args.command == "start":
        asyncio.run(_run_start(args))
        return
    raise SystemExit(f"Unsupported command: {args.command}")
