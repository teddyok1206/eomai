"""Actual PDF/readback and source-range proofs; no Kakao, account or NAS access."""

import json
import subprocess
import sys

import pymupdf
import pytest
from eom_kakao_archive_contracts import LocalMember, canonical_bytes, sha256
from eom_kakao_archive_contracts.study import StudyRenderManifest
from eom_kakao_archive_contracts.study_layout import (
    StudyLayoutReceipt,
    build_study_sections,
    check_study_layout,
)
from eom_kakao_archive_contracts.study_validation import (
    STUDY_LAYOUT_SCHEMA_SHA256,
    load_study_schema,
    validate_study_contract,
)
from eom_kakao_archive_worker.study_pdf import render_study

from tests.unit.test_kakao_question_render import identity, local_file, picture
from tests.unit.test_kakao_study_render_contract import ROOT, command, manifest, supplement


@pytest.fixture
def prepared(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    font = LocalMember.model_validate(
        local_file(source, "font.otf", pymupdf.Font("korea").buffer, "font/otf")
    )

    def prepare(change=None):
        value = manifest().model_dump(mode="json")
        question = value["questions"][0]
        question["student"]["images"] = []
        question["student"]["ordered_blocks"] = [
            reference
            for reference in question["student"]["ordered_blocks"]
            if reference["kind"] == "TEXT"
        ]
        if change:
            change(value)
        value = StudyRenderManifest.model_validate(value)
        raw = canonical_bytes(value.model_dump(mode="json"))
        request = command(value).model_copy(
            update={
                "manifest": LocalMember.model_validate(
                    local_file(source, "manifest.json", raw, "application/json")
                ),
                "font": font,
            }
        )
        return value, request

    return source, output, prepare


def render(prepared, change=None):
    source, output, prepare = prepared
    value, request = prepare(change)
    result = render_study(
        request,
        input_root=source,
        output_root=output,
        renderer_release_sha256=request.renderer_release_sha256,
    )
    return value, request, result


def add_role_photos(value, source, *, shared=False):
    question = value["questions"][0]
    student_photo = picture(source, 1)
    staff_photo = dict(student_photo, attachment_occurrence_id=identity("attachment", 2))
    if not shared:
        staff_photo = picture(source, 2, size=(600, 400))
    for role, photo in (("student", student_photo), ("staff", staff_photo)):
        content = question[role]
        occurrence = content["text_blocks"][0]["source_occurrence_id"]
        content["images"].append(dict(source_occurrence_id=occurrence, value=photo))
        # Deliberately source text first: printed profile puts the sender's photos first.
        content["ordered_blocks"].append(
            dict(kind="IMAGE", attachment_occurrence_id=photo["attachment_occurrence_id"])
        )


def test_layout_schema_mirror_and_hash_are_pinned():
    path = ROOT / "schemas/kakao-archive/worker-study-layout-v1.schema.json"
    raw = path.read_bytes()
    assert sha256(raw) == STUDY_LAYOUT_SCHEMA_SHA256
    assert (
        raw
        == (
            ROOT
            / "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas"
            / path.name
        ).read_bytes()
    )
    assert load_study_schema(layout=True)["$id"].endswith("worker-study-layout/1.0")


def test_real_question_reply_and_record_information(prepared):
    value, request, result = render(prepared)
    assert result.status == "COMPLETED" and result.page_count == 2
    receipt = StudyLayoutReceipt.model_validate_json((prepared[1] / "layout.json").read_bytes())
    assert [page.section for page in receipt.pages] == ["STUDENT", "STAFF"]
    check_study_layout(request, value, receipt)
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        assert "답변" not in pdf[0].get_text()
        assert "답변" in pdf[1].get_text()
        assert "기록" in pdf[1].get_text()
        assert "2026" in pdf[1].get_text()
        assert not pdf[0].get_image_info() and not pdf[1].get_image_info()
    for output in result.outputs:
        assert sha256((prepared[1] / output.relative_path).read_bytes()) == output.sha256


def test_student_and_staff_photos_on_separate_pages_are_not_cropped(prepared):
    value, request, result = render(prepared, lambda v: add_role_photos(v, prepared[0]))
    assert result.status == "COMPLETED" and result.page_count >= 2
    receipt = StudyLayoutReceipt.model_validate_json((prepared[1] / "layout.json").read_bytes())
    expected = [identity("attachment", 1), identity("attachment", 2)]
    assert [
        image.attachment_occurrence_id for p in receipt.pages for image in p.layout.image_blocks
    ] == expected
    assert all(image.crop is None for p in receipt.pages for image in p.layout.image_blocks)
    check_study_layout(request, value, receipt)
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        assert len(pdf[0].get_image_info()) == 1
        assert len(pdf[1].get_image_info()) == 1


def test_repeated_member_is_decoded_once_but_each_use_is_preserved(prepared, monkeypatch):
    import eom_kakao_archive_worker.question_pdf as engine

    original = engine._image_bytes
    calls = []

    def decode(*args):
        calls.append(args[1].attachment_occurrence_id)
        return original(*args)

    monkeypatch.setattr(engine, "_image_bytes", decode)
    _, _, result = render(prepared, lambda v: add_role_photos(v, prepared[0], shared=True))
    assert result.status == "COMPLETED" and len(calls) == 1
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        assert pdf[0].get_images()[0][0] == pdf[1].get_images()[0][0]


def test_shared_member_cache_never_bypasses_staff_photo_quality_check(prepared):
    def change(value):
        add_role_photos(value, prepared[0], shared=True)
        value["questions"][0]["staff"]["images"][0]["value"]["quality_accepted"] = False

    _, _, result = render(prepared, change)
    assert result.status == "NEEDS_LAYOUT_REVIEW"
    assert result.error_code == "IMAGE_QUALITY_REVIEW_REQUIRED"
    assert not result.outputs and not list(prepared[1].iterdir())


def test_no_staff_does_not_create_empty_reply_or_invent_photos(prepared):
    def change(value):
        question = value["questions"][0]
        question["staff"] = None
        question["messages"] = [m for m in question["messages"] if m["role"] == "student"]

    _, _, result = render(prepared, change)
    assert result.status == "COMPLETED" and result.page_count == 1
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        assert "기록" in pdf[0].get_text()
        assert "조교" not in pdf[0].get_text()


@pytest.mark.parametrize("ending", ["\n", "\r\n", " e\u0301\n"])
def test_long_reply_flows_without_missing_or_duplicated_codepoints(prepared, ending):
    text = ("답변의 원문 보존과 연속 구간 확인" + ending) * 150

    def change(value):
        value["questions"][0]["staff"]["text_blocks"][0]["value"]["text"] = text

    value, request, result = render(prepared, change)
    assert result.status == "COMPLETED" and result.page_count > 3
    receipt = StudyLayoutReceipt.model_validate_json((prepared[1] / "layout.json").read_bytes())
    check_study_layout(request, value, receipt)
    span = value.questions[0].staff.text_blocks[0].value.span_id
    slices = [s for p in receipt.pages for s in p.spans if s.span_id == span]
    end = 0
    for fragment in slices:
        assert fragment.start_codepoint == end
        end = fragment.end_codepoint
    assert end == len(text)
    assert all(p.layout.font_size_pt == 11 for p in receipt.pages if p.section == "STAFF")


def test_supplement_is_after_reply_and_carries_title_origin_and_citation(prepared):
    def change(value):
        value["study_revision_id"] = identity("studyrev")
        value["questions"][0]["supplements"] = [
            supplement()
            | {
                "origin": "SOURCE_EXCERPT",
                "citations": [
                    dict(
                        evidence_id="evidence-1",
                        source_title="검증용 교재",
                        page_label="15쪽",
                        source_sha256=sha256(b"source"),
                    )
                ],
            }
        ]

    value, request, result = render(prepared, change)
    assert result.status == "COMPLETED" and result.page_count == 3
    receipt = StudyLayoutReceipt.model_validate_json((prepared[1] / "layout.json").read_bytes())
    check_study_layout(request, value, receipt)
    assert [p.section for p in receipt.pages] == ["STUDENT", "STAFF", "SUPPLEMENT"]
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        text = pdf[2].get_text().replace("\u00a0", " ")
        assert "교재 원문 자료" in text and "15쪽" in text and "보충 설명" in text


def test_unknown_time_is_preserved_in_draft_not_replaced_with_today(prepared):
    def change(value):
        value["mode"] = "DRAFT"
        value["questions"][0]["header_date"] = None
        for message in value["questions"][0]["messages"]:
            message.update(source_timezone="unknown", sent_at_utc=None)

    _, _, result = render(prepared, change)
    assert result.status == "COMPLETED"
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        assert "날짜 확인 필요" in pdf[0].get_text().replace("\u00a0", " ")
        assert "미확정" in pdf[1].get_text()


@pytest.mark.parametrize("mode", ["DRAFT", "FINAL"])
def test_missing_photo_is_explicit_or_requires_review(prepared, mode):
    def change(value):
        value["mode"] = mode
        add_role_photos(value, prepared[0])
        value["questions"][0]["student"]["images"][0]["value"].update(
            availability="MISSING", member=None, quality_accepted=False
        )

    _, _, result = render(prepared, change)
    if mode == "FINAL":
        assert result.status == "NEEDS_LAYOUT_REVIEW"
        assert result.error_code == "REQUIRED_IMAGE_UNAVAILABLE"
        assert not result.outputs and not list(prepared[1].iterdir())
    else:
        assert result.status == "COMPLETED"
        with pymupdf.open(prepared[1] / "report.pdf") as pdf:
            assert "미확보" in pdf[0].get_text()


@pytest.mark.parametrize("case", ["question-overflow", "glyph", "wide-photo"])
def test_unreadable_source_is_never_silently_cut(prepared, case):
    def change(value):
        question = value["questions"][0]
        if case == "question-overflow":
            question["student"]["text_blocks"][0]["value"]["text"] = "긴 질문\n" * 1000
        elif case == "glyph":
            question["staff"]["text_blocks"][0]["value"]["text"] = "\U0010ffff"
        else:
            add_role_photos(value, prepared[0])
            photo = picture(prepared[0], 3, size=(2000, 10))
            question["staff"]["images"][0]["value"] = photo
            question["staff"]["ordered_blocks"][-1]["attachment_occurrence_id"] = photo[
                "attachment_occurrence_id"
            ]

    _, _, result = render(prepared, change)
    assert result.status == "NEEDS_LAYOUT_REVIEW" and not result.outputs
    assert not list(prepared[1].iterdir())


@pytest.mark.parametrize("case", ["gap", "repeat", "drop", "order", "pin", "font"])
def test_core_rejects_forged_layout_coverage(prepared, case):
    value, request, result = render(prepared)
    assert result.status == "COMPLETED"
    raw = json.loads((prepared[1] / "layout.json").read_bytes())
    if case == "gap":
        raw["pages"][0]["spans"][0]["start_codepoint"] = 1
    elif case == "repeat":
        raw["pages"].append(raw["pages"][-1])
    elif case == "drop":
        raw["pages"].pop()
    elif case == "order":
        raw["pages"].reverse()
    elif case == "pin":
        raw["packet_revision_id"] = identity("packetrev", 999)
    else:
        raw["pages"][1]["layout"]["font_size_pt"] = 10.0
    with pytest.raises(ValueError, match="KAKAO_"):
        check_study_layout(request, value, StudyLayoutReceipt.model_validate(raw))


def test_complete_study_command_uses_existing_cli_without_new_runtime_authority(prepared):
    _, request = prepared[2]()
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "eom_kakao_archive_worker.cli",
            "--input-root",
            str(prepared[0]),
            "--output-root",
            str(prepared[1]),
            "--renderer-release-sha256",
            request.renderer_release_sha256,
        ],
        input=canonical_bytes(request.model_dump(mode="json")),
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    validate_study_contract("result", result)
    assert result["status"] == "COMPLETED" and result["page_count"] == 2


@pytest.mark.parametrize("case", ["release", "hash", "output-exists", "overlap"])
def test_untrusted_handoff_never_writes_or_overwrites_output(prepared, case):
    source, output, prepare = prepared
    _, request = prepare()
    release = request.renderer_release_sha256
    if case == "release":
        release = sha256(b"other release")
    elif case == "hash":
        (source / "manifest.json").write_bytes(b"wrong input")
    elif case == "output-exists":
        (output / "keep.txt").write_text("existing file")
    else:
        output = source
    result = render_study(
        request, input_root=source, output_root=output, renderer_release_sha256=release
    )
    assert result.status == "INVALID_INPUT" and not result.outputs
    assert not (output / "report.pdf").exists()
    if case == "output-exists":
        assert (output / "keep.txt").read_text() == "existing file"


def test_page_budget_exhaustion_stops_before_pdf_generation(prepared, monkeypatch):
    import eom_kakao_archive_worker.study_pages as pages

    calls = []
    original = pages._flow_section

    def exhaust(*args, **kwargs):
        calls.append(1)
        return original(*args, **(kwargs | {"page_budget": 0}))

    monkeypatch.setattr(pages, "_flow_section", exhaust)
    _, _, result = render(prepared)
    assert calls and result.status == "NEEDS_LAYOUT_REVIEW"
    assert not result.outputs and not list(prepared[1].iterdir())


def test_section_projection_is_deterministic_and_preserves_original_question_ids():
    value = manifest()
    assert build_study_sections(value) == build_study_sections(value)
    assert {s.question_revision_id for s in build_study_sections(value)} == {
        value.questions[0].question_revision_id
    }


def test_inconsistent_source_array_and_authored_order_cannot_reach_renderer():
    raw = manifest().model_dump(mode="json")
    content = raw["questions"][0]["student"]
    content["ordered_blocks"] = list(reversed(content["ordered_blocks"]))
    with pytest.raises(ValueError, match="BLOCK_ORDER_INVALID"):
        StudyRenderManifest.model_validate(raw)
