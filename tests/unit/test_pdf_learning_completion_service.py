from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    ArtifactMember,
    AssessmentSourceBundleRevision,
    EffectiveExtractionDocuments,
    EffectiveKnowledgeAnalysisDocuments,
    GraphSnapshotDatabaseEvidence,
    KnowledgeGraphSnapshotManifestV8,
    KnowledgeGraphStructureManifestV5,
    LegacyItemCorpusCompletionReceipt,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionValidationRecovery,
    LegacySourceInventoryV2,
    PdfLearningItemCompletionShard,
    completion_identity_sha256,
)
from eom_catalog_service.pdf_learning_completion_service import (
    CurrentPdfLearningCompletionState,
    PdfLearningCompletionError,
    PdfLearningCompletionEvidence,
    PdfLearningCompletionObservation,
    PdfLearningCompletionRequest,
    PdfLearningCompletionService,
    PdfLearningCompletionValidator,
    ResolvedPdfLearningCompletionSnapshot,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from test_pdf_learning_completion import _completion_items, _receipt, validate_payload


class _Source:
    def __init__(self, snapshot: ResolvedPdfLearningCompletionSnapshot) -> None:
        self.snapshot = snapshot
        self.drift = False
        self.completion_identity: str | None = None

    def resolve_completion_snapshot(
        self,
        _request: PdfLearningCompletionRequest,
        *,
        source_release: object,
    ) -> ResolvedPdfLearningCompletionSnapshot:
        assert source_release is not None
        return self.snapshot

    def claim_first_observation(
        self,
        _request: PdfLearningCompletionRequest,
        *,
        source_release: object,
        completion_identity_sha256: str,
        mutable_fingerprint_sha256: str,
        observed_at_utc: datetime,
    ) -> PdfLearningCompletionObservation:
        assert source_release is not None
        self.completion_identity = completion_identity_sha256
        return PdfLearningCompletionObservation(
            completion_identity_sha256=completion_identity_sha256,
            mutable_fingerprint_sha256=mutable_fingerprint_sha256,
            first_observed_at_utc=observed_at_utc,
        )

    def recheck_current_state(
        self,
        _request: PdfLearningCompletionRequest,
        *,
        observation_identity_sha256: str,
    ) -> CurrentPdfLearningCompletionState:
        assert observation_identity_sha256 == self.completion_identity
        return CurrentPdfLearningCompletionState(
            mutable_fingerprint_sha256=(
                "sha256:" + "f" * 64 if self.drift else self.snapshot.mutable_fingerprint_sha256
            ),
            observed_at_utc=self.snapshot.observed_at_utc,
        )


class _Artifacts:
    def __init__(self) -> None:
        self.shards: dict[int, ArtifactMember] = {}
        self.receipts: dict[str, ArtifactMember] = {}

    def commit_completion_shard(
        self,
        shard: PdfLearningItemCompletionShard,
        *,
        completion_map_sha256: str,
        created_at: datetime,
    ) -> ArtifactMember:
        assert completion_map_sha256.startswith("sha256:")
        assert created_at.tzinfo is not None
        existing = self.shards.get(shard.shard_index)
        if existing is not None:
            return existing
        value = ArtifactMember(
            artifact_id="artifact_" + f"{shard.shard_index + 900_000:032x}",
            artifact_revision_id="rev_" + f"{shard.shard_index + 900_000:032x}",
            member_path=f"item-completions/shard-{shard.shard_index:02d}.json",
            schema_ref=("eom://schemas/legacy-assessment/pdf-learning-item-completion-shard/1.0"),
            media_type="application/json",
            sha256=sha256_bytes(canonical_json_bytes(shard.model_dump(mode="json"))),
        )
        self.shards[shard.shard_index] = value
        return value

    def commit_completion_receipt(
        self,
        receipt: object,
        *,
        completion_identity: str,
    ) -> ArtifactMember:
        document = receipt.model_dump(mode="json")
        assert completion_identity == completion_identity_sha256(receipt)
        existing = self.receipts.get(completion_identity)
        if existing is not None:
            return existing
        value = ArtifactMember(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "e" * 32,
            member_path="completion-receipt.json",
            schema_ref="eom://schemas/legacy-assessment/pdf-learning-completion/1.0",
            media_type="application/json",
            sha256=sha256_bytes(canonical_json_bytes(document)),
        )
        self.receipts[completion_identity] = value
        return value


class _Verifier(PdfLearningCompletionValidator):
    calls = 0

    @classmethod
    def verify(cls, receipt: object, shards: tuple[object, ...], snapshot: object) -> None:
        cls.calls += 1
        assert receipt.item_count == 520
        assert len(shards) == 9
        assert snapshot.items == _completion_items_from_shards(shards)


def _completion_items_from_shards(shards: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(item for shard in shards for item in shard.items)


def _snapshot() -> tuple[
    PdfLearningCompletionRequest,
    ResolvedPdfLearningCompletionSnapshot,
]:
    fixture = _receipt()
    receipt = validate_payload(fixture)
    items = _completion_items(fixture)
    generic = LegacyItemCorpusCompletionReceipt.model_construct(
        schema_version="legacy-item-corpus-completion-receipt/1.0",
        status="COMPLETE",
        requested_by="operator_stage_c",
        command_sha256="sha256:" + "1" * 64,
        inventory_id=receipt.inventory.inventory_id,
        inventory_sha256=receipt.inventory.inventory_sha256,
        inventory_artifact=receipt.inventory.artifact,
        original_batch=receipt.original_batch,
        successor_batch=receipt.successor_batch,
        recovery_sha256=receipt.recovery_authorization.recovery_sha256,
        recovery_artifact=receipt.recovery_authorization.artifact,
        coverage_id=receipt.corpus_coverage.coverage_id,
        coverage_sha256=receipt.corpus_coverage.coverage_sha256,
        coverage_artifact=receipt.corpus_coverage.artifact,
        original_work_unit_count=108,
        effective_work_unit_count=108,
        recovered_work_unit_count=3,
        expected_item_count=520,
        accepted_item_count=520,
        missing_item_count=0,
        conflict_item_count=0,
        expected_item_keys_sha256=receipt.expected_item_keys_sha256,
        accepted_item_map_sha256=receipt.coverage_accepted_map_sha256,
        created_at=receipt.observed_at_utc,
        receipt_sha256="sha256:" + "2" * 64,
    )
    request = PdfLearningCompletionRequest(
        corpus_completion=generic,
        graph_snapshot_revision_id=receipt.graph_snapshot.graph_snapshot_revision_id,
        graph_snapshot_sha256=receipt.graph_snapshot.snapshot_sha256,
    )
    evidence = PdfLearningCompletionEvidence(
        inventory=receipt.inventory,
        original_batch=receipt.original_batch,
        successor_batch=receipt.successor_batch,
        recovery_authorization=receipt.recovery_authorization,
        corpus_coverage=receipt.corpus_coverage,
        pdf_sources=receipt.pdf_sources,
        effective_work_units=receipt.effective_work_units,
        graph_snapshot=receipt.graph_snapshot,
        analysis_recoveries=receipt.analysis_recoveries,
        quiescence=receipt.quiescence,
    )
    snapshot = ResolvedPdfLearningCompletionSnapshot(
        requested_by="operator_stage_c",
        requester_active=True,
        requester_authorized=True,
        observed_at_utc=datetime(2026, 9, 9, tzinfo=UTC),
        mutable_fingerprint_sha256="sha256:" + "a" * 64,
        evidence=evidence,
        items=items,
        effective_documents=tuple[EffectiveExtractionDocuments](),
        knowledge_documents=tuple[EffectiveKnowledgeAnalysisDocuments](),
        bundle_revisions=tuple[AssessmentSourceBundleRevision](),
        inventory_document=LegacySourceInventoryV2.model_construct(),
        original_manifest=LegacyItemExtractionBatchManifestV2.model_construct(),
        successor_manifest=LegacyItemExtractionBatchManifestV2.model_construct(),
        recovery_document=LegacyItemExtractionValidationRecovery.model_construct(),
        coverage_document=LegacyItemCorpusCoverage.model_construct(),
        snapshot_manifest=KnowledgeGraphSnapshotManifestV8.model_construct(),
        structure_manifest=KnowledgeGraphStructureManifestV5.model_construct(),
        projection_member_bytes={},
        snapshot_database=GraphSnapshotDatabaseEvidence.model_construct(),
        placement_database_rows=(),
        snapshot_analysis_database_rows=(),
    )
    return request, snapshot


def test_service_publishes_nine_canonical_shards_and_replays_exact_receipt() -> None:
    request, snapshot = _snapshot()
    source = _Source(snapshot)
    artifacts = _Artifacts()
    service = PdfLearningCompletionService(
        source=source,
        artifacts=artifacts,
        source_release=validate_payload(_receipt()).source_release,
        validator=_Verifier(),
    )

    first = service.complete(request)
    replay = service.complete(request)

    assert first == replay
    assert tuple(shard.item_count for shard in first.shards) == (64,) * 8 + (8,)
    assert len({pointer.artifact.artifact_id for pointer in first.receipt.item_shards}) == 9
    assert len(artifacts.shards) == 9
    assert len(artifacts.receipts) == 1


def test_service_fails_after_publication_when_mutable_state_changed() -> None:
    request, snapshot = _snapshot()
    source = _Source(snapshot)
    source.drift = True
    service = PdfLearningCompletionService(
        source=source,
        artifacts=_Artifacts(),
        source_release=validate_payload(_receipt()).source_release,
        validator=_Verifier(),
    )

    with pytest.raises(PdfLearningCompletionError) as captured:
        service.complete(request)

    assert captured.value.code == "PDF_LEARNING_COMPLETION_CURRENT_STATE_CHANGED"
