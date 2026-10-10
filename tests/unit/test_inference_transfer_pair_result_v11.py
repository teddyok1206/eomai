"""Schema-first three-axis closure; no human/scientific or runtime acceptance."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_pair_result_v11 import (
    AxisJudgement,
    ComparisonAxis,
    PairComparisonResultV11,
    parse_pair_comparison_result_v11,
    validate_pair_comparison_references_v11,
)
from eom_catalog_contracts.item_inference_transfer import PairComparisonResult
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import profile, request, result
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_body_v11, pair_result_v11

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAME = "item-inference-transfer-pair-result-v1.1"
SCHEMA_FILE = "item-inference-transfer-pair-result-v1_1.schema.json"
SCHEMA_SHA256 = "5dd12768a41eef7d91edfbeb9effc399f2ad7525306f213bb945c3c7a3ec1451"


def rehash(body: dict[str, Any]) -> dict[str, Any]:
    body.pop("result_sha256", None)
    return body | {"result_sha256": content_sha256(body)}


def no_transfer_body() -> dict[str, Any]:
    return pair_result_body_v11(judgement="NO_TRANSFER", mappings=[], shared_idea=None)


def test_schema_canonical_resource_sha_and_declared_2020_12_match() -> None:
    canonical = ROOT / "schemas/knowledge" / SCHEMA_FILE
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / SCHEMA_FILE
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == SCHEMA_SHA256
    import json

    schema = json.loads(canonical.read_bytes())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "eom://schemas/knowledge/item-inference-transfer-pair-result/1.1"


def test_three_axes_are_independent_frozen_hypotheses_with_exact_refs() -> None:
    comparison = pair_result_v11()
    validate_pair_comparison_references_v11(request(), comparison, profile("a"), profile("b"))
    assert tuple(axis.axis for axis in comparison.axes) == tuple(ComparisonAxis)
    assert tuple(axis.judgement for axis in comparison.axes) == (
        AxisJudgement.PARTIAL,
        AxisJudgement.DIFFERENT,
        AxisJudgement.SAME,
    )
    assert comparison.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
    with pytest.raises(ValidationError):
        comparison.axes[0].explanation = "changed"


@pytest.mark.parametrize("axis_index", [0, 1])
@pytest.mark.parametrize("judgement", ["SAME", "DIFFERENT", "PARTIAL", "INSUFFICIENT"])
def test_concept_and_material_can_be_independently_insufficient(
    axis_index: int, judgement: str
) -> None:
    body = pair_result_body_v11()
    body["axes"][axis_index]["judgement"] = judgement
    if judgement == "INSUFFICIENT":
        body["axes"][axis_index].update(
            left_claim_ids=[],
            right_claim_ids=[],
            explanation="보고된 claim에 구체적인 해당 축 근거가 부족하다.",
        )
    comparison = parse_pair_comparison_result_v11(rehash(body))
    validate_pair_comparison_references_v11(request(), comparison, profile("a"), profile("b"))
    assert comparison.axes[axis_index].judgement == judgement


@pytest.mark.parametrize("judgement", ["SAME", "PARTIAL", "DIFFERENT"])
def test_crux_requires_decisive_evidence_for_every_sufficient_judgement(judgement: str) -> None:
    body = no_transfer_body()
    body["axes"][2]["judgement"] = judgement
    comparison = parse_pair_comparison_result_v11(rehash(body))
    validate_pair_comparison_references_v11(request(), comparison, profile("a"), profile("b"))
    for side in ("left_claim_ids", "right_claim_ids"):
        changed = no_transfer_body()
        changed["axes"][2]["judgement"] = judgement
        changed["axes"][2][side] = ["transferclaim_condition"]
        invalid = parse_pair_comparison_result_v11(rehash(changed))
        with pytest.raises(ValueError, match="decisive"):
            validate_pair_comparison_references_v11(request(), invalid, profile("a"), profile("b"))


def test_insufficient_crux_allows_available_refs_without_fabricating_positive_transfer() -> None:
    body = pair_result_body_v11(judgement="INSUFFICIENT", mappings=[], shared_idea=None)
    body["axes"][2].update(
        judgement="INSUFFICIENT",
        left_claim_ids=["transferclaim_condition"],
        right_claim_ids=[],
        explanation="결정적 추론의 양측 비교 근거가 보고되어 있지 않다.",
    )
    comparison = parse_pair_comparison_result_v11(rehash(body))
    validate_pair_comparison_references_v11(request(), comparison, profile("a"), profile("b"))


@pytest.mark.parametrize("overall", ["STRUCTURAL_ANALOGY", "NEAR_IDENTICAL_CANDIDATE"])
@pytest.mark.parametrize("crux", ["DIFFERENT", "INSUFFICIENT"])
def test_positive_transfer_cannot_hide_different_or_insufficient_crux(
    overall: str, crux: str
) -> None:
    body = pair_result_body_v11(judgement=overall)
    body["axes"][2]["judgement"] = crux
    invalid = rehash(body)
    with pytest.raises(JsonSchemaError):
        validate_contract(SCHEMA_NAME, invalid)
    with pytest.raises(ValidationError):
        PairComparisonResultV11.model_validate(invalid)


@pytest.mark.parametrize("shape", ["missing", "two", "four", "duplicate", "reverse"])
def test_exact_three_axis_cardinality_order_and_uniqueness_are_required(shape: str) -> None:
    body = pair_result_body_v11()
    if shape == "missing":
        del body["axes"]
    elif shape == "two":
        body["axes"] = body["axes"][:2]
    elif shape == "four":
        body["axes"].append(body["axes"][0])
    elif shape == "duplicate":
        body["axes"][1]["axis"] = "CONCEPT"
    else:
        body["axes"].reverse()
    invalid = rehash(body)
    with pytest.raises(JsonSchemaError):
        validate_contract(SCHEMA_NAME, invalid)
    with pytest.raises(ValidationError):
        PairComparisonResultV11.model_validate(invalid)


@pytest.mark.parametrize("axis_index", [0, 1, 2])
@pytest.mark.parametrize("side", ["left_claim_ids", "right_claim_ids"])
def test_sufficient_axes_need_both_sides_and_refs_cannot_be_unknown(
    axis_index: int, side: str
) -> None:
    body = pair_result_body_v11()
    body["axes"][axis_index][side] = []
    invalid = rehash(body)
    with pytest.raises(JsonSchemaError):
        validate_contract(SCHEMA_NAME, invalid)
    with pytest.raises(ValidationError):
        PairComparisonResultV11.model_validate(invalid)
    body = pair_result_body_v11()
    body["axes"][axis_index][side] = ["transferclaim_foreign"]
    invalid_comparison = parse_pair_comparison_result_v11(rehash(body))
    with pytest.raises(ValueError, match="unselected or foreign"):
        validate_pair_comparison_references_v11(
            request(), invalid_comparison, profile("a"), profile("b")
        )


@pytest.mark.parametrize("text", ["", "   \n\t", "x" * 2001, "hidden\x00text"])
def test_axis_explanation_is_bounded_nonempty_and_control_safe(text: str) -> None:
    body = pair_result_body_v11()
    body["axes"][0]["explanation"] = text
    with pytest.raises((JsonSchemaError, ValidationError)):
        parse_pair_comparison_result_v11(rehash(body))


@pytest.mark.parametrize(
    "ids",
    [
        ["transferclaim_decisive", "transferclaim_condition"],
        ["transferclaim_condition", "transferclaim_condition"],
        ["transferclaim_condition"] * 17,
    ],
)
def test_axis_refs_are_canonical_unique_and_bounded(ids: list[str]) -> None:
    body = pair_result_body_v11()
    body["axes"][0]["left_claim_ids"] = ids
    with pytest.raises((JsonSchemaError, ValidationError)):
        parse_pair_comparison_result_v11(rehash(body))


@pytest.mark.parametrize("field", ["score", "human_label", "approved", "authority"])
def test_machine_result_cannot_carry_score_approval_or_authority(field: str) -> None:
    body = pair_result_body_v11()
    body[field] = "PASS"
    with pytest.raises(JsonSchemaError):
        parse_pair_comparison_result_v11(rehash(body))


def test_axis_and_core_content_are_both_included_in_independent_result_hash() -> None:
    body = pair_result_body_v11()
    original_hash = body["result_sha256"]
    body["axes"][1]["explanation"] = "changed grounded hypothesis"
    with pytest.raises(ValidationError, match="result_sha256"):
        PairComparisonResultV11.model_validate(body)
    checked = parse_pair_comparison_result_v11(rehash(body))
    assert checked.result_sha256 != original_hash


@pytest.mark.parametrize(
    "field", ["request_id", "request_sha256", "rubric", "left_profile", "right_profile"]
)
def test_exact_request_rubric_and_profile_pins_must_match(field: str) -> None:
    body = pair_result_body_v11()
    if field == "request_id":
        body[field] = "transferrequest_" + "f" * 32
    elif field == "request_sha256":
        body[field] = "sha256:" + "f" * 64
    elif field == "rubric":
        body[field]["rubric_revision_id"] = "transferrubricrev_" + "f" * 32
    else:
        body[field]["profile_sha256"] = "sha256:" + "f" * 64
    comparison = parse_pair_comparison_result_v11(rehash(body))
    with pytest.raises(ValueError):
        validate_pair_comparison_references_v11(request(), comparison, profile("a"), profile("b"))


def test_model_copy_cannot_bypass_axis_request_or_profile_validation() -> None:
    comparison = pair_result_v11()
    axis = comparison.axes[0].model_copy(update={"left_claim_ids": ("transferclaim_foreign",)})
    invalid = comparison.model_copy(update={"axes": (axis, *comparison.axes[1:])})
    with pytest.raises(ValueError):
        validate_pair_comparison_references_v11(request(), invalid, profile("a"), profile("b"))
    invalid_request = request().model_copy(update={"direction": "B_TO_A"})
    with pytest.raises(ValueError):
        validate_pair_comparison_references_v11(
            invalid_request, comparison, profile("a"), profile("b")
        )
    invalid_profile = profile("a").model_copy(update={"claims": ()})
    with pytest.raises(ValueError):
        validate_pair_comparison_references_v11(
            request(), comparison, invalid_profile, profile("b")
        )


def test_released_v1_schema_parser_and_canonical_result_are_not_reinterpreted() -> None:
    legacy = result()
    before = canonical_json_bytes(legacy.model_dump(mode="json"))
    validate_contract("item-inference-transfer", legacy.model_dump(mode="json"))
    with pytest.raises(JsonSchemaError):
        parse_pair_comparison_result_v11(legacy.model_dump(mode="json"))
    successor = pair_result_v11()
    validate_pair_comparison_references_v11(request(), successor, profile("a"), profile("b"))
    with pytest.raises(JsonSchemaError):
        validate_contract("item-inference-transfer", successor.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        PairComparisonResult.model_validate(successor.model_dump(mode="json"))
    assert canonical_json_bytes(legacy.model_dump(mode="json")) == before


def test_contract_dependency_direction_is_pure() -> None:
    source = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_pair_result_v11.py"
    )
    tree = ast.parse(source.read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name.startswith(
            ("sqlalchemy", "eom_orchestrator", "eom_catalog_service", "subprocess", "http")
        )
        for name in imports
    )
