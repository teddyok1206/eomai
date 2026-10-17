"""Pinned private numeric file set, never current Chat/source or execution authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from eom_catalog_contracts.embedding_private_chat_query import (
    MAX_PRIVATE_CHAT_QUERY_BYTES,
    EmbeddingPrivateChatQueryInput,
    EmbeddingPrivateChatQueryResult,
    validate_private_chat_query_result,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import parse_embedding_shard
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
)
from eom_workflow.private_chat_query_publication import (
    PrivateChatQueryExecutionRecord,
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_workflow_receipt,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class ResolvedPrivateChatQueryArtifacts:
    """Canonical local materialization only; ownership/native grant remains upstream."""

    request: EmbeddingPrivateChatQueryInput = field(repr=False)
    result: EmbeddingPrivateChatQueryResult
    binary: bytes = field(repr=False)
    publication_job_id: str


class CatalogPrivateChatQueryArtifacts:
    def __init__(
        self,
        session: Session,
        settings: CatalogSettings,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> None:
        self.session, self.root = session, session.get_transaction()
        self.reader = (
            PinnedArtifactReadContext(session, settings)
            if artifact_reader is None
            else artifact_reader
        )
        if self.reader.settings != settings:
            raise ValueError("PRIVATE_CHAT_QUERY_ARTIFACT_READ_ROOT_INVALID")
        self._require_root()

    def _require_root(self) -> None:
        session = self.session
        if (
            self.root is None
            or not self.root.is_active
            or not session.is_active
            or session.get_transaction() is not self.root
            or session.in_nested_transaction()
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_ARTIFACT_READ_ROOT_INVALID")
        self.reader.require_session(session)

    def resolve_publication(
        self,
        *,
        workflow_request: PrivateChatQueryWorkflowRequest,
        policy: PrivateChatQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: PrivateChatQueryLaunchAssociation,
        native_input: EmbeddingPrivateChatQueryInput,
        receipt: PrivateChatQueryWorkflowReceipt,
        origin: ChatPrivateQueryOrigin,
        workflow_id: str,
        step_run_id: str,
        receipt_owner_job_id: str,
        manifest_sha256: str,
    ) -> ResolvedPrivateChatQueryArtifacts:
        """Current-owned input is supplied; the committed file set contains no question copy."""
        self._require_root()
        try:
            TypeAdapter(Sha256).validate_python(manifest_sha256, strict=True)
            native_input = EmbeddingPrivateChatQueryInput.model_validate(
                raw_similarity_contract_value(native_input)
            )
            receipt = PrivateChatQueryWorkflowReceipt.model_validate(
                raw_similarity_contract_value(receipt)
            )
            expected_record = validate_private_chat_query_launch(
                launch, workflow_request, policy, bundle, native_input
            )
            pointers = (
                receipt.execution_record,
                receipt.query_execution.result_member,
                receipt.shard,
                receipt.binary,
            )
            primary = pointers[0]
            self.reader.prefetch(((primary.artifact_id, primary.artifact_revision_id),))
            self.reader.require_file_set(
                primary.artifact_id,
                primary.artifact_revision_id,
                ("intent.json", "result.json", "shard.json", "vectors.f32"),
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
                manifest_sha256=manifest_sha256,
            )
            producers: set[str] = set()

            def read(pointer: ArtifactMemberPointer, maximum: int) -> bytes:
                member = self.reader.read_pinned(
                    **pointer.model_dump(mode="python"),
                    expected_artifact_types=(EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE,),
                    expected_primary_file="result.json",
                    max_bytes=maximum,
                )
                producers.add(member.producer_job_id)
                return member.payload

            def document(pointer: ArtifactMemberPointer) -> object:
                raw = read(pointer, MAX_PRIVATE_CHAT_QUERY_BYTES)
                value: object = json.loads(raw)
                if canonical_json_bytes(value) != raw:
                    raise ValueError()
                return value

            record = PrivateChatQueryExecutionRecord.model_validate(document(pointers[0]))
            result = EmbeddingPrivateChatQueryResult.model_validate(document(pointers[1]))
            validate_private_chat_query_result(native_input, result)
            shard = document(pointers[2])
            if (
                record != expected_record
                or not isinstance(shard, dict)
                or parse_embedding_shard(shard) != result.shard
            ):
                raise ValueError()
            binary = read(pointers[3], native_input.spaces.query.model_spec.dimension * 4)
            read_unit_vectors(
                binary,
                dimension=result.shard.dimension,
                row_count=1,
                expected_sha256=result.shard.binary.sha256,
            )
            if producers != {receipt.query_artifact_owner_job_id}:
                raise ValueError()
            validate_private_chat_query_workflow_receipt(
                receipt,
                workflow_request,
                policy,
                bundle,
                launch,
                native_input,
                result,
                origin=origin,
                workflow_id=workflow_id,
                step_run_id=step_run_id,
                query_artifact_owner_job_id=receipt.query_artifact_owner_job_id,
                receipt_owner_job_id=receipt_owner_job_id,
            )
            self.reader.revalidate_provenance()
            self._require_root()
            return ResolvedPrivateChatQueryArtifacts(
                native_input, result, binary, receipt.query_artifact_owner_job_id
            )
        except (ValueError, TypeError, SchemaError, OSError):
            raise ValueError("PRIVATE_CHAT_QUERY_ARTIFACT_READ_INVALID") from None
