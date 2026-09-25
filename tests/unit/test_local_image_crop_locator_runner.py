from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest
from eom_image_contracts import LocalImageCropLocatorCommand, content_sha256
from eom_image_trainer import crop_locator_runner
from PIL import Image, ImageDraw  # type: ignore[import-not-found]


def _sha(character: str) -> str:
    return "sha256:" + character * 64


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


def _page() -> bytes:
    image = Image.new("RGB", (1000, 800), "white")
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((280, 180, 720, 620), outline="black", width=16)
    drawing.line((350, 400, 650, 400), fill="black", width=10)
    target = io.BytesIO()
    image.save(target, format="PNG", optimize=False)
    return target.getvalue()


def _command(page_sha256: str) -> LocalImageCropLocatorCommand:
    holdout_ids = ["imgsample_" + f"{index:032x}" for index in range(12)]
    holdout_anchors = ["assessmentanchor_" + f"{index + 100:032x}" for index in range(12)]
    identity_body: dict[str, object] = {
        "schema_version": "local-image-crop-locator-command/1.0",
        "source_snapshot": {
            "graph_revision_id": "graphrev_" + "1" * 32,
            "graph_snapshot_sha256": _sha("2"),
            "graph_manifest_sha256": _sha("3"),
            "target_count": 520,
            "target_set_sha256": _sha("4"),
        },
        "training_authorization": _pointer(
            "5",
            member_path="manifests/training-authorization.json",
            schema_ref="eom://schemas/image-provider/local-image-training-authorization/1.0",
        ),
        "holdout_evaluation_plan": _pointer(
            "6",
            member_path="manifests/evaluation-plan.json",
            schema_ref="eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0",
        ),
        "holdout_sample_ids": holdout_ids,
        "holdout_source_anchor_ids": holdout_anchors,
        "selection_query_revision": "local-image-lora-crop-source-query/1.0",
        "locator_revision": "local-image-visual-crop-locator/1.0",
        "sources": [
            {
                "item_revision_id": "itemrev_" + "7" * 32,
                "extraction_result": _pointer(
                    "8",
                    member_path="extraction/result.json",
                    schema_ref="eom://schemas/catalog/legacy-item-extraction-result/1.0",
                ),
                "source_anchor_id": "assessmentanchor_" + "9" * 32,
                "visual_pattern_ids": ["visualpattern_" + "a" * 32],
                "source_page_image": _pointer(
                    "b",
                    member_path="pages/problem-1.png",
                    schema_ref="eom://schemas/catalog/assessment-page-image/1.0",
                    media_type="image/png",
                    sha256=page_sha256,
                ),
                "staged_page_member": ("pages/" + page_sha256.removeprefix("sha256:") + ".png"),
                "physical_page": 1,
                "context_bounding_box": {
                    "left": 0,
                    "top": 0,
                    "right": 10000,
                    "bottom": 10000,
                },
                "rights_policy": {
                    "rights_policy_id": "rightspolicy_" + "c" * 32,
                    "rights_policy_revision_id": "rightspolicyrev_" + "d" * 32,
                    "rights_policy_sha256": _sha("e"),
                },
                "representation_kind": "PHOTOGRAPH",
                "rendering_mode": "RASTER",
                "visual_features": [],
            }
        ],
        "preliminary_omissions": [],
        "created_at": "2026-09-25T12:30:00Z",
        "created_by": "operator_test",
        "output_member": "outputs/crop-locator-result.json",
    }
    identity = content_sha256(identity_body).removeprefix("sha256:")
    body = {**identity_body, "locator_run_id": "imgcroplocator_" + identity[:32]}
    return LocalImageCropLocatorCommand.model_validate(
        {**body, "command_sha256": content_sha256(body)}
    )


def _workspace(tmp_path: Path, command: LocalImageCropLocatorCommand, page: bytes) -> Path:
    workspace = tmp_path / command.locator_run_id
    workspace.mkdir(mode=0o700)
    (workspace / "pages").mkdir(mode=0o700)
    (workspace / "outputs").mkdir(mode=0o700)
    (workspace / "review").mkdir(mode=0o700)
    page_path = workspace / command.sources[0].staged_page_member
    page_path.write_bytes(page)
    os.chmod(page_path, 0o600)
    return workspace


def test_crop_locator_runner_writes_bound_result_and_contact_sheet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page()
    page_sha256 = "sha256:" + hashlib.sha256(page).hexdigest()
    command = _command(page_sha256)
    workspace = _workspace(tmp_path, command, page)
    monkeypatch.setattr(crop_locator_runner, "run_tesseract", lambda _image: ())

    result = crop_locator_runner.run_crop_locator_command(
        workspace=workspace,
        command=command,
    )

    assert result.status == "SUCCEEDED"
    assert result.proposal_set is not None
    assert (workspace / command.output_member).is_file()
    assert (workspace / "review/review-index.json").is_file()
    assert tuple((workspace / "review").glob("contact-sheet-*.png"))


def test_crop_locator_runner_persists_typed_failure_on_page_hash_mismatch(
    tmp_path: Path,
) -> None:
    page = _page()
    command = _command(_sha("f"))
    workspace = _workspace(tmp_path, command, page)

    result = crop_locator_runner.run_crop_locator_command(
        workspace=workspace,
        command=command,
    )

    assert result.status == "FAILED"
    assert result.error_code == "IMAGE_TRAINING_INPUT_HASH_MISMATCH"
    stored = json.loads((workspace / command.output_member).read_text(encoding="utf-8"))
    assert stored["result_sha256"] == result.result_sha256
