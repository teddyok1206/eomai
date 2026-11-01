"""Original private QUERY continuation values; never current authority or retry permission."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_private_chat_query import PRIVATE_CHAT_QUERY_RESULT_REF
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import SHARD_SCHEMA_REF
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.public_solution_query import PUBLIC_SOLUTION_QUERY_RESULT_REF
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_workflow.embedding_batch_execution_receipt import (
    PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
)
from eom_workflow.models import JobId
from eom_workflow.native_reference_query_coordinator import (
    NATIVE_QUERY_PHASES,
    NativeQueryAllocation,
    NativeQueryBatchExecutionObservation,
    NativeQueryExecutedObservation,
    NativeQueryPhase,
)
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryWorkflowRequestV2,
    SupportedPrivateChatQueryWorkflowRequest,
    parse_supported_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_publication import (
    PRIVATE_CHAT_QUERY_RECORD_REF,
    PrivateChatQueryExecutionRecord,
    PrivateChatQueryLaunchAssociation,
)
from eom_workflow.private_chat_query_publication_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_RECORD_REF,
    PrivateChatPublicQueryExecutionRecord,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_step_output,
)
from eom_workflow.private_chat_query_workflow_v2 import (
    PrivateChatQueryStepOutputV2,
    PrivateChatQueryWorkflowReceiptV2,
    validate_private_chat_public_query_step_output,
)
from eom_workflow.schemas import (
    NativeEmbeddingContract,
    validate_native_private_chat_query_checkpoint,
    validate_native_private_chat_query_checkpoint_v2,
    validate_native_private_chat_query_checkpoint_v21,
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


class NativePrivateQueryBatchExecuted(NativeQueryBatchExecutionObservation):
    """Private receipt1.1 child0 only; actual producer/source resolution is separate."""

    child_ordinal: int = Field(ge=0, le=0, strict=True)

    @model_validator(mode="after")
    def exact_private_member(self) -> Self:
        if (
            self.batch_receipt.member_path != "receipt.json"
            or self.batch_receipt.schema_ref != PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF
            or self.batch_receipt.media_type != "application/json"
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_FILE_SET_INVALID")
        return self


class _NativePrivateQueryPublishedFields(NativeEmbeddingContract):
    query_owner_job_id: JobId
    execution_record: ArtifactMemberPointer
    result: ArtifactMemberPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    manifest_sha256: Sha256
    published_observed_at: UtcDatetime

    def require_members(self, record_ref: str, result_ref: str) -> None:
        members = (
            (
                self.execution_record,
                "intent.json",
                record_ref,
                "application/json",
            ),
            (self.result, "result.json", result_ref, "application/json"),
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


class NativePrivateQueryPublished(_NativePrivateQueryPublishedFields):
    @model_validator(mode="after")
    def exact_members(self) -> Self:
        self.require_members(PRIVATE_CHAT_QUERY_RECORD_REF, PRIVATE_CHAT_QUERY_RESULT_REF)
        return self


class NativePrivateQueryPublishedV2(_NativePrivateQueryPublishedFields):
    @model_validator(mode="after")
    def exact_members(self) -> Self:
        self.require_members(PRIVATE_CHAT_PUBLIC_QUERY_RECORD_REF, PUBLIC_SOLUTION_QUERY_RESULT_REF)
        return self


class NativePrivateQueryCompleted(NativeEmbeddingContract):
    output: PrivateChatQueryStepOutput


class NativePrivateQueryCompletedV2(NativeEmbeddingContract):
    output: PrivateChatQueryStepOutputV2


type NativePrivateQueryPayload = (
    NativePrivateQueryAllocation
    | NativePrivateQueryExecuted
    | NativePrivateQueryPublished
    | NativePrivateQueryCompleted
)
type NativePrivateQueryPayloadV2 = (
    NativePrivateQueryAllocation
    | NativePrivateQueryExecuted
    | NativePrivateQueryPublishedV2
    | NativePrivateQueryCompletedV2
)
type NativePrivateQueryPayloadV21 = (
    NativePrivateQueryAllocation
    | NativePrivateQueryBatchExecuted
    | NativePrivateQueryPublishedV2
    | NativePrivateQueryCompletedV2
)
type SupportedNativePrivateQueryPayload = (
    NativePrivateQueryPayload | NativePrivateQueryPayloadV2 | NativePrivateQueryPayloadV21
)
_PAYLOADS = MappingProxyType(
    {
        "ALLOCATION": NativePrivateQueryAllocation,
        "EXECUTED": NativePrivateQueryExecuted,
        "PUBLISHED": NativePrivateQueryPublished,
        "COMPLETED": NativePrivateQueryCompleted,
    }
)
_PAYLOADS_V2 = MappingProxyType(
    {
        **_PAYLOADS,
        "PUBLISHED": NativePrivateQueryPublishedV2,
        "COMPLETED": NativePrivateQueryCompletedV2,
    }
)
_PAYLOADS_V21 = MappingProxyType({**_PAYLOADS_V2, "EXECUTED": NativePrivateQueryBatchExecuted})
_PAYLOAD_FAMILIES = MappingProxyType(
    {
        "native-private-chat-query-coordinator/1.0": _PAYLOADS,
        "native-private-chat-query-coordinator/2.0": _PAYLOADS_V2,
        "native-private-chat-query-coordinator/2.1": _PAYLOADS_V21,
    }
)


class _NativePrivateChatQueryCheckpointFields(NativeEmbeddingContract):
    schema_version: Literal[
        "native-private-chat-query-coordinator/1.0",
        "native-private-chat-query-coordinator/2.0",
        "native-private-chat-query-coordinator/2.1",
    ]
    record_type: NativeQueryPhase
    native_launch_job_id: JobId
    association_sha256: Sha256
    payload: SupportedNativePrivateQueryPayload
    checkpoint_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        value = raw_similarity_contract_value(value)
        version = value.get("schema_version") if isinstance(value, dict) else None
        if version == "native-private-chat-query-coordinator/2.1":
            validate_native_private_chat_query_checkpoint_v21(value)
        elif version == "native-private-chat-query-coordinator/2.0":
            validate_native_private_chat_query_checkpoint_v2(value)
        else:
            validate_native_private_chat_query_checkpoint(value)
        return value

    @model_validator(mode="after")
    def exact_stage(self) -> Self:
        payloads = _PAYLOAD_FAMILIES[self.schema_version]
        if (
            type(self.payload) is not payloads[self.record_type]
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


class NativePrivateChatQueryCheckpoint(_NativePrivateChatQueryCheckpointFields):
    schema_version: Literal["native-private-chat-query-coordinator/1.0"] = (
        "native-private-chat-query-coordinator/1.0"
    )
    payload: NativePrivateQueryPayload


class NativePrivateChatQueryCheckpointV2(_NativePrivateChatQueryCheckpointFields):
    schema_version: Literal["native-private-chat-query-coordinator/2.0"] = (
        "native-private-chat-query-coordinator/2.0"
    )
    payload: NativePrivateQueryPayloadV2


class NativePrivateChatQueryCheckpointV21(_NativePrivateChatQueryCheckpointFields):
    schema_version: Literal["native-private-chat-query-coordinator/2.1"] = (
        "native-private-chat-query-coordinator/2.1"
    )
    payload: NativePrivateQueryPayloadV21


type SupportedNativePrivateChatQueryCheckpoint = (
    NativePrivateChatQueryCheckpoint
    | NativePrivateChatQueryCheckpointV2
    | NativePrivateChatQueryCheckpointV21
)


def parse_native_private_chat_query_checkpoint(value: object) -> NativePrivateChatQueryCheckpoint:
    try:
        return NativePrivateChatQueryCheckpoint.model_validate(raw_similarity_contract_value(value))
    except (ValueError, TypeError):
        # A forged input can include arbitrary private text in otherwise forbidden fields.
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID") from None


def parse_native_private_chat_query_checkpoint_v2(
    value: object,
) -> NativePrivateChatQueryCheckpointV2:
    try:
        return NativePrivateChatQueryCheckpointV2.model_validate(
            raw_similarity_contract_value(value)
        )
    except (ValueError, TypeError):
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID") from None


def parse_native_private_chat_query_checkpoint_v21(
    value: object,
) -> NativePrivateChatQueryCheckpointV21:
    try:
        return NativePrivateChatQueryCheckpointV21.model_validate(
            raw_similarity_contract_value(value)
        )
    except (ValueError, TypeError):
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID") from None


def parse_supported_native_private_chat_query_checkpoint(
    value: object,
) -> SupportedNativePrivateChatQueryCheckpoint:
    value = raw_similarity_contract_value(value)
    if (
        isinstance(value, dict)
        and value.get("schema_version") == "native-private-chat-query-coordinator/2.1"
    ):
        return parse_native_private_chat_query_checkpoint_v21(value)
    if (
        isinstance(value, dict)
        and value.get("schema_version") == "native-private-chat-query-coordinator/2.0"
    ):
        return parse_native_private_chat_query_checkpoint_v2(value)
    return parse_native_private_chat_query_checkpoint(value)


def native_private_chat_query_checkpoint(
    launch: PrivateChatQueryLaunchAssociation,
    phase: NativeQueryPhase,
    payload: NativePrivateQueryPayload,
) -> NativePrivateChatQueryCheckpoint:
    return parse_native_private_chat_query_checkpoint(
        _private_chat_query_checkpoint_document(launch, phase, payload, version="1.0")
    )


def native_private_chat_public_query_checkpoint(
    launch: PrivateChatQueryLaunchAssociation,
    phase: NativeQueryPhase,
    payload: NativePrivateQueryPayloadV2,
) -> NativePrivateChatQueryCheckpointV2:
    return parse_native_private_chat_query_checkpoint_v2(
        _private_chat_query_checkpoint_document(launch, phase, payload, version="2.0")
    )


def native_private_chat_gpu_query_checkpoint(
    launch: PrivateChatQueryLaunchAssociation,
    phase: NativeQueryPhase,
    payload: NativePrivateQueryPayloadV21,
) -> NativePrivateChatQueryCheckpointV21:
    """Explicit successor; historical CPU builders never silently change families."""
    return parse_native_private_chat_query_checkpoint_v21(
        _private_chat_query_checkpoint_document(launch, phase, payload, version="2.1")
    )


def supported_native_private_chat_query_checkpoint(
    request: SupportedPrivateChatQueryWorkflowRequest,
    launch: PrivateChatQueryLaunchAssociation,
    phase: NativeQueryPhase,
    payload: SupportedNativePrivateQueryPayload,
) -> SupportedNativePrivateChatQueryCheckpoint:
    """Select the original request family, not a new launch or an execution grant."""
    request = parse_supported_private_chat_query_workflow_request(request)
    if launch.workflow_request_sha256 != request.request_sha256:
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID")
    return parse_supported_native_private_chat_query_checkpoint(
        _private_chat_query_checkpoint_document(
            launch,
            phase,
            payload,
            version="2.0" if isinstance(request, PrivateChatQueryWorkflowRequestV2) else "1.0",
        )
    )


def _private_chat_query_checkpoint_document(
    launch: PrivateChatQueryLaunchAssociation,
    phase: NativeQueryPhase,
    payload: SupportedNativePrivateQueryPayload,
    *,
    version: Literal["1.0", "2.0", "2.1"],
) -> dict[str, Any]:
    launch = PrivateChatQueryLaunchAssociation.model_validate(raw_similarity_contract_value(launch))
    payloads = _PAYLOAD_FAMILIES["native-private-chat-query-coordinator/" + version]
    if phase not in payloads or type(payload) is not payloads[phase]:
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_PURPOSE_INVALID")
    payload = type(payload).model_validate(raw_similarity_contract_value(payload))
    body = {
        "schema_version": "native-private-chat-query-coordinator/" + version,
        "record_type": phase,
        "native_launch_job_id": launch.native_launch_job_id,
        "association_sha256": launch.association_sha256,
        "payload": payload.model_dump(mode="json"),
    }
    return body | {"checkpoint_sha256": content_sha256(body)}


def private_chat_query_checkpoint_receipt(
    request: PrivateChatQueryWorkflowRequest,
    launch: PrivateChatQueryLaunchAssociation,
    allocation: NativePrivateQueryAllocation,
    executed: NativePrivateQueryExecuted,
    published: NativePrivateQueryPublished,
) -> PrivateChatQueryWorkflowReceipt:
    """Reconstruct text-free metadata, not physical/source/Artifact validation."""
    return PrivateChatQueryWorkflowReceipt.model_validate(
        _private_chat_query_checkpoint_receipt_body(
            request, launch, allocation, executed, published
        )
    )


def private_chat_public_query_checkpoint_receipt(
    request: PrivateChatQueryWorkflowRequestV2,
    launch: PrivateChatQueryLaunchAssociation,
    allocation: NativePrivateQueryAllocation,
    executed: NativePrivateQueryExecuted | NativePrivateQueryBatchExecuted,
    published: NativePrivateQueryPublishedV2,
) -> PrivateChatQueryWorkflowReceiptV2:
    return PrivateChatQueryWorkflowReceiptV2.model_validate(
        _private_chat_query_checkpoint_receipt_body(
            request, launch, allocation, executed, published
        )
    )


def supported_private_chat_query_checkpoint_receipt(
    request: SupportedPrivateChatQueryWorkflowRequest,
    launch: PrivateChatQueryLaunchAssociation,
    allocation: NativePrivateQueryAllocation,
    executed: NativePrivateQueryExecuted | NativePrivateQueryBatchExecuted,
    published: NativePrivateQueryPublished | NativePrivateQueryPublishedV2,
) -> PrivateChatQueryWorkflowReceipt | PrivateChatQueryWorkflowReceiptV2:
    """One exact family choice around the unchanged predecessor/successor receipt rules."""
    request = parse_supported_private_chat_query_workflow_request(request)
    if isinstance(request, PrivateChatQueryWorkflowRequestV2):
        if not isinstance(published, NativePrivateQueryPublishedV2):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID")
        return private_chat_public_query_checkpoint_receipt(
            request, launch, allocation, executed, published
        )
    if not isinstance(published, NativePrivateQueryPublished) or not isinstance(
        executed, NativePrivateQueryExecuted
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID")
    return private_chat_query_checkpoint_receipt(request, launch, allocation, executed, published)


def _private_chat_query_checkpoint_receipt_body(
    request: PrivateChatQueryWorkflowRequest | PrivateChatQueryWorkflowRequestV2,
    launch: PrivateChatQueryLaunchAssociation,
    allocation: NativePrivateQueryAllocation,
    executed: NativePrivateQueryExecuted | NativePrivateQueryBatchExecuted,
    published: _NativePrivateQueryPublishedFields,
) -> dict[str, Any]:
    if isinstance(executed, NativePrivateQueryBatchExecuted) and (
        not isinstance(request, PrivateChatQueryWorkflowRequestV2)
        or request.resource_profile.device != "CUDA"
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_PURPOSE_INVALID")
    version = "2.0" if isinstance(request, PrivateChatQueryWorkflowRequestV2) else "1.0"
    body = {
        "schema_version": "private-chat-query-workflow-receipt/" + version,
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
        "execution_result_schema": (
            "embedding-reference-query-result@2.0"
            if version == "2.0"
            else "embedding-private-chat-query-result@1.0"
        ),
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
    return body | {"receipt_sha256": content_sha256(body)}


def validate_native_private_chat_query_history(
    records: tuple[SupportedNativePrivateChatQueryCheckpoint, ...],
    launch: PrivateChatQueryLaunchAssociation,
    request: PrivateChatQueryWorkflowRequest | PrivateChatQueryWorkflowRequestV2,
) -> None:
    public = isinstance(request, PrivateChatQueryWorkflowRequestV2)
    request = (
        PrivateChatQueryWorkflowRequestV2.model_validate(raw_similarity_contract_value(request))
        if public
        else PrivateChatQueryWorkflowRequest.model_validate(raw_similarity_contract_value(request))
    )
    launch = PrivateChatQueryLaunchAssociation.model_validate(raw_similarity_contract_value(launch))
    body = {
        "schema_version": "private-chat-query-execution-record/2.0"
        if public
        else "private-chat-query-execution-record/1.0",
        "purpose": "PRIVATE_CHAT_QUERY",
        "workflow_request": request.model_dump(mode="json"),
        "launch": launch.model_dump(mode="json"),
    }
    intent = (
        PrivateChatPublicQueryExecutionRecord.model_validate(
            body | {"record_sha256": content_sha256(body)}
        )
        if public
        else PrivateChatQueryExecutionRecord.model_validate(
            body | {"record_sha256": content_sha256(body)}
        )
    )
    checked = tuple(
        parse_supported_native_private_chat_query_checkpoint(value) for value in records
    )
    gpu = bool(checked) and type(checked[0]) is NativePrivateChatQueryCheckpointV21
    expected_type = (
        NativePrivateChatQueryCheckpointV21
        if gpu
        else NativePrivateChatQueryCheckpointV2
        if public
        else NativePrivateChatQueryCheckpoint
    )
    if (
        (gpu and (not public or request.resource_profile.device != "CUDA"))
        or any(type(row) is not expected_type for row in checked)
        or len(checked) > 4
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
    assert isinstance(executed, (NativePrivateQueryExecuted, NativePrivateQueryBatchExecuted))
    if executed.completed_observed_at < allocation.allocation.created_at:
        raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_ORDER_INVALID")
    if len(checked) < 3:
        return
    published = checked[2].payload
    assert isinstance(published, (NativePrivateQueryPublished, NativePrivateQueryPublishedV2))
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
    receipt: PrivateChatQueryWorkflowReceipt | PrivateChatQueryWorkflowReceiptV2
    if isinstance(request, PrivateChatQueryWorkflowRequestV2):
        if not isinstance(published, NativePrivateQueryPublishedV2):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_PURPOSE_INVALID")
        receipt = private_chat_public_query_checkpoint_receipt(
            request, launch, allocation, executed, published
        )
    else:
        if not isinstance(published, NativePrivateQueryPublished) or not isinstance(
            executed, NativePrivateQueryExecuted
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_PURPOSE_INVALID")
        receipt = private_chat_query_checkpoint_receipt(
            request, launch, allocation, executed, published
        )
    if len(checked) == 4:
        completed = checked[3].payload
        assert isinstance(completed, (NativePrivateQueryCompleted, NativePrivateQueryCompletedV2))
        output = completed.output
        if (
            output.receipt.artifact_id != allocation.allocation.receipt_producer.artifact_id
            or output.receipt.artifact_revision_id
            != allocation.allocation.receipt_producer.artifact_revision_id
            or output.receipt.sha256 != sha256_bytes(canonical_json_bytes(receipt))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_COMPLETION_INVALID")
        if isinstance(completed, NativePrivateQueryCompletedV2) and isinstance(
            receipt, PrivateChatQueryWorkflowReceiptV2
        ):
            validate_private_chat_public_query_step_output(completed.output, receipt)
        elif isinstance(completed, NativePrivateQueryCompleted) and isinstance(
            receipt, PrivateChatQueryWorkflowReceipt
        ):
            validate_private_chat_query_step_output(completed.output, receipt)
        else:
            raise ValueError("PRIVATE_CHAT_QUERY_CHECKPOINT_PURPOSE_INVALID")
