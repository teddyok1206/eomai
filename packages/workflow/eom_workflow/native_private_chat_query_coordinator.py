"""Original private QUERY continuation values; never current authority or retry permission."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_private_chat_query import PRIVATE_CHAT_QUERY_RESULT_REF
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import SHARD_SCHEMA_REF
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import model_validator

from eom_workflow.models import JobId
from eom_workflow.native_reference_query_coordinator import (
    NATIVE_QUERY_PHASES,
    NativeQueryAllocation,
    NativeQueryExecutedObservation,
    NativeQueryPhase,
)
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import (
    PRIVATE_CHAT_QUERY_RECORD_REF,
    PrivateChatQueryExecutionRecord,
    PrivateChatQueryLaunchAssociation,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_step_output,
)
from eom_workflow.schemas import (
    NativeEmbeddingContract,
    validate_native_private_chat_query_checkpoint,
)


class NativePrivateQueryAllocation(NativeEmbeddingContract):
    allocation: NativeQueryAllocation
    origin: ChatPrivateQueryOrigin


class NativePrivateQueryExecuted(NativeQueryExecutedObservation):
    prepare_template_sha256: Literal[
        "sha256:f3c9d2bad306b0f3f1ac35272d2af8d8957c7f8cfd16866695403da0cd4d7227"
    ]
    query_template_sha256: Literal[
        "sha256:cecb3128eaf33b0e897a813aab7ec4559ca26e63291fb7622a5c429826538bde"
    ]


class NativePrivateQueryPublished(NativeEmbeddingContract):
    query_owner_job_id: JobId
    execution_record: ArtifactMemberPointer
    result: ArtifactMemberPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    manifest_sha256: Sha256
    published_observed_at: UtcDatetime

    @model_validator(mode="after")
    def exact_members(self) -> NativePrivateQueryPublished:
        members = (
            (
                self.execution_record,
                "intent.json",
                PRIVATE_CHAT_QUERY_RECORD_REF,
                "application/json",
            ),
            (self.result, "result.json", PRIVATE_CHAT_QUERY_RESULT_REF, "application/json"),
            (self.shard, "shard.json", SHARD_SCHEMA_REF, "application/json"),
            (
                self.binary,
                "vectors.f32",
                "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                "application/octet-stream",
            ),
        )
        if len({(p.artifact_id, p.artifact_revision_id) for p, *_ in members}) != 1 or any(
            (p.member_path, p.schema_ref, p.media_type) != (name, schema, media)
            for p, name, schema, media in members
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_FILE_SET_INVALID")
        return self


class NativePrivateQueryCompleted(NativeEmbeddingContract):
    output: PrivateChatQueryStepOutput


type NativePrivateQueryPayload = (
    NativePrivateQueryAllocation
    | NativePrivateQueryExecuted
    | NativePrivateQueryPublished
    | NativePrivateQueryCompleted
)
_PAYLOADS = {
    "ALLOCATION": NativePrivateQueryAllocation,
    "EXECUTED": NativePrivateQueryExecuted,
    "PUBLISHED": NativePrivateQueryPublished,
    "COMPLETED": NativePrivateQueryCompleted,
}


class NativePrivateChatQueryCheckpoint(NativeEmbeddingContract):
    schema_version: Literal["native-private-chat-query-coordinator/1.0"] = (
        "native-private-chat-query-coordinator/1.0"
    )
    record_type: NativeQueryPhase
    native_launch_job_id: JobId
    association_sha256: Sha256
    payload: NativePrivateQueryPayload
    checkpoint_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        value = raw_similarity_contract_value(value)
        validate_native_private_chat_query_checkpoint(value)
        return value

    @model_validator(mode="after")
    def exact_stage(self) -> NativePrivateChatQueryCheckpoint:
        if (
            type(self.payload) is not _PAYLOADS[self.record_type]
            or (
                self.checkpoint_sha256
                != content_sha256(self.model_dump(mode="json", exclude={"checkpoint_sha256"}))
            )
            or (
                isinstance(self.payload, NativePrivateQueryAllocation)
                and self.native_launch_job_id
                in {
                    self.payload.allocation.query_producer.job_id,
                    self.payload.allocation.receipt_producer.job_id,
                }
            )
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID")
        return self


def parse_native_private_chat_query_checkpoint(value: object) -> NativePrivateChatQueryCheckpoint:
    try:
        return NativePrivateChatQueryCheckpoint.model_validate(raw_similarity_contract_value(value))
    except (ValueError, TypeError):
        # A forged input can include arbitrary private text in otherwise forbidden fields.
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID") from None


def native_private_chat_query_checkpoint(
    launch: PrivateChatQueryLaunchAssociation,
    phase: NativeQueryPhase,
    payload: NativePrivateQueryPayload,
) -> NativePrivateChatQueryCheckpoint:
    launch = PrivateChatQueryLaunchAssociation.model_validate(raw_similarity_contract_value(launch))
    if phase not in _PAYLOADS or type(payload) is not _PAYLOADS[phase]:
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_PURPOSE_INVALID")
    payload = type(payload).model_validate(raw_similarity_contract_value(payload))
    body = {
        "schema_version": "native-private-chat-query-coordinator/1.0",
        "record_type": phase,
        "native_launch_job_id": launch.native_launch_job_id,
        "association_sha256": launch.association_sha256,
        "payload": payload.model_dump(mode="json"),
    }
    return parse_native_private_chat_query_checkpoint(
        body | {"checkpoint_sha256": content_sha256(body)}
    )


def private_chat_query_checkpoint_receipt(
    request: PrivateChatQueryWorkflowRequest,
    launch: PrivateChatQueryLaunchAssociation,
    allocation: NativePrivateQueryAllocation,
    executed: NativePrivateQueryExecuted,
    published: NativePrivateQueryPublished,
) -> PrivateChatQueryWorkflowReceipt:
    """Reconstruct text-free metadata, not physical/source/Artifact validation."""
    body = {
        "schema_version": "private-chat-query-workflow-receipt/1.0",
        "purpose": "PRIVATE_CHAT_QUERY",
        "workflow_id": launch.workflow_id,
        "step_run_id": launch.step_run_id,
        "step_key": launch.step_key,
        "attempt": launch.attempt,
        "workflow_definition_sha256": request.workflow_definition_sha256,
        "workflow_request_sha256": request.request_sha256,
        "context_request_sha256": request.context_request.request_sha256,
        "origin_sha256": allocation.origin.origin_sha256,
        "receipt_owner_job_id": allocation.allocation.receipt_producer.job_id,
        "query_artifact_owner_job_id": published.query_owner_job_id,
        "native_launch_job_id": launch.native_launch_job_id,
        "launch_association_sha256": launch.association_sha256,
        "execution_result_schema": "embedding-private-chat-query-result@1.0",
        "execution_record": published.execution_record.model_dump(mode="json"),
        "query_execution": {
            "job_id": launch.native_launch_job_id,
            "query_request_id": launch.query_request_id,
            "request_sha256": launch.query_request_sha256,
            "input_set_sha256": launch.query_input_set_sha256,
            "basis_sha256": launch.basis_sha256,
            "result_member": published.result.model_dump(mode="json"),
            "result_sha256": executed.result_sha256,
        },
        "shard": published.shard.model_dump(mode="json"),
        "binary": published.binary.model_dump(mode="json"),
        "runtime_bundle": request.runtime_bundle.model_dump(mode="json"),
        "resource_profile_sha256": request.resource_profile.resource_profile_sha256,
        "published_at": published.published_observed_at.isoformat().replace("+00:00", "Z"),
    }
    return PrivateChatQueryWorkflowReceipt.model_validate(
        body | {"receipt_sha256": content_sha256(body)}
    )


def validate_native_private_chat_query_history(
    records: tuple[NativePrivateChatQueryCheckpoint, ...],
    launch: PrivateChatQueryLaunchAssociation,
    request: PrivateChatQueryWorkflowRequest,
) -> None:
    request = PrivateChatQueryWorkflowRequest.model_validate(raw_similarity_contract_value(request))
    launch = PrivateChatQueryLaunchAssociation.model_validate(raw_similarity_contract_value(launch))
    body = {
        "schema_version": "private-chat-query-execution-record/1.0",
        "purpose": "PRIVATE_CHAT_QUERY",
        "workflow_request": request.model_dump(mode="json"),
        "launch": launch.model_dump(mode="json"),
    }
    intent = PrivateChatQueryExecutionRecord.model_validate(
        body | {"record_sha256": content_sha256(body)}
    )
    checked = tuple(parse_native_private_chat_query_checkpoint(value) for value in records)
    if (
        len(checked) > 4
        or tuple(r.record_type for r in checked) != NATIVE_QUERY_PHASES[: len(checked)]
        or any(
            r.native_launch_job_id != launch.native_launch_job_id
            or r.association_sha256 != launch.association_sha256
            for r in checked
        )
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_HISTORY_INVALID")
    if not checked:
        return
    allocation = checked[0].payload
    assert isinstance(allocation, NativePrivateQueryAllocation)
    if allocation.origin.actor_id != request.operator_audit.operator_id or (
        allocation.origin.basis != request.context_request.query_basis
        or allocation.allocation.created_at < launch.launched_at
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_ORIGIN_INVALID")
    if len(checked) < 2:
        return
    executed = checked[1].payload
    assert isinstance(executed, NativePrivateQueryExecuted)
    if executed.completed_observed_at < allocation.allocation.created_at:
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_ORDER_INVALID")
    if len(checked) < 3:
        return
    published = checked[2].payload
    assert isinstance(published, NativePrivateQueryPublished)
    if (
        published.query_owner_job_id != allocation.allocation.query_producer.job_id
        or published.execution_record.artifact_id
        != allocation.allocation.query_producer.artifact_id
        or published.execution_record.artifact_revision_id
        != allocation.allocation.query_producer.artifact_revision_id
        or published.execution_record.sha256 != sha256_bytes(canonical_json_bytes(intent))
        or published.published_observed_at < executed.completed_observed_at
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_PUBLICATION_INVALID")
    receipt = private_chat_query_checkpoint_receipt(
        request, launch, allocation, executed, published
    )
    if len(checked) == 4:
        completed = checked[3].payload
        assert isinstance(completed, NativePrivateQueryCompleted)
        output = completed.output
        if (
            output.receipt.artifact_id != allocation.allocation.receipt_producer.artifact_id
            or output.receipt.artifact_revision_id
            != allocation.allocation.receipt_producer.artifact_revision_id
            or output.receipt.sha256 != sha256_bytes(canonical_json_bytes(receipt))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_COMPLETION_INVALID")
        validate_private_chat_query_step_output(output, receipt)
