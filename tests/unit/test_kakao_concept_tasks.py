"""Closed task metadata/intents; neither DTOs nor synthetic scope pins grant source access."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.kakao_concept_tasks import (
    CONCEPT_TASK_REF,
    KakaoConceptCreate,
    KakaoConceptIntent,
    KakaoConceptTask,
)
from eom_catalog_contracts.kakao_source import SOURCE_RESOLUTION_REF
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_identifiers import sha256_bytes

from tests.unit.test_kakao_concept_contracts import ROOT
from tests.unit.test_kakao_concept_workflow_contracts import work_value


def command_value():
    return dict(
        schema_version="kakao-concept-create/1.0",
        source_binding_id="kakaobinding_" + "1" * 32,
        room_id="kakaoroom_" + "2" * 32,
        question_id="kakaoquestion_" + "3" * 32,
        question_revision_id="kakaoquestionrev_" + "1" * 32,
        expected_question_version=1,
        base_study_revision_id=None,
        additional_instructions="기초 개념을 먼저 확인해 주세요.",
    )


def scope_value():
    return dict(
        snapshot=dict(
            graph_snapshot_revision_id="graphrev_" + "a" * 32, sha256="sha256:" + "a" * 64
        ),
        policy=dict(access_policy_revision_id="accessrev_" + "b" * 32, sha256="sha256:" + "b" * 64),
    )


def intent_value():
    pointer = work_value()["question_manifest"]
    return dict(
        schema_version="kakao-concept-intent/1.0",
        task_id="kakaoconcepttask_" + "4" * 32,
        request=command_value(),
        question_manifest=pointer,
        scope=scope_value(),
        sources=[
            dict(
                source_revision_id="kakaosourcerev_" + "5" * 32,
                normalization_revision_id="kakaonormalizationrev_" + "6" * 32,
                manifest={**pointer, "schema_ref": SOURCE_RESOLUTION_REF},
                closure=[pointer],
            )
        ],
    )


def test_schema_and_packaged_mirror_match_and_commands_are_not_authority_claims():
    entry = CATALOG_SCHEMA_RESOURCES["kakao-concept-task-store-v1"]
    raw = (ROOT / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    command = KakaoConceptCreate.model_validate(command_value())
    assert not set(type(command).model_fields) & {
        "actor",
        "scope",
        "operator_id",
        "slot_id",
        "work_input",
        "files",
        "role",
        "session_id",
    }
    validate_contract("kakao-concept-task-store-v1", command.model_dump(mode="json"))
    intent = KakaoConceptIntent.model_validate(intent_value())
    assert intent.request == command


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator_id", "operator_" + "a" * 32),
        ("scope", scope_value()),
        ("slot_id", "06"),
        ("expected_question_version", True),
        ("additional_instructions", "x\x00y"),
        ("additional_instructions", "x" * 6001),
        ("base_study_revision_id", "latest"),
        ("question_revision_id", "current"),
    ],
)
def test_public_request_is_closed_and_bounded(field, value):
    body = command_value() | {field: value}
    with pytest.raises(ValueError):
        KakaoConceptCreate.model_validate(body)


@pytest.mark.parametrize(
    "case",
    [
        "question-schema",
        "source-schema",
        "source-media",
        "duplicate-source",
        "duplicate-closure",
        "empty-sources",
        "missing-scope",
    ],
)
def test_intent_rejects_wrong_and_duplicate_pins(case):
    value = intent_value()
    if case == "question-schema":
        value["question_manifest"]["schema_ref"] = SOURCE_RESOLUTION_REF
    elif case == "source-schema":
        value["sources"][0]["manifest"]["schema_ref"] = CONCEPT_TASK_REF
    elif case == "source-media":
        value["sources"][0]["manifest"]["media_type"] = "image/png"
    elif case == "duplicate-source":
        value["sources"].append(deepcopy(value["sources"][0]))
    elif case == "duplicate-closure":
        value["sources"][0]["closure"] *= 2
    elif case == "empty-sources":
        value["sources"] = []
    else:
        del value["scope"]
    with pytest.raises(ValueError):
        KakaoConceptIntent.model_validate(value)


@pytest.mark.parametrize("prepared", [False, True])
def test_task_state_describes_input_preparation_not_fictional_model_completion(prepared):
    intent = intent_value()
    pointer = {**intent["question_manifest"], "schema_ref": CONCEPT_TASK_REF}
    body = dict(
        schema_version="kakao-concept-task/1.0",
        task_id=intent["task_id"],
        **{
            name: intent["request"][name]
            for name in ("source_binding_id", "room_id", "question_id", "question_revision_id")
        },
        request_sha256="sha256:" + "c" * 64,
        state="PREPARED" if prepared else "RESERVED",
        intent=pointer if prepared else None,
        created_at="2026-11-17T10:00:00Z",
    )
    assert KakaoConceptTask.model_validate(body).state == body["state"]
    body["intent"] = None if prepared else pointer
    with pytest.raises(ValueError):
        KakaoConceptTask.model_validate(body)
