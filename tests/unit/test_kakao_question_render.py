"""Anonymous local fixtures exercise actual PyMuPDF output, not stubbed PDFs."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pytest
from eom_kakao_archive_contracts import (
    LocalMember,
    RenderCommand,
    RenderManifest,
    RenderResult,
    canonical_bytes,
    sha256,
    subset_sha256,
)
from eom_kakao_archive_contracts.validation import SCHEMA_SHA256, load_schema, validate_contract
from eom_kakao_archive_worker.local_members import read_member
from eom_kakao_archive_worker.question_pdf import _readback_text_matches, render_questions
from PIL import Image
from pydantic import ValidationError

RELEASE = "sha256:" + "a" * 64


@pytest.mark.parametrize(
    ("expected", "extracted", "shared_glyph", "matches"),
    [
        ("2026-11-17", "2026\u201111\u201117", True, True),
        ("A\u2011B", "A-B", True, True),
        ("모르겠어요\u2026", "모르겠어요\u22ef", True, True),
        ("질문\u3160\u3160", "질문\uffd7\uffd7", True, True),
        ("2026-11-17", "2026\u201111\u201117", False, False),
        ("A-B", "A\u2212B", True, False),
        ("A+B", "A-B", True, False),
        ("x=2", "x=3", True, False),
        ("한글 질문", "한글", True, False),
        ("A-B", "A--B", True, False),
        ("질문\n2026-11-17", "질문\u00a02026\u201111\u201117", True, True),
    ],
)
def test_readback_accepts_only_exact_nonzero_font_glyph_alias(
    expected, extracted, shared_glyph, matches
):
    font = Mock()
    aliases = {0x2D: 14, 0x2011: 14, 0x2026: 735, 0x22EF: 735, 0x3160: 1739, 0xFFD7: 1739}
    font.has_glyph.side_effect = lambda code, **kwargs: (
        aliases.get(code, code + 100) if shared_glyph else code + 100
    )
    assert _readback_text_matches(expected, extracted, font) is matches


def test_readback_does_not_accept_shared_missing_glyphs():
    font = Mock()
    font.has_glyph.return_value = 0
    assert not _readback_text_matches("A-B", "A\u2011B", font)


def identity(kind: str, n: int = 1) -> str:
    return f"kakao{kind}_{n:032x}"


def local_file(root: Path, name: str, raw: bytes, media: str) -> dict[str, object]:
    (root / name).write_bytes(raw)
    (root / name).chmod(0o640)
    return {
        "relative_path": name,
        "sha256": sha256(raw),
        "size_bytes": len(raw),
        "media_type": media,
    }


@pytest.fixture
def prepared(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    font = local_file(source, "font.otf", pymupdf.Font("korea").buffer, "font/otf")
    question = {
        "question_revision_id": identity("questionrev"),
        "header_date": "2026-11-01",
        "text_blocks": [
            {"span_id": "span-one", "text": "질문입니다. \u03b1 → \u03b2\n두 번째 줄."}
        ],
        "images": [],
    }
    manifest = {
        "schema_version": "kakao-question-render-manifest/1.0",
        "source_binding_id": identity("binding"),
        "packet_revision_id": identity("packetrev"),
        "student_id": identity("student"),
        "student_display_name": "익명 학생",
        "subset_sha256": subset_sha256((identity("questionrev"),)),
        "mode": "FINAL",
        "questions": [question],
    }

    def prepare(change=None):
        value = json.loads(json.dumps(manifest))
        if change:
            change(value)
        for question in value["questions"]:
            if "ordered_blocks" not in question:
                question["ordered_blocks"] = [
                    *(
                        {"kind": "TEXT", "span_id": block["span_id"]}
                        for block in question["text_blocks"]
                    ),
                    *(
                        {
                            "kind": "IMAGE",
                            "attachment_occurrence_id": block["attachment_occurrence_id"],
                        }
                        for block in question["images"]
                    ),
                ]
        value["subset_sha256"] = subset_sha256(
            tuple(q["question_revision_id"] for q in value["questions"])
        )
        member = local_file(source, "manifest.json", canonical_bytes(value), "application/json")
        return RenderCommand.model_validate(
            {
                "schema_version": "kakao-question-render/1.0",
                "execution": {
                    "command_id": identity("command"),
                    "task_id": identity("task"),
                    "attempt_id": identity("attempt"),
                    "attempt_number": 1,
                    "fence": 1,
                },
                "export_id": identity("export"),
                **{
                    name: value[name]
                    for name in (
                        "source_binding_id",
                        "packet_revision_id",
                        "student_id",
                        "subset_sha256",
                        "mode",
                    )
                },
                "renderer_release_sha256": RELEASE,
                "layout_policy": "student-question-a4/1.0",
                "manifest": member,
                "font": font,
            }
        )

    return source, output, prepare


def render(prepared, change=None):
    source, output, prepare = prepared
    command = prepare(change)
    return render_questions(
        command, input_root=source, output_root=output, renderer_release_sha256=RELEASE
    )


def picture(source: Path, n=1, size=(400, 300)):
    buffer = io.BytesIO()
    with Image.new("RGB", size, (40, 100, 180)) as image:
        image.save(buffer, format="PNG")
    return {
        "attachment_occurrence_id": identity("attachment", n),
        "attachment_revision_id": identity("attachmentrev", n),
        "availability": "AVAILABLE",
        "quality_accepted": True,
        "member": local_file(source, f"image-{n}.png", buffer.getvalue(), "image/png"),
    }


def test_real_korean_pdf_and_preview(prepared):
    result = render(prepared)
    assert result.status == "COMPLETED"
    assert result.page_count == 1 and len(result.outputs) == 3
    root = prepared[1]
    for output in result.outputs:
        assert sha256((root / output.relative_path).read_bytes()) == output.sha256
    with pymupdf.open(root / "report.pdf") as document:
        assert len(document) == 1
        text = document[0].get_text().replace("\u00a0", " ")
        assert "질문입니다" in text and "두 번째 줄" in text
        assert "\u03b1 → \u03b2" in text
        assert all(document.extract_font(font[0])[3] for font in document[0].get_fonts())
    receipt = json.loads((root / "layout.json").read_bytes())
    assert receipt["pages"][0]["text_blocks"][0]["start_codepoint"] == 0
    assert receipt["pages"][0]["text_blocks"][-1]["end_codepoint"] == len(
        "질문입니다. \u03b1 → \u03b2\n두 번째 줄."
    )


def test_unknown_draft_date_preserved_in_schema_dto_and_real_pdf(prepared):
    def change(value):
        value["mode"] = "DRAFT"
        value["questions"][0]["header_date"] = None

    result = render(prepared, change)
    assert result.status == "COMPLETED" and result.page_count == 1
    raw = json.loads((prepared[0] / "manifest.json").read_bytes())
    validate_contract("manifest", raw)
    assert RenderManifest.model_validate(raw).questions[0].header_date is None
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        assert len(pdf) == 1
        text = pdf[0].get_text().replace("\u00a0", " ")
        assert "검토용" in text and "날짜 확인 필요" in text
        assert "2026-" not in text and "None" not in text
        raster = pdf[0].get_pixmap()
        assert len(set(raster.samples)) > 1
    with pymupdf.open(prepared[1] / "page-0001.png") as preview:
        assert preview[0].rect.width > 0 and preview[0].rect.height > 0


def test_unknown_final_date_rejected_before_output_in_schema_and_dto(prepared):
    result = render(prepared, lambda value: value["questions"][0].update(header_date=None))
    assert result.status == "INVALID_INPUT" and result.error_code == "KAKAO_RENDER_SCHEMA_INVALID"
    assert not result.outputs and not list(prepared[1].iterdir())
    raw = json.loads((prepared[0] / "manifest.json").read_bytes())
    with pytest.raises(ValueError, match="SCHEMA_INVALID"):
        validate_contract("manifest", raw)
    with pytest.raises(ValidationError, match="DATE_UNVERIFIED"):
        RenderManifest.model_validate(raw)


def test_question_page_and_picture_occurrence_order(prepared):
    photos = [picture(prepared[0], n) for n in (1, 2)]

    def change(value):
        value["questions"][0]["images"] = photos
        value["questions"].append(
            {
                "question_revision_id": identity("questionrev", 2),
                "header_date": "2026-11-02",
                "text_blocks": [],
                "images": [photos[0]],
            }
        )

    result = render(prepared, change)
    assert result.status == "COMPLETED" and result.page_count == 2
    receipt = json.loads((prepared[1] / "layout.json").read_bytes())
    assert [entry["attachment_occurrence_id"] for entry in receipt["pages"][0]["image_blocks"]] == [
        identity("attachment", n) for n in (1, 2)
    ]
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        assert len(pdf[0].get_image_info()) == 2
        assert len(pdf[1].get_image_info()) == 1


@pytest.mark.parametrize(
    "case,code",
    [
        ("text", "NEEDS_LAYOUT_REVIEW"),
        ("many", "NEEDS_LAYOUT_REVIEW"),
        ("glyph", "UNSUPPORTED_GLYPH"),
    ],
)
def test_overflow_and_unsupported_glyph_are_not_clipped(prepared, case, code):
    photo = picture(prepared[0])

    def change(value):
        question = value["questions"][0]
        if case == "text":
            question["text_blocks"][0]["text"] = "긴 본문\n" * 1000
        elif case == "many":
            question["images"] = [
                dict(photo, attachment_occurrence_id=identity("attachment", n))
                for n in range(1, 31)
            ]
        else:
            question["text_blocks"][0]["text"] = "unknown \U0010fffd"

    result = render(prepared, change)
    assert result.status == "NEEDS_LAYOUT_REVIEW" and result.error_code == code
    assert not result.outputs and not list(prepared[1].iterdir())


@pytest.mark.parametrize("availability", ["MISSING", "UNRESOLVED", "EXPIRED"])
def test_missing_final_images_block_but_draft_reports_placeholder(prepared, availability):
    def change(value):
        value["questions"][0]["images"] = [
            {
                "attachment_occurrence_id": identity("attachment"),
                "attachment_revision_id": identity("attachmentrev"),
                "member": None,
                "availability": availability,
                "quality_accepted": False,
            }
        ]

    result = render(prepared, change)
    assert result.error_code == "REQUIRED_IMAGE_UNAVAILABLE"

    def draft(value):
        change(value)
        value["mode"] = "DRAFT"

    result = render(prepared, draft)
    assert result.status == "COMPLETED"
    with pymupdf.open(prepared[1] / "report.pdf") as pdf:
        text = pdf[0].get_text().replace("\u00a0", " ")
        assert "검토용" in text and "미확보 사진" in text


def test_bad_quality_final_requires_review(prepared):
    photo = picture(prepared[0])
    photo["quality_accepted"] = False
    result = render(prepared, lambda value: value["questions"][0].update(images=[photo]))
    assert result.error_code == "IMAGE_QUALITY_REVIEW_REQUIRED"


def test_exif_orientation_preserved_as_display_derivative(prepared):
    buffer = io.BytesIO()
    with Image.new("RGB", (400, 200), "red") as image:
        exif = Image.Exif()
        exif[274] = 6
        image.save(buffer, format="JPEG", exif=exif)
    photo = picture(prepared[0])
    photo["member"] = local_file(prepared[0], "rotated.jpg", buffer.getvalue(), "image/jpeg")
    result = render(prepared, lambda value: value["questions"][0].update(images=[photo]))
    assert result.status == "COMPLETED"
    receipt = json.loads((prepared[1] / "layout.json").read_bytes())
    x0, y0, x1, y1 = receipt["pages"][0]["image_blocks"][0]["bounds_pt"]
    assert (x1 - x0) / (y1 - y0) == pytest.approx(0.5)
    assert (prepared[0] / "rotated.jpg").read_bytes() == buffer.getvalue()


def test_identity_and_runtime_pin_mismatch(prepared):
    source, output, prepare = prepared
    command = prepare()
    wrong = command.model_copy(update={"student_id": identity("student", 2)})
    result = render_questions(
        wrong, input_root=source, output_root=output, renderer_release_sha256=RELEASE
    )
    assert result.error_code == "KAKAO_RENDER_MANIFEST_IDENTITY_MISMATCH"
    result = render_questions(
        command, input_root=source, output_root=output, renderer_release_sha256="sha256:" + "b" * 64
    )
    assert result.error_code == "KAKAO_RENDER_RELEASE_MISMATCH"


def test_corrupted_image_and_hash_are_rejected(prepared):
    photo = picture(prepared[0])
    photo["member"] = local_file(prepared[0], "html.png", b"<html>login</html>", "image/png")
    result = render(prepared, lambda value: value["questions"][0].update(images=[photo]))
    assert result.status == "INVALID_INPUT"
    source, output, prepare = prepared
    command = prepare()
    raw = (source / "manifest.json").read_bytes()
    (source / "manifest.json").write_bytes(raw.replace("익명".encode(), "다른".encode()))
    result = render_questions(
        command, input_root=source, output_root=output, renderer_release_sha256=RELEASE
    )
    assert result.error_code == "KAKAO_RENDER_MEMBER_HASH_MISMATCH"


def test_symlink_and_hardlink_inputs_are_rejected(tmp_path):
    origin = tmp_path / "origin"
    member = local_file(tmp_path, "origin", b"data", "application/json")
    (tmp_path / "symlink").symlink_to(origin)
    with pytest.raises(OSError):
        read_member(tmp_path, LocalMember.model_validate(dict(member, relative_path="symlink")))
    os.link(origin, tmp_path / "hardlink")
    with pytest.raises(ValueError, match="MEMBER_UNSAFE"):
        read_member(tmp_path, LocalMember.model_validate(dict(member, relative_path="hardlink")))


@pytest.mark.parametrize(
    "path", ["../data", "/etc/passwd", "x//data", "x/./data", "x\\data", "https://host/a"]
)
def test_member_path_is_not_arbitrary(path):
    with pytest.raises(ValidationError):
        LocalMember(relative_path=path, sha256=RELEASE, size_bytes=1, media_type="image/png")


def test_schema_resources_and_strict_contracts(prepared):
    command = prepared[2]()
    value = command.model_dump(mode="json")
    validate_contract("command", value)
    assert load_schema()["$schema"].endswith("2020-12/schema")
    raw = Path("schemas/kakao-archive/worker-question-render-v1.schema.json").read_bytes()
    assert sha256(raw) == SCHEMA_SHA256
    resource = Path(
        "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas/worker-question-render-v1.schema.json"
    )
    assert resource.read_bytes() == raw
    with pytest.raises(ValueError, match="SCHEMA_INVALID"):
        validate_contract("command", dict(value, actor="ADMIN"))
    manifest = json.loads((prepared[0] / "manifest.json").read_bytes())
    manifest["subset_sha256"] = RELEASE
    with pytest.raises(ValidationError):
        RenderManifest.model_validate(manifest)


@pytest.mark.parametrize("value", [True, "12", 12.0])
def test_numeric_member_fields_do_not_coerce(value):
    with pytest.raises(ValidationError):
        LocalMember(relative_path="a.png", sha256=RELEASE, size_bytes=value, media_type="image/png")


def test_id_kind_cannot_be_substituted(prepared):
    value = prepared[2]().model_dump(mode="json")
    value["packet_revision_id"] = identity("student")
    with pytest.raises(ValidationError):
        RenderCommand.model_validate(value)
    with pytest.raises(ValueError, match="SCHEMA_INVALID"):
        validate_contract("command", value)


def test_result_cannot_repeat_one_member_to_claim_success(prepared):
    result = render(prepared)
    value = result.model_dump(mode="json")
    value["outputs"] = [value["outputs"][0]] * 3
    with pytest.raises(ValidationError):
        RenderResult.model_validate(value)


def test_output_may_not_overlap_input(prepared):
    source, _, prepare = prepared
    result = render_questions(
        prepare(), input_root=source, output_root=source, renderer_release_sha256=RELEASE
    )
    assert result.error_code == "KAKAO_RENDER_WORKSPACE_OVERLAP"


def test_same_pins_produce_identical_pdf_and_manifest(prepared):
    source, first_output, prepare = prepared
    photo = picture(source)
    command = prepare(lambda value: value["questions"][0].update(images=[photo]))
    first = render_questions(
        command, input_root=source, output_root=first_output, renderer_release_sha256=RELEASE
    )
    second_output = first_output.parent / "second-output"
    second_output.mkdir()
    second = render_questions(
        command, input_root=source, output_root=second_output, renderer_release_sha256=RELEASE
    )
    assert first.status == second.status == "COMPLETED"
    assert first == second
    assert (first_output / "report.pdf").read_bytes() == (second_output / "report.pdf").read_bytes()


def test_occupied_output_is_not_overwritten(prepared):
    marker = prepared[1] / "layout.json"
    marker.write_bytes(b"original")
    result = render(prepared)
    assert result.error_code == "KAKAO_RENDER_OUTPUT_NOT_EMPTY"
    assert marker.read_bytes() == b"original"
    assert list(prepared[1].iterdir()) == [marker]


def test_manifest_wire_types_are_validated_before_date_coercion(prepared):
    result = render(prepared, lambda value: value["questions"][0].update(header_date=1793491200))
    assert result.status == "INVALID_INPUT" and result.error_code == "KAKAO_RENDER_SCHEMA_INVALID"
    assert not list(prepared[1].iterdir())


def test_display_budget_fails_before_outputs(prepared, monkeypatch):
    import eom_kakao_archive_worker.question_pdf as worker

    monkeypatch.setattr(worker, "MAX_TOTAL_PIXELS", 100)
    photo = picture(prepared[0])
    result = render(prepared, lambda value: value["questions"][0].update(images=[photo]))
    assert result.error_code == "KAKAO_RENDER_DISPLAY_BUDGET_EXCEEDED"
    assert not list(prepared[1].iterdir())


def test_partial_output_write_is_not_a_success_receipt(prepared, monkeypatch):
    import eom_kakao_archive_worker.question_pdf as worker

    original = worker.write_member

    def fail_second(root, name, raw, media_type):
        if name == "layout.json":
            raise OSError("private source content must never be echoed")
        return original(root, name, raw, media_type)

    monkeypatch.setattr(worker, "write_member", fail_second)
    result = render(prepared)
    assert result.status == "INVALID_INPUT" and result.outputs == () and result.page_count == 0
    assert "private" not in result.model_dump_json()
    # Owner may inspect/clean failed local materialization.
    assert (prepared[1] / "report.pdf").exists()


@pytest.mark.parametrize("raw", [b'{"private":"secret",', b"secret" * 10000])
def test_cli_invalid_and_oversized_input_is_redacted(prepared, raw):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eom_kakao_archive_worker.cli",
            "--input-root",
            str(prepared[0]),
            "--output-root",
            str(prepared[1]),
            "--renderer-release-sha256",
            RELEASE,
        ],
        input=raw,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b"KAKAO_RENDER_COMMAND_INVALID\n"
    assert not list(prepared[1].iterdir())


def test_cli_real_local_handoff(prepared):
    command = prepared[2]()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eom_kakao_archive_worker.cli",
            "--input-root",
            str(prepared[0]),
            "--output-root",
            str(prepared[1]),
            "--renderer-release-sha256",
            RELEASE,
        ],
        input=canonical_bytes(command.model_dump(mode="json")),
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0 and completed.stderr == b""
    assert RenderResult.model_validate_json(completed.stdout).status == "COMPLETED"
