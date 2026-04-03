"""ExtensionRegistry — emits lifecycle events, knows nothing about listeners."""

import asyncio

from agent_adapter_contracts.extensions import Extension, ExtensionHook, RuntimeEvent


def _normalize_hook_name(hook: ExtensionHook) -> str:
    if isinstance(hook, RuntimeEvent):
        return hook.value
    return str(hook)


class ExtensionRegistry:
    def __init__(self) -> None:
        self._extensions: list[Extension] = []

    def register(self, ext: Extension) -> None:
        self._extensions.append(ext)

    async def emit(self, hook: ExtensionHook, payload: object) -> None:
        hook_name = _normalize_hook_name(hook)
        tasks = [
            getattr(ext, hook_name)(payload)
            for ext in self._extensions
            if hook_name in {_normalize_hook_name(item) for item in ext.hooks}
            and hasattr(ext, hook_name)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
