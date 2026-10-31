"""Pure mixed carrier closures, never installed service/source/lease authority."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingInput
from eom_catalog_contracts.inference_transfer_experiment import experiment_view_text
from eom_catalog_contracts.mixed_embedding_index import (
    RegisteredReviewEmbeddingEntry,
    registered_review_embedding_text,
)
from eom_catalog_contracts.mixed_embedding_registry import (
    EmbeddingIndexRegistrationResultV2,
    RegisterEmbeddingIndexCommandV2,
)
from eom_catalog_service.local_embedding_source_plan_v2 import build_local_embedding_source_plan_v2
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobRequest,
    EmbeddingEncodingReadResult,
    LocalEmbeddingOwnedJob,
    parse_embedding_encoding_job_message,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    EmbeddingEncodingAttachedEventV2,
    EmbeddingEncodingCompletedEventV2,
    EmbeddingEncodingReadResultV2,
    LocalEmbeddingLaunchAssociationV2,
    LocalEmbeddingLaunchIntentV2,
    parse_embedding_encoding_ownership_v2,
    parse_supported_embedding_encoding_read,
    validate_embedding_encoding_completions_v2,
    validate_local_embedding_launch_association_v2,
    validate_supported_embedding_encoding_read,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingServiceExecutionPolicy
from eom_workflow.local_embedding_request import parse_local_embedding_executable_request
from eom_workflow.local_embedding_request_v2 import (
    parse_local_embedding_workflow_request_v2,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
    validate_local_embedding_request_references_v2,
)
from eom_workflow.local_embedding_workflow_receipt import (
    parse_local_embedding_step_output,
    parse_local_embedding_workflow_receipt,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V2_SCHEMA_REF,
    LocalEmbeddingStepOutputV2,
    LocalEmbeddingWorkflowReceiptV2,
    ResolvedNativeIndexCoverageV2,
    parse_local_embedding_step_output_v2,
    parse_local_embedding_workflow_receipt_v2,
    validate_local_embedding_step_output_v2,
    validate_local_embedding_workflow_receipt_v2,
)
from eom_workflow.schemas import (
    MIXED_NATIVE_WORKFLOW_SCHEMA_RESOURCES,
    LocalEmbeddingAdmissionContractError,
    load_local_embedding_admission_schema,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import embedding_input, embedding_result, seal
from tests.unit.local_embedding_admission_fixtures import member, native_fixture
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture
from tests.unit.test_embedding_index_assembly_v2 import assemble, pointer, rows_for
from tests.unit.test_local_embedding_source_plan_v2 import inputs


@lru_cache(maxsize=2)
def carrier_fixture(*, device="CPU") -> dict[str, Any]:
    original = (
        service_fixture()
        if device == "CPU"
        else service_fixture(base=native_fixture("a", "b", device=device, timeout_seconds=180))
    )
    query, resolved, bases = inputs("CONTENT_ONLY")
    space = original.base.plan.space
    query = replace(
        query, namespace=query.namespace.model_copy(update={"space_sha256": space.space_sha256})
    )
    resolved = replace(resolved, space=space)
    plan = build_local_embedding_source_plan_v2(
        query, resolved, target_revision_ids=tuple(bases), base_analysis_run_ids=bases
    )
    policy = LocalEmbeddingServiceExecutionPolicy.model_validate(
        seal(
            original.policy.model_dump(mode="json")
            | {"workflow_definition_sha256": "sha256:" + "8" * 64},
            "policy_sha256",
        )
    )
    request_body = original.request.model_dump(mode="json") | {
        "schema_version": "local-embedding-workflow-request/2.0",
        "workflow_definition_version": "2.0.0",
        "workflow_definition_sha256": policy.workflow_definition_sha256,
        **{
            field: getattr(plan, field).model_dump(mode="json")
            if hasattr(getattr(plan, field), "model_dump")
            else getattr(plan, field)
            for field in (
                "corpus_id",
                "graph_snapshot",
                "access_policy_revision_id",
                "access_policy_sha256",
                "namespace",
                "space",
            )
        },
        "source_plan": member(
            "source-plan.json",
            "eom://schemas/workflow/local-embedding-source-plan/2.0",
            plan.model_dump(mode="json"),
            "2",
        ).model_dump(mode="json"),
        "source_plan_sha256": plan.plan_sha256,
        "native_execution_policy": member(
            "policy.json",
            "eom://schemas/workflow/local-embedding-execution-policy/1.1",
            policy.model_dump(mode="json"),
            "3",
        ).model_dump(mode="json"),
        "native_execution_policy_sha256": policy.policy_sha256,
    }
    request = parse_local_embedding_workflow_request_v2(seal(request_body, "request_sha256"))
    texts = tuple(
        registered_review_embedding_text(entry, "CONTENT_ONLY")
        if isinstance(entry, RegisteredReviewEmbeddingEntry)
        else experiment_view_text(entry, "CONTENT_ONLY")
        for entry in resolved.entries
    )
    native_input = IncrementalEmbeddingInput.model_validate(
        seal(
            embedding_input(*(text for text in texts if text is not None), space=space).model_dump(
                mode="json"
            )
            | {
                "batch_size": request.resource_profile.batch_size,
                "threads": request.resource_profile.threads,
            },
            "request_sha256",
        )
    )
    jobs = []
    for old_job, row in zip(original.base.association.owned_jobs, native_input.rows, strict=True):
        job_request = EmbeddingEncodingJobRequest.model_validate(
            seal(
                old_job.request.model_dump(mode="json")
                | {"encoding": row.encoding.model_dump(mode="json")},
                "request_sha256",
            )
        )
        jobs.append(
            LocalEmbeddingOwnedJob.model_validate(
                {
                    "job_reference": old_job.job_reference.model_dump(mode="json")
                    | {"request_sha256": job_request.request_sha256},
                    "request": job_request.model_dump(mode="json"),
                }
            )
        )
    intent = LocalEmbeddingLaunchIntentV2.model_validate(
        seal(
            original.base.association.intent.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "intent_sha256",
        )
    )
    association = LocalEmbeddingLaunchAssociationV2.model_validate(
        seal(
            original.base.association.model_dump(mode="json")
            | {
                "schema_version": "embedding-encoding-ownership/2.0",
                "intent": intent.model_dump(mode="json"),
                "owned_jobs": [job.model_dump(mode="json") for job in jobs],
                "owned_input": member(
                    "input.json",
                    "eom://schemas/knowledge/incremental-embedding-input/1.0",
                    native_input.model_dump(mode="json"),
                    "7",
                ).model_dump(mode="json"),
                "owned_input_request_sha256": native_input.request_sha256,
                "owned_input_set_sha256": native_input.input_set_sha256,
            },
            "association_sha256",
        )
    )
    result = embedding_result(native_input)
    events = []
    for ordinal, (old_event, job) in enumerate(zip(original.base.completions, jobs, strict=True)):
        receipt_body = old_event.receipt.model_dump(mode="json") | {
            "result_manifest": member(
                "result.json",
                "eom://schemas/knowledge/incremental-embedding-result/1.0",
                result.model_dump(mode="json"),
            ).model_dump(mode="json"),
            "result_sha256": result.result_sha256,
            "shard_manifest": member(
                "shard.json",
                "eom://schemas/knowledge/embedding-vector-shard/1.0",
                result.shard.model_dump(mode="json"),
            ).model_dump(mode="json"),
            "shard_sha256": result.shard.shard_sha256,
        }
        receipt_body["binary_member"]["sha256"] = result.shard.binary.sha256
        receipt_body["row_ref"].update(
            shard_manifest=receipt_body["shard_manifest"],
            row_index=ordinal,
            encoding_sha256=job.request.encoding.encoding_sha256,
        )
        events.append(
            EmbeddingEncodingCompletedEventV2.model_validate(
                seal(
                    old_event.model_dump(mode="json")
                    | {
                        "schema_version": "embedding-encoding-ownership/2.0",
                        "owned_job": job.model_dump(mode="json"),
                        "intent": intent.model_dump(mode="json"),
                        "launch_association_sha256": association.association_sha256,
                        "receipt": seal(receipt_body, "receipt_sha256"),
                    },
                    "event_sha256",
                )
            )
        )
    old_receipt = receipt_fixture().receipt
    rows, shard = rows_for(plan)
    index = assemble(plan, rows, (shard,)).index
    command = RegisterEmbeddingIndexCommandV2.model_validate(
        seal(
            old_receipt.registration_command.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-command/2.0",
                "namespace": plan.namespace.model_dump(mode="json"),
                "graph_snapshot": plan.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": plan.access_policy_revision_id,
                "policy_sha256": plan.access_policy_sha256,
                "index_id": index.index_id,
                "index_revision_id": index.index_revision_id,
                "index_manifest": pointer(index).model_dump(mode="json"),
                "index_sha256": index.index_sha256,
                "source_set_sha256": plan.source_set_sha256,
                "binding_set_sha256": content_sha256([b.binding_sha256 for b in index.bindings]),
            },
            "request_sha256",
        )
    )
    registered = EmbeddingIndexRegistrationResultV2.model_validate(
        seal(
            old_receipt.registration_result.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-result/2.0",
                **{
                    field: getattr(command, field)
                    for field in (
                        "operation_key",
                        "request_sha256",
                        "index_id",
                        "index_revision_id",
                        "index_manifest",
                        "index_sha256",
                    )
                },
                "current_index_revision_id": command.index_revision_id,
            },
            "result_sha256",
        )
    )
    receipt = LocalEmbeddingWorkflowReceiptV2.model_validate(
        seal(
            old_receipt.model_dump(mode="json")
            | {
                "schema_version": "local-embedding-workflow-receipt/2.0",
                "workflow_definition_sha256": request.workflow_definition_sha256,
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
                "launch_association_sha256": association.association_sha256,
                "registration_command": command.model_dump(mode="json"),
                "registration_result": registered.model_dump(mode="json"),
            },
            "receipt_sha256",
        )
    )
    output = LocalEmbeddingStepOutputV2.model_validate(
        seal(
            receipt_fixture().output.model_dump(mode="json")
            | {
                "schema_version": "local-embedding-step-output/2.0",
                "receipt_schema": LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V2_SCHEMA_REF,
                "receipt": member(
                    "receipt.json",
                    LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V2_SCHEMA_REF,
                    receipt.model_dump(mode="json"),
                    "e",
                ).model_dump(mode="json"),
                "receipt_sha256": receipt.receipt_sha256,
            },
            "output_sha256",
        )
    )
    return dict(
        original=original,
        request=request,
        plan=plan,
        policy=policy,
        association=association,
        input=native_input,
        result=result,
        events=tuple(events),
        receipt=receipt,
        output=output,
        coverage=ResolvedNativeIndexCoverageV2(index, plan.sources),
    )


def validate_receipt(f: dict[str, Any], **changes: Any) -> Any:
    return validate_local_embedding_workflow_receipt_v2(
        changes.get("receipt", f["receipt"]),
        changes.get("request", f["request"]),
        changes.get("plan", f["plan"]),
        changes.get("policy", f["policy"]),
        workflow_id=f["receipt"].workflow_id,
        step_run_id=f["receipt"].step_run_id,
        receipt_owner_job_id=f["receipt"].receipt_owner_job_id,
        launch_association=changes.get("association", f["association"]),
        owned_input=changes.get("input", f["input"]),
        index_coverage=changes.get("coverage", f["coverage"]),
    )


def test_exact_mixed_request_original_ownership_and_completion_roundtrip() -> None:
    f = carrier_fixture()
    validate_local_embedding_request_references_v2(f["request"], f["plan"], f["policy"])
    validate_local_embedding_launch_association_v2(
        f["association"],
        f["plan"],
        f["input"],
        f["request"].resource_profile,
        f["request"].request_sha256,
    )
    validate_embedding_encoding_completions_v2(
        f["events"], f["association"], f["input"], f["result"]
    )
    assert validate_receipt(f) == f["receipt"]
    assert validate_local_embedding_step_output_v2(f["output"], f["receipt"]) == f["output"]
    for value in (f["association"], *f["events"]):
        assert parse_embedding_encoding_ownership_v2(value) == value
    assert parse_local_embedding_workflow_receipt_v2(f["receipt"]) == f["receipt"]
    assert parse_local_embedding_step_output_v2(f["output"]) == f["output"]


def test_new_wire_frames_are_not_instances_of_released_wire_families() -> None:
    f = carrier_fixture()
    old_receipts = receipt_fixture()
    for current, original in (
        (f["request"], f["original"].request),
        (f["association"].intent, f["original"].base.association.intent),
        (f["association"], f["original"].base.association),
        (f["events"][0], f["original"].base.completions[0]),
        (f["receipt"], old_receipts.receipt),
        (f["output"], old_receipts.output),
    ):
        assert not isinstance(current, type(original))
        assert type(original) not in type(current).__mro__


def test_supported_request_dispatch_is_canonical_without_widening_old_parsers() -> None:
    f = carrier_fixture()
    for value in (f["original"].base.request, f["original"].request, f["request"]):
        assert parse_supported_local_embedding_request(value) == value
    assert supported_local_embedding_request_actor(f["request"]) == (
        "local_indexing_service",
        f["request"].actor_context.service_id,
    )
    assert supported_local_embedding_request_actor(f["original"].base.request) == (
        "human",
        f["original"].base.request.actor_context.operator_id,
    )
    for value in (f["original"].request, f["request"]):
        with pytest.raises(LocalEmbeddingAdmissionContractError):
            parse_supported_local_embedding_request(value.model_copy(update={"authority": True}))
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_supported_local_embedding_request(
            f["request"].model_copy(
                update={"schema_version": "local-embedding-workflow-request/99.0"}
            )
        )


def test_attachment_and_read_frames_are_explicit2_with_real_request1() -> None:
    f = carrier_fixture()
    job, intent = f["association"].owned_jobs[0], f["association"].intent
    attached = EmbeddingEncodingAttachedEventV2.model_validate(
        seal(
            {
                "schema_version": "embedding-encoding-ownership/2.0",
                "record_type": "ATTACHED",
                "owned_job": job,
                "intent": intent,
            },
            "event_sha256",
        )
    )
    for status, completion in (("OWNED", None), ("COMPLETED", f["events"][0])):
        read = EmbeddingEncodingReadResultV2.model_validate(
            seal(
                {
                    "schema_version": "embedding-encoding-ownership/2.0",
                    "record_type": "READ_RESULT",
                    "owned_job": job,
                    "owner_intent": intent,
                    "status": status,
                    "completion": completion,
                },
                "read_sha256",
            )
        )
        assert parse_embedding_encoding_ownership_v2(read) == read
        assert not isinstance(read, EmbeddingEncodingReadResult)
    assert parse_embedding_encoding_ownership_v2(attached) == attached


def test_mixed_intent_borrows_original_completed_job1_without_retagging_or_rekeying() -> None:
    f = carrier_fixture()
    original = f["original"].base
    old_event = next(
        event
        for event in original.completions
        if any(
            current.request == event.owned_job.request for current in f["association"].owned_jobs
        )
    )
    current = next(
        job for job in f["association"].owned_jobs if job.request == old_event.owned_job.request
    )
    read = EmbeddingEncodingReadResult.model_validate(
        seal(
            {
                "schema_version": "embedding-encoding-job/1.0",
                "record_type": "READ_RESULT",
                "owned_job": old_event.owned_job,
                "owner_intent": old_event.intent,
                "status": "COMPLETED",
                "completion": old_event,
            },
            "read_sha256",
        )
    )
    result = validate_supported_embedding_encoding_read(
        read, expected_request=current.request, expected_reference=old_event.owned_job.job_reference
    )
    assert type(result) is EmbeddingEncodingReadResult
    assert result == read and result.owner_intent == original.association.intent
    assert result.owner_intent.source_plan.schema_ref.endswith("/1.0")
    assert result.owner_intent != f["association"].intent
    assert result.owned_job.request.idempotency_key == current.request.idempotency_key
    assert parse_supported_embedding_encoding_read(read) == read
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_embedding_encoding_ownership_v2(read)
    for field, value in (
        ("allocated_artifact_id", "artifact_" + "f" * 32),
        ("job_id", "job_" + "f" * 32),
    ):
        with pytest.raises(ValueError, match="original computational"):
            validate_supported_embedding_encoding_read(
                read,
                expected_request=current.request,
                expected_reference=old_event.owned_job.job_reference.model_copy(
                    update={field: value}
                ),
            )


@pytest.mark.parametrize("version", [1, 2])
def test_read_result_cannot_cross_pair_original_intent_and_completion_families(
    version: int,
) -> None:
    f = carrier_fixture()
    old = f["original"].base.completions[0]
    new = f["events"][0]
    event = old if version == 1 else new
    body = {
        "schema_version": "embedding-encoding-job/1.0"
        if version == 1
        else "embedding-encoding-ownership/2.0",
        "record_type": "READ_RESULT",
        "owned_job": event.owned_job,
        "owner_intent": event.intent,
        "status": "COMPLETED",
        "completion": new if version == 1 else old,
    }
    with pytest.raises(ValueError):
        parse_supported_embedding_encoding_read(seal(body, "read_sha256"))


@pytest.mark.parametrize("family", ["request", "association", "receipt"])
@pytest.mark.parametrize("fault", ["copied_extra", "hidden_extra"])
def test_new_parsers_reject_actual_unserialized_forged_fields(family: str, fault: str) -> None:
    f = carrier_fixture()
    value = f[family].model_copy()
    if fault == "copied_extra":
        value = value.model_copy(update={"authority": "SYNTHETIC_NOT_AUTHORITY"})
    else:
        object.__setattr__(value, "__pydantic_extra__", {"authority": "SYNTHETIC_NOT_AUTHORITY"})
    parse = {
        "request": parse_local_embedding_workflow_request_v2,
        "association": parse_embedding_encoding_ownership_v2,
        "receipt": parse_local_embedding_workflow_receipt_v2,
    }[family]
    with pytest.raises(LocalEmbeddingAdmissionContractError) as caught:
        parse(value)
    assert "SYNTHETIC_NOT_AUTHORITY" not in str(caught.value)


@pytest.mark.parametrize("name,filename,schema_id,expected", MIXED_NATIVE_WORKFLOW_SCHEMA_RESOURCES)
def test_three_schema_resources_are_mirrored_closed_and_hash_pinned(
    name: Any, filename: str, schema_id: str, expected: str
) -> None:
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == expected
    schema = load_local_embedding_admission_schema(name)
    assert schema["$id"] == schema_id
    Draft202012Validator.check_schema(schema)


def test_old_parsers_reject_new_carriers_and_numeric_job1_is_unchanged() -> None:
    f = carrier_fixture()
    for parse, value in (
        (parse_local_embedding_executable_request, f["request"]),
        (parse_embedding_encoding_job_message, f["association"]),
        (parse_embedding_encoding_job_message, f["events"][0]),
        (parse_local_embedding_workflow_receipt, f["receipt"]),
        (parse_local_embedding_step_output, f["output"]),
    ):
        with pytest.raises(ValueError):
            parse(value.model_dump(mode="json"))
    for job in f["association"].owned_jobs:
        assert (
            parse_embedding_encoding_job_message(job.request.model_dump(mode="json")) == job.request
        )
        assert job.request.schema_version == "embedding-encoding-job/1.0"
        with pytest.raises(LocalEmbeddingAdmissionContractError):
            parse_embedding_encoding_ownership_v2(job.request)
    assert f["input"].schema_version == "incremental-embedding-input/1.0"
    assert f["receipt"].execution_result_schema == "incremental-embedding-result@1.0"


@pytest.mark.parametrize(
    "fault",
    [
        "old_definition",
        "old_plan",
        "old_namespace",
        "human",
        "extra",
        "bool",
        "raw_hash",
        "policy_sha",
    ],
)
def test_request2_cannot_reinterpret_old_scope_or_forged_metadata(fault: str) -> None:
    f = carrier_fixture()
    body = f["request"].model_dump(mode="json")
    if fault == "old_definition":
        body["workflow_definition_version"] = "1.0.0"
    elif fault == "old_plan":
        body["source_plan"]["schema_ref"] = "eom://schemas/workflow/local-embedding-source-plan/1.0"
    elif fault == "old_namespace":
        body["namespace"]["projection_version"] = "accepted-solution-comparison/1.0"
    elif fault == "human":
        body["actor_context"] = f["original"].base.request.actor_context.model_dump(mode="json")
    elif fault == "extra":
        body["actor_context"]["authority"] = "ADMIN"
    elif fault == "bool":
        body["resource_profile"]["threads"] = True
    elif fault == "raw_hash":
        body["source_plan"]["sha256"] = body["source_plan_sha256"]
    else:
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        checked = parse_local_embedding_workflow_request_v2(seal(body, "request_sha256"))
        validate_local_embedding_request_references_v2(checked, f["plan"], f["policy"])


@pytest.mark.parametrize(
    "fault", ["plan1", "original_intent", "allocation", "owned_set", "raw_input", "bool"]
)
def test_ownership2_exact_original_subset_and_no_request2_numeric_frame(fault: str) -> None:
    f = carrier_fixture()
    body = f["association"].model_dump(mode="json")
    if fault == "plan1":
        body["intent"]["source_plan"]["schema_ref"] = (
            "eom://schemas/workflow/local-embedding-source-plan/1.0"
        )
    elif fault == "original_intent":
        body["intent"]["workflow_request_sha256"] = "sha256:" + "f" * 64
    elif fault == "allocation":
        body["owned_jobs"][0]["job_reference"]["job_id"] = body["intent"]["native_launch_job_id"]
    elif fault == "owned_set":
        body["owned_jobs"] = body["owned_jobs"][::-1]
    elif fault == "raw_input":
        body["owned_input"]["sha256"] = body["owned_input_request_sha256"]
    else:
        body["intent"]["lease_generation"] = True
    body["intent"] = seal(body["intent"], "intent_sha256")
    with pytest.raises(ValueError):
        checked = parse_embedding_encoding_ownership_v2(seal(body, "association_sha256"))
        assert isinstance(checked, LocalEmbeddingLaunchAssociationV2)
        validate_local_embedding_launch_association_v2(
            checked,
            f["plan"],
            f["input"],
            f["request"].resource_profile,
            f["request"].request_sha256,
        )


def test_borrowed_only_receipt_preserves_registration_without_claiming_a_launch() -> None:
    f = carrier_fixture()
    receipt = LocalEmbeddingWorkflowReceiptV2.model_validate(
        seal(
            f["receipt"].model_dump(mode="json")
            | {"native_launch_job_id": None, "launch_association_sha256": None},
            "receipt_sha256",
        )
    )
    assert validate_receipt(f, receipt=receipt, association=None, input=None) == receipt


@pytest.mark.parametrize(
    "fault",
    [
        "no_launch_pair",
        "old_registration",
        "wrong_registration_hash",
        "foreign_eligible",
        "wrong_base",
        "wrong_row",
        "original_allocation",
        "copy_extra",
    ],
)
def test_completion2_fails_on_changed_original_or_registry_coverage(fault: str) -> None:
    f = carrier_fixture()
    receipt, coverage, events = f["receipt"], f["coverage"], f["events"]
    if fault == "copy_extra":
        with pytest.raises(LocalEmbeddingAdmissionContractError):
            parse_local_embedding_workflow_receipt_v2(
                receipt.model_copy(update={"authority": True})
            )
        return
    if fault == "wrong_row":
        event = events[0].model_copy(
            update={
                "receipt": events[0].receipt.model_copy(
                    update={
                        "row_ref": events[0].receipt.row_ref.model_copy(update={"row_index": 1000})
                    }
                )
            }
        )
        with pytest.raises(ValueError):
            validate_embedding_encoding_completions_v2(
                (event, *events[1:]), f["association"], f["input"], f["result"]
            )
        return
    if fault == "original_allocation":
        event = events[0].model_copy(update={"owned_job": events[1].owned_job})
        with pytest.raises(ValueError):
            validate_embedding_encoding_completions_v2(
                (event, *events[1:]), f["association"], f["input"], f["result"]
            )
        return
    body = receipt.model_dump(mode="json")
    if fault == "no_launch_pair":
        body["native_launch_job_id"] = None
    elif fault == "old_registration":
        body["registration_command"]["schema_version"] = (
            "embedding-registry-registration-command/1.0"
        )
    elif fault == "wrong_registration_hash":
        body["registration_command"]["index_sha256"] = "sha256:" + "f" * 64
    elif fault == "foreign_eligible":
        coverage = replace(coverage, eligible_sources=coverage.eligible_sources[:1])
    else:
        index_body = coverage.index.model_dump(mode="json")
        index_body["bindings"][0]["base_analysis_run_id"] = "analysisrun_" + "f" * 32
        index_body["bindings"][0] = seal(index_body["bindings"][0], "binding_sha256")
        coverage = replace(
            coverage, index=type(coverage.index).model_validate(seal(index_body, "index_sha256"))
        )
    with pytest.raises(ValueError):
        checked = parse_local_embedding_workflow_receipt_v2(seal(body, "receipt_sha256"))
        validate_receipt(f, receipt=checked, coverage=coverage)
