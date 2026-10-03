from __future__ import annotations

import os
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageSdxlLineartStack,
    SdxlLineartStackPointer,
    content_json_bytes,
)
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.staged_file_io import copy_verified_member, verified_directory

from tests.unit.test_sdxl_lineart_probe import _sha
from tests.unit.test_sdxl_lineart_stack_contract import _seal_component, _seal_stack, _stack


def _materialize(
    tmp_path: Path,
) -> tuple[LocalImageSdxlLineartStack, SdxlLineartStackPointer, Path]:
    value = _stack()
    for component in value["components"]:
        for file in component["files"]:
            file["sha256"] = _sha(b"x" * 20)
        component.update(_seal_component(component))
    manifest = LocalImageSdxlLineartStack.model_validate(_seal_stack(value))
    pointer = SdxlLineartStackPointer(
        **manifest.model_dump(
            include={
                "model_id",
                "model_revision_id",
                "manifest_sha256",
                "provider_family",
                "runtime_contract_version",
            }
        )
    )
    root = tmp_path / manifest.model_id / manifest.model_revision_id
    for component in manifest.components:
        for file in component.files:
            path = root / "components" / component.role.lower() / file.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 20)
            path.chmod(0o600)
    (root / "manifest.json").write_bytes(content_json_bytes(manifest.model_dump(mode="json")))
    (root / "manifest.json").chmod(0o600)
    tmp_path.chmod(0o700)
    for path in tmp_path.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
    return manifest, pointer, root


def test_model_resolves_exact_revision_and_sorted_component_roots(tmp_path: Path) -> None:
    manifest, pointer, root = _materialize(tmp_path)
    resolved = resolve_sdxl_stack(tmp_path, pointer, expected_owner_uid=os.geteuid())
    assert resolved.manifest == manifest
    assert tuple(resolved.component_roots) == ("BASE", "LINEART_ADAPTER", "VAE")
    assert resolved.component_roots["BASE"] == root / "components/base"


@pytest.mark.parametrize(
    "fault", ["missing", "extra", "hash", "symlink", "hardlink", "mode", "stale", "pointer"]
)
def test_model_pointer_resolution_rejects_missing_stale_changed_or_unsafe_weights(
    tmp_path: Path,
    fault: str,
) -> None:
    _manifest, pointer, root = _materialize(tmp_path)
    weight = root / "components/base/unet/diffusion_pytorch_model.fp16.safetensors"
    if fault == "missing":
        weight.unlink()
    elif fault == "extra":
        (root / "components/base/untracked.txt").write_bytes(b"x")
    elif fault == "hash":
        weight.write_bytes(b"y" * 20)
    elif fault == "symlink":
        weight.unlink()
        weight.symlink_to(root / "components/base/model_index.json")
    elif fault == "hardlink":
        weight.unlink()
        os.link(root / "components/base/model_index.json", weight)
    elif fault == "mode":
        weight.chmod(0o660)
    elif fault == "stale":
        pointer = pointer.model_copy(update={"model_revision_id": "imgmodelrev_" + "f" * 32})
    else:
        pointer = pointer.model_copy(update={"manifest_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ProviderError):
        resolve_sdxl_stack(tmp_path, pointer, expected_owner_uid=os.geteuid())


@pytest.mark.parametrize("fault", [None, "hash", "size", "symlink", "hardlink"])
def test_install_boundary_streams_only_verified_exact_weight_members(
    tmp_path: Path, fault: str | None
) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir(mode=0o700)
    destination.mkdir(mode=0o700)
    payload = b"bounded test weight"
    (source / "weight.safetensors").write_bytes(payload)
    (source / "weight.safetensors").chmod(0o600)
    if fault in {"symlink", "hardlink"}:
        (source / "origin").write_bytes(payload)
        (source / "weight.safetensors").unlink()
        if fault == "symlink":
            (source / "weight.safetensors").symlink_to(source / "origin")
        else:
            os.link(source / "origin", source / "weight.safetensors")
    with (
        verified_directory(source, expected_owner_uid=os.geteuid()) as origin,
        verified_directory(destination, expected_owner_uid=os.geteuid()) as target,
    ):
        kwargs = {
            "size_bytes": len(payload) + (1 if fault == "size" else 0),
            "sha256": "sha256:" + "f" * 64 if fault == "hash" else _sha(payload),
            "source_owner_uid": os.geteuid(),
            "destination_group_gid": os.getegid(),
        }
        if fault:
            with pytest.raises(ProviderError):
                copy_verified_member(origin, target, "weight.safetensors", **kwargs)
        else:
            copy_verified_member(origin, target, "weight.safetensors", **kwargs)
            assert (destination / "weight.safetensors").read_bytes() == payload
            assert (destination / "weight.safetensors").stat().st_mode & 0o777 == 0o640
            with pytest.raises(ProviderError):
                copy_verified_member(origin, target, "weight.safetensors", **kwargs)
