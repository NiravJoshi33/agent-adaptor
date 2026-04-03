"""MCP capability ingestion and execution helpers.

This module currently supports MCP over HTTP JSON-RPC. It performs the
required initialize -> initialized lifecycle before issuing tools/list or
tools/call requests.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from agent_adapter_contracts.types import Capability

MCP_PROTOCOL_VERSION = "2025-06-18"


def _tool_to_capability(
    tool: dict[str, Any],
    *,
    server_url: str,
    headers: dict[str, str] | None = None,
) -> Capability:
    description = tool.get("description", "")
    if tool.get("title") and tool["title"] not in description:
        description = (
            f"{tool['title']}: {description}" if description else str(tool["title"])
        )
    return Capability(
        name=str(tool["name"]).replace("-", "_"),
        source="mcp",
        source_ref=str(tool["name"]),
        description=description,
        input_schema=tool.get("inputSchema") or {"type": "object", "properties": {}},
        output_schema=tool.get("outputSchema") or {},
        execution={
            "type": "mcp",
            "server_url": server_url,
            "tool_name": tool["name"],
            "headers": headers or {},
        },
        enabled=False,
    )


def _mcp_hash(tools: list[dict[str, Any]]) -> str:
    raw = json.dumps(tools, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


async def _jsonrpc_request(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    request_id: int | str = 1,
) -> dict[str, Any]:
    response = await client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
        headers=headers or {},
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        message = payload["error"].get("message", "MCP request failed")
        raise ValueError(f"MCP {method} failed: {message}")
    return payload.get("result", {})


async def _jsonrpc_notification(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    response = await client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        },
        headers=headers or {},
    )
    response.raise_for_status()


async def initialize_mcp_session(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, str]:
    base_headers = dict(headers or {})
    init_result = await _jsonrpc_request(
        client,
        url,
        method="initialize",
        params={
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "agent-adapter", "version": "0.1.0"},
        },
        headers=base_headers,
        request_id=1,
    )
    protocol_version = str(
        init_result.get("protocolVersion") or MCP_PROTOCOL_VERSION
    )
    op_headers = dict(base_headers)
    op_headers["MCP-Protocol-Version"] = protocol_version
    await _jsonrpc_notification(
        client,
        url,
        method="notifications/initialized",
        headers=op_headers,
    )
    return op_headers


async def fetch_mcp_capabilities(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[Capability], str]:
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=True, timeout=30)
    try:
        op_headers = await initialize_mcp_session(client, url, headers=headers)
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        request_id = 2
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            result = await _jsonrpc_request(
                client,
                url,
                method="tools/list",
                params=params,
                headers=op_headers,
                request_id=request_id,
            )
            request_id += 1
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return (
            [
                _tool_to_capability(tool, server_url=url, headers=headers)
                for tool in tools
            ],
            _mcp_hash(tools),
        )
    finally:
        if own_client:
            await client.aclose()


async def call_mcp_tool(
    url: str,
    *,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=True, timeout=30)
    try:
        op_headers = await initialize_mcp_session(client, url, headers=headers)
        result = await _jsonrpc_request(
            client,
            url,
            method="tools/call",
            params={"name": tool_name, "arguments": arguments or {}},
            headers=op_headers,
            request_id=2,
        )
        return {
            "tool_name": tool_name,
            "content": result.get("content", []),
            "structured_content": result.get("structuredContent"),
            "is_error": bool(result.get("isError", False)),
            "raw": result,
        }
    finally:
        if own_client:
            await client.aclose()
