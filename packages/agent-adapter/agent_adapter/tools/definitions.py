"""Type-safe tool definitions for the embedded agent.

Each tool is a Pydantic model. The class name is the tool name (with __ separators),
the docstring is the description, and fields define typed parameters.
Use `build_tool_list()` to get the OpenAI-compatible tools list.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from openai import pydantic_function_tool

from agent_adapter_contracts.types import ToolDefinition


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


class net__listen_sse(BaseModel):
    """Connect to a Server-Sent Events endpoint, collect a bounded number of events, and optionally persist them for later processing."""

    url: str = Field(description="Full SSE endpoint URL")
    headers: dict[str, str] = Field(default_factory=dict, description="Request headers")
    params: dict[str, str] = Field(default_factory=dict, description="Query parameters")
    max_events: int = Field(default=5, description="Maximum number of SSE events to collect")
    timeout_seconds: float = Field(default=10.0, description="Maximum time to wait for SSE events")
    channel: str = Field(default="", description="Optional channel key used when persisting events")
    store_events: bool = Field(default=True, description="Whether to store received events in the local inbound event queue")


class net__heartbeat(BaseModel):
    """Send a one-shot heartbeat or presence update to a platform endpoint and persist the latest heartbeat result locally."""

    url: str = Field(description="Heartbeat endpoint URL")
    method: str = Field(default="POST", description="HTTP method, usually POST or PUT")
    headers: dict[str, str] = Field(default_factory=dict, description="Request headers")
    params: dict[str, str] = Field(default_factory=dict, description="Query parameters")
    body: dict | list | str | None = Field(default=None, description="Optional heartbeat payload")
    namespace: str = Field(default="heartbeats", description="State namespace where the latest heartbeat result is stored")
    key: str = Field(default="", description="State key for the heartbeat record; defaults to the URL")


class net__webhook_receive(BaseModel):
    """Read pending inbound webhook or SSE events from the local queue and optionally acknowledge them."""

    source_type: str = Field(default="", description="Optional source filter: webhook or sse")
    channel: str = Field(default="", description="Optional channel filter")
    limit: int = Field(default=20, description="Maximum number of events to return")
    acknowledge: bool = Field(default=True, description="Whether to mark returned events as delivered")
    pending_only: bool = Field(default=True, description="Whether to return only undelivered events")


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


class wallet__sign_transaction(BaseModel):
    """Sign serialized transaction bytes and return the signed transaction as hex."""

    transaction: str = Field(
        description="Hex-encoded serialized transaction bytes to sign"
    )


# ── Payment tools ─────────────────────────────────────────────────────


class pay_x402__check_requirements(BaseModel):
    """Make an unpaid HTTP request and inspect x402 payment requirements if the server responds with 402."""

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


class pay_x402__execute(BaseModel):
    """Handle an x402-protected HTTP request end-to-end and return the paid response."""

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


class pay_mpp__open_session(BaseModel):
    """Open or join an MPP payment session via the configured payment adapter and return a serializable session payload."""

    headers: dict[str, str] = Field(default_factory=dict, description="HTTP challenge or authorization headers")
    challenge: dict | None = Field(default=None, description="Optional structured payment challenge metadata")
    credential: dict | None = Field(default=None, description="Optional structured payment credential metadata")
    amount: float = Field(default=0.0, description="Payment amount in major units when known")
    session_url: str = Field(default="", description="Optional payment session URL")
    extra: dict = Field(default_factory=dict, description="Additional adapter-specific payment metadata")
    job_id: str = Field(default="", description="Optional job identifier for tracing")


class pay_mpp__capture(BaseModel):
    """Capture or settle an existing MPP payment session."""

    session: dict = Field(description="Serialized session payload returned by pay_mpp__open_session")


class pay_mpp__refund(BaseModel):
    """Refund an existing MPP payment session."""

    session: dict = Field(description="Serialized session payload returned by pay_mpp__open_session")
    reason: str = Field(default="requested_by_customer", description="Refund reason passed to the payment adapter")


# ── Escrow payment tools ──────────────────────────────────────────────


class pay_escrow__prepare_lock(BaseModel):
    """Normalize a platform-supplied Solana escrow payload into an unsigned transaction. Accept either an unsigned_transaction or raw instruction payloads."""

    payment: dict = Field(
        description="Platform-supplied escrow payload. Supports either {unsigned_transaction, transaction_encoding} or {instructions:[{program_id, accounts, data, data_encoding}], fee_payer?, recent_blockhash?, amount?, currency?, metadata?}"
    )


class pay_escrow__sign_and_submit(BaseModel):
    """Sign a prepared Solana escrow transaction with the active wallet and submit it to the configured RPC."""

    transaction: str = Field(description="Serialized transaction bytes")
    encoding: str = Field(
        default="base64", description="Encoding for the transaction: base64 or hex"
    )
    job_id: str = Field(default="", description="Optional job identifier for payment tracing")
    amount: float = Field(default=0.0, description="Payment amount in major units when known")
    currency: str = Field(default="USDC", description="Payment currency")


class pay_escrow__check_status(BaseModel):
    """Check the chain confirmation status for a submitted escrow transaction signature."""

    signature: str = Field(description="Submitted transaction signature")


# ── All core tool models ──────────────────────────────────────────────

CORE_TOOL_MODELS: list[type[BaseModel]] = [
    status__whoami,
    net__http_request,
    net__fetch_spec,
    net__listen_sse,
    net__heartbeat,
    net__webhook_receive,
    secrets__store,
    secrets__retrieve,
    secrets__delete,
    state__set,
    state__get,
    state__list,
    wallet__get_address,
    wallet__get_balance,
    wallet__sign_message,
    wallet__sign_transaction,
    pay_x402__check_requirements,
    pay_x402__execute,
    pay_mpp__open_session,
    pay_mpp__capture,
    pay_mpp__refund,
    pay_escrow__prepare_lock,
    pay_escrow__sign_and_submit,
    pay_escrow__check_status,
]


def build_tool_list(
    extra_models: list[type[BaseModel]] | None = None,
    extra_tools: list[ToolDefinition] | None = None,
) -> list[dict]:
    """Build the OpenAI-compatible tools list from all registered tool models."""
    models = CORE_TOOL_MODELS + (extra_models or [])
    tools = [pydantic_function_tool(m) for m in models]
    for tool in extra_tools or []:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema
                    or {"type": "object", "properties": {}},
                },
            }
        )
    return tools
