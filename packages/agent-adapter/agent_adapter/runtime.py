"""Runtime bootstrap and shared management services."""

from __future__ import annotations

import asyncio
import csv
import json
import io
import os
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_adapter.agent.loop import AgentLoop, DEFAULT_SYSTEM_PROMPT
from agent_adapter.capabilities.manual import parse_manual_definitions
from agent_adapter.capabilities.mcp import fetch_mcp_capabilities
from agent_adapter.capabilities.openapi import fetch_and_parse, parse_openapi_spec
from agent_adapter.capabilities.registry import CapabilityRegistry
from agent_adapter.config import (
    apply_pricing_overlay,
    load_config,
    update_agent_config,
    update_wallet_config,
)
from agent_adapter.events import (
    acknowledge_inbound_events,
    list_inbound_events,
    record_inbound_event,
)
from agent_adapter.extensions import ExtensionRegistry, load_extensions
from agent_adapter.drivers import DriverRegistry, load_drivers
from agent_adapter.jobs.engine import JobEngine
from agent_adapter.payments import PaymentRegistry, load_payment_registry
from agent_adapter.store.database import Database
from agent_adapter.store.encryption import (
    ExternalSecretsBackend,
    migrate_legacy_wallet_secrets,
)
from agent_adapter.store.secrets import SecretsStore
from agent_adapter.store.state import StateStore
from agent_adapter.tools.handlers import ToolHandlers
from agent_adapter.wallet.loader import load_wallet
from agent_adapter.wallet.persistence import persist_wallet_keypair
from agent_adapter_contracts.extensions import RuntimeEvent
from agent_adapter_contracts.types import Capability, PricingConfig


def _data_dir(config: dict[str, Any], config_path: Path) -> Path:
    raw = config.get("adapter", {}).get("dataDir", "./data")
    path = Path(raw)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def _prompt_path(config: dict[str, Any], config_path: Path) -> Path:
    raw = config.get("agent", {}).get("systemPromptFile", "./prompts/system.md")
    path = Path(raw)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def _db_path(config: dict[str, Any], config_path: Path) -> Path:
    raw = config.get("adapter", {}).get("dbPath")
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else (config_path.parent / path).resolve()
    return _data_dir(config, config_path) / "adapter.db"


def _wallet_encryption_key(config: dict[str, Any]) -> str:
    configured = str(config.get("adapter", {}).get("walletEncryptionKey", "") or "")
    if configured:
        return configured
    return os.environ.get("AGENT_ADAPTER_WALLET_ENCRYPTION_KEY", "")


def _secrets_encryption_key(config: dict[str, Any]) -> str:
    configured = str(config.get("adapter", {}).get("secretsEncryptionKey", "") or "")
    if configured:
        return configured
    return os.environ.get("AGENT_ADAPTER_SECRETS_ENCRYPTION_KEY", "")


async def _legacy_wallet_secret_material(wallet: Any) -> bytes:
    if hasattr(wallet, "secret_bytes"):
        return bytes(wallet.secret_bytes)
    # Legacy runtimes derived secret encryption from wallet signing output.
    return await wallet.sign_message(b"agent-adapter-encryption-key-derivation")


async def _has_persisted_secrets(db: Database) -> bool:
    cursor = await db.conn.execute("SELECT 1 FROM secrets LIMIT 1")
    return await cursor.fetchone() is not None


def _effective_prompt(default_prompt: str, custom_prompt: str, append_to_default: bool) -> str:
    if not custom_prompt:
        return default_prompt if append_to_default else ""
    if append_to_default:
        return default_prompt + "\n\n## Provider Instructions\n" + custom_prompt
    return custom_prompt


async def _load_openapi_source(
    url: str, *, base_url: str = ""
) -> tuple[list[Capability], str]:
    path = Path(url)
    if path.exists():
        raw = path.read_text()
        source_hash = hashlib.sha256(raw.encode()).hexdigest()
        return parse_openapi_spec(raw, base_url=base_url), f"file:{source_hash}"
    return await fetch_and_parse(url, base_url=base_url)


async def discover_capabilities(
    config: dict[str, Any],
) -> tuple[CapabilityRegistry, dict[str, str]]:
    """Discover capabilities from configured sources."""
    registry = CapabilityRegistry()
    source_hashes: dict[str, str] = {}
    caps_cfg = config.get("capabilities", {})
    sources = []
    if "sources" in caps_cfg:
        sources = caps_cfg["sources"]
    elif "source" in caps_cfg:
        sources = [caps_cfg["source"]]

    for source in sources:
        src_type = source.get("type")
        if src_type == "openapi":
            caps, source_hash = await _load_openapi_source(
                source["url"],
                base_url=source.get("base_url", ""),
            )
            for cap in caps:
                registry.register(cap)
                source_hashes[cap.name] = source_hash
        elif src_type == "manual":
            for cap in parse_manual_definitions(caps_cfg.get("definitions", [])):
                registry.register(cap)
                source_hashes[cap.name] = "manual"
        elif src_type == "mcp":
            caps, source_hash = await fetch_mcp_capabilities(
                source.get("server") or source.get("url", ""),
                headers=source.get("headers"),
            )
            for cap in caps:
                registry.register(cap)
                source_hashes[cap.name] = source_hash
        else:
            raise ValueError(f"Unsupported capability source type: {src_type}")

    apply_pricing_overlay(registry, caps_cfg.get("pricing", {}))
    return registry, source_hashes


async def _get_capability_rows(db: Database) -> dict[str, dict[str, Any]]:
    cursor = await db.conn.execute("SELECT * FROM capability_config")
    rows = await cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    return {
        row[0]: dict(zip(cols, row))
        for row in rows
    }


def _pricing_from_row(row: dict[str, Any]) -> PricingConfig | None:
    if not row.get("pricing_model"):
        return None
    return PricingConfig(
        model=row["pricing_model"],
        amount=row["pricing_amount"] or 0.0,
        currency=row.get("pricing_currency") or "USDC",
        item_field=row.get("pricing_item_field") or "",
        floor=row.get("pricing_floor") or 0.0,
        ceiling=row.get("pricing_ceiling") or 0.0,
    )


async def sync_capability_overlays(
    db: Database,
    registry: CapabilityRegistry,
    source_hashes: dict[str, str] | None = None,
) -> None:
    """Persist discovered capabilities and re-apply provider overlays from SQLite."""
    rows = await _get_capability_rows(db)
    for cap in registry.list_all():
        row = rows.get(cap.name)
        source_hash = source_hashes.get(cap.name, "") if source_hashes else ""
        if row is None:
            cap.drift_status = "new"  # type: ignore[attr-defined]
            cap.source_hash = source_hash  # type: ignore[attr-defined]
            await db.conn.execute(
                """
                INSERT INTO capability_config (
                    name, enabled, pricing_amount, pricing_currency, pricing_model,
                    pricing_item_field, pricing_floor, pricing_ceiling,
                    source_hash, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    cap.name,
                    1 if cap.enabled else 0,
                    cap.pricing.amount if cap.pricing else None,
                    cap.pricing.currency if cap.pricing else None,
                    cap.pricing.model if cap.pricing else None,
                    cap.pricing.item_field if cap.pricing else None,
                    cap.pricing.floor if cap.pricing else None,
                    cap.pricing.ceiling if cap.pricing else None,
                    source_hash,
                ),
            )
            continue

        cap.enabled = bool(row["enabled"])
        cap.pricing = _pricing_from_row(row)
        cap.source_hash = source_hash or row.get("source_hash", "")  # type: ignore[attr-defined]
        cap.drift_status = (  # type: ignore[attr-defined]
            "schema_changed"
            if source_hash and source_hash != row.get("source_hash")
            else "unchanged"
        )
        if row.get("custom_description"):
            cap.description = row["custom_description"]
    await db.conn.commit()


async def build_stale_capability_records(
    db: Database, registry: CapabilityRegistry
) -> list[dict[str, Any]]:
    rows = await _get_capability_rows(db)
    stale: list[dict[str, Any]] = []
    live_names = {cap.name for cap in registry.list_all()}
    for name, row in rows.items():
        if name in live_names:
            continue
        pricing = _pricing_from_row(row)
        stale.append(
            {
                "name": name,
                "source": "unknown",
                "source_ref": "",
                "description": row.get("custom_description") or "",
                "enabled": bool(row["enabled"]),
                "pricing": None
                if pricing is None
                else {
                    "model": pricing.model,
                    "amount": pricing.amount,
                    "currency": pricing.currency,
                    "item_field": pricing.item_field,
                    "floor": pricing.floor,
                    "ceiling": pricing.ceiling,
                },
                "input_schema": {},
                "output_schema": {},
                "base_url": "",
                "status": "stale",
                "drift_status": "stale",
            }
        )
    return stale


def _serialize_capability(cap: Capability) -> dict[str, Any]:
    drift_status = getattr(cap, "drift_status", "unchanged")
    return {
        "name": cap.name,
        "source": cap.source,
        "source_ref": cap.source_ref,
        "description": cap.description,
        "enabled": cap.enabled,
        "pricing": None
        if cap.pricing is None
        else {
            "model": cap.pricing.model,
            "amount": cap.pricing.amount,
            "currency": cap.pricing.currency,
            "item_field": cap.pricing.item_field,
            "floor": cap.pricing.floor,
            "ceiling": cap.pricing.ceiling,
        },
        "input_schema": cap.input_schema,
        "output_schema": cap.output_schema,
        "base_url": cap.base_url,
        "drift_status": drift_status,
        "status": (
            "stale"
            if drift_status == "stale"
            else "schema_changed"
            if drift_status == "schema_changed"
            else "new"
            if drift_status == "new" and not cap.pricing
            else "active"
            if cap.enabled and cap.pricing
            else "disabled" if not cap.enabled else "needs_pricing"
        ),
    }


@dataclass
class RuntimeContext:
    config: dict[str, Any]
    config_path: Path
    db: Database
    wallet: Any
    secrets: SecretsStore
    state: StateStore
    registry: CapabilityRegistry
    drivers: DriverRegistry
    payments: PaymentRegistry
    extensions: ExtensionRegistry
    job_engine: JobEngine
    handlers: ToolHandlers
    x402_http_client: Any = None
    agent_paused: bool = False
    stale_capabilities: list[dict[str, Any]] | None = None
    _agent_loop: AgentLoop | None = None
    _prompt_signature: tuple[str, bool, str] | None = None

    async def whoami(self) -> dict[str, Any]:
        active_jobs = await self.job_engine.list_active()
        earnings = await self.job_engine.earnings_today()
        balances = await self.wallet.get_balance()
        low_balance = await self.check_low_balance(balances=balances)
        return {
            "adapter_name": self.config.get("adapter", {}).get("name", "agent-adapter"),
            "wallet": await self.wallet.get_address(),
            "balances": balances,
            "low_balance": low_balance,
            "registered_platforms": await self.list_platforms(),
            "platform_drivers": await self.list_drivers(),
            "capabilities": await self.list_capabilities(),
            "active_jobs": len(active_jobs),
            "jobs_completed_today": (await self.job_engine.count_today()).get(
                "completed", 0
            ),
            "earnings_today": earnings,
            "payment_adapters": self.payments.list(),
            "agent_status": "paused" if self.agent_paused else "running",
        }

    async def list_capabilities(self) -> list[dict[str, Any]]:
        capabilities = [_serialize_capability(cap) for cap in self.registry.list_all()]
        return capabilities + list(self.stale_capabilities or [])

    async def get_capability(self, name: str) -> dict[str, Any]:
        cap = self.registry.get(name)
        if cap is None:
            raise KeyError(name)
        return _serialize_capability(cap)

    async def set_capability_pricing(
        self,
        name: str,
        *,
        model: str,
        amount: float,
        currency: str = "USDC",
        item_field: str = "",
        floor: float = 0.0,
        ceiling: float = 0.0,
    ) -> dict[str, Any]:
        cap = self.registry.get(name)
        if cap is None:
            raise KeyError(name)
        source_hash = str(getattr(cap, "source_hash", "") or "")
        cap.pricing = PricingConfig(
            model=model,
            amount=amount,
            currency=currency,
            item_field=item_field,
            floor=floor,
            ceiling=ceiling,
        )
        cap.drift_status = "unchanged"  # type: ignore[attr-defined]
        await self.db.conn.execute(
            """
            INSERT INTO capability_config (
                name, enabled, pricing_amount, pricing_currency, pricing_model,
                pricing_item_field, pricing_floor, pricing_ceiling, source_hash, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(name) DO UPDATE SET
                pricing_amount = excluded.pricing_amount,
                pricing_currency = excluded.pricing_currency,
                pricing_model = excluded.pricing_model,
                pricing_item_field = excluded.pricing_item_field,
                pricing_floor = excluded.pricing_floor,
                pricing_ceiling = excluded.pricing_ceiling,
                source_hash = excluded.source_hash,
                updated_at = datetime('now')
            """,
            (
                name,
                1 if cap.enabled else 0,
                amount,
                currency,
                model,
                item_field,
                floor,
                ceiling,
                source_hash,
            ),
        )
        await self.db.conn.commit()
        self._agent_loop = None
        return await self.get_capability(name)

    async def set_capability_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        cap = self.registry.get(name)
        if cap is None:
            raise KeyError(name)
        cap.enabled = enabled
        cap.drift_status = "unchanged"  # type: ignore[attr-defined]
        source_hash = str(getattr(cap, "source_hash", "") or "")
        await self.db.conn.execute(
            """
            INSERT INTO capability_config (name, enabled, source_hash, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(name) DO UPDATE SET
                enabled = excluded.enabled,
                source_hash = excluded.source_hash,
                updated_at = datetime('now')
            """,
            (name, 1 if enabled else 0, source_hash),
        )
        await self.db.conn.commit()
        self._agent_loop = None
        return await self.get_capability(name)

    async def refresh_capabilities(self) -> list[dict[str, Any]]:
        registry, source_hashes = await discover_capabilities(self.config)
        await sync_capability_overlays(self.db, registry, source_hashes)
        self.registry = registry
        self.handlers._capability_registry = registry
        self.stale_capabilities = await build_stale_capability_records(self.db, registry)
        self._agent_loop = None
        for cap in self.registry.list_all():
            if "drift_status" not in cap.__dict__:
                cap.drift_status = "unchanged"  # type: ignore[attr-defined]
        capabilities = await self.list_capabilities()
        for cap in capabilities:
            if cap.get("drift_status") not in {None, "", "unchanged"}:
                await self.extensions.emit(RuntimeEvent.ON_CAPABILITY_DRIFT, cap)
        return capabilities

    async def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.job_engine.list_recent(limit)

    async def list_platforms(self) -> list[dict[str, Any]]:
        cursor = await self.db.conn.execute(
            "SELECT * FROM platforms ORDER BY platform_name, base_url"
        )
        rows = await cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def add_platform(
        self,
        base_url: str,
        *,
        platform_name: str = "",
        driver: str = "",
    ) -> dict[str, Any]:
        if driver:
            selected = next(
                (
                    item
                    for item in self.drivers.list_drivers()
                    if driver in {item["name"], item["namespace"]}
                ),
                None,
            )
            if selected is None:
                raise KeyError(driver)
            register_tool = next(
                (tool for tool in selected["tools"] if tool.endswith("__register")),
                None,
            )
            if register_tool is None:
                raise ValueError(f"Driver {selected['name']} does not expose a register tool")
            result = json.loads(
                await self.handlers.dispatch(register_tool, {"platform_url": base_url})
            )
            return {
                "base_url": base_url,
                "driver": selected["name"],
                "registration_method": "driver",
                **result,
            }

        payload = {
            "name": platform_name or base_url,
            "agent_id": await self.wallet.get_address(),
        }
        await self.handlers.dispatch(
            "state__set",
            {
                "namespace": "platforms",
                "key": base_url,
                "data": payload,
            },
        )
        platforms = await self.list_platforms()
        return next(
            (platform for platform in platforms if platform["base_url"] == base_url),
            {
                "base_url": base_url,
                "platform_name": payload["name"],
                "agent_id": payload["agent_id"],
                "registration_status": "registered",
            },
        )

    async def list_drivers(self) -> list[dict[str, Any]]:
        return self.drivers.list_drivers()

    async def list_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        cursor = await self.db.conn.execute(
            "SELECT * FROM decision_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        data = [dict(zip(cols, row)) for row in rows]
        for row in data:
            if row.get("detail"):
                try:
                    row["detail"] = json.loads(row["detail"])
                except Exception:
                    pass
        return data

    async def list_state_entries(
        self,
        namespace: str,
        *,
        prefix: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        cursor = await self.db.conn.execute(
            """
            SELECT key, data, updated_at
            FROM state
            WHERE namespace = ? AND key LIKE ?
            ORDER BY datetime(updated_at) DESC, key
            LIMIT ?
            """,
            (namespace, f"{prefix}%", limit),
        )
        rows = await cursor.fetchall()
        entries: list[dict[str, Any]] = []
        for key, data, updated_at in rows:
            try:
                payload = json.loads(data)
            except Exception:
                payload = data
            entries.append(
                {
                    "key": key,
                    "data": payload,
                    "updated_at": updated_at,
                }
            )
        return entries

    async def get_operations_overview(self) -> dict[str, Any]:
        status = await self.whoami()
        heartbeats = await self.list_state_entries("heartbeats", limit=10)
        events = await self.list_inbound_events(limit=12, pending_only=False)
        platforms = await self.list_platforms()
        jobs = await self.list_jobs(8)

        pending_events_cursor = await self.db.conn.execute(
            "SELECT COUNT(*) FROM inbound_events WHERE delivered_at IS NULL"
        )
        pending_events = int((await pending_events_cursor.fetchone())[0])

        heartbeat_count_cursor = await self.db.conn.execute(
            "SELECT COUNT(*) FROM state WHERE namespace = 'heartbeats'"
        )
        heartbeat_count = int((await heartbeat_count_cursor.fetchone())[0])

        return {
            "wallet": status["wallet"],
            "balances": status["balances"],
            "payment_adapters": status["payment_adapters"],
            "agent_status": status["agent_status"],
            "active_jobs": status["active_jobs"],
            "jobs_completed_today": status["jobs_completed_today"],
            "registered_platforms": platforms,
            "platform_drivers": await self.list_drivers(),
            "heartbeats": heartbeats,
            "heartbeats_total": heartbeat_count,
            "events": events,
            "pending_events": pending_events,
            "recent_jobs": jobs,
        }

    async def get_wallet_overview(self) -> dict[str, Any]:
        status = await self.whoami()
        wallet_cfg = self.config.get("wallet", {})
        provider = str(wallet_cfg.get("provider", "unknown"))
        provider_cfg = wallet_cfg.get("config", {}) or {}
        recent_jobs = await self.list_jobs(12)
        payment_activity = [
            {
                "id": job["id"],
                "capability": job["capability"],
                "platform": job["platform"] or "local runtime",
                "status": job["status"],
                "payment_protocol": job.get("payment_protocol") or "unassigned",
                "payment_amount": job.get("payment_amount") or 0.0,
                "payment_currency": job.get("payment_currency") or "USDC",
                "created_at": job.get("created_at"),
                "completed_at": job.get("completed_at"),
            }
            for job in recent_jobs
            if job.get("payment_protocol") or job.get("payment_amount")
        ]

        cluster = str(provider_cfg.get("cluster", ""))
        chain = str(provider_cfg.get("chain", ""))
        rpc_url = str(provider_cfg.get("rpc_url", ""))
        faucet_links: list[dict[str, str]] = []
        if provider == "solana-raw" and cluster == "devnet":
            faucet_links.append(
                {
                    "label": "Solana Devnet Faucet",
                    "url": "https://faucet.solana.com/",
                }
            )
        if "EtWTRABZaYq6iMfeYKouRu166VU2xqa1" in chain:
            faucet_links.append(
                {
                    "label": "OWS Solana Devnet Faucet",
                    "url": "https://faucet.solana.com/",
                }
            )

        return {
            "address": status["wallet"],
            "balances": status["balances"],
            "low_balance": status.get("low_balance", {}),
            "provider": provider,
            "cluster": cluster,
            "chain": chain,
            "rpc_url": rpc_url,
            "export_supported": provider == "solana-raw" or hasattr(self.wallet, "keypair"),
            "export_requires_token": True,
            "import_supported": True,
            "import_requires_restart": True,
            "faucet_links": faucet_links,
            "payment_activity": payment_activity,
        }

    async def pause_agent(self) -> dict[str, Any]:
        self.agent_paused = True
        return {"status": "paused"}

    async def resume_agent(self) -> dict[str, Any]:
        self.agent_paused = False
        return {"status": "running"}

    async def get_prompt_settings(self) -> dict[str, Any]:
        prompt_path, custom_prompt, append_to_default, _ = self._read_prompt_state()
        return {
            "path": str(prompt_path),
            "exists": prompt_path.exists(),
            "append_to_default": append_to_default,
            "custom_prompt": custom_prompt,
            "default_prompt": DEFAULT_SYSTEM_PROMPT,
            "effective_prompt": _effective_prompt(
                DEFAULT_SYSTEM_PROMPT,
                custom_prompt,
                append_to_default,
            ),
        }

    async def update_prompt_settings(
        self,
        *,
        custom_prompt: str | None = None,
        append_to_default: bool | None = None,
    ) -> dict[str, Any]:
        prompt_path = _prompt_path(self.config, self.config_path)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        if custom_prompt is not None:
            prompt_path.write_text(custom_prompt)

        should_persist_path = (
            custom_prompt is not None
            or "systemPromptFile" not in self.config.get("agent", {})
        )
        if append_to_default is not None:
            self.config.setdefault("agent", {})["appendToDefault"] = append_to_default
            update_agent_config(
                self.config_path,
                append_to_default=append_to_default,
                system_prompt_file=str(prompt_path) if should_persist_path else None,
            )
        elif should_persist_path:
            update_agent_config(self.config_path, system_prompt_file=str(prompt_path))

        self._agent_loop = None
        self._prompt_signature = None
        return await self.get_prompt_settings()

    async def record_inbound_event(
        self,
        *,
        source_type: str,
        source: str,
        channel: str,
        event_type: str,
        payload: Any,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await record_inbound_event(
            self.db,
            source_type=source_type,
            source=source,
            channel=channel,
            event_type=event_type,
            payload=payload,
            headers=headers,
        )

    async def list_inbound_events(
        self,
        *,
        source_type: str | None = None,
        channel: str | None = None,
        limit: int = 20,
        pending_only: bool = True,
        acknowledge: bool = False,
    ) -> list[dict[str, Any]]:
        events = await list_inbound_events(
            self.db,
            source_type=source_type,
            channel=channel,
            limit=limit,
            pending_only=pending_only,
        )
        if acknowledge:
            await acknowledge_inbound_events(
                self.db,
                [int(event["id"]) for event in events if event.get("id") is not None],
            )
        return events

    async def record_llm_usage(self, usage: dict[str, Any]) -> dict[str, Any]:
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(
            usage.get("total_tokens", prompt_tokens + completion_tokens)
            or (prompt_tokens + completion_tokens)
        )
        model = str(usage.get("model", ""))
        cost_cfg = self.config.get("agent", {}).get("costs", {})
        input_rate = float(cost_cfg.get("input_per_1m_tokens", 0.0) or 0.0)
        output_rate = float(cost_cfg.get("output_per_1m_tokens", 0.0) or 0.0)
        currency = str(cost_cfg.get("currency", "USD"))
        estimated_cost = (
            (prompt_tokens / 1_000_000) * input_rate
            + (completion_tokens / 1_000_000) * output_rate
        )
        await self.db.conn.execute(
            """
            INSERT INTO llm_usage (
                model, prompt_tokens, completion_tokens, total_tokens,
                estimated_cost, currency, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                estimated_cost,
                currency,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self.db.conn.commit()
        return {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": estimated_cost,
            "currency": currency,
        }

    async def export_metrics(self, days: int = 30, fmt: str = "csv") -> str:
        fmt = fmt.lower()
        summary = await self.get_metrics_summary(days)
        series = await self.get_metrics_timeseries(days)
        if fmt == "json":
            return json.dumps(
                {"summary": summary, "series": series},
                indent=2,
                sort_keys=True,
            )
        if fmt != "csv":
            raise ValueError(f"Unsupported metrics export format: {fmt}")

        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["day", "revenue", "llm_cost", "stable_margin"],
        )
        writer.writeheader()
        writer.writerows(series)
        return buffer.getvalue().strip()

    async def export_wallet_secret(self) -> dict[str, Any]:
        provider = str(self.config.get("wallet", {}).get("provider", ""))
        if provider != "solana-raw" and not hasattr(self.wallet, "keypair"):
            raise NotImplementedError(
                f'Wallet provider "{provider}" does not support private-key export'
            )

        if hasattr(self.wallet, "keypair"):
            secret_key = str(self.wallet.keypair)
        elif hasattr(self.wallet, "secret_bytes"):
            from solders.keypair import Keypair

            secret_key = str(Keypair.from_bytes(self.wallet.secret_bytes))
        else:
            raise NotImplementedError(
                f'Wallet provider "{provider}" does not expose exportable key material'
            )

        return {
            "provider": provider or "solana-raw",
            "encoding": "base58",
            "secret_key": secret_key,
        }

    async def issue_wallet_export_token(
        self, *, ttl_seconds: int = 300
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max(ttl_seconds, 1))
        token = secrets.token_urlsafe(24)
        await self.state.set(
            "management_tokens",
            "wallet_export",
            {
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                "issued_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
        )
        return {
            "token": token,
            "issued_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "scope": "wallet_export",
        }

    async def validate_wallet_export_token(self, token: str) -> None:
        payload = await self.state.get("management_tokens", "wallet_export")
        now = datetime.now(timezone.utc)
        if not payload:
            raise PermissionError("Wallet export token missing or expired")

        expected_hash = str(payload.get("token_hash", ""))
        expires_at_raw = str(payload.get("expires_at", ""))
        if not expected_hash or not expires_at_raw:
            await self.state.delete("management_tokens", "wallet_export")
            raise PermissionError("Wallet export token missing or expired")

        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except ValueError as exc:
            await self.state.delete("management_tokens", "wallet_export")
            raise PermissionError("Wallet export token missing or expired") from exc

        if not token or hashlib.sha256(token.encode()).hexdigest() != expected_hash:
            raise PermissionError("Wallet export token is invalid")
        if now >= expires_at:
            await self.state.delete("management_tokens", "wallet_export")
            raise PermissionError("Wallet export token missing or expired")

        await self.state.delete("management_tokens", "wallet_export")

    async def import_wallet_secret(self, secret_key: str) -> dict[str, Any]:
        from solders.keypair import Keypair

        keypair = Keypair.from_base58_string(secret_key.strip())
        wallet_encryption_key = _wallet_encryption_key(self.config)
        if not wallet_encryption_key:
            raise ValueError(
                "Wallet import requires adapter.walletEncryptionKey "
                "or AGENT_ADAPTER_WALLET_ENCRYPTION_KEY."
            )
        await persist_wallet_keypair(self.db, wallet_encryption_key, keypair)
        current_cfg = dict(self.config.get("wallet", {}).get("config", {}))
        next_cfg = {
            key: value
            for key, value in current_cfg.items()
            if key in {"rpc_url", "cluster"}
        }
        update_wallet_config(
            self.config_path,
            provider="solana-raw",
            config_updates=next_cfg,
            replace_config=True,
        )
        self.config = load_config(self.config_path)
        return {
            "provider": "solana-raw",
            "address": str(keypair.pubkey()),
            "encoding": "base58",
        }

    async def check_low_balance(
        self,
        *,
        balances: dict[str, Any] | None = None,
        emit: bool = True,
    ) -> dict[str, Any]:
        raw_thresholds = (
            self.config.get("adapter", {}).get("lowBalanceThresholds", {}) or {}
        )
        thresholds = {
            str(asset).lower(): float(value)
            for asset, value in raw_thresholds.items()
            if value is not None
        }
        if not thresholds:
            return {
                "active": False,
                "thresholds": {},
                "below_threshold": {},
            }

        balance_map = balances or await self.wallet.get_balance()
        below_threshold: dict[str, dict[str, float]] = {}
        for asset, threshold in thresholds.items():
            balance = float(
                balance_map.get(asset, balance_map.get(asset.upper(), 0.0)) or 0.0
            )
            if balance <= threshold:
                below_threshold[asset] = {
                    "balance": balance,
                    "threshold": threshold,
                }

        active = bool(below_threshold)
        now = datetime.now(timezone.utc).isoformat()
        previous = await self.state.get("alerts", "low_balance") or {}
        payload = {
            "wallet": await self.wallet.get_address(),
            "balances": balance_map,
            "thresholds": thresholds,
            "below_threshold": below_threshold,
            "detected_at": now,
            "active": active,
        }

        if (
            emit
            and active
            and (
                not previous.get("active")
                or previous.get("below_threshold") != below_threshold
            )
        ):
            await self.extensions.emit(RuntimeEvent.ON_LOW_BALANCE, payload)

        next_state = {
            "active": active,
            "thresholds": thresholds,
            "below_threshold": below_threshold,
            "last_checked_at": now,
        }
        if previous != next_state:
            await self.state.set("alerts", "low_balance", next_state)
        return payload

    async def get_metrics_summary(self, days: int = 30) -> dict[str, Any]:
        since = (
            datetime.now(timezone.utc) - timedelta(days=max(days - 1, 0))
        ).strftime("%Y-%m-%d")
        status_rows = await self._fetch_rows(
            """
            SELECT status, COUNT(*) AS count
            FROM jobs
            WHERE created_at >= ?
            GROUP BY status
            """,
            (since,),
        )
        completed_count = next(
            (row["count"] for row in status_rows if row["status"] == "completed"),
            0,
        )
        revenue_rows = await self._fetch_rows(
            """
            SELECT payment_currency, COALESCE(SUM(payment_amount), 0) AS amount
            FROM jobs
            WHERE status = 'completed' AND created_at >= ?
            GROUP BY payment_currency
            """,
            (since,),
        )
        protocol_rows = await self._fetch_rows(
            """
            SELECT payment_protocol, COUNT(*) AS jobs, COALESCE(SUM(payment_amount), 0) AS revenue
            FROM jobs
            WHERE created_at >= ?
            GROUP BY payment_protocol
            ORDER BY revenue DESC, jobs DESC
            """,
            (since,),
        )
        avg_job_row = await self._fetch_one(
            """
            SELECT COALESCE(AVG(payment_amount), 0) AS avg_value
            FROM jobs
            WHERE status = 'completed' AND created_at >= ?
            """,
            (since,),
        )
        llm_row = await self._fetch_one(
            """
            SELECT
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                MIN(currency) AS currency
            FROM llm_usage
            WHERE created_at >= ?
            """,
            (since,),
        )
        llm_model_rows = await self._fetch_rows(
            """
            SELECT model, COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_cost), 0) AS estimated_cost
            FROM llm_usage
            WHERE created_at >= ?
            GROUP BY model
            ORDER BY estimated_cost DESC, total_tokens DESC
            """,
            (since,),
        )

        stable_revenue = sum(
            row["amount"]
            for row in revenue_rows
            if row["payment_currency"] in {"USD", "USDC"}
        )
        llm_cost = float(llm_row.get("estimated_cost", 0.0) if llm_row else 0.0)
        return {
            "days": days,
            "since": since,
            "jobs_by_status": {row["status"]: row["count"] for row in status_rows},
            "completed_jobs": completed_count,
            "revenue_by_currency": {
                row["payment_currency"] or "UNKNOWN": row["amount"] for row in revenue_rows
            },
            "revenue_by_payment_protocol": [
                {
                    "payment_protocol": row["payment_protocol"] or "unassigned",
                    "jobs": row["jobs"],
                    "revenue": row["revenue"],
                }
                for row in protocol_rows
            ],
            "avg_completed_job_value": avg_job_row.get("avg_value", 0.0)
            if avg_job_row
            else 0.0,
            "llm_usage": {
                "prompt_tokens": llm_row.get("prompt_tokens", 0) if llm_row else 0,
                "completion_tokens": llm_row.get("completion_tokens", 0)
                if llm_row
                else 0,
                "total_tokens": llm_row.get("total_tokens", 0) if llm_row else 0,
                "estimated_cost": llm_cost,
                "currency": (llm_row.get("currency") if llm_row else None) or "USD",
                "by_model": llm_model_rows,
            },
            "estimated_stable_margin": stable_revenue - llm_cost,
        }

    async def get_metrics_timeseries(self, days: int = 14) -> list[dict[str, Any]]:
        since_dt = datetime.now(timezone.utc) - timedelta(days=max(days - 1, 0))
        since = since_dt.strftime("%Y-%m-%d")
        revenue_rows = await self._fetch_rows(
            """
            SELECT substr(created_at, 1, 10) AS day, COALESCE(SUM(payment_amount), 0) AS revenue
            FROM jobs
            WHERE status = 'completed' AND created_at >= ?
            GROUP BY substr(created_at, 1, 10)
            """,
            (since,),
        )
        llm_rows = await self._fetch_rows(
            """
            SELECT substr(created_at, 1, 10) AS day, COALESCE(SUM(estimated_cost), 0) AS cost
            FROM llm_usage
            WHERE created_at >= ?
            GROUP BY substr(created_at, 1, 10)
            """,
            (since,),
        )
        revenue_by_day = {row["day"]: row["revenue"] for row in revenue_rows}
        cost_by_day = {row["day"]: row["cost"] for row in llm_rows}
        series: list[dict[str, Any]] = []
        for index in range(days):
            day = (since_dt + timedelta(days=index)).strftime("%Y-%m-%d")
            revenue = float(revenue_by_day.get(day, 0.0))
            llm_cost = float(cost_by_day.get(day, 0.0))
            series.append(
                {
                    "day": day,
                    "revenue": revenue,
                    "llm_cost": llm_cost,
                    "stable_margin": revenue - llm_cost,
                }
            )
        return series

    async def _fetch_rows(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        cursor = await self.db.conn.execute(query, params)
        rows = await cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def _fetch_one(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        cursor = await self.db.conn.execute(query, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))

    async def ensure_agent_loop(self) -> AgentLoop | None:
        agent_cfg = self.config.get("agent", {})
        api_key = agent_cfg.get("apiKey") or _default_api_key(agent_cfg)
        if not api_key:
            return None

        _, custom_prompt, append_to_default, prompt_signature = self._read_prompt_state()
        if self._agent_loop is not None and self._prompt_signature == prompt_signature:
            return self._agent_loop

        self._agent_loop = AgentLoop(
            api_key=api_key,
            model=agent_cfg.get("model", "openai/gpt-oss-120b"),
            base_url=agent_cfg.get("base_url", "https://openrouter.ai/api/v1"),
            handlers=self.handlers,
            custom_prompt=custom_prompt if append_to_default else "",
            system_prompt=custom_prompt if not append_to_default else DEFAULT_SYSTEM_PROMPT,
            max_tool_rounds=agent_cfg.get("max_tool_rounds", 20),
            extra_tools=self.registry.to_tool_definitions()
            + self.drivers.to_tool_definitions(),
            usage_recorder=self.record_llm_usage,
        )
        self._prompt_signature = prompt_signature
        return self._agent_loop

    async def run_agent_once(self, message: str = "Begin your planning loop.") -> str:
        agent = await self.ensure_agent_loop()
        if agent is None:
            return "Agent API key not configured; skipping agent loop."
        if self.agent_paused:
            return "Agent is paused."
        await self.check_low_balance()
        try:
            return await agent.run_once(message)
        except Exception as exc:
            await self.extensions.emit(
                RuntimeEvent.ON_AGENT_ERROR,
                {
                    "error": str(exc),
                    "message": message,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            raise

    async def run_agent_forever(self) -> None:
        interval = int(self.config.get("agent", {}).get("loopInterval", 30))
        while True:
            if not self.agent_paused:
                await self.run_agent_once()
            await asyncio.sleep(interval)

    async def close(self) -> None:
        try:
            await self.drivers.shutdown()
        finally:
            try:
                await self.extensions.shutdown()
            finally:
                try:
                    await self.handlers.close()
                finally:
                    await self.db.close()

    def _read_prompt_state(self) -> tuple[Path, str, bool, tuple[str, bool, str]]:
        prompt_path = _prompt_path(self.config, self.config_path)
        custom_prompt = prompt_path.read_text() if prompt_path.exists() else ""
        append_to_default = self.config.get("agent", {}).get("appendToDefault", True)
        signature = (
            str(prompt_path.resolve()),
            append_to_default,
            custom_prompt,
        )
        return prompt_path, custom_prompt, append_to_default, signature


def _default_api_key(agent_cfg: dict[str, Any]) -> str:
    provider = agent_cfg.get("provider", "")
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY", "")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY", "")
    return os.environ.get("OPENROUTER_API_KEY", "")


async def create_runtime(config_path: str | Path = "agent-adapter.yaml") -> RuntimeContext:
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    db = Database(_db_path(config, config_path))
    await db.connect()
    runtime: RuntimeContext | None = None
    try:
        wallet_cfg = config.get("wallet", {})
        wallet = await load_wallet(
            wallet_cfg.get("provider", "solana-raw"),
            wallet_cfg.get("config", {}),
            db=db,
            data_dir=_data_dir(config, config_path),
            wallet_encryption_key=_wallet_encryption_key(config),
        )

        secrets_encryption_key = _secrets_encryption_key(config)
        if not secrets_encryption_key:
            raise ValueError(
                "Secrets encryption requires adapter.secretsEncryptionKey, "
                "or AGENT_ADAPTER_SECRETS_ENCRYPTION_KEY."
            )
        secrets_backend = ExternalSecretsBackend(secrets_encryption_key)
        if await _has_persisted_secrets(db):
            async def _load_legacy_wallet_key_material() -> bytes:
                return await _legacy_wallet_secret_material(wallet)

            await migrate_legacy_wallet_secrets(
                db,
                legacy_wallet_key_material_loader=_load_legacy_wallet_key_material,
                target_backend=secrets_backend,
            )
        secrets = SecretsStore(db, secrets_backend)
        state = StateStore(db)
        registry, source_hashes = await discover_capabilities(config)
        await sync_capability_overlays(db, registry, source_hashes)
        stale_capabilities = await build_stale_capability_records(db, registry)

        extensions = await load_extensions(config.get("extensions"), runtime=None)
        job_engine = JobEngine(db, extensions)
        drivers = DriverRegistry()

        payments = load_payment_registry(config.get("payments"), wallet=wallet)

        x402_http_client = None
        if "x402" in payments.list() and hasattr(wallet, "keypair"):
            from payment_x402.http_client import X402HttpClient

            rpc_url = wallet_cfg.get("config", {}).get("rpc_url", "http://127.0.0.1:8899")
            x402_http_client = X402HttpClient(keypair=wallet.keypair, rpc_url=rpc_url)

        runtime = RuntimeContext(
            config=config,
            config_path=config_path,
            db=db,
            wallet=wallet,
            secrets=secrets,
            state=state,
            registry=registry,
            drivers=drivers,
            payments=payments,
            extensions=extensions,
            job_engine=job_engine,
            handlers=ToolHandlers(
                wallet=wallet,
                secrets=secrets,
                state=state,
                db=db,
                job_engine=job_engine,
                capability_registry=registry,
                driver_registry=drivers,
                extensions=extensions,
                x402_http_client=x402_http_client,
                payments=payments,
            ),
            x402_http_client=x402_http_client,
            stale_capabilities=stale_capabilities,
        )
        runtime.handlers._whoami_fn = runtime.whoami
        await load_drivers(config.get("drivers"), runtime=runtime, registry=drivers)
        for extension in extensions._extensions:
            if hasattr(extension, "initialize"):
                await extension.initialize(runtime)
        return runtime
    except Exception:
        if runtime is not None:
            await runtime.close()
        else:
            await db.close()
        raise
