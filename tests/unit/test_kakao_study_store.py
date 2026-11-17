"""Closed saved-study requests, immutable source pins and local packaged schemas."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_packet_store import PACKET_REF
from eom_catalog_contracts.kakao_study_store import (
    STUDY_REF,
    KakaoStoredStudy,
    KakaoStudyBlockEdit,
    KakaoStudyCreate,
    KakaoStudyManifest,
    KakaoStudyMutation,
    KakaoStudyPage,
    KakaoStudyQuestion,
    KakaoStudyQuestionEdit,
    KakaoStudyRevise,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_identifiers import canonical_json_bytes, sha256_bytes

ROOT = Path(__file__).resolve().parents[2]


def identity(prefix, index=1):
    return prefix + "_" + f"{index:032x}"


def pointer(schema=PACKET_REF, member="packet.json"):
    return dict(
        artifact_id=identity("artifact"),
        artifact_revision_id=identity("rev"),
        schema_ref=schema,
        media_type="application/json",
        member_path=member,
        sha256="sha256:" + "a" * 64,
    )


def command():
    return KakaoStudyCreate(
        source_binding_id=identity("kakaobinding"),
        packet_id=identity("kakaopacket"),
        packet_revision_id=identity("kakaopacketrev"),
        student_id=identity("kakaostudent"),
        title="질문과 관련 개념",
        questions=(
            KakaoStudyQuestionEdit(
                question_revision_id=identity("kakaoquestionrev"),
                concept_task_id=None,
                blocks=(),
                notes=(dict(title="직접 작성한 메모", text="선택한 질문을 위한 설명입니다."),),
            ),
        ),
    )


def manifest():
    c = command()
    return KakaoStudyManifest(
        **c.model_dump(exclude={"schema_version", "questions"}),
        study_id=identity("kakaostudy"),
        study_revision_id=identity("kakaostudyrev"),
        previous_revision_id=None,
        resource_version=1,
        packet_manifest=pointer(),
        subset_sha256="sha256:" + "b" * 64,
        questions=(KakaoStudyQuestion(edit=c.questions[0], result=None),),
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
        created_by=identity("operator"),
    )


def stored():
    value = manifest()
    return KakaoStoredStudy(
        **value.model_dump(
            exclude={
                "schema_version",
                "questions",
                "created_by",
                "packet_manifest",
                "subset_sha256",
            }
        ),
        question_count=1,
        manifest=pointer(STUDY_REF, "study.json"),
    )


def test_schema_mirror_hash_and_all_saved_shapes_roundtrip():
    raw = (ROOT / "schemas/kakao-archive/study-store-v1.schema.json").read_bytes()
    assert (
        raw
        == (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/kakao-archive"
            / "study-store-v1.schema.json"
        ).read_bytes()
    )
    assert sha256_bytes(raw) == CATALOG_SCHEMA_RESOURCES["kakao-study-store-v1"].sha256
    c = command()
    revise = KakaoStudyRevise(
        **c.model_dump(exclude={"schema_version"}),
        study_id=identity("kakaostudy"),
        parent_revision_id=identity("kakaostudyrev"),
        expected_resource_version=1,
    )
    values = (
        c,
        revise,
        manifest(),
        stored(),
        KakaoStudyMutation(study=stored(), replayed=True),
        KakaoStudyPage(items=(stored(),), next_cursor=None),
    )
    for value in values:
        validate_contract("kakao-study-store-v1", value.model_dump(mode="json"))
        assert type(value).model_validate_json(canonical_json_bytes(value)) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator_id", identity("operator")),
        ("slot", "05"),
        ("scope", {}),
        ("path", "/mnt/nas/private"),
        ("latest", True),
    ],
)
def test_caller_cannot_supply_authority_source_path_or_latest(field, value):
    with pytest.raises(ValueError):
        KakaoStudyCreate.model_validate(command().model_dump(mode="json") | {field: value})


@pytest.mark.parametrize(
    "change",
    [
        "duplicate-question",
        "block-without-task",
        "duplicate-block",
        "duplicate-capture",
        "invalid-block",
        "whitespace-title",
    ],
)
def test_invalid_edits_and_duplicate_selections_are_rejected(change):
    c = command().model_dump(mode="json")
    q = c["questions"][0]
    if change == "duplicate-question":
        c["questions"].append(deepcopy(q))
    elif change == "whitespace-title":
        c["title"] = "  "
    else:
        b = KakaoStudyBlockEdit(block_index=0).model_dump(mode="json")
        q["blocks"] = [b]
        if change != "block-without-task":
            q["concept_task_id"] = identity("kakaoconcepttask")
        if change == "duplicate-block":
            q["blocks"].append(deepcopy(b))
        elif change == "duplicate-capture":
            b["capture_indices"] = [0, 0]
        elif change == "invalid-block":
            b["block_index"] = True
    with pytest.raises(ValueError):
        KakaoStudyCreate.model_validate(c)


@pytest.mark.parametrize("change", ["parent", "pointer", "source-result"])
def test_exact_manifest_and_source_results_cannot_be_faked(change):
    value = manifest().model_dump(mode="json")
    if change == "parent":
        value["resource_version"] = 2
    elif change == "pointer":
        value["packet_manifest"]["schema_ref"] = STUDY_REF
    else:
        value["questions"][0]["edit"]["concept_task_id"] = identity("kakaoconcepttask")
    with pytest.raises(ValueError):
        KakaoStudyManifest.model_validate(value)


def test_validation_errors_do_not_print_private_note_contents():
    value = manifest().model_dump(mode="json")
    private = "PRIVATE_STUDENT_NOTE_" + "z" * 200
    value["questions"][0]["edit"]["notes"][0]["text"] = private
    value["packet_manifest"]["schema_ref"] = STUDY_REF
    with pytest.raises(ValueError) as error:
        KakaoStudyManifest.model_validate(value)
    assert private not in str(error.value)
    assert "KAKAO_STUDY_CONTRACT_INVALID" in str(error.value)
