"""Synthetic native-use coverage; no pixels, workers, permissions or publication."""

from __future__ import annotations

import ast
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import material_native_visual_coverage as owner
from eom_catalog_contracts.material_learning import MaterialExtractionResult
from eom_catalog_contracts.material_native_visual_coverage import (
    MATERIAL_NATIVE_VISUAL_COVERAGE_REF,
    MaterialNativeVisualCoverage,
    validate_material_native_visual_coverage,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_material_learning_contracts import extraction_result
from tests.unit.test_material_native_visual_selection import _scope

ROOT = Path(__file__).resolve().parents[2]
TARGET = "extregion_" + "1" * 32
SOLUTION = "extregion_" + "2" * 32
FOREIGN = "extregion_" + "3" * 32


def case(kind="NATIVE_TABLE", *, item_number=9):
    scope = _scope().model_copy(update={"item_number": item_number})
    value = extraction_result()
    value["proposal"]["item_number"] = item_number
    value["office_bindings"] = dict(office_catalog_sha256=scope.source_catalog_sha256, bindings=[])
    disposition = dict(kind=kind, picture_use_id=scope.allowed_picture_use_ids[0])
    if kind == "IMAGE":
        value["proposal"]["content"]["body"].append(
            dict(
                type="source_image",
                block_id="block_picture",
                purpose="stimulus",
                source_region_id=TARGET,
                target_region_id=TARGET,
                alt_text="합성 도식",
            )
        )
        value["proposal"]["content_region_map"].append(
            dict(content_path="body[1]", region_ids=[TARGET])
        )
        value["office_bindings"]["bindings"] = [
            dict(
                block_id="block_picture",
                picture_use_id=disposition["picture_use_id"],
                source_region_id=TARGET,
                selection_reason="합성 본문 사용 개체 대조",
            )
        ]
        disposition.update(block_id="block_picture", source_region_id=TARGET)
    elif kind in {"NATIVE_EQUATION", "NATIVE_TABLE"}:
        block_id = "block_data"
        if kind == "NATIVE_EQUATION":
            block_id = "block_native_equation"
            value["proposal"]["content"]["body"].append(
                dict(
                    type="equation",
                    block_id=block_id,
                    purpose="stimulus",
                    notation="hancom-equation-script",
                    source="A + B = C",
                )
            )
            value["proposal"]["content_region_map"].append(
                dict(content_path="body[1]", region_ids=[TARGET])
            )
        disposition.update(
            block_id=block_id,
            source_region_ids=[TARGET],
            justification="원문 정보가 실제 해당 native block에 보존되었다는 선언",
        )
    elif kind == "NON_CONTENT":
        disposition.update(
            reason="DECORATION",
            source_region_ids=[TARGET],
            evidence="내용이 아닌 장식이라는 관찰 근거",
        )
    elif kind == "UNRESOLVED":
        value.update(status="NEEDS_DECISION", proposal=None)
        value["solution_report"].update(
            answer_state="UNDETERMINED",
            answer_labels=[],
            accepted_answers=[],
            answer_cross_check="NOT_DETERMINED",
        )
        value["conflicts"] = [
            dict(
                conflict_code="UNRESOLVED_IMAGE",
                description="원그림을 충실하게 표현할 수 없다.",
                source_region_ids=[TARGET],
                blocking=True,
            )
        ]
        disposition.update(conflict_index=0, source_region_ids=[TARGET])
    result = MaterialExtractionResult.model_validate(value)
    coverage = dict(
        schema_version="material-native-visual-coverage/1.0",
        input_sha256=result.input_sha256,
        scope_sha256=content_sha256(scope.model_dump(mode="json")),
        dispositions=[disposition],
    )
    return scope, result, coverage


def validate(scope, result, value):
    coverage = MaterialNativeVisualCoverage.model_validate(value)
    validate_material_native_visual_coverage(coverage, scope=scope, result=result)
    return coverage


@pytest.mark.parametrize(
    "kind",
    [
        "IMAGE",
        "NATIVE_EQUATION",
        "NATIVE_TABLE",
        "NON_CONTENT",
        "UNRESOLVED",
    ],
)
def test_each_closed_representation_has_actual_source_closure(kind):
    scope, result, value = case(kind)
    before = canonical_json_bytes(result.model_dump(mode="json"))
    coverage = validate(scope, result, value)
    assert len(coverage.dispositions) == 1
    assert canonical_json_bytes(result.model_dump(mode="json")) == before
    assert (
        MaterialNativeVisualCoverage.model_validate_json(
            canonical_json_bytes(coverage.model_dump(mode="json"))
        )
        == coverage
    )


def test_q22_omitted_body_picture_is_rejected_despite_empty_binding_closure():
    scope, result, value = case(item_number=22)
    assert not result.office_bindings.bindings
    value["dispositions"] = []
    with pytest.raises(ValueError, match="USE_SET_MISMATCH"):
        validate(scope, result, value)


def test_q25_actual_native_equation_does_not_require_a_duplicate_png():
    scope, result, value = case("NATIVE_EQUATION", item_number=25)
    assert not result.office_bindings.bindings
    validate(scope, result, value)


def test_empty_native_use_scope_is_valid_without_inventing_a_picture():
    scope, result, value = case()
    scope = scope.model_copy(update={"allowed_picture_use_ids": ()})
    value.update(scope_sha256=content_sha256(scope.model_dump(mode="json")), dispositions=[])
    validate(scope, result, value)


@pytest.mark.parametrize("field", ["input_sha256", "scope_sha256"])
def test_owner_supplied_input_and_whole_scope_hashes_are_exact(field):
    scope, result, value = case()
    value[field] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match=r"INPUT_MISMATCH|SCOPE_MISMATCH"):
        validate(scope, result, value)


def test_scope_hash_includes_native_document_revision_not_only_the_use_set():
    scope, result, value = case()
    question = scope.question_document.model_copy(
        update={"artifact_revision_id": "rev_" + "f" * 32}
    )
    changed = scope.model_copy(update={"question_document": question})
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        validate(changed, result, value)


@pytest.mark.parametrize("catalog", [None, "sha256:" + "f" * 64])
def test_office_catalog_must_match_exact_scope_even_when_no_image_is_selected(catalog):
    scope, result, value = case()
    result = result.model_copy(
        update={
            "office_bindings": None
            if catalog is None
            else result.office_bindings.model_copy(update={"office_catalog_sha256": catalog})
        }
    )
    with pytest.raises(ValueError, match="CATALOG_MISMATCH"):
        validate(scope, result, value)


def test_other_item_number_is_not_the_same_native_scope():
    scope, result, value = case()
    changed = result.model_copy(
        update={"proposal": result.proposal.model_copy(update={"item_number": 10})}
    )
    with pytest.raises(ValueError, match="ITEM_MISMATCH"):
        validate(scope, changed, value)


@pytest.mark.parametrize("change", ["outside", "missing", "duplicate", "duplicate-other-kind"])
def test_every_allowed_use_is_covered_once_and_only_once(change):
    scope, result, value = case()
    if change == "outside":
        value["dispositions"][0]["picture_use_id"] = "officeobj_" + "f" * 32
    elif change == "missing":
        value["dispositions"] = []
    else:
        duplicate = deepcopy(value["dispositions"][0])
        if change == "duplicate-other-kind":
            duplicate = dict(
                kind="NON_CONTENT",
                picture_use_id=duplicate["picture_use_id"],
                reason="DECORATION",
                source_region_ids=[TARGET],
                evidence="합성 관찰 근거",
            )
        value["dispositions"].append(duplicate)
    with pytest.raises(ValueError, match=r"USE_SET_MISMATCH|USE_DUPLICATE"):
        validate(scope, result, value)


@pytest.mark.parametrize(
    "change", ["unknown-block", "wrong-type", "foreign-region", "unknown-region", "wrong-map"]
)
def test_native_representations_require_real_typed_blocks_and_exact_source_maps(change):
    scope, result, value = case()
    entry = value["dispositions"][0]
    if change == "unknown-block":
        entry["block_id"] = "block_missing"
    elif change == "wrong-type":
        entry["kind"] = "NATIVE_EQUATION"
    elif change == "foreign-region":
        entry["source_region_ids"] = [SOLUTION]
    elif change == "unknown-region":
        entry["source_region_ids"] = ["extregion_" + "f" * 32]
    else:
        body = result.model_dump(mode="json")
        added = dict(body["regions"][0], region_id="extregion_" + "4" * 32)
        body["regions"].append(added)
        result = MaterialExtractionResult.model_validate(body)
        entry["source_region_ids"] = [added["region_id"]]
    with pytest.raises(ValueError, match=r"BLOCK_MISMATCH|REGION_MISMATCH"):
        validate(scope, result, value)


@pytest.mark.parametrize("change", ["unknown-block", "wrong-use", "other-region", "non-image"])
def test_image_disposition_is_an_exact_existing_block_and_binding_reference(change):
    scope, result, value = case("IMAGE")
    entry = value["dispositions"][0]
    if change == "unknown-block":
        entry["block_id"] = "block_missing"
    elif change == "wrong-use":
        changed = result.office_bindings.bindings[0].model_copy(
            update={"picture_use_id": "officeobj_" + "f" * 32}
        )
        result = result.model_copy(
            update={
                "office_bindings": result.office_bindings.model_copy(
                    update={"bindings": (changed,)}
                )
            }
        )
    elif change == "other-region":
        entry["source_region_id"] = SOLUTION
    else:
        entry["block_id"] = "block_data"
    with pytest.raises(ValueError, match="IMAGE_BINDING_MISMATCH"):
        validate(scope, result, value)


def test_non_content_claim_cannot_hide_an_actually_bound_source_image():
    scope, result, value = case("IMAGE")
    value["dispositions"] = [
        dict(
            kind="NON_CONTENT",
            picture_use_id=scope.allowed_picture_use_ids[0],
            reason="DECORATION",
            source_region_ids=[TARGET],
            evidence="합성 장식 관찰",
        )
    ]
    with pytest.raises(ValueError, match="IMAGE_BINDING_MISMATCH"):
        validate(scope, result, value)


@pytest.mark.parametrize("reason", ["DECORATION", "PAGE_FURNITURE", "EDITORIAL_MARK"])
def test_non_content_requires_a_closed_reason_and_declared_evidence_regions(reason):
    scope, result, value = case("NON_CONTENT")
    value["dispositions"][0]["reason"] = reason
    validate(scope, result, value)


@pytest.mark.parametrize("region", [SOLUTION, FOREIGN, "extregion_" + "f" * 32])
def test_non_content_cannot_cite_solution_attached_original_or_unknown_regions(region):
    scope, result, value = case("NON_CONTENT")
    value["dispositions"][0]["source_region_ids"] = [region]
    with pytest.raises(ValueError, match="REGION_MISMATCH"):
        validate(scope, result, value)


@pytest.mark.parametrize(
    "change", ["proposed", "wrong-conflict", "unrelated", "nonblocking", "wrong-code"]
)
def test_unresolved_only_points_to_relevant_existing_blocking_visual_conflict(change):
    scope, result, value = case("UNRESOLVED")
    body = result.model_dump(mode="json")
    if change == "proposed":
        _, result, _ = case()
    elif change == "wrong-conflict":
        value["dispositions"][0]["conflict_index"] = 31
    elif change == "unrelated":
        body["conflicts"][0]["source_region_ids"] = [SOLUTION]
    elif change == "nonblocking":
        body["conflicts"].append(dict(body["conflicts"][0]))
        body["conflicts"][0]["blocking"] = False
    else:
        body["conflicts"][0]["conflict_code"] = "ANSWER_DISAGREEMENT"
    if change != "proposed":
        result = MaterialExtractionResult.model_validate(body)
    with pytest.raises(ValueError, match="UNRESOLVED_INVALID"):
        validate(scope, result, value)


@pytest.mark.parametrize("kind", ["NATIVE_EQUATION", "NON_CONTENT"])
@pytest.mark.parametrize("text", ["", "  \t\n", "bad\x00text", "a" * 1501])
def test_explanation_cannot_be_blank_unsafe_or_unbounded(kind, text):
    _, _, value = case(kind)
    value["dispositions"][0]["evidence" if kind == "NON_CONTENT" else "justification"] = text
    with pytest.raises((ValidationError, SchemaError)):
        MaterialNativeVisualCoverage.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("material-native-visual-coverage-v1", value)


@pytest.mark.parametrize("kind", ["NATIVE_EQUATION", "NATIVE_TABLE"])
def test_actual_blank_native_block_is_not_a_representation(kind):
    scope, result, value = case(kind)
    body = result.model_dump(mode="json")
    if kind == "NATIVE_EQUATION":
        body["proposal"]["content"]["body"][1]["source"] = " "
    else:
        body["proposal"]["content"]["body"][0].update(headers=["", ""], rows=[["", ""]])
    result = MaterialExtractionResult.model_validate(body)
    with pytest.raises(ValueError, match="BLOCK_MISMATCH"):
        validate(scope, result, value)


def test_64_uses_can_share_one_actual_native_table_and_hash_scope_once(monkeypatch):
    scope, result, value = case()
    identifiers = tuple(f"officeobj_{index:032x}" for index in range(64))
    scope = scope.model_copy(update={"allowed_picture_use_ids": identifiers})
    value["scope_sha256"] = content_sha256(scope.model_dump(mode="json"))
    value["dispositions"] = [
        dict(value["dispositions"][0], picture_use_id=identifier) for identifier in identifiers
    ]
    original, calls = owner.content_sha256, []

    def hashed(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(owner, "content_sha256", hashed)
    coverage = validate(scope, result, value)
    assert len(coverage.dispositions) == 64 and len(calls) == 1
    value["dispositions"].append(
        dict(value["dispositions"][0], picture_use_id="officeobj_" + "f" * 32)
    )
    with pytest.raises((ValidationError, SchemaError)):
        MaterialNativeVisualCoverage.model_validate(value)


def test_schema_resource_identity_closed_fields_and_frozen_model():
    scope, result, value = case()
    coverage = validate(scope, result, value)
    schema = load_schema("material-native-visual-coverage-v1")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == MATERIAL_NATIVE_VISUAL_COVERAGE_REF
    Draft202012Validator.check_schema(schema)
    name = "material-learning/material-native-visual-coverage-v1.schema.json"
    assert (ROOT / "schemas" / name).read_bytes() == (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
    ).read_bytes()
    for bad in (dict(value, permission="ADMIN"), dict(value, block_sha256="sha256:" + "0" * 64)):
        with pytest.raises((ValidationError, SchemaError)):
            MaterialNativeVisualCoverage.model_validate(bad)
    with pytest.raises(ValidationError, match="frozen_instance"):
        coverage.scope_sha256 = "sha256:" + "f" * 64


def test_existing_work_result_and_office_binding_wire_bytes_remain_unchanged():
    expected = (
        (
            "schemas/material-learning/material-learning-extraction-work-v1.schema.json",
            "5df41437aab399a06417bdfb2c2987b7d05c8f9ec1450cf1bbdaabc92a471c53",
        ),
        (
            "schemas/material-learning/material-learning-extraction-result-v1.schema.json",
            "70ebbfde34ee6892b75f0906ec1b7b2e2938d9e021374b91cb9677fdd764d7ad",
        ),
        (
            "schemas/external-item/office-visual-bindings-v1.schema.json",
            "51d172dd763837a4e02436bfbeee31ffb0dbe697201c6699859da2b1a16021fd",
        ),
    )
    for filename, digest in expected:
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest


def test_contract_has_no_infrastructure_or_runtime_source_dependency():
    path = Path(owner.__file__)
    tree = ast.parse(path.read_bytes())
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert all(
        not name.startswith(("eom_catalog_service", "eom_orchestrator", "sqlalchemy", "subprocess"))
        for name in imports
    )
    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name in {"subprocess", "os", "pathlib"} for alias in node.names)
        for node in ast.walk(tree)
    )
    assert set(MaterialNativeVisualCoverage.model_fields) == {
        "schema_version",
        "input_sha256",
        "scope_sha256",
        "dispositions",
    }
