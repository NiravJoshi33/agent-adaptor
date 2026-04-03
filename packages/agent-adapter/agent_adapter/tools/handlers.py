"""Tool handlers — execute tool calls from the agent and return results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from agent_adapter.capabilities.openapi import fetch_and_parse
from agent_adapter.capabilities.registry import CapabilityRegistry
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
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self._wallet = wallet
        self._secrets = secrets
        self._state = state
        self._db = db
        self._job_engine = job_engine
        self._whoami_fn = whoami_fn
        self._x402_http_client = x402_http_client
        self._capability_registry = capability_registry
        self._plain_http_client = httpx.AsyncClient(follow_redirects=True, timeout=30)

    @property
    def _http_client(self):
        """Use x402 client if available (handles 402 automatically), else plain httpx."""
        return self._x402_http_client or self._plain_http_client

    async def dispatch(self, tool_name: str, args: dict[str, Any]) -> str:
        """Route a tool call to the right handler. Returns JSON string result."""
        handler = getattr(self, f"_handle_{tool_name}", None)
        is_dynamic_capability = False
        if handler is None and tool_name.startswith("cap__"):
            handler = self._handle_capability_tool
            is_dynamic_capability = True
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            result = (
                await handler(tool_name, args)
                if is_dynamic_capability
                else await handler(args)
            )
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
        return await self._request_http(
            args["method"],
            args["url"],
            headers=args.get("headers"),
            params=args.get("params"),
            body=args.get("body"),
        )

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

    async def _handle_wallet__sign_transaction(self, args: dict) -> dict:
        tx_bytes = bytes.fromhex(args["transaction"])
        signed = await self._wallet.sign_transaction(tx_bytes)
        return {"signed_transaction": signed.hex()}

    async def _handle_capability_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        capability_name = tool_name.removeprefix("cap__")
        if self._capability_registry is None:
            raise ValueError("No capability registry configured")

        capability = self._capability_registry.get(capability_name)
        if capability is None:
            raise ValueError(f"Unknown capability: {capability_name}")
        if not capability.enabled or capability.pricing is None:
            raise ValueError(f"Capability is not enabled and priced: {capability_name}")

        plan = capability.execution
        if plan.get("type") != "http":
            raise NotImplementedError(
                f"Capability execution is not implemented for source {capability.source}"
            )

        path = plan.get("path", "")
        for name in plan.get("path_params", []):
            if name not in args:
                raise ValueError(f"Missing required path parameter: {name}")
            path = path.replace("{" + name + "}", quote(str(args[name]), safe=""))

        query_params = {
            name: str(args[name])
            for name in plan.get("query_params", [])
            if name in args and args[name] is not None
        }
        headers = {
            name: str(args[name])
            for name in plan.get("header_params", [])
            if name in args and args[name] is not None
        }

        handled_keys = set(plan.get("path_params", []))
        handled_keys.update(plan.get("query_params", []))
        handled_keys.update(plan.get("header_params", []))
        handled_keys.update(plan.get("cookie_params", []))
        remaining = {k: v for k, v in args.items() if k not in handled_keys}

        body = None
        if plan.get("body_schema"):
            body = remaining.get("body") if set(remaining.keys()) == {"body"} else remaining
            if body == {} and plan.get("body_required"):
                raise ValueError("Capability requires a request body")

        url = self._build_capability_url(capability.base_url, path)
        job_id = None
        if self._job_engine:
            job_id = await self._job_engine.create(
                capability=capability.name,
                input_data=args,
                payment_protocol="x402" if self._x402_http_client else "free",
                payment_amount=self._estimate_payment_amount(capability, args),
                payment_currency=capability.pricing.currency,
            )
            await self._job_engine.mark_executing(job_id)

        try:
            response = await self._request_http(
                plan.get("method", "GET"),
                url,
                headers=headers,
                params=query_params,
                body=body,
            )
            if self._job_engine and job_id:
                if 200 <= response["status_code"] < 400:
                    await self._job_engine.mark_completed(
                        job_id,
                        output_hash=self._hash_payload(response.get("body")),
                        payment_status="settled",
                    )
                else:
                    await self._job_engine.mark_failed(
                        job_id,
                        error=f"HTTP {response['status_code']}",
                        payment_status="pending",
                    )
            response["capability"] = capability.name
            if job_id:
                response["job_id"] = job_id
            return response
        except Exception as exc:
            if self._job_engine and job_id:
                await self._job_engine.mark_failed(
                    job_id, error=str(exc), payment_status="pending"
                )
            raise

    async def _request_http(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "headers": headers or {},
            "params": params or {},
        }
        if body is not None:
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            else:
                kwargs["content"] = str(body)

        resp = await self._http_client.request(method.upper(), url, **kwargs)
        result: dict[str, Any] = {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
        }
        try:
            result["body"] = resp.json()
        except Exception:
            result["body"] = resp.text[:4000]
        return result

    def _build_capability_url(self, base_url: str, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not base_url:
            raise ValueError("Capability is missing a base_url")
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    def _estimate_payment_amount(self, capability: Any, args: dict[str, Any]) -> float:
        pricing = capability.pricing
        if pricing is None:
            return 0.0
        if pricing.model == "per_call":
            return pricing.amount
        if pricing.model == "per_item":
            return pricing.amount * max(self._resolve_item_count(args, pricing.item_field), 0)
        if pricing.model == "quoted":
            return pricing.floor
        if pricing.model == "per_token":
            return pricing.amount
        return 0.0

    def _resolve_item_count(self, args: dict[str, Any], item_field: str) -> int:
        node: Any = args
        field = item_field.removeprefix("input.")
        if not field:
            return 0
        for part in field.split("."):
            if part == "length":
                return len(node) if hasattr(node, "__len__") else 0
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = getattr(node, part, None)
            if node is None:
                return 0
        if isinstance(node, list):
            return len(node)
        if isinstance(node, (int, float)):
            return int(node)
        return 1 if node else 0

    def _hash_payload(self, payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    async def close(self) -> None:
        await self._plain_http_client.aclose()
        if self._x402_http_client and hasattr(self._x402_http_client, "aclose"):
            await self._x402_http_client.aclose()
