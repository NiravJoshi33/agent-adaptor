"""OpenAPI spec ingestor — parses an OpenAPI 3.x spec into Capabilities."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import httpx
import yaml

from agent_adapter_contracts.types import Capability


def _resolve_ref(ref: str, spec: dict) -> dict:
    """Resolve a $ref pointer like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node[part]
    return node


def _resolve_schema(schema: dict | None, spec: dict) -> dict:
    """Recursively resolve $ref in a schema."""
    if schema is None:
        return {}
    if "$ref" in schema:
        return _resolve_schema(_resolve_ref(schema["$ref"], spec), spec)
    return schema


def _extract_input_schema(operation: dict, spec: dict) -> dict:
    """Build a JSON Schema from parameters + requestBody."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in operation.get("parameters", []):
        p = _resolve_schema(param, spec) if "$ref" in param else param
        name = p["name"]
        properties[name] = _resolve_schema(p.get("schema", {}), spec)
        if p.get("required"):
            required.append(name)

    body = operation.get("requestBody", {})
    if "$ref" in body:
        body = _resolve_ref(body["$ref"], spec)
    content = body.get("content", {})
    json_body = content.get("application/json", {})
    body_schema = _resolve_schema(json_body.get("schema"), spec)
    if body_schema:
        if body_schema.get("type") == "object" and "properties" in body_schema:
            properties.update(body_schema["properties"])
            required.extend(body_schema.get("required", []))
        else:
            properties["body"] = body_schema

    if not properties:
        return {}
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _merge_parameters(
    path_item: dict[str, Any], operation: dict[str, Any], spec: dict
) -> list[dict[str, Any]]:
    """Merge path-level and operation-level parameters per OpenAPI rules."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in path_item.get("parameters", []) + operation.get("parameters", []):
        param = _resolve_schema(raw, spec) if "$ref" in raw else raw
        merged[(param["name"], param.get("in", "query"))] = param
    return list(merged.values())


def _extract_request_body(operation: dict[str, Any], spec: dict) -> dict[str, Any]:
    """Resolve requestBody metadata for execution planning."""
    body = operation.get("requestBody", {})
    if "$ref" in body:
        body = _resolve_ref(body["$ref"], spec)
    return body


def _build_execution_plan(
    method: str,
    path: str,
    params: list[dict[str, Any]],
    request_body: dict[str, Any],
    spec: dict,
) -> dict[str, Any]:
    """Create enough execution metadata for cap__* HTTP tool handlers."""
    json_body = request_body.get("content", {}).get("application/json", {})
    body_schema = _resolve_schema(json_body.get("schema"), spec)

    plan: dict[str, Any] = {
        "type": "http",
        "method": method.upper(),
        "path": path,
        "path_params": [],
        "query_params": [],
        "header_params": [],
        "cookie_params": [],
        "body_schema": body_schema,
        "body_required": bool(request_body.get("required", False)),
    }

    for param in params:
        loc = param.get("in", "query")
        key = f"{loc}_params"
        if key in plan:
            plan[key].append(param["name"])

    return plan


def _extract_output_schema(operation: dict, spec: dict) -> dict:
    """Extract response schema from the 200/201 response."""
    responses = operation.get("responses", {})
    for code in ("200", "201", "default"):
        resp = responses.get(code, {})
        if "$ref" in resp:
            resp = _resolve_ref(resp["$ref"], spec)
        content = resp.get("content", {})
        json_resp = content.get("application/json", {})
        schema = _resolve_schema(json_resp.get("schema"), spec)
        if schema:
            return schema
    return {}


def parse_openapi_spec(
    spec_data: str | bytes, base_url: str = ""
) -> list[Capability]:
    """Parse an OpenAPI 3.x spec (JSON or YAML) into a list of Capabilities."""
    spec: dict = yaml.safe_load(spec_data)
    capabilities: list[Capability] = []

    # Resolve base_url from spec if not provided
    if not base_url:
        servers = spec.get("servers", [])
        if servers:
            base_url = servers[0].get("url", "")

    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is None:
                continue

            params = _merge_parameters(path_item, operation, spec)
            op_for_schema = deepcopy(operation)
            op_for_schema["parameters"] = params
            request_body = _extract_request_body(operation, spec)
            op_for_schema["requestBody"] = request_body

            op_id = operation.get("operationId", f"{method}_{path}".replace("/", "_"))
            name = op_id.replace("-", "_").strip("_")

            capabilities.append(
                Capability(
                    name=name,
                    source="openapi",
                    source_ref=f"{method.upper()} {path}",
                    description=operation.get("summary")
                    or operation.get("description", ""),
                    input_schema=_extract_input_schema(op_for_schema, spec),
                    output_schema=_extract_output_schema(operation, spec),
                    execution=_build_execution_plan(
                        method, path, params, request_body, spec
                    ),
                    base_url=base_url,
                    enabled=False,
                )
            )

    return capabilities


def spec_hash(spec_data: str | bytes) -> str:
    """Content hash for change detection."""
    raw = spec_data.encode() if isinstance(spec_data, str) else spec_data
    return hashlib.sha256(raw).hexdigest()[:16]


async def fetch_and_parse(
    url: str, base_url: str = "", client: httpx.AsyncClient | None = None
) -> tuple[list[Capability], str]:
    """Fetch an OpenAPI spec from a URL and parse it.

    Returns (capabilities, content_hash).
    """
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=True)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text
        return parse_openapi_spec(raw, base_url=base_url), spec_hash(raw)
    finally:
        if own_client:
            await client.aclose()
