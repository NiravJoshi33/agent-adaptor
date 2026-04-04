"""CLI entrypoint for agent-adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import uvicorn
import yaml

from agent_adapter.management import create_management_app
from agent_adapter.plugins.discovery import list_all_plugins
from agent_adapter.plugins.discovery import discover_plugins
from agent_adapter.runtime import create_runtime
from agent_adapter.config import (
    add_driver_config,
    add_tool_plugin_config,
    remove_driver_config,
    remove_tool_plugin_config,
)


DEFAULT_SYSTEM_PROMPT = """## Provider Instructions

- Review discovered capabilities and set pricing before going live.
- Keep credentials in the runtime secrets store.
- Prefer direct capability execution through cap__* tools.
"""


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _validate_management_bind(config: dict[str, Any]) -> None:
    dashboard = config.get("adapter", {}).get("dashboard", {})
    host = str(dashboard.get("bind", "127.0.0.1") or "127.0.0.1")
    if _is_loopback_host(host):
        return
    if str(config.get("adapter", {}).get("managementToken", "") or ""):
        return
    if os.environ.get("AGENT_ADAPTER_MANAGEMENT_TOKEN", ""):
        return
    if bool(config.get("adapter", {}).get("allowUnsafeRemoteManagement", False)):
        return
    raise ValueError(
        "Remote management binds are blocked by default. "
        "Set adapter.managementToken (or AGENT_ADAPTER_MANAGEMENT_TOKEN), or explicitly enable allowUnsafeRemoteManagement only when external auth/TLS is already in front of the runtime."
    )


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
    wallet_sub.add_parser("address")
    wallet_sub.add_parser("balance")
    wallet_export_token = wallet_sub.add_parser("export-token")
    wallet_export_token.add_argument("--ttl-seconds", type=int, default=300)
    wallet_export = wallet_sub.add_parser("export")
    wallet_export.add_argument("--yes", action="store_true")
    wallet_export.add_argument("--output")
    wallet_import = wallet_sub.add_parser("import")
    wallet_import.add_argument("source")

    agent = sub.add_parser("agent")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_sub.add_parser("pause")
    agent_sub.add_parser("resume")
    decisions = agent_sub.add_parser("decisions")
    decisions.add_argument("--limit", type=int, default=20)

    prompt = sub.add_parser("prompt")
    prompt_sub = prompt.add_subparsers(dest="prompt_command", required=True)
    prompt_sub.add_parser("show")
    prompt_set = prompt_sub.add_parser("set")
    prompt_set.add_argument("--content")
    prompt_set.add_argument("--file")
    prompt_mode = prompt_sub.add_parser("mode")
    mode_group = prompt_mode.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--append", action="store_true")
    mode_group.add_argument("--replace", action="store_true")

    metrics = sub.add_parser("metrics")
    metrics_sub = metrics.add_subparsers(dest="metrics_command", required=True)
    metrics_summary = metrics_sub.add_parser("summary")
    metrics_summary.add_argument("--days", type=int, default=30)
    metrics_daily = metrics_sub.add_parser("daily")
    metrics_daily.add_argument("--days", type=int, default=14)
    metrics_export = metrics_sub.add_parser("export")
    metrics_export.add_argument("--days", type=int, default=30)
    metrics_export.add_argument("--format", choices=("csv", "json"), default="csv")
    metrics_export.add_argument("--output")

    platforms = sub.add_parser("platforms")
    platforms_sub = platforms.add_subparsers(dest="platforms_command", required=True)
    platforms_sub.add_parser("list")
    platforms_add = platforms_sub.add_parser("add")
    platforms_add.add_argument("url")
    platforms_add.add_argument("--name", default="")
    platforms_add.add_argument("--driver", default="")

    drivers = sub.add_parser("drivers")
    drivers_sub = drivers.add_subparsers(dest="drivers_command", required=True)
    drivers_sub.add_parser("list")
    drivers_install = drivers_sub.add_parser("install")
    drivers_install.add_argument("source")
    drivers_install.add_argument("--class-name")
    drivers_install.add_argument("--plugin-id")
    drivers_remove = drivers_sub.add_parser("remove")
    drivers_remove.add_argument("target")

    tools = sub.add_parser("tools")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    tools_sub.add_parser("list")
    tools_install = tools_sub.add_parser("install")
    tools_install.add_argument("source")
    tools_install.add_argument("--class-name")
    tools_install.add_argument("--plugin-id")
    tools_remove = tools_sub.add_parser("remove")
    tools_remove.add_argument("target")

    plugins = sub.add_parser("plugins")
    plugins_sub = plugins.add_subparsers(dest="plugins_command", required=True)
    plugins_sub.add_parser("list")

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


def _emit(data: Any) -> None:
    if isinstance(data, (dict, list)):
        _print(data)
        return
    print(data)


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
            "walletEncryptionKey": "${AGENT_ADAPTER_WALLET_ENCRYPTION_KEY}",
            "secretsEncryptionKey": "${AGENT_ADAPTER_SECRETS_ENCRYPTION_KEY}",
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
        "required_env": [
            "AGENT_ADAPTER_WALLET_ENCRYPTION_KEY",
            "AGENT_ADAPTER_SECRETS_ENCRYPTION_KEY",
        ],
    }


async def _run_status(args: argparse.Namespace) -> dict[str, Any]:
    runtime = await create_runtime(args.config)
    try:
        return await runtime.whoami()
    finally:
        await runtime.close()


async def _run_wallet_command(args: argparse.Namespace) -> Any:
    runtime = await create_runtime(args.config)
    try:
        if args.wallet_command == "address":
            return {"address": await runtime.wallet.get_address()}
        if args.wallet_command == "balance":
            return {
                "address": await runtime.wallet.get_address(),
                "balances": await runtime.wallet.get_balance(),
            }
        if args.wallet_command == "export-token":
            return await runtime.issue_wallet_export_token(ttl_seconds=args.ttl_seconds)
        if args.wallet_command == "export":
            if not args.yes:
                raise ValueError("wallet export requires --yes because it reveals private key material.")
            exported = await runtime.export_wallet_secret()
            if args.output:
                Path(args.output).write_text(exported["secret_key"] + "\n")
                return {
                    "written": True,
                    "output": str(Path(args.output).resolve()),
                    "provider": exported["provider"],
                    "encoding": exported["encoding"],
                }
            return exported
        if args.wallet_command == "import":
            source_path = Path(args.source)
            secret = source_path.read_text().strip() if source_path.exists() else args.source.strip()
            return await runtime.import_wallet_secret(secret)
        raise ValueError(f"Unknown wallet command: {args.wallet_command}")
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


async def _run_prompt_command(args: argparse.Namespace) -> Any:
    runtime = await create_runtime(args.config)
    try:
        if args.prompt_command == "show":
            return await runtime.get_prompt_settings()
        if args.prompt_command == "set":
            content = args.content
            if args.file:
                content = Path(args.file).read_text()
            if content is None:
                raise ValueError("Provide --content or --file for prompt set.")
            return await runtime.update_prompt_settings(custom_prompt=content)
        if args.prompt_command == "mode":
            return await runtime.update_prompt_settings(
                append_to_default=True if args.append else False
            )
        raise ValueError(f"Unknown prompt command: {args.prompt_command}")
    finally:
        await runtime.close()


async def _run_metrics_command(args: argparse.Namespace) -> Any:
    runtime = await create_runtime(args.config)
    try:
        if args.metrics_command == "summary":
            return await runtime.get_metrics_summary(args.days)
        if args.metrics_command == "daily":
            return {"series": await runtime.get_metrics_timeseries(args.days)}
        if args.metrics_command == "export":
            content = await runtime.export_metrics(args.days, args.format)
            if args.output:
                Path(args.output).write_text(content + ("\n" if not content.endswith("\n") else ""))
                return {
                    "written": True,
                    "output": str(Path(args.output).resolve()),
                    "format": args.format,
                    "days": args.days,
                }
            return content
        raise ValueError(f"Unknown metrics command: {args.metrics_command}")
    finally:
        await runtime.close()


async def _run_drivers_command(args: argparse.Namespace) -> Any:
    if args.drivers_command == "install":
        return await _install_driver(args)
    if args.drivers_command == "remove":
        return await _remove_driver(args)

    runtime = await create_runtime(args.config)
    try:
        if args.drivers_command == "list":
            return {"drivers": await runtime.list_drivers()}
        raise ValueError(f"Unknown drivers command: {args.drivers_command}")
    finally:
        await runtime.close()


async def _run_tools_command(args: argparse.Namespace) -> Any:
    if args.tools_command == "install":
        return await _install_tool_plugin(args)
    if args.tools_command == "remove":
        return await _remove_tool_plugin(args)

    runtime = await create_runtime(args.config)
    try:
        if args.tools_command == "list":
            return {"tools": await runtime.list_tool_plugins()}
        raise ValueError(f"Unknown tools command: {args.tools_command}")
    finally:
        await runtime.close()


async def _run_platforms_command(args: argparse.Namespace) -> Any:
    runtime = await create_runtime(args.config)
    try:
        if args.platforms_command == "list":
            return {"platforms": await runtime.list_platforms()}
        if args.platforms_command == "add":
            return await runtime.add_platform(
                args.url,
                platform_name=args.name,
                driver=args.driver,
            )
        raise ValueError(f"Unknown platforms command: {args.platforms_command}")
    finally:
        await runtime.close()


def _discover_plugin_class(
    source: str,
    *,
    explicit_class_name: str | None,
    base_class: type,
    label: str,
    import_prefix: str,
) -> str:
    import importlib.util
    import inspect

    module_path = Path(source).resolve()
    spec = importlib.util.spec_from_file_location(
        f"{import_prefix}_{abs(hash(str(module_path)))}",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {label} module from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if explicit_class_name:
        return explicit_class_name
    matches = [
        name
        for name, value in inspect.getmembers(module, inspect.isclass)
        if issubclass(value, base_class) and value is not base_class
    ]
    if not matches:
        raise ValueError(f"No {label} implementation found in {source}")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple {label} implementations found in {source}; pass --class-name"
        )
    return matches[0]


def _discover_driver_class(source: str, explicit_class_name: str | None = None) -> str:
    from agent_adapter_contracts.drivers import PlatformDriver

    return _discover_plugin_class(
        source,
        explicit_class_name=explicit_class_name,
        base_class=PlatformDriver,
        label="PlatformDriver",
        import_prefix="agent_adapter_install_driver",
    )


def _discover_tool_plugin_class(
    source: str, explicit_class_name: str | None = None
) -> str:
    from agent_adapter_contracts.tool_plugins import ToolPlugin

    return _discover_plugin_class(
        source,
        explicit_class_name=explicit_class_name,
        base_class=ToolPlugin,
        label="ToolPlugin",
        import_prefix="agent_adapter_install_tool_plugin",
    )


async def _install_driver(args: argparse.Namespace) -> Any:
    source = args.source
    source_path = Path(source)
    if source_path.exists() and source_path.suffix == ".py":
        class_name = _discover_driver_class(source, args.class_name)
        entry = {
            "module": str(source_path.resolve()),
            "class_name": class_name,
            "config": {},
        }
        add_driver_config(args.config, entry)
        return {
            "installed": True,
            "mode": "file",
            "module": entry["module"],
            "class_name": class_name,
        }

    before = set(discover_plugins("driver"))
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")
    subprocess.run(
        ["uv", "pip", "install", source],
        check=True,
        env=env,
    )
    after = discover_plugins("driver")
    plugin_id = args.plugin_id
    if not plugin_id:
        new_ids = sorted(set(after) - before)
        if len(new_ids) == 1:
            plugin_id = new_ids[0]
        elif len(new_ids) == 0 and source in after:
            plugin_id = source
        else:
            raise ValueError(
                "Could not determine installed driver plugin id automatically; pass --plugin-id"
            )
    if plugin_id not in after:
        raise ValueError(f'Installed driver plugin "{plugin_id}" was not discovered')
    add_driver_config(args.config, {"id": plugin_id})
    return {
        "installed": True,
        "mode": "plugin",
        "plugin_id": plugin_id,
        "source": source,
    }


async def _remove_driver(args: argparse.Namespace) -> Any:
    try:
        index = int(args.target) - 1
    except ValueError as exc:
        raise ValueError("drivers remove expects a 1-based config index") from exc
    _, removed = remove_driver_config(args.config, index)
    return {
        "removed": True,
        "index": index + 1,
        "driver": removed,
    }


async def _install_tool_plugin(args: argparse.Namespace) -> Any:
    source = args.source
    source_path = Path(source)
    if source_path.exists() and source_path.suffix == ".py":
        class_name = _discover_tool_plugin_class(source, args.class_name)
        entry = {
            "module": str(source_path.resolve()),
            "class_name": class_name,
            "config": {},
        }
        add_tool_plugin_config(args.config, entry)
        return {
            "installed": True,
            "mode": "file",
            "module": entry["module"],
            "class_name": class_name,
        }

    before = set(discover_plugins("tool"))
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")
    subprocess.run(
        ["uv", "pip", "install", source],
        check=True,
        env=env,
    )
    after = discover_plugins("tool")
    plugin_id = args.plugin_id
    if not plugin_id:
        new_ids = sorted(set(after) - before)
        if len(new_ids) == 1:
            plugin_id = new_ids[0]
        elif len(new_ids) == 0 and source in after:
            plugin_id = source
        else:
            raise ValueError(
                "Could not determine installed tool plugin id automatically; pass --plugin-id"
            )
    if plugin_id not in after:
        raise ValueError(f'Installed tool plugin "{plugin_id}" was not discovered')
    add_tool_plugin_config(args.config, {"id": plugin_id})
    return {
        "installed": True,
        "mode": "plugin",
        "plugin_id": plugin_id,
        "source": source,
    }


async def _remove_tool_plugin(args: argparse.Namespace) -> Any:
    try:
        index = int(args.target) - 1
    except ValueError as exc:
        raise ValueError("tools remove expects a 1-based config index") from exc
    _, removed = remove_tool_plugin_config(args.config, index)
    return {
        "removed": True,
        "index": index + 1,
        "tool": removed,
    }


def _run_plugins_command(args: argparse.Namespace) -> Any:
    if args.plugins_command == "list":
        return list_all_plugins()
    raise ValueError(f"Unknown plugins command: {args.plugins_command}")


async def _run_start(args: argparse.Namespace) -> None:
    runtime = await create_runtime(args.config)
    app = create_management_app(runtime)
    dashboard = runtime.config.get("adapter", {}).get("dashboard", {})
    host = dashboard.get("bind", "127.0.0.1")
    port = int(dashboard.get("port", 9090))
    _validate_management_bind(runtime.config)

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
    except asyncio.CancelledError:
        pass
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
        _emit(asyncio.run(_run_wallet_command(args)))
        return
    if args.command == "capabilities":
        _print(asyncio.run(_run_capabilities(args)))
        return
    if args.command == "agent":
        _print(asyncio.run(_run_agent_command(args)))
        return
    if args.command == "prompt":
        _print(asyncio.run(_run_prompt_command(args)))
        return
    if args.command == "metrics":
        _emit(asyncio.run(_run_metrics_command(args)))
        return
    if args.command == "platforms":
        _print(asyncio.run(_run_platforms_command(args)))
        return
    if args.command == "drivers":
        _print(asyncio.run(_run_drivers_command(args)))
        return
    if args.command == "tools":
        _print(asyncio.run(_run_tools_command(args)))
        return
    if args.command == "plugins":
        _print(_run_plugins_command(args))
        return
    if args.command == "start":
        try:
            asyncio.run(_run_start(args))
        except KeyboardInterrupt:
            pass
        return
    raise SystemExit(f"Unsupported command: {args.command}")
