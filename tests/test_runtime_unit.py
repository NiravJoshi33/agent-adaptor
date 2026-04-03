"""Atomic tests for runtime behavior and dynamic capability execution."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import base64
import httpx
from unittest.mock import AsyncMock, patch

from agent_adapter.agent.loop import AgentLoop
from agent_adapter.capabilities.mcp import MCP_PROTOCOL_VERSION, fetch_mcp_capabilities
from agent_adapter.capabilities.openapi import parse_openapi_spec
from agent_adapter.capabilities.registry import CapabilityRegistry
from agent_adapter.drivers import DriverRegistry
from agent_adapter.payments import load_payment_registry
from agent_adapter.plugins.discovery import list_all_plugins
from agent_adapter.store.database import Database
from agent_adapter.store.encryption import WalletDerivedSecretsBackend
from agent_adapter.store.secrets import SecretsStore
from agent_adapter.store.state import StateStore
from agent_adapter.jobs.engine import JobEngine
from agent_adapter.tools.definitions import build_tool_list
from agent_adapter.tools.handlers import ToolHandlers
from agent_adapter_contracts.extensions import RuntimeEvent
from agent_adapter_contracts.payments import PaymentChallenge, PaymentReceipt, PaymentSession
from agent_adapter_contracts.types import Capability, PricingConfig, ToolDefinition
from payment_escrow import EscrowAdapter
from payment_mpp_stripe import (
    MPPStripeAdapter,
    STRIPE_MPP_API_VERSION,
    build_payment_receipt_header,
    parse_payment_authorization_header,
    parse_payment_challenge_header,
)
from webhook_notifier import WebhookNotifierExtension
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import to_bytes_versioned
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction


class DummyWallet:
    def __init__(self) -> None:
        self.signed_messages: list[bytes] = []

    async def get_address(self) -> str:
        return "dummy-wallet"

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        return {"sol": 1.0, "usdc": 5.0}

    async def sign_message(self, msg: bytes) -> bytes:
        self.signed_messages.append(msg)
        return b"\xaa" * 64

    async def sign_transaction(self, tx: bytes) -> bytes:
        return tx + b"-signed"


class SigningWallet:
    def __init__(self) -> None:
        self.keypair = Keypair()

    async def get_address(self) -> str:
        return str(self.keypair.pubkey())

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        return {"sol": 0.0, "usdc": 0.0}

    async def sign_message(self, msg: bytes) -> bytes:
        return bytes(self.keypair.sign_message(msg))

    async def sign_transaction(self, tx: bytes) -> bytes:
        versioned = VersionedTransaction.from_bytes(tx)
        message_bytes = to_bytes_versioned(versioned.message)
        signatures = list(versioned.signatures)
        for idx, key in enumerate(
            list(versioned.message.account_keys)[
                : versioned.message.header.num_required_signatures
            ]
        ):
            if key == self.keypair.pubkey():
                signatures[idx] = self.keypair.sign_message(message_bytes)
        return bytes(VersionedTransaction.populate(versioned.message, signatures))


class FakeHttpResponse:
    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self._body = body

    def json(self) -> object:
        return self._body


class FakeHttpClient:
    def __init__(self, status_code: int = 200, body: object | None = None) -> None:
        self.status_code = status_code
        self.body = body if body is not None else {"ok": True}
        self.calls: list[tuple[str, str, dict]] = []

    async def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeHttpResponse(self.status_code, self.body)

    async def aclose(self) -> None:
        pass


class FakeRpcResponse:
    def __init__(self, value: object) -> None:
        self.value = value


class FakeSignatureStatus:
    def __init__(
        self,
        *,
        confirmation_status: str = "confirmed",
        confirmations: int | None = None,
        slot: int = 99,
        err: object = None,
    ) -> None:
        self.confirmation_status = confirmation_status
        self.confirmations = confirmations
        self.slot = slot
        self.err = err


class FakeRpcClient:
    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self.sent_transactions: list[bytes] = []
        self.confirmed: list[str] = []
        self.statuses: dict[str, FakeSignatureStatus] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_latest_blockhash(self):
        return FakeRpcResponse(type("V", (), {"blockhash": Hash.default()})())

    async def send_raw_transaction(self, raw_tx: bytes, opts=None):
        self.sent_transactions.append(raw_tx)
        signature = str(VersionedTransaction.from_bytes(raw_tx).signatures[0])
        self.statuses[signature] = FakeSignatureStatus()
        return FakeRpcResponse(signature)

    async def confirm_transaction(self, signature: str):
        self.confirmed.append(str(signature))
        return FakeRpcResponse(True)

    async def get_signature_statuses(self, signatures, search_transaction_history: bool = True):
        values = [self.statuses.get(str(sig)) for sig in signatures]
        return FakeRpcResponse(values)


class FakeRpcFactory:
    def __init__(self) -> None:
        self.client = FakeRpcClient("fake-rpc")

    def __call__(self, rpc_url: str) -> FakeRpcClient:
        self.client.rpc_url = rpc_url
        return self.client


class FakeStripeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "stripe error",
                request=httpx.Request("POST", "https://api.stripe.com"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict[str, object]:
        return dict(self._payload)


class FakeStripeClient:
    def __init__(self, responses: list[FakeStripeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._responses.pop(0)

    async def aclose(self) -> None:
        return None


class FakeAgentMessage:
    def __init__(self, *, content: str, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {"role": "assistant", "content": self.content}
        if not exclude_none or self.tool_calls is not None:
            payload["tool_calls"] = self.tool_calls
        return payload


class FakeAgentChoice:
    def __init__(self, message: FakeAgentMessage) -> None:
        self.message = message


class FakeAgentResponse:
    def __init__(self, *, content: str, usage: dict[str, int]) -> None:
        self.choices = [FakeAgentChoice(FakeAgentMessage(content=content))]
        self.usage = usage


class FakeCompletions:
    def __init__(self, response: FakeAgentResponse) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeChat:
    def __init__(self, response: FakeAgentResponse) -> None:
        self.completions = FakeCompletions(response)


class FakeOpenAIClient:
    def __init__(self, response: FakeAgentResponse) -> None:
        self.chat = FakeChat(response)


class FakeSSEStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


class FakeEntryPoint:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


class FakeEntryPoints:
    def __init__(self, mapping: dict[str, list[FakeEntryPoint]]) -> None:
        self._mapping = mapping

    def select(self, *, group: str):
        return list(self._mapping.get(group, []))


class DummyExtension:
    def __init__(self, name: str = "ext") -> None:
        self.name = name
        self.initialized_with = None

    async def initialize(self, runtime) -> None:
        self.initialized_with = runtime


class DummyDriver:
    def __init__(self) -> None:
        self.initialized_with = None

    @property
    def name(self) -> str:
        return "dummy-driver"

    @property
    def namespace(self) -> str:
        return "drv_dummy"

    @property
    def tools(self):
        return [
            ToolDefinition(
                name="drv_dummy__register",
                description="Register with a dummy driver",
                input_schema={
                    "type": "object",
                    "properties": {"platform_url": {"type": "string"}},
                    "required": ["platform_url"],
                },
            )
        ]

    async def initialize(self, runtime) -> None:
        self.initialized_with = runtime

    async def shutdown(self) -> None:
        return None

    async def execute(self, tool_name: str, args: dict[str, object]) -> dict[str, object]:
        return {"tool": tool_name, "args": args, "driver": self.name}


class DummyRuntime:
    def __init__(self) -> None:
        self.config = {"adapter": {"name": "unit-runtime"}}


class OpenAPIParsingTests(unittest.TestCase):
    def test_parse_openapi_merges_path_parameters_and_execution_plan(self) -> None:
        spec = """
openapi: 3.0.0
servers:
  - url: https://api.example.com
paths:
  /reports/{report_id}:
    parameters:
      - name: report_id
        in: path
        required: true
        schema:
          type: string
    post:
      operationId: create_report
      parameters:
        - name: include_meta
          in: query
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                topic:
                  type: string
              required: [topic]
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
"""
        [cap] = parse_openapi_spec(spec)

        self.assertEqual(cap.name, "create_report")
        self.assertEqual(cap.input_schema["required"], ["report_id", "topic"])
        self.assertIn("report_id", cap.input_schema["properties"])
        self.assertIn("include_meta", cap.input_schema["properties"])
        self.assertEqual(cap.execution["method"], "POST")
        self.assertEqual(cap.execution["path"], "/reports/{report_id}")
        self.assertEqual(cap.execution["path_params"], ["report_id"])
        self.assertEqual(cap.execution["query_params"], ["include_meta"])
        self.assertTrue(cap.execution["body_required"])


class MCPCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_mcp_capabilities_initializes_and_paginates(self) -> None:
        calls: list[tuple[str, dict, dict[str, str]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(405, text="Method Not Allowed")
            payload = json.loads(request.content.decode())
            calls.append((payload["method"], payload.get("params", {}), dict(request.headers)))
            if payload["method"] == "initialize":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {"protocolVersion": MCP_PROTOCOL_VERSION},
                    },
                )
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202, json={})
            if payload["method"] == "tools/list" and not payload.get("params"):
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "tools": [
                                {
                                    "name": "get_report",
                                    "description": "Fetch a report",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"report_id": {"type": "string"}},
                                        "required": ["report_id"],
                                    },
                                }
                            ],
                            "nextCursor": "page-2",
                        },
                    },
                )
            if payload["method"] == "tools/list":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "tools": [
                                {
                                    "name": "create_export",
                                    "description": "Create export",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"format": {"type": "string"}},
                                    },
                                }
                            ]
                        },
                    },
                )
            raise AssertionError(f"Unexpected MCP method: {payload['method']}")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)

        capabilities, content_hash = await fetch_mcp_capabilities(
            "http://mcp.test",
            headers={"Authorization": "Bearer token"},
            client=client,
        )

        self.assertEqual([cap.name for cap in capabilities], ["get_report", "create_export"])
        self.assertTrue(content_hash)
        self.assertEqual(
            [method for method, _, _ in calls],
            ["initialize", "notifications/initialized", "tools/list", "tools/list"],
        )
        self.assertEqual(
            calls[2][2].get("mcp-protocol-version")
            or calls[2][2].get("MCP-Protocol-Version"),
            MCP_PROTOCOL_VERSION,
        )
        self.assertEqual(capabilities[0].source, "mcp")
        self.assertEqual(capabilities[0].execution["tool_name"], "get_report")
        self.assertEqual(
            capabilities[0].input_schema["required"],
            ["report_id"],
        )

    async def test_mcp_capability_dispatch_and_fetch_spec_use_runtime_protocol(self) -> None:
        calls: list[tuple[str, dict, dict[str, str]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode())
            calls.append((payload["method"], payload.get("params", {}), dict(request.headers)))
            if payload["method"] == "initialize":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {"protocolVersion": MCP_PROTOCOL_VERSION},
                    },
                )
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202, json={})
            if payload["method"] == "tools/list":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "tools": [
                                {
                                    "name": "sum_numbers",
                                    "description": "Add numbers",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "values": {
                                                "type": "array",
                                                "items": {"type": "integer"},
                                            }
                                        },
                                        "required": ["values"],
                                    },
                                }
                            ]
                        },
                    },
                )
            if payload["method"] == "tools/call":
                self.assertEqual(payload["params"]["name"], "sum_numbers")
                self.assertEqual(payload["params"]["arguments"], {"values": [1, 2, 3]})
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "content": [{"type": "text", "text": "6"}],
                            "structuredContent": {"sum": 6},
                        },
                    },
                )
            raise AssertionError(f"Unexpected MCP method: {payload['method']}")

        db_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(db_dir.cleanup)
        db = Database(os.path.join(db_dir.name, "mcp.db"))
        await db.connect()
        self.addAsyncCleanup(db.close)

        wallet = DummyWallet()
        secrets = SecretsStore(db, WalletDerivedSecretsBackend(b"\x22" * 64))
        state = StateStore(db)
        job_engine = JobEngine(db)
        registry = CapabilityRegistry()
        registry.register(
            Capability(
                name="sum_numbers",
                source="mcp",
                source_ref="sum_numbers",
                description="Add numbers",
                input_schema={
                    "type": "object",
                    "properties": {
                        "values": {
                            "type": "array",
                            "items": {"type": "integer"},
                        }
                    },
                    "required": ["values"],
                },
                execution={
                    "type": "mcp",
                    "server_url": "http://mcp.test",
                    "tool_name": "sum_numbers",
                    "headers": {"Authorization": "Bearer token"},
                },
                enabled=True,
                pricing=PricingConfig(model="per_call", amount=0.2),
            )
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        handlers = ToolHandlers(
            wallet=wallet,
            secrets=secrets,
            state=state,
            db=db,
            job_engine=job_engine,
            capability_registry=registry,
            plain_http_client=client,
        )
        self.addAsyncCleanup(handlers.close)

        fetched = json.loads(await handlers.dispatch("net__fetch_spec", {"url": "http://mcp.test"}))
        self.assertEqual(fetched["source_type"], "mcp")
        self.assertEqual(fetched["count"], 1)

        result = json.loads(
            await handlers.dispatch("cap__sum_numbers", {"values": [1, 2, 3]})
        )
        self.assertEqual(result["structured_content"], {"sum": 6})
        self.assertFalse(result["is_error"])

        jobs = await job_engine.list_recent(1)
        self.assertEqual(jobs[0]["status"], "completed")
        self.assertEqual(jobs[0]["payment_protocol"], "free")
        self.assertEqual(
            [method for method, _, _ in calls],
            [
                "initialize",
                "notifications/initialized",
                "tools/list",
                "initialize",
                "notifications/initialized",
                "tools/call",
            ],
        )
        self.assertEqual(
            calls[-1][2].get("authorization")
            or calls[-1][2].get("Authorization"),
            "Bearer token",
        )
        self.assertEqual(
            calls[-1][2].get("mcp-protocol-version")
            or calls[-1][2].get("MCP-Protocol-Version"),
            MCP_PROTOCOL_VERSION,
        )


class CapabilityExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.db_dir.name, "unit.db"))
        await self.db.connect()
        self.wallet = DummyWallet()
        self.secrets = SecretsStore(self.db, WalletDerivedSecretsBackend(b"\x11" * 64))
        self.state = StateStore(self.db)
        self.job_engine = JobEngine(self.db)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.db_dir.cleanup()

    async def test_dynamic_capability_tool_creates_completed_job(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            Capability(
                name="get_widget",
                source="openapi",
                source_ref="GET /widgets/{widget_id}",
                description="Get widget",
                input_schema={
                    "type": "object",
                    "properties": {
                        "widget_id": {"type": "string"},
                        "verbose": {"type": "string"},
                    },
                    "required": ["widget_id"],
                },
                execution={
                    "type": "http",
                    "method": "GET",
                    "path": "/widgets/{widget_id}",
                    "path_params": ["widget_id"],
                    "query_params": ["verbose"],
                    "header_params": [],
                    "cookie_params": [],
                    "body_schema": {},
                    "body_required": False,
                },
                base_url="https://api.example.com",
                enabled=True,
                pricing=PricingConfig(model="per_call", amount=0.25),
            )
        )
        http_client = FakeHttpClient(body={"widget": "123"})

        handlers = ToolHandlers(
            wallet=self.wallet,
            secrets=self.secrets,
            state=self.state,
            db=self.db,
            job_engine=self.job_engine,
            capability_registry=registry,
            x402_http_client=http_client,
        )
        self.addAsyncCleanup(handlers.close)

        tools = build_tool_list(extra_tools=registry.to_tool_definitions())
        self.assertTrue(any(t["function"]["name"] == "cap__get_widget" for t in tools))

        raw = await handlers.dispatch(
            "cap__get_widget", {"widget_id": "123", "verbose": "yes"}
        )
        result = json.loads(raw)

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["body"], {"widget": "123"})
        self.assertEqual(result["capability"], "get_widget")
        self.assertEqual(len(http_client.calls), 1)
        method, url, kwargs = http_client.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.example.com/widgets/123")
        self.assertEqual(kwargs["params"], {"verbose": "yes"})

        jobs = await self.job_engine.list_recent(1)
        self.assertEqual(jobs[0]["status"], "completed")
        self.assertEqual(jobs[0]["payment_protocol"], "x402")
        self.assertEqual(jobs[0]["payment_amount"], 0.25)
        self.assertEqual(jobs[0]["payment_status"], "settled")

    async def test_dynamic_driver_tool_dispatches_and_builds_agent_tools(self) -> None:
        registry = DriverRegistry()
        driver = DummyDriver()
        await driver.initialize({"runtime": "stub"})
        registry.register(driver)

        handlers = ToolHandlers(
            wallet=self.wallet,
            secrets=self.secrets,
            state=self.state,
            db=self.db,
            job_engine=self.job_engine,
            driver_registry=registry,
        )
        self.addAsyncCleanup(handlers.close)

        tools = build_tool_list(extra_tools=registry.to_tool_definitions())
        self.assertTrue(
            any(t["function"]["name"] == "drv_dummy__register" for t in tools)
        )

        raw = await handlers.dispatch(
            "drv_dummy__register",
            {"platform_url": "https://tasknet.example"},
        )
        result = json.loads(raw)

        self.assertEqual(result["driver"], "dummy-driver")
        self.assertEqual(result["tool"], "drv_dummy__register")
        self.assertEqual(
            result["args"]["platform_url"], "https://tasknet.example"
        )

    async def test_dynamic_capability_tool_marks_failed_job_for_error_response(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            Capability(
                name="create_widget",
                source="manual",
                source_ref="POST /widgets",
                description="Create widget",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                execution={
                    "type": "http",
                    "method": "POST",
                    "path": "/widgets",
                    "path_params": [],
                    "query_params": [],
                    "header_params": [],
                    "cookie_params": [],
                    "body_schema": {"type": "object"},
                    "body_required": True,
                },
                base_url="https://api.example.com",
                enabled=True,
                pricing=PricingConfig(model="per_call", amount=1.0),
            )
        )
        http_client = FakeHttpClient(status_code=502, body={"error": "upstream failed"})
        handlers = ToolHandlers(
            wallet=self.wallet,
            secrets=self.secrets,
            state=self.state,
            db=self.db,
            job_engine=self.job_engine,
            capability_registry=registry,
            x402_http_client=http_client,
        )
        self.addAsyncCleanup(handlers.close)

        raw = await handlers.dispatch("cap__create_widget", {"name": "bad-widget"})
        result = json.loads(raw)

        self.assertEqual(result["status_code"], 502)
        jobs = await self.job_engine.list_recent(1)
        self.assertEqual(jobs[0]["status"], "failed")
        self.assertEqual(jobs[0]["payment_status"], "pending")

    async def test_wallet_sign_transaction_tool_returns_hex_payload(self) -> None:
        handlers = ToolHandlers(
            wallet=self.wallet,
            secrets=self.secrets,
            state=self.state,
        )
        self.addAsyncCleanup(handlers.close)

        raw = await handlers.dispatch(
            "wallet__sign_transaction", {"transaction": b"abc".hex()}
        )
        result = json.loads(raw)
        self.assertEqual(bytes.fromhex(result["signed_transaction"]), b"abc-signed")

    async def test_operational_tools_handle_sse_and_heartbeat(self) -> None:
        calls: list[tuple[str, str, dict[str, Any]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, str(request.url), dict(request.headers)))
            if request.url.path == "/events":
                stream = FakeSSEStream(
                    [
                        b"id: evt-1\n",
                        b"event: task.created\n",
                        b"data: {\"task_id\":\"t1\"}\n\n",
                        b"data: plain-text\n\n",
                    ]
                )
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    stream=stream,
                )
            if request.url.path == "/heartbeat":
                return httpx.Response(200, json={"ok": True, "presence": "alive"})
            raise AssertionError(f"Unexpected request path: {request.url.path}")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        handlers = ToolHandlers(
            wallet=self.wallet,
            secrets=self.secrets,
            state=self.state,
            db=self.db,
            job_engine=self.job_engine,
            plain_http_client=client,
        )
        self.addAsyncCleanup(handlers.close)

        sse = json.loads(
            await handlers.dispatch(
                "net__listen_sse",
                {
                    "url": "http://events.test/events",
                    "max_events": 2,
                    "channel": "tasknet",
                },
            )
        )
        self.assertEqual(sse["count"], 2)
        self.assertEqual(sse["events"][0]["event"], "task.created")
        self.assertEqual(sse["events"][0]["data"], {"task_id": "t1"})
        self.assertEqual(sse["events"][1]["data"], "plain-text")

        queued = json.loads(
            await handlers.dispatch(
                "net__webhook_receive",
                {"source_type": "sse", "channel": "tasknet", "limit": 10},
            )
        )
        self.assertEqual(queued["count"], 2)
        self.assertEqual(queued["events"][0]["channel"], "tasknet")

        heartbeat = json.loads(
            await handlers.dispatch(
                "net__heartbeat",
                {
                    "url": "http://events.test/heartbeat",
                    "method": "POST",
                    "body": {"agent": "alpha"},
                    "key": "tasknet",
                },
            )
        )
        self.assertEqual(heartbeat["status_code"], 200)
        state_row = await self.state.get("heartbeats", "tasknet")
        self.assertEqual(state_row["response_body"], {"ok": True, "presence": "alive"})
        self.assertEqual(calls[0][0], "GET")
        self.assertEqual(calls[1][0], "POST")

    async def test_http_request_retries_mpp_payment_challenge_with_authorization(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []
        request_payload = {
            "amount": "250",
            "currency": "usd",
            "description": "Metered access",
            "methodDetails": {"networkId": "seller-network"},
        }
        challenge_header = (
            'Payment id="ch_retry_1", realm="seller.example", method="stripe", '
            f'intent="charge", request="{build_payment_receipt_header(request_payload)}", '
            'expires="2099-01-01T00:00:00Z"'
        )
        payment_receipt = build_payment_receipt_header(
            {
                "status": "success",
                "method": "stripe",
                "reference": "pi_paid_123",
                "timestamp": "2099-01-01T00:00:00Z",
            }
        )

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, dict(request.headers)))
            if "authorization" not in request.headers:
                return httpx.Response(
                    402,
                    headers={"WWW-Authenticate": challenge_header},
                    json={"detail": "payment required"},
                )
            credential = parse_payment_authorization_header(
                request.headers["authorization"]
            )
            assert credential["payload"]["spt"] == "spt_client_123"
            return httpx.Response(
                200,
                headers={"Payment-Receipt": payment_receipt},
                json={"ok": True},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        payments = load_payment_registry(
            [{"type": "mpp", "config": {"shared_payment_token": "spt_client_123"}}]
        )
        handlers = ToolHandlers(
            wallet=self.wallet,
            secrets=self.secrets,
            state=self.state,
            db=self.db,
            job_engine=self.job_engine,
            payments=payments,
            plain_http_client=client,
        )
        self.addAsyncCleanup(handlers.close)

        result = json.loads(
            await handlers.dispatch(
                "net__http_request",
                {"method": "GET", "url": "https://seller.example/protected"},
            )
        )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["body"], {"ok": True})
        self.assertEqual(result["payment"]["protocol"], "mpp")
        self.assertEqual(result["payment"]["challenge_id"], "ch_retry_1")
        self.assertEqual(result["payment"]["payment_receipt"], payment_receipt)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("authorization", {k.lower(): v for k, v in calls[0][1].items()})
        self.assertIn("authorization", {k.lower(): v for k, v in calls[1][1].items()})


class LoaderTests(unittest.TestCase):
    def test_load_payment_registry_from_config(self) -> None:
        registry = load_payment_registry(
            [
                {"type": "free"},
                {"type": "escrow"},
                {"type": "mpp", "config": {"secret_key": "sk_test_123"}},
            ]
        )
        self.assertEqual(registry.list(), ["free", "solana_escrow", "stripe_mpp"])
        self.assertEqual(registry.resolve(PaymentChallenge(type="free")).id, "free")
        self.assertEqual(
            registry.resolve(PaymentChallenge(type="escrow")).id, "solana_escrow"
        )
        self.assertEqual(registry.resolve(PaymentChallenge(type="mpp")).id, "stripe_mpp")

    def test_plugin_discovery_lists_entry_point_plugins(self) -> None:
        fake_eps = FakeEntryPoints(
            {
                "agent_adapter.wallets": [
                    FakeEntryPoint("custom-wallet", "tests.dummy_plugins:DummyWalletPlugin")
                ],
                "agent_adapter.payments": [
                    FakeEntryPoint("custom-pay", "payment_free:FreeAdapter")
                ],
                "agent_adapter.extensions": [
                    FakeEntryPoint("custom-ext", "tests.test_runtime_unit:DummyExtension")
                ],
                "agent_adapter.drivers": [
                    FakeEntryPoint(
                        "custom-driver", "tests.dummy_plugins:DummyPlatformDriver"
                    )
                ],
            }
        )
        with patch("agent_adapter.plugins.discovery.entry_points", return_value=fake_eps):
            plugins = list_all_plugins()

        self.assertEqual(plugins["wallet"][0]["id"], "custom-wallet")
        self.assertEqual(plugins["payment"][0]["id"], "custom-pay")
        self.assertEqual(plugins["extension"][0]["id"], "custom-ext")
        self.assertEqual(plugins["driver"][0]["id"], "custom-driver")


class NotificationExtensionTests(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_notifier_sends_structured_payload(self) -> None:
        extension = WebhookNotifierExtension(
            url="https://notify.example/webhook",
            headers={"x-runtime-token": "secret"},
        )
        extension._client.post = AsyncMock(return_value=None)  # type: ignore[method-assign]
        await extension.initialize(DummyRuntime())

        await extension.on_job_failed({"id": "job_123", "status": "failed"})

        extension._client.post.assert_awaited_once()  # type: ignore[attr-defined]
        _, kwargs = extension._client.post.await_args  # type: ignore[attr-defined]
        self.assertEqual(kwargs["json"]["hook"], RuntimeEvent.ON_JOB_FAILED.value)
        self.assertEqual(kwargs["json"]["payload"]["id"], "job_123")
        self.assertEqual(kwargs["json"]["runtime"], "unit-runtime")
        self.assertEqual(kwargs["headers"]["x-runtime-token"], "secret")
        self.assertEqual(extension.hooks[0], RuntimeEvent.ON_JOB_COMPLETE)

        await extension.shutdown()


class MPPStripeAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _build_mpp_fixture(self) -> tuple[dict[str, object], dict[str, object]]:
        request = {
            "amount": "100",
            "currency": "usd",
            "description": "Premium API access",
            "methodDetails": {
                "networkId": "internal",
                "metadata": {"product": "api"},
            },
        }
        challenge = {
            "id": "chlg_123",
            "realm": "api.example.com",
            "method": "stripe",
            "intent": "charge",
            "request": build_payment_receipt_header(request),
            "expires": "2099-01-01T00:00:00Z",
        }
        credential = {
            "challenge": challenge,
            "payload": {
                "spt": "spt_123",
                "externalId": "ext_456",
            },
        }
        return challenge, credential

    async def test_mpp_adapter_executes_stripe_charge_from_headers(self) -> None:
        challenge, credential = self._build_mpp_fixture()
        client = FakeStripeClient(
            [FakeStripeResponse(200, {"id": "pi_123", "status": "succeeded"})]
        )
        adapter = MPPStripeAdapter(secret_key="sk_test_123", http_client=client)

        challenge_header = (
            "Payment "
            f'id="{challenge["id"]}", '
            f'realm="{challenge["realm"]}", '
            'method="stripe", '
            'intent="charge", '
            f'request="{challenge["request"]}", '
            f'expires="{challenge["expires"]}"'
        )
        authorization = "Payment " + build_payment_receipt_header(credential)

        receipt = await adapter.execute(
            PaymentChallenge(
                type="mpp",
                amount=1.0,
                headers={
                    "WWW-Authenticate": challenge_header,
                    "Authorization": authorization,
                },
            ),
            DummyWallet(),
        )

        self.assertEqual(receipt.protocol, "mpp")
        self.assertEqual(receipt.amount, 1.0)
        self.assertEqual(receipt.currency, "USD")
        self.assertEqual(receipt.extra["payment_intent_id"], "pi_123")
        self.assertEqual(receipt.extra["receipt"]["method"], "stripe")
        self.assertEqual(client.calls[0]["url"], "/v1/payment_intents")
        self.assertEqual(
            client.calls[0]["headers"]["Idempotency-Key"], "chlg_123_spt_123"
        )
        self.assertEqual(client.calls[0]["data"]["shared_payment_granted_token"], "spt_123")
        self.assertEqual(client.calls[0]["data"]["metadata[product]"], "api")

    async def test_mpp_adapter_builds_client_authorization_from_shared_token(self) -> None:
        challenge, _ = self._build_mpp_fixture()
        adapter = MPPStripeAdapter(
            shared_payment_token="spt_client_123",
            external_id="ext_789",
        )

        challenge_header = (
            "Payment "
            f'id="{challenge["id"]}", '
            f'realm="{challenge["realm"]}", '
            'method="stripe", '
            'intent="charge", '
            f'request="{challenge["request"]}", '
            f'expires="{challenge["expires"]}"'
        )

        receipt = await adapter.execute(
            PaymentChallenge(
                type="mpp",
                headers={"WWW-Authenticate": challenge_header},
            ),
            DummyWallet(),
        )

        self.assertEqual(receipt.protocol, "mpp")
        self.assertEqual(receipt.currency, "USD")
        self.assertEqual(receipt.amount, 1.0)
        auth_value = str(receipt.extra["authorization_header"])
        self.assertTrue(auth_value.startswith("Payment "))
        credential = parse_payment_authorization_header(auth_value)
        self.assertEqual(credential["payload"]["spt"], "spt_client_123")
        self.assertEqual(credential["payload"]["externalId"], "ext_789")
        self.assertEqual(credential["challenge"]["id"], challenge["id"])

    async def test_mpp_adapter_refund_uses_payment_intent(self) -> None:
        client = FakeStripeClient([FakeStripeResponse(200, {"id": "re_123"})])
        adapter = MPPStripeAdapter(secret_key="sk_test_123", http_client=client)
        session = PaymentSession(
            job_id="job_123",
            adapter_id="stripe_mpp",
            challenge=PaymentChallenge(type="mpp", extra={}),
            receipt=PaymentReceipt(
                protocol="mpp",
                extra={"payment_intent_id": "pi_123"},
            ),
        )

        await adapter.refund(session, "customer asked nicely")

        self.assertEqual(client.calls[0]["url"], "/v1/refunds")
        self.assertEqual(client.calls[0]["data"]["payment_intent"], "pi_123")
        self.assertEqual(
            client.calls[0]["data"]["reason"], "requested_by_customer"
        )

    def test_mpp_header_helpers_parse_and_encode(self) -> None:
        header = (
            'Payment id="ch_1", realm="seller.example", method="stripe", '
            'intent="charge", request="abc123", expires="2099-01-01T00:00:00Z"'
        )
        parsed = parse_payment_challenge_header(header)
        self.assertEqual(parsed["id"], "ch_1")
        self.assertEqual(parsed["method"], "stripe")

        token = build_payment_receipt_header(
            {"challenge": {"id": "ch_1"}, "payload": {"spt": "spt_123"}}
        )
        auth = parse_payment_authorization_header(f"Payment {token}")
        self.assertEqual(auth["payload"]["spt"], "spt_123")
        self.assertTrue(token)


class EscrowAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _transfer_payload(
        self,
        payer: SigningWallet,
        recipient: Keypair,
        *,
        lamports: int = 1234,
        fee_payer: str | None = None,
    ) -> dict[str, object]:
        instruction = transfer(
            TransferParams(
                from_pubkey=payer.keypair.pubkey(),
                to_pubkey=recipient.pubkey(),
                lamports=lamports,
            )
        )
        return {
            "instructions": [
                {
                    "program_id": str(instruction.program_id),
                    "accounts": [
                        {
                            "pubkey": str(meta.pubkey),
                            "is_signer": meta.is_signer,
                            "is_writable": meta.is_writable,
                        }
                        for meta in instruction.accounts
                    ],
                    "data": base64.b64encode(bytes(instruction.data)).decode(),
                    "data_encoding": "base64",
                }
            ],
            "recent_blockhash": str(Hash.default()),
            "fee_payer": fee_payer or str(payer.keypair.pubkey()),
            "amount": 0.000001234,
            "currency": "SOL",
            "reference": "escrow-demo",
            "metadata": {"platform": "tasknet"},
        }

    async def test_prepare_lock_builds_transaction_from_program_payload(self) -> None:
        wallet = SigningWallet()
        recipient = Keypair()
        adapter = EscrowAdapter(rpc_client_factory=FakeRpcFactory())

        prepared = await adapter.prepare_lock(
            PaymentChallenge(
                type="escrow",
                amount=0.000001234,
                extra=self._transfer_payload(wallet, recipient),
            ),
            wallet,
        )

        self.assertEqual(prepared["encoding"], "base64")
        self.assertEqual(prepared["currency"], "SOL")
        self.assertEqual(prepared["required_signers"], [await wallet.get_address()])

        tx_bytes = base64.b64decode(prepared["transaction"])
        versioned = VersionedTransaction.from_bytes(tx_bytes)
        self.assertEqual(
            str(versioned.message.account_keys[0]), await wallet.get_address()
        )

    async def test_prepare_lock_rejects_additional_required_signers(self) -> None:
        wallet = SigningWallet()
        recipient = Keypair()
        adapter = EscrowAdapter(rpc_client_factory=FakeRpcFactory())

        payload = self._transfer_payload(
            wallet,
            recipient,
            fee_payer=str(Keypair().pubkey()),
        )
        with self.assertRaisesRegex(ValueError, "fee payer"):
            await adapter.prepare_lock(
                PaymentChallenge(type="escrow", extra=payload),
                wallet,
            )

    async def test_sign_and_submit_and_check_status_use_rpc_path(self) -> None:
        wallet = SigningWallet()
        recipient = Keypair()
        rpc_factory = FakeRpcFactory()
        adapter = EscrowAdapter(rpc_client_factory=rpc_factory)

        prepared = await adapter.prepare_lock(
            PaymentChallenge(type="escrow", extra=self._transfer_payload(wallet, recipient)),
            wallet,
        )
        submitted = await adapter.sign_and_submit(prepared["transaction"], wallet)
        status = await adapter.check_status(submitted["signature"])

        self.assertTrue(submitted["submitted"])
        self.assertTrue(rpc_factory.client.sent_transactions)
        self.assertIn(submitted["signature"], rpc_factory.client.confirmed)
        self.assertTrue(status["found"])
        self.assertEqual(status["confirmation_status"], "confirmed")


class AgentLoopUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_loop_records_usage(self) -> None:
        recorded: list[dict[str, object]] = []
        
        async def record_usage(usage: dict[str, object]) -> None:
            recorded.append(usage)

        response = FakeAgentResponse(
            content="done",
            usage={"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
        )
        client = FakeOpenAIClient(response)
        loop = AgentLoop(
            api_key="test-key",
            client=client,
            usage_recorder=record_usage,
        )

        result = await loop.run_once("hello")

        self.assertEqual(result, "done")
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["prompt_tokens"], 120)
        self.assertEqual(recorded[0]["completion_tokens"], 45)
        self.assertEqual(recorded[0]["model"], "openai/gpt-oss-120b")


if __name__ == "__main__":
    unittest.main()
