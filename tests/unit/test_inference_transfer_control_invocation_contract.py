"""Protocol-only preparation/release closure, with no real owner, DB, or model."""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.control_plane import FrozenModel
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, load_control_schema
from eom_workflow.inference_transfer_control_invocation import (
    InferenceTransferControlReleaseResult,
    InferenceTransferPreparedReceipt,
    parse_inference_transfer_prepared_receipt,
    parse_inference_transfer_release_request,
    parse_inference_transfer_release_result,
    validate_inference_transfer_release_result_context,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_control_invocation_fixtures import (
    prepared_receipt,
    rehash,
    release_request,
    release_result,
)

ROOT = Path(__file__).resolve().parents[2]


def test_schema_first_resource_mirror_and_raw_sha_are_exact() -> None:
    resource = CONTROL_SCHEMA_RESOURCES["inference-transfer-control-invocation"]
    source = (ROOT / resource.canonical_path).read_bytes()
    assert source == files("eom_workflow").joinpath(resource.resource_path).read_bytes()
    assert sha256_bytes(source) == resource.sha256
    schema = load_control_schema("inference-transfer-control-invocation")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_initial_preparation_explicit_release_roundtrip_is_not_educational_approval() -> None:
    receipt, query, result = prepared_receipt(), release_request(), release_result()
    assert parse_inference_transfer_prepared_receipt(receipt.model_dump(mode="json")) == receipt
    assert parse_inference_transfer_release_request(query.model_dump(mode="json")) == query
    assert parse_inference_transfer_release_result(result.model_dump(mode="json")) == result
    validate_inference_transfer_release_result_context(query, result)
    assert receipt.draft.state == "DRAFT" and result.preset.state == "RELEASED"
    assert receipt.draft.preset_id == result.preset.preset_id
    assert receipt.draft.preset_revision_id != result.preset.preset_revision_id
    assert result.quality_score_permille is None
    assert result.scientific_evaluation == result.human_transfer_evaluation == "NOT_EVALUATED"
    assert receipt.bootstrap_artifact.sha256 != receipt.manifest.manifest_sha256


def test_bootstrap_pointer_hashes_actual_newline_terminated_published_bytes() -> None:
    receipt = prepared_receipt()
    manifest = receipt.manifest.model_dump(mode="json")
    assert receipt.bootstrap_artifact.sha256 == sha256_bytes(canonical_json_bytes(manifest) + b"\n")
    assert receipt.bootstrap_artifact.sha256 != content_sha256(manifest)
    body = receipt.model_dump(mode="json")
    body["bootstrap_artifact"]["sha256"] = content_sha256(manifest)
    with pytest.raises(ValueError):
        parse_inference_transfer_prepared_receipt(rehash(body, "receipt_sha256"))


@pytest.mark.parametrize("value", (None, [], "not-json", 17))
def test_nonobject_invocation_is_explicitly_rejected(value: object) -> None:
    for parser in (
        parse_inference_transfer_prepared_receipt,
        parse_inference_transfer_release_request,
        parse_inference_transfer_release_result,
    ):
        with pytest.raises(ValueError):
            parser(value)


@pytest.mark.parametrize(
    "field", ("actor_id", "session_id", "token", "permissions", "released_at", "platform_payload")
)
def test_receipt_contains_no_caller_authority_clock_or_instruction_bytes(field: str) -> None:
    body = prepared_receipt().model_dump(mode="json") | {field: "forged"}
    with pytest.raises(SchemaError):
        parse_inference_transfer_prepared_receipt(rehash(body, "receipt_sha256"))


@pytest.mark.parametrize("phase", ("RECEIPT", "REQUEST", "RESULT"))
def test_outer_hash_tampering_is_rejected(phase: str) -> None:
    value: FrozenModel
    parser: Callable[[object], FrozenModel]
    if phase == "RECEIPT":
        value, parser, field = (
            prepared_receipt(),
            parse_inference_transfer_prepared_receipt,
            "receipt_sha256",
        )
    elif phase == "REQUEST":
        value, parser, field = (
            release_request(),
            parse_inference_transfer_release_request,
            "request_sha256",
        )
    else:
        value, parser, field = (
            release_result(),
            parse_inference_transfer_release_result,
            "result_sha256",
        )
    body = value.model_dump(mode="json") | {field: content_sha256("tampered")}
    with pytest.raises(ValueError):
        parser(body)


@pytest.mark.parametrize(
    "change",
    (
        "MANIFEST_HASH",
        "BOOTSTRAP_HASH",
        "BUNDLE_HASH",
        "BUNDLE_SCHEMA",
        "PRESET_HASH",
        "CAPACITY",
        "MODEL",
        "TIMEOUT",
        "BUNDLE_POLICY",
        "CREATED_AT",
        "STATE",
        "REVISION",
        "POOL",
        "ROLE",
        "PROTOCOL",
        "GENERAL",
    ),
)
def test_preparation_rejects_wrong_identity_review_or_dedicated_policy(change: str) -> None:
    body = prepared_receipt().model_dump(mode="json")
    draft = body["draft"]
    policy = draft["role_policies"][0]
    if change == "MANIFEST_HASH":
        body["manifest"]["manifest_sha256"] = content_sha256("tampered")
    elif change == "BOOTSTRAP_HASH":
        body["bootstrap_artifact"]["sha256"] = body["manifest"]["manifest_sha256"]
    elif change == "BUNDLE_HASH":
        body["instruction_bundle"]["manifest_sha256"] = content_sha256("foreign")
    elif change == "BUNDLE_SCHEMA":
        body["instruction_bundle"]["manifest_artifact"]["schema_ref"] = (
            "eom://schemas/workflow/other/1.0"
        )
    elif change == "PRESET_HASH":
        draft["content_sha256"] = content_sha256("tampered")
    elif change == "CAPACITY":
        draft["capacity_policy_revision_id"] = "capacityrev_" + "f" * 32
    elif change == "MODEL":
        policy["model_candidates"][0]["model"] = "unreviewed-other-model"
    elif change == "TIMEOUT":
        policy["timeout_seconds"] = 400
    elif change == "BUNDLE_POLICY":
        policy["instruction_bundle"]["bundle_revision_id"] = "instrrev_" + "f" * 32
    elif change == "CREATED_AT":
        draft["created_at"] = "2026-10-10T10:00:00Z"
    elif change == "STATE":
        draft["state"] = "RELEASED"
    elif change == "REVISION":
        draft["revision_number"] = 2
    elif change == "POOL":
        policy["worker_pool_key"] = "default"
    elif change == "ROLE":
        policy["role"] = "authoring"
    elif change == "PROTOCOL":
        draft["compatible_workflow_protocols"] = ["workflow-role/1.28.0"]
    else:
        draft["general_knowledge_policy"] = "ALLOW_WITH_PROVENANCE"
    if change != "PRESET_HASH":
        body["draft"] = rehash(draft, "content_sha256")
    with pytest.raises((ValueError, SchemaError)):
        parse_inference_transfer_prepared_receipt(rehash(body, "receipt_sha256"))


def test_copied_nested_preset_cannot_bypass_hash_or_policy_checks() -> None:
    original = prepared_receipt()
    copied = original.model_copy(
        update={
            "draft": original.draft.model_copy(
                update={"content_sha256": content_sha256("tampered")}
            )
        }
    )
    request = release_request()
    copied_request = request.model_copy(update={"receipt": copied})
    with pytest.raises(ValueError):
        validate_inference_transfer_release_result_context(copied_request, release_result())


@pytest.mark.parametrize(
    "field,value",
    (
        ("quality_score_permille", 999),
        ("scientific_evaluation", "PASS"),
        ("human_transfer_evaluation", "PASS"),
        ("executed_cases", []),
        ("executed_cases", ["DUPLICATE", "DUPLICATE"]),
        ("executed_cases", ["unsafe case\n"]),
        ("executed_cases", ["CASE" + str(n) for n in range(65)]),
    ),
)
def test_release_result_never_fabricates_quality_or_unbounded_case_claims(
    field: str, value: Any
) -> None:
    body = release_result().model_dump(mode="json") | {field: value}
    with pytest.raises((ValueError, SchemaError)):
        parse_inference_transfer_release_result(rehash(body, "result_sha256"))


@pytest.mark.parametrize(
    "change", ("RECEIPT", "LOGICAL_ID", "SAME_REVISION", "BEFORE_DRAFT", "MODEL", "DESCRIPTION")
)
def test_release_context_requires_exact_initial_prepared_policy(change: str) -> None:
    query = release_request()
    body = release_result(query).model_dump(mode="json")
    if change == "RECEIPT":
        body["prepared_receipt_sha256"] = content_sha256("other receipt")
    elif change == "LOGICAL_ID":
        body["preset"]["preset_id"] = "execpreset_" + "f" * 32
    elif change == "SAME_REVISION":
        body["preset"]["preset_revision_id"] = query.receipt.draft.preset_revision_id
    elif change == "BEFORE_DRAFT":
        body["preset"]["created_at"] = "2026-10-10T08:00:00Z"
    elif change == "MODEL":
        body["preset"]["role_policies"][0]["model_candidates"][0]["model"] = "other-valid-model"
    else:
        body["preset"]["description"] = "Changed executable purpose metadata."
    body["preset"] = rehash(body["preset"], "content_sha256")
    result = parse_inference_transfer_release_result(rehash(body, "result_sha256"))
    with pytest.raises(ValueError):
        validate_inference_transfer_release_result_context(query, result)


def test_receipt_and_result_are_frozen_small_metadata() -> None:
    receipt = prepared_receipt()
    with pytest.raises(ValueError):
        receipt.receipt_sha256 = content_sha256("modified")
    with pytest.raises(ValueError):
        receipt.draft.state = "RELEASED"  # type: ignore[assignment]
    body = release_result().model_dump(mode="json")
    body["evaluation_artifact"]["logical_name"] = "other.json"
    with pytest.raises((ValueError, SchemaError)):
        InferenceTransferControlReleaseResult.model_validate(rehash(body, "result_sha256"))
    body = receipt.model_dump(mode="json") | {"unexpected": "no dynamic registry"}
    with pytest.raises(ValueError):
        InferenceTransferPreparedReceipt.model_validate(rehash(body, "receipt_sha256"))


def test_canonical_control_byte_budget_is_applied_without_silent_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = prepared_receipt().model_dump(mode="json")
    monkeypatch.setattr(
        "eom_workflow.inference_transfer_control_invocation.MAX_TRANSFER_CONTROL_INVOCATION_BYTES",
        100,
    )
    with pytest.raises(ValueError, match="encoded byte budget"):
        parse_inference_transfer_prepared_receipt(receipt)
