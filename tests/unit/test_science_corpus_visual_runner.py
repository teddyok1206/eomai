from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts import (
    ImageEvaluationBoundingBox,
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotPlan,
    content_sha256,
)
from eom_image_trainer import science_corpus_visual_runner as runner
from eom_image_trainer.crop_locator import LocatedVisualRegion
from PIL import Image, ImageDraw  # type: ignore[import-not-found]


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _pointer(
    character: str,
    *,
    member_path: str,
    schema_ref: str,
    media_type: str = "application/json",
    sha256: str | None = None,
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + character * 32,
        "artifact_revision_id": "rev_" + character * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": sha256 or _sha(character),
    }


def _source(index: int) -> tuple[dict[str, object], bytes]:
    payload = (f"%PDF-science-visual-{index:02d}".encode() * 80)[:1280]
    digest = hashlib.sha256(payload).hexdigest()
    partition = "TRAIN" if index < 6 else "VALIDATION" if index < 9 else "HOLDOUT"
    issuer = "KICE" if index % 2 else "EDUCATION_AUTHORITY"
    group = content_sha256(
        {
            "issuer_type": issuer,
            "administration_year": 2010 + index,
            "grade": 3,
            "session_label": f"SESSION_{index:02d}",
        }
    )
    return (
        {
            "document_id": "sciencedoc_" + digest[:32],
            "source_file_id": "sourcefile_" + f"{index + 1:032x}",
            "pdf": _pointer(
                f"{index + 1:x}",
                member_path=f"source/exam-{index:02d}.pdf",
                schema_ref="eom://schemas/content-intake/source-file/1.0",
                media_type="application/pdf",
                sha256="sha256:" + digest,
            ),
            "bytes": len(payload),
            "page_count": 1,
            "subject_family": (
                "CHEMISTRY",
                "EARTH_SCIENCE",
                "GENERAL_SCIENCE",
                "INTEGRATED_SCIENCE",
                "LIFE_SCIENCE",
                "PHYSICS",
            )[index % 6],
            "issuer_type": issuer,
            "administration_year": 2010 + index,
            "grade": 3,
            "session_label": f"SESSION_{index:02d}",
            "exam_group_sha256": group,
            "partition": partition,
        },
        payload,
    )


def _plan() -> tuple[LocalImageScienceCorpusVisualPilotPlan, dict[str, bytes]]:
    source_pairs = [_source(index) for index in range(12)]
    source_pairs.sort(key=lambda value: str(value[0]["document_id"]))
    sources = [value[0] for value in source_pairs]
    payloads = {str(value[0]["document_id"]): value[1] for value in source_pairs}
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-plan/1.0",
        "corpus_manifest": _pointer(
            "1",
            member_path="corpus-manifest.json",
            schema_ref=(
                "eom://schemas/legacy-assessment/science-assessment-web-corpus-manifest/2.0"
            ),
        ),
        "corpus_id": "sciencecorpus_" + "2" * 32,
        "corpus_manifest_sha256": _sha("3"),
        "acquisition_sha256": _sha("4"),
        "resolution_sha256": _sha("5"),
        "resolution_policy_id": "sciencecorpuspolicy_" + "6" * 32,
        "resolution_policy_sha256": _sha("7"),
        "training_authorization": _pointer(
            "8",
            member_path="manifests/science-corpus-training-authorization.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0"
            ),
        ),
        "selection_algorithm": "SCIENCE_VISUAL_STRATIFIED_SHA256_V1",
        "selection_seed_sha256": _sha("9"),
        "selected_sources": sources,
        "max_page_images": 12,
        "max_visual_candidates": 24,
        "max_lora_training_crops": 12,
        "page_render_dpi": 144,
        "locator_revision": "science-corpus-visual-locator/1.0",
        "guidance_authorities": [
            {
                "role": "AUTHORING_TEAM_LEAD",
                "logical_name": (
                    "config/control-plane/standard-item-v5/references/guidance/"
                    "content-team-integrated-science-authoring-v05.md"
                ),
                "source_commit": "a" * 40,
                "sha256": _sha("a"),
            },
            {
                "role": "HWPX_EDITOR_TEAM_LEAD",
                "logical_name": (
                    "config/control-plane/standard-item-v6/references/guidance/"
                    "content-team-hwp-question-editor-handoff-v1.md"
                ),
                "source_commit": "a" * 40,
                "sha256": _sha("b"),
            },
            {
                "role": "KICE_ILLUSTRATION_GUIDE",
                "logical_name": "content/image-specs/kice-integrated-science-illustration-v1.md",
                "source_commit": "a" * 40,
                "sha256": _sha("c"),
            },
        ],
        "tools": {
            "pdftoppm": {
                "path": "/usr/bin/pdftoppm",
                "sha256": _sha("d"),
                "version": "pdftoppm version 24.02.0",
            },
            "tesseract": {
                "path": "/usr/bin/tesseract",
                "sha256": _sha("e"),
                "version": "tesseract 5.3.4",
            },
        },
        "created_at": "2026-09-25T19:00:00Z",
        "created_by": "operator_user",
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["pilot_id"] = "imgscivispilot_" + identity[:32]
    body["plan_sha256"] = content_sha256(body)
    return LocalImageScienceCorpusVisualPilotPlan.model_validate(body), payloads


def _stage(tmp_path: Path) -> tuple[Path, Path, LocalImageScienceCorpusVisualPilotPlan]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    input_root = workspace / "input"
    input_root.mkdir(mode=0o700)
    pdf_root = input_root / "pdfs"
    pdf_root.mkdir(mode=0o700)
    plan, payloads = _plan()
    plan_payload = _canonical_json(plan.model_dump(mode="json"))
    plan_path = input_root / "visual-pilot-plan.json"
    plan_path.write_bytes(plan_payload)
    plan_path.chmod(0o600)
    staged_sources = []
    for source in plan.selected_sources:
        member = f"input/pdfs/{source.document_id}.pdf"
        path = workspace / member
        path.write_bytes(payloads[source.document_id])
        path.chmod(0o600)
        staged_sources.append(
            {
                "document_id": source.document_id,
                "staged_pdf_member": member,
                "sha256": source.pdf.sha256,
                "bytes": source.bytes,
                "page_count": source.page_count,
            }
        )
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-command/1.0",
        "plan": _pointer(
            "f",
            member_path="manifests/visual-pilot-plan.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.0"
            ),
            sha256="sha256:" + hashlib.sha256(plan_payload).hexdigest(),
        ),
        "plan_sha256": plan.plan_sha256,
        "staged_plan_member": "input/visual-pilot-plan.json",
        "staged_sources": staged_sources,
        "result_member": "manifests/visual-pilot-result.json",
        "requested_at": "2026-09-25T19:05:00Z",
        "requested_by": "operator_user",
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["attempt_id"] = "imgscivisattempt_" + identity[:32]
    body["command_sha256"] = content_sha256(body)
    command = LocalImageScienceCorpusVisualPilotCommand.model_validate(body)
    command_path = workspace / "command.json"
    command_path.write_bytes(_canonical_json(command.model_dump(mode="json")))
    command_path.chmod(0o600)
    return workspace, command_path, plan


def _png_for_path(path: Path) -> bytes:
    digest = hashlib.sha256(path.name.encode()).digest()
    image = Image.new("RGB", (160, 120), (255, 255, 255))
    drawing = ImageDraw.Draw(image)
    for index, height in enumerate(digest[:16]):
        left = 5 + index * 9
        drawing.rectangle((left, 110 - height % 96, left + 5, 110), fill=0)
    from io import BytesIO

    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def test_runner_materializes_typed_pages_candidates_and_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, command_path, plan = _stage(tmp_path)
    region = LocatedVisualRegion(
        crop_bounding_box=ImageEvaluationBoundingBox(
            left=1000,
            top=1000,
            right=9000,
            bottom=9000,
        ),
        redaction_boxes=(),
        candidate_rank=1,
        ink_fraction_milli=800,
    )
    monkeypatch.setattr(
        runner,
        "_verify_tools",
        lambda _plan: ("pdftoppm version 24.02.0", "tesseract 5.3.4"),
    )
    monkeypatch.setattr(
        runner,
        "_render_pdf",
        lambda path, *, expected_pages, dpi: (_png_for_path(path),),
    )
    monkeypatch.setattr(runner, "run_tesseract", lambda page, *, executable: ())
    monkeypatch.setattr(
        runner,
        "locate_visual_regions",
        lambda page, *, context_bounding_box, ocr_boxes: (region,),
    )

    result = runner.run_science_corpus_visual_pilot(
        workspace=workspace,
        command_path=command_path,
        now=datetime(2026, 9, 25, 19, 10, tzinfo=UTC),
    )

    assert result.status == "SUCCEEDED"
    assert result.plan_sha256 == plan.plan_sha256
    assert len(result.page_images) == 12
    assert len(result.visual_candidates) == 12
    assert not result.omissions
    assert all(
        value.authority_class == "UNKNOWN_REVIEW_REQUIRED" for value in result.visual_candidates
    )
    result_path = workspace / "manifests/visual-pilot-result.json"
    assert result_path.read_bytes() == _canonical_json(result.model_dump(mode="json"))
    assert result_path.stat().st_mode & 0o777 == 0o600


def test_runner_rejects_staged_pdf_hash_drift_before_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, command_path, _plan_value = _stage(tmp_path)
    first_pdf = next((workspace / "input/pdfs").iterdir())
    first_pdf.write_bytes(first_pdf.read_bytes() + b"drift")
    first_pdf.chmod(0o600)
    render_called = False

    def _unexpected_render(path: Path, *, expected_pages: int, dpi: int) -> tuple[bytes, ...]:
        nonlocal render_called
        render_called = True
        return (_png_for_path(path),)

    monkeypatch.setattr(
        runner,
        "_verify_tools",
        lambda _plan: ("pdftoppm version 24.02.0", "tesseract 5.3.4"),
    )
    monkeypatch.setattr(runner, "_render_pdf", _unexpected_render)

    with pytest.raises(
        runner.ScienceCorpusVisualRunnerError,
        match="SCIENCE_VISUAL_PILOT_INPUT_INVALID",
    ):
        runner.run_science_corpus_visual_pilot(
            workspace=workspace,
            command_path=command_path,
            now=datetime(2026, 9, 25, 19, 10, tzinfo=UTC),
        )
    assert not render_called
