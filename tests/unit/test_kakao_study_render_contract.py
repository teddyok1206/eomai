"""Closed successor contracts; predecessor bytes and source permissions stay separate."""

import json
from pathlib import Path

import pytest
from eom_catalog_service.kakao_study_projection import project_kakao_student_study
from eom_kakao_archive_contracts import (
    LocalMember,
    RenderCommand,
    RenderResult,
    canonical_bytes,
    sha256,
)
from eom_kakao_archive_contracts.study import (
    StudyQuestion,
    StudyRenderCommand,
    StudyRenderManifest,
    StudyRenderResult,
    StudySupplement,
    study_input_members,
)
from eom_kakao_archive_contracts.study_validation import (
    STUDY_SCHEMA_SHA256,
    load_study_schema,
    validate_study_contract,
)
from eom_kakao_archive_contracts.validation import SCHEMA_SHA256, load_schema, validate_contract

from tests.unit.test_kakao_question_editing import identity
from tests.unit.test_kakao_render_projection import prepare
from tests.unit.test_kakao_study_projection import two_photo_inputs

ROOT = Path(__file__).resolve().parents[2]


def manifest():
    return project_kakao_student_study(**prepare(photo=True, replies=True))


def command(value):
    raw = canonical_bytes(value.model_dump(mode="json"))
    return StudyRenderCommand(
        execution=dict(
            command_id=identity("kakaocommand", 1),
            task_id=identity("kakaotask", 1),
            attempt_id=identity("kakaoattempt", 1),
            attempt_number=1,
            fence=1,
        ),
        schema_version="kakao-study-render/1.0",
        export_id=identity("kakaoexport", 1),
        source_binding_id=value.source_binding_id,
        packet_revision_id=value.packet_revision_id,
        study_revision_id=value.study_revision_id,
        student_id=value.student_id,
        subset_sha256=value.subset_sha256,
        mode=value.mode,
        renderer_release_sha256=sha256(b"release"),
        layout_policy="student-study-a4/1.0",
        manifest=LocalMember(
            relative_path="manifest.json",
            sha256=sha256(raw),
            size_bytes=len(raw),
            media_type="application/json",
        ),
        font=LocalMember(
            relative_path="font.otf", sha256=sha256(b"font"), size_bytes=4, media_type="font/otf"
        ),
    )


def supplement():
    return dict(
        supplement_id="concept-1",
        title="보충 설명",
        origin="USER_NOTE",
        text_blocks=[dict(span_id="note-1", text="사용자가 작성한 설명입니다.")],
        images=[],
        ordered_blocks=[dict(kind="TEXT", span_id="note-1")],
        citations=[],
    )


def test_canonical_schema_and_wheel_resource_are_identical_and_predecessor_unchanged():
    path = ROOT / "schemas/kakao-archive/worker-study-render-v1.schema.json"
    raw = path.read_bytes()
    assert sha256(raw) == STUDY_SCHEMA_SHA256
    assert (
        raw
        == (
            ROOT
            / "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas"
            / path.name
        ).read_bytes()
    )
    assert (
        sha256((ROOT / "schemas/kakao-archive/worker-question-render-v1.schema.json").read_bytes())
        == SCHEMA_SHA256
    )
    assert load_study_schema()["$id"] != load_schema()["$id"]
    value = manifest()
    for kind, model in (("manifest", value), ("command", command(value))):
        validate_study_contract(kind, model.model_dump(mode="json"))
        with pytest.raises(ValueError, match="SCHEMA_INVALID"):
            validate_contract(kind, model.model_dump(mode="json"))
    assert StudyRenderManifest.model_validate_json(value.model_dump_json()) == value
    assert canonical_bytes(value.model_dump(mode="json")) == canonical_bytes(
        manifest().model_dump(mode="json")
    )


def test_no_arbitrary_authority_paths_or_unknown_fields():
    for field, unknown in (
        ("permissions", ["ADMIN"]),
        ("path", "/mnt/nas/private"),
        ("latest", True),
    ):
        with pytest.raises(ValueError):
            StudyRenderManifest.model_validate(
                manifest().model_dump(mode="json") | {field: unknown}
            )


@pytest.mark.parametrize(
    "change",
    [
        {"messages": []},
        {"header_date": "2026-11-17"},
    ],
)
def test_missing_metadata_and_invented_dates_are_rejected(change):
    value = manifest().questions[0].model_dump(mode="json")
    with pytest.raises(ValueError):
        StudyQuestion.model_validate(value | change)


def test_role_and_occurrence_membership_are_exact():
    value = manifest().questions[0].model_dump(mode="json")
    value["messages"][0]["role"] = "staff"
    with pytest.raises(ValueError, match="MESSAGE_SET_MISMATCH"):
        StudyQuestion.model_validate(value)
    value = manifest().questions[0].model_dump(mode="json")
    value["messages"].append(value["messages"][0])
    with pytest.raises(ValueError, match="MESSAGE_SET_MISMATCH"):
        StudyQuestion.model_validate(value)
    value = manifest().questions[0].model_dump(mode="json")
    value["staff"]["text_blocks"][0]["source_occurrence_id"] = value["student"]["text_blocks"][0][
        "source_occurrence_id"
    ]
    with pytest.raises(ValueError, match="ROLE_MISMATCH"):
        StudyQuestion.model_validate(value)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("raw_date", "2026-11-17 01:02:03"),
        ("sent_at_utc", "2026-10-31T23:59:01+09:00"),
        ("sent_at_utc", None),
        ("source_timezone", "unknown"),
    ],
)
def test_raw_time_and_verified_utc_cannot_disagree(field, bad):
    value = manifest().model_dump(mode="json")
    value["questions"][0]["messages"][0][field] = bad
    with pytest.raises(ValueError, match=r"KAKAO_STUDY_RENDER_(TIME|RAW_DATE)"):
        StudyRenderManifest.model_validate(value)


def test_source_excerpt_requires_citation_and_supplements_require_saved_revision():
    value = supplement() | {"origin": "SOURCE_EXCERPT"}
    with pytest.raises(ValueError, match="CITATION_REQUIRED"):
        StudySupplement.model_validate(value)
    value = manifest().model_dump(mode="json")
    value["questions"][0]["supplements"] = [supplement()]
    with pytest.raises(ValueError, match="STUDY_REVISION_REQUIRED"):
        StudyRenderManifest.model_validate(value)
    with pytest.raises(ValueError, match="SCHEMA_INVALID"):
        validate_study_contract("manifest", value)
    value["study_revision_id"] = identity("kakaostudyrev", 1)
    assert (
        StudyRenderManifest.model_validate(value).questions[0].supplements[0].origin == "USER_NOTE"
    )


def test_duplicate_supplement_and_citation_are_not_silently_deduplicated():
    value = manifest().model_dump(mode="json")
    value["questions"][0]["supplements"] = [supplement(), supplement()]
    with pytest.raises(ValueError, match="SUPPLEMENT_DUPLICATED"):
        StudyRenderManifest.model_validate(value)
    value = supplement()
    citation = dict(
        evidence_id="evidence-1",
        source_title="검증용 교재",
        page_label="10쪽",
        source_sha256=sha256(b"source"),
    )
    value["citations"] = [citation, citation]
    with pytest.raises(ValueError, match="CITATION_DUPLICATED"):
        StudySupplement.model_validate(value)


def test_command_pin_mismatch_never_uses_latest_manifest():
    value = manifest()
    altered = command(value).model_copy(
        update={"packet_revision_id": identity("kakaopacketrev", 999)}
    )
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        study_input_members(altered, value)
    with pytest.raises(ValueError):
        RenderCommand.model_validate(command(value).model_dump(mode="json"))


def test_shared_binary_keeps_independent_photo_uses_but_materializes_member_once():
    value = project_kakao_student_study(**two_photo_inputs(shared_member=True))
    members = study_input_members(command(value), value)
    assert [member.relative_path for member in members] == [
        "manifest.json",
        "font.otf",
        "shared.png",
    ]
    assert (
        value.questions[0].student.images[0].value.attachment_occurrence_id
        != value.questions[0].staff.images[0].value.attachment_occurrence_id
    )


def test_conflicting_local_member_path_is_explicit():
    value = manifest().model_dump(mode="json")
    value["questions"][0]["student"]["images"][0]["value"]["member"]["relative_path"] = "font.otf"
    value = StudyRenderManifest.model_validate(value)
    with pytest.raises(ValueError, match="MEMBER_COLLISION"):
        study_input_members(command(value), value)


def test_result_family_is_explicit_and_failure_has_no_success_outputs():
    request = command(manifest())
    value = dict(
        execution=request.execution,
        schema_version="kakao-study-render-result/1.0",
        export_id=request.export_id,
        command_sha256=sha256(b"command"),
        manifest_sha256=request.manifest.sha256,
        status="INVALID_INPUT",
        page_count=0,
        outputs=(),
        error_code="INVALID_INPUT",
        question_revision_id=None,
    )
    result = StudyRenderResult(**value)
    with pytest.raises(ValueError):
        RenderResult.model_validate(result.model_dump(mode="json"))
    with pytest.raises(ValueError, match="FAILED_OUTPUT_INVALID"):
        StudyRenderResult.model_validate(result.model_dump(mode="json") | {"page_count": 1})


def test_loading_schemas_never_mutates_or_fetches_network(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("NETWORK_SCHEMA_LOOKUP")

    monkeypatch.setattr(socket, "create_connection", denied)
    before = json.dumps(load_schema(), sort_keys=True)
    validate_study_contract("manifest", manifest().model_dump(mode="json"))
    assert json.dumps(load_schema(), sort_keys=True) == before
