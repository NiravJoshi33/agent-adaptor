"""Higher-level integration tests that use the production runtime path with Surfpool."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import tempfile
import unittest

import httpx
from agent_adapter.payments import load_payment_registry
from solana.rpc.async_api import AsyncClient as SolanaClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer

from agent_adapter.capabilities.openapi import parse_openapi_spec
from agent_adapter.capabilities.registry import CapabilityRegistry
from agent_adapter.store.database import Database
from agent_adapter.store.encryption import WalletDerivedSecretsBackend
from agent_adapter.store.secrets import SecretsStore
from agent_adapter.store.state import StateStore
from agent_adapter.jobs.engine import JobEngine
from agent_adapter.tools.handlers import ToolHandlers
from agent_adapter_contracts.types import PricingConfig
from payment_x402.http_client import X402HttpClient
from simulation.provider_api import paid_server
from simulation.setup_usdc import create_usdc_mint, fund_usdc, get_usdc_balance
from tests.helpers import SURFPOOL_RPC, airdrop_and_confirm, wait_for_surfpool
from wallet_solana_raw import SolanaRawWallet


def _serialize_instruction_payload(instruction, *, fee_payer: str, amount: float, currency: str) -> dict[str, object]:
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
        "fee_payer": fee_payer,
        "amount": amount,
        "currency": currency,
        "reference": "platform-escrow-lock",
        "metadata": {"payment_protocol": "escrow"},
    }

@contextlib.contextmanager
def override_provider_routes():
    """Replace paid endpoint implementations while keeping middleware/x402 intact."""
    originals: list[tuple[object, object, object]] = []

    async def fake_holidays(country_code: str) -> list[dict]:
        return [
            {
                "date": "2026-05-03",
                "localName": "Constitution Memorial Day",
                "name": "Constitution Memorial Day",
                "countryCode": country_code,
            }
        ]

    async def fake_weather(location: str) -> dict:
        return {
            "location": location,
            "temperature_c": 20.0,
            "condition": "Sunny",
            "humidity": "45",
            "wind": "10 km/h NW",
        }

    replacements = {
        "/holidays/next/{country_code}": fake_holidays,
        "/weather/current": fake_weather,
    }

    try:
        for route in paid_server.app.router.routes:
            endpoint = replacements.get(getattr(route, "path", ""))
            if endpoint is None or not hasattr(route, "dependant"):
                continue
            originals.append((route, route.endpoint, route.dependant.call))
            route.endpoint = endpoint
            route.dependant.call = endpoint
        yield
    finally:
        for route, endpoint, dependant_call in originals:
            route.endpoint = endpoint
            route.dependant.call = dependant_call


class SurfpoolX402FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.rpc = SolanaClient(SURFPOOL_RPC)
        try:
            await wait_for_surfpool(self.rpc)
        except RuntimeError as exc:
            await self.rpc.close()
            raise unittest.SkipTest(str(exc)) from exc

        self.db_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.db_dir.name, "integration.db"))
        await self.db.connect()

        self.agent_wallet = SolanaRawWallet.generate(
            rpc_url=SURFPOOL_RPC, cluster="devnet"
        )
        await airdrop_and_confirm(
            self.rpc, self.agent_wallet.keypair.pubkey(), 5_000_000_000
        )

        self.mint_authority = Keypair()
        await airdrop_and_confirm(
            self.rpc, self.mint_authority.pubkey(), 5_000_000_000
        )
        self.usdc_mint = await create_usdc_mint(self.mint_authority)

        paid_server._used_sigs.clear()
        paid_server.configure(str(self.usdc_mint))
        await airdrop_and_confirm(
            self.rpc, paid_server.PROVIDER_KEYPAIR.pubkey(), 2_000_000_000
        )
        await fund_usdc(
            self.mint_authority,
            self.usdc_mint,
            paid_server.PROVIDER_KEYPAIR.pubkey(),
            0,
        )
        await fund_usdc(
            self.mint_authority,
            self.usdc_mint,
            self.agent_wallet.keypair.pubkey(),
            100_000_000,
        )

        backend = WalletDerivedSecretsBackend(self.agent_wallet.secret_bytes)
        self.secrets = SecretsStore(self.db, backend)
        self.state = StateStore(self.db)
        self.job_engine = JobEngine(self.db)

        self.registry = CapabilityRegistry()
        spec = json.dumps(paid_server.app.openapi())
        for cap in parse_openapi_spec(spec, base_url="http://testserver"):
            self.registry.register(cap)
        for name, amount in {
            "get_current_weather": 0.01,
            "get_weather_forecast": 0.02,
            "get_next_holidays": 0.005,
            "get_country_info": 0.003,
        }.items():
            cap = self.registry.get(name)
            if cap:
                cap.enabled = True
                cap.pricing = PricingConfig(model="per_call", amount=amount)

        self.transport = httpx.ASGITransport(app=paid_server.app)
        self.x402_client = X402HttpClient(
            keypair=self.agent_wallet.keypair,
            rpc_url=SURFPOOL_RPC,
            transport=self.transport,
            base_url="http://testserver",
        )
        self.handlers = ToolHandlers(
            wallet=self.agent_wallet,
            secrets=self.secrets,
            state=self.state,
            db=self.db,
            job_engine=self.job_engine,
            capability_registry=self.registry,
            x402_http_client=self.x402_client,
        )

    async def asyncTearDown(self) -> None:
        await self.handlers.close()
        await self.db.close()
        await self.rpc.close()
        self.db_dir.cleanup()

    async def test_capability_execution_settles_real_x402_payment_on_surfpool(self) -> None:
        provider_before = await get_usdc_balance(
            paid_server.PROVIDER_KEYPAIR.pubkey(), self.usdc_mint
        )
        agent_before = await get_usdc_balance(
            self.agent_wallet.keypair.pubkey(), self.usdc_mint
        )

        with override_provider_routes():
            raw = await self.handlers.dispatch(
                "cap__get_next_holidays", {"country_code": "JP"}
            )

        result = json.loads(raw)
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["capability"], "get_next_holidays")
        self.assertEqual(result["body"][0]["countryCode"], "JP")

        jobs = await self.job_engine.list_recent(1)
        self.assertEqual(jobs[0]["status"], "completed")
        self.assertEqual(jobs[0]["payment_protocol"], "")
        self.assertEqual(jobs[0]["payment_status"], "pending")
        self.assertEqual(jobs[0]["payment_amount"], 0.005)

        provider_after = await get_usdc_balance(
            paid_server.PROVIDER_KEYPAIR.pubkey(), self.usdc_mint
        )
        agent_after = await get_usdc_balance(
            self.agent_wallet.keypair.pubkey(), self.usdc_mint
        )
        self.assertGreaterEqual(provider_after - provider_before, 0.005)
        self.assertLessEqual(agent_after, agent_before - 0.005)
        self.assertTrue(paid_server._used_sigs)

    async def test_payment_response_header_contains_chain_receipt(self) -> None:
        with override_provider_routes():
            raw = await self.handlers.dispatch(
                "cap__get_current_weather", {"location": "London"}
            )

        result = json.loads(raw)
        payment_response = result["headers"].get("payment-response")
        self.assertIsNotNone(payment_response)

        receipt = json.loads(base64.b64decode(payment_response))
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["asset"], str(self.usdc_mint))
        self.assertIn("txSignature", receipt)

    async def test_escrow_tools_submit_platform_supplied_program_payload(self) -> None:
        payments = load_payment_registry(
            [{"type": "escrow", "config": {"rpc_url": SURFPOOL_RPC}}],
            wallet=self.agent_wallet,
        )
        handlers = ToolHandlers(
            wallet=self.agent_wallet,
            secrets=self.secrets,
            state=self.state,
            db=self.db,
            job_engine=self.job_engine,
            payments=payments,
        )
        self.addAsyncCleanup(handlers.close)

        recipient = Keypair()
        before = (await self.rpc.get_balance(recipient.pubkey())).value
        instruction = transfer(
            TransferParams(
                from_pubkey=self.agent_wallet.keypair.pubkey(),
                to_pubkey=recipient.pubkey(),
                lamports=500_000,
            )
        )
        payload = _serialize_instruction_payload(
            instruction,
            fee_payer=str(self.agent_wallet.keypair.pubkey()),
            amount=0.0005,
            currency="SOL",
        )

        prepared = json.loads(
            await handlers.dispatch("pay_escrow__prepare_lock", {"payment": payload})
        )
        self.assertEqual(prepared["currency"], "SOL")
        self.assertEqual(
            prepared["required_signers"], [str(self.agent_wallet.keypair.pubkey())]
        )

        submitted = json.loads(
            await handlers.dispatch(
                "pay_escrow__sign_and_submit",
                {"transaction": prepared["transaction"], "encoding": prepared["encoding"]},
            )
        )
        self.assertTrue(submitted["submitted"])

        status = json.loads(
            await handlers.dispatch(
                "pay_escrow__check_status", {"signature": submitted["signature"]}
            )
        )
        self.assertTrue(status["found"])
        self.assertIn(status["confirmation_status"], {"processed", "confirmed", "finalized"})

        after = (await self.rpc.get_balance(recipient.pubkey())).value
        self.assertGreaterEqual(after - before, 500_000)


if __name__ == "__main__":
    unittest.main()
