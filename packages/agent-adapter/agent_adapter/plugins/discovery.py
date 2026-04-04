"""Entry-point based plugin discovery for installed Agent Adapter plugins."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

ENTRY_POINT_GROUPS = {
    "wallet": "agent_adapter.wallets",
    "payment": "agent_adapter.payments",
    "extension": "agent_adapter.extensions",
    "driver": "agent_adapter.drivers",
    "tool": "agent_adapter.tools",
}


@dataclass(frozen=True)
class PluginSpec:
    plugin_type: str
    plugin_id: str
    module: str
    attr: str
    value: str


def discover_plugins(plugin_type: str) -> dict[str, PluginSpec]:
    """Return installed plugin specs for a given plugin type."""
    try:
        group = ENTRY_POINT_GROUPS[plugin_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported plugin type: {plugin_type}") from exc

    discovered: dict[str, PluginSpec] = {}
    for ep in entry_points().select(group=group):
        discovered[ep.name] = _spec_from_entry_point(plugin_type, ep)
    return discovered


def list_all_plugins() -> dict[str, list[dict[str, str]]]:
    return {
        plugin_type: [
            {
                "id": spec.plugin_id,
                "module": spec.module,
                "class_name": spec.attr,
                "entry_point": spec.value,
            }
            for spec in discover_plugins(plugin_type).values()
        ]
        for plugin_type in ENTRY_POINT_GROUPS
    }


def _spec_from_entry_point(plugin_type: str, ep: EntryPoint) -> PluginSpec:
    module, _, attr = ep.value.partition(":")
    return PluginSpec(
        plugin_type=plugin_type,
        plugin_id=ep.name,
        module=module,
        attr=attr,
        value=ep.value,
    )
