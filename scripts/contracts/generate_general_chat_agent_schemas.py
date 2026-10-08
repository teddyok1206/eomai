#!/usr/bin/env python3
"""Define additive C06 JSON Schema first; preserve all released V1/V2 bytes."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

Schema = dict[str, Any]

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "schemas/general-chat"
PACKAGE = ROOT / "packages/protocol/eom_protocol/schemas"
PREFIX = "eom://schemas/general-chat/"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def obj(properties: dict[str, Schema], required: list[str] | None = None) -> Schema:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties) if required is None else required,
    }


def generate() -> dict[str, Schema]:
    grounding = json.loads((BASE / "general-chat-grounding.schema.json").read_bytes())

    def ref(name: str) -> Schema:
        return {"$ref": PREFIX + "grounding/1.0#/$defs/" + name}

    def own(name: str) -> Schema:
        return {"$ref": PREFIX + "agent-search/1.0#/$defs/" + name}

    def nullable(value: Schema) -> Schema:
        return {"anyOf": [value, {"type": "null"}]}

    def string(pattern: str) -> Schema:
        return {"type": "string", "pattern": pattern}

    def integer(low: int, high: int) -> Schema:
        return {"type": "integer", "minimum": low, "maximum": high}

    def array(value: Schema, high: int) -> Schema:
        return {"type": "array", "items": value, "maxItems": high}

    def enum(values: list[str]) -> Schema:
        return {"enum": values}

    defs: dict[str, Schema] = {}
    for name in ("Input", "Result"):
        value = copy.deepcopy(grounding["$defs"][name])
        value["properties"]["protocol_version"] = {"const": "general-chat-turn/3.0"}
        value["properties"]["prompt_revision"] = {"const": "general-chat-agent/1.0.0"}

        # The answer/knowledge structures retain their released canonical meaning.
        def externalize(node: Any) -> None:
            if isinstance(node, dict):
                if isinstance(node.get("$ref"), str) and node["$ref"].startswith("#/$defs/"):
                    node["$ref"] = PREFIX + "grounding/1.0" + node["$ref"]
                for child in node.values():
                    externalize(child)
            elif isinstance(node, list):
                for child in node:
                    externalize(child)

        externalize(value)
        if name == "Result":
            value["properties"]["tool_records"] = array(
                {"$ref": "eom://schemas/artifact-member/1.0"}, 5
            )
            value["required"].append("tool_records")
        defs[name] = value
    defs["SearchArguments"] = obj(
        {
            "kind": enum(["TOPIC", "RECENT", "EXAM"]),
            "source": enum(["ALL", "PAST_EXAM", "GENERATED"]),
            "terms": array(
                {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 128,
                    "pattern": "^[a-z0-9가-힣_]+$",
                },
                8,
            ),
            "administration_year": nullable(integer(1900, 2200)),
            "administration_month": nullable(integer(1, 12)),
            "target_school_level": nullable(enum(["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"])),
            "target_grade": nullable(integer(1, 6)),
            "subject_key": nullable(
                {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 160,
                    "pattern": "^[a-z0-9][a-z0-9._:-]*$",
                }
            ),
            "item_number": nullable(integer(1, 200)),
        }
    )
    defs["ReadArguments"] = obj(
        {"references": {**array(ref("Item"), 3), "minItems": 1, "uniqueItems": True}}
    )
    defs["Request"] = obj(
        {
            "schema_version": {"const": "general-chat-tool-request/1.0"},
            "rpc_request_id": string("^chatwrpc_[0-9a-f]{32}$"),
            "ticket": {"$ref": PREFIX + "worker-ticket/1.0"},
            "sequence": integer(1, 5),
            "command": {
                "oneOf": [
                    obj({"action": {"const": "SEARCH"}, "arguments": own("SearchArguments")}),
                    obj({"action": {"const": "READ"}, "arguments": own("ReadArguments")}),
                ]
            },
        }
    )
    defs["Card"] = obj(
        {
            "item": ref("Item"),
            "display_name": {"type": "string", "minLength": 1, "maxLength": 512},
            "approval": enum(["APPROVED", "PENDING"]),
            "source_kind": enum(["PAST_EXAM", "GENERATED", "UNCLASSIFIED"]),
            "graph_membership": enum(["INDEXED", "NOT_INDEXED", "UNAVAILABLE"]),
        }
    )
    defs["Outcome"] = obj(
        {
            "status": enum(["SUCCEEDED", "EMPTY", "FAILED"]),
            "cards": array(own("Card"), 6),
            "snapshot": nullable(ref("Snapshot")),
            "truncated": {"type": "boolean"},
            "context": nullable(ref("Context")),
            "error_code": nullable(
                enum(
                    [
                        "CHAT_KNOWLEDGE_FORBIDDEN",
                        "CHAT_KNOWLEDGE_UNAVAILABLE",
                        "CHAT_KNOWLEDGE_POINTER_INVALID",
                        "CHAT_KNOWLEDGE_QUERY_INVALID",
                        "CHAT_KNOWLEDGE_READ_LIMIT",
                        "CHAT_KNOWLEDGE_NOT_OFFERED",
                    ]
                )
            ),
        }
    )
    defs["Record"] = obj(
        {
            "schema_version": {"const": "general-chat-tool-record/1.0"},
            "request": own("Request"),
            "outcome": own("Outcome"),
        }
    )
    defs["Reply"] = obj(
        {
            "schema_version": {"const": "general-chat-tool-reply/1.0"},
            "record": own("Record"),
            "pointer": {"$ref": "eom://schemas/artifact-member/1.0"},
        }
    )
    defs["CatalogRequest"] = obj(
        {
            "schema_version": {"const": "chat-knowledge-search-request/1.0"},
            "operation": {"const": "SEARCH_CHAT_KNOWLEDGE"},
            "actor_id": string("^operator_[0-9a-f]{32}$"),
            "arguments": own("SearchArguments"),
            "snapshot": nullable(ref("Snapshot")),
        }
    )
    defs["CatalogReply"] = obj(
        {
            "schema_version": {"const": "chat-knowledge-search-reply/1.0"},
            "operation": {"const": "SEARCH_CHAT_KNOWLEDGE"},
            "outcome": own("Outcome"),
        }
    )
    output: dict[str, Schema] = {
        "general-chat-agent-search.schema.json": {
            "$schema": DRAFT,
            "$id": PREFIX + "agent-search/1.0",
            "$defs": defs,
        }
    }
    for leaf, definition in (("turn-input", "Input"), ("turn-result", "Result")):
        output["general-chat-" + leaf + "-v3.schema.json"] = {
            "$schema": DRAFT,
            "$id": PREFIX + leaf + "/3.0",
            "$ref": own(definition)["$ref"],
        }
    for leaf in ("worker-policy", "worker-request", "worker-reply", "dispatch"):
        value = json.loads((BASE / ("general-chat-" + leaf + "-v2.schema.json")).read_bytes())
        value["$id"] = PREFIX + leaf + "/3.0"
        value["properties"]["schema_version"] = {"const": "general-chat-" + leaf + "/3.0"}

        def successor(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("$ref") == PREFIX + "worker-policy/2.0":
                    node["$ref"] = PREFIX + "worker-policy/3.0"
                if node.get("$ref") in (PREFIX + "turn-input/2.0", PREFIX + "turn-result/2.0"):
                    node["$ref"] = node["$ref"].replace("/2.0", "/3.0")
                if "enum" in node and PREFIX + "turn-input/2.0" in node["enum"]:
                    node["enum"].append(PREFIX + "turn-input/3.0")
                for child in node.values():
                    successor(child)
            elif isinstance(node, list):
                for child in node:
                    successor(child)

        successor(value)
        if leaf == "worker-policy":
            value["properties"]["agent_prompt_sha256"] = string("^sha256:[0-9a-f]{64}$")
            value["required"].append("agent_prompt_sha256")

        # V3 receivers retain historical V2 input/result recovery support.
        def add_v2(node: Any) -> None:
            if isinstance(node, dict):
                options = node.get("oneOf")
                if isinstance(options, list):
                    for choice in tuple(options):
                        if isinstance(choice, dict) and choice.get("$ref") in (
                            PREFIX + "turn-input/3.0",
                            PREFIX + "turn-result/3.0",
                        ):
                            options.append({"$ref": choice["$ref"].replace("/3.0", "/2.0")})
                for child in node.values():
                    add_v2(child)
            elif isinstance(node, list):
                for child in node:
                    add_v2(child)

        add_v2(value)
        output["general-chat-" + leaf + "-v3.schema.json"] = value
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, schema in generate().items():
        payload = (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode()
        for root in (BASE, PACKAGE):
            target = root / name
            if args.check:
                if not target.exists() or target.read_bytes() != payload:
                    raise SystemExit("Agent schema drift: " + str(target))
            else:
                target.write_bytes(payload)


if __name__ == "__main__":
    main()
