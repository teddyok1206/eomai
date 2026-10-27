"""The creative page manifest is separate from PDF-review image contracts."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.worker_exec import _load_image_inputs
from eom_workflow import CodexCreativeImageInputManifest
from eom_workflow.control_schemas import validate_control_contract
from pydantic import ValidationError

from tests.unit.test_worker_systemd import _png_header

ROOT = Path(__file__).resolve().parents[2]


def _manifest(tmp_path: Path) -> dict[str, object]:
    images: list[dict[str, object]] = []
    for page in (1, 2):
        relative = f"source/pages/page-{page:04d}.png"
        payload = _png_header(800, 1200) + bytes([page])
        image = tmp_path / relative
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(payload)
        image.chmod(0o640)
        images.append(
            {
                "physical_page": page,
                "relative_path": relative,
                "media_type": "image/png",
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "width_pixels": 800,
                "height_pixels": 1200,
            }
        )
    body: dict[str, object] = {
        "schema_version": "codex-image-input-manifest/4.0",
        "plan_id": "execplan_" + "1" * 32,
        "images": images,
    }
    return {**body, "manifest_sha256": content_sha256(body)}


def test_creative_schema_model_and_worker_accept_the_same_exact_pages(tmp_path: Path) -> None:
    canonical = ROOT / "schemas/workflow/control-plane/codex-image-input-manifest-v4.schema.json"
    resource = (
        ROOT
        / "packages/workflow/eom_workflow/resources/control-plane"
        / "codex-image-input-manifest-v4.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()
    manifest = _manifest(tmp_path)
    validate_control_contract("codex-image-input-manifest-v4", manifest)
    parsed = CodexCreativeImageInputManifest.model_validate(manifest)
    assert tuple(image.physical_page for image in parsed.images) == (1, 2)
    path = tmp_path / "codex-image-inputs.json"
    path.write_bytes(canonical_json_bytes(manifest))
    path.chmod(0o640)
    assert _load_image_inputs(
        path,
        workspace=tmp_path,
        group_id=os.getgid(),
        expected_plan_id=str(manifest["plan_id"]),
    ) == (tmp_path / "source/pages/page-0001.png", tmp_path / "source/pages/page-0002.png")


def test_creative_manifest_rejects_path_and_page_order_drift(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    bad_path = deepcopy(manifest)
    bad_path["images"][0]["relative_path"] = "source/pages/page-0002.png"
    bad_path["manifest_sha256"] = content_sha256(
        {key: value for key, value in bad_path.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="physical page"):
        CodexCreativeImageInputManifest.model_validate(bad_path)

    wrong_order = deepcopy(manifest)
    wrong_order["images"].reverse()
    wrong_order["manifest_sha256"] = content_sha256(
        {key: value for key, value in wrong_order.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="ordered, contiguous"):
        CodexCreativeImageInputManifest.model_validate(wrong_order)
