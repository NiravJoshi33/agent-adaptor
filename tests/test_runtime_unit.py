"""Atomic tests for runtime behavior and dynamic capability execution."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from agent_adapter.capabilities.openapi import parse_openapi_spec
from agent_adapter.capabilities.registry import CapabilityRegistry
from agent_adapter.payments import load_payment_registry
from agent_adapter.store.database import Database
from agent_adapter.store.encryption import WalletDerivedSecretsBackend
from agent_adapter.store.secrets import SecretsStore
from agent_adapter.store.state import StateStore
from agent_adapter.jobs.engine import JobEngine
from agent_adapter.tools.definitions import build_tool_list
from agent_adapter.tools.handlers import ToolHandlers
from agent_adapter_contracts.payments import PaymentChallenge
from agent_adapter_contracts.types import Capability, PricingConfig


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


class LoaderTests(unittest.TestCase):
    def test_load_payment_registry_from_config(self) -> None:
        registry = load_payment_registry([{"type": "free"}])
        self.assertEqual(registry.list(), ["free"])
        self.assertEqual(registry.resolve(PaymentChallenge(type="free")).id, "free")


if __name__ == "__main__":
    unittest.main()
