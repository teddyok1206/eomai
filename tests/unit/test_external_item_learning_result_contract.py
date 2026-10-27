"""A source-only creative archive result cannot borrow the adjacent original."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_result import (
    EXTERNAL_ITEM_LEARNING_RESULT_SCHEMA,
    ExternalItemLearningResult,
    validate_external_item_learning_result_for_source,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _result() -> dict[str, object]:
    target_region = "extregion_" + "1" * 32
    solution_region = "extregion_" + "2" * 32
    original_region = "extregion_" + "3" * 32
    result: dict[str, object] = {
        "schema_version": "external-item-learning-result/1.0",
        "result_id": "extlearnresult_" + "4" * 32,
        "input_sha256": "sha256:" + "5" * 64,
        "source_id": "extitem_" + "6" * 32,
        "source_revision_id": "extitemrev_" + "7" * 32,
        "external_number": "10310",
        "status": "PROPOSED",
        "regions": [
            {
                "region_id": region_id,
                "role": role,
                "physical_page": 1,
                "bounding_box": {"left": left, "top": 100, "right": left + 1000, "bottom": 900},
                "observed_text": observed,
                "confidence_milli": 950,
            }
            for region_id, role, left, observed in (
                (target_region, "TARGET_ITEM", 100, "문항 본문"),
                (solution_region, "EDITORIAL_SOLUTION", 2500, "편집 해설"),
                (original_region, "REFERENCE_ORIGINAL", 5000, "원본 기출 첨부"),
            )
        ],
        "proposal": {
            "item_number": 11,
            "content": {
                "schema_version": "1.0",
                "locale": "ko-KR",
                "title": "다음은 자료에 대한 설명이다.",
                "body": [
                    {
                        "block_id": "block_data",
                        "type": "table",
                        "purpose": "data",
                        "headers": ["조건", "값"],
                        "rows": [["A", "1"]],
                    }
                ],
                "interaction": {
                    "type": "single_choice",
                    "choices": [
                        {"choice_id": f"choice_{n}", "label": str(n), "text": f"선지 {n}"}
                        for n in range(1, 6)
                    ],
                },
                "solution": {
                    "correct_choice_ids": ["choice_1"],
                    "accepted_answers": [],
                    "explanation": "자료로부터 도출된다.",
                    "authoring_intent": "자료 해석을 평가한다.",
                    "statement_explanations": [],
                },
                "score": {"points": 2},
            },
            "content_region_map": [
                {"content_path": "title", "region_ids": [target_region]},
                {"content_path": "body[0]", "region_ids": [target_region]},
                {"content_path": "interaction", "region_ids": [target_region]},
                {"content_path": "solution.explanation", "region_ids": [solution_region]},
                {"content_path": "solution.correct_choice_ids", "region_ids": [solution_region]},
                {"content_path": "score.points", "region_ids": [target_region]},
            ],
            "solution_steps": [
                {
                    "step_number": 1,
                    "reasoning_summary": "조건 A를 읽고 값을 확인한다.",
                    "source_region_ids": [target_region, solution_region],
                }
            ],
            "answer_cross_check": "MATCHES_EDITORIAL_SOLUTION",
        },
        "conflicts": [],
    }
    result["result_sha256"] = content_sha256(result)
    return result


def _rehash(value: dict[str, object]) -> None:
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )


def test_result_contract_accepts_only_pinned_source_and_separate_original() -> None:
    value = _result()
    validate_contract(EXTERNAL_ITEM_LEARNING_RESULT_SCHEMA, value)
    parsed = ExternalItemLearningResult.model_validate(value)
    validate_external_item_learning_result_for_source(
        parsed,
        value["input_sha256"],
        value["source_id"],
        value["source_revision_id"],
        value["external_number"],
    )
    assert parsed.regions[2].role == "REFERENCE_ORIGINAL"


def test_result_schema_mirror_is_exact() -> None:
    canonical = ROOT / "schemas/external-item/external-item-learning-result-v1.schema.json"
    resource = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/external-item"
        / "external-item-learning-result-v1.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()


def test_result_rejects_original_leaking_into_item_or_solution() -> None:
    value = _result()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    maps = proposal["content_region_map"]
    assert isinstance(maps, list) and isinstance(maps[0], dict)
    maps[0]["region_ids"] = ["extregion_" + "3" * 32]
    _rehash(value)
    validate_contract(EXTERNAL_ITEM_LEARNING_RESULT_SCHEMA, value)
    with pytest.raises(ValidationError, match="unrelated source region"):
        ExternalItemLearningResult.model_validate(value)

    value = _result()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    steps = proposal["solution_steps"]
    assert isinstance(steps, list) and isinstance(steps[0], dict)
    steps[0]["source_region_ids"] = ["extregion_" + "3" * 32]
    _rehash(value)
    with pytest.raises(ValidationError, match="unrelated source region"):
        ExternalItemLearningResult.model_validate(value)


def test_result_rejects_unresolved_proposal_and_stale_hash() -> None:
    value = _result()
    value["status"] = "NEEDS_DECISION"
    _rehash(value)
    with pytest.raises(ValidationError, match="blocking conflict"):
        ExternalItemLearningResult.model_validate(value)

    value = _result()
    value["external_number"] = "99999"
    with pytest.raises(ValidationError, match="result hash differs"):
        ExternalItemLearningResult.model_validate(value)

    value = _result()
    value["external_number"] = "99999"
    _rehash(value)
    parsed = ExternalItemLearningResult.model_validate(value)
    with pytest.raises(ValueError, match="pinned source"):
        validate_external_item_learning_result_for_source(
            parsed,
            "sha256:" + "5" * 64,
            "extitem_" + "6" * 32,
            "extitemrev_" + "7" * 32,
            "10310",
        )


def test_result_can_quarantine_an_unreadable_source_without_item_promotion() -> None:
    value = _result()
    value["status"] = "NEEDS_DECISION"
    value["proposal"] = None
    value["conflicts"] = [
        {
            "conflict_code": "UNREADABLE_CONTENT",
            "description": "문항의 왼쪽 표를 읽을 수 없다.",
            "source_region_ids": ["extregion_" + "1" * 32],
            "blocking": True,
        }
    ]
    _rehash(value)
    validate_contract(EXTERNAL_ITEM_LEARNING_RESULT_SCHEMA, value)
    parsed = ExternalItemLearningResult.model_validate(value)
    assert parsed.proposal is None


def test_result_allows_editorial_solution_but_not_original_in_solution() -> None:
    value = _result()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    maps = proposal["content_region_map"]
    assert isinstance(maps, list) and isinstance(maps[3], dict)
    maps[3]["region_ids"] = ["extregion_" + "3" * 32]
    _rehash(value)
    with pytest.raises(ValidationError, match="unrelated source region"):
        ExternalItemLearningResult.model_validate(value)


def test_result_rejects_nonexistent_or_unmapped_content_fields() -> None:
    value = _result()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    maps = proposal["content_region_map"]
    assert isinstance(maps, list) and isinstance(maps[1], dict)
    maps[1]["content_path"] = "body[99]"
    _rehash(value)
    with pytest.raises(ValidationError, match="required Item fields"):
        ExternalItemLearningResult.model_validate(value)

    value = _result()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    maps = proposal["content_region_map"]
    assert isinstance(maps, list)
    maps.append({"content_path": "body[99].text", "region_ids": ["extregion_" + "1" * 32]})
    _rehash(value)
    with pytest.raises(ValidationError, match="does not resolve"):
        ExternalItemLearningResult.model_validate(value)


def test_result_schema_rejects_malformed_authority_and_media() -> None:
    value = deepcopy(_result())
    value["source_revision_id"] = "../latest"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(EXTERNAL_ITEM_LEARNING_RESULT_SCHEMA, value)
