"""Composition receipts carry exact small pointers, never client source text or authority."""

from datetime import timedelta
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_question_composition_result import KakaoQuestionCompositionResult
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_question_composition_models import (
    KakaoQuestionCompositionInputRecord,
    KakaoQuestionCompositionOutputRecord,
    KakaoQuestionCompositionRecord,
)
from eom_catalog_service.kakao_question_service import KakaoQuestionService  # noqa: F401
from eom_identifiers import canonical_json_bytes, sha256_bytes
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from tests.unit.test_kakao_question_editing import identity, student
from tests.unit.test_kakao_question_store_contracts import stored_payload


def payload():
    outputs = [
        stored_payload()
        | dict(
            question_id=identity("kakaoquestion", number),
            question_revision_id=identity("kakaoquestionrev", number),
            student=student(),
        )
        for number in (2, 3)
    ]
    return dict(
        composition_id=identity("kakaocomposition", 1),
        operation="SPLIT",
        source_binding_id=outputs[0]["source_binding_id"],
        room_id=outputs[0]["room_id"],
        inputs=[
            dict(
                question_id=identity("kakaoquestion", 1),
                question_revision_id=identity("kakaoquestionrev", 1),
                resource_version=1,
            )
        ],
        outputs=outputs,
        replayed=False,
    )


def test_result_schema_pins_bytes_and_roundtrips_split_and_merge():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["kakao-question-composition-result-v1"]
    raw = (root / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    value = payload()
    split = KakaoQuestionCompositionResult.model_validate(value)
    merge = KakaoQuestionCompositionResult.model_validate(
        value
        | dict(
            operation="MERGE",
            inputs=[
                dict(
                    question_id=identity("kakaoquestion", number),
                    question_revision_id=identity("kakaoquestionrev", number),
                    resource_version=1,
                )
                for number in (4, 5)
            ],
            outputs=value["outputs"][:1],
        )
    )
    for result in (split, merge):
        wire = result.model_dump(mode="json")
        validate_contract("kakao-question-composition-result-v1", wire)
        assert (
            KakaoQuestionCompositionResult.model_validate_json(canonical_json_bytes(wire)) == result
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("question_id", identity("kakaoquestion", 1)),
        ("question_id", identity("kakaoquestion", 2)),
        ("question_revision_id", identity("kakaoquestionrev", 2)),
        ("source_binding_id", identity("kakaobinding", 9)),
        ("room_id", identity("kakaoroom", 9)),
        ("student", None),
        ("student", student(2)),
        ("student", student(mapping=2)),
        ("review_state", "CONFIRMED"),
        ("previous_revision_id", identity("kakaoquestionrev", 7)),
        ("resource_version", 2),
    ],
)
def test_result_rejects_output_identity_scope_student_or_lifecycle_mismatch(field, value):
    body = payload()
    body["outputs"][1][field] = value
    with pytest.raises(ValueError):
        KakaoQuestionCompositionResult.model_validate(body)


@pytest.mark.parametrize(
    "fault",
    [
        "empty_inputs",
        "empty_outputs",
        "one_split_output",
        "one_merge_input",
        "duplicate_inputs",
        "coerced_replay",
        "created_at",
        "owner",
        "text",
    ],
)
def test_result_rejects_wrong_shape_and_extra_payload(fault):
    body = payload()
    if fault == "empty_inputs":
        body["inputs"] = []
    elif fault == "empty_outputs":
        body["outputs"] = []
    elif fault == "one_split_output":
        body["outputs"] = body["outputs"][:1]
    elif fault == "one_merge_input":
        body.update(operation="MERGE", outputs=body["outputs"][:1])
    elif fault == "duplicate_inputs":
        body.update(operation="MERGE", inputs=body["inputs"] * 2, outputs=body["outputs"][:1])
    elif fault == "coerced_replay":
        body["replayed"] = 1
    elif fault == "created_at":
        body["outputs"][1]["created_at"] += timedelta(seconds=1)
    elif fault == "owner":
        body["owner_operator_id"] = identity("operator", 1)
    else:
        body["source_text"] = "not part of an adoption receipt"
    with pytest.raises(ValueError):
        KakaoQuestionCompositionResult.model_validate(body)


def test_composition_tables_keep_only_small_metadata_and_indexed_membership():
    for model in (
        KakaoQuestionCompositionRecord,
        KakaoQuestionCompositionInputRecord,
        KakaoQuestionCompositionOutputRecord,
    ):
        assert all(
            isinstance(column.type, (String, Integer, DateTime))
            for column in model.__table__.columns
        )
        sql = str(CreateTable(model.__table__).compile(dialect=dialect()))
        assert "JSON" not in sql and "BYTEA" not in sql
    for model in (KakaoQuestionCompositionInputRecord, KakaoQuestionCompositionOutputRecord):
        assert tuple(c.name for c in model.__table__.primary_key.columns) == (
            "composition_id",
            "ordinal",
        )
