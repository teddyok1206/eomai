"""Real worker-helper parsing agrees with the typed source-role-aware image contract."""

import os
from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.worker_exec import _load_image_inputs
from eom_workflow.material_learning_images import MaterialCodexImageManifest
from pydantic import ValidationError

from tests.unit.test_worker_systemd import _png_header


def manifest(tmp_path):
    images = []
    for index, (role, page) in enumerate((("MAIN", 17), ("SOLUTIONS", 17)), 1):
        relative = f"source/material/{role.lower()}/page-{page:06d}.png"
        payload = _png_header(800, 1200) + bytes([index])
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        path.chmod(0o640)
        images.append(
            {
                "input_index": index,
                "source_role": role,
                "physical_page": page,
                "relative_path": relative,
                "media_type": "image/png",
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "width_pixels": 800,
                "height_pixels": 1200,
            }
        )
    body = {
        "schema_version": "codex-image-input-manifest/5.0",
        "plan_id": "execplan_" + "1" * 32,
        "images": images,
    }
    return {**body, "manifest_sha256": content_sha256(body)}


def load(tmp_path, value):
    path = tmp_path / "codex-image-inputs.json"
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o640)
    return _load_image_inputs(
        path, workspace=tmp_path, group_id=os.getgid(), expected_plan_id=value["plan_id"]
    )


def test_same_physical_page_in_separate_sources_stays_separate(tmp_path):
    value = manifest(tmp_path)
    parsed = MaterialCodexImageManifest.model_validate(value)
    assert tuple(image.physical_page for image in parsed.images) == (17, 17)
    assert load(tmp_path, value) == tuple(tmp_path / image.relative_path for image in parsed.images)
    root = Path(__file__).resolve().parents[2]
    name = "codex-image-input-manifest-v5.schema.json"
    assert (root / "schemas/workflow/control-plane" / name).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources/control-plane" / name
    ).read_bytes()


@pytest.mark.parametrize("case", ["role", "page", "index", "duplicate", "bool", "hash"])
def test_model_and_installed_helper_reject_same_bad_identity(tmp_path, case):
    value = deepcopy(manifest(tmp_path))
    if case == "role":
        value["images"][0]["source_role"] = "SOLUTIONS"
    elif case == "page":
        value["images"][0]["physical_page"] = 18
    elif case == "index":
        value["images"][0]["input_index"] = 2
    elif case == "duplicate":
        value["images"][1] = {**value["images"][0], "input_index": 2}
    elif case == "bool":
        value["images"][0]["input_index"] = True
    if case != "hash":
        value["manifest_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "manifest_sha256"}
        )
    else:
        value["manifest_sha256"] = "sha256:" + "0" * 64
    with pytest.raises((ValidationError, ValueError)):
        MaterialCodexImageManifest.model_validate(value)
    with pytest.raises(ValueError):
        load(tmp_path, value)
