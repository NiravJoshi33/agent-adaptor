"""Tool plugin loader — resolves configured agent tool plugins into a registry."""

from __future__ import annotations

import importlib.util
from importlib import import_module
from pathlib import Path
from typing import Any

from agent_adapter.plugins.discovery import discover_plugins
from agent_adapter.tool_plugins.registry import ToolPluginRegistry


def _load_class(module_name: str, class_name: str) -> type:
    module_path = Path(module_name)
    if module_name.endswith(".py") and module_path.exists():
        safe_name = f"agent_adapter_dynamic_tool_plugin_{abs(hash(str(module_path.resolve())))}"
        spec = importlib.util.spec_from_file_location(safe_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load tool plugin module from {module_name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = import_module(module_name)
    return getattr(module, class_name)


async def load_tool_plugins(
    tool_configs: list[dict[str, Any]] | None,
    *,
    runtime: Any,
    registry: ToolPluginRegistry | None = None,
) -> ToolPluginRegistry:
    """Instantiate configured tool plugins and initialize them with the runtime."""
    target = registry or ToolPluginRegistry()
    discovered = discover_plugins("tool")
    for item in tool_configs or []:
        module_name = item.get("module")
        class_name = item.get("class_name")
        if not module_name or not class_name:
            plugin_id = item.get("id") or item.get("type") or item.get("provider")
            if plugin_id and plugin_id in discovered:
                spec = discovered[plugin_id]
                module_name, class_name = spec.module, spec.attr
            else:
                raise ValueError(
                    "Tool config entries must define module and class_name or reference an installed plugin id"
                )
        plugin = _load_class(module_name, class_name)(**item.get("config", {}))
        await plugin.initialize(runtime)
        target.register(plugin)
    return target
