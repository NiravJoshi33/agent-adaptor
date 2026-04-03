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
    with open(p) as f:
        return _resolve_env_vars(yaml.safe_load(f))


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
