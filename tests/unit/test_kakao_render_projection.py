"""Exact private question→student subset→local PDF boundary with anonymous fixtures."""

from dataclasses import replace
from datetime import date

import pymupdf
import pytest
from eom_catalog_contracts.kakao_question import KakaoImageTransform
from eom_catalog_service.kakao_question_editing import KakaoAttachmentSource
from eom_catalog_service.kakao_render_projection import (
    KakaoRenderImageInput,
    project_kakao_student_render,
)
from eom_kakao_archive_contracts import LocalMember, RenderCommand, canonical_bytes, subset_sha256
from eom_kakao_archive_worker.question_pdf import render_questions

from tests.unit.test_kakao_question_editing import (
    confirmed,
    identity,
    image,
    packet,
    pointer,
    published,
    question,
    source,
    student,
)
from tests.unit.test_kakao_question_render import RELEASE, local_file


def prepare(*, photo=False, replies=False, association="SOURCE_VERIFIED"):
    resolved = source(attachments={1: (image(association=association),)} if photo else None)
    selected = confirmed(question(resolved), (resolved,))
    materialized = tuple(
        KakaoRenderImageInput(
            value.pointer,
            LocalMember(
                relative_path=f"image-{position}.png",
                sha256=value.pointer.sha256,
                size_bytes=len(b"fixture-pixels"),
                media_type="image/png",
            ),
        )
        for position, value in enumerate(resolved.attachments.values(), 1)
    )
    return dict(
        packet=packet((selected,), include_replies=replies),
        student_id=student().student_id,
        questions=(published(selected),),
        sources=(resolved,),
        images=materialized,
    )


@pytest.mark.parametrize("replies", [False, True])
def test_original_text_image_interleaving_and_reply_policy_preserved(replies):
    args = prepare(photo=True, replies=replies)
    result = project_kakao_student_render(**args)
    rendered = result.questions[0]
    assert [ref.kind for ref in rendered.ordered_blocks] == ["TEXT", "IMAGE", "TEXT"] + (
        ["TEXT"] if replies else []
    )
    assert rendered.header_date == date(2026, 10, 31)
    assert rendered.text_blocks[0].text == "첫 질문"
    assert [block.text for block in rendered.text_blocks] == ["첫 질문", "추가 질문"] + (
        ["답변\n답변"] if replies else []
    )
    assert rendered.images[0].member == args["images"][0].member
    assert result.subset_sha256 == subset_sha256(
        tuple(value.question_revision_id for value in args["packet"].questions)
    )
    assert result == project_kakao_student_render(**args)


def test_only_the_requested_student_exact_subset_is_materialized():
    first_source, second_source = source(number=1), source(number=2)
    first = confirmed(question(first_source, number=1), (first_source,), number=11)
    second = confirmed(
        question(second_source, number=2, mapping=student(2)), (second_source,), number=22
    )
    bundle = packet((first, second))
    result = project_kakao_student_render(
        packet=bundle,
        student_id=student(2).student_id,
        questions=(published(second),),
        sources=(second_source,),
        images=(),
    )
    assert result.student_id == student(2).student_id
    assert tuple(value.question_revision_id for value in result.questions) == (
        second.question_revision_id,
    )
    with pytest.raises(ValueError, match="QUESTION_SET_MISMATCH"):
        project_kakao_student_render(
            packet=bundle,
            student_id=student(2).student_id,
            questions=(published(first), published(second)),
            sources=(first_source, second_source),
            images=(),
        )


@pytest.mark.parametrize("field", ["questions", "sources", "images"])
def test_missing_pinned_input_is_not_resolved_to_latest(field):
    args = prepare(photo=True)
    args[field] = ()
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_RENDER_"):
        project_kakao_student_render(**args)


def test_extra_or_duplicate_local_image_inputs_rejected():
    args = prepare(photo=True)
    args["images"] = args["images"] * 2
    with pytest.raises(ValueError, match="IMAGE_DUPLICATED"):
        project_kakao_student_render(**args)
    args = prepare(photo=True)
    args["images"] += (
        replace(
            args["images"][0],
            pointer=pointer(
                "eom://schemas/kakao-archive/media/1.0", b"fixture-pixels", 999, "image/png"
            ),
        ),
    )
    with pytest.raises(ValueError, match="IMAGE_SET_MISMATCH"):
        project_kakao_student_render(**args)


def test_packet_cannot_relabel_another_bindings_question_subset():
    args = prepare()
    args["packet"] = args["packet"].model_copy(
        update={"source_binding_id": identity("kakaobinding", 999)}
    )
    with pytest.raises(ValueError, match="QUESTION_PIN_MISMATCH"):
        project_kakao_student_render(**args)


def test_manual_attachment_confirmation_keeps_quality_acceptance():
    result = project_kakao_student_render(**prepare(photo=True, association="MANUAL_CONFIRMED"))
    assert result.questions[0].images[0].quality_accepted is True


def test_explicit_transform_is_forwarded_without_source_hash_change():
    args = prepare(photo=True)
    selected = args["questions"][0].question
    original = selected.ordered_blocks[1]
    transform = KakaoImageTransform(
        transform_revision_id=identity("kakaotransformrev", 1),
        rotate_clockwise=90,
        crop=None,
        reason="사용자가 방향 확인",
    )
    selected = selected.model_copy(
        update={
            "ordered_blocks": (
                selected.ordered_blocks[0],
                original.model_copy(update={"transform": transform}),
                *selected.ordered_blocks[2:],
            )
        }
    )
    args.update(packet=packet((selected,)), questions=(published(selected),))
    projected = project_kakao_student_render(**args).questions[0].images[0]
    assert projected.transform.transform_revision_id == transform.transform_revision_id
    assert projected.transform.rotate_clockwise == 90
    assert projected.member.sha256 == original.source_pointer.sha256


def test_unknown_date_is_not_replaced_by_today():
    resolved = source(timezone="unknown")
    value = question(resolved)
    bundle = packet((value,), mode="DRAFT")
    result = project_kakao_student_render(
        packet=bundle,
        student_id=student().student_id,
        questions=(published(value),),
        sources=(resolved,),
        images=(),
    )
    assert result.questions[0].header_date is None
    assert result.mode == "DRAFT"
    assert "TIMEZONE_UNVERIFIED" in bundle.questions[0].final_blockers
    with pytest.raises(ValueError, match="FINAL_BLOCKED"):
        packet((value,), mode="FINAL")
    with pytest.raises(ValueError, match="FINAL_BLOCKED"):
        project_kakao_student_render(
            packet=bundle.model_copy(update={"mode": "FINAL"}),
            student_id=student().student_id,
            questions=(published(value),),
            sources=(resolved,),
            images=(),
        )


@pytest.mark.parametrize(
    "field,value", [("sha256", "sha256:" + "0" * 64), ("media_type", "image/jpeg")]
)
def test_local_image_materialization_pin_must_match_artifact(field, value):
    given = prepare(photo=True)["images"][0]
    with pytest.raises(ValueError, match="IMAGE_PIN_MISMATCH"):
        KakaoRenderImageInput(given.pointer, given.member.model_copy(update={field: value}))


@pytest.mark.parametrize("unknown_date", [False, True])
def test_actual_pdf_from_question_packet_and_source_images(tmp_path, unknown_date):
    # No generated fixture is committed: only this test's disposable workspace.
    input_root, output_root = tmp_path / "input", tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 180), False)
    pixmap.clear_with(170)
    photo = pixmap.tobytes("png")
    resolved = source(
        attachments={1: (image(),)}, timezone="unknown" if unknown_date else "Asia/Seoul"
    )
    entry = next(iter(resolved.attachments))
    source_pointer = pointer("eom://schemas/kakao-archive/media/1.0", photo, 71, "image/png")
    resolved = replace(
        resolved,
        attachments={
            entry: KakaoAttachmentSource(image().attachment_revision_id, source_pointer, "ORIGINAL")
        },
    )
    selected = question(resolved)
    if not unknown_date:
        selected = confirmed(selected, (resolved,))
    manifest = project_kakao_student_render(
        packet=packet((selected,), include_replies=True, mode="DRAFT" if unknown_date else "FINAL"),
        student_id=student().student_id,
        questions=(published(selected),),
        sources=(resolved,),
        images=(
            KakaoRenderImageInput(
                source_pointer,
                LocalMember.model_validate(local_file(input_root, "photo.png", photo, "image/png")),
            ),
        ),
    )
    command = RenderCommand.model_validate(
        {
            "schema_version": "kakao-question-render/1.0",
            "execution": {
                "command_id": identity("kakaocommand", 1),
                "task_id": identity("kakaotask", 1),
                "attempt_id": identity("kakaoattempt", 1),
                "attempt_number": 1,
                "fence": 1,
            },
            "export_id": identity("kakaoexport", 1),
            **{
                key: getattr(manifest, key)
                for key in (
                    "source_binding_id",
                    "packet_revision_id",
                    "student_id",
                    "subset_sha256",
                    "mode",
                )
            },
            "renderer_release_sha256": RELEASE,
            "layout_policy": "student-question-a4/1.0",
            "manifest": local_file(
                input_root,
                "manifest.json",
                canonical_bytes(manifest.model_dump(mode="json")),
                "application/json",
            ),
            "font": local_file(input_root, "font.otf", pymupdf.Font("korea").buffer, "font/otf"),
        }
    )
    result = render_questions(
        command, input_root=input_root, output_root=output_root, renderer_release_sha256=RELEASE
    )
    assert result.status == "COMPLETED", result.error_code
    assert result.page_count == 1
    with pymupdf.open(output_root / "report.pdf") as document:
        assert len(document) == 1
        text = document[0].get_text().replace("\u00a0", " ")
        assert all(value in text for value in ("첫 질문", "추가 질문", "답변", "학생 1"))
        assert len(document[0].get_images()) == 1
        if unknown_date:
            assert "검토용" in text and "날짜 확인 필요" in text
            assert "2026-" not in text and "None" not in text
        else:
            assert "2026-10-31" in text and "날짜 확인 필요" not in text
        raster = document[0].get_pixmap()
        assert raster.width > 0 and raster.height > 0 and len(set(raster.samples)) > 1
    assert (input_root / "photo.png").read_bytes() == photo
