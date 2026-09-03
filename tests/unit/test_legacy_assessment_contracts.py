from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    AssessmentBundleCoverage,
    AssessmentSourceBundleProposal,
    AssessmentSourceBundleRevision,
    LegacyAssessmentItemProposal,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    LegacyItemPromotionRequest,
    validate_contract,
)
from eom_catalog_service.legacy_item_promotion_service import (
    LegacyItemPromotionError,
    LegacyItemPromotionService,
)
from eom_identifiers import content_sha256
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.legacy_item_extraction_artifact import (
    stage_legacy_item_extraction_result,
)
from pydantic import ValidationError

ZERO_SHA = "sha256:" + "0" * 64
NOW = "2026-09-01T00:00:00Z"


def _artifact(
    seed: str,
    member: str,
    media_type: str,
    *,
    schema_ref: str = "eom://schemas/legacy-assessment/source/1.0",
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": member,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": "sha256:" + seed * 64,
    }


def _hashed(value: dict[str, object], field: str) -> dict[str, object]:
    assert field not in value
    return {**value, field: content_sha256(value)}


def _table_only_item_content() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "locale": "ko-KR",
        "title": "표 자료 해석 문항",
        "body": [
            {
                "block_id": "block_stem",
                "type": "paragraph",
                "purpose": "stem",
                "text": "다음은 어떤 현상을 측정한 자료이다.",
            },
            {
                "block_id": "block_table",
                "type": "table",
                "purpose": "data",
                "caption": None,
                "headers": ["구분", "A", "B"],
                "rows": [["측정값", "1", "2"]],
            },
            {
                "block_id": "block_prompt",
                "type": "paragraph",
                "purpose": "prompt",
                "text": "자료에 대한 설명으로 옳은 것은?",
            },
        ],
        "interaction": {
            "type": "single_choice",
            "choices": [
                {
                    "choice_id": f"choice_{number}",
                    "label": str(number),
                    "text": f"선택지 {number}",
                }
                for number in range(1, 6)
            ],
        },
        "solution": {
            "correct_choice_ids": ["choice_2"],
            "accepted_answers": [],
            "explanation": "표의 값을 비교하면 정답을 판단할 수 있다.",
            "authoring_intent": "표 자료 해석 능력을 평가한다.",
            "statement_explanations": [],
        },
        "score": {"points": 2},
    }


def _multiple_image_statement_item_content() -> dict[str, object]:
    content = _table_only_item_content()
    content["title"] = "복수 그림과 보기 문항"
    content["body"] = [
        {
            "block_id": "block_stem",
            "type": "paragraph",
            "purpose": "stem",
            "text": "그림 (가)와 (나)는 서로 다른 과정을 나타낸 것이다.",
        },
        {
            "block_id": "block_image_a",
            "type": "image",
            "purpose": "stimulus",
            "artifact": {
                "artifact_id": "artifact_" + "a" * 32,
                "artifact_revision_id": "rev_" + "a" * 32,
                "artifact_member": "image-a.png",
                "sha256": "sha256:" + "a" * 64,
                "media_type": "image/png",
            },
            "alt_text": "과정 가",
            "width_px": 640,
            "height_px": 360,
        },
        {
            "block_id": "block_image_b",
            "type": "image",
            "purpose": "stimulus",
            "artifact": {
                "artifact_id": "artifact_" + "b" * 32,
                "artifact_revision_id": "rev_" + "b" * 32,
                "artifact_member": "image-b.png",
                "sha256": "sha256:" + "b" * 64,
                "media_type": "image/png",
            },
            "alt_text": "과정 나",
            "width_px": 640,
            "height_px": 360,
        },
        {
            "block_id": "block_prompt",
            "type": "paragraph",
            "purpose": "prompt",
            "text": "이에 대한 설명으로 옳은 것만을 <보기>에서 고른 것은?",
        },
        {
            "block_id": "block_claims",
            "type": "statement_set",
            "purpose": "claims",
            "statements": [
                {"statement_id": "statement_g", "label": "ㄱ", "text": "ㄱ 설명"},
                {"statement_id": "statement_n", "label": "ㄴ", "text": "ㄴ 설명"},
                {"statement_id": "statement_d", "label": "ㄷ", "text": "ㄷ 설명"},
            ],
        },
    ]
    solution = content["solution"]
    assert isinstance(solution, dict)
    solution["statement_explanations"] = [
        {"statement_id": "statement_g", "text": "ㄱ 해설"},
        {"statement_id": "statement_n", "text": "ㄴ 해설"},
        {"statement_id": "statement_d", "text": "ㄷ 해설"},
    ]
    return content


def _item_proposal(*, item_content: dict[str, object] | None = None) -> dict[str, object]:
    problem_anchor = "assessmentanchor_" + "1" * 32
    answer_anchor = "assessmentanchor_" + "2" * 32
    return {
        "item_proposal_id": "itemproposal_" + "1" * 32,
        "item_number": 1,
        "item_content": item_content or _table_only_item_content(),
        "authoring_intent_evidence_state": "ANALYST_RECONSTRUCTED",
        "source_anchors": [
            {
                "anchor_id": problem_anchor,
                "source": _artifact("1", "problem.pdf", "application/pdf"),
                "source_role": "PROBLEM_DOCUMENT",
                "physical_page": 1,
                "bounding_box": {"left": 100, "top": 100, "right": 9000, "bottom": 9000},
                "locator_detail": "문제 PDF 1쪽 1번",
            },
            {
                "anchor_id": answer_anchor,
                "source": _artifact("2", "answer.pdf", "application/pdf"),
                "source_role": "ANSWER_EXPLANATION_DOCUMENT",
                "physical_page": 1,
                "bounding_box": {"left": 100, "top": 100, "right": 9000, "bottom": 4000},
                "locator_detail": "정답 PDF 1쪽 1번",
            },
        ],
        "content_anchor_map": [
            {"content_path": "title", "source_anchor_ids": [problem_anchor]},
            {"content_path": "body[0]", "source_anchor_ids": [problem_anchor]},
            {"content_path": "body[1]", "source_anchor_ids": [problem_anchor]},
            {"content_path": "interaction", "source_anchor_ids": [problem_anchor]},
            {"content_path": "solution", "source_anchor_ids": [answer_anchor]},
        ],
        "curriculum_observations": [],
        "linguistic_patterns": [
            {
                "pattern_id": "linguisticpattern_" + "1" * 32,
                "prompt_form": "SELECT_CORRECT",
                "polarity": "POSITIVE",
                "condition_placement": "INLINE",
                "choice_grammar": "COMPLETE_SENTENCE",
                "uses_statement_set": False,
                "closing_expression": "옳은 것은?",
                "structure_summary": "자료 제시 뒤 옳은 설명을 고른다.",
                "reusable_pattern": "표 자료를 비교하여 하나의 설명을 선택한다.",
                "source_anchor_ids": [problem_anchor],
            }
        ],
        "visual_patterns": [
            {
                "pattern_id": "visualpattern_" + "1" * 32,
                "representation_kind": "TABLE",
                "rendering_mode": "VECTOR_LIKE",
                "color_mode": "MONOCHROME",
                "background": "WHITE",
                "panel_layout": "SINGLE",
                "features": ["GRID", "LABELS"],
                "pedagogical_function": "PRIMARY_DATA",
                "composition_summary": "한 개의 3열 표를 중심에 배치한다.",
                "reconstruction_guidance": "흰 배경과 가는 검은 격자선을 유지한다.",
                "source_anchor_ids": [problem_anchor],
            }
        ],
        "metadata_observations": [],
        "conflicts": [],
        "confidence_milli": 930,
    }


def _result(*, item_content: dict[str, object] | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "legacy-item-extraction-result/1.0",
        "extraction_result_id": "itemextractresult_" + "1" * 32,
        "extraction_request_id": "itemextractreq_" + "1" * 32,
        "request_sha256": ZERO_SHA,
        "observed_page_input_ids": ["assessmentpage_" + "1" * 32],
        "items": [_item_proposal(item_content=item_content)],
    }
    return _hashed(value, "result_sha256")


def _acceptance(
    result: LegacyItemExtractionResult,
    *,
    decision: str = "ACCEPT",
) -> LegacyItemExtractionAcceptance:
    proposal = result.items[0]
    value: dict[str, object] = {
        "schema_version": "legacy-item-extraction-acceptance/1.0",
        "acceptance_id": "itemacceptance_" + "3" * 32,
        "extraction_result": {
            "artifact": _artifact(
                "4",
                "result.json",
                "application/json",
                schema_ref=("eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"),
            ),
            "extraction_result_id": result.extraction_result_id,
            "result_sha256": result.result_sha256,
        },
        "state": "ACCEPTED" if decision == "ACCEPT" else "ACCEPTED_WITH_CORRECTIONS",
        "item_decisions": [
            {
                "item_proposal_id": proposal.item_proposal_id,
                "item_number": proposal.item_number,
                "decision": decision,
                "accepted_content_paths": [
                    item.content_path for item in proposal.content_anchor_map
                ],
                "rejected_content_paths": [],
                "required_corrections": (
                    [] if decision == "ACCEPT" else ["검토된 교정 아티팩트가 필요하다."]
                ),
            }
        ],
        "coverage_state": "COMPLETE",
        "reviewed_at": NOW,
        "reviewed_by": "operator_reviewer",
    }
    return LegacyItemExtractionAcceptance.model_validate(_hashed(value, "acceptance_sha256"))


def _promotion_request(
    acceptance: LegacyItemExtractionAcceptance,
) -> LegacyItemPromotionRequest:
    decision = acceptance.item_decisions[0]
    value: dict[str, object] = {
        "schema_version": "legacy-item-promotion-request/1.0",
        "acceptance_id": acceptance.acceptance_id,
        "acceptance_sha256": acceptance.acceptance_sha256,
        "item_proposal_id": decision.item_proposal_id,
        "item_number": decision.item_number,
        "content_pack_release_id": "packrel_" + "5" * 32,
        "primary_taxonomy_ref": None,
        "difficulty_band": None,
        "requested_by": "operator_reviewer",
        "idempotency_key": "legacy-item-promotion-test",
    }
    return LegacyItemPromotionRequest.model_validate(_hashed(value, "request_sha256"))


def _staging_request() -> LegacyItemExtractionRequest:
    value: dict[str, object] = {
        "schema_version": "legacy-item-extraction-request/1.0",
        "extraction_request_id": "itemextractreq_" + "8" * 32,
        "bundle": {
            "assessment_source_bundle_id": "assessbundle_" + "8" * 32,
            "assessment_source_bundle_revision_id": "assessbundlerev_" + "8" * 32,
            "bundle_manifest_sha256": "sha256:" + "8" * 64,
        },
        "occurrence": {
            "assessment_occurrence_id": "occurrence_" + "8" * 32,
            "assessment_occurrence_revision_id": "occurrev_" + "8" * 32,
            "occurrence_revision_sha256": "sha256:" + "8" * 64,
        },
        "layout_observation": {
            "assessment_layout_observation_id": "assessmentlayout_" + "8" * 32,
            "artifact": _artifact(
                "8",
                "assessment-layout.json",
                "application/json",
                schema_ref=("eom://schemas/legacy-assessment/assessment-layout-observation/1.0"),
            ),
            "workspace_relative_path": "source/layout-observation.json",
            "observation_sha256": "sha256:" + "8" * 64,
        },
        "work_unit_ordinal": 0,
        "expected_item_numbers": [1],
        "page_inputs": [
            {
                "page_input_id": "assessmentpage_" + "8" * 32,
                "source_role": "PROBLEM_DOCUMENT",
                "physical_page": 1,
                "source": _artifact("3", "problem.pdf", "application/pdf"),
                "image": _artifact(
                    "4",
                    "pages/problem-1.png",
                    "image/png",
                    schema_ref="eom://schemas/legacy-assessment/page-image/1.0",
                ),
                "workspace_relative_path": ("source/pages/assessmentpage_" + "8" * 32 + ".png"),
                "width_px": 1653,
                "height_px": 2337,
            },
            {
                "page_input_id": "assessmentpage_" + "9" * 32,
                "source_role": "ANSWER_EXPLANATION_DOCUMENT",
                "physical_page": 1,
                "source": _artifact("5", "answer.pdf", "application/pdf"),
                "image": _artifact(
                    "6",
                    "pages/answer-1.png",
                    "image/png",
                    schema_ref="eom://schemas/legacy-assessment/page-image/1.0",
                ),
                "workspace_relative_path": ("source/pages/assessmentpage_" + "9" * 32 + ".png"),
                "width_px": 1653,
                "height_px": 2337,
            },
        ],
        "source_materializations": [
            {
                "materialization_id": "assessmaterial_" + "7" * 32,
                "source_role": "OTHER_REVIEWED_EVIDENCE",
                "source": _artifact("7", "reference.json", "application/json"),
                "workspace_relative_path": "source/reference.json",
            }
        ],
        "execution_preset_id": "execpreset_" + "8" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "8" * 32,
        "execution_preset_sha256": "sha256:" + "8" * 64,
        "worker_result_schema_ref": (
            "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
        ),
        "created_at": NOW,
    }
    return LegacyItemExtractionRequest.model_validate(_hashed(value, "request_sha256"))


def _staging_result(request: LegacyItemExtractionRequest) -> LegacyItemExtractionResult:
    value = _result()
    value["extraction_request_id"] = request.extraction_request_id
    value["request_sha256"] = request.request_sha256
    value["observed_page_input_ids"] = [page.page_input_id for page in request.page_inputs]
    items = value["items"]
    assert isinstance(items, list) and isinstance(items[0], dict)
    anchors = items[0]["source_anchors"]
    assert isinstance(anchors, list)
    for anchor, page in zip(anchors, request.page_inputs, strict=True):
        assert isinstance(anchor, dict)
        anchor["source"] = page.image.model_dump(mode="json")
    materialization = request.source_materializations[0]
    anchors.append(
        {
            "anchor_id": "assessmentanchor_" + "3" * 32,
            "source": materialization.source.model_dump(mode="json"),
            "source_role": materialization.source_role,
            "physical_page": None,
            "bounding_box": None,
            "locator_detail": "검토된 보조 자료",
        }
    )
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return LegacyItemExtractionResult.model_validate(value)


def test_extraction_result_schema_and_typed_contract_accept_table_only_item() -> None:
    value = _result()
    validate_contract("legacy-item-extraction-result", value)
    parsed = LegacyItemExtractionResult.model_validate(value)
    assert parsed.items[0].visual_patterns[0].representation_kind == "TABLE"


def test_promotion_accepts_only_the_exact_fully_reviewed_proposal() -> None:
    result = LegacyItemExtractionResult.model_validate(_result())
    acceptance = _acceptance(result)
    command = _promotion_request(acceptance)

    assert (
        LegacyItemPromotionService._accepted_proposal_index(
            acceptance,
            result,
            command,
        )
        == 0
    )


def test_promotion_rejects_correct_and_accept_without_corrected_artifact() -> None:
    result = LegacyItemExtractionResult.model_validate(_result())
    acceptance = _acceptance(result, decision="CORRECT_AND_ACCEPT")

    with pytest.raises(LegacyItemPromotionError) as error:
        LegacyItemPromotionService._accepted_proposal_index(
            acceptance,
            result,
            _promotion_request(acceptance),
        )

    assert error.value.code == "LEGACY_ITEM_PROMOTION_REVIEW_INCOMPLETE"


def test_extraction_staging_accepts_pinned_page_images_and_materialized_source(
    tmp_path: Path,
) -> None:
    request = _staging_request()
    result = _staging_result(request)

    staged, receipt = stage_legacy_item_extraction_result(
        result=result,
        request=request,
        completed_at=datetime(2026, 9, 2, tzinfo=UTC),
        job_id="job_" + "8" * 32,
        logical_artifact_id="artifact_" + "9" * 32,
        revision_id="rev_" + "a" * 32,
        staging=tmp_path,
    )

    assert staged.primary_hash == receipt.result_artifact.sha256
    assert receipt.observed_page_input_ids == tuple(
        page.page_input_id for page in request.page_inputs
    )


def test_extraction_staging_rejects_pdf_source_as_page_anchor(tmp_path: Path) -> None:
    request = _staging_request()
    result = _staging_result(request)
    document = result.model_dump(mode="json")
    document["items"][0]["source_anchors"][0]["source"] = request.page_inputs[0].source.model_dump(
        mode="json"
    )
    document["result_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "result_sha256"}
    )

    with pytest.raises(PlatformError, match="outside the pinned page inputs"):
        stage_legacy_item_extraction_result(
            result=LegacyItemExtractionResult.model_validate(document),
            request=request,
            completed_at=datetime(2026, 9, 2, tzinfo=UTC),
            job_id="job_" + "8" * 32,
            logical_artifact_id="artifact_" + "9" * 32,
            revision_id="rev_" + "a" * 32,
            staging=tmp_path,
        )
    assert not (tmp_path / "legacy-item-extraction-artifact").exists()


def test_extraction_staging_still_rejects_unpinned_materialized_source(
    tmp_path: Path,
) -> None:
    request = _staging_request()
    result = _staging_result(request)
    document = result.model_dump(mode="json")
    document["items"][0]["source_anchors"][2]["source"] = _artifact(
        "f", "foreign.json", "application/json"
    )
    document["result_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "result_sha256"}
    )

    with pytest.raises(PlatformError, match="outside the pinned materializations"):
        stage_legacy_item_extraction_result(
            result=LegacyItemExtractionResult.model_validate(document),
            request=request,
            completed_at=datetime(2026, 9, 2, tzinfo=UTC),
            job_id="job_" + "8" * 32,
            logical_artifact_id="artifact_" + "9" * 32,
            revision_id="rev_" + "a" * 32,
            staging=tmp_path,
        )
    assert not (tmp_path / "legacy-item-extraction-artifact").exists()


def test_extraction_contract_preserves_multiple_images_and_required_statement_set_shape() -> None:
    value = _result(item_content=_multiple_image_statement_item_content())
    validate_contract("legacy-item-extraction-result", value)
    parsed = LegacyItemExtractionResult.model_validate(value)
    body_types = tuple(block.type for block in parsed.items[0].item_content.body)
    assert body_types.count("image") == 2
    assert body_types.count("statement_set") == 1
    assert body_types.count("table") == 0
    assert body_types.count("equation") == 0


def test_item_proposal_rejects_dangling_source_anchor() -> None:
    value = _item_proposal()
    patterns = value["linguistic_patterns"]
    assert isinstance(patterns, list) and isinstance(patterns[0], dict)
    patterns[0]["source_anchor_ids"] = ["assessmentanchor_" + "f" * 32]
    with pytest.raises(ValidationError, match="closed source-anchor set"):
        LegacyAssessmentItemProposal.model_validate(value)


def test_item_proposal_rejects_conflicting_statement_pattern_claim() -> None:
    value = _item_proposal()
    patterns = value["linguistic_patterns"]
    assert isinstance(patterns, list) and isinstance(patterns[0], dict)
    patterns[0]["uses_statement_set"] = True
    with pytest.raises(ValidationError, match="statement-combination choices"):
        LegacyAssessmentItemProposal.model_validate(value)


def test_result_rejects_hash_mismatch_and_duplicate_items() -> None:
    wrong_hash = _result()
    wrong_hash["result_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="canonical content"):
        LegacyItemExtractionResult.model_validate(wrong_hash)

    duplicate = _result()
    items = duplicate["items"]
    assert isinstance(items, list)
    items.append(deepcopy(items[0]))
    duplicate["result_sha256"] = content_sha256(
        {key: value for key, value in duplicate.items() if key != "result_sha256"}
    )
    with pytest.raises(ValidationError, match="proposal IDs must be unique"):
        LegacyItemExtractionResult.model_validate(duplicate)


def test_request_pins_preset_pages_and_materializations() -> None:
    value: dict[str, object] = {
        "schema_version": "legacy-item-extraction-request/1.0",
        "extraction_request_id": "itemextractreq_" + "1" * 32,
        "bundle": {
            "assessment_source_bundle_id": "assessbundle_" + "1" * 32,
            "assessment_source_bundle_revision_id": "assessbundlerev_" + "1" * 32,
            "bundle_manifest_sha256": ZERO_SHA,
        },
        "occurrence": {
            "assessment_occurrence_id": "occurrence_" + "1" * 32,
            "assessment_occurrence_revision_id": "occurrev_" + "1" * 32,
            "occurrence_revision_sha256": ZERO_SHA,
        },
        "layout_observation": {
            "assessment_layout_observation_id": "assessmentlayout_" + "1" * 32,
            "artifact": _artifact(
                "3",
                "assessment-layout.json",
                "application/json",
                schema_ref=("eom://schemas/legacy-assessment/assessment-layout-observation/1.0"),
            ),
            "workspace_relative_path": "source/layout-observation.json",
            "observation_sha256": ZERO_SHA,
        },
        "work_unit_ordinal": 0,
        "expected_item_numbers": [1, 2],
        "page_inputs": [
            {
                "page_input_id": "assessmentpage_" + "1" * 32,
                "source_role": "PROBLEM_DOCUMENT",
                "physical_page": 1,
                "source": _artifact("1", "problem.pdf", "application/pdf"),
                "image": _artifact("2", "page-0001.png", "image/png"),
                "workspace_relative_path": ("source/pages/assessmentpage_" + "1" * 32 + ".png"),
                "width_px": 2480,
                "height_px": 3508,
            }
        ],
        "source_materializations": [],
        "execution_preset_id": "execpreset_" + "1" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "1" * 32,
        "execution_preset_sha256": ZERO_SHA,
        "worker_result_schema_ref": (
            "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
        ),
        "created_at": NOW,
    }
    value = _hashed(value, "request_sha256")
    validate_contract("legacy-item-extraction-request", value)
    assert LegacyItemExtractionRequest.model_validate(value).expected_item_numbers == (1, 2)

    reversed_items = deepcopy(value)
    reversed_items["expected_item_numbers"] = [2, 1]
    reversed_items["request_sha256"] = content_sha256(
        {key: item for key, item in reversed_items.items() if key != "request_sha256"}
    )
    with pytest.raises(ValidationError, match="must be sorted"):
        LegacyItemExtractionRequest.model_validate(reversed_items)

    decompression_bomb = deepcopy(value)
    page_inputs = decompression_bomb["page_inputs"]
    assert isinstance(page_inputs, list) and isinstance(page_inputs[0], dict)
    page_inputs[0]["width_px"] = 20000
    page_inputs[0]["height_px"] = 4000
    decompression_bomb["request_sha256"] = content_sha256(
        {key: item for key, item in decompression_bomb.items() if key != "request_sha256"}
    )
    with pytest.raises(ValidationError, match="decoded-pixel"):
        LegacyItemExtractionRequest.model_validate(decompression_bomb)


def test_reviewed_bundle_pins_exact_inventory_artifact_and_member_inventory() -> None:
    value: dict[str, object] = {
        "schema_version": "assessment-source-bundle/1.0",
        "assessment_source_bundle_id": "assessbundle_" + "1" * 32,
        "assessment_source_bundle_revision_id": "assessbundlerev_" + "1" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "bundle_key": "legacy.exam.2024.sample",
        "state": "REVIEWED",
        "inventory_id": "legacyinventory_" + "1" * 32,
        "inventory_sha256": ZERO_SHA,
        "inventory_artifact": _artifact(
            "3",
            "legacy-source-inventory.json",
            "application/json",
            schema_ref="eom://schemas/legacy-knowledge/legacy-source-inventory/2.0",
        ),
        "occurrence": {
            "assessment_occurrence_id": "occurrence_" + "1" * 32,
            "assessment_occurrence_revision_id": "occurrev_" + "1" * 32,
            "occurrence_revision_sha256": ZERO_SHA,
        },
        "rights_policy": {
            "rights_policy_id": "rightspolicy_" + "1" * 32,
            "rights_policy_revision_id": "rightspolicyrev_" + "1" * 32,
            "rights_policy_sha256": ZERO_SHA,
        },
        "members": [
            {
                "member_id": "assessbundlemember_" + "1" * 32,
                "role": "PROBLEM_DOCUMENT",
                "source": _artifact("1", "problem.pdf", "application/pdf"),
                "inventory_source": {
                    "inventory_id": "legacyinventory_" + "1" * 32,
                    "inventory_sha256": ZERO_SHA,
                    "entry_key": "legacyentry_" + "1" * 32,
                    "content_sha256": "sha256:" + "1" * 64,
                },
            }
        ],
        "reviewed_at": NOW,
        "reviewed_by": "operator_" + "1" * 32,
    }
    value = _hashed(value, "bundle_manifest_sha256")
    validate_contract("assessment-source-bundle", value)
    assert AssessmentSourceBundleRevision.model_validate(value).revision_number == 1

    wrong_inventory = deepcopy(value)
    members = wrong_inventory["members"]
    assert isinstance(members, list) and isinstance(members[0], dict)
    inventory_source = members[0]["inventory_source"]
    assert isinstance(inventory_source, dict)
    inventory_source["inventory_id"] = "legacyinventory_" + "2" * 32
    wrong_inventory["bundle_manifest_sha256"] = content_sha256(
        {key: item for key, item in wrong_inventory.items() if key != "bundle_manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="inventory pointer is inconsistent"):
        AssessmentSourceBundleRevision.model_validate(wrong_inventory)

    wrong_source_hash = deepcopy(value)
    source_members = wrong_source_hash["members"]
    assert isinstance(source_members, list) and isinstance(source_members[0], dict)
    source_inventory = source_members[0]["inventory_source"]
    assert isinstance(source_inventory, dict)
    source_inventory["content_sha256"] = "sha256:" + "2" * 64
    wrong_source_hash["bundle_manifest_sha256"] = content_sha256(
        {key: item for key, item in wrong_source_hash.items() if key != "bundle_manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="source hash differs"):
        AssessmentSourceBundleRevision.model_validate(wrong_source_hash)


def test_bundle_proposal_rejects_member_from_another_inventory() -> None:
    value: dict[str, object] = {
        "schema_version": "assessment-source-bundle-proposal/1.0",
        "proposal_id": "assessbundleproposal_" + "1" * 32,
        "inventory_id": "legacyinventory_" + "1" * 32,
        "inventory_sha256": ZERO_SHA,
        "candidate_key": "legacy.exam.2024.sample",
        "members": [
            {
                "source": {
                    "inventory_id": "legacyinventory_" + "2" * 32,
                    "inventory_sha256": ZERO_SHA,
                    "entry_key": "legacyentry_" + "1" * 32,
                    "content_sha256": ZERO_SHA,
                },
                "proposed_role": "PROBLEM_DOCUMENT",
                "pairing_reason_codes": ["EXACT_OCCURRENCE_TOKEN"],
                "confidence_milli": 900,
            }
        ],
        "occurrence_observation": {
            "organization_label": None,
            "exam_family_label": "표본 시험",
            "administration_year": 2024,
            "administration_date": None,
            "session_label": None,
            "subject_label": "통합과학",
            "form_label": None,
            "source_entry_keys": ["legacyentry_" + "1" * 32],
        },
        "conflicts": [],
        "created_at": NOW,
    }
    value = _hashed(value, "proposal_sha256")
    with pytest.raises(ValidationError, match="inventory pointer is inconsistent"):
        AssessmentSourceBundleProposal.model_validate(value)


def test_coverage_requires_an_exact_nonoverlapping_partition() -> None:
    bundle = {
        "assessment_source_bundle_id": "assessbundle_" + "1" * 32,
        "assessment_source_bundle_revision_id": "assessbundlerev_" + "1" * 32,
        "bundle_manifest_sha256": ZERO_SHA,
    }
    valid_bundle = {
        "bundle": bundle,
        "expected_item_numbers": [1, 2, 3],
        "accepted_items": [
            {
                "item_number": 1,
                "acceptance_id": "itemacceptance_" + "1" * 32,
                "acceptance_sha256": ZERO_SHA,
            }
        ],
        "missing_item_numbers": [2],
        "conflict_item_numbers": [3],
    }
    assert AssessmentBundleCoverage.model_validate(valid_bundle).missing_item_numbers == (2,)

    overlap = deepcopy(valid_bundle)
    overlap["conflict_item_numbers"] = [2, 3]
    with pytest.raises(ValidationError, match="cannot overlap"):
        AssessmentBundleCoverage.model_validate(overlap)

    corpus: dict[str, object] = {
        "schema_version": "legacy-item-corpus-coverage/1.0",
        "coverage_id": "itemcoverage_" + "1" * 32,
        "inventory_id": "legacyinventory_" + "1" * 32,
        "inventory_sha256": ZERO_SHA,
        "bundle_coverages": [valid_bundle],
        "expected_item_count": 3,
        "accepted_item_count": 1,
        "missing_item_count": 1,
        "conflict_item_count": 1,
        "state": "CONFLICT",
        "created_at": NOW,
    }
    corpus = _hashed(corpus, "coverage_sha256")
    validate_contract("legacy-item-corpus-coverage", corpus)
    assert LegacyItemCorpusCoverage.model_validate(corpus).state == "CONFLICT"
