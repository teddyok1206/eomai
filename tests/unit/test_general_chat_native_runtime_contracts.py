"""Additive runtime provenance contracts; no native process or inference."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import CHAT_MEMBER
from eom_protocol.general_chat_dispatch import (
    ChatDispatchReceipt,
    ChatExecutionIdentity,
    read_chat_dispatch,
)
from eom_protocol.general_chat_rag_turn import RAG_INPUT_SCHEMA
from eom_protocol.general_chat_schema_family import chat_family_validator, validate_chat_envelope
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerPolicy,
    CodexCliIdentity,
    chat_worker_protocol_version,
    chat_worker_ticket,
    read_chat_worker_policy,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.general_chat_rag_fixtures import HASH, request

ROOT = Path(__file__).resolve().parents[2]
LEGACY_PROFILE = "codex-app-server/0.160.0/environment-free/1.0"
PROFILE = "codex-app-server/environment-free/2.0"
LEGACY_SCHEMA_HASHES = {
    "general-chat-worker-policy.schema.json": (
        "00b73f45c5bd7a4a3f56c6167a5d0dfa2c96fa0abaefe7d284f7e523d96c916e"
    ),
    "general-chat-worker-policy-v2.schema.json": (
        "be05738c29b0c34954548711809992f93d2e090fd0cdb2d27b71bdc9ecc3e53d"
    ),
    "general-chat-worker-policy-v3.schema.json": (
        "66469c1ef1fd89024c99c2806849660dcb535f647c8d468f36c50f275edbddb8"
    ),
    "general-chat-worker-policy-v4.schema.json": (
        "cf65fe9b388454f197526a842383d32e259db587a6d12117b5b8e3df04e978c7"
    ),
    "general-chat-dispatch.schema.json": (
        "1bfa70a374b2e1f44bdc893a9e3fc72cdc9b32108685bc3b7906bfc317ad011e"
    ),
    "general-chat-dispatch-v2.schema.json": (
        "6aae24b836140b3e98773ccb96c83b0bccfbc113c3452a0900d6c39345702e88"
    ),
    "general-chat-dispatch-v3.schema.json": (
        "eec85ee9df633a402ea46615bb9413946dd04838df95ef26e36d0e3cd69e9649"
    ),
    "general-chat-dispatch-v4.schema.json": (
        "6670dfe26b61ca91f371f76f6dd4dff7b7ef1304ae2127bdd788bccbb44054a3"
    ),
}


def runtime_document() -> dict[str, str]:
    return {
        "cli_version": "0.162.1",
        "cli_launcher_sha256": "sha256:" + "b" * 64,
        "cli_binary_sha256": "sha256:" + "c" * 64,
    }


def policy_document(version: int = 5) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": f"general-chat-worker-policy/{version}.0",
        "model": "synthetic-model",
        "native_profile": PROFILE if version == 5 else LEGACY_PROFILE,
        "prompt_revision": "general-chat/1.0.0",
        "prompt_sha256": HASH,
    }
    if version >= 2:
        value["grounded_prompt_sha256"] = HASH
    if version >= 3:
        value["agent_prompt_sha256"] = HASH
    if version >= 4:
        value["rag_prompt_sha256"] = HASH
    if version == 5:
        value["native_runtime"] = runtime_document()
    return value


def runtime_policy() -> ChatWorkerPolicy:
    return read_chat_worker_policy(policy_document())


def dispatch_document() -> dict[str, Any]:
    prepared, policy = request(), runtime_policy()
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path=CHAT_MEMBER,
        schema_ref=RAG_INPUT_SCHEMA,
        media_type="application/json",
        sha256=sha256_bytes(canonical_json_bytes(prepared.model_dump(mode="json"))),
    )
    return ChatDispatchReceipt(
        schema_version="general-chat-dispatch/5.0",
        runtime_id="chatrt_" + "d" * 32,
        identity=ChatExecutionIdentity(boot_id="chatboot_" + "e" * 32, policy=policy),
        ticket=chat_worker_ticket(prepared, policy_sha256=policy.sha256),
        input=pointer,
    ).model_dump(mode="json")


@pytest.mark.parametrize("leaf,digest", tuple(LEGACY_SCHEMA_HASHES.items()))
def test_released_policy_and_dispatch_bytes_remain_exact(leaf: str, digest: str) -> None:
    canonical = (ROOT / "schemas/general-chat" / leaf).read_bytes()
    assert sha256_bytes(canonical) == "sha256:" + digest
    assert canonical == (ROOT / "packages/protocol/eom_protocol/schemas" / leaf).read_bytes()


@pytest.mark.parametrize("leaf", ("worker-policy", "dispatch"))
def test_new_schemas_are_mirrored_closed_202012_and_valid_offline(leaf: str) -> None:
    file_name = f"general-chat-{leaf}-v5.schema.json"
    canonical = (ROOT / "schemas/general-chat" / file_name).read_bytes()
    assert canonical == (ROOT / "packages/protocol/eom_protocol/schemas" / file_name).read_bytes()
    schema = json.loads(canonical)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    Draft202012Validator.check_schema(schema)
    validate_chat_envelope(
        leaf, policy_document() if leaf == "worker-policy" else dispatch_document()
    )


@pytest.mark.parametrize("version,transport", ((1, 1), (2, 2), (3, 3), (4, 4), (5, 4)))
def test_policy_revision_maps_explicitly_without_changing_old_serialization(
    version: int, transport: int
) -> None:
    document = policy_document(version)
    policy = read_chat_worker_policy(document)
    assert chat_worker_protocol_version(policy) == transport
    assert policy.model_dump(mode="json") == document
    assert policy.sha256 == sha256_bytes(canonical_json_bytes(document))
    assert ("native_runtime" in document) == (version == 5)


@pytest.mark.parametrize("field", tuple(policy_document()))
def test_v5_wire_requires_every_selected_runtime_and_prompt_field(field: str) -> None:
    document = policy_document()
    del document[field]
    with pytest.raises(SchemaError):
        read_chat_worker_policy(document)


@pytest.mark.parametrize(
    "field",
    ("native_runtime", "grounded_prompt_sha256", "agent_prompt_sha256", "rag_prompt_sha256"),
)
def test_v5_pydantic_cannot_invent_missing_runtime_or_prompt_pins(field: str) -> None:
    document = policy_document()
    del document[field]
    with pytest.raises(ValidationError):
        ChatWorkerPolicy.model_validate(document)


@pytest.mark.parametrize("field", tuple(runtime_document()))
def test_runtime_identity_has_no_missing_field_fallback(field: str) -> None:
    document = policy_document()
    del document["native_runtime"][field]
    with pytest.raises(SchemaError):
        read_chat_worker_policy(document)
    with pytest.raises(ValidationError):
        CodexCliIdentity.model_validate(document["native_runtime"])


@pytest.mark.parametrize("field", ("cli_launcher_sha256", "cli_binary_sha256"))
@pytest.mark.parametrize(
    "value",
    ("a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63, HASH + "\n", None, 123),
)
def test_native_hashes_are_exact_prefixed_lowercase_sha256(field: str, value: object) -> None:
    document = policy_document()
    document["native_runtime"][field] = value
    with pytest.raises(SchemaError):
        read_chat_worker_policy(document)
    with pytest.raises(ValidationError):
        CodexCliIdentity.model_validate(document["native_runtime"])


@pytest.mark.parametrize("value", ("latest", "v0.162.1", "0.162", "0.162.1-alpha", "", None, 123))
def test_runtime_version_is_an_explicit_numeric_identity_not_an_alias(value: object) -> None:
    document = policy_document()
    document["native_runtime"]["cli_version"] = value
    with pytest.raises(SchemaError):
        read_chat_worker_policy(document)
    with pytest.raises(ValidationError):
        CodexCliIdentity.model_validate(document["native_runtime"])


@pytest.mark.parametrize("version", ("0.160.0", "0.162.1", "42.123.456"))
def test_runtime_type_is_not_a_source_level_cli_version_allowlist(version: str) -> None:
    document = policy_document()
    document["native_runtime"]["cli_version"] = version
    selected = read_chat_worker_policy(document).native_runtime
    assert selected is not None and selected.cli_version == version


@pytest.mark.parametrize("version", (1, 2, 3, 4))
@pytest.mark.parametrize("mutation", ("runtime", "profile"))
def test_legacy_policy_cannot_silently_adopt_new_runtime_meaning(
    version: int, mutation: str
) -> None:
    document = policy_document(version)
    if mutation == "runtime":
        document["native_runtime"] = runtime_document()
    else:
        document["native_profile"] = PROFILE
    with pytest.raises(SchemaError):
        read_chat_worker_policy(document)
    with pytest.raises(ValidationError):
        ChatWorkerPolicy.model_validate(document)


@pytest.mark.parametrize("section", ("policy", "native_runtime"))
@pytest.mark.parametrize("field", ("auth", "operator_id", "native_thread_id", "nas_path"))
def test_policy_identity_accepts_no_caller_authority_or_storage_handles(
    section: str, field: str
) -> None:
    document = policy_document()
    target = document if section == "policy" else document["native_runtime"]
    target[field] = "untrusted"
    with pytest.raises(SchemaError):
        read_chat_worker_policy(document)
    with pytest.raises(ValidationError):
        ChatWorkerPolicy.model_validate(document)


def test_runtime_and_policy_are_frozen_and_part_of_exact_policy_hash() -> None:
    policy = runtime_policy()
    assert policy.native_runtime is not None
    with pytest.raises(ValidationError):
        policy.native_runtime.cli_version = "0.163.0"
    with pytest.raises(ValidationError):
        policy.native_runtime = CodexCliIdentity.model_validate(runtime_document())
    document = policy_document()
    document["native_runtime"]["cli_binary_sha256"] = HASH
    assert read_chat_worker_policy(document).sha256 != policy.sha256


@pytest.mark.parametrize("leaf", ("worker-request", "worker-reply", "owner-request", "owner-reply"))
def test_v5_does_not_invent_unsupported_transport_families(leaf: str) -> None:
    with pytest.raises(ValueError, match="unsupported chat envelope"):
        chat_family_validator(leaf, 5)


def test_dispatch_v5_retains_v4_input_and_exact_runtime_policy_ticket() -> None:
    document = dispatch_document()
    original = deepcopy(document)
    receipt = read_chat_dispatch(document)
    assert receipt.model_dump(mode="json") == original
    assert receipt.input.schema_ref == RAG_INPUT_SCHEMA
    assert receipt.ticket.policy_sha256 == receipt.identity.policy.sha256
    assert receipt.identity.policy.native_runtime == CodexCliIdentity.model_validate(
        runtime_document()
    )
    assert set(receipt.model_dump(mode="json")) == set(original)


@pytest.mark.parametrize(
    "mutation", ("legacy_dispatch", "legacy_policy", "runtime", "input", "ticket")
)
def test_dispatch_v5_cannot_reinterpret_legacy_family_or_dangling_pins(mutation: str) -> None:
    document = dispatch_document()
    if mutation == "legacy_dispatch":
        document["schema_version"] = "general-chat-dispatch/4.0"
    elif mutation == "legacy_policy":
        document["identity"]["policy"] = policy_document(4)
    elif mutation == "runtime":
        document["identity"]["policy"]["native_runtime"]["cli_binary_sha256"] = HASH
    elif mutation == "input":
        document["input"]["schema_ref"] = "eom://schemas/general-chat/turn-input/3.0"
    else:
        document["ticket"]["policy_sha256"] = HASH
    with pytest.raises((SchemaError, ValidationError)):
        read_chat_dispatch(document)


@pytest.mark.parametrize(
    "schema_ref",
    (
        "eom://schemas/general-chat/turn-input/1.0",
        "eom://schemas/general-chat/turn-input/2.0",
        "eom://schemas/general-chat/turn-input/3.0",
    ),
)
def test_dispatch_v5_pydantic_requires_existing_rag_capability(schema_ref: str) -> None:
    document = dispatch_document()
    document["input"]["schema_ref"] = schema_ref
    with pytest.raises(ValidationError):
        ChatDispatchReceipt.model_validate(document)
