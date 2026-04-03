"""Payment adapter loader — resolves configured payment plugins into a registry."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from agent_adapter.payments.registry import PaymentRegistry
from agent_adapter.plugins.discovery import discover_plugins

_BUNDLED_PAYMENT_PLUGINS: dict[str, tuple[str, str]] = {
    "free": ("payment_free", "FreeAdapter"),
    "x402": ("payment_x402", "X402Adapter"),
    "escrow": ("payment_escrow", "EscrowAdapter"),
    "solana_escrow": ("payment_escrow", "EscrowAdapter"),
    "mpp": ("payment_mpp_stripe", "MPPStripeAdapter"),
    "stripe_mpp": ("payment_mpp_stripe", "MPPStripeAdapter"),
    "mpp_stripe": ("payment_mpp_stripe", "MPPStripeAdapter"),
}


def _load_class(module_name: str, class_name: str) -> type:
    module = import_module(module_name)
    return getattr(module, class_name)


def load_payment_registry(
    payment_configs: list[dict[str, Any]] | None,
    wallet: Any = None,
) -> PaymentRegistry:
    """Instantiate configured payment adapters and register them."""
    registry = PaymentRegistry()
    discovered = discover_plugins("payment")
    for item in payment_configs or []:
        plugin_type = item.get("type") or item.get("provider") or item.get("id")
        if not plugin_type:
            raise ValueError("Payment config entry is missing a type/id")

        module_name = item.get("module")
        class_name = item.get("class_name")
        if module_name is None or class_name is None:
            if plugin_type in discovered:
                spec = discovered[plugin_type]
                module_name, class_name = spec.module, spec.attr
            else:
                try:
                    module_name, class_name = _BUNDLED_PAYMENT_PLUGINS[plugin_type]
                except KeyError as exc:
                    raise ValueError(
                        f"Unknown payment adapter '{plugin_type}'. "
                        "Set module and class_name for external plugins or install a matching entry-point plugin."
                    ) from exc

        kwargs = dict(item.get("config", {}))
        if plugin_type == "x402" and "keypair" not in kwargs and hasattr(wallet, "keypair"):
            kwargs["keypair"] = wallet.keypair

        adapter = _load_class(module_name, class_name)(**kwargs)
        registry.register(adapter)
    return registry
