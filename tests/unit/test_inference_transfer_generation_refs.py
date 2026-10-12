"""Generation set serialization only; no live candidate, model or owner calls."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_pair_result_v11 import (
    PairComparisonResultV11,
    parse_pair_comparison_result_v11,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfile
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_RESULT_SCHEMA,
    TRANSFER_PAIR_RESULT_SCHEMA_V11,
    InferenceTransferPairWorkerRequestV11,
    validate_inference_transfer_worker_result_v11,
)
from eom_workflow.schemas import (
    WorkflowSchemaError,
    load_codex_result_schema,
    load_role_result_schema,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import profile, request, sha
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_v11
from tests.unit.test_inference_transfer_generation_hash import _document, _validate

COLLECTIONS = ("axes", "mappings", "differences", "new_reasoning")
SIDES = ("left_claim_ids", "right_claim_ids")
MEMBERS = (
    ("axes", 0),
    ("axes", 2),
    ("mappings", 0),
    ("mappings", 1),
    ("differences", 0),
    ("new_reasoning", 0),
)


def _expanded_profile(seed: str) -> InferenceTransferProfile:
    body = profile(seed).model_dump(mode="json", exclude={"profile_sha256"})
    original = list(body["claims"])
    body["claims"].extend(
        claim | {"claim_id": claim["claim_id"] + "_secondary"} for claim in original
    )
    body["claims"].append(
        original[0]
        | {
            "claim_id": "transferclaim_misconception",
            "facet": "MISCONCEPTION",
            "text": "마찰이 없다는 부정 조건을 무시하면 오답이다.",
        }
    )
    body["claims"].sort(key=lambda claim: claim["claim_id"])
    return InferenceTransferProfile.model_validate(body | {"profile_sha256": content_sha256(body)})


def _context() -> tuple[dict[str, Any], InferenceTransferPairWorkerRequestV11]:
    left, right = _expanded_profile("a"), _expanded_profile("b")
    selected = request(left, right)
    worker = InferenceTransferPairWorkerRequestV11(
        comparison=selected, left_profile=left, right_profile=right
    )
    document = _document()
    output = pair_result_v11(selected).model_dump(mode="json", exclude={"result_sha256"})
    for axis in output["axes"]:
        names = (
            ("decisive", "decisive_secondary")
            if axis["axis"] == "CRUX"
            else ("condition", "condition_secondary", "misconception")
        )
        for side in SIDES:
            axis[side] = ["transferclaim_" + name for name in names]
    for mapping in output["mappings"]:
        name = "condition" if mapping["facet"] == "GIVEN_CONDITION" else "decisive"
        for side in SIDES:
            mapping[side] = ["transferclaim_" + name, "transferclaim_" + name + "_secondary"]
    for collection in ("differences", "new_reasoning"):
        output[collection] = [
            {
                "left_claim_ids": ["transferclaim_condition", "transferclaim_misconception"],
                "right_claim_ids": ["transferclaim_condition", "transferclaim_misconception"],
                "explanation": "부정 조건과 오개념을 제거하지 않는 합성 차이·추론 설명이다.",
            },
            {
                "left_claim_ids": [],
                "right_claim_ids": ["transferclaim_decisive"],
                "explanation": "오른쪽에만 필요한 합성 추론이며 좌우 연결을 바꾸지 않는다.",
            },
        ]
    document["output"] = output
    return document, worker


@pytest.mark.parametrize("collection,index", MEMBERS)
@pytest.mark.parametrize("side", SIDES)
def test_unique_unsorted_generation_refs_serialize_without_semantic_changes(
    collection: str, index: int, side: str
) -> None:
    document, worker = _context()
    expected = copy.deepcopy(document)
    document["output"][collection][index][side].reverse()
    before = copy.deepcopy(document)
    Draft202012Validator(load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)).validate(
        document
    )
    parsed = _validate(document)
    canonical = parsed.model_dump(mode="json")
    expected["output"]["result_sha256"] = content_sha256(expected["output"])
    assert canonical == expected
    assert canonical_json_bytes(document) == canonical_json_bytes(before)
    assert "result_sha256" not in document["output"]
    assert parsed.output.result_sha256 != content_sha256(before["output"])
    validate_inference_transfer_worker_result_v11(worker, parsed.output)
    Draft202012Validator(load_role_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)).validate(
        canonical
    )
    for family in COLLECTIONS:
        for original, normalized in zip(
            before["output"][family], canonical["output"][family], strict=True
        ):
            assert original["explanation"] == normalized["explanation"]
            for reference_side in SIDES:
                assert len(original[reference_side]) == len(normalized[reference_side])
                assert set(original[reference_side]) == set(normalized[reference_side])
    assert "부정 조건" in canonical["output"]["new_reasoning"][0]["explanation"]
    assert (
        "transferclaim_misconception" in canonical["output"]["new_reasoning"][0]["right_claim_ids"]
    )


def test_all_unsorted_sets_normalize_together_without_reordering_objects() -> None:
    document, worker = _context()
    expected = copy.deepcopy(document["output"])
    for collection in COLLECTIONS:
        for member in document["output"][collection]:
            for side in SIDES:
                member[side].reverse()
    before = copy.deepcopy(document)
    parsed = _validate(document)
    assert parsed.output.model_dump(mode="json", exclude={"result_sha256"}) == expected
    assert parsed.output.result_sha256 == content_sha256(expected)
    assert document == before
    validate_inference_transfer_worker_result_v11(worker, parsed.output)


@pytest.mark.parametrize("collection", COLLECTIONS)
@pytest.mark.parametrize("side", SIDES)
def test_duplicate_refs_are_not_deduplicated_or_admitted(collection: str, side: str) -> None:
    document, _worker = _context()
    references = document["output"][collection][0][side]
    references.reverse()
    references.append(references[0])
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        _validate(document)
    assert document == before


@pytest.mark.parametrize("collection", COLLECTIONS)
@pytest.mark.parametrize("side", SIDES)
def test_unique_foreign_refs_remain_foreign_after_serialization(collection: str, side: str) -> None:
    document, worker = _context()
    references = document["output"][collection][0][side]
    references.append("transferclaim_foreign")
    references.reverse()
    before = copy.deepcopy(document)
    parsed = _validate(document)
    normalized = parsed.output.model_dump(mode="json")[collection][0][side]
    assert set(normalized) == set(references)
    assert len(normalized) == len(references)
    with pytest.raises(ValueError):
        validate_inference_transfer_worker_result_v11(worker, parsed.output)
    assert document == before


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "transferclaim_condition",
        [True],
        [1],
        [{}],
        ["not-a-ref"],
        ["transferclaim_condition"] * 17,
    ],
)
def test_malformed_ref_arrays_remain_invalid_and_unchanged(invalid: object) -> None:
    document, _worker = _context()
    document["output"]["new_reasoning"][0]["right_claim_ids"] = invalid
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        _validate(document)
    assert document == before


@pytest.mark.parametrize("hash_kind", ["matching_unsorted", "wrong", "null"])
def test_supplied_hash_prevents_all_reference_normalization(hash_kind: str) -> None:
    document, _worker = _context()
    document["output"]["axes"][0]["right_claim_ids"].reverse()
    output = document["output"]
    output["result_sha256"] = (
        content_sha256(output)
        if hash_kind == "matching_unsorted"
        else sha("f")
        if hash_kind == "wrong"
        else None
    )
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        _validate(document)
    assert document == before


@pytest.mark.parametrize("collection", COLLECTIONS)
def test_direct_canonical_parser_still_rejects_unsorted_sets(collection: str) -> None:
    document, _worker = _context()
    document["output"][collection][0]["right_claim_ids"].reverse()
    output = document["output"]
    output["result_sha256"] = content_sha256(output)
    before = copy.deepcopy(output)
    with pytest.raises(ValidationError):
        PairComparisonResultV11.model_validate(output)
    with pytest.raises(ValidationError):
        parse_pair_comparison_result_v11(output)
    assert output == before


def test_absent_hash_normalization_does_not_apply_to_legacy_results() -> None:
    document, _worker = _context()
    output = document["output"]
    output["schema_version"] = "item-inference-transfer-pair-result/1.0"
    del output["axes"]
    output["new_reasoning"][0]["right_claim_ids"].reverse()
    output["result_sha256"] = content_sha256(output)
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        validate_role_result(document, "support", TRANSFER_PAIR_RESULT_SCHEMA)
    assert document == before


def test_generation_description_documents_owner_set_serialization_only() -> None:
    schema = load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)
    description = schema["$defs"]["InferenceTransferPairResultV11"]["description"]
    assert "membership, sides and object order remain unchanged" in description
    assert "Duplicate or foreign references" in description
