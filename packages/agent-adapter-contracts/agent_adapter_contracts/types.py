"""Shared dataclasses used across the runtime and plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Capability:
    name: str
    source: Literal["openapi", "mcp", "manual"]
    source_ref: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    base_url: str = ""
    enabled: bool = False
    pricing: PricingConfig | None = None


@dataclass
class PricingConfig:
    model: Literal["per_call", "per_item", "per_token", "quoted"]
    amount: float = 0.0
    currency: str = "USDC"
    item_field: str = ""
    floor: float = 0.0
    ceiling: float = 0.0


@dataclass
class Job:
    id: str
    capability: str
    status: Literal["pending", "executing", "completed", "failed"] = "pending"
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    platform: str = ""
    platform_ref: str = ""
    payment_protocol: str = ""
    payment_status: str = ""
    payment_amount: float = 0.0
    payment_currency: str = "USDC"
    created_at: str = ""
    completed_at: str = ""


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
