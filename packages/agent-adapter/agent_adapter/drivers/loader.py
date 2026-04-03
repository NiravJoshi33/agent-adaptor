"""Platform driver loader — resolves configured driver plugins into a registry."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from agent_adapter.drivers.registry import DriverRegistry
from agent_adapter.plugins.discovery import discover_plugins


def _load_class(module_name: str, class_name: str) -> type:
    module = import_module(module_name)
    return getattr(module, class_name)


async def load_drivers(
    driver_configs: list[dict[str, Any]] | None,
    *,
    runtime: Any,
    registry: DriverRegistry | None = None,
) -> DriverRegistry:
    """Instantiate configured drivers and initialize them with the runtime."""
    target = registry or DriverRegistry()
    discovered = discover_plugins("driver")
    for item in driver_configs or []:
        module_name = item.get("module")
        class_name = item.get("class_name")
        if not module_name or not class_name:
            plugin_id = item.get("id") or item.get("type") or item.get("provider")
            if plugin_id and plugin_id in discovered:
                spec = discovered[plugin_id]
                module_name, class_name = spec.module, spec.attr
            else:
                raise ValueError(
                    "Driver config entries must define module and class_name or reference an installed plugin id"
                )
        driver = _load_class(module_name, class_name)(**item.get("config", {}))
        await driver.initialize(runtime)
        target.register(driver)
    return target
