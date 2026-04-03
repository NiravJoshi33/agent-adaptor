"""Tool handlers — execute tool calls from the agent and return results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from agent_adapter.capabilities.openapi import fetch_and_parse
from agent_adapter.store.database import Database
from agent_adapter.store.secrets import SecretsStore
from agent_adapter.store.state import StateStore
from agent_adapter.jobs.engine import JobEngine
from agent_adapter_contracts.wallet import WalletPlugin


class ToolHandlers:
    """Dispatches tool calls to their implementations."""

    def __init__(
        self,
        wallet: WalletPlugin,
        secrets: SecretsStore,
        state: StateStore,
        db: Database | None = None,
        job_engine: JobEngine | None = None,
        whoami_fn: Any = None,
        x402_http_client: Any = None,
    ) -> None:
        self._wallet = wallet
        self._secrets = secrets
        self._state = state
        self._db = db
        self._job_engine = job_engine
        self._whoami_fn = whoami_fn
        self._x402_http_client = x402_http_client
        self._plain_http_client = httpx.AsyncClient(follow_redirects=True, timeout=30)

    @property
    def _http_client(self):
        """Use x402 client if available (handles 402 automatically), else plain httpx."""
        return self._x402_http_client or self._plain_http_client

    async def dispatch(self, tool_name: str, args: dict[str, Any]) -> str:
        """Route a tool call to the right handler. Returns JSON string result."""
        handler = getattr(self, f"_handle_{tool_name}", None)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            result = await handler(args)
            # Log decision
            await self._log_decision("tool_call", tool_name, args, result)
            return json.dumps(result) if not isinstance(result, str) else result
        except Exception as e:
            await self._log_decision("tool_error", tool_name, args, {"error": str(e)})
            return json.dumps({"error": str(e)})

    async def _log_decision(
        self, action: str, tool_name: str, args: dict, result: Any
    ) -> None:
        """Persist agent decisions to decision_log table."""
        if self._db is None:
            return
        try:
            detail = json.dumps({
                "tool": tool_name,
                "args_summary": {k: str(v)[:100] for k, v in args.items()},
                "result_summary": str(result)[:200] if result else None,
            })
            await self._db.conn.execute(
                """INSERT INTO decision_log (action, platform, detail, created_at)
                   VALUES (?, '', ?, ?)""",
                (action, detail, datetime.now(timezone.utc).isoformat()),
            )
            await self._db.conn.commit()
        except Exception:
            pass

    # ── Status ─────────────────────────────────────────────────────

    async def _handle_status__whoami(self, args: dict) -> dict:
        if self._whoami_fn:
            return await self._whoami_fn()
        return {"status": "running", "wallet": await self._wallet.get_address()}

    # ── Network ────────────────────────────────────────────────────

    async def _handle_net__http_request(self, args: dict) -> dict:
        method = args["method"].upper()
        url = args["url"]
        headers = args.get("headers", {})
        body = args.get("body")
        params = args.get("params", {})

        kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if body is not None:
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            else:
                kwargs["content"] = str(body)

        resp = await self._http_client.request(method, url, **kwargs)
        result: dict[str, Any] = {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
        }
        try:
            result["body"] = resp.json()
        except Exception:
            result["body"] = resp.text[:4000]
        return result

    async def _handle_net__fetch_spec(self, args: dict) -> dict:
        caps, content_hash = await fetch_and_parse(args["url"])
        return {
            "capabilities": [
                {
                    "name": c.name,
                    "description": c.description,
                    "source_ref": c.source_ref,
                    "input_fields": list(
                        c.input_schema.get("properties", {}).keys()
                    ),
                }
                for c in caps
            ],
            "count": len(caps),
            "spec_hash": content_hash,
        }

    # ── Secrets ────────────────────────────────────────────────────

    async def _handle_secrets__store(self, args: dict) -> dict:
        await self._secrets.store(args["platform"], args["key"], args["value"])
        return {"stored": True, "platform": args["platform"], "key": args["key"]}

    async def _handle_secrets__retrieve(self, args: dict) -> dict:
        value = await self._secrets.retrieve(args["platform"], args["key"])
        if value is None:
            return {"found": False}
        return {"found": True, "value": value}

    async def _handle_secrets__delete(self, args: dict) -> dict:
        deleted = await self._secrets.delete(args["platform"], args["key"])
        return {"deleted": deleted}

    # ── State ──────────────────────────────────────────────────────

    async def _handle_state__set(self, args: dict) -> dict:
        await self._state.set(args["namespace"], args["key"], args["data"])

        # Also persist platform registrations to platforms table
        if args["namespace"] == "platforms" and self._db:
            data = args["data"] if isinstance(args["data"], dict) else {}
            try:
                await self._db.conn.execute(
                    """INSERT INTO platforms (base_url, platform_name, agent_id,
                        registration_status, registered_at, metadata)
                       VALUES (?, ?, ?, 'registered', ?, ?)
                       ON CONFLICT(base_url) DO UPDATE SET
                        agent_id = excluded.agent_id,
                        registration_status = 'registered',
                        last_active_at = excluded.registered_at,
                        metadata = excluded.metadata""",
                    (
                        args["key"],
                        data.get("name", args["key"]),
                        data.get("agent_id", ""),
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(data),
                    ),
                )
                await self._db.conn.commit()
            except Exception:
                pass

        return {"stored": True}

    async def _handle_state__get(self, args: dict) -> dict:
        data = await self._state.get(args["namespace"], args["key"])
        if data is None:
            return {"found": False}
        return {"found": True, "data": data}

    async def _handle_state__list(self, args: dict) -> dict:
        keys = await self._state.list(args["namespace"], args.get("prefix", ""))
        return {"keys": keys}

    # ── Wallet ─────────────────────────────────────────────────────

    async def _handle_wallet__get_address(self, args: dict) -> dict:
        address = await self._wallet.get_address()
        return {"address": address}

    async def _handle_wallet__get_balance(self, args: dict) -> dict:
        balance = await self._wallet.get_balance()
        return balance

    async def _handle_wallet__sign_message(self, args: dict) -> dict:
        sig = await self._wallet.sign_message(args["message"].encode())
        return {"signature": sig.hex()}

    async def close(self) -> None:
        await self._plain_http_client.aclose()
        if self._x402_http_client and hasattr(self._x402_http_client, 'aclose'):
            await self._x402_http_client.aclose()
