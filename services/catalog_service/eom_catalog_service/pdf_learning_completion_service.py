"""Exact Stage-C PDF learning completion coordinator.

The Catalog application service owns validation and orchestration only.  A Catalog source adapter
resolves one repeatable-read snapshot and persists its first truthful observation timestamp; an
Orchestrator adapter is the sole implementation allowed to write the bounded Artifact members.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

from eom_catalog_contracts import (
    AnalysisRecoveryLineage,
    ArtifactMember,
    AssessmentSourceBundleRevision,
    BatchProof,
    CompletionItemKey,
    CorpusCoverage,
    EffectiveExtractionDocuments,
    EffectiveKnowledgeAnalysisDocuments,
    EffectiveWorkUnit,
    GraphPlacementDatabaseEvidence,
    GraphSnapshot,
    GraphSnapshotAnalysisDatabaseEvidence,
    GraphSnapshotDatabaseEvidence,
    InventoryPointer,
    ItemCompletion,
    KnowledgeGraphSnapshotManifestV8,
    KnowledgeGraphStructureManifestV5,
    LegacyExtractionResultIdentityCollisions,
    LegacyItemCorpusCompletionReceipt,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionValidationRecovery,
    LegacySourceInventoryV2,
    PdfLearningCompletionReceipt,
    PdfLearningItemCompletionShard,
    PdfLearningItemCompletionShardPointer,
    PdfSource,
    Quiescence,
    RecoveryAuthorization,
    SourceRelease,
    completion_identity_sha256,
    verify_completion_shards,
    verify_graph_documents,
    verify_graph_past_exam_sources,
    verify_protocol_documents,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

_GRAPH_REVISION_ID = re.compile(r"^graphrev_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class PdfLearningCompletionError(RuntimeError):
    """Stable, content-free Stage-C failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PdfLearningCompletionRequest:
    """Pinned generic COMPLETE coverage plus the Graph revision to prove."""

    corpus_completion: LegacyItemCorpusCompletionReceipt
    graph_snapshot_revision_id: str
    graph_snapshot_sha256: str

    def __post_init__(self) -> None:
        if (
            self.corpus_completion.status != "COMPLETE"
            or _GRAPH_REVISION_ID.fullmatch(self.graph_snapshot_revision_id) is None
            or _SHA256.fullmatch(self.graph_snapshot_sha256) is None
        ):
            raise ValueError("PDF learning completion request is invalid")


@dataclass(frozen=True)
class PdfLearningCompletionEvidence:
    """Small typed receipt fields derived from the stable source snapshot."""

    inventory: InventoryPointer
    original_batch: BatchProof
    successor_batch: BatchProof
    recovery_authorization: RecoveryAuthorization
    corpus_coverage: CorpusCoverage
    pdf_sources: tuple[PdfSource, ...]
    effective_work_units: tuple[EffectiveWorkUnit, ...]
    graph_snapshot: GraphSnapshot
    analysis_recoveries: tuple[AnalysisRecoveryLineage, ...]
    quiescence: Quiescence
    historical_result_identity_collisions: LegacyExtractionResultIdentityCollisions | None = None


@dataclass(frozen=True)
class ResolvedPdfLearningCompletionSnapshot:
    """All immutable and mutable evidence read under one stable database transaction.

    ``observed_at_utc`` is the truthful time at which this read-only transaction took its mutable
    observation.  After full validation, the separate observation boundary persists or reloads
    the first such timestamp under a semantic advisory lock so replay bytes stay identical.
    ``mutable_fingerprint_sha256`` covers every current/lifecycle/runtime/quiescence fact used by
    the receipt and is checked again after publication.
    """

    requested_by: str
    requester_active: Literal[True]
    requester_authorized: Literal[True]
    observed_at_utc: datetime
    mutable_fingerprint_sha256: str
    evidence: PdfLearningCompletionEvidence
    items: tuple[ItemCompletion, ...]
    effective_documents: tuple[EffectiveExtractionDocuments, ...]
    knowledge_documents: tuple[EffectiveKnowledgeAnalysisDocuments, ...]
    bundle_revisions: tuple[AssessmentSourceBundleRevision, ...]
    inventory_document: LegacySourceInventoryV2
    original_manifest: LegacyItemExtractionBatchManifestV2
    successor_manifest: LegacyItemExtractionBatchManifestV2
    recovery_document: LegacyItemExtractionValidationRecovery
    coverage_document: LegacyItemCorpusCoverage
    snapshot_manifest: KnowledgeGraphSnapshotManifestV8
    structure_manifest: KnowledgeGraphStructureManifestV5
    projection_member_bytes: Mapping[str, bytes]
    snapshot_database: GraphSnapshotDatabaseEvidence
    placement_database_rows: tuple[GraphPlacementDatabaseEvidence, ...]
    snapshot_analysis_database_rows: tuple[GraphSnapshotAnalysisDatabaseEvidence, ...]

    def __post_init__(self) -> None:
        if (
            _SHA256.fullmatch(self.mutable_fingerprint_sha256) is None
            or self.observed_at_utc.tzinfo is None
            or self.observed_at_utc.utcoffset() != UTC.utcoffset(self.observed_at_utc)
        ):
            raise ValueError("PDF learning completion snapshot authority is invalid")


@dataclass(frozen=True)
class CurrentPdfLearningCompletionState:
    """Second trusted observation immediately after final Artifact publication."""

    mutable_fingerprint_sha256: str
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        if (
            _SHA256.fullmatch(self.mutable_fingerprint_sha256) is None
            or self.observed_at_utc.tzinfo is None
            or self.observed_at_utc.utcoffset() != UTC.utcoffset(self.observed_at_utc)
        ):
            raise ValueError("PDF learning completion current-state observation is invalid")


@dataclass(frozen=True)
class PdfLearningCompletionObservation:
    """Persisted first observation returned by the serialized write boundary."""

    completion_identity_sha256: str
    mutable_fingerprint_sha256: str
    first_observed_at_utc: datetime

    def __post_init__(self) -> None:
        if (
            _SHA256.fullmatch(self.completion_identity_sha256) is None
            or _SHA256.fullmatch(self.mutable_fingerprint_sha256) is None
            or self.first_observed_at_utc.tzinfo is None
            or self.first_observed_at_utc.utcoffset() != UTC.utcoffset(self.first_observed_at_utc)
        ):
            raise ValueError("PDF learning completion observation authority is invalid")


@dataclass(frozen=True)
class PdfLearningCompletionPublication:
    """Final bounded Artifact pointers and their fully verified typed documents."""

    completion_identity_sha256: str
    receipt: PdfLearningCompletionReceipt
    receipt_artifact: ArtifactMember
    shards: tuple[PdfLearningItemCompletionShard, ...]


class PdfLearningCompletionSourceBoundary(Protocol):
    """Catalog-owned repeatable-read and post-publication current-state boundary."""

    def resolve_completion_snapshot(
        self,
        request: PdfLearningCompletionRequest,
        *,
        source_release: SourceRelease,
    ) -> ResolvedPdfLearningCompletionSnapshot: ...

    def claim_first_observation(
        self,
        request: PdfLearningCompletionRequest,
        *,
        source_release: SourceRelease,
        completion_identity_sha256: str,
        mutable_fingerprint_sha256: str,
        observed_at_utc: datetime,
    ) -> PdfLearningCompletionObservation: ...

    def recheck_current_state(
        self,
        request: PdfLearningCompletionRequest,
        *,
        observation_identity_sha256: str,
    ) -> CurrentPdfLearningCompletionState: ...


class PdfLearningCompletionArtifactBoundary(Protocol):
    """Implemented only by the Orchestrator-owned validated Artifact adapter."""

    def commit_completion_shard(
        self,
        shard: PdfLearningItemCompletionShard,
        *,
        completion_map_sha256: str,
        created_at: datetime,
    ) -> ArtifactMember: ...

    def commit_completion_receipt(
        self,
        receipt: PdfLearningCompletionReceipt,
        *,
        completion_identity: str,
    ) -> ArtifactMember: ...


class PdfLearningCompletionValidator:
    """Production cross-document verifier kept separate from I/O composition."""

    @staticmethod
    def verify(
        receipt: PdfLearningCompletionReceipt,
        shards: tuple[PdfLearningItemCompletionShard, ...],
        snapshot: ResolvedPdfLearningCompletionSnapshot,
    ) -> None:
        items = verify_completion_shards(receipt, shards)
        if items != snapshot.items:
            raise ValueError("completion shards differ from the stable source snapshot")
        verify_protocol_documents(
            receipt,
            items=items,
            effective_documents=snapshot.effective_documents,
            knowledge_documents=snapshot.knowledge_documents,
            bundle_revisions=snapshot.bundle_revisions,
            inventory=snapshot.inventory_document,
            original_manifest=snapshot.original_manifest,
            successor_manifest=snapshot.successor_manifest,
            recovery=snapshot.recovery_document,
            coverage=snapshot.coverage_document,
        )
        verify_graph_past_exam_sources(
            items=items,
            knowledge_documents=snapshot.knowledge_documents,
            snapshot_manifest=snapshot.snapshot_manifest,
        )
        verify_graph_documents(
            receipt,
            items=items,
            snapshot_manifest=snapshot.snapshot_manifest,
            structure_manifest=snapshot.structure_manifest,
            projection_member_bytes=snapshot.projection_member_bytes,
            snapshot_database=snapshot.snapshot_database,
            placement_database_rows=snapshot.placement_database_rows,
            snapshot_analysis_database_rows=snapshot.snapshot_analysis_database_rows,
        )


class PdfLearningCompletionService:
    """Verify exact 520 chains, publish bounded proof members, then recheck current state."""

    def __init__(
        self,
        *,
        source: PdfLearningCompletionSourceBoundary,
        artifacts: PdfLearningCompletionArtifactBoundary,
        source_release: SourceRelease,
        validator: PdfLearningCompletionValidator | None = None,
    ) -> None:
        self.source = source
        self.artifacts = artifacts
        self.source_release = source_release
        self.validator = validator or PdfLearningCompletionValidator()

    def complete(
        self,
        request: PdfLearningCompletionRequest,
    ) -> PdfLearningCompletionPublication:
        snapshot = self.source.resolve_completion_snapshot(
            request,
            source_release=self.source_release,
        )
        self._require_source_authority(request, snapshot)
        shards = self._build_shards(snapshot.items)
        provisional_pointers = tuple(self._provisional_pointer(shard) for shard in shards)
        provisional_receipt = self._build_receipt(
            snapshot,
            item_shards=provisional_pointers,
        )
        completion_identity = completion_identity_sha256(provisional_receipt)
        self._verify(provisional_receipt, shards, snapshot)
        try:
            observation = self.source.claim_first_observation(
                request,
                source_release=self.source_release,
                completion_identity_sha256=completion_identity,
                mutable_fingerprint_sha256=snapshot.mutable_fingerprint_sha256,
                observed_at_utc=snapshot.observed_at_utc,
            )
        except Exception as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_OBSERVATION_IDENTITY_INVALID",
                "completion first-observation authority failed",
                exc,
            )
        if (
            observation.completion_identity_sha256 != completion_identity
            or observation.mutable_fingerprint_sha256 != snapshot.mutable_fingerprint_sha256
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_OBSERVATION_IDENTITY_INVALID",
                "persisted completion observation identity differs",
            )
        snapshot = replace(snapshot, observed_at_utc=observation.first_observed_at_utc)
        provisional_receipt = self._build_receipt(snapshot, item_shards=provisional_pointers)
        if completion_identity_sha256(provisional_receipt) != completion_identity:
            self._fail(
                "PDF_LEARNING_COMPLETION_OBSERVATION_IDENTITY_INVALID",
                "persisted observation changed the semantic completion identity",
            )
        self._verify(provisional_receipt, shards, snapshot)

        shard_pointers: list[PdfLearningItemCompletionShardPointer] = []
        try:
            for shard in shards:
                artifact = self.artifacts.commit_completion_shard(
                    shard,
                    completion_map_sha256=provisional_receipt.completion_map_sha256,
                    created_at=snapshot.observed_at_utc,
                )
                shard_pointers.append(self._published_shard_pointer(shard, artifact))
        except Exception as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_SHARD_PUBLICATION_FAILED",
                "completion shard publication failed",
                exc,
            )

        receipt = self._build_receipt(snapshot, item_shards=tuple(shard_pointers))
        if completion_identity_sha256(receipt) != completion_identity:
            self._fail(
                "PDF_LEARNING_COMPLETION_PUBLICATION_IDENTITY_DRIFT",
                "published shard pointers changed the completion semantic identity",
            )
        self._verify(receipt, shards, snapshot)
        try:
            receipt_artifact = self.artifacts.commit_completion_receipt(
                receipt,
                completion_identity=completion_identity,
            )
        except Exception as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_RECEIPT_PUBLICATION_FAILED",
                "completion receipt publication failed",
                exc,
            )
        self._require_receipt_pointer(receipt, receipt_artifact)

        current = self.source.recheck_current_state(
            request,
            observation_identity_sha256=completion_identity,
        )
        if (
            current.mutable_fingerprint_sha256 != snapshot.mutable_fingerprint_sha256
            or current.observed_at_utc < snapshot.observed_at_utc
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_CURRENT_STATE_CHANGED",
                "completion current-state evidence changed during publication",
            )
        return PdfLearningCompletionPublication(
            completion_identity_sha256=completion_identity,
            receipt=receipt,
            receipt_artifact=receipt_artifact,
            shards=shards,
        )

    def _verify(
        self,
        receipt: PdfLearningCompletionReceipt,
        shards: tuple[PdfLearningItemCompletionShard, ...],
        snapshot: ResolvedPdfLearningCompletionSnapshot,
    ) -> None:
        try:
            self.validator.verify(receipt, shards, snapshot)
        except ValueError as exc:
            self._fail(
                "PDF_LEARNING_COMPLETION_EVIDENCE_INVALID",
                "completion evidence is not an exact closed proof",
                exc,
            )

    def _require_source_authority(
        self,
        request: PdfLearningCompletionRequest,
        snapshot: ResolvedPdfLearningCompletionSnapshot,
    ) -> None:
        completion = request.corpus_completion
        evidence = snapshot.evidence
        if (
            snapshot.requested_by != completion.requested_by
            or snapshot.requester_active is not True
            or snapshot.requester_authorized is not True
            or evidence.graph_snapshot.graph_snapshot_revision_id
            != request.graph_snapshot_revision_id
            or evidence.graph_snapshot.snapshot_sha256 != request.graph_snapshot_sha256
            or evidence.inventory.inventory_id != completion.inventory_id
            or evidence.inventory.inventory_sha256 != completion.inventory_sha256
            or evidence.inventory.artifact.model_dump(mode="json")
            != completion.inventory_artifact.model_dump(mode="json")
            or evidence.original_batch.extraction_batch_id
            != completion.original_batch.extraction_batch_id
            or evidence.original_batch.manifest_sha256 != completion.original_batch.manifest_sha256
            or evidence.original_batch.manifest_artifact.model_dump(mode="json")
            != completion.original_batch.manifest_artifact.model_dump(mode="json")
            or evidence.successor_batch.extraction_batch_id
            != completion.successor_batch.extraction_batch_id
            or evidence.successor_batch.manifest_sha256
            != completion.successor_batch.manifest_sha256
            or evidence.successor_batch.manifest_artifact.model_dump(mode="json")
            != completion.successor_batch.manifest_artifact.model_dump(mode="json")
            or evidence.recovery_authorization.recovery_sha256 != completion.recovery_sha256
            or evidence.recovery_authorization.artifact.model_dump(mode="json")
            != completion.recovery_artifact.model_dump(mode="json")
            or evidence.historical_result_identity_collisions
            != completion.historical_result_identity_collisions
            or evidence.corpus_coverage.coverage_id != completion.coverage_id
            or evidence.corpus_coverage.coverage_sha256 != completion.coverage_sha256
            or evidence.corpus_coverage.artifact.model_dump(mode="json")
            != completion.coverage_artifact.model_dump(mode="json")
            or completion.expected_item_count != 520
            or completion.accepted_item_count != 520
            or completion.missing_item_count != 0
            or completion.conflict_item_count != 0
        ):
            self._fail(
                "PDF_LEARNING_COMPLETION_SOURCE_AUTHORITY_INVALID",
                "completion snapshot differs from its pinned source authority",
            )

    def _build_receipt(
        self,
        snapshot: ResolvedPdfLearningCompletionSnapshot,
        *,
        item_shards: tuple[PdfLearningItemCompletionShardPointer, ...],
    ) -> PdfLearningCompletionReceipt:
        evidence = snapshot.evidence
        collision_version = evidence.historical_result_identity_collisions is not None
        expected_keys = tuple(
            sorted(
                (unit.bundle_revision_id, item_number)
                for unit in evidence.effective_work_units
                for item_number in unit.expected_item_numbers
            )
        )
        receipt_document: dict[str, object] = {
            "schema_version": (
                "eom-pdf-learning-completion/1.1"
                if collision_version
                else "eom-pdf-learning-completion/1.0"
            ),
            "status": "COMPLETE",
            "source_release": self.source_release.model_dump(mode="json"),
            "inventory": evidence.inventory.model_dump(mode="json"),
            "original_batch": evidence.original_batch.model_dump(mode="json"),
            "successor_batch": evidence.successor_batch.model_dump(mode="json"),
            "recovery_authorization": evidence.recovery_authorization.model_dump(mode="json"),
            "corpus_coverage": evidence.corpus_coverage.model_dump(mode="json"),
            "pdf_sources": [value.model_dump(mode="json") for value in evidence.pdf_sources],
            "effective_work_units": [
                value.model_dump(mode="json") for value in evidence.effective_work_units
            ],
            "item_count": len(snapshot.items),
            "item_shards": [value.model_dump(mode="json") for value in item_shards],
            "graph_snapshot": evidence.graph_snapshot.model_dump(mode="json"),
            "analysis_recoveries": [
                value.model_dump(mode="json") for value in evidence.analysis_recoveries
            ],
            "quiescence": evidence.quiescence.model_dump(mode="json"),
            "pdf_sources_sha256": content_sha256(
                [value.model_dump(mode="json") for value in evidence.pdf_sources]
            ),
            "expected_item_keys_sha256": content_sha256(
                [
                    {"bundle_revision_id": bundle_revision_id, "item_number": item_number}
                    for bundle_revision_id, item_number in expected_keys
                ]
            ),
            "coverage_accepted_map_sha256": content_sha256(
                [
                    {
                        "bundle_revision_id": value.bundle_revision_id,
                        "item_number": value.item_number,
                        "acceptance_id": value.acceptance_id,
                        "acceptance_sha256": value.acceptance_sha256,
                    }
                    for value in snapshot.items
                ]
            ),
            "analysis_recovery_set_sha256": content_sha256(
                [value.model_dump(mode="json") for value in evidence.analysis_recoveries]
            ),
            "completion_map_sha256": content_sha256(
                [value.model_dump(mode="json") for value in snapshot.items]
            ),
            "observed_at_utc": snapshot.observed_at_utc.isoformat().replace("+00:00", "Z"),
            "receipt_sha256": "sha256:" + "0" * 64,
        }
        if evidence.historical_result_identity_collisions is not None:
            receipt_document["historical_result_identity_collisions"] = (
                evidence.historical_result_identity_collisions.model_dump(mode="json")
            )
        receipt_document["receipt_sha256"] = content_sha256(
            {key: value for key, value in receipt_document.items() if key != "receipt_sha256"}
        )
        return PdfLearningCompletionReceipt.model_validate(receipt_document)

    @staticmethod
    def _build_shards(
        items: tuple[ItemCompletion, ...],
    ) -> tuple[PdfLearningItemCompletionShard, ...]:
        keys = tuple((value.bundle_revision_id, value.item_number) for value in items)
        if len(items) != 520 or keys != tuple(sorted(set(keys))):
            raise PdfLearningCompletionError(
                "PDF_LEARNING_COMPLETION_ITEM_SET_INVALID",
                "completion item set is not the canonical exact 520",
            )
        shards: list[PdfLearningItemCompletionShard] = []
        for shard_index, start in enumerate(range(0, len(items), 64)):
            values = items[start : start + 64]
            first = CompletionItemKey(
                bundle_revision_id=values[0].bundle_revision_id,
                item_number=values[0].item_number,
            )
            last = CompletionItemKey(
                bundle_revision_id=values[-1].bundle_revision_id,
                item_number=values[-1].item_number,
            )
            document: dict[str, object] = {
                "schema_version": "eom-pdf-learning-item-completion-shard/1.0",
                "shard_index": shard_index,
                "first_key": first.model_dump(mode="json"),
                "last_key": last.model_dump(mode="json"),
                "item_count": len(values),
                "items": [value.model_dump(mode="json") for value in values],
                "shard_sha256": "sha256:" + "0" * 64,
            }
            document["shard_sha256"] = content_sha256(
                {key: value for key, value in document.items() if key != "shard_sha256"}
            )
            shards.append(PdfLearningItemCompletionShard.model_validate(document))
        return tuple(shards)

    @staticmethod
    def _provisional_pointer(
        shard: PdfLearningItemCompletionShard,
    ) -> PdfLearningItemCompletionShardPointer:
        identity = content_sha256(
            {"stage": "PREVALIDATION_ONLY", "shard_sha256": shard.shard_sha256}
        ).removeprefix("sha256:")
        payload = canonical_json_bytes(shard.model_dump(mode="json"))
        return PdfLearningItemCompletionShardPointer(
            shard_index=shard.shard_index,
            first_key=shard.first_key,
            last_key=shard.last_key,
            item_count=shard.item_count,
            shard_sha256=shard.shard_sha256,
            artifact=ArtifactMember(
                artifact_id="artifact_" + identity[:32],
                artifact_revision_id="rev_" + identity[32:],
                member_path=f"item-completions/shard-{shard.shard_index:02d}.json",
                schema_ref=(
                    "eom://schemas/legacy-assessment/pdf-learning-item-completion-shard/1.0"
                ),
                media_type="application/json",
                sha256=sha256_bytes(payload),
            ),
        )

    @staticmethod
    def _published_shard_pointer(
        shard: PdfLearningItemCompletionShard,
        artifact: ArtifactMember,
    ) -> PdfLearningItemCompletionShardPointer:
        payload_sha256 = sha256_bytes(canonical_json_bytes(shard.model_dump(mode="json")))
        expected_path = f"item-completions/shard-{shard.shard_index:02d}.json"
        if (
            artifact.member_path != expected_path
            or artifact.schema_ref
            != "eom://schemas/legacy-assessment/pdf-learning-item-completion-shard/1.0"
            or artifact.media_type != "application/json"
            or artifact.sha256 != payload_sha256
        ):
            raise ValueError("published completion shard pointer differs")
        return PdfLearningItemCompletionShardPointer(
            shard_index=shard.shard_index,
            first_key=shard.first_key,
            last_key=shard.last_key,
            item_count=shard.item_count,
            shard_sha256=shard.shard_sha256,
            artifact=artifact,
        )

    @staticmethod
    def _require_receipt_pointer(
        receipt: PdfLearningCompletionReceipt,
        artifact: ArtifactMember,
    ) -> None:
        expected_schema_ref = (
            "eom://schemas/legacy-assessment/pdf-learning-completion/1.1"
            if receipt.schema_version == "eom-pdf-learning-completion/1.1"
            else "eom://schemas/legacy-assessment/pdf-learning-completion/1.0"
        )
        if (
            artifact.member_path != "completion-receipt.json"
            or artifact.schema_ref != expected_schema_ref
            or artifact.media_type != "application/json"
            or artifact.sha256
            != sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json")))
        ):
            raise PdfLearningCompletionError(
                "PDF_LEARNING_COMPLETION_RECEIPT_POINTER_INVALID",
                "published completion receipt pointer differs",
            )

    @staticmethod
    def _fail(code: str, message: str, cause: Exception | None = None) -> None:
        error = PdfLearningCompletionError(code, message)
        if cause is None:
            raise error
        raise error from cause


__all__ = [
    "CurrentPdfLearningCompletionState",
    "PdfLearningCompletionArtifactBoundary",
    "PdfLearningCompletionError",
    "PdfLearningCompletionEvidence",
    "PdfLearningCompletionObservation",
    "PdfLearningCompletionPublication",
    "PdfLearningCompletionRequest",
    "PdfLearningCompletionService",
    "PdfLearningCompletionSourceBoundary",
    "PdfLearningCompletionValidator",
    "ResolvedPdfLearningCompletionSnapshot",
]
