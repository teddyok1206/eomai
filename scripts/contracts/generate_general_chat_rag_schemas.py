#!/usr/bin/env python3
"""Define CHAT-RAG-2 JSON Schema before runtime models; never rewrite predecessors."""

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
RAG = PREFIX + "rag/1.0"
ARTIFACT = "eom://schemas/artifact-member/1.0"


def _object(properties: dict[str, Schema]) -> Schema:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _ref(name: str) -> Schema:
    return {"$ref": RAG + "#/$defs/" + name}


def _old(name: str) -> Schema:
    return {"$ref": PREFIX + "grounding/1.0#/$defs/" + name}


def _nullable(value: Schema) -> Schema:
    return {"anyOf": [value, {"type": "null"}]}


def _string(*, pattern: str | None = None, maximum: int = 256) -> Schema:
    value: Schema = {"type": "string", "minLength": 1, "maxLength": maximum}
    if pattern is not None:
        value["pattern"] = pattern
    return value


def _array(value: Schema, maximum: int, *, minimum: int = 0, unique: bool = False) -> Schema:
    output: Schema = {"type": "array", "items": value, "minItems": minimum, "maxItems": maximum}
    if unique:
        output["uniqueItems"] = True
    return output


def _enum(*values: str) -> Schema:
    return {"enum": list(values)}


def _id(prefix: str) -> Schema:
    return _string(pattern="^" + prefix + "_[0-9a-f]{32}$", maximum=64)


def _externalize(value: Any, namespace: str) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("$ref"), str) and value["$ref"].startswith("#/$defs/"):
            value["$ref"] = namespace + value["$ref"]
        for child in value.values():
            _externalize(child, namespace)
    elif isinstance(value, list):
        for child in value:
            _externalize(child, namespace)


def generate() -> dict[str, Schema]:
    grounding = json.loads((BASE / "general-chat-grounding.schema.json").read_bytes())
    agent = json.loads((BASE / "general-chat-agent-search.schema.json").read_bytes())
    artifact = json.loads((PACKAGE / "artifact-member-v1.schema.json").read_bytes())
    defs: dict[str, Schema] = {}
    defs["Policy"] = _object(
        {"access_policy_revision_id": _id("accessrev"), "sha256": _old("Hash")}
    )
    defs["Scope"] = _object({"snapshot": _old("Snapshot"), "policy": _ref("Policy")})
    pointer = _object(
        {
            "artifact_id": _id("artifact"),
            "artifact_revision_id": _id("rev"),
            "member_path": copy.deepcopy(artifact["properties"]["member_path"]),
            "sha256": _old("Hash"),
            "schema_ref": _nullable(_string(maximum=256)),
            "media_type": _enum("application/pdf", "application/json"),
            "bytes": {"type": "integer", "minimum": 1, "maximum": 1073741824},
        }
    )
    defs["OriginalPointer"] = pointer
    defs["DocumentReference"] = _object(
        {
            "source_kind": {"const": "DOCUMENT_REVISION"},
            "source_class": {"const": "TEXTBOOK"},
            "document_id": _id("edudoc"),
            "document_revision_id": _id("edudocrev"),
            "artifact_member": _ref("OriginalPointer"),
            "first_physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
            "last_physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
        }
    )
    defs["DocumentReference"]["properties"]["artifact_member"] = {
        "allOf": [
            _ref("OriginalPointer"),
            {
                "properties": {
                    "media_type": {"const": "application/pdf"},
                    "schema_ref": {"const": "eom://schemas/educational-document/pdf-source/1.0"},
                }
            },
        ]
    }
    defs["IntakeReference"] = _object(
        {
            "source_kind": {"const": "CONTENT_INTAKE_FILE"},
            "source_class": _enum("TEXTBOOK", "PAST_EXAM"),
            "source_file_id": _id("sourcefile"),
            "artifact_member": _ref("OriginalPointer"),
        }
    )
    defs["ItemReference"] = _object(
        {
            "source_kind": {"const": "APPROVED_ITEM_REVISION"},
            "source_class": _enum("PAST_EXAM", "APPROVED_ITEM"),
            "item_id": _id("item"),
            "item_revision_id": _id("itemrev"),
            "artifact_member": _ref("OriginalPointer"),
        }
    )
    defs["ItemReference"]["properties"]["artifact_member"] = {
        "allOf": [
            _ref("OriginalPointer"),
            {"properties": {"media_type": {"const": "application/json"}}},
        ]
    }
    defs["SourceReference"] = {
        "oneOf": [_ref(name) for name in ("DocumentReference", "IntakeReference", "ItemReference")]
    }
    defs["Anchor"] = _object(
        {
            "anchor_id": _string(maximum=96),
            "artifact_revision_id": _id("rev"),
            "member_path": copy.deepcopy(artifact["properties"]["member_path"]),
            "locator": _string(maximum=256),
            "excerpt_sha256": _old("Hash"),
        }
    )
    defs["Reference"] = _object(
        {
            "source": _ref("SourceReference"),
            "analysis_run_id": _id("analysisrun"),
            "accepted_result": {
                "allOf": [
                    {"$ref": ARTIFACT},
                    {
                        "properties": {
                            "media_type": {"const": "application/json"},
                            "member_path": {"const": "evidence/accepted-result.json"},
                            "schema_ref": {
                                "pattern": r"^eom://schemas/knowledge/knowledge-analysis-result/(?:[2-9]|10)\.0$"
                            },
                        }
                    },
                ]
            },
            "analysis_member": {
                "allOf": [
                    {"$ref": ARTIFACT},
                    {
                        "properties": {
                            "media_type": {"const": "text/markdown"},
                            "schema_ref": {
                                "const": "eom://schemas/knowledge/normalized-markdown/1.0"
                            },
                        }
                    },
                ]
            },
            "anchors": _array(_ref("Anchor"), 32, minimum=1, unique=True),
            "graph_node_ids": _array(_string(maximum=72), 32, minimum=1, unique=True),
        }
    )
    defs["Source"] = _object(
        {
            "key": _string(pattern="^R[1-3]$"),
            "reference": _ref("Reference"),
            "display_name": _string(maximum=256),
            "location": _string(maximum=256),
            "text_kind": {"const": "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"},
            "text": _string(pattern=r"\S", maximum=6000),
        }
    )
    defs["Context"] = _object(
        {
            "schema_version": {"const": "chat-rag-context/1.0"},
            "scope": _ref("Scope"),
            "sources": _array(_ref("Source"), 3, minimum=1),
            "limitations": _array(_string(maximum=256), 12, unique=True),
            "context_sha256": _old("Hash"),
        }
    )
    defs["Arguments"] = _object(
        {
            "terms": _array(
                _string(pattern="^[a-z0-9가-힣_]+$", maximum=128), 8, minimum=1, unique=True
            ),
            "source_classes": _array(
                _enum("TEXTBOOK", "PAST_EXAM", "APPROVED_ITEM"), 3, minimum=1, unique=True
            ),
        }
    )
    defs["Arguments"]["properties"]["terms"]["items"]["minLength"] = 2
    # A second RAG read extends immutable R keys, never retargets an existing citation.
    defs["CatalogRequest"] = _object(
        {
            "schema_version": {"const": "chat-rag-catalog-request/1.0"},
            "operation": {"const": "CHAT_RAG"},
            "actor_id": _id("operator"),
            "command": {
                "oneOf": [
                    _object(
                        {
                            "action": {"const": "PREPARE_CHAT_RAG"},
                            "snapshot": _nullable(_old("Snapshot")),
                            "policy": _ref("Policy"),
                        }
                    ),
                    _object(
                        {
                            "action": {"const": "RETRIEVE_CHAT_RAG"},
                            "scope": _ref("Scope"),
                            "arguments": _ref("Arguments"),
                            "prior_context": _nullable(_ref("Context")),
                        }
                    ),
                    _object(
                        {"action": {"const": "AUTHORIZE_CHAT_RAG"}, "context": _ref("Context")}
                    ),
                ]
            },
        }
    )
    defs["Error"] = _enum(
        "CHAT_KNOWLEDGE_FORBIDDEN",
        "CHAT_KNOWLEDGE_UNAVAILABLE",
        "CHAT_KNOWLEDGE_POINTER_INVALID",
        "CHAT_KNOWLEDGE_QUERY_INVALID",
        "CHAT_KNOWLEDGE_READ_LIMIT",
        "CHAT_KNOWLEDGE_NOT_OFFERED",
    )
    defs["CatalogReply"] = _object(
        {
            "schema_version": {"const": "chat-rag-catalog-reply/1.0"},
            "operation": {"const": "CHAT_RAG"},
            "status": _enum("SUCCEEDED", "EMPTY", "FAILED"),
            "scope": _nullable(_ref("Scope")),
            "context": _nullable(_ref("Context")),
            "error_code": _nullable(_ref("Error")),
        }
    )
    defs["CatalogReply"]["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "FAILED"}}},
            "then": {
                "properties": {
                    "scope": {"type": "null"},
                    "context": {"type": "null"},
                    "error_code": _ref("Error"),
                }
            },
            "else": {"properties": {"scope": _ref("Scope"), "error_code": {"type": "null"}}},
        },
        {
            "if": {"properties": {"status": {"const": "EMPTY"}}},
            "then": {"properties": {"context": {"type": "null"}}},
        },
    ]
    tool = copy.deepcopy(agent["$defs"]["Request"])
    tool["properties"]["schema_version"] = {"const": "general-chat-tool-request/2.0"}
    tool["properties"]["sequence"]["maximum"] = 7
    tool["properties"]["command"]["oneOf"].append(
        _object(
            {
                "action": {"const": "RAG"},
                "arguments": _ref("Arguments"),
            }
        )
    )
    defs["Request"] = tool
    outcome = copy.deepcopy(agent["$defs"]["Outcome"])
    outcome["properties"]["rag_context"] = _nullable(_ref("Context"))
    outcome["required"].append("rag_context")
    defs["Outcome"] = outcome
    defs["Record"] = _object(
        {
            "schema_version": {"const": "general-chat-tool-record/2.0"},
            "request": _ref("Request"),
            "outcome": _ref("Outcome"),
        }
    )
    defs["Reply"] = _object(
        {
            "schema_version": {"const": "general-chat-tool-reply/2.0"},
            "record": _ref("Record"),
            "pointer": {"$ref": ARTIFACT},
        }
    )
    section = copy.deepcopy(grounding["$defs"]["Section"])
    section["properties"]["citation_keys"]["maxItems"] = 12
    section["properties"]["citation_keys"]["items"]["pattern"] = "^(S[1-9]|R[1-3])$"
    defs["Section"] = section
    answer = copy.deepcopy(grounding["$defs"]["Answer"])
    answer["properties"]["answer_sections"]["items"] = _ref("Section")
    defs["Answer"] = answer
    for name in ("Input", "Result"):
        value = copy.deepcopy(agent["$defs"][name])
        value["properties"]["protocol_version"] = {"const": "general-chat-turn/4.0"}
        value["properties"]["prompt_revision"] = {"const": "general-chat-rag-agent/1.0.0"}
        if name == "Input":
            value["properties"].update(
                rag_scope=_nullable(_ref("Scope")), rag_knowledge=_nullable(_ref("Context"))
            )
            value["required"].extend(("rag_scope", "rag_knowledge"))
        else:
            value["properties"]["answer"] = _nullable(_ref("Answer"))
            value["allOf"][0]["then"]["properties"]["answer"] = _ref("Answer")
            value["properties"]["tool_records"] = _array(
                {
                    "allOf": [
                        {"$ref": ARTIFACT},
                        {
                            "properties": {
                                "schema_ref": {"const": PREFIX + "tool-record/2.0"},
                                "member_path": {"const": "chat/evidence.json"},
                                "media_type": {"const": "application/json"},
                            }
                        },
                    ]
                },
                7,
                unique=True,
            )
        defs[name] = value
    receipt = copy.deepcopy(grounding["$defs"]["Receipt"])
    _externalize(receipt, PREFIX + "grounding/1.0")
    receipt["properties"]["schema_version"] = {"const": "chat-knowledge-citation-receipt/2.0"}
    receipt["properties"]["used_source_keys"] = _array(
        _string(pattern="^(S[1-9]|R[1-3])$"), 12, unique=True
    )
    receipt["properties"]["verified_rag_references"] = _array(_ref("Reference"), 3, unique=True)
    receipt["required"].append("verified_rag_references")
    defs["Receipt"] = receipt
    card = copy.deepcopy(grounding["$defs"]["SourceCard"])
    _externalize(card, PREFIX + "grounding/1.0")
    defs["SourceCard"] = {
        "oneOf": [
            card,
            _object(
                {
                    "key": _string(pattern="^R[1-3]$"),
                    "reference": _ref("Reference"),
                    "display_name": _string(maximum=256),
                    "kind": {"const": "RAG_ANALYSIS"},
                    "approval": {"const": "APPROVED"},
                    "location": _string(maximum=256),
                    "text_kind": {"const": "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"},
                }
            ),
        ]
    }
    view = copy.deepcopy(grounding["$defs"]["TurnView"])
    view["properties"]["sources"] = _array(_ref("SourceCard"), 12)
    view["properties"]["receipt"] = _nullable({"oneOf": [_old("Receipt"), _ref("Receipt")]})
    defs["TurnView"] = view
    views = copy.deepcopy(grounding["$defs"]["Views"])
    views["properties"]["values"]["items"] = _ref("TurnView")
    defs["Views"] = views
    output: dict[str, Schema] = {
        "general-chat-rag.schema.json": {
            "$schema": DRAFT,
            "$id": RAG,
            "title": (
                "CHAT-RAG-2 immutable textbook/Item evidence and bounded native read contracts"
            ),
            "$defs": defs,
        }
    }
    for leaf, name in (("turn-input", "Input"), ("turn-result", "Result")):
        output[f"general-chat-{leaf}-v4.schema.json"] = {
            "$schema": DRAFT,
            "$id": PREFIX + leaf + "/4.0",
            "$ref": _ref(name)["$ref"],
        }
    for leaf in (
        "worker-policy",
        "worker-request",
        "worker-reply",
        "dispatch",
        "owner-request",
        "owner-reply",
    ):
        version = 3 if (BASE / f"general-chat-{leaf}-v3.schema.json").exists() else 2
        value = json.loads((BASE / f"general-chat-{leaf}-v{version}.schema.json").read_bytes())
        value["$id"] = PREFIX + leaf + "/4.0"
        value["properties"]["schema_version"] = {"const": f"general-chat-{leaf}/4.0"}
        if leaf == "worker-policy":
            value["properties"]["rag_prompt_sha256"] = _old("Hash")
            value["required"].append("rag_prompt_sha256")
        _extend_envelope(value)
        output[f"general-chat-{leaf}-v4.schema.json"] = value
    return output


def _extend_envelope(value: Any) -> None:
    """V4 receivers preserve V1-V3 histories and add exactly the new input/result/views."""
    if isinstance(value, dict):
        if value.get("$ref") == PREFIX + "worker-policy/3.0":
            value["$ref"] = PREFIX + "worker-policy/4.0"
        if value.get("$ref") == PREFIX + "grounding/1.0#/$defs/Views":
            value["$ref"] = _ref("Views")["$ref"]
        for field in ("oneOf", "anyOf"):
            options = value.get(field)
            if isinstance(options, list):
                refs = {choice.get("$ref") for choice in options if isinstance(choice, dict)}
                for leaf in ("turn-input", "turn-result"):
                    predecessor = PREFIX + leaf + "/3.0"
                    successor = PREFIX + leaf + "/4.0"
                    if predecessor in refs and successor not in refs:
                        options.append({"$ref": successor})
        enums = value.get("enum")
        if isinstance(enums, list) and PREFIX + "turn-input/3.0" in enums:
            enums.append(PREFIX + "turn-input/4.0")
        for child in value.values():
            _extend_envelope(child)
    elif isinstance(value, list):
        for child in value:
            _extend_envelope(child)


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
                    raise SystemExit("Chat RAG schema drift: " + str(target))
            else:
                target.write_bytes(payload)


if __name__ == "__main__":
    main()
