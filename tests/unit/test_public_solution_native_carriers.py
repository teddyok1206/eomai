"""Public report3 closures with genuine numerical1 values; synthetic IAM/model only."""

from dataclasses import replace
from functools import lru_cache

import pytest
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.public_solution_embedding_registry import (
    PublicSolutionIndexRegistrationResult,
    RegisterPublicSolutionIndexCommand,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.local_embedding_source_plan_v3 import build_local_embedding_source_plan_v3
from eom_catalog_service.public_solution_index_assembly import assemble_public_solution_index
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_encoding_dispatch import (
    build_supported_owned_incremental_embedding_input,
    embedding_ownership_version,
    parse_supported_embedding_message,
    validate_supported_embedding_association,
    validate_supported_embedding_completions,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobRequest,
    LocalEmbeddingOwnedJob,
)
from eom_workflow.local_embedding_encoding_ownership_v3 import (
    EmbeddingEncodingCompletedEventV3,
    LocalEmbeddingLaunchAssociationV3,
    LocalEmbeddingLaunchIntentV3,
)
from eom_workflow.local_embedding_request_v2 import (
    LOCAL_EMBEDDING_REQUEST_TYPES,
    parse_local_embedding_workflow_request_v2,
    parse_supported_local_embedding_request,
    validate_supported_local_embedding_request_references,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    parse_supported_local_embedding_step_output,
    parse_supported_local_embedding_workflow_receipt,
)
from eom_workflow.local_embedding_workflow_receipt_v3 import (
    LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V3_SCHEMA_REF,
    LocalEmbeddingStepOutputV3,
    LocalEmbeddingWorkflowReceiptV3,
    ResolvedNativeIndexCoverageV3,
    validate_local_embedding_step_output_v3,
    validate_local_embedding_workflow_receipt_v3,
)
from eom_workflow_runner.repository import workflow_request_storage_document

from tests.unit.inference_transfer_embedding_fixtures import embedding_result, seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_local_embedding_source_plan_v3 import inputs
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture


@lru_cache(maxsize=2)
def public_native_fixture(*, device="CPU"):
    original = carrier_fixture(device=device)
    policy = original["policy"]
    profile = policy.profiles[0]
    query, resolved, _ = inputs()
    namespace = query.namespace.model_copy(update={"space_sha256": profile.space.space_sha256})
    query = replace(query, namespace=namespace)
    resolved = replace(resolved, space=profile.space)
    plan = build_local_embedding_source_plan_v3(
        query, resolved, target_revision_ids=tuple(s.item_revision_id for s in resolved.sources)
    )
    request = parse_supported_local_embedding_request(
        seal(
            original["request"].model_dump(mode="json")
            | {
                "schema_version": "local-embedding-workflow-request/3.0",
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
                    "eom://schemas/workflow/local-embedding-source-plan/3.0",
                    plan.model_dump(mode="json"),
                    "2",
                ).model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "request_sha256",
        )
    )
    intent = LocalEmbeddingLaunchIntentV3.model_validate(
        seal(
            original["association"].intent.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "intent_sha256",
        )
    )
    old_job = original["association"].owned_jobs[0]
    job_request = EmbeddingEncodingJobRequest.model_validate(
        seal(
            old_job.request.model_dump(mode="json")
            | {"encoding": plan.demands[0].encoding.model_dump(mode="json")},
            "request_sha256",
        )
    )
    job = LocalEmbeddingOwnedJob.model_validate(
        {
            "request": job_request.model_dump(mode="json"),
            "job_reference": old_job.job_reference.model_dump(mode="json")
            | {"request_sha256": job_request.request_sha256},
        }
    )
    owned_input = build_supported_owned_incremental_embedding_input(
        plan,
        resolved.entries,
        (job,),
        native_launch_job_id=intent.native_launch_job_id,
        resources=profile.resource_profile,
    )
    association = LocalEmbeddingLaunchAssociationV3.model_validate(
        seal(
            original["association"].model_dump(mode="json")
            | {
                "schema_version": "embedding-encoding-ownership/3.0",
                "intent": intent.model_dump(mode="json"),
                "owned_jobs": [job.model_dump(mode="json")],
                "owned_input": member(
                    "input.json",
                    "eom://schemas/knowledge/incremental-embedding-input/1.0",
                    owned_input.model_dump(mode="json"),
                    "7",
                ).model_dump(mode="json"),
                "owned_input_request_sha256": owned_input.request_sha256,
                "owned_input_set_sha256": owned_input.input_set_sha256,
            },
            "association_sha256",
        )
    )
    result = embedding_result(owned_input)
    shard = member(
        "shard.json",
        "eom://schemas/knowledge/embedding-vector-shard/1.0",
        result.shard.model_dump(mode="json"),
    )
    shared = original["events"][0].receipt.model_dump(mode="json")
    shared.update(
        result_manifest=member(
            "result.json",
            "eom://schemas/knowledge/incremental-embedding-result/1.0",
            result.model_dump(mode="json"),
        ).model_dump(mode="json"),
        result_sha256=result.result_sha256,
        shard_manifest=shard.model_dump(mode="json"),
        shard_sha256=result.shard.shard_sha256,
        row_ref={
            "shard_manifest": shard.model_dump(mode="json"),
            "row_index": 0,
            "encoding_sha256": job.request.encoding.encoding_sha256,
        },
    )
    shared["binary_member"]["sha256"] = result.shard.binary.sha256
    event = EmbeddingEncodingCompletedEventV3.model_validate(
        seal(
            {
                "schema_version": "embedding-encoding-ownership/3.0",
                "record_type": "COMPLETED",
                "owned_job": job.model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
                "launch_association_sha256": association.association_sha256,
                "receipt": seal(shared, "receipt_sha256"),
            },
            "event_sha256",
        )
    )
    index = assemble_public_solution_index(
        resolved.entries,
        available_rows=(
            RegisteredEmbeddingRow(
                job.request.encoding,
                EmbeddingVectorRowRef(
                    shard_manifest=shard,
                    row_index=0,
                    encoding_sha256=job.request.encoding.encoding_sha256,
                ),
            ),
        ),
        shards=((shard, result.shard),),
        namespace=namespace,
        space=profile.space,
        index_id="embeddingindex_" + "1" * 32,
        index_revision_id="embeddingindexrev_" + "2" * 32,
        previous_manifest=None,
        created_at=NOW,
    ).index
    command = RegisterPublicSolutionIndexCommand.model_validate(
        seal(
            original["receipt"].registration_command.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-command/3.0",
                "namespace": namespace.model_dump(mode="json"),
                "graph_snapshot": plan.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": plan.access_policy_revision_id,
                "policy_sha256": plan.access_policy_sha256,
                "index_id": index.index_id,
                "index_revision_id": index.index_revision_id,
                "index_manifest": member(
                    "index.json",
                    "eom://schemas/knowledge/embedding-index-manifest/3.0",
                    index.model_dump(mode="json"),
                    "c",
                ).model_dump(mode="json"),
                "index_sha256": index.index_sha256,
                "source_set_sha256": plan.source_set_sha256,
                "binding_set_sha256": content_sha256([b.binding_sha256 for b in index.bindings]),
                "eligible_source_count": len(plan.sources),
                "binding_count": len(index.bindings),
            },
            "request_sha256",
        )
    )
    registered = PublicSolutionIndexRegistrationResult.model_validate(
        seal(
            original["receipt"].registration_result.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-result/3.0",
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
    receipt = LocalEmbeddingWorkflowReceiptV3.model_validate(
        seal(
            original["receipt"].model_dump(mode="json")
            | {
                "schema_version": "local-embedding-workflow-receipt/3.0",
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
    output = LocalEmbeddingStepOutputV3.model_validate(
        seal(
            original["output"].model_dump(mode="json")
            | {
                "schema_version": "local-embedding-step-output/3.0",
                "receipt_schema": LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V3_SCHEMA_REF,
                "receipt": member(
                    "receipt.json",
                    LOCAL_EMBEDDING_WORKFLOW_RECEIPT_V3_SCHEMA_REF,
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
        plan=plan,
        request=request,
        policy=policy,
        intent=intent,
        association=association,
        input=owned_input,
        result=result,
        events=(event,),
        receipt=receipt,
        output=output,
        coverage=ResolvedNativeIndexCoverageV3(index, plan.sources),
    )


def test_public_native_path_keeps_two_proofs_but_one_numerical_input():
    f = public_native_fixture()
    assert len(f["plan"].demands) == len(f["coverage"].index.bindings) == 2
    assert len(f["input"].rows) == len(f["association"].owned_jobs) == 1
    assert f["input"].rows[0].text == "속도는 -36 km/h이고 합력은 0 N이 아니다."
    assert f["input"].schema_version == "incremental-embedding-input/1.0"
    assert embedding_ownership_version(f["intent"]) == "embedding-encoding-ownership/3.0"
    validate_supported_local_embedding_request_references(f["request"], f["plan"], f["policy"])
    validate_supported_embedding_association(
        f["association"],
        f["plan"],
        f["input"],
        f["request"].resource_profile,
        f["request"].request_sha256,
    )
    validate_supported_embedding_completions(f["events"], f["association"], f["input"], f["result"])
    assert parse_supported_embedding_message(f["association"]) == f["association"]
    assert parse_supported_embedding_message(f["events"][0]) == f["events"][0]


def test_public_completion_closes_exact_source_plan_index_and_registration():
    f = public_native_fixture()
    assert (
        validate_local_embedding_workflow_receipt_v3(
            f["receipt"],
            f["request"],
            f["plan"],
            f["policy"],
            workflow_id=f["intent"].workflow_id,
            step_run_id=f["intent"].step_run_id,
            receipt_owner_job_id=f["receipt"].receipt_owner_job_id,
            launch_association=f["association"],
            owned_input=f["input"],
            index_coverage=f["coverage"],
        )
        == f["receipt"]
    )
    assert validate_local_embedding_step_output_v3(f["output"], f["receipt"]) == f["output"]
    assert parse_supported_local_embedding_step_output(f["output"]) == f["output"]
    assert parse_supported_local_embedding_workflow_receipt(f["receipt"]) == f["receipt"]


def test_runtime_classification_and_storage_never_fall_through_to_item_request():
    f = public_native_fixture()
    for value in (f["request"], f["original"]["request"]):
        assert isinstance(value, LOCAL_EMBEDDING_REQUEST_TYPES)
        assert workflow_request_storage_document(value) == value.model_dump(mode="json")
    with pytest.raises(ValueError):
        parse_local_embedding_workflow_request_v2(f["request"])
    with pytest.raises(ValueError):
        validate_supported_embedding_association(
            f["association"],
            f["original"]["plan"],
            f["input"],
            f["request"].resource_profile,
            f["request"].request_sha256,
        )
