"""Verbose agent cycle demo — real LLM, real wallet, real DB, real x402 payments.

Pre-recorded video demo showing the full runtime loop with tool-by-tool tracing.
No mocks. Every tool call, decision, and transaction is real:

  - Solana wallet (solana-raw) on Surfpool local validator
  - USDC SPL token minted on-chain
  - x402 HTTP-native payments (402 → build tx → co-sign → submit → serve)
  - LLM via OpenRouter (openai/gpt-oss-120b)
  - SQLite database for jobs, decisions, metrics
  - TaskNet marketplace for task discovery and delivery
  - Real weather + holiday APIs behind x402 paywall

Prerequisites:
    - Surfpool running on :8899
    - OPENROUTER_API_KEY env var set

Run: uv run python simulation/demo_verbose_cycle.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
import uvicorn

# Load .env from repo root before anything else
_repo_root = Path(__file__).resolve().parent.parent
_env_file = _repo_root / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

sys.path.insert(0, str(_repo_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
# Silence noisy loggers — we have our own tracing
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("solana").setLevel(logging.WARNING)
logging.getLogger("agent_adapter.agent.loop").setLevel(logging.WARNING)
logging.getLogger("payment_x402").setLevel(logging.WARNING)
logger = logging.getLogger("demo")

# ── Pretty printing ──────────────────────────────────────────────────

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
BLUE = "\033[34m"
WHITE = "\033[97m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
BG_DARK = "\033[48;5;236m"

# Tool name → human-friendly label + emoji-free icon
TOOL_LABELS: dict[str, tuple[str, str]] = {
    "status__whoami": ("Runtime Status", "SYS"),
    "net__http_request": ("HTTP Request", "NET"),
    "net__fetch_spec": ("Fetch Spec", "NET"),
    "wallet__sign_message": ("Wallet Sign", "KEY"),
    "wallet__get_address": ("Wallet Address", "KEY"),
    "wallet__get_balance": ("Wallet Balance", "KEY"),
    "secrets__store": ("Store Secret", "SEC"),
    "secrets__retrieve": ("Retrieve Secret", "SEC"),
    "state__set": ("Persist State", "DB"),
    "state__get": ("Read State", "DB"),
    "state__list": ("List State", "DB"),
    "jobs__create": ("Create Job", "JOB"),
    "jobs__pending": ("Pending Jobs", "JOB"),
    "pay_x402__execute": ("x402 Payment", "PAY"),
}


# ── x402 log tap — capture payment events during cap__ calls ──────────

_x402_handler: logging.Handler | None = None


class _X402TapHandler(logging.Handler):
    """Captures x402 log messages into a list for inline display."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        # Translate raw log lines into clean event descriptions
        if "Got 402" in msg:
            url = msg.split("Got 402 from ")[-1].split(" —")[0]
            self._events.append(f"402 Payment Required → {url}")
        elif "Building USDC transfer" in msg:
            parts = msg.split("Building USDC transfer: ")[-1]
            self._events.append(f"Building USDC tx: {parts}")
        elif "Retrying" in msg:
            parts = msg.split("Retrying ")[-1].split(" with")[0]
            self._events.append(f"Retrying with payment proof → {parts}")


def _install_x402_tap(events: list[str]) -> None:
    global _x402_handler
    x402_logger = logging.getLogger("payment_x402.http_client")
    _x402_handler = _X402TapHandler(events)
    _x402_handler.setLevel(logging.DEBUG)
    x402_logger.addHandler(_x402_handler)
    x402_logger.setLevel(logging.DEBUG)


def _remove_x402_tap() -> None:
    global _x402_handler
    if _x402_handler:
        x402_logger = logging.getLogger("payment_x402.http_client")
        x402_logger.removeHandler(_x402_handler)
        x402_logger.setLevel(logging.WARNING)
        _x402_handler = None


def _banner(text: str) -> None:
    w = 72
    print()
    print(f"  {BOLD}{MAGENTA}{'━' * w}{RESET}")
    print(f"  {BOLD}{MAGENTA}┃{RESET}  {BOLD}{WHITE}{text}{RESET}{' ' * (w - len(text) - 3)}{BOLD}{MAGENTA}┃{RESET}")
    print(f"  {BOLD}{MAGENTA}{'━' * w}{RESET}")
    print()


def _section(text: str) -> None:
    print(f"\n  {BOLD}{CYAN}{'─' * 3} {text} {'─' * max(1, 56 - len(text))}{RESET}\n")


def _step(number: int, text: str) -> None:
    idx = f"0{number}" if number < 10 else str(number)
    print(f"  {DIM}{CYAN}[{idx}]{RESET} {text}")


def _kv(key: str, value: str, indent: int = 6) -> None:
    pad = " " * indent
    print(f"{pad}{DIM}{key}:{RESET} {BOLD}{value}{RESET}")


def _json_block(label: str, payload: Any, max_lines: int = 12) -> None:
    print(f"      {YELLOW}{label}{RESET}")
    text = json.dumps(payload, indent=2, sort_keys=True, default=str, ensure_ascii=False) if not isinstance(payload, str) else payload
    lines = text.split("\n")
    for line in lines[:max_lines]:
        print(f"      {DIM}{line}{RESET}")
    if len(lines) > max_lines:
        print(f"      {DIM}… +{len(lines) - max_lines} more lines{RESET}")


def _tool_label(name: str) -> str:
    label, tag = TOOL_LABELS.get(name, ("", ""))
    if not label:
        if name.startswith("cap__"):
            cap_name = name[5:]
            label = f"Execute {cap_name}"
            tag = "CAP"
        else:
            label = name
            tag = "?"
    return f"{tag} {label}"


def _compact_args(name: str, args: dict[str, Any]) -> str:
    """One-line summary of tool call arguments."""
    if name == "net__http_request":
        method = args.get("method", "?")
        url = args.get("url", "")
        # Strip long URLs to path
        if "127.0.0.1" in url:
            url = url.split("127.0.0.1")[1]  # keep port+path
        body = args.get("body")
        parts = [f"{method} {url}"]
        if body and isinstance(body, dict):
            keys = list(body.keys())
            if len(keys) <= 3:
                parts.append(f"body={{{', '.join(keys)}}}")
            else:
                parts.append(f"body={{{', '.join(keys[:2])}, …}}")
        return "  ".join(parts)
    if name == "wallet__sign_message":
        msg = args.get("message", "")
        return msg[:60] + ("…" if len(msg) > 60 else "")
    if name == "secrets__store":
        return f"{args.get('platform', '?')}/{args.get('key', '?')}"
    if name == "state__set":
        return f"{args.get('namespace', '?')}/{args.get('key', '?')}"
    if name.startswith("cap__"):
        return ", ".join(f"{k}={v}" for k, v in args.items() if not k.startswith("_"))
    # Fallback: compact key=value
    parts = [f"{k}={json.dumps(v, default=str)}" for k, v in list(args.items())[:4]]
    return ", ".join(parts)


def _compact_result(name: str, parsed: Any) -> tuple[str, Any | None]:
    """Return (one-line summary, optional detail payload to show)."""
    if isinstance(parsed, str):
        return (parsed[:120], None)

    if not isinstance(parsed, dict):
        return (str(parsed)[:120], None)

    # HTTP responses — strip headers, show status + body summary
    if "status_code" in parsed:
        status = parsed["status_code"]
        body = parsed.get("body", {})
        color = GREEN if 200 <= status < 300 else (YELLOW if status < 500 else RED)

        if isinstance(body, dict):
            # Show key fields, skip noise
            interesting = {k: v for k, v in body.items()
                           if k not in ("detail",) or status >= 400}
            if status >= 400:
                msg = interesting.get("detail", body)
                if isinstance(msg, list) and msg:
                    msg = msg[0].get("msg", msg)
                return (f"{color}{status}{RESET}  {msg}", None)
            # For success, show a compact key summary — never dump full body
            keys = list(interesting.keys())
            if len(keys) <= 4:
                summary = json.dumps(interesting, default=str, ensure_ascii=False)
                if len(summary) <= 160:
                    return (f"{color}{status}{RESET}  {summary}", None)
            return (f"{color}{status}{RESET}  {{{', '.join(keys[:5])}{'…' if len(keys)>5 else ''}}}", None)
        if isinstance(body, list):
            return (f"{color}{status}{RESET}  [{len(body)} items]", body[:3] if len(body) > 0 else None)
        return (f"{color}{status}{RESET}  {str(body)[:120]}", None)

    # Capability results
    if "capability" in parsed:
        cap = parsed.get("capability", "")
        body = parsed.get("body", parsed)
        status = parsed.get("status_code", "ok")
        payment = parsed.get("headers", {}).get("payment-response")
        paid = f"  {GREEN}x402 paid{RESET}" if payment else ""
        if isinstance(body, dict):
            summary = ", ".join(f"{k}={v}" for k, v in list(body.items())[:4])
            return (f"{GREEN}{status}{RESET}{paid}  {summary}", None)
        if isinstance(body, list):
            return (f"{GREEN}{status}{RESET}{paid}  [{len(body)} items]", body[:2] if body else None)
        return (f"{GREEN}{status}{RESET}{paid}", None)

    # Simple key-value results
    if len(parsed) <= 3:
        summary = ", ".join(f"{k}={v}" for k, v in parsed.items())
        return (summary, None)

    return (f"{{{', '.join(list(parsed.keys())[:4])}, …}}", None)


# ── Server helpers ───────────────────────────────────────────────────


async def start_server(app: Any, port: int) -> asyncio.Task:
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
    from solana.rpc.async_api import AsyncClient
    from solders.pubkey import Pubkey

    async with AsyncClient(rpc_url) as rpc:
        pubkey = Pubkey.from_string(address)
        resp = await rpc.request_airdrop(pubkey, lamports)
        sig = resp.value
        # Surfpool confirms instantly — brief sleep then verify balance
        for _ in range(20):
            await asyncio.sleep(0.3)
            try:
                status = await rpc.get_signature_statuses([sig])
                statuses = status.value
                if statuses and statuses[0] is not None:
                    return
            except Exception:
                pass
        # Fallback: if polling didn't confirm, just wait and continue
        await asyncio.sleep(1)


async def post_tasks(platform_url: str) -> list[dict]:
    task_defs = [
        {
            "title": "Get upcoming public holidays in Japan",
            "description": "Fetch next upcoming public holidays for Japan (JP). Return holiday names and dates.",
            "required_capability": "get_next_holidays",
            "budget": 0.05,
            "input_data": {"country_code": "JP"},
        },
        {
            "title": "Current weather in Tokyo",
            "description": "Get the current temperature, conditions, humidity and wind for Tokyo, Japan.",
            "required_capability": "get_current_weather",
            "budget": 0.05,
            "input_data": {"location": "Tokyo"},
        },
    ]

    created = []
    async with httpx.AsyncClient() as client:
        for t in task_defs:
            resp = await client.post(f"{platform_url}/requester/tasks", json=t)
            resp.raise_for_status()
            created.append(resp.json())
    return created


# ── Main demo ────────────────────────────────────────────────────────


async def run_demo_cycle(*, emit: bool = True) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: Set OPENROUTER_API_KEY env var")
        sys.exit(1)

    RPC_URL = "http://127.0.0.1:8899"
    transcript: list[dict[str, Any]] = []

    if emit:
        _banner("Agent Adapter Runtime — Live Demo")
        _kv("Payment", "x402 on-chain USDC (Surfpool)")
        _kv("LLM", "openai/gpt-oss-120b via OpenRouter")
        _kv("Provider", "WeatherPro — weather + holidays behind x402 paywall")
        _kv("Platform", "TaskNet marketplace")
        print(f"      {DIM}Everything is real — no mocks.{RESET}")

    # ── 1. Create USDC mint on Surfpool ──────────────────────────────
    if emit:
        _section("Infrastructure Setup")

    from simulation.setup_usdc import create_usdc_mint, fund_usdc, get_usdc_balance
    from solders.keypair import Keypair as SoldersKeypair
    from solders.pubkey import Pubkey

    if emit:
        _step(1, "Creating USDC SPL token mint on Surfpool…")
    mint_authority = SoldersKeypair()
    await fund_wallet_sol(RPC_URL, str(mint_authority.pubkey()), 5_000_000_000)
    usdc_mint = await create_usdc_mint(mint_authority)
    if emit:
        _kv("Mint", str(usdc_mint))

    # ── 2. Start servers ─────────────────────────────────────────────
    from simulation.provider_api.paid_server import (
        app as provider_app,
        PROVIDER_ADDRESS,
        configure,
    )
    from simulation.tasknet.server import app as platform_app

    configure(str(usdc_mint))
    await fund_usdc(mint_authority, usdc_mint, Pubkey.from_string(PROVIDER_ADDRESS), 0)

    if emit:
        _step(2, "Starting x402-paid provider API on :8001…")
    provider_task = await start_server(provider_app, 8001)
    if emit:
        _kv("Provider wallet", PROVIDER_ADDRESS)

    if emit:
        _step(3, "Starting TaskNet marketplace on :8002…")
    platform_task = await start_server(platform_app, 8002)

    # ── 3. Boot agent adapter via create_runtime() ─────────────────
    if emit:
        _section("Agent Adapter Boot")

    from agent_adapter.runtime import create_runtime
    from agent_adapter.tools.definitions import build_tool_list
    from agent_adapter.agent.loop import AgentLoop

    platform_url = "http://127.0.0.1:8002"
    provider_url = "http://127.0.0.1:8001"
    wallet_name = f"demo-{os.getpid()}"

    # Generate a Solana keypair and import into OWS so we get:
    # - OWS as the identity/signing layer (Open Wallet Standard)
    # - Raw keypair access for x402 transaction building
    import ows
    from solders.keypair import Keypair as SoldersKeypair
    demo_keypair = SoldersKeypair()
    ed25519_seed_hex = bytes(demo_keypair)[:32].hex()
    try:
        ows.delete_wallet(wallet_name)
    except Exception:
        pass
    ows.import_wallet_private_key(wallet_name, ed25519_seed_hex, ed25519_key=ed25519_seed_hex)

    # Write runtime config YAML
    config_path = Path(tempfile.mkdtemp()) / "agent-adapter.yaml"
    import yaml
    config_path.write_text(yaml.safe_dump({
        "adapter": {
            "name": "verbose-demo",
            "dataDir": str(config_path.parent / "data"),
            "secretsEncryptionKey": "demo-verbose-secret-key",
        },
        "wallet": {
            "provider": "ows",
            "config": {
                "wallet_name": wallet_name,
                "chain": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
                "rpc_url": RPC_URL,
                "ed25519_seed_hex": ed25519_seed_hex,
            },
        },
        "agent": {
            "model": os.environ.get("DEMO_MODEL", "openai/gpt-oss-120b"),
            "base_url": "https://openrouter.ai/api/v1",
        },
        "capabilities": {
            "sources": [{"type": "openapi", "url": f"{provider_url}/openapi.json", "base_url": provider_url}],
            "pricing": {
                "get_current_weather": {"model": "per_call", "amount": 0.01, "enabled": True},
                "get_weather_forecast": {"model": "per_call", "amount": 0.02, "enabled": True},
                "get_next_holidays": {"model": "per_call", "amount": 0.005, "enabled": True},
                "get_country_info": {"model": "per_call", "amount": 0.003, "enabled": True},
            },
        },
        "payments": [
            {"type": "free"},
            {"type": "x402", "config": {"rpc_url": RPC_URL}},
        ],
        "platform": {"url": platform_url},
    }, sort_keys=False))

    if emit:
        _step(4, f"Config written to {config_path}")

    # create_runtime does everything: wallet, DB, capabilities, payments, handlers
    runtime = await create_runtime(config_path)
    address = await runtime.wallet.get_address()

    if emit:
        _kv("Wallet", f"OWS ({wallet_name})")
        _kv("Address", address)
        print(f"      {YELLOW}⚡ Keys managed by Open Wallet Standard (~/.ows/ vault){RESET}")

    # Fund wallets
    if emit:
        _step(5, "Funding wallets with SOL + USDC…")
    await fund_wallet_sol(RPC_URL, address, 5_000_000_000)
    await fund_wallet_sol(RPC_URL, PROVIDER_ADDRESS, 2_000_000_000)
    await fund_usdc(mint_authority, usdc_mint, Pubkey.from_string(address), 100_000_000)
    agent_usdc = await get_usdc_balance(Pubkey.from_string(address), usdc_mint)
    if emit:
        _kv("Balance", f"5.0 SOL / {agent_usdc} USDC")

    # Show what the runtime auto-discovered
    all_caps = runtime.registry.list_all()
    priced = runtime.registry.list_priced()
    if emit:
        _step(6, f"Auto-discovered {len(all_caps)} capabilities from provider OpenAPI spec")
        for cap in all_caps:
            method = cap.execution.get("method", "?")
            path = cap.execution.get("path", "")
            params = cap.execution.get("path_params", []) + cap.execution.get("query_params", [])
            param_str = f"  params=[{', '.join(params)}]" if params else ""
            print(f"      {DIM}{method} {provider_url}{path}{param_str} → {cap.name}{RESET}")
        print(f"      {YELLOW}⚡ Pricing overlay applied — {len(priced)} capabilities priced and enabled{RESET}")
        for c in priced:
            print(f"      {DIM}cap__{c.name}  →  {c.pricing.amount} USDC/call{RESET}")
        _step(7, f"Payment adapters: {', '.join(runtime.payments.list())}")
        if runtime.x402_http_client:
            print(f"      {YELLOW}⚡ x402 HTTP client active — 402 payments handled automatically{RESET}")

    # Convenience aliases
    handlers = runtime.handlers
    job_engine = runtime.job_engine
    db = runtime.db

    # ── 4. Post tasks to marketplace ─────────────────────────────────
    if emit:
        _section("Requester Posts Tasks")

    posted_tasks = await post_tasks(platform_url)
    if emit:
        for t in posted_tasks:
            print(f"  {YELLOW}●{RESET} {t['title']}  {DIM}{t['id']}  budget={t['budget']} USDC{RESET}")

    # ── 5. Wire up agent ─────────────────────────────────────────────
    if emit:
        _section("Agent Loop — Real LLM + Real Tools")

    cap_summary = "\n".join(
        f"- {c.name}: {c.description or 'no desc'} (${c.pricing.amount}/call)\n"
        f"  Endpoint: {c.base_url}{c.execution.get('path', '')}"
        for c in priced
    )

    # Build task details into the prompt so the agent knows exactly what to do
    task_descriptions = "\n".join(
        f'  - {t["id"]}: capability={t["required_capability"]}, input={json.dumps(t["input_data"])}, budget={t["budget"]}'
        for t in posted_tasks
    )

    model = os.environ.get("DEMO_MODEL", "openai/gpt-oss-120b")

    agent = AgentLoop(
        api_key=api_key,
        model=model,
        handlers=handlers,
        system_prompt=f"""You are an autonomous economic agent running inside a wallet-backed runtime.
You MUST use tools to complete EVERY step below. NEVER stop early. NEVER summarize without acting.
You are NOT done until BOTH tasks below are delivered and confirmed.

## MANDATORY EXECUTION PLAN — do NOT skip any step

Step 1: status__whoami — check wallet and capabilities
Step 2: net__http_request GET {platform_url}/docs.md — learn the platform API
Step 3: net__http_request POST {platform_url}/agents/challenge — body: {{"wallet_address": "<your address from step 1>"}}
Step 4: wallet__sign_message — sign the challenge string from step 3
Step 5: net__http_request POST {platform_url}/agents/register — body: {{"wallet_address": "...", "signature": "...", "name": "AutoAgent", "capabilities": ["get_current_weather","get_next_holidays"]}}
Step 6: secrets__store — store the api_key from step 5 (platform="tasknet", key="api_key")
Step 7: state__set — persist registration (namespace="platforms", key="tasknet")
Step 8: net__http_request GET {platform_url}/tasks?status=open — headers: {{"X-API-Key": "<api_key>"}}
Step 9: For EACH task → net__http_request POST {platform_url}/tasks/{{task_id}}/bid — body: {{"price": 0.03}}
Step 10: For EACH task → cap__<capability> with the task's input params
Step 11: For EACH task → net__http_request POST {platform_url}/tasks/{{task_id}}/deliver — body: {{"output": {{<wrap the result in a dict>}}}}

## Known open tasks (execute ALL of them)
{task_descriptions}

## Your capabilities
{cap_summary}

## x402 payment
cap__* tools auto-handle x402 (402 → pay USDC → retry). No manual payment needed.

## CRITICAL RULES
- You are NOT done until ALL tasks show "completed" delivery confirmation
- If you get a 422 on delivery, wrap the output in a dict like {{"holidays": [...]}} or {{"weather": {{...}}}}
- Task IDs always start with "task_" — use the full ID including the prefix
- Always include X-API-Key header when calling TaskNet endpoints (except /agents/challenge)
""",
        max_tool_rounds=30,
        extra_tools=runtime.registry.to_tool_definitions(),
        usage_recorder=lambda u: _record_usage(db, u),
        completion_check=lambda: _check_tasks_done(posted_tasks, emit),
    )

    # ── 6. Run agent with verbose tracing ────────────────────────────
    #
    # Instrument the real AgentLoop.run_once() by wrapping dispatch
    # + LLM calls. Keeps the battle-tested loop, adds clean tracing.

    import time as _time

    tools = build_tool_list(extra_tools=agent._extra_tools)
    if emit:
        _kv("Tools", str(len(tools)))
        _kv("Model", "openai/gpt-oss-120b via OpenRouter")
        _kv("Max rounds", str(agent._max_tool_rounds))

    # Wrap handlers.dispatch for tool call tracing
    _original_dispatch = handlers.dispatch
    _trace_round = [0]
    _tool_count = [0]

    async def _traced_dispatch(name: str, args: dict[str, Any]) -> str:
        _tool_count[0] += 1
        transcript.append({"type": "tool_call", "round": _trace_round[0], "name": name, "args": args})

        label = _tool_label(name)
        compact = _compact_args(name, args)
        if emit:
            print(f"\n    {CYAN}▸ {label}{RESET}  {DIM}{compact}{RESET}")

        # Intercept x402 logs for cap__ calls so we can show the payment flow
        x402_events: list[str] = []
        if emit and name.startswith("cap__"):
            _install_x402_tap(x402_events)

        t0 = _time.monotonic()
        raw = await _original_dispatch(name, args)
        elapsed = _time.monotonic() - t0

        # Print any x402 events that fired during execution
        if emit and x402_events:
            for evt in x402_events:
                print(f"      {YELLOW}⚡ {evt}{RESET}")
            _remove_x402_tap()

        try:
            parsed: Any = json.loads(raw)
        except Exception:
            parsed = raw
        transcript.append({"type": "tool_result", "round": _trace_round[0], "name": name, "result": parsed})

        if emit:
            summary, detail = _compact_result(name, parsed)
            timing = f"{DIM}{elapsed:.1f}s{RESET}" if elapsed > 0.5 else f"{DIM}{elapsed*1000:.0f}ms{RESET}"
            print(f"    {GREEN}◂ {RESET}{summary}  {timing}")
            if detail:
                _json_block("", detail, max_lines=6)

        return raw

    handlers.dispatch = _traced_dispatch

    # Wrap the LLM client to trace decisions
    _original_create = agent._client.chat.completions.create

    async def _traced_create(**kwargs: Any) -> Any:
        _trace_round[0] += 1
        if emit:
            print(f"\n  {BOLD}{WHITE}Round {_trace_round[0]}{RESET}  {DIM}thinking…{RESET}", end="", flush=True)

        t0 = _time.monotonic()
        resp = await _original_create(**kwargs)
        elapsed = _time.monotonic() - t0

        msg = resp.choices[0].message
        transcript.append({"type": "decision", "round": _trace_round[0], "content": msg.content})

        n_tools = len(msg.tool_calls) if msg.tool_calls else 0
        if emit:
            # Overwrite the "thinking…" line
            print(f"\r  {BOLD}{WHITE}Round {_trace_round[0]}{RESET}  {DIM}{elapsed:.1f}s{RESET}  ", end="")
            if n_tools:
                print(f"{DIM}→ {n_tools} tool call{'s' if n_tools > 1 else ''}{RESET}")
            else:
                print(f"{GREEN}done{RESET}")

            if msg.content:
                # Show first 3 lines of agent reasoning
                lines = msg.content.strip().split("\n")
                for line in lines[:3]:
                    print(f"    {DIM}{MAGENTA}{line}{RESET}")
                if len(lines) > 3:
                    print(f"    {DIM}{MAGENTA}…{RESET}")
        return resp

    agent._client.chat.completions.create = _traced_create

    user_message = (
        "Execute the full plan now. Start with status__whoami, then register on TaskNet, "
        "find and bid on all open tasks, execute each capability, and deliver every result. "
        "Do NOT stop until every task is delivered and confirmed. Go."
    )
    demo_start = _time.monotonic()
    final_response = await agent.run_once(user_message)
    demo_elapsed = _time.monotonic() - demo_start

    # ── 7. Post-demo verification ────────────────────────────────────
    if emit:
        _section("Results")
        print(f"  {DIM}Completed in {demo_elapsed:.1f}s across {_trace_round[0]} rounds, {_tool_count[0]} tool calls{RESET}")
        print()

    # Agent response
    if emit and final_response:
        lines = final_response.strip().split("\n")
        for line in lines[:8]:
            print(f"  {line}")
        if len(lines) > 8:
            print(f"  {DIM}…{RESET}")
        print()

    # Tasks
    from simulation.tasknet.server import tasks as platform_tasks
    if emit:
        for t in posted_tasks:
            final = platform_tasks.get(t["id"], {})
            status = final.get("status", "unknown")
            color = GREEN if status == "completed" else (YELLOW if status == "in_progress" else RED)
            print(f"  {color}●{RESET} {t['title'][:45]}  {color}{status}{RESET}  {DIM}{t['id']}{RESET}")

    # Wallet
    final_sol = await runtime.wallet.get_balance()
    final_usdc = await get_usdc_balance(Pubkey.from_string(address), usdc_mint)
    usdc_spent = round(agent_usdc - final_usdc, 6)
    if emit:
        print()
        _kv("Wallet", address[:12] + "…" + address[-6:])
        _kv("SOL", f"{final_sol['sol']}")
        _kv("USDC", f"{final_usdc}  {DIM}(spent {usdc_spent} USDC on x402 payments){RESET}")

    # Jobs
    jobs = []
    if job_engine:
        jobs = await job_engine.list_recent(10)
    if emit and jobs:
        print()
        for j in jobs:
            color = GREEN if j["status"] == "completed" else YELLOW
            print(f"  {color}●{RESET} {j['capability']}  {color}{j['status']}{RESET}  {DIM}{j['id']}{RESET}")

    # Decision log from DB
    cursor = await db.conn.execute("SELECT COUNT(*) FROM decision_log")
    decision_count = (await cursor.fetchone())[0]

    # LLM usage
    cursor = await db.conn.execute(
        "SELECT SUM(prompt_tokens), SUM(completion_tokens), SUM(estimated_cost) FROM llm_usage"
    )
    row = await cursor.fetchone()
    llm_usage = {
        "prompt_tokens": row[0] or 0,
        "completion_tokens": row[1] or 0,
        "estimated_cost_usd": round(row[2] or 0, 4),
    }

    if emit:
        print()
        _kv("Decisions logged", str(decision_count))
        _kv("LLM tokens", f"{llm_usage['prompt_tokens']} in / {llm_usage['completion_tokens']} out")

    if emit:
        _banner("Demo Complete")

    # ── Cleanup ──────────────────────────────────────────────────────
    await runtime.close()
    try:
        ows.delete_wallet(wallet_name)
    except Exception:
        pass
    # Suppress uvicorn CancelledError noise on shutdown
    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
    provider_task.cancel()
    platform_task.cancel()
    await asyncio.sleep(0.1)

    return {
        "final_response": final_response,
        "tool_sequence": [
            item["name"] for item in transcript if item["type"] == "tool_call"
        ],
        "jobs": jobs,
        "llm_usage": llm_usage,
        "transcript": transcript,
    }


async def _check_tasks_done(posted_tasks: list[dict], emit: bool) -> str | None:
    """Completion guard — returns a nudge message if tasks remain unfinished."""
    from simulation.tasknet.server import tasks as live_tasks
    incomplete = [
        t for t in posted_tasks
        if live_tasks.get(t["id"], {}).get("status") not in ("completed", "failed")
    ]
    if not incomplete:
        return None
    names = ", ".join(t["id"] for t in incomplete)
    if emit:
        print(f"\n    {YELLOW}▸ {len(incomplete)} task(s) not delivered yet — continuing…{RESET}")
    return (
        f"You are NOT done. These tasks still need capability execution and delivery: {names}. "
        f"For each: call the matching cap__* tool, then POST /tasks/{{task_id}}/deliver with the output wrapped in a dict. "
        f"Do NOT stop until you get delivery confirmation for every task."
    )


async def _record_usage(db: Any, usage: dict[str, Any]) -> None:
    """Persist LLM usage to the database."""
    try:
        await db.conn.execute(
            "INSERT INTO llm_usage (model, prompt_tokens, completion_tokens, total_tokens, estimated_cost) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                usage.get("model", "openai/gpt-oss-120b"),
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
                usage.get("estimated_cost", 0),
            ),
        )
        await db.conn.commit()
    except Exception:
        pass


def main() -> None:
    asyncio.run(run_demo_cycle(emit=True))


if __name__ == "__main__":
    main()
