"""Tiny canonical metadata fixtures, never current authority or binary/Artifact proof."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
)
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_workflow_receipt import (
    LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF,
    LocalEmbeddingStepOutput,
    LocalEmbeddingWorkflowReceipt,
)

from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    index_pointer,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import (
    NativeAdmissionFixture,
    member,
    native_fixture,
)


@dataclass(frozen=True)
class NativeReceiptFixture:
    native: NativeAdmissionFixture
    receipt: LocalEmbeddingWorkflowReceipt
    output: LocalEmbeddingStepOutput


def receipt_fixture(
    *, borrowed_only: bool = False, historical: bool = False
) -> NativeReceiptFixture:
    native = native_fixture()
    plan = native.plan
    shard = vector_shard(tuple(row.encoding for row in native.native_input.rows), space=plan.space)
    pointer = shard_pointer(shard)
    bindings = tuple(
        source_binding(
            entry,
            view=plan.namespace.view,
            recipe=plan.recipe,
            space=plan.space,
            shard=shard,
            pointer=pointer,
        )
        for entry in native.entries
    )
    index = index_manifest(*bindings, space=plan.space, view=plan.namespace.view)
    command = RegisterEmbeddingIndexCommand.model_validate(
        seal(
            {
                "schema_version": "embedding-registry-registration-command/1.0",
                "operation": "REGISTER_EMBEDDING_INDEX",
                "operation_key": "synthetic-native-receipt:first",
                "corpus_id": plan.corpus_id,
                "namespace": plan.namespace.model_dump(mode="json"),
                "index_id": index.index_id,
                "index_revision_id": index.index_revision_id,
                "index_manifest": index_pointer(index).model_dump(mode="json"),
                "index_sha256": index.index_sha256,
                "graph_snapshot": plan.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": plan.access_policy_revision_id,
                "policy_sha256": plan.access_policy_sha256,
                "expected_current_index_revision_id": None,
                "expected_lock_version": 1,
                "source_set_sha256": plan.source_set_sha256,
                "binding_set_sha256": content_sha256(
                    [binding.binding_sha256 for binding in bindings]
                ),
                "eligible_source_count": len(plan.sources),
                "binding_count": len(plan.demands),
                "requested_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "request_sha256",
        )
    )
    result = EmbeddingIndexRegistrationResult.model_validate(
        seal(
            {
                "schema_version": "embedding-registry-registration-result/1.0",
                **{
                    field: getattr(command, field)
                    for field in (
                        "operation_key",
                        "request_sha256",
                        "index_id",
                        "index_revision_id",
                        "index_sha256",
                    )
                },
                "index_manifest": command.index_manifest.model_dump(mode="json"),
                "previous_index_revision_id": None,
                "registered_lock_version": 2,
                "current_index_revision_id": (
                    "embeddingindexrev_" + "c" * 32 if historical else command.index_revision_id
                ),
                "current_lock_version": 3 if historical else 2,
                "replayed": historical,
                "is_current": not historical,
                "registered_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "result_sha256",
        )
    )
    intent = native.association.intent
    receipt = LocalEmbeddingWorkflowReceipt.model_validate(
        seal(
            {
                "schema_version": "local-embedding-workflow-receipt/1.0",
                "purpose": "LOCAL_EMBEDDING",
                "workflow_id": intent.workflow_id,
                "workflow_definition_sha256": native.request.workflow_definition_sha256,
                "workflow_request_sha256": native.request.request_sha256,
                "source_plan": native.request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
                "step_run_id": intent.step_run_id,
                "step_key": "encode_batch",
                "attempt": 1,
                "receipt_owner_job_id": "job_" + "e" * 32,
                "execution_result_schema": "incremental-embedding-result@1.0",
                "native_launch_job_id": None if borrowed_only else intent.native_launch_job_id,
                "launch_association_sha256": (
                    None if borrowed_only else native.association.association_sha256
                ),
                "registration_command": command.model_dump(mode="json"),
                "registration_result": result.model_dump(mode="json"),
                "registration_observed_at": (NOW + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            "receipt_sha256",
        )
    )
    output = LocalEmbeddingStepOutput.model_validate(
        seal(
            {
                "schema_version": "local-embedding-step-output/1.0",
                "purpose": "LOCAL_EMBEDDING",
                **{
                    field: getattr(receipt, field)
                    for field in (
                        "workflow_id",
                        "step_run_id",
                        "step_key",
                        "attempt",
                        "receipt_owner_job_id",
                        "execution_result_schema",
                        "receipt_sha256",
                    )
                },
                "receipt_schema": LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF,
                "receipt": member(
                    "receipt.json",
                    LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF,
                    receipt.model_dump(mode="json"),
                    "e",
                ).model_dump(mode="json"),
            },
            "output_sha256",
        )
    )
    return NativeReceiptFixture(native, receipt, output)
