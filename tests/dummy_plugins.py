"""Test-only plugin implementations for management/CLI bootstrap tests."""

from __future__ import annotations

from agent_adapter_contracts.types import ToolDefinition


class DummyWalletPlugin:
    def __init__(
        self,
        address: str = "dummy-wallet",
        sol: float = 2.5,
        usdc: float = 9.0,
    ) -> None:
        self._address = address
        self._balances = {"sol": sol, "usdc": usdc}
        self.secret_bytes = b"\x22" * 64

    async def initialize(self) -> None:
        return None

    async def get_address(self) -> str:
        return self._address

    async def get_balance(self, chain: str | None = None) -> dict[str, float]:
        return dict(self._balances)

    async def sign_message(self, msg: bytes) -> bytes:
        return b"\xbb" * 64

    async def sign_transaction(self, tx: bytes) -> bytes:
        return tx + b"-dummy"


class DummyPlatformDriver:
    def __init__(self, label: str = "dummy-platform") -> None:
        self._runtime = None
        self._label = label

    @property
    def name(self) -> str:
        return "dummy-driver"

    @property
    def namespace(self) -> str:
        return "drv_dummy"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="drv_dummy__register",
                description="Register the runtime with a dummy platform driver.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "platform_url": {"type": "string"},
                    },
                    "required": ["platform_url"],
                },
            )
        ]

    async def initialize(self, runtime) -> None:
        self._runtime = runtime

    async def shutdown(self) -> None:
        return None

    async def execute(self, tool_name: str, args: dict[str, object]) -> dict[str, object]:
        if tool_name != "drv_dummy__register":
            raise ValueError(f"Unknown tool: {tool_name}")
        assert self._runtime is not None
        platform_url = str(args["platform_url"])
        wallet = await self._runtime.wallet.get_address()
        await self._runtime.handlers.dispatch(
            "state__set",
            {
                "namespace": "platforms",
                "key": platform_url,
                "data": {
                    "name": self._label,
                    "agent_id": wallet,
                    "driver": self.name,
                },
            },
        )
        return {
            "registered": True,
            "platform_url": platform_url,
            "wallet": wallet,
            "driver": self.name,
        }
