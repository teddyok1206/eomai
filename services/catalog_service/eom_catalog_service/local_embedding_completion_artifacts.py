"""Resolve a completion through the existing committed/approved Artifact boundary."""

from __future__ import annotations

import json

from eom_identifiers import canonical_json_bytes
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_completion_artifacts import NATIVE_COMPLETION_ARTIFACT_TYPE
from eom_workflow.local_embedding_workflow_receipt import (
    MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES,
    LocalEmbeddingStepOutput,
    LocalEmbeddingWorkflowReceipt,
    parse_local_embedding_step_output,
    parse_local_embedding_workflow_receipt,
    validate_local_embedding_step_output,
)
from sqlalchemy.orm import Session

from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings


def resolve_native_embedding_completion(
    session: Session, settings: CatalogSettings, output: LocalEmbeddingStepOutput
) -> LocalEmbeddingWorkflowReceipt:
    """Current Identity/source admission is REQUIRED before calling this read.

    A valid carrier or receipt never grants permission. This boundary checks actual
    producer/commit/lifecycle/member/hash; registration and current scope belong to
    the supported Catalog registration-observation use case in the SAME root.
    """
    output = parse_local_embedding_step_output(output)
    pointer = output.receipt
    reader = PinnedArtifactReadContext(session, settings)
    reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
    reader.require_file_set(
        pointer.artifact_id,
        pointer.artifact_revision_id,
        ("receipt.json",),
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
    )
    materialized = reader.read_pinned(
        **pointer.model_dump(mode="python"),
        expected_artifact_types=(NATIVE_COMPLETION_ARTIFACT_TYPE,),
        expected_primary_file="receipt.json",
        max_bytes=MAX_LOCAL_EMBEDDING_WORKFLOW_RECEIPT_BYTES,
    )
    body = json.loads(materialized.payload)
    if canonical_json_bytes(body) != materialized.payload:
        raise ValueError("LOCAL_EMBEDDING_RECEIPT_NONCANONICAL")
    receipt = parse_local_embedding_workflow_receipt(body)
    if materialized.producer_job_id != receipt.receipt_owner_job_id:
        raise ValueError("LOCAL_EMBEDDING_RECEIPT_PRODUCER_MISMATCH")
    validate_local_embedding_step_output(output, receipt)
    return receipt
