"""Resolve a completion through the existing committed/approved Artifact boundary."""

from __future__ import annotations

import json

from eom_catalog_contracts.embedding_reference_query import MAX_REFERENCE_QUERY_BYTES
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_completion_artifacts import (
    NATIVE_COMPLETION_ARTIFACT_TYPE,
    PRIVATE_CHAT_QUERY_COMPLETION_ARTIFACT_TYPE,
    QUERY_COMPLETION_ARTIFACT_TYPE,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_workflow_receipt import (
    MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    SupportedLocalEmbeddingStepOutput,
    SupportedLocalEmbeddingWorkflowReceipt,
    parse_supported_local_embedding_step_output,
    parse_supported_local_embedding_workflow_receipt,
    validate_supported_local_embedding_step_output,
)
from eom_workflow.private_chat_query_workflow import (
    MAX_PRIVATE_CHAT_QUERY_RECEIPT_BYTES,
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_step_output,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    ReferenceQueryStepOutputV2,
    ReferenceQueryWorkflowReceipt,
    ReferenceQueryWorkflowReceiptV2,
    SupportedReferenceQueryStepOutput,
    SupportedReferenceQueryWorkflowReceipt,
    parse_reference_query_step_output,
    parse_supported_reference_query_workflow_receipt,
    validate_reference_query_step_output,
)
from sqlalchemy.orm import Session

from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactMember,
    PinnedArtifactReadContext,
)
from eom_catalog_service.settings import CatalogSettings


def resolve_native_embedding_completion(
    session: Session, settings: CatalogSettings, output: SupportedLocalEmbeddingStepOutput
) -> SupportedLocalEmbeddingWorkflowReceipt:
    """Current Identity/source admission is REQUIRED before calling this read.

    A valid carrier or receipt never grants permission. This boundary checks actual
    producer/commit/lifecycle/member/hash; registration and current scope belong to
    the supported Catalog registration-observation use case in the SAME root.
    """
    output = parse_supported_local_embedding_step_output(output)
    materialized = _read_receipt(
        session,
        settings,
        output.receipt,
        NATIVE_COMPLETION_ARTIFACT_TYPE,
        MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES,
    )
    body = json.loads(materialized.payload)
    if canonical_json_bytes(body) != materialized.payload:
        raise ValueError("LOCAL_EMBEDDING_RECEIPT_NONCANONICAL")
    receipt = parse_supported_local_embedding_workflow_receipt(body)
    if materialized.producer_job_id != receipt.receipt_owner_job_id:
        raise ValueError("LOCAL_EMBEDDING_RECEIPT_PRODUCER_MISMATCH")
    validate_supported_local_embedding_step_output(output, receipt)
    return receipt


def resolve_native_reference_query_completion(
    session: Session,
    settings: CatalogSettings,
    output: ReferenceQueryStepOutput,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> ReferenceQueryWorkflowReceipt:
    """Canonical read only; caller must separately validate current source/Job closure."""
    output = parse_reference_query_step_output(output)
    receipt = _resolve_reference_query_completion(
        session, settings, output, artifact_reader=artifact_reader
    )
    if not isinstance(receipt, ReferenceQueryWorkflowReceipt):
        raise ValueError("REFERENCE_QUERY_RECEIPT_FAMILY_MISMATCH")
    return receipt


def resolve_native_public_solution_query_completion(
    session: Session,
    settings: CatalogSettings,
    output: ReferenceQueryStepOutputV2,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> ReferenceQueryWorkflowReceiptV2:
    """QUERY2 canonical receipt only; no source, Workflow or physical execution grant."""
    output = ReferenceQueryStepOutputV2.model_validate(output)
    receipt = _resolve_reference_query_completion(
        session, settings, output, artifact_reader=artifact_reader
    )
    if not isinstance(receipt, ReferenceQueryWorkflowReceiptV2):
        raise ValueError("REFERENCE_QUERY_RECEIPT_FAMILY_MISMATCH")
    return receipt


def _resolve_reference_query_completion(
    session: Session,
    settings: CatalogSettings,
    output: SupportedReferenceQueryStepOutput,
    *,
    artifact_reader: PinnedArtifactReadContext | None,
) -> SupportedReferenceQueryWorkflowReceipt:
    materialized = _read_receipt(
        session,
        settings,
        output.receipt,
        QUERY_COMPLETION_ARTIFACT_TYPE,
        MAX_REFERENCE_QUERY_BYTES,
        artifact_reader=artifact_reader,
    )
    body = json.loads(materialized.payload)
    if canonical_json_bytes(body) != materialized.payload:
        raise ValueError("REFERENCE_QUERY_RECEIPT_NONCANONICAL")
    receipt = parse_supported_reference_query_workflow_receipt(body)
    if (
        materialized.producer_job_id != receipt.receipt_owner_job_id
        or len(
            {
                receipt.receipt_owner_job_id,
                receipt.query_artifact_owner_job_id,
                receipt.native_launch_job_id,
            }
        )
        != 3
    ):
        raise ValueError("REFERENCE_QUERY_RECEIPT_PRODUCER_MISMATCH")
    validate_reference_query_step_output(output, receipt)
    return receipt


def resolve_native_private_chat_query_completion(
    session: Session,
    settings: CatalogSettings,
    output: PrivateChatQueryStepOutput,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> PrivateChatQueryWorkflowReceipt:
    """Receipt provenance only; current owned-source/public scope admission is upstream."""
    root = session.get_transaction()
    if (
        root is None
        or not root.is_active
        or session.in_nested_transaction()
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_READ_ROOT_INVALID")
    output = PrivateChatQueryStepOutput.model_validate(output)
    reader = (
        PinnedArtifactReadContext(session, settings) if artifact_reader is None else artifact_reader
    )
    materialized = _read_receipt(
        session,
        settings,
        output.receipt,
        PRIVATE_CHAT_QUERY_COMPLETION_ARTIFACT_TYPE,
        MAX_PRIVATE_CHAT_QUERY_RECEIPT_BYTES,
        artifact_reader=reader,
    )
    body = json.loads(materialized.payload)
    if canonical_json_bytes(body) != materialized.payload:
        raise ValueError("PRIVATE_CHAT_QUERY_RECEIPT_NONCANONICAL")
    receipt = PrivateChatQueryWorkflowReceipt.model_validate(body)
    if materialized.producer_job_id != receipt.receipt_owner_job_id:
        raise ValueError("PRIVATE_CHAT_QUERY_RECEIPT_PRODUCER_MISMATCH")
    validate_private_chat_query_step_output(output, receipt)
    # Initial capture/file hashes do not prove current approval after materialization.
    reader.revalidate_provenance()
    if (
        session.get_transaction() is not root
        or not root.is_active
        or session.in_nested_transaction()
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_READ_ROOT_INVALID")
    return receipt


def _read_receipt(
    session: Session,
    settings: CatalogSettings,
    pointer: ArtifactMemberPointer,
    artifact_type: str,
    maximum: int,
    *,
    artifact_reader: PinnedArtifactReadContext | None = None,
) -> PinnedArtifactMember:
    reader = (
        PinnedArtifactReadContext(session, settings) if artifact_reader is None else artifact_reader
    )
    reader.require_session(session)
    if reader.settings != settings:
        raise ValueError("NATIVE_COMPLETION_READ_SETTINGS_MISMATCH")
    reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
    reader.require_file_set(
        pointer.artifact_id,
        pointer.artifact_revision_id,
        ("receipt.json",),
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
    )
    return reader.read_pinned(
        **pointer.model_dump(mode="python"),
        expected_artifact_types=(artifact_type,),
        expected_primary_file="receipt.json",
        max_bytes=maximum,
    )
