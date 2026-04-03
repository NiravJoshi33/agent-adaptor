"""Config loader — reads agent-adapter.yaml and wires up the runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _resolve_env_vars(value: Any) -> Any:
    """Recursively resolve ${ENV_VAR} values in loaded config."""
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def load_config(path: str | Path = "agent-adapter.yaml") -> dict[str, Any]:
    """Load and return the adapter config from YAML."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    return _resolve_env_vars(_load_raw_config(p))


def _load_raw_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with open(p) as f:
        return yaml.safe_load(f) or {}


def _write_config(path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    p = Path(path)
    p.write_text(yaml.safe_dump(config, sort_keys=False))
    return config


def update_agent_config(
    path: str | Path,
    *,
    system_prompt_file: str | None = None,
    append_to_default: bool | None = None,
) -> dict[str, Any]:
    """Update agent config fields while preserving unrelated YAML values."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    config = _load_raw_config(p)
    agent = config.setdefault("agent", {})
    if system_prompt_file is not None:
        agent["systemPromptFile"] = system_prompt_file
    if append_to_default is not None:
        agent["appendToDefault"] = append_to_default
    return _write_config(p, config)


def update_wallet_config(
    path: str | Path,
    *,
    provider: str | None = None,
    config_updates: dict[str, Any] | None = None,
    replace_config: bool = False,
) -> dict[str, Any]:
    """Update wallet config fields while preserving unrelated YAML values."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    config = _load_raw_config(p)
    wallet = config.setdefault("wallet", {})
    if provider is not None:
        wallet["provider"] = provider
    current = wallet.get("config", {})
    wallet["config"] = (
        dict(config_updates or {})
        if replace_config
        else {**current, **(config_updates or {})}
    )
    return _write_config(p, config)


def apply_pricing_overlay(
    registry: Any, pricing_config: dict[str, dict]
) -> None:
    """Apply pricing from config to discovered capabilities.

    pricing_config format:
        get_current_weather:
          model: per_call
          amount: 0.01
          enabled: true
    """
    from agent_adapter_contracts.types import PricingConfig

    for cap_name, pricing in pricing_config.items():
        cap = registry.get(cap_name)
        if cap is None:
            continue
        if pricing.get("enabled", False):
            cap.enabled = True
        if "model" in pricing and "amount" in pricing:
            cap.pricing = PricingConfig(
                model=pricing["model"],
                amount=pricing["amount"],
                currency=pricing.get("currency", "USDC"),
                item_field=pricing.get("item_field", ""),
                floor=pricing.get("floor", 0.0),
                ceiling=pricing.get("ceiling", 0.0),
            )
