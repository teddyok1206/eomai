from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_image_contracts import content_json_bytes, content_sha256

from scripts.image_trainer import publish_science_visual_pilot_result as publication
from tests.unit.test_science_corpus_visual_contracts import _plan_value


def _png(seed: int) -> bytes:
    width = height = 100
    scanline = b"\x00" + bytes((255 - seed % 128,)) * width
    raw = scanline * height

    def chunk(name: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + name
            + body
            + struct.pack(">I", zlib.crc32(name + body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)


def _stage_complete_workspace(tmp_path: Path) -> tuple[Path, int]:
    plan_value = _plan_value()
    plan_payload = content_json_bytes(plan_value)
    staged_sources = [
        {
            "document_id": source["document_id"],
            "staged_pdf_member": f"input/pdfs/{source['document_id']}.pdf",
            "sha256": source["pdf"]["sha256"],
            "bytes": source["bytes"],
            "page_count": source["page_count"],
        }
        for source in plan_value["selected_sources"]
    ]
    command_body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-command/1.0",
        "plan": {
            "artifact_id": "artifact_" + "7" * 32,
            "artifact_revision_id": "rev_" + "7" * 32,
            "member_path": "manifests/visual-pilot-plan.json",
            "schema_ref": (
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.0"
            ),
            "media_type": "application/json",
            "sha256": sha256_bytes(plan_payload),
        },
        "plan_sha256": plan_value["plan_sha256"],
        "staged_plan_member": "input/visual-pilot-plan.json",
        "staged_sources": staged_sources,
        "result_member": "manifests/visual-pilot-result.json",
        "requested_at": "2026-09-25T19:05:00Z",
        "requested_by": "operator_user",
    }
    command_identity = content_sha256(command_body).removeprefix("sha256:")
    command_with_id = {
        **command_body,
        "attempt_id": "imgscivisattempt_" + command_identity[:32],
    }
    command_value = {
        **command_with_id,
        "command_sha256": content_sha256(command_with_id),
    }
    workspace = tmp_path / str(command_value["attempt_id"])
    workspace.mkdir(mode=0o700)
    _write(workspace / "command.json", content_json_bytes(command_value))
    _write(workspace / "input/visual-pilot-plan.json", plan_payload)

    pages: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for index, source in enumerate(plan_value["selected_sources"]):
        document_id = str(source["document_id"])
        page_payload = _png(index)
        page_sha256 = sha256_bytes(page_payload)
        page_member = f"pages/{document_id}/page-1.png"
        _write(workspace / page_member, page_payload)
        pages.append(
            {
                "document_id": document_id,
                "physical_page": 1,
                "member_path": page_member,
                "sha256": page_sha256,
                "size_bytes": len(page_payload),
                "width_px": 100,
                "height_px": 100,
            }
        )
        candidate_body: dict[str, object] = {
            "document_id": document_id,
            "physical_page": 1,
            "page_image_sha256": page_sha256,
            "bounding_box": {"left": 1000, "top": 1000, "right": 9000, "bottom": 9000},
            "representation_kind": "UNKNOWN",
            "rendering_mode": "MIXED",
            "visual_features": [],
            "authority_class": "UNKNOWN_REVIEW_REQUIRED",
            "review_state": "PENDING",
            "locator_score_milli": 800,
        }
        candidate_identity = content_sha256(candidate_body).removeprefix("sha256:")
        candidate_id = "imgsciviscandidate_" + candidate_identity[:32]
        crop_payload = _png(index + 100)
        crop_member = f"crops/{candidate_id}.png"
        _write(workspace / crop_member, crop_payload)
        candidates.append(
            {
                "candidate_id": candidate_id,
                **candidate_body,
                "member_path": crop_member,
                "sha256": sha256_bytes(crop_payload),
                "size_bytes": len(crop_payload),
            }
        )
    candidates.sort(key=lambda value: str(value["candidate_id"]))
    result_body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-result/1.0",
        "pilot_id": plan_value["pilot_id"],
        "plan_sha256": plan_value["plan_sha256"],
        "status": "SUCCEEDED",
        "page_images": pages,
        "visual_candidates": candidates,
        "omissions": [],
        "runtime": {
            "python_version": "3.11",
            "pillow_version": "11.3",
            "opencv_version": "not-used",
            "tesseract_version": "5.3",
            "pdftoppm_version": "24.02",
        },
        "error_code": None,
        "started_at": "2026-09-25T19:05:00Z",
        "completed_at": "2026-09-25T19:06:00Z",
    }
    result_value = {**result_body, "result_sha256": content_sha256(result_body)}
    _write(
        workspace / "manifests/visual-pilot-result.json",
        content_json_bytes(result_value),
    )
    return workspace, len(pages) + len(candidates) + 1


def test_load_workspace_validates_closed_page_and_crop_set(tmp_path: Path) -> None:
    workspace, expected_members = _stage_complete_workspace(tmp_path)

    command, plan, result, result_payload, output_bytes = publication._load_workspace(workspace)

    assert command.attempt_id == workspace.name
    assert plan.plan_sha256 == result.plan_sha256
    assert len(result.page_images) == 12
    assert len(result.visual_candidates) == 12
    assert expected_members == 25
    assert output_bytes > len(result_payload)


def test_load_workspace_rejects_an_extra_crop(tmp_path: Path) -> None:
    workspace, _expected_members = _stage_complete_workspace(tmp_path)
    _write(workspace / "crops/untrusted-extra.png", _png(255))

    with pytest.raises(
        publication.ScienceVisualPilotPublicationError,
        match="SCIENCE_VISUAL_PILOT_OUTPUT_CLOSURE_INVALID",
    ):
        publication._load_workspace(workspace)


def test_load_workspace_rejects_plan_pointer_hash_drift(tmp_path: Path) -> None:
    workspace, _expected_members = _stage_complete_workspace(tmp_path)
    plan_path = workspace / "input/visual-pilot-plan.json"
    plan_path.write_bytes(plan_path.read_bytes() + b" ")
    plan_path.chmod(0o600)

    with pytest.raises(
        publication.ScienceVisualPilotPublicationError,
        match="SCIENCE_VISUAL_PILOT_MEMBER_HASH_MISMATCH",
    ):
        publication._load_workspace(workspace)


def test_png_parser_rejects_crc_drift() -> None:
    payload = bytearray(_png(1))
    payload[-5] ^= 1

    with pytest.raises(
        publication.ScienceVisualPilotPublicationError,
        match="SCIENCE_VISUAL_PILOT_PNG_INVALID",
    ):
        publication._png_dimensions(bytes(payload))
