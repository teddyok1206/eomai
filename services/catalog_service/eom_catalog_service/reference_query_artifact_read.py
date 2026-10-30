"""Canonical QUERY file-set resolution only; actual current execution admission is external."""

from __future__ import annotations

import json
from dataclasses import dataclass

from eom_catalog_contracts.embedding_reference_query import (
    MAX_REFERENCE_QUERY_BYTES,
    EmbeddingReferenceQueryResult,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import parse_embedding_shard
from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EMBEDDING_REFERENCE_QUERY_ARTIFACT_TYPE
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.reference_query_execution import (
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    ReferenceQueryWorkflowReceipt,
    ReferenceQueryWorkflowReceiptV2,
    ReferenceQueryWorkflowRequestV3,
    SupportedReferenceQueryNativeInput,
    SupportedReferenceQueryNativeResult,
    SupportedReferenceQueryWorkflowIntent,
    SupportedReferenceQueryWorkflowReceipt,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_workflow_receipt,
    validate_reference_query_workflow_receipt,
)
from sqlalchemy.orm import Session

from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class ResolvedReferenceQueryArtifacts:
    """Materialized canonical values, NOT a verified native-execution/source grant."""

    request: EmbeddingReferenceQueryInputV11
    result: EmbeddingReferenceQueryResult
    binary: bytes
    publication_job_id: str


@dataclass(frozen=True, slots=True)
class ResolvedPublicSolutionQueryArtifacts:
    """Materialized QUERY2 bytes, not the actual producer/source execution authority."""

    request: PublicSolutionQueryInput
    result: PublicSolutionQueryResult
    binary: bytes
    publication_job_id: str


class CatalogReferenceQueryArtifacts:
    """Caller must retain current source/execution authority around this storage read.

    This adapter never authorizes a caller, creates a job, starts a unit, resolves
    latest or returns the consumer's stronger VerifiedReferenceQueryRead capability.
    """

    def __init__(
        self,
        session: Session,
        settings: CatalogSettings,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> None:
        self.reader = (
            PinnedArtifactReadContext(session, settings)
            if artifact_reader is None
            else artifact_reader
        )
        self.reader.require_session(session)
        if self.reader.settings != settings:
            raise ValueError("REFERENCE_QUERY_READ_SETTINGS_MISMATCH")

    def resolve_publication(
        self,
        *,
        workflow_request: SupportedReferenceQueryWorkflowRequest,
        policy: ReferenceQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: ReferenceQueryLaunchAssociation,
        receipt: ReferenceQueryWorkflowReceipt,
        workflow_id: str,
        step_run_id: str,
        receipt_owner_job_id: str,
        manifest_sha256: str | None = None,
    ) -> ResolvedReferenceQueryArtifacts:
        receipt = parse_reference_query_workflow_receipt(receipt)
        resolved = self._resolve_publication(
            workflow_request=workflow_request,
            policy=policy,
            bundle=bundle,
            launch=launch,
            receipt=receipt,
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            receipt_owner_job_id=receipt_owner_job_id,
            manifest_sha256=manifest_sha256,
        )
        if not isinstance(resolved, ResolvedReferenceQueryArtifacts):
            raise ValueError("REFERENCE_QUERY_READ_FAMILY_MISMATCH")
        return resolved

    def resolve_public_solution_publication(
        self,
        *,
        workflow_request: ReferenceQueryWorkflowRequestV3,
        policy: ReferenceQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: ReferenceQueryLaunchAssociation,
        receipt: ReferenceQueryWorkflowReceiptV2,
        workflow_id: str,
        step_run_id: str,
        receipt_owner_job_id: str,
        manifest_sha256: str | None = None,
    ) -> ResolvedPublicSolutionQueryArtifacts:
        receipt = ReferenceQueryWorkflowReceiptV2.model_validate(receipt)
        resolved = self._resolve_publication(
            workflow_request=workflow_request,
            policy=policy,
            bundle=bundle,
            launch=launch,
            receipt=receipt,
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            receipt_owner_job_id=receipt_owner_job_id,
            manifest_sha256=manifest_sha256,
        )
        if not isinstance(resolved, ResolvedPublicSolutionQueryArtifacts):
            raise ValueError("REFERENCE_QUERY_READ_FAMILY_MISMATCH")
        return resolved

    def _resolve_publication(
        self,
        *,
        workflow_request: SupportedReferenceQueryWorkflowIntent,
        policy: ReferenceQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: ReferenceQueryLaunchAssociation,
        receipt: SupportedReferenceQueryWorkflowReceipt,
        workflow_id: str,
        step_run_id: str,
        receipt_owner_job_id: str,
        manifest_sha256: str | None,
    ) -> ResolvedReferenceQueryArtifacts | ResolvedPublicSolutionQueryArtifacts:
        input_pointer = receipt.query_input
        pointers = (
            input_pointer,
            receipt.query_execution.result_member,
            receipt.shard,
            receipt.binary,
        )
        self.reader.prefetch(((input_pointer.artifact_id, input_pointer.artifact_revision_id),))
        self.reader.require_file_set(
            input_pointer.artifact_id,
            input_pointer.artifact_revision_id,
            ("input.json", "result.json", "shard.json", "vectors.f32"),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
            manifest_sha256=manifest_sha256,
        )
        producers: set[str] = set()

        def read(pointer: ArtifactMemberPointer, maximum: int) -> bytes:
            member = self.reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(EMBEDDING_REFERENCE_QUERY_ARTIFACT_TYPE,),
                expected_primary_file="result.json",
                max_bytes=maximum,
            )
            producers.add(member.producer_job_id)
            return member.payload

        def document(pointer: ArtifactMemberPointer) -> object:
            raw = read(pointer, MAX_REFERENCE_QUERY_BYTES)
            value: object = json.loads(raw)
            if canonical_json_bytes(value) != raw:
                raise ValueError("REFERENCE_QUERY_ARTIFACT_NONCANONICAL")
            return value

        native_input: SupportedReferenceQueryNativeInput
        result: SupportedReferenceQueryNativeResult
        if isinstance(receipt, ReferenceQueryWorkflowReceiptV2):
            native_input = PublicSolutionQueryInput.model_validate(document(pointers[0]))
            result = PublicSolutionQueryResult.model_validate(document(pointers[1]))
        else:
            native_input = parse_embedding_reference_query_input_v11(document(pointers[0]))
            result = parse_embedding_reference_query_result(document(pointers[1]))
        shard_document = document(pointers[2])
        if not isinstance(shard_document, dict):
            raise ValueError("REFERENCE_QUERY_CANONICAL_SHARD_INVALID")
        if parse_embedding_shard(shard_document) != result.shard:
            raise ValueError("REFERENCE_QUERY_CANONICAL_SHARD_MISMATCH")
        binary = read(pointers[3], result.shard.binary.byte_count)
        read_unit_vectors(
            binary,
            dimension=result.shard.dimension,
            row_count=result.shard.row_count,
            expected_sha256=result.shard.binary.sha256,
        )
        if producers != {receipt.query_artifact_owner_job_id}:
            raise ValueError("REFERENCE_QUERY_PUBLICATION_PRODUCER_MISMATCH")
        validate_reference_query_workflow_receipt(
            receipt,
            workflow_request,
            policy,
            bundle,
            launch,
            native_input,
            result,
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            query_artifact_owner_job_id=receipt.query_artifact_owner_job_id,
            receipt_owner_job_id=receipt_owner_job_id,
        )
        if isinstance(native_input, PublicSolutionQueryInput):
            if not isinstance(result, PublicSolutionQueryResult):
                raise ValueError("REFERENCE_QUERY_READ_FAMILY_MISMATCH")
            return ResolvedPublicSolutionQueryArtifacts(
                native_input, result, binary, receipt.query_artifact_owner_job_id
            )
        if not isinstance(result, EmbeddingReferenceQueryResult):
            raise ValueError("REFERENCE_QUERY_READ_FAMILY_MISMATCH")
        return ResolvedReferenceQueryArtifacts(
            native_input, result, binary, receipt.query_artifact_owner_job_id
        )
