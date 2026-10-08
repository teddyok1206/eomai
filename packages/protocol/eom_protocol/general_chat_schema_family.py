"""Closed successor schema selection; released V1 validators remain authoritative."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


@lru_cache(maxsize=12)
def chat_family_validator(leaf: str, version: int) -> Draft202012Validator:
    if leaf not in {
        "worker-policy",
        "worker-request",
        "worker-reply",
        "dispatch",
        "owner-request",
        "owner-reply",
    } or version not in {1, 2}:
        raise ValueError("unsupported chat envelope")
    root = files("eom_protocol").joinpath("schemas")
    registry: Registry = Registry()
    for name in (
        "artifact-member-v1",
        "general-chat-views",
        "general-chat-turn-input",
        "general-chat-turn-result",
        "general-chat-worker-ticket",
        "general-chat-worker-policy",
        "general-chat-worker-policy-v2",
        "general-chat-grounding",
        "general-chat-turn-input-v2",
        "general-chat-turn-result-v2",
    ):
        schema = json.loads(root.joinpath(name + ".schema.json").read_bytes())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    document = json.loads(
        root.joinpath(
            "general-chat-" + leaf + ("-v2" if version == 2 else "") + ".schema.json"
        ).read_bytes()
    )
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document, registry=registry)


def validate_chat_envelope(leaf: str, document: object) -> None:
    version = (
        2
        if isinstance(document, dict)
        and document.get("schema_version") == "general-chat-" + leaf + "/2.0"
        else 1
    )
    chat_family_validator(leaf, version).validate(document)
