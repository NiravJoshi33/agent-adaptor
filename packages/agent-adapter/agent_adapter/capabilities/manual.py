"""Manual capability definitions — loaded from agent-adapter.yaml config."""

from __future__ import annotations

from typing import Any

from agent_adapter_contracts.types import Capability


def parse_manual_definitions(definitions: list[dict[str, Any]]) -> list[Capability]:
    """Parse manual capability definitions from config.

    Expected format per PRD §4.1:
        - name: "full_audit"
          description: "Complete security audit of a smart contract"
          inputSchema:
            type: "object"
            properties:
              contract_code:
                type: "string"
            required: ["contract_code"]
          outputSchema:
            type: "object"
            properties:
              report:
                type: "string"
    """
    capabilities: list[Capability] = []
    for defn in definitions:
        capabilities.append(
            Capability(
                name=defn["name"],
                source="manual",
                source_ref=defn.get("sourceRef", defn.get("name", "")),
                description=defn.get("description", ""),
                input_schema=defn.get("inputSchema", defn.get("input_schema", {})),
                output_schema=defn.get("outputSchema", defn.get("output_schema", {})),
                execution=defn.get("execution", {}),
                base_url=defn.get("baseUrl", defn.get("base_url", "")),
                enabled=False,
            )
        )
    return capabilities
