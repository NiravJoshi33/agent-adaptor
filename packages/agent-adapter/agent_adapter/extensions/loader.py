"""Extension loader — resolves configured extension plugins into a registry."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from agent_adapter.extensions.registry import ExtensionRegistry


def _load_class(module_name: str, class_name: str) -> type:
    module = import_module(module_name)
    return getattr(module, class_name)


async def load_extensions(
    extension_configs: list[dict[str, Any]] | None,
    runtime: Any = None,
) -> ExtensionRegistry:
    """Instantiate configured extensions and initialize them when possible."""
    registry = ExtensionRegistry()
    for item in extension_configs or []:
        module_name = item.get("module")
        class_name = item.get("class_name")
        if not module_name or not class_name:
            raise ValueError(
                "Extension config entries must define module and class_name"
            )
        extension = _load_class(module_name, class_name)(**item.get("config", {}))
        registry.register(extension)
        if runtime is not None and hasattr(extension, "initialize"):
            await extension.initialize(runtime)
    return registry
