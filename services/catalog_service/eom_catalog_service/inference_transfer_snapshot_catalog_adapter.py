"""Catalog-owned authorized snapshot producer, not an installed transport operation.

Identity/permission/source/report admission precedes bounded owner Artifact reads.
The CPU harness and workers never receive database or NAS access from this port.
"""

from __future__ import annotations

import json
from typing import Any, cast

from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2, CreateEvidenceBundleCommand
from eom_catalog_contracts.inference_transfer_experiment import (
    MAX_GRAPH_BASELINE_CANDIDATES,
    StagedExperimentEntry,
    SuppliedGraphBaseline,
    profile_key,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotHeader,
    InferenceTransferSnapshotIndexEntry,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotRecord,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import content_sha256
from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    ControlArtifactResolutionError,
    resolve_control_artifact_members,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from eom_catalog_service.inference_transfer_catalog_adapter import (
    AcceptedInferenceTransferProfileInput,
    CatalogInferenceTransferSourceAdapter,
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_item_projection import project_staged_item_entry
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_snapshot_service import (
    AuthorizedSnapshotCapture,
    hashed_snapshot_value,
    prepare_snapshot_value,
    validate_snapshot_selection,
)
from eom_catalog_service.item_content_contract import ITEM_CONTENT_SCHEMAS, read_item_content
from eom_catalog_service.knowledge_graph_projection import knowledge_node_terms
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalServiceError,
    ReadOnlyCandidatePoolScope,
)
from eom_catalog_service.settings import CatalogSettings

_MAXIMUM_ITEM_MEMBER_BYTES = 16 * 1024**2
_MAXIMUM_ARTIFACT_BATCH_BYTES = 128 * 1024**2


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate canonical Item JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


class CatalogInferenceTransferSnapshotSourceAdapter:
    """Actual-actor owner port; every capture recomputes the complete exact scope."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.engine = engine
        self.sources = CatalogInferenceTransferSourceAdapter(engine, settings)

    def _materialize_entries(
        self,
        request: InferenceTransferSnapshotPrepareRequest,
        inputs: tuple[AcceptedInferenceTransferProfileInput, ...],
    ) -> dict[str, StagedExperimentEntry]:
        """One explicit owner-local materialization; exact member checks precede parsing."""
        pointers: dict[ArtifactMemberPointer, int] = {}
        inputs_by_pointer: dict[
            ArtifactMemberPointer, list[AcceptedInferenceTransferProfileInput]
        ] = {}
        result: dict[str, StagedExperimentEntry] = {}
        for value in inputs:
            profile = value.profile
            run_id = profile.source_basis.solution_evidence.base_analysis_run_id
            member = profile.source_basis.source.artifact_member
            unavailable: str | None = None
            if member.media_type != "application/json":
                unavailable = "INFERENCE_ITEM_CONTENT_MEDIA_TYPE_UNAVAILABLE"
            elif member.schema_ref not in ITEM_CONTENT_SCHEMAS:
                unavailable = "INFERENCE_ITEM_CONTENT_SCHEMA_UNAVAILABLE"
            elif member.bytes > _MAXIMUM_ITEM_MEMBER_BYTES:
                unavailable = "INFERENCE_ITEM_CONTENT_BYTES_TOO_LARGE"
            else:
                pointer = ArtifactMemberPointer(
                    artifact_id=member.artifact_id,
                    artifact_revision_id=member.artifact_revision_id,
                    member_path=member.member_path,
                    schema_ref=cast(str, member.schema_ref),
                    media_type=member.media_type,
                    sha256=member.sha256,
                )
                if pointer in pointers and pointers[pointer] != member.bytes:
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                pointers[pointer] = member.bytes
                inputs_by_pointer.setdefault(pointer, []).append(value)
            if unavailable is not None:
                result[run_id] = StagedExperimentEntry(
                    profile=profile,
                    content=None,
                    metadata=(),
                    limitations=(unavailable,),
                )
        batch: list[BoundedControlArtifactRead] = []
        batch_bytes = 0

        def read_batch() -> None:
            if not batch:
                return
            try:
                values = resolve_control_artifact_members(self.engine, tuple(batch))
            except ControlArtifactResolutionError as exc:
                raise InferenceTransferServiceError(
                    "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH"
                ) from exc
            if len(values) != len(batch):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
            for read, payload in zip(batch, values, strict=True):
                pointer = cast(ArtifactMemberPointer, read.pointer)
                if len(payload) != pointers[pointer]:
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                try:
                    document = json.loads(
                        payload.decode("utf-8"),
                        object_pairs_hook=_unique_json_object,
                        parse_constant=_reject_json_constant,
                    )
                    if not isinstance(document, dict):
                        raise ValueError("canonical Item must be a JSON object")
                    item = read_item_content(pointer.schema_ref, document)
                    # Parse one canonical member once, but preserve each exact
                    # profile/report identity when the member is shared.
                    for value in inputs_by_pointer[pointer]:
                        run_id = value.profile.source_basis.solution_evidence.base_analysis_run_id
                        result[run_id] = project_staged_item_entry(
                            profile=value.profile,
                            item=item,
                            accepted_report=value.report,
                            recipe=request.recipe,
                        )
                except (UnicodeError, ValueError) as exc:
                    raise InferenceTransferServiceError(
                        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH"
                    ) from exc
            batch.clear()

        for pointer, size in pointers.items():
            if len(batch) == 128 or batch_bytes + size > _MAXIMUM_ARTIFACT_BATCH_BYTES:
                read_batch()
                batch_bytes = 0
            batch.append(BoundedControlArtifactRead(pointer, maximum_bytes=size))
            batch_bytes += size
        read_batch()
        return result

    def _baselines(
        self,
        session: Session,
        request: InferenceTransferSnapshotPrepareRequest,
        scope: ReadOnlyCandidatePoolScope,
        entries: dict[str, StagedExperimentEntry],
        eligible_inputs: tuple[AcceptedInferenceTransferProfileInput, ...],
        admitted_sources: tuple[AdmittedInferenceTransferSource, ...],
    ) -> tuple[tuple[SuppliedGraphBaseline, ...], tuple[str, ...]]:
        profiles_by_run = {}
        for row in eligible_inputs:
            run_id = row.profile.source_basis.solution_evidence.base_analysis_run_id
            profiles_by_run[run_id] = InferenceTransferProfilePointer.from_profile(row.profile)
        sources_by_run = {row.analysis_run_id: row.source for row in admitted_sources}
        baselines: list[SuppliedGraphBaseline] = []
        limitations: set[str] = set()
        selected_queries = tuple(
            value
            for value in entries.values()
            if value.profile.source_basis.source.item_revision_id in request.query_item_revision_ids
        )
        for entry in selected_queries:
            if entry.content is None:
                limitations.add(
                    "Requested query CONTENT is unavailable; no official Graph baseline "
                    "was materialized."
                )
                continue
            terms = knowledge_node_terms("", entry.content.text)
            if len(terms) > 128:
                limitations.add(
                    "Lexical seed recipe uses the first 128 sorted unique terms; "
                    "question text is not truncated."
                )
            topic_keys = self.sources.retrieval.topic_keys_for_terms(
                session,
                snapshot_id=request.graph_snapshot.graph_snapshot_revision_id,
                terms=terms[:128],
                source_classes=request.source_classes,
                allow_answer_bearing=True,
            )
            if not topic_keys:
                limitations.add(
                    "No supported Graph topic keys matched a requested query; "
                    "baseline is unavailable, not an empty result."
                )
                continue
            body = {
                "operation": "CREATE_EVIDENCE_BUNDLE",
                "graph_snapshot_revision_id": request.graph_snapshot.graph_snapshot_revision_id,
                "query_kind": "ITEM_PREPARATION",
                "curriculum_scope": None,
                "topic_keys": topic_keys,
                "target_item_revision_id": None,
                "required_item_elements": (),
                "source_classes": request.source_classes,
                "evidence_budget": scope.evidence_budget.model_dump(mode="json"),
                "access_policy_revision_id": scope.access_policy_revision_id,
                "requester_role": scope.requester_role,
                "requester_permission_keys": scope.requester_permission_keys,
                "requested_by": scope.requested_by,
            }
            digest = content_sha256(body)
            command = CreateEvidenceBundleCommand.model_validate(
                body
                | {
                    "submission_sha256": digest,
                    "idempotency_key": "snapshot-baseline:" + digest[7:],
                }
            )
            try:
                selection = self.sources.retrieval.retrieve_read_only(session, command)
            except KnowledgeRetrievalServiceError as exc:
                if exc.code != "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE":
                    raise
                limitations.add(
                    "Official retrieval returned insufficient evidence; "
                    "a baseline was not materialized."
                )
                continue
            query = InferenceTransferProfilePointer.from_profile(entry.profile)
            ordered: list[InferenceTransferProfilePointer] = []
            seen: set[InferenceTransferProfilePointer] = set()
            for candidate in selection.candidates:
                pointer = profiles_by_run.get(candidate.analysis_run_id)
                if sources_by_run.get(candidate.analysis_run_id) != candidate.source:
                    pointer = None
                if pointer is None or pointer == query or pointer in seen:
                    continue
                seen.add(pointer)
                ordered.append(pointer)
            if len(ordered) < len(selection.candidates):
                limitations.add(
                    "Official Graph order is filtered to frozen eligible report profiles "
                    "and excludes the query; ranking/budget are unchanged."
                )
            if not ordered:
                limitations.add(
                    "A materialized official baseline has zero eligible comparison candidates."
                )
            if len(ordered) > MAX_GRAPH_BASELINE_CANDIDATES:
                # The supported read-only Graph port returns its candidate pool,
                # not the final published Evidence selection. This bounded
                # experiment records a declared prefix, never a complete-pool
                # claim or a second implementation of authoring budget rules.
                limitations.add(
                    f"Official read-only Graph candidate order has {len(ordered)} eligible "
                    f"comparisons; this bounded baseline retains the first "
                    f"{MAX_GRAPH_BASELINE_CANDIDATES} in unchanged order. Remaining "
                    "candidates are not recorded in this baseline; it is not the "
                    "final authoring Evidence selection."
                )
                ordered = ordered[:MAX_GRAPH_BASELINE_CANDIDATES]
            baselines.append(
                hashed_snapshot_value(
                    SuppliedGraphBaseline,
                    "result_sha256",
                    query=query,
                    command_sha256=command.submission_sha256,
                    ordered_candidates=tuple(ordered),
                )
            )
        return tuple(sorted(baselines, key=lambda value: profile_key(value.query))), tuple(
            sorted(limitations)
        )

    def capture(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotPrepareRequest,
        *,
        expected_header: InferenceTransferSnapshotHeader | None = None,
        selected_index_entries: tuple[InferenceTransferSnapshotIndexEntry, ...] = (),
        materialize_all: bool = False,
    ) -> AuthorizedSnapshotCapture:
        request = InferenceTransferSnapshotPrepareRequest.model_validate(
            request.model_dump(mode="json")
        )
        command = InferenceTransferCorpusReadCommand(
            actor_id=actor_id,
            graph_snapshot=request.graph_snapshot,
            access_policy_revision_id=request.access_policy_revision_id,
            access_policy_sha256=request.access_policy_sha256,
            source_classes=request.source_classes,
            maximum_candidates=request.max_sources,
            population_scope=InferenceTransferPopulationScope(request.population_scope),
        )
        with self.sources.sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            scope = self.sources._scope(session, command)
            pool = self.sources.retrieval.admit_read_only_candidate_pool(session, scope)
            inputs, missing = self.sources._resolve_profile_inputs(session, pool)
            admitted = []
            for value in pool.candidates:
                if not isinstance(value.source, ApprovedItemKnowledgeSourceV2):
                    raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")
                admitted.append(
                    AdmittedInferenceTransferSource(value.analysis_run_id, value.source)
                )
            corpus = AdmittedInferenceTransferCorpus(
                profiles=tuple(value.profile for value in inputs),
                graph_scores=(),
                truncated=pool.truncated,
                missing_solution_reports=missing,
                sources=tuple(admitted),
            )
            current = prepare_snapshot_value(actor_id, request, corpus)
            validate_snapshot_selection(current, expected_header, selected_index_entries)
            selected = current.index if materialize_all else selected_index_entries
            if not selected:
                return AuthorizedSnapshotCapture(corpus)
            run_ids = {row.base_analysis_run_id for row in selected}
            entries = self._materialize_entries(
                request,
                tuple(
                    value
                    for value in inputs
                    if value.profile.source_basis.solution_evidence.base_analysis_run_id in run_ids
                ),
            )
            sources_by_run = {value.analysis_run_id: value.source for value in corpus.sources}
            records = tuple(
                InferenceTransferSnapshotRecord(
                    index_entry=row,
                    source=sources_by_run[row.base_analysis_run_id],
                    staged_entry=entries.get(row.base_analysis_run_id),
                )
                for row in selected
            )
            baselines, limits = self._baselines(
                session,
                request,
                scope,
                entries,
                inputs,
                corpus.sources,
            )
            limitations = set(limits)
            if any(
                row.profile is None
                and row.source_item_revision_id in request.query_item_revision_ids
                for row in selected
            ):
                limitations.add(
                    "Requested query has no accepted solution report; "
                    "its source remains in the full denominator."
                )
            return AuthorizedSnapshotCapture(corpus, records, baselines, tuple(sorted(limitations)))
