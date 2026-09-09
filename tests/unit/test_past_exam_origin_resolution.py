from __future__ import annotations

from collections.abc import Iterable
from copy import copy
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeGraphStructureManifestV5,
)
from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRecord,
    AssessmentOccurrenceRevisionRecord,
    ItemOriginDerivationRecord,
    ItemOriginOccurrenceRecord,
    ItemOriginProfileRecord,
)
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.legacy_assessment_models import (
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_catalog_service.past_exam_origin_resolution import (
    PastExamOriginInput,
    PastExamOriginResolutionError,
    PastExamOriginStatus,
    resolve_past_exam_origins,
)
from sqlalchemy.orm import Session


class _BulkSession:
    def __init__(self, rows: dict[type[Any], tuple[Any, ...]]) -> None:
        self.rows = rows
        self.scalar_calls = 0

    def scalars(self, statement: Any) -> Iterable[Any]:
        self.scalar_calls += 1
        entity = statement.column_descriptions[0]["entity"]
        return self.rows.get(entity, ())


def _hash(seed: int) -> str:
    return "sha256:" + f"{seed:064x}"


def _fixture(
    seed: int = 1,
    *,
    school_level: str = "HIGH_SCHOOL",
    grade: int = 2,
    month: int = 6,
) -> tuple[PastExamOriginInput, dict[type[Any], tuple[Any, ...]]]:
    item_id = f"item_{seed}"
    item_revision_id = f"itemrev_{seed}"
    profile_id = f"originprofile_{seed}"
    acceptance_id = f"itemacceptance_{seed}"
    proposal_id = f"itemproposal_{seed}"
    result_id = f"itemextractresult_{seed}"
    occurrence_id = f"occurrence_{seed}"
    occurrence_revision_id = f"occurrev_{seed}"
    bundle_id = f"assessbundle_{seed}"
    bundle_revision_id = f"assessbundlerev_{seed}"
    item_manifest_sha256 = _hash(seed + 10_000)
    occurrence_sha256 = _hash(seed + 20_000)
    bundle_sha256 = _hash(seed + 30_000)
    acceptance_sha256 = _hash(seed + 40_000)
    result_sha256 = _hash(seed + 50_000)
    rights_sha256 = _hash(seed + 60_000)
    acceptance_artifact = SimpleNamespace(
        artifact_id=f"acceptance-artifact-{seed}",
        artifact_revision_id=f"acceptance-revision-{seed}",
        member_path="acceptance.json",
        schema_ref="acceptance/1.0",
        media_type="application/json",
        sha256=_hash(seed + 70_000),
    )
    result_artifact = SimpleNamespace(
        artifact_id=f"result-artifact-{seed}",
        artifact_revision_id=f"result-revision-{seed}",
        member_path="result.json",
        schema_ref="result/1.0",
        media_type="application/json",
        sha256=_hash(seed + 80_000),
    )
    source = ApprovedPastExamItemKnowledgeSourceV3.model_construct(
        item_id=item_id,
        item_revision_id=item_revision_id,
        extraction_acceptance_id=acceptance_id,
        extraction_acceptance_sha256=acceptance_sha256,
        extraction_acceptance_artifact=acceptance_artifact,
        extraction_result_id=result_id,
        extraction_result_sha256=result_sha256,
        extraction_result_artifact=result_artifact,
        item_proposal_id=proposal_id,
        item_number=seed,
        bundle=SimpleNamespace(
            assessment_source_bundle_id=bundle_id,
            assessment_source_bundle_revision_id=bundle_revision_id,
            bundle_manifest_sha256=bundle_sha256,
        ),
    )
    rights = {
        "rights_policy_id": f"rights-{seed}",
        "rights_policy_revision_id": f"rights-revision-{seed}",
        "rights_policy_sha256": rights_sha256,
    }
    rows: dict[type[Any], tuple[Any, ...]] = {
        ItemOriginProfileRecord: (
            SimpleNamespace(
                item_origin_profile_id=profile_id,
                item_id=item_id,
                item_revision_id=item_revision_id,
                item_manifest_sha256=item_manifest_sha256,
                source_domain="EXTERNAL_INSTITUTION",
                profile_sha256=_hash(seed + 90_000),
                **rights,
            ),
        ),
        ItemOriginOccurrenceRecord: (
            SimpleNamespace(
                item_origin_occurrence_id=seed,
                item_origin_profile_id=profile_id,
                assessment_occurrence_id=occurrence_id,
                assessment_occurrence_revision_id=occurrence_revision_id,
                occurrence_revision_sha256=occurrence_sha256,
            ),
        ),
        ItemOriginDerivationRecord: (
            SimpleNamespace(
                item_origin_derivation_id=seed,
                item_origin_profile_id=profile_id,
                source_kind="ASSESSMENT_SOURCE_BUNDLE_REVISION",
                logical_id=bundle_id,
                revision_id=bundle_revision_id,
                manifest_sha256=bundle_sha256,
                relation="DIGITIZED_FROM",
            ),
        ),
        AssessmentOccurrenceRevisionRecord: (
            SimpleNamespace(
                assessment_occurrence_id=occurrence_id,
                assessment_occurrence_revision_id=occurrence_revision_id,
                revision_sha256=occurrence_sha256,
                schema_version="assessment-occurrence-revision/2.0",
                revision_state="REVIEWED",
                display_label=f"Occurrence {seed}",
                administration_year=2025,
                administration_month=month,
                target_school_level=school_level,
                target_grade=grade,
                subject_key="integrated-science",
                **rights,
            ),
        ),
        AssessmentOccurrenceRecord: (
            SimpleNamespace(
                assessment_occurrence_id=occurrence_id,
                lifecycle_state="ACTIVE",
                current_revision_id=occurrence_revision_id,
            ),
        ),
        AssessmentSourceBundleRevisionRecord: (
            SimpleNamespace(
                assessment_source_bundle_id=bundle_id,
                assessment_source_bundle_revision_id=bundle_revision_id,
                bundle_manifest_sha256=bundle_sha256,
                state="REVIEWED",
                assessment_occurrence_id=occurrence_id,
                assessment_occurrence_revision_id=occurrence_revision_id,
                occurrence_revision_sha256=occurrence_sha256,
                **rights,
            ),
        ),
        LegacyItemExtractionAcceptanceRecord: (
            SimpleNamespace(
                acceptance_id=acceptance_id,
                acceptance_sha256=acceptance_sha256,
                state="ACCEPTED",
                coverage_state="COMPLETE",
                extraction_result_id=result_id,
                result_sha256=result_sha256,
                acceptance_artifact_id=acceptance_artifact.artifact_id,
                acceptance_artifact_revision_id=acceptance_artifact.artifact_revision_id,
                acceptance_artifact_member_path=acceptance_artifact.member_path,
                acceptance_artifact_schema_ref=acceptance_artifact.schema_ref,
                acceptance_artifact_media_type=acceptance_artifact.media_type,
                acceptance_artifact_sha256=acceptance_artifact.sha256,
                result_artifact_id=result_artifact.artifact_id,
                result_artifact_revision_id=result_artifact.artifact_revision_id,
                result_artifact_member_path=result_artifact.member_path,
                result_artifact_schema_ref=result_artifact.schema_ref,
                result_artifact_media_type=result_artifact.media_type,
                result_artifact_sha256=result_artifact.sha256,
            ),
        ),
        LegacyItemExtractionDecisionRecord: (
            SimpleNamespace(
                acceptance_id=acceptance_id,
                item_proposal_id=proposal_id,
                item_number=seed,
                decision="ACCEPT",
            ),
        ),
        ItemRevisionRecord: (
            SimpleNamespace(
                item_id=item_id,
                item_revision_id=item_revision_id,
                revision_state="APPROVED",
                registration_key=f"legacy-item-promotion:{acceptance_id}:{proposal_id}",
                manifest_sha256=item_manifest_sha256,
            ),
        ),
        ItemRecord: (
            SimpleNamespace(
                item_id=item_id,
                lifecycle_state="ACTIVE",
                current_revision_id=item_revision_id,
            ),
        ),
    }
    return PastExamOriginInput(analysis_run_id=f"analysisrun_{seed}", source=source), rows


def _session(rows: dict[type[Any], tuple[Any, ...]]) -> tuple[Session, _BulkSession]:
    fake = _BulkSession(rows)
    return cast(Session, fake), fake


def test_bulk_resolver_returns_exact_eligible_and_policy_excluded_values() -> None:
    eligible, eligible_rows = _fixture()
    excluded, excluded_rows = _fixture(2, grade=1, month=3)
    rows = {model: (*eligible_rows[model], *excluded_rows[model]) for model in eligible_rows}
    session, _ = _session(rows)

    resolutions = resolve_past_exam_origins(session, (eligible, excluded))

    assert tuple(resolution.status for resolution in resolutions) == (
        PastExamOriginStatus.ELIGIBLE,
        PastExamOriginStatus.POLICY_EXCLUDED,
    )
    assert resolutions[0].item_revision_id == eligible.source.item_revision_id
    assert resolutions[0].assessment_source_bundle_revision_id == (
        eligible.source.bundle.assessment_source_bundle_revision_id
    )


def test_final_publication_validator_compares_placements_with_shared_resolution() -> None:
    origin, rows = _fixture()
    first_session, _ = _session(rows)
    resolution = resolve_past_exam_origins(first_session, (origin,))[0]
    placement_value = asdict(resolution)
    placement_value.pop("status")
    placement = SimpleNamespace(**placement_value)
    structure = KnowledgeGraphStructureManifestV5.model_construct(
        assessment_item_occurrences=(placement,)
    )
    analysis = AcceptedAnalysisProposal(
        analysis_run_id=origin.analysis_run_id,
        source=origin.source,
        accepted_result=cast(Any, object()),
        proposal=cast(Any, object()),
    )

    valid_session, _ = _session(rows)
    KnowledgeGraphPublicationService._validate_assessment_item_occurrences(
        valid_session,
        structure,
        (analysis,),
    )

    placement.item_number += 1
    invalid_session, _ = _session(rows)
    with pytest.raises(KnowledgeGraphPublicationError) as caught:
        KnowledgeGraphPublicationService._validate_assessment_item_occurrences(
            invalid_session,
            structure,
            (analysis,),
        )
    assert caught.value.code == "KNOWLEDGE_GRAPH_ASSESSMENT_PLACEMENT_INVALID"


def test_final_publication_validator_maps_shared_origin_failure() -> None:
    origin, rows = _fixture()
    valid_session, _ = _session(rows)
    resolution = resolve_past_exam_origins(valid_session, (origin,))[0]
    placement_value = asdict(resolution)
    placement_value.pop("status")
    structure = KnowledgeGraphStructureManifestV5.model_construct(
        assessment_item_occurrences=(SimpleNamespace(**placement_value),)
    )
    analysis = AcceptedAnalysisProposal(
        analysis_run_id=origin.analysis_run_id,
        source=origin.source,
        accepted_result=cast(Any, object()),
        proposal=cast(Any, object()),
    )
    rows[ItemOriginProfileRecord] = ()
    invalid_session, _ = _session(rows)

    with pytest.raises(KnowledgeGraphPublicationError) as caught:
        KnowledgeGraphPublicationService._validate_assessment_item_occurrences(
            invalid_session,
            structure,
            (analysis,),
        )

    assert caught.value.code == "KNOWLEDGE_GRAPH_ASSESSMENT_PLACEMENT_INVALID"
    assert isinstance(caught.value.__cause__, PastExamOriginResolutionError)


@pytest.mark.parametrize(
    ("case", "reason"),
    (
        ("missing-profile", "origin_profile_cardinality"),
        ("missing-occurrence", "origin_occurrence_cardinality"),
        ("duplicate-occurrence", "origin_occurrence_cardinality"),
        ("missing-derivation", "origin_derivation_cardinality"),
        ("duplicate-derivation", "origin_derivation_cardinality"),
        ("missing-decision", "extraction_decision_cardinality"),
        ("decision-reject", "extraction_decision_invalid"),
        ("occurrence-hash-split", "occurrence_revision_invalid"),
        ("bundle-hash-split", "bundle_derivation_invalid"),
        ("rights-split", "rights_policy_invalid"),
        ("wrong-relation", "bundle_derivation_invalid"),
        ("item-not-current", "item_revision_or_profile_invalid"),
        ("acceptance-hash-split", "extraction_acceptance_invalid"),
    ),
)
def test_bulk_resolver_rejects_missing_duplicate_stale_and_hash_split_origins(
    case: str,
    reason: str,
) -> None:
    origin, rows = _fixture()
    if case == "missing-profile":
        rows[ItemOriginProfileRecord] = ()
    elif case == "missing-occurrence":
        rows[ItemOriginOccurrenceRecord] = ()
    elif case == "duplicate-occurrence":
        rows[ItemOriginOccurrenceRecord] += (copy(rows[ItemOriginOccurrenceRecord][0]),)
    elif case == "missing-derivation":
        rows[ItemOriginDerivationRecord] = ()
    elif case == "duplicate-derivation":
        rows[ItemOriginDerivationRecord] += (copy(rows[ItemOriginDerivationRecord][0]),)
    elif case == "missing-decision":
        rows[LegacyItemExtractionDecisionRecord] = ()
    elif case == "decision-reject":
        rows[LegacyItemExtractionDecisionRecord][0].decision = "REJECT"
    elif case == "occurrence-hash-split":
        rows[ItemOriginOccurrenceRecord][0].occurrence_revision_sha256 = _hash(999_001)
    elif case == "bundle-hash-split":
        rows[AssessmentSourceBundleRevisionRecord][0].bundle_manifest_sha256 = _hash(999_002)
    elif case == "rights-split":
        rows[AssessmentOccurrenceRevisionRecord][0].rights_policy_sha256 = _hash(999_003)
    elif case == "wrong-relation":
        rows[ItemOriginDerivationRecord][0].relation = "DERIVED_FROM"
    elif case == "item-not-current":
        rows[ItemRecord][0].current_revision_id = "itemrev_other"
    elif case == "acceptance-hash-split":
        rows[LegacyItemExtractionAcceptanceRecord][0].acceptance_sha256 = _hash(999_004)
    session, _ = _session(rows)

    with pytest.raises(PastExamOriginResolutionError) as caught:
        resolve_past_exam_origins(session, (origin,))

    assert caught.value.code == "PAST_EXAM_ORIGIN_INVALID"
    assert caught.value.reason == reason
    assert caught.value.analysis_run_id == origin.analysis_run_id


def test_bulk_resolver_scales_to_520_items_with_a_fixed_query_count() -> None:
    fixtures = tuple(_fixture(seed) for seed in range(1, 521))
    rows = {
        model: tuple(row for _, fixture_rows in fixtures for row in fixture_rows[model])
        for model in fixtures[0][1]
    }
    session, fake = _session(rows)

    resolutions = resolve_past_exam_origins(
        session,
        tuple(origin for origin, _ in fixtures),
    )

    assert len(resolutions) == 520
    assert fake.scalar_calls == 10
