"""OpenAPI spec ingestor — parses an OpenAPI 3.x spec into Capabilities."""

from __future__ import annotations

import hashlib
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


def parse_openapi_spec(spec_data: str | bytes) -> list[Capability]:
    """Parse an OpenAPI 3.x spec (JSON or YAML) into a list of Capabilities."""
    spec: dict = yaml.safe_load(spec_data)
    capabilities: list[Capability] = []

    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is None:
                continue

            op_id = operation.get("operationId", f"{method}_{path}".replace("/", "_"))
            name = op_id.replace("-", "_").strip("_")

            capabilities.append(
                Capability(
                    name=name,
                    source="openapi",
                    source_ref=f"{method.upper()} {path}",
                    description=operation.get("summary")
                    or operation.get("description", ""),
                    input_schema=_extract_input_schema(operation, spec),
                    output_schema=_extract_output_schema(operation, spec),
                    enabled=False,
                )
            )

    return capabilities


def spec_hash(spec_data: str | bytes) -> str:
    """Content hash for change detection."""
    raw = spec_data.encode() if isinstance(spec_data, str) else spec_data
    return hashlib.sha256(raw).hexdigest()[:16]


async def fetch_and_parse(url: str) -> tuple[list[Capability], str]:
    """Fetch an OpenAPI spec from a URL and parse it.

    Returns (capabilities, content_hash).
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    raw = resp.text
    return parse_openapi_spec(raw), spec_hash(raw)
