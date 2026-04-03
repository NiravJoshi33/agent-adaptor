"""Type-safe tool definitions for the embedded agent.

Each tool is a Pydantic model. The class name is the tool name (with __ separators),
the docstring is the description, and fields define typed parameters.
Use `build_tool_list()` to get the OpenAI-compatible tools list.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from openai import pydantic_function_tool


# ── Status tools ───────────────────────────────────────────────────────


class status__whoami(BaseModel):
    """Returns the adapter's full current state: wallet address, balances, registered platforms, capabilities, active jobs, earnings, and payment adapters."""


# ── Network tools ──────────────────────────────────────────────────────


class net__http_request(BaseModel):
    """Make an HTTP request to any URL. Use this to interact with platform APIs, fetch docs, register, bid, deliver, etc."""

    method: str = Field(description="HTTP method: GET, POST, PUT, PATCH, DELETE")
    url: str = Field(description="Full URL to request")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Request headers"
    )
    body: dict | list | str | None = Field(
        default=None, description="Request body (JSON or string)"
    )
    params: dict[str, str] = Field(
        default_factory=dict, description="Query parameters"
    )


class net__fetch_spec(BaseModel):
    """Fetch and parse an OpenAPI spec from a URL. Returns discovered capabilities with their schemas."""

    url: str = Field(description="URL to the OpenAPI JSON or YAML spec")


# ── Secrets tools ──────────────────────────────────────────────────────


class secrets__store(BaseModel):
    """Store an encrypted credential, scoped by platform and key. Use this immediately when receiving API keys or tokens."""

    platform: str = Field(description="Platform name, e.g. 'agicitizens'")
    key: str = Field(description="Credential key, e.g. 'api_key'")
    value: str = Field(description="Credential value (will be encrypted at rest)")


class secrets__retrieve(BaseModel):
    """Retrieve a decrypted credential by platform and key."""

    platform: str = Field(description="Platform name")
    key: str = Field(description="Credential key")


class secrets__delete(BaseModel):
    """Delete a stored credential."""

    platform: str = Field(description="Platform name")
    key: str = Field(description="Credential key")


# ── State tools ────────────────────────────────────────────────────────


class state__set(BaseModel):
    """Store JSON data in a namespace/key pair. Use for registration metadata, platform state, etc."""

    namespace: str = Field(description="Namespace, e.g. 'platforms', 'config'")
    key: str = Field(description="Key within the namespace")
    data: dict | list | str | float | bool | None = Field(
        description="Any JSON-serializable data"
    )


class state__get(BaseModel):
    """Retrieve JSON data by namespace and key."""

    namespace: str = Field(description="Namespace")
    key: str = Field(description="Key within the namespace")


class state__list(BaseModel):
    """List keys in a namespace, optionally filtered by prefix."""

    namespace: str = Field(description="Namespace")
    prefix: str = Field(default="", description="Optional key prefix filter")


# ── Wallet tools ───────────────────────────────────────────────────────


class wallet__get_address(BaseModel):
    """Returns the adapter's wallet public key / address."""


class wallet__get_balance(BaseModel):
    """Returns the wallet's token balances (SOL, USDC, etc.)."""


class wallet__sign_message(BaseModel):
    """Sign an arbitrary message with the wallet's private key. Used for challenge-response auth flows. Returns hex-encoded signature."""

    message: str = Field(description="Message to sign")


# ── All core tool models ──────────────────────────────────────────────

CORE_TOOL_MODELS: list[type[BaseModel]] = [
    status__whoami,
    net__http_request,
    net__fetch_spec,
    secrets__store,
    secrets__retrieve,
    secrets__delete,
    state__set,
    state__get,
    state__list,
    wallet__get_address,
    wallet__get_balance,
    wallet__sign_message,
]


def build_tool_list(
    extra_models: list[type[BaseModel]] | None = None,
) -> list[dict]:
    """Build the OpenAI-compatible tools list from all registered tool models."""
    models = CORE_TOOL_MODELS + (extra_models or [])
    return [pydantic_function_tool(m) for m in models]
