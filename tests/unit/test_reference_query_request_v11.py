"""Input-only authoring reference successor; synthetic closure is not native admission."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import (
    ReferenceQueryWorkflowRequest,
    ReferenceQueryWorkflowRequestV11,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_workflow_request,
    parse_reference_query_workflow_request_v11,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_launch_association,
    validate_reference_query_request_references,
    validate_reference_query_step_output,
)
from eom_workflow import schemas as schema_owner
from eom_workflow.schemas import (
    ReferenceQueryContractError,
    load_reference_query_request_v11_schema,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_execution_contracts import case, checked_receipt

ROOT = Path(__file__).resolve().parents[2]


def test_closed_schema_mirror_hash_and_reused_predecessor_field_constraints():
    raw = (ROOT / "schemas/workflow/reference-query-workflow-request-v1_1.schema.json").read_bytes()
    mirror = (
        ROOT
        / "packages/workflow/eom_workflow/resources"
        / "reference-query-workflow-request-v1_1.schema.json"
    ).read_bytes()
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    assert raw == mirror
    assert sha256_bytes(raw) == schema_owner.REFERENCE_QUERY_REQUEST_V11_SCHEMA_RESOURCE[2]
    old_raw = (ROOT / "schemas/workflow/reference-query-execution-v1.schema.json").read_bytes()
    assert sha256_bytes(old_raw) == (
        "sha256:68e741506fec708956096aa5af6199e7c03821219385775cf9623aea88246c9b"
    )
    old = json.loads(old_raw)["$defs"]["request"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == old["required"]
    assert set(schema["properties"]) == set(old["properties"])
    for name, value in schema["properties"].items():
        if name not in {"schema_version", "context_request"}:
            assert value == {
                "$ref": "eom://schemas/workflow/reference-query-execution/1.0"
                + "#/$defs/request/properties/"
                + name
            }


@pytest.mark.parametrize("purpose", ("PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"))
def test_input_successor_reuses_exact_policy_launch_result_receipt_and_worker_contracts(purpose):
    value = case(consumer_purpose=purpose)
    raw = seal(
        value.request.model_dump(mode="json")
        | {"schema_version": "reference-query-workflow-request/1.1"},
        "request_sha256",
    )
    parsed = parse_reference_query_workflow_request_v11(raw)
    assert type(parsed) is ReferenceQueryWorkflowRequestV11
    assert isinstance(parsed, SupportedReferenceQueryWorkflowRequest)
    assert parse_supported_reference_query_workflow_request(parsed) == parsed
    with pytest.raises(ReferenceQueryContractError, match="CONTRACT_INVALID"):
        parse_reference_query_workflow_request(parsed)
    if purpose == "PAST_EXAM_VARIATION":
        # Existing producers retain request1.0 and original canonical bytes.
        assert type(value.request) is ReferenceQueryWorkflowRequest
        assert parse_supported_reference_query_workflow_request(value.request) == value.request
        assert canonical_json_bytes(value.request.model_dump(mode="json")) != canonical_json_bytes(
            raw
        )
    else:
        assert parsed == value.request
        validate_reference_query_request_references(parsed, value.policy, value.bundle)
        validate_reference_query_launch_association(
            value.launch, parsed, value.policy, value.bundle, value.native_input
        )
        checked_receipt(value, value.receipt)
        validate_reference_query_step_output(value.output, value.receipt)
        assert value.receipt.schema_version == "reference-query-workflow-receipt/1.0"
        assert value.result.schema_version == "embedding-reference-query-result/1.0"


@pytest.mark.parametrize(
    "fault",
    (
        "unknown_version",
        "old_version_with_new_purpose",
        "bool",
        "extra",
        "bad_hash",
        "unsupported_consumer",
        "private_basis",
        "wrong_policy_schema",
        "raw_model_copy",
    ),
)
def test_fixed_supported_parser_rejects_foreign_versions_authority_and_forged_nested_values(fault):
    value = case(consumer_purpose="ITEM_AUTHORING").request
    raw = value.model_dump(mode="json")
    if fault == "unknown_version":
        raw["schema_version"] = "reference-query-workflow-request/1.2"
    elif fault == "old_version_with_new_purpose":
        raw["schema_version"] = "reference-query-workflow-request/1.0"
    elif fault == "bool":
        raw["context_request"]["top_k"] = True
        raw["context_request"] = seal(raw["context_request"], "request_sha256")
    elif fault == "extra":
        raw["runtime_authority"] = "ADMIN"
    elif fault == "bad_hash":
        raw["request_sha256"] = "sha256:" + "f" * 64
    elif fault == "unsupported_consumer":
        raw["context_request"]["consumer_purpose"] = "GENERAL_CHAT_READ"
        raw["context_request"] = seal(raw["context_request"], "request_sha256")
    elif fault == "private_basis":
        raw["context_request"]["anchor"]["basis"] = "PRIVATE_AUTHORING_RESULT"
        raw["context_request"] = seal(raw["context_request"], "request_sha256")
    elif fault == "wrong_policy_schema":
        raw["native_execution_policy"]["schema_ref"] = "eom://schemas/workflow/unknown/1.0"
    elif fault == "raw_model_copy":
        raw = value.model_copy(update={"resource_profile": {"device": "CUDA", "authority": True}})
    if isinstance(raw, dict) and fault != "bad_hash":
        raw = seal(raw, "request_sha256")
    with pytest.raises(ReferenceQueryContractError, match="CONTRACT_INVALID"):
        parse_supported_reference_query_workflow_request(raw)


def test_new_resource_mutation_does_not_change_pinned_parser_or_old_request_path(monkeypatch):
    schema = load_reference_query_request_v11_schema()
    schema["properties"]["schema_version"]["const"] = "forged"
    current = case(consumer_purpose="ITEM_REVIEW").request
    assert parse_reference_query_workflow_request_v11(current) == current
    legacy = case().request

    def missing():
        raise ReferenceQueryContractError("REFERENCE_QUERY_SCHEMA_UNAVAILABLE")

    monkeypatch.setattr(schema_owner, "_reference_query_request_v11_schema", missing)
    assert parse_reference_query_workflow_request(legacy) == legacy
    with pytest.raises(ReferenceQueryContractError, match="SCHEMA_UNAVAILABLE"):
        parse_reference_query_workflow_request_v11(current)


def test_purpose_change_cannot_reuse_original_native_launch_or_request_hash():
    old, current = case(), case(consumer_purpose="ITEM_AUTHORING")
    assert old.request.context_request.request_id == current.request.context_request.request_id
    assert old.request.request_sha256 != current.request.request_sha256
    assert (
        old.request.context_request.request_sha256 != current.request.context_request.request_sha256
    )
    assert old.policy == current.policy and old.bundle == current.bundle
    with pytest.raises(ValueError, match="launch differs"):
        validate_reference_query_launch_association(
            old.launch, current.request, current.policy, current.bundle, current.native_input
        )
    assert (
        current.native_input.context_request_sha256
        == current.request.context_request.request_sha256
    )
    assert content_sha256(current.request.model_dump(mode="json", exclude={"request_sha256"})) == (
        current.request.request_sha256
    )


@pytest.mark.parametrize("fault", ("copied_extra", "cyclic_value"))
def test_raw_contract_failures_remain_stable_before_native_or_source_work(fault):
    value = case(consumer_purpose="ITEM_REVIEW").request
    if fault == "copied_extra":
        raw = value.model_copy(update={"invented_authority": "ADMIN"})
    else:
        raw = value.model_dump(mode="json")
        raw["unexpected_cycle"] = raw
    with pytest.raises(ReferenceQueryContractError, match="REFERENCE_QUERY_CONTRACT_INVALID"):
        parse_supported_reference_query_workflow_request(raw)
