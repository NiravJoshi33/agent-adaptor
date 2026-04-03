"""Tests for the provider-facing management API and CLI surfaces."""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml

from agent_adapter import cli
from agent_adapter.management import create_management_app
from agent_adapter.runtime import create_runtime
from agent_adapter.extensions import load_extensions
from agent_adapter.payments import load_payment_registry
from agent_adapter.wallet.loader import load_wallet
from tests.dummy_plugins import DummyWalletPlugin


def _write_openapi_spec(path: Path) -> None:
    path.write_text(
        """
openapi: 3.0.0
servers:
  - url: https://provider.example.com
paths:
  /reports/{report_id}:
    parameters:
      - name: report_id
        in: path
        required: true
        schema:
          type: string
    get:
      operationId: get_report
      summary: Get report
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
    )


def _write_config(path: Path, spec_path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "adapter": {
                    "name": "test-agent",
                    "dataDir": str(path.parent / "data"),
                    "dashboard": {"bind": "127.0.0.1", "port": 9090},
                },
                "wallet": {
                    "provider": "dummy",
                    "config": {
                        "module": "tests.dummy_plugins",
                        "class_name": "DummyWalletPlugin",
                        "address": "cli-wallet",
                        "sol": 3.0,
                        "usdc": 11.5,
                    },
                },
                "agent": {
                    "provider": "openrouter",
                    "model": "openai/gpt-oss-120b",
                    "apiKey": "test-key",
                    "systemPromptFile": str(path.parent / "prompts" / "system.md"),
                    "appendToDefault": True,
                    "costs": {
                        "input_per_1m_tokens": 5.0,
                        "output_per_1m_tokens": 15.0,
                        "currency": "USD",
                    },
                },
                "capabilities": {
                    "source": {"type": "openapi", "url": str(spec_path)},
                    "pricing": {
                        "get_report": {
                            "model": "per_call",
                            "amount": 0.01,
                            "enabled": True,
                        }
                    },
                },
                "payments": [{"type": "free"}],
            },
            sort_keys=False,
        )
    )
    prompt_dir = path.parent / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "system.md").write_text("Keep bids conservative.")


class CLITests(unittest.TestCase):
    def test_init_writes_config_database_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "agent-adapter.yaml"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(
                    [
                        "--config",
                        str(config_path),
                        "init",
                        "--adapter-name",
                        "init-agent",
                        "--data-dir",
                        "./runtime-data",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertTrue(config_path.exists())
            self.assertTrue(Path(payload["database"]).exists())
            self.assertTrue(Path(payload["prompt"]).exists())

    def test_cli_status_and_capability_updates_use_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "openapi.yaml"
            config_path = root / "agent-adapter.yaml"
            _write_openapi_spec(spec_path)
            _write_config(config_path, spec_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(["--config", str(config_path), "status"])
            status = json.loads(stdout.getvalue())
            self.assertEqual(status["wallet"], "cli-wallet")
            self.assertEqual(status["balances"]["usdc"], 11.5)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(
                    [
                        "--config",
                        str(config_path),
                        "capabilities",
                        "price",
                        "get_report",
                        "--amount",
                        "0.05",
                        "--model",
                        "per_call",
                    ]
                )
            priced = json.loads(stdout.getvalue())
            self.assertEqual(priced["pricing"]["amount"], 0.05)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(
                    ["--config", str(config_path), "capabilities", "disable", "get_report"]
                )
            disabled = json.loads(stdout.getvalue())
            self.assertFalse(disabled["enabled"])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(["--config", str(config_path), "capabilities", "list"])
            listed = json.loads(stdout.getvalue())
            self.assertEqual(listed["capabilities"][0]["pricing"]["amount"], 0.05)
            self.assertEqual(listed["capabilities"][0]["status"], "disabled")

    def test_cli_prompt_commands_update_content_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "openapi.yaml"
            config_path = root / "agent-adapter.yaml"
            _write_openapi_spec(spec_path)
            _write_config(config_path, spec_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(["--config", str(config_path), "prompt", "show"])
            prompt_state = json.loads(stdout.getvalue())
            self.assertTrue(prompt_state["append_to_default"])
            self.assertIn("Keep bids conservative.", prompt_state["effective_prompt"])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(["--config", str(config_path), "prompt", "mode", "--replace"])
            prompt_state = json.loads(stdout.getvalue())
            self.assertFalse(prompt_state["append_to_default"])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(
                    [
                        "--config",
                        str(config_path),
                        "prompt",
                        "set",
                        "--content",
                        "Only take premium work.",
                    ]
                )
            prompt_state = json.loads(stdout.getvalue())
            self.assertEqual(prompt_state["custom_prompt"], "Only take premium work.")
            self.assertEqual(prompt_state["effective_prompt"], "Only take premium work.")

            config = yaml.safe_load(config_path.read_text())
            self.assertFalse(config["agent"]["appendToDefault"])

    def test_cli_metrics_commands_report_job_and_llm_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "openapi.yaml"
            config_path = root / "agent-adapter.yaml"
            _write_openapi_spec(spec_path)
            _write_config(config_path, spec_path)

            async def seed_runtime() -> None:
                runtime = await create_runtime(config_path)
                try:
                    job_id = await runtime.job_engine.create(
                        capability="get_report",
                        input_data={"report_id": "m1"},
                        payment_protocol="x402",
                        payment_amount=0.75,
                    )
                    await runtime.job_engine.mark_executing(job_id)
                    await runtime.job_engine.mark_completed(job_id, output_hash="ok")
                    await runtime.record_llm_usage(
                        {
                            "model": "openai/gpt-oss-120b",
                            "prompt_tokens": 1000,
                            "completion_tokens": 500,
                            "total_tokens": 1500,
                        }
                    )
                finally:
                    await runtime.close()

            asyncio.run(seed_runtime())

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(["--config", str(config_path), "metrics", "summary", "--days", "30"])
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["completed_jobs"], 1)
            self.assertEqual(summary["revenue_by_currency"]["USDC"], 0.75)
            self.assertEqual(summary["jobs_by_status"]["completed"], 1)
            self.assertAlmostEqual(summary["llm_usage"]["estimated_cost"], 0.0125)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli.app(["--config", str(config_path), "metrics", "daily", "--days", "7"])
            series = json.loads(stdout.getvalue())["series"]
            self.assertEqual(len(series), 7)
            self.assertTrue(any(point["revenue"] == 0.75 for point in series))

    def test_cli_plugins_list_shows_discovered_entry_points(self) -> None:
        class FakeEntryPoint:
            def __init__(self, name: str, value: str) -> None:
                self.name = name
                self.value = value

        class FakeEntryPoints:
            def __init__(self, mapping):
                self.mapping = mapping

            def select(self, *, group: str):
                return list(self.mapping.get(group, []))

        fake_eps = FakeEntryPoints(
            {
                "agent_adapter.wallets": [
                    FakeEntryPoint("custom-wallet", "tests.dummy_plugins:DummyWalletPlugin")
                ],
                "agent_adapter.payments": [
                    FakeEntryPoint("custom-pay", "payment_free:FreeAdapter")
                ],
                "agent_adapter.extensions": [
                    FakeEntryPoint("custom-ext", "tests.test_management_surface:TestExtension")
                ],
            }
        )

        stdout = io.StringIO()
        with patch("agent_adapter.plugins.discovery.entry_points", return_value=fake_eps):
            with redirect_stdout(stdout):
                cli.app(["plugins", "list"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["wallet"][0]["id"], "custom-wallet")
        self.assertEqual(payload["payment"][0]["id"], "custom-pay")
        self.assertEqual(payload["extension"][0]["id"], "custom-ext")


class TestExtension:
    def __init__(self) -> None:
        self.runtime = None

    async def initialize(self, runtime) -> None:
        self.runtime = runtime


class ManagementAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.spec_path = self.root / "openapi.yaml"
        self.config_path = self.root / "agent-adapter.yaml"
        _write_openapi_spec(self.spec_path)
        _write_config(self.config_path, self.spec_path)
        self.runtime = await create_runtime(self.config_path)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_management_app(self.runtime)),
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.runtime.close()
        self.tmp.cleanup()

    async def test_management_api_exposes_and_updates_runtime_state(self) -> None:
        status = (await self.client.get("/manage/status")).json()
        self.assertEqual(status["wallet"], "cli-wallet")
        self.assertEqual(status["balances"]["sol"], 3.0)

        caps = (await self.client.get("/manage/capabilities")).json()["capabilities"]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["name"], "get_report")
        self.assertEqual(caps[0]["pricing"]["amount"], 0.01)

        updated = (
            await self.client.put(
                "/manage/capabilities/get_report/pricing",
                json={"model": "per_call", "amount": 0.125, "currency": "USDC"},
            )
        ).json()
        self.assertEqual(updated["pricing"]["amount"], 0.125)

        disabled = (
            await self.client.post("/manage/capabilities/get_report/disable")
        ).json()
        self.assertFalse(disabled["enabled"])

        await self.runtime.handlers.dispatch(
            "state__set",
            {
                "namespace": "platforms",
                "key": "tasknet",
                "data": {"name": "TaskNet", "agent_id": "agent-123"},
            },
        )
        job_id = await self.runtime.job_engine.create(
            capability="get_report",
            input_data={"report_id": "r1"},
            payment_protocol="free",
            payment_amount=0.01,
        )
        await self.runtime.job_engine.mark_executing(job_id)
        await self.runtime.job_engine.mark_completed(job_id, output_hash="done")
        await self.runtime.handlers.dispatch("wallet__get_address", {})

        jobs = (await self.client.get("/manage/jobs")).json()["jobs"]
        self.assertEqual(jobs[0]["id"], job_id)
        self.assertEqual(jobs[0]["status"], "completed")

        platforms = (await self.client.get("/manage/platforms")).json()["platforms"]
        self.assertEqual(platforms[0]["agent_id"], "agent-123")

        decisions = (
            await self.client.get("/manage/agent/decisions?limit=5")
        ).json()["decisions"]
        self.assertTrue(decisions)

        paused = (await self.client.post("/manage/agent/pause")).json()
        resumed = (await self.client.post("/manage/agent/resume")).json()
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(resumed["status"], "running")

        await self.runtime.record_llm_usage(
            {
                "model": "openai/gpt-oss-120b",
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
            }
        )
        metrics = (await self.client.get("/manage/metrics?days=30")).json()
        self.assertEqual(metrics["completed_jobs"], 1)
        self.assertEqual(metrics["revenue_by_currency"]["USDC"], 0.01)
        self.assertEqual(metrics["revenue_by_payment_protocol"][0]["payment_protocol"], "free")
        self.assertAlmostEqual(metrics["llm_usage"]["estimated_cost"], 0.0125)

        timeseries = (await self.client.get("/manage/metrics/timeseries?days=7")).json()["series"]
        self.assertEqual(len(timeseries), 7)
        self.assertTrue(any(point["llm_cost"] > 0 for point in timeseries))

    async def test_management_api_updates_prompt_and_rebuilds_agent_loop(self) -> None:
        prompt = (await self.client.get("/manage/agent/prompt")).json()
        self.assertTrue(prompt["append_to_default"])
        self.assertIn("Keep bids conservative.", prompt["effective_prompt"])

        updated = (
            await self.client.put(
                "/manage/agent/prompt",
                json={
                    "custom_prompt": "Only accept high-margin jobs.",
                    "append_to_default": False,
                },
            )
        ).json()
        self.assertFalse(updated["append_to_default"])
        self.assertEqual(updated["effective_prompt"], "Only accept high-margin jobs.")

        agent = await self.runtime.ensure_agent_loop()
        self.assertIsNotNone(agent)
        assert agent is not None
        self.assertEqual(agent.system_prompt, "Only accept high-margin jobs.")

        updated = (
            await self.client.put(
                "/manage/agent/prompt",
                json={
                    "custom_prompt": "Keep inventory risk near zero.",
                    "append_to_default": True,
                },
            )
        ).json()
        self.assertTrue(updated["append_to_default"])
        self.assertIn("## Provider Instructions", updated["effective_prompt"])
        self.assertIn("Keep inventory risk near zero.", updated["effective_prompt"])

        agent = await self.runtime.ensure_agent_loop()
        assert agent is not None
        self.assertIn("Keep inventory risk near zero.", agent.system_prompt)

    async def test_webhook_receiver_persists_events_for_agent_consumption(self) -> None:
        received = (
            await self.client.post(
                "/webhooks/tasknet?event=task.created",
                json={"task_id": "task-42", "price": 1.25},
                headers={"x-event-type": "task.created"},
            )
        ).json()
        self.assertTrue(received["received"])

        events = (await self.client.get("/manage/events?channel=tasknet")).json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "task.created")
        self.assertEqual(events[0]["payload"]["task_id"], "task-42")

        consumed = json.loads(
            await self.runtime.handlers.dispatch(
                "net__webhook_receive",
                {"channel": "tasknet", "source_type": "webhook", "acknowledge": True},
            )
        )
        self.assertEqual(consumed["count"], 1)
        self.assertEqual(consumed["events"][0]["payload"]["price"], 1.25)

        pending = (await self.client.get("/manage/events?channel=tasknet")).json()["events"]
        self.assertEqual(pending, [])

    async def test_dashboard_pages_render_and_capability_refresh_surfaces_drift(self) -> None:
        overview = await self.client.get("/dashboard/")
        self.assertEqual(overview.status_code, 200)
        self.assertIn("Local Provider Console", overview.text)

        capabilities_page = await self.client.get("/dashboard/capabilities")
        self.assertEqual(capabilities_page.status_code, 200)
        self.assertIn("Capability Registry", capabilities_page.text)

        job_id = await self.runtime.job_engine.create(
            capability="get_report",
            input_data={"report_id": "dashboard"},
            payment_protocol="x402",
            payment_amount=0.45,
        )
        await self.runtime.job_engine.mark_executing(job_id)
        await self.runtime.job_engine.mark_completed(job_id, output_hash="dashboard-ok")
        await self.runtime.record_llm_usage(
            {
                "model": "openai/gpt-oss-120b",
                "prompt_tokens": 800,
                "completion_tokens": 200,
                "total_tokens": 1000,
            }
        )

        metrics_page = await self.client.get("/dashboard/metrics")
        self.assertEqual(metrics_page.status_code, 200)
        self.assertIn("Economic Observability", metrics_page.text)
        self.assertIn("Daily Revenue vs Cost", metrics_page.text)
        self.assertIn("&quot;page&quot;: &quot;metrics&quot;", metrics_page.text)

        self.spec_path.write_text(
            """
openapi: 3.0.0
servers:
  - url: https://provider.example.com
paths:
  /reports/{report_id}:
    parameters:
      - name: report_id
        in: path
        required: true
        schema:
          type: integer
    get:
      operationId: get_report
      summary: Get report changed
      responses:
        '200':
          description: ok
  /exports:
    post:
      operationId: create_export
      summary: Create export
      responses:
        '200':
          description: ok
"""
        )

        refreshed = (await self.client.post("/manage/capabilities/refresh")).json()
        by_name = {cap["name"]: cap for cap in refreshed["capabilities"]}
        self.assertEqual(by_name["get_report"]["drift_status"], "schema_changed")
        self.assertIn(by_name["get_report"]["status"], {"schema_changed", "disabled"})
        self.assertEqual(by_name["create_export"]["drift_status"], "new")

        self.spec_path.write_text(
            """
openapi: 3.0.0
servers:
  - url: https://provider.example.com
paths:
  /exports:
    post:
      operationId: create_export
      summary: Create export
      responses:
        '200':
          description: ok
"""
        )
        refreshed = (await self.client.post("/manage/capabilities/refresh")).json()
        by_name = {cap["name"]: cap for cap in refreshed["capabilities"]}
        self.assertEqual(by_name["get_report"]["drift_status"], "stale")
        self.assertEqual(by_name["get_report"]["status"], "stale")

    async def test_loaders_can_resolve_entry_point_plugins(self) -> None:
        class FakeEntryPoint:
            def __init__(self, name: str, value: str) -> None:
                self.name = name
                self.value = value

        class FakeEntryPoints:
            def __init__(self, mapping):
                self.mapping = mapping

            def select(self, *, group: str):
                return list(self.mapping.get(group, []))

        fake_eps = FakeEntryPoints(
            {
                "agent_adapter.wallets": [
                    FakeEntryPoint("dummy-entry", "tests.dummy_plugins:DummyWalletPlugin")
                ],
                "agent_adapter.payments": [
                    FakeEntryPoint("free-entry", "payment_free:FreeAdapter")
                ],
                "agent_adapter.extensions": [
                    FakeEntryPoint("test-ext", "tests.test_management_surface:TestExtension")
                ],
            }
        )

        with patch("agent_adapter.plugins.discovery.entry_points", return_value=fake_eps):
            wallet = await load_wallet(
                "dummy-entry",
                {"address": "entry-wallet", "sol": 2.0, "usdc": 4.5},
            )
            self.assertIsInstance(wallet, DummyWalletPlugin)
            self.assertEqual(await wallet.get_address(), "entry-wallet")

            payments = load_payment_registry([{"type": "free-entry"}])
            self.assertEqual(payments.list(), ["free"])

            extensions = await load_extensions([{"id": "test-ext"}], runtime=self.runtime)
            self.assertEqual(len(extensions._extensions), 1)
            self.assertIsInstance(extensions._extensions[0], TestExtension)
            self.assertIs(extensions._extensions[0].runtime, self.runtime)
