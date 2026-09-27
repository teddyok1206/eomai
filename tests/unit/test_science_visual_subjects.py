from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_contracts import KnowledgeAnalysisResultV9, LegacyItemExtractionResult
from eom_catalog_service.science_visual_subjects import (
    AcceptedVisualSubjectSource,
    ScienceVisualSubjectProjectionError,
    classify_science_visual_subjects,
    project_science_visual_subject_inventory,
)
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualSubjectInventory,
    content_sha256,
)


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _pointer(
    character: str,
    *,
    schema_ref: str,
    member_path: str,
    sha256: str,
) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + character * 32,
        artifact_revision_id="rev_" + character * 32,
        member_path=member_path,
        schema_ref=schema_ref,
        media_type="application/json",
        sha256=sha256,
    )


def _source(*, accepted_hash: str = _sha("1")) -> AcceptedVisualSubjectSource:
    anchors = ("assessmentanchor_" + "0" * 32,)
    patterns = (
        SimpleNamespace(
            pattern_id="visualpattern_" + "a" * 32,
            representation_kind="DIAGRAM",
            rendering_mode="VECTOR_LIKE",
            composition_summary="학생이 자동차의 범퍼를 관찰하는 단순 선화",
            reconstruction_guidance="학생과 자동차를 익명 선화와 정확한 벡터로 재구성한다.",
            source_anchor_ids=anchors,
        ),
        SimpleNamespace(
            pattern_id="visualpattern_" + "b" * 32,
            representation_kind="APPARATUS",
            rendering_mode="VECTOR_LIKE",
            composition_summary="비커 속 수용액과 시험관을 나란히 배치한 실험 장치",
            reconstruction_guidance="액면과 기구 외곽선을 편집 가능한 선으로 그린다.",
            source_anchor_ids=anchors,
        ),
        SimpleNamespace(
            pattern_id="visualpattern_" + "c" * 32,
            representation_kind="NONE",
            rendering_mode="TEXT_ONLY",
            composition_summary="시각 자료 없음",
            reconstruction_guidance="그리지 않는다.",
            source_anchor_ids=anchors,
        ),
    )
    proposal = SimpleNamespace(
        item_proposal_id="itemproposal_" + "d" * 32,
        item_number=7,
        visual_patterns=patterns,
    )
    extraction_hash = _sha("2")
    extraction = SimpleNamespace(
        extraction_result_id="itemextractresult_" + "e" * 32,
        result_sha256=extraction_hash,
        items=(proposal,),
    )
    accepted_source = SimpleNamespace(
        item_revision_id="itemrev_" + "f" * 32,
        item_proposal_id=proposal.item_proposal_id,
        item_number=proposal.item_number,
        extraction_result_id=extraction.extraction_result_id,
        extraction_result_sha256=extraction_hash,
    )
    accepted = SimpleNamespace(source=accepted_source, result_sha256=accepted_hash)
    return AcceptedVisualSubjectSource(
        accepted=cast(KnowledgeAnalysisResultV9, accepted),
        accepted_result=_pointer(
            "1",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/9.0",
            member_path="normalized/accepted-result.json",
            sha256=accepted_hash,
        ),
        extraction=cast(LegacyItemExtractionResult, extraction),
        extraction_result=_pointer(
            "2",
            schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
            member_path="normalized/result.json",
            sha256=extraction_hash,
        ),
    )


def _inventory() -> LocalImageScienceVisualSubjectInventory:
    return project_science_visual_subject_inventory(
        sources=(_source(),),
        training_authorization=_pointer(
            "3",
            schema_ref="eom://schemas/image-provider/local-image-training-authorization/1.0",
            member_path="manifests/training-authorization.json",
            sha256=_sha("3"),
        ),
        pattern_inventory=_pointer(
            "4",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-visual-campaign-pattern-inventory/1.0"
            ),
            member_path="manifests/science-visual-campaign-pattern-inventory.json",
            sha256=_sha("4"),
        ),
        target_set_sha256=_sha("5"),
        created_at=datetime(2026, 9, 27, tzinfo=UTC),
        created_by="projection_test",
    )


def test_projection_indexes_specific_objects_and_closes_observation_population() -> None:
    inventory = _inventory()
    by_key = {subject.subject_key: subject for subject in inventory.subjects}

    assert {"BEAKER", "SOLUTION_LIQUID", "STUDENT_OR_TEACHER", "TEST_TUBE", "VEHICLE_CAR"} <= set(
        by_key
    )
    assert by_key["VEHICLE_CAR"].render_route == "PYTHON_SVG"
    assert by_key["STUDENT_OR_TEACHER"].renderer_primitive == "GENERIC_LABELLED_DIAGRAM"
    assert by_key["BEAKER"].renderer_primitive == "APPARATUS"
    assert inventory.source_visual_observation_count == 3
    assert inventory.covered_visual_observation_count == 2
    assert len(inventory.omissions) == 1
    assert inventory.inventory_sha256 == content_sha256(
        inventory.model_dump(mode="json", exclude={"inventory_sha256"})
    )


def test_classifier_routes_unknown_raster_to_explicit_blocked_subject() -> None:
    (definition,) = classify_science_visual_subjects(
        composition_summary="식별되지 않은 자연 사진",
        reconstruction_guidance="원본 질감을 보존한다.",
        representation_kind="PHOTOGRAPH",
        rendering_mode="RASTER",
    )
    assert definition.key == "UNCLASSIFIED_RASTER_SUBJECT"
    assert definition.route == "BLOCKED"
    assert definition.blocked_reason == "NO_SAFE_RENDER_ROUTE"


@pytest.mark.parametrize(
    ("summary", "expected_subject"),
    (
        ("초전도 전력 케이블 단면과 액체 질소를 표시한다.", "SUPERCONDUCTING_CABLE"),
        ("유전적 다양성, 종 다양성, 생태계 다양성의 세 패널이다.", "BIODIVERSITY"),
        ("LED등과 도꼬마리 열매를 나란히 제시한다.", "BURR_FRUIT"),
        ("반도체 소자와 여러 전자 부품을 제시한다.", "ELECTRONIC_COMPONENT"),
        ("400 nm부터 700 nm까지 세 스펙트럼 띠를 비교한다.", "SPECTRUM_PLOT"),
        ("동심층에 원소가 표시된 별 내부 구조이다.", "STELLAR_INTERIOR"),
        ("두 원형 분할 그래프를 나란히 배치한다.", "PIE_CHART"),
        ("과산화 수소와 카탈레이스의 효소 반응 과정이다.", "ENZYME_REACTION"),
        ("A와 B의 시간 간격별 위치를 격자 위에 표시한다.", "MOTION_SEQUENCE"),
        ("과학 탐구 보고서에 준비물, 탐구 과정, 탐구 결과를 표시한다.", "SCIENCE_REPORT_PANEL"),
        ("A, B, C 세 원이 겹친 벤 다이어그램이다.", "VENN_DIAGRAM"),
        ("사과나무에 매달린 A와 낙하 중인 B를 표시한다.", "APPLE_TREE"),
        ("변전소와 송전선 A, B가 송전탑으로 이어진다.", "ELECTRIC_GRID"),
        ("규산염 사면체와 휘석 및 각섬석 구조이다.", "SILICATE_STRUCTURE"),
        ("지지대, 매달린 추, 회전 원통으로 된 지진계이다.", "SEISMOMETER"),
        ("전기차 측면과 길이·너비 치수 화살표이다.", "VEHICLE_CAR"),
        ("공기 중과 진공 중 깃털과 구슬의 낙하 위치이다.", "MOTION_SEQUENCE"),
    ),
)
def test_classifier_covers_previously_generic_or_blocked_elements(
    summary: str,
    expected_subject: str,
) -> None:
    definitions = classify_science_visual_subjects(
        composition_summary=summary,
        reconstruction_guidance="원문 구조를 유지한다.",
        representation_kind="COMPOSITE",
        rendering_mode="RASTER",
    )
    keys = {definition.key for definition in definitions}
    assert expected_subject in keys
    assert "GENERIC_SCIENCE_DIAGRAM" not in keys
    assert "UNCLASSIFIED_RASTER_SUBJECT" not in keys


def test_projection_rejects_extraction_semantic_hash_drift() -> None:
    source = _source(accepted_hash=_sha("8"))
    accepted_source = SimpleNamespace(
        **{
            **source.accepted.source.__dict__,
            "extraction_result_sha256": _sha("9"),
        }
    )
    drifted = AcceptedVisualSubjectSource(
        accepted=cast(
            KnowledgeAnalysisResultV9,
            SimpleNamespace(source=accepted_source, result_sha256=source.accepted.result_sha256),
        ),
        accepted_result=source.accepted_result,
        extraction=source.extraction,
        extraction_result=source.extraction_result,
    )
    with pytest.raises(ScienceVisualSubjectProjectionError, match="SOURCE_POINTER_MISMATCH"):
        project_science_visual_subject_inventory(
            sources=(drifted,),
            training_authorization=_pointer(
                "3",
                schema_ref="eom://schemas/image-provider/local-image-training-authorization/1.0",
                member_path="manifests/training-authorization.json",
                sha256=_sha("3"),
            ),
            pattern_inventory=_pointer(
                "4",
                schema_ref=(
                    "eom://schemas/image-provider/"
                    "local-image-science-visual-campaign-pattern-inventory/1.0"
                ),
                member_path="manifests/science-visual-campaign-pattern-inventory.json",
                sha256=_sha("4"),
            ),
            target_set_sha256=_sha("5"),
            created_at=datetime(2026, 9, 27, tzinfo=UTC),
            created_by="projection_test",
        )
