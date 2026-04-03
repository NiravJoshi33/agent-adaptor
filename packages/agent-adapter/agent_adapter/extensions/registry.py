"""ExtensionRegistry — emits lifecycle events, knows nothing about listeners."""

import asyncio

from agent_adapter_contracts.extensions import Extension, ExtensionHook


class ExtensionRegistry:
    def __init__(self) -> None:
        self._extensions: list[Extension] = []

    def register(self, ext: Extension) -> None:
        self._extensions.append(ext)

    async def emit(self, hook: ExtensionHook, payload: object) -> None:
        tasks = [
            getattr(ext, hook)(payload)
            for ext in self._extensions
            if hook in ext.hooks and hasattr(ext, hook)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
