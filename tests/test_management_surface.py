"""Tests for the provider-facing management API and CLI surfaces."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import httpx
import yaml

from agent_adapter import cli
from agent_adapter.management import create_management_app
from agent_adapter.runtime import create_runtime


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
                    "systemPromptFile": str(path.parent / "prompts" / "system.md"),
                    "appendToDefault": True,
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
