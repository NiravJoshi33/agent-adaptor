"""Tool handlers — execute tool calls from the agent and return results."""

from __future__ import annotations

import hashlib
import json
import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from agent_adapter.capabilities.mcp import call_mcp_tool, fetch_mcp_capabilities
from agent_adapter.events import (
    acknowledge_inbound_events,
    list_inbound_events,
    record_inbound_event,
)
from agent_adapter.capabilities.openapi import fetch_and_parse
from agent_adapter.capabilities.registry import CapabilityRegistry
from agent_adapter.drivers.registry import DriverRegistry
from agent_adapter.payments.registry import PaymentRegistry
from agent_adapter.store.database import Database
from agent_adapter.store.secrets import SecretsStore
from agent_adapter.store.state import StateStore
from agent_adapter.jobs.engine import JobEngine
from agent_adapter.extensions.registry import ExtensionRegistry
from agent_adapter_contracts.extensions import RuntimeEvent
from agent_adapter_contracts.payments import (
    PaymentChallenge,
    PaymentReceipt,
    PaymentSession,
)
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
        driver_registry: DriverRegistry | None = None,
        extensions: ExtensionRegistry | None = None,
        payments: PaymentRegistry | None = None,
        plain_http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._wallet = wallet
        self._secrets = secrets
        self._state = state
        self._db = db
        self._job_engine = job_engine
        self._whoami_fn = whoami_fn
        self._x402_http_client = x402_http_client
        self._capability_registry = capability_registry
        self._driver_registry = driver_registry
        self._extensions = extensions
        self._payments = payments
        self._owns_plain_http_client = plain_http_client is None
        self._plain_http_client = plain_http_client or httpx.AsyncClient(
            follow_redirects=True, timeout=30
        )

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
        if handler is None and tool_name.startswith("drv_"):
            handler = self._handle_driver_tool
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
        try:
            caps, content_hash = await fetch_and_parse(
                args["url"], client=self._plain_http_client
            )
            if not caps:
                raise ValueError("No OpenAPI capabilities discovered")
            source_type = "openapi"
        except Exception:
            caps, content_hash = await fetch_mcp_capabilities(
                args["url"], client=self._plain_http_client
            )
            source_type = "mcp"
        return {
            "source_type": source_type,
            "capabilities": [
                {
                    "name": c.name,
                    "description": c.description,
                    "source_ref": c.source_ref,
                    "input_fields": list(c.input_schema.get("properties", {}).keys()),
                }
                for c in caps
            ],
            "count": len(caps),
            "spec_hash": content_hash,
        }

    async def _handle_net__listen_sse(self, args: dict) -> dict:
        url = args["url"]
        headers = {"Accept": "text/event-stream", **(args.get("headers") or {})}
        params = args.get("params") or {}
        max_events = max(int(args.get("max_events", 5) or 5), 1)
        timeout_seconds = float(args.get("timeout_seconds", 10.0) or 10.0)
        channel = args.get("channel") or url
        store_events = bool(args.get("store_events", True))

        events: list[dict[str, Any]] = []
        buffer: dict[str, Any] = {"data_lines": []}
        started_at = datetime.now(timezone.utc).isoformat()

        async def consume() -> None:
            async with self._plain_http_client.stream(
                "GET",
                url,
                headers=headers,
                params=params,
                timeout=timeout_seconds,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line == "":
                        event = self._finalize_sse_event(buffer)
                        if event:
                            if store_events and self._db is not None:
                                stored = await record_inbound_event(
                                    self._db,
                                    source_type="sse",
                                    source=url,
                                    channel=channel,
                                    event_type=event.get("event", "message"),
                                    payload=event,
                                    headers=headers,
                                )
                                event["event_id"] = stored["id"]
                            events.append(event)
                            if len(events) >= max_events:
                                break
                        buffer.clear()
                        buffer["data_lines"] = []
                        continue
                    if line.startswith(":"):
                        continue
                    field, _, value = line.partition(":")
                    value = value[1:] if value.startswith(" ") else value
                    if field == "data":
                        buffer.setdefault("data_lines", []).append(value)
                    else:
                        buffer[field] = value
                trailing = self._finalize_sse_event(buffer)
                if trailing and len(events) < max_events:
                    if store_events and self._db is not None:
                        stored = await record_inbound_event(
                            self._db,
                            source_type="sse",
                            source=url,
                            channel=channel,
                            event_type=trailing.get("event", "message"),
                            payload=trailing,
                            headers=headers,
                        )
                        trailing["event_id"] = stored["id"]
                    events.append(trailing)

        try:
            await asyncio.wait_for(consume(), timeout=timeout_seconds + 1)
            completion_reason = "stream_exhausted" if len(events) < max_events else "max_events"
        except asyncio.TimeoutError:
            completion_reason = "timeout"

        return {
            "url": url,
            "channel": channel,
            "events": events[:max_events],
            "count": len(events[:max_events]),
            "completion_reason": completion_reason,
            "started_at": started_at,
        }

    async def _handle_net__heartbeat(self, args: dict) -> dict:
        sent_at = datetime.now(timezone.utc).isoformat()
        response = await self._request_http(
            args.get("method", "POST"),
            args["url"],
            headers=args.get("headers"),
            params=args.get("params"),
            body=args.get("body"),
        )
        state_key = args.get("key") or args["url"]
        heartbeat_state = {
            "url": args["url"],
            "method": args.get("method", "POST").upper(),
            "status_code": response["status_code"],
            "sent_at": sent_at,
            "response_body": response.get("body"),
        }
        await self._state.set(args.get("namespace", "heartbeats"), state_key, heartbeat_state)
        return heartbeat_state

    async def _handle_net__webhook_receive(self, args: dict) -> dict:
        if self._db is None:
            raise ValueError("Webhook queue requires database access")
        events = await list_inbound_events(
            self._db,
            source_type=args.get("source_type") or None,
            channel=args.get("channel") or None,
            limit=int(args.get("limit", 20) or 20),
            pending_only=bool(args.get("pending_only", True)),
        )
        if args.get("acknowledge", True):
            await acknowledge_inbound_events(
                self._db,
                [int(event["id"]) for event in events if event.get("id") is not None],
            )
            for event in events:
                event["delivered_at"] = datetime.now(timezone.utc).isoformat()
        return {"events": events, "count": len(events)}

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
                if self._extensions:
                    await self._extensions.emit(
                        RuntimeEvent.ON_PLATFORM_REGISTERED,
                        {
                            "base_url": args["key"],
                            "platform_name": data.get("name", args["key"]),
                            "agent_id": data.get("agent_id", ""),
                            "metadata": data,
                        },
                    )
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

    # ── x402 payment tools ────────────────────────────────────────────

    async def _handle_pay_x402__check_requirements(self, args: dict) -> dict:
        response = await self._plain_http_client.request(
            args["method"].upper(),
            args["url"],
            **self._request_kwargs(
                headers=args.get("headers"),
                params=args.get("params"),
                body=args.get("body"),
            ),
        )
        result = self._response_to_result(response)
        if response.status_code != 402:
            result["requires_payment"] = False
            return result

        from payment_x402.plugin import parse_402_requirements

        result["requires_payment"] = True
        result["requirements"] = parse_402_requirements(dict(response.headers))
        return result

    async def _handle_pay_x402__execute(self, args: dict) -> dict:
        method = args["method"].upper()
        url = args["url"]
        kwargs = self._request_kwargs(
            headers=args.get("headers"),
            params=args.get("params"),
            body=args.get("body"),
        )
        initial = await self._plain_http_client.request(method, url, **kwargs)
        if initial.status_code != 402:
            result = self._response_to_result(initial)
            result["payment"] = None
            return result

        if self._payments is None:
            raise ValueError("No payment registry configured")

        from payment_x402.plugin import parse_402_requirements

        requirements = parse_402_requirements(dict(initial.headers))
        challenge = PaymentChallenge(
            type="x402",
            headers=dict(initial.headers),
            amount=float(requirements.get("maxAmountRequired", 0) or 0) / 1_000_000,
            extra={
                "requirements": requirements,
                "resource": url,
                "http_method": method,
            },
        )
        adapter = self._payments.resolve(challenge)
        receipt = await adapter.execute(challenge, self._wallet)
        payment_header = str(receipt.extra.get("payment_header", ""))
        if not payment_header:
            raise ValueError("x402 adapter did not return a payment_header")

        retry_headers = dict(kwargs.get("headers") or {})
        retry_headers["PAYMENT-SIGNATURE"] = payment_header
        retried = await self._plain_http_client.request(
            method,
            url,
            **{**kwargs, "headers": retry_headers},
        )
        result = self._response_to_result(retried)
        result["payment"] = {
            "protocol": receipt.protocol,
            "amount": receipt.amount,
            "currency": receipt.currency,
            "network": receipt.extra.get("network", ""),
        }
        return result

    # ── MPP payment tools ─────────────────────────────────────────────

    async def _handle_pay_mpp__open_session(self, args: dict) -> dict:
        if self._payments is None:
            raise ValueError("No payment registry configured")
        extra = dict(args.get("extra") or {})
        if args.get("challenge") is not None:
            extra["challenge"] = args["challenge"]
        if args.get("credential") is not None:
            extra["credential"] = args["credential"]
        challenge = PaymentChallenge(
            type="mpp",
            headers=args.get("headers") or {},
            amount=float(args.get("amount", 0.0) or 0.0),
            session_url=str(args.get("session_url", "") or ""),
            extra=extra,
        )
        adapter = self._payments.resolve(challenge)
        receipt = await adapter.execute(challenge, self._wallet)
        session = PaymentSession(
            job_id=str(args.get("job_id", "") or ""),
            adapter_id=adapter.id,
            challenge=challenge,
            receipt=receipt,
            status=(
                "authorized"
                if receipt.extra.get("authorization_header")
                else "secured"
            ),
        )
        await self._sync_job_payment(
            session.job_id,
            protocol=adapter.id,
            status=session.status,
            amount=receipt.amount,
            currency=receipt.currency,
        )
        return self._serialize_payment_session(session)

    async def _handle_pay_mpp__capture(self, args: dict) -> dict:
        session = self._payment_session_from_dict(args["session"])
        adapter = self._require_payment_adapter(
            session.challenge.type,
            adapter_id=session.adapter_id,
        )
        previous_status = session.status
        await adapter.settle(session)
        if session.status == previous_status:
            session.status = "settled"
        await self._sync_job_payment(
            session.job_id,
            protocol=session.adapter_id,
            status=session.status,
            amount=session.receipt.amount if session.receipt else None,
            currency=session.receipt.currency if session.receipt else None,
        )
        return self._serialize_payment_session(session)

    async def _handle_pay_mpp__refund(self, args: dict) -> dict:
        session = self._payment_session_from_dict(args["session"])
        adapter = self._require_payment_adapter(
            session.challenge.type,
            adapter_id=session.adapter_id,
        )
        await adapter.refund(session, str(args.get("reason", "")))
        session.status = "refunded"
        await self._sync_job_payment(
            session.job_id,
            protocol=session.adapter_id,
            status=session.status,
            amount=session.receipt.amount if session.receipt else None,
            currency=session.receipt.currency if session.receipt else None,
        )
        return self._serialize_payment_session(session)

    # ── Escrow payment tools ───────────────────────────────────────

    async def _handle_pay_escrow__prepare_lock(self, args: dict) -> dict:
        adapter = self._require_payment_adapter("escrow")
        payment = args.get("payment") or {}
        challenge = PaymentChallenge(
            type="escrow",
            amount=float(payment.get("amount", 0.0) or 0.0),
            extra=payment,
        )
        if not hasattr(adapter, "prepare_lock"):
            raise NotImplementedError("Escrow adapter does not support prepare_lock")
        return await adapter.prepare_lock(challenge, self._wallet)

    async def _handle_pay_escrow__sign_and_submit(self, args: dict) -> dict:
        adapter = self._require_payment_adapter("escrow")
        if not hasattr(adapter, "sign_and_submit"):
            raise NotImplementedError("Escrow adapter does not support sign_and_submit")
        result = await adapter.sign_and_submit(
            args["transaction"],
            self._wallet,
            encoding=args.get("encoding", "base64"),
        )
        await self._sync_job_payment(
            str(args.get("job_id", "") or ""),
            protocol=adapter.id,
            status="secured",
            amount=float(args.get("amount", 0.0) or 0.0),
            currency=str(args.get("currency", "USDC") or "USDC"),
        )
        return result

    async def _handle_pay_escrow__check_status(self, args: dict) -> dict:
        adapter = self._require_payment_adapter("escrow")
        if not hasattr(adapter, "check_status"):
            raise NotImplementedError("Escrow adapter does not support check_status")
        return await adapter.check_status(args["signature"])

    async def _handle_capability_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        capability_name = tool_name.removeprefix("cap__")
        if self._capability_registry is None:
            raise ValueError("No capability registry configured")

        capability = self._capability_registry.get(capability_name)
        if capability is None:
            raise ValueError(f"Unknown capability: {capability_name}")
        drift_status = getattr(capability, "drift_status", "unchanged")
        if drift_status in {"schema_changed", "stale"}:
            raise ValueError(
                f"Capability is blocked pending provider review: {capability_name}"
            )
        if not capability.enabled or capability.pricing is None:
            raise ValueError(f"Capability is not enabled and priced: {capability_name}")

        plan = capability.execution
        if plan.get("type") == "mcp":
            return await self._execute_mcp_capability(capability, args)
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
                    )
                else:
                    await self._job_engine.mark_failed(
                        job_id,
                        error=f"HTTP {response['status_code']}",
                    )
            response["capability"] = capability.name
            if job_id:
                response["job_id"] = job_id
            return response
        except Exception as exc:
            if self._job_engine and job_id:
                await self._job_engine.mark_failed(job_id, error=str(exc))
            raise

    async def _handle_driver_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        if self._driver_registry is None:
            raise ValueError("No driver registry configured")
        return await self._driver_registry.execute(tool_name, args)

    async def _execute_mcp_capability(
        self, capability: Any, args: dict[str, Any]
    ) -> dict[str, Any]:
        plan = capability.execution
        server_url = plan.get("server_url", "")
        if not server_url:
            raise ValueError("MCP capability is missing a server_url")

        job_id = None
        if self._job_engine:
            job_id = await self._job_engine.create(
                capability=capability.name,
                input_data=args,
                payment_amount=self._estimate_payment_amount(capability, args),
                payment_currency=capability.pricing.currency,
            )
            await self._job_engine.mark_executing(job_id)

        try:
            result = await call_mcp_tool(
                server_url,
                tool_name=plan.get("tool_name", capability.source_ref or capability.name),
                arguments=args,
                headers=plan.get("headers"),
                client=self._plain_http_client,
            )
            if self._job_engine and job_id:
                if result.get("is_error"):
                    await self._job_engine.mark_failed(
                        job_id,
                        error=self._hash_payload(result.get("raw")),
                    )
                else:
                    await self._job_engine.mark_completed(
                        job_id,
                        output_hash=self._hash_payload(result.get("raw")),
                    )
            result["capability"] = capability.name
            if job_id:
                result["job_id"] = job_id
            return result
        except Exception as exc:
            if self._job_engine and job_id:
                await self._job_engine.mark_failed(job_id, error=str(exc))
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
        kwargs = self._request_kwargs(headers=headers, params=params, body=body)
        resp = await self._http_client.request(method.upper(), url, **kwargs)
        payment_result: dict[str, Any] | None = None
        if self._payments and resp.status_code == 402:
            payment_result, resp = await self._attempt_payment_retry(
                method.upper(),
                url,
                resp,
                kwargs=kwargs,
            )
        result = self._response_to_result(resp)
        if payment_result:
            result["payment"] = payment_result
        return result

    async def _attempt_payment_retry(
        self,
        method: str,
        url: str,
        response: Any,
        *,
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, Any]:
        auth_header = response.headers.get("WWW-Authenticate") or response.headers.get(
            "www-authenticate"
        )
        if not auth_header or not auth_header.lower().startswith("payment "):
            return None, response

        challenge = PaymentChallenge(
            type="mpp",
            headers=dict(response.headers),
            amount=0.0,
            extra={
                "resource": url,
                "http_method": method,
            },
        )
        try:
            adapter = self._payments.resolve(challenge)
            receipt = await adapter.execute(challenge, self._wallet)
        except Exception:
            return None, response

        authorization_header = receipt.extra.get("authorization_header")
        if not authorization_header:
            return None, response

        retry_headers = dict(kwargs.get("headers") or {})
        retry_headers["Authorization"] = str(authorization_header)
        retry_kwargs = dict(kwargs)
        retry_kwargs["headers"] = retry_headers
        retried = await self._plain_http_client.request(method, url, **retry_kwargs)
        payment_result: dict[str, Any] = {
            "protocol": receipt.protocol,
            "amount": receipt.amount,
            "currency": receipt.currency,
            "retry_authorized": True,
            "challenge_id": receipt.extra.get("challenge_id", ""),
        }
        payment_receipt = retried.headers.get("Payment-Receipt") or retried.headers.get(
            "payment-receipt"
        )
        if payment_receipt:
            payment_result["payment_receipt"] = payment_receipt
        for key, value in receipt.extra.items():
            if key == "authorization_header":
                continue
            payment_result[key] = value
        return payment_result, retried

    def _build_capability_url(self, base_url: str, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not base_url:
            raise ValueError("Capability is missing a base_url")
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    def _request_kwargs(
        self,
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
        return kwargs

    def _response_to_result(self, response: Any) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }
        try:
            result["body"] = response.json()
        except Exception:
            result["body"] = response.text[:4000]
        return result

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

    def _require_payment_adapter(
        self, challenge_type: str, *, adapter_id: str = ""
    ) -> Any:
        if self._payments is None:
            raise ValueError("No payment registry configured")
        if adapter_id:
            return self._payments.resolve_by_id(adapter_id)
        return self._payments.resolve(PaymentChallenge(type=challenge_type))

    async def _sync_job_payment(
        self,
        job_id: str,
        *,
        protocol: str | None = None,
        status: str | None = None,
        amount: float | None = None,
        currency: str | None = None,
    ) -> None:
        if not job_id or self._job_engine is None:
            return
        await self._job_engine.update_payment(
            job_id,
            protocol=protocol,
            status=status,
            amount=amount,
            currency=currency,
        )

    def _serialize_payment_challenge(
        self, challenge: PaymentChallenge
    ) -> dict[str, Any]:
        return {
            "type": challenge.type,
            "headers": dict(challenge.headers),
            "platform": challenge.platform,
            "task_id": challenge.task_id,
            "amount": challenge.amount,
            "session_url": challenge.session_url,
            "extra": dict(challenge.extra),
        }

    def _serialize_payment_receipt(self, receipt: PaymentReceipt | None) -> dict[str, Any] | None:
        if receipt is None:
            return None
        return {
            "protocol": receipt.protocol,
            "amount": receipt.amount,
            "currency": receipt.currency,
            "tx_signature": receipt.tx_signature,
            "extra": dict(receipt.extra),
        }

    def _serialize_payment_session(self, session: PaymentSession) -> dict[str, Any]:
        return {
            "job_id": session.job_id,
            "adapter_id": session.adapter_id,
            "status": session.status,
            "challenge": self._serialize_payment_challenge(session.challenge),
            "receipt": self._serialize_payment_receipt(session.receipt),
        }

    def _payment_session_from_dict(self, payload: dict[str, Any]) -> PaymentSession:
        challenge_payload = payload.get("challenge") or {}
        receipt_payload = payload.get("receipt")
        return PaymentSession(
            job_id=str(payload.get("job_id", "") or ""),
            adapter_id=str(payload.get("adapter_id", "") or ""),
            status=str(payload.get("status", "pending") or "pending"),
            challenge=PaymentChallenge(
                type=str(challenge_payload.get("type", "mpp") or "mpp"),
                headers=dict(challenge_payload.get("headers") or {}),
                platform=str(challenge_payload.get("platform", "") or ""),
                task_id=str(challenge_payload.get("task_id", "") or ""),
                amount=float(challenge_payload.get("amount", 0.0) or 0.0),
                session_url=str(challenge_payload.get("session_url", "") or ""),
                extra=dict(challenge_payload.get("extra") or {}),
            ),
            receipt=(
                None
                if receipt_payload is None
                else PaymentReceipt(
                    protocol=str(receipt_payload.get("protocol", "mpp") or "mpp"),
                    amount=float(receipt_payload.get("amount", 0.0) or 0.0),
                    currency=str(receipt_payload.get("currency", "USDC") or "USDC"),
                    tx_signature=str(receipt_payload.get("tx_signature", "") or ""),
                    extra=dict(receipt_payload.get("extra") or {}),
                )
            ),
        )

    async def close(self) -> None:
        if self._owns_plain_http_client:
            await self._plain_http_client.aclose()
        if self._x402_http_client and hasattr(self._x402_http_client, "aclose"):
            await self._x402_http_client.aclose()

    def _finalize_sse_event(self, buffer: dict[str, Any]) -> dict[str, Any] | None:
        if not buffer or not buffer.get("data_lines") and not any(
            key in buffer for key in ("event", "id", "retry")
        ):
            return None
        data = "\n".join(buffer.get("data_lines", []))
        payload: Any = data
        if data:
            try:
                payload = json.loads(data)
            except Exception:
                payload = data
        event: dict[str, Any] = {
            "event": buffer.get("event", "message"),
            "data": payload,
        }
        if "id" in buffer:
            event["id"] = buffer["id"]
        if "retry" in buffer:
            event["retry"] = buffer["retry"]
        return event
