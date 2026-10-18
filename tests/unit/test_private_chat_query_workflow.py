"""Pure synthetic completion provenance; no current source, native or Runner authority."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_service.embedding_encoder_adapter import encode_private_chat_query
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition_data
from eom_workflow.private_chat_query_workflow import (
    PRIVATE_CHAT_QUERY_RECEIPT_REF,
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowDefinition,
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_definition,
    validate_private_chat_query_step_output,
    validate_private_chat_query_workflow_receipt,
)
from eom_workflow.reference_query_execution import (
    parse_reference_query_step_output,
    parse_reference_query_workflow_receipt,
)
from eom_workflow.schemas import (
    PRIVATE_CHAT_QUERY_RUNNER_SCHEMA_RESOURCE,
    load_local_embedding_admission_schema,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_private_chat_query import backend
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_publication import launch_case
from tests.unit.test_private_chat_query_source import source_case
from tests.unit.test_reference_query_execution_contracts import pointer

ROOT = Path(__file__).resolve().parents[2]
FAILURES = (ValueError, SchemaError)


def definition_body():
    return {
        "schema_version": "1.3",
        "definition_key": "local-embedding-private-chat-query",
        "definition_version": "1.0.0",
        "start_step": "encode_private_chat_query",
        "limits": {"max_rework_cycles": 0, "max_step_attempts": 1},
        "steps": [
            {
                "key": "encode_private_chat_query",
                "type": "application",
                "operation": "BUILD_PRIVATE_CHAT_QUERY_EMBEDDINGS",
                "result_schema": "embedding-private-chat-query-result@1.0",
                "on_success": "complete",
            },
            {"key": "complete", "type": "terminal", "terminal_status": "COMPLETED"},
        ],
    }


@pytest.fixture
def completed():
    request, policy, bundle, native, launch = launch_case()
    from eom_workflow.private_chat_query_publication import validate_private_chat_query_launch

    record = validate_private_chat_query_launch(launch, request, policy, bundle, native)
    encoded = encode_private_chat_query(native, backend(native))
    result = encoded.result
    source = source_case(question=TEXT)
    origin = source.execution.materialize_live_private_query(source.ticket).origin.model_dump(
        mode="json"
    )
    origin["actor_id"] = request.operator_audit.operator_id
    origin["basis"] = native.basis.model_dump(mode="json")
    origin["ticket"]["conversation_id"] = native.basis.conversation_id
    origin["ticket"]["turn_id"] = native.basis.turn_id
    origin = ChatPrivateQueryOrigin.model_validate(seal(origin, "origin_sha256"))
    result_member = pointer(
        "result.json",
        "eom://schemas/knowledge/embedding-private-chat-query-result/1.0",
        sha256_bytes(canonical_json_bytes(result)),
    )
    receipt = PrivateChatQueryWorkflowReceipt.model_validate(
        seal(
            {
                "schema_version": "private-chat-query-workflow-receipt/1.0",
                "purpose": "PRIVATE_CHAT_QUERY",
                "workflow_id": launch.workflow_id,
                "workflow_definition_sha256": request.workflow_definition_sha256,
                "workflow_request_sha256": request.request_sha256,
                "context_request_sha256": request.context_request.request_sha256,
                "origin_sha256": origin.origin_sha256,
                "step_run_id": launch.step_run_id,
                "step_key": "encode_private_chat_query",
                "attempt": 1,
                "receipt_owner_job_id": "job_" + "c" * 32,
                "query_artifact_owner_job_id": "job_" + "9" * 32,
                "native_launch_job_id": native.job_id,
                "launch_association_sha256": launch.association_sha256,
                "execution_result_schema": "embedding-private-chat-query-result@1.0",
                "execution_record": pointer(
                    "intent.json",
                    "eom://schemas/workflow/private-chat-query-execution-record/1.0",
                    sha256_bytes(canonical_json_bytes(record)),
                ).model_dump(mode="json"),
                "query_execution": {
                    "job_id": native.job_id,
                    "query_request_id": native.query_request_id,
                    "request_sha256": native.request_sha256,
                    "input_set_sha256": native.input_set_sha256,
                    "basis_sha256": native.basis.basis_sha256,
                    "result_member": result_member.model_dump(mode="json"),
                    "result_sha256": result.result_sha256,
                },
                "shard": pointer(
                    "shard.json",
                    "eom://schemas/knowledge/embedding-vector-shard/1.0",
                    sha256_bytes(canonical_json_bytes(result.shard)),
                ).model_dump(mode="json"),
                "binary": pointer(
                    "vectors.f32",
                    "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                    result.shard.binary.sha256,
                    media="application/octet-stream",
                ).model_dump(mode="json"),
                "runtime_bundle": request.runtime_bundle.model_dump(mode="json"),
                "resource_profile_sha256": request.resource_profile.resource_profile_sha256,
                "published_at": (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            },
            "receipt_sha256",
        )
    )
    expected = {
        "origin": origin,
        "workflow_id": launch.workflow_id,
        "step_run_id": launch.step_run_id,
        "query_artifact_owner_job_id": receipt.query_artifact_owner_job_id,
        "receipt_owner_job_id": receipt.receipt_owner_job_id,
    }
    output = PrivateChatQueryStepOutput.model_validate(
        seal(
            {
                "schema_version": "private-chat-query-step-output/1.0",
                "purpose": "PRIVATE_CHAT_QUERY",
                "workflow_id": launch.workflow_id,
                "step_run_id": launch.step_run_id,
                "step_key": "encode_private_chat_query",
                "attempt": 1,
                "receipt_owner_job_id": receipt.receipt_owner_job_id,
                "execution_result_schema": "embedding-private-chat-query-result@1.0",
                "receipt_schema": PRIVATE_CHAT_QUERY_RECEIPT_REF,
                "receipt": pointer(
                    "receipt.json",
                    PRIVATE_CHAT_QUERY_RECEIPT_REF,
                    sha256_bytes(canonical_json_bytes(receipt)),
                    seed="d",
                ).model_dump(mode="json"),
                "receipt_sha256": receipt.receipt_sha256,
            },
            "output_sha256",
        )
    )
    return SimpleNamespace(
        request=request,
        policy=policy,
        bundle=bundle,
        native=native,
        launch=launch,
        result=result,
        receipt=receipt,
        expected=expected,
        output=output,
    )


def check(value, receipt=None, **updates):
    validate_private_chat_query_workflow_receipt(
        value.receipt if receipt is None else receipt,
        value.request,
        value.policy,
        value.bundle,
        value.launch,
        value.native,
        value.result,
        **(value.expected | updates),
    )


def test_resource_is_closed_hash_pinned_and_mirrored():
    _, filename, schema_id, digest = PRIVATE_CHAT_QUERY_RUNNER_SCHEMA_RESOURCE
    raw = (ROOT / "schemas/workflow" / filename).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == digest
    schema = load_local_embedding_admission_schema("private-chat-runner")
    assert schema["$id"] == schema_id
    Draft202012Validator.check_schema(schema)
    for name in ("definition", "receipt", "step-output"):
        value = schema["$defs"][name]
        assert value["additionalProperties"] is False
        assert set(value["properties"]) == set(value["required"])


def test_fixed_definition_hash_and_exact_static_admission_not_runtime_authority(completed):
    definition = PrivateChatQueryWorkflowDefinition.model_validate(definition_body())
    assert PrivateChatQueryWorkflowDefinition.model_validate(definition) == definition
    request = type(completed.request).model_validate(
        seal(
            completed.request.model_dump(mode="json")
            | {
                "workflow_definition_sha256": sha256_bytes(canonical_json_bytes(definition)),
            },
            "request_sha256",
        )
    )
    validate_private_chat_query_definition(definition, request)
    with pytest.raises(ValueError, match="DEFINITION_MISMATCH"):
        validate_private_chat_query_definition(definition, completed.request)
    assert workflow_definition_is_admitted(definition.definition_key, definition.definition_version)
    compiled = compile_definition_data(definition_body(), "synthetic-private-definition", set())
    assert compiled.definition == definition
    assert compiled.sha256 == request.workflow_definition_sha256


@pytest.mark.parametrize(
    "fault",
    [
        "role",
        "operation",
        "target",
        "result",
        "limits",
        "bool",
        "order",
        "extra",
        "third_step",
        "terminal",
        "copied",
    ],
)
def test_private_graph_is_fixed_without_executable_or_role_overrides(fault):
    body = definition_body()
    if fault == "role":
        body["steps"][0]["worker_role"] = "authoring"
    elif fault == "operation":
        body["steps"][0]["operation"] = "BUILD_REFERENCE_QUERY_EMBEDDINGS"
    elif fault == "target":
        body["steps"][0]["on_success"] = "encode_private_chat_query"
    elif fault == "result":
        body["steps"][0]["result_schema"] = "embedding-reference-query-result@1.0"
    elif fault == "limits":
        body["limits"]["max_step_attempts"] = 2
    elif fault == "bool":
        body["limits"]["max_rework_cycles"] = False
    elif fault == "order":
        body["steps"].reverse()
    elif fault == "extra":
        body["authority"] = "ADMIN"
    elif fault == "third_step":
        body["steps"].append(deepcopy(body["steps"][1]))
    elif fault == "terminal":
        body["steps"][1]["terminal_status"] = "FAILED"
    else:
        value = PrivateChatQueryWorkflowDefinition.model_validate(body)
        body = value.model_copy(
            update={"limits": value.limits.model_copy(update={"max_step_attempts": True})}
        )
    with pytest.raises(FAILURES):
        PrivateChatQueryWorkflowDefinition.model_validate(body)


def test_private_receipt_and_output_roundtrip_are_pointer_only_and_previous_parsers_reject(
    completed,
):
    check(completed)
    validate_private_chat_query_step_output(completed.output, completed.receipt)
    for value in (completed.receipt, completed.output):
        assert type(value).model_validate(value) == value
        assert type(value).model_validate_json(canonical_json_bytes(value)) == value
        assert TEXT.encode() not in canonical_json_bytes(value)
        assert b'"input.json"' not in canonical_json_bytes(value)
    with pytest.raises(ValueError):
        parse_reference_query_workflow_receipt(completed.receipt)
    with pytest.raises(ValueError):
        parse_reference_query_step_output(completed.output)


@pytest.mark.parametrize(
    "field",
    [
        "workflow_definition_sha256",
        "workflow_request_sha256",
        "context_request_sha256",
        "origin_sha256",
        "launch_association_sha256",
        "resource_profile_sha256",
        "query_artifact_owner_job_id",
        "receipt_owner_job_id",
        "workflow_id",
        "step_run_id",
    ],
)
def test_resealed_receipt_cannot_change_original_expectations(completed, field):
    body = completed.receipt.model_dump(mode="json")
    body[field] = (
        body[field].split("_")[0] + "_" + "f" * 32
        if not field.endswith("sha256")
        else "sha256:" + "f" * 64
    )
    changed = PrivateChatQueryWorkflowReceipt.model_validate(seal(body, "receipt_sha256"))
    with pytest.raises(ValueError, match="PROVENANCE_INVALID"):
        check(completed, changed)


@pytest.mark.parametrize("field", ["execution_record", "shard", "binary"])
@pytest.mark.parametrize("fault", ["path", "schema", "media", "revision", "hash"])
def test_wrong_or_foreign_files_are_not_an_accepted_publication(completed, field, fault):
    body = completed.receipt.model_dump(mode="json")
    member = body[field]
    if fault == "path":
        member["member_path"] = "input.json"
    elif fault == "schema":
        member["schema_ref"] = "eom://schemas/workflow/reference-query-workflow-receipt/1.0"
    elif fault == "media":
        member["media_type"] = "text/plain"
    elif fault == "revision":
        member["artifact_revision_id"] = "rev_" + "f" * 32
    else:
        member["sha256"] = "sha256:" + "f" * 64
    with pytest.raises(FAILURES):
        check(
            completed, PrivateChatQueryWorkflowReceipt.model_validate(seal(body, "receipt_sha256"))
        )


@pytest.mark.parametrize(
    "fault", ["actor", "basis", "claim", "time", "raw_vs_semantic", "native_copy"]
)
def test_origin_raw_hash_time_and_unvalidated_native_boundaries(completed, fault):
    if fault in {"actor", "basis", "claim"}:
        body = completed.expected["origin"].model_dump(mode="json")
        if fault == "actor":
            body["actor_id"] = "operator_" + "f" * 32
        elif fault == "claim":
            body["ticket"]["claim_id"] = "chatclaim_" + "f" * 32
        else:
            basis = body["basis"]
            basis["message"]["artifact_revision_id"] = "rev_" + "f" * 32
            body["basis"] = seal(basis, "basis_sha256")
        origin = ChatPrivateQueryOrigin.model_validate(seal(body, "origin_sha256"))
        # Owner supplies the original expected origin; a carrier cannot retarget it.
        receipt = completed.receipt.model_dump(mode="json") | {
            "origin_sha256": origin.origin_sha256
        }
        changed = PrivateChatQueryWorkflowReceipt.model_validate(seal(receipt, "receipt_sha256"))
        with pytest.raises(ValueError):
            check(completed, changed)
        if fault != "claim":
            with pytest.raises(ValueError):
                check(completed, changed, origin=origin)
    elif fault == "native_copy":
        completed.native = completed.native.model_copy(
            update={
                "row": completed.native.row.model_copy(
                    update={"text": "PRIVATE-QUESTION-LEAK\u0000"}
                )
            }
        )
        with pytest.raises(ValueError) as caught:
            check(completed)
        assert "PRIVATE-QUESTION-LEAK" not in str(caught.value)
        assert caught.value.__suppress_context__
    else:
        receipt = completed.receipt.model_dump(mode="json")
        if fault == "time":
            receipt["published_at"] = (
                (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
            )
        else:
            receipt["query_execution"]["result_member"]["sha256"] = completed.result.result_sha256
        with pytest.raises(ValueError):
            check(
                completed,
                PrivateChatQueryWorkflowReceipt.model_validate(seal(receipt, "receipt_sha256")),
            )


@pytest.mark.parametrize(
    "field", ["workflow_id", "step_run_id", "receipt_owner_job_id", "receipt_sha256", "receipt"]
)
def test_step_output_requires_exact_receipt_not_just_valid_schema(completed, field):
    body = completed.output.model_dump(mode="json")
    if field == "receipt":
        body[field]["sha256"] = completed.receipt.receipt_sha256
    elif field.endswith("sha256"):
        body[field] = "sha256:" + "f" * 64
    else:
        body[field] = body[field].split("_")[0] + "_" + "f" * 32
    changed = PrivateChatQueryStepOutput.model_validate(seal(body, "output_sha256"))
    with pytest.raises(ValueError):
        validate_private_chat_query_step_output(changed, completed.receipt)


@pytest.mark.parametrize(
    "left,right",
    [
        ("receipt_owner_job_id", "query_artifact_owner_job_id"),
        ("receipt_owner_job_id", "native_launch_job_id"),
        ("query_artifact_owner_job_id", "native_launch_job_id"),
    ],
)
def test_three_actual_jobs_cannot_be_one_merged_producer(completed, left, right):
    body = completed.receipt.model_dump(mode="json")
    body[left] = body[right]
    with pytest.raises(ValueError):
        PrivateChatQueryWorkflowReceipt.model_validate(seal(body, "receipt_sha256"))


@pytest.mark.parametrize("field", ["artifact_id", "artifact_revision_id"])
def test_receipt_member_cannot_be_smuggled_into_four_member_numeric_file_set(completed, field):
    body = completed.output.model_dump(mode="json")
    body["receipt"][field] = getattr(completed.receipt.execution_record, field)
    output = PrivateChatQueryStepOutput.model_validate(seal(body, "output_sha256"))
    with pytest.raises(ValueError, match="OUTPUT_PROVENANCE_INVALID"):
        validate_private_chat_query_step_output(output, completed.receipt)
