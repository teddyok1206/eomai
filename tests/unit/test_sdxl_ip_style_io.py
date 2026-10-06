"""Tiny local fixtures exercise resolution, not actual model or visual acceptance."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest
from eom_image_contracts import content_json_bytes, sdxl_ip_style_model_pointer
from eom_image_contracts import sdxl_ip_style as contract
from eom_image_contracts.models import ModelFile
from eom_image_provider import sdxl_ip_style_io as resolution
from eom_image_provider.provider import ProviderError

from tests.unit.test_sdxl_ip_style_manifest import _seal, _value


def _payloads():
    return {
        "LICENSE.code.txt": b"Apache License\nVersion 2.0\n",
        "NOTICE.encoder.md": b"---\nlicense: mit\n---\nEncoder notice.\n",
        "README.md": b"---\nlicense: apache-2.0\n---\nResearch card.\n",
        "models/image_encoder/config.json": json.dumps(
            dict(
                architectures=["CLIPVisionModelWithProjection"],
                model_type="clip_vision_model",
                hidden_size=1280,
                intermediate_size=5120,
                num_attention_heads=16,
                num_hidden_layers=32,
                projection_dim=1024,
                image_size=224,
                patch_size=14,
                num_channels=3,
                torch_dtype="float16",
            )
        ).encode(),
        "models/image_encoder/model.safetensors": b"synthetic encoder, not tensors",
        "sdxl_models/ip-adapter_sdxl_vit-h.safetensors": b"synthetic adapter, not tensors",
    }


def _stage(tmp_path, monkeypatch, payloads=None):
    payloads = _payloads() if payloads is None else payloads
    value = _value()
    files = {
        name: ModelFile(
            relative_path=name,
            size_bytes=len(raw),
            sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        )
        for name, raw in payloads.items()
    }
    # Only this test substitutes tiny bytes. Production keeps the fixed upstream hash whitelist.
    monkeypatch.setattr(contract, "SDXL_IP_STYLE_FILES", MappingProxyType(files))
    value["files"] = [files[name].model_dump(mode="json") for name in sorted(files)]
    manifest = contract.LocalImageSdxlIpStyleModelManifest.model_validate(_seal(value))
    pointer = sdxl_ip_style_model_pointer(manifest)
    store = tmp_path / "store"
    root = store / pointer.model_id / pointer.model_revision_id
    root.mkdir(parents=True, mode=0o700)
    store.chmod(0o700)
    root.parent.chmod(0o700)
    for name, raw in payloads.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(raw)
        target.chmod(0o600)
    for directory in ("models", "models/image_encoder", "sdxl_models"):
        (root / directory).chmod(0o700)
    (root / "manifest.json").write_bytes(content_json_bytes(manifest.model_dump(mode="json")))
    (root / "manifest.json").chmod(0o600)
    return store, root, manifest, pointer


def _resolve(store, pointer):
    return resolution.resolve_sdxl_ip_style_model(store, pointer, expected_owner_uid=os.getuid())


def _denied(store, pointer, code="SDXL_PROBE_MODEL_INVALID"):
    with pytest.raises(ProviderError) as error:
        _resolve(store, pointer)
    assert error.value.code == code


def test_resolve_materializes_only_manifest_and_four_metadata_then_streams_weights(
    tmp_path, monkeypatch
):
    store, root, manifest, pointer = _stage(tmp_path, monkeypatch)
    reads, streams = [], []
    read, verify = resolution.read_staged_member, resolution.verify_staged_member

    def observe_read(*args, **kwargs):
        assert not streams
        reads.append(args[1])
        return read(*args, **kwargs)

    def observe_stream(*args, **kwargs):
        assert len(reads) == 5
        streams.append(args[1])
        return verify(*args, **kwargs)

    monkeypatch.setattr(resolution, "read_staged_member", observe_read)
    monkeypatch.setattr(resolution, "verify_staged_member", observe_stream)
    result = _resolve(store, pointer)
    assert result.root == root and result.manifest == manifest
    assert reads == [
        "manifest.json",
        "LICENSE.code.txt",
        "NOTICE.encoder.md",
        "README.md",
        "config.json",
    ]
    assert streams == ["model.safetensors", "ip-adapter_sdxl_vit-h.safetensors"]


@pytest.mark.parametrize("member", (*_payloads(), "manifest.json"))
def test_missing_member_fails_without_recovery(tmp_path, monkeypatch, member):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    (root / member).unlink()
    _denied(store, pointer)


@pytest.mark.parametrize("member", tuple(_payloads()))
def test_each_member_hash_is_checked(tmp_path, monkeypatch, member):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    target = root / member
    raw = target.read_bytes()
    target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    _denied(store, pointer, "SDXL_PROBE_HASH_MISMATCH")


@pytest.mark.parametrize(
    "fault", ["symlink", "hardlink", "writable", "directory", "empty", "oversize", "fifo"]
)
@pytest.mark.parametrize(
    "member", ["manifest.json", "README.md", "models/image_encoder/model.safetensors"]
)
def test_unsafe_file_types_permissions_and_bounds_fail(tmp_path, monkeypatch, member, fault):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    target = root / member
    if fault == "symlink":
        copy = tmp_path / "same-bytes"
        target.rename(copy)
        target.symlink_to(copy)
    elif fault == "hardlink":
        os.link(target, tmp_path / "second-link")
    elif fault == "writable":
        target.chmod(0o620)
    elif fault == "directory":
        target.unlink()
        target.mkdir()
    elif fault == "empty":
        target.write_bytes(b"")
    elif fault == "fifo":
        target.unlink()
        os.mkfifo(target)
    else:
        target.write_bytes(b"x" * (65537 if member == "manifest.json" else 1024))
    _denied(store, pointer)


@pytest.mark.parametrize("directory", ["", "models", "models/image_encoder", "sdxl_models"])
@pytest.mark.parametrize("fault", ["extra-file", "extra-empty-dir", "writable", "symlink"])
def test_exact_nested_tree_closure_no_link_traversal(tmp_path, monkeypatch, directory, fault):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    target = root / directory
    if fault == "extra-file":
        (target / ".extra").write_bytes(b"unused")
    elif fault == "extra-empty-dir":
        (target / "extra").mkdir()
    elif fault == "writable":
        target.chmod(0o770)
    else:
        renamed = tmp_path / "moved-directory"
        target.rename(renamed)
        target.symlink_to(renamed, target_is_directory=True)
    _denied(store, pointer)


@pytest.mark.parametrize(
    "fault", ["noncanonical", "schema", "state", "identity", "pointer-hash", "stale"]
)
def test_manifest_and_pointer_cannot_select_latest_or_reinterpret_state(
    tmp_path, monkeypatch, fault
):
    store, root, manifest, pointer = _stage(tmp_path, monkeypatch)
    if fault == "pointer-hash":
        pointer = pointer.model_copy(update={"manifest_sha256": "sha256:" + "0" * 64})
        _denied(store, pointer, "SDXL_PROBE_HASH_MISMATCH")
        return
    if fault == "stale":
        pointer = pointer.model_copy(update={"model_revision_id": "imgmodelrev_" + "0" * 32})
        _denied(store, pointer)
        return
    value = manifest.model_dump(mode="json")
    if fault == "noncanonical":
        raw = json.dumps(value, indent=2).encode()
    else:
        field = {"schema": "schema_version", "state": "state", "identity": "model_id"}[fault]
        value[field] = {
            "schema": "unknown/1.0",
            "state": "APPROVED",
            "identity": "imgmodel_" + "0" * 32,
        }[fault]
        raw = content_json_bytes(value)
    (root / "manifest.json").write_bytes(raw)
    _denied(store, pointer)


@pytest.mark.parametrize("field", ["model_id", "model_revision_id"])
def test_unvalidated_model_copy_rejected_before_any_directory_read(tmp_path, monkeypatch, field):
    store, _, _, pointer = _stage(tmp_path, monkeypatch)
    pointer = pointer.model_copy(update={field: "../../escape"})

    def forbidden(*args, **kwargs):
        pytest.fail("invalid pointer reached filesystem")

    monkeypatch.setattr(resolution, "verified_directory", forbidden)
    _denied(store, pointer)


@pytest.mark.parametrize(
    "fault", ["hidden-size", "remote-code", "card-license", "encoder-license", "code-license"]
)
def test_metadata_semantics_fail_before_weight_streaming(tmp_path, monkeypatch, fault):
    payloads = _payloads()
    if fault in {"hidden-size", "remote-code"}:
        config = json.loads(payloads["models/image_encoder/config.json"])
        config["hidden_size" if fault == "hidden-size" else "auto_map"] = 42
        payloads["models/image_encoder/config.json"] = json.dumps(config).encode()
    else:
        member = {
            "card-license": "README.md",
            "encoder-license": "NOTICE.encoder.md",
            "code-license": "LICENSE.code.txt",
        }[fault]
        payloads[member] = b"invalid notice"
    store, _, _, pointer = _stage(tmp_path, monkeypatch, payloads)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid metadata reached weights")

    monkeypatch.setattr(resolution, "verify_staged_member", forbidden)
    _denied(store, pointer)


@pytest.mark.parametrize(
    "target",
    [
        "manifest.json",
        "README.md",
        "models/image_encoder/model.safetensors",
        "models",
        "models/image_encoder",
        "",
        "..",
        "../..",
    ],
)
def test_permission_changed_during_verification_rejected(tmp_path, monkeypatch, target):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    original = resolution.verify_staged_member

    def change(*args, **kwargs):
        original(*args, **kwargs)
        (root / target).chmod(0o770 if (root / target).is_dir() else 0o620)

    monkeypatch.setattr(resolution, "verify_staged_member", change)
    _denied(store, pointer)


@pytest.mark.parametrize(
    "target", ["manifest.json", "README.md", "models/image_encoder/model.safetensors"]
)
def test_same_bytes_inode_replacement_during_verification_rejected(tmp_path, monkeypatch, target):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    original = resolution.verify_staged_member
    replaced = False

    def change(*args, **kwargs):
        nonlocal replaced
        original(*args, **kwargs)
        if not replaced:
            member = root / target
            candidate = tmp_path / "replacement"
            candidate.write_bytes(member.read_bytes())
            candidate.chmod(0o600)
            candidate.replace(member)
            replaced = True

    monkeypatch.setattr(resolution, "verify_staged_member", change)
    _denied(store, pointer)


def test_tree_closure_changed_after_reads_rejected(tmp_path, monkeypatch):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    original = resolution.verify_staged_member

    def change(*args, **kwargs):
        original(*args, **kwargs)
        (root / "sdxl_models" / ".extra").write_bytes(b"unused")

    monkeypatch.setattr(resolution, "verify_staged_member", change)
    _denied(store, pointer)


@pytest.mark.parametrize(
    "target", ["models", "models/image_encoder", "sdxl_models", "", "..", "../.."]
)
def test_directory_replaced_during_verification_rejected(tmp_path, monkeypatch, target):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    original = resolution.verify_staged_member
    replaced = False

    def change(*args, **kwargs):
        nonlocal replaced
        original(*args, **kwargs)
        if not replaced:
            directory = root / target
            directory.rename(tmp_path / "removed-directory")
            directory.mkdir(mode=0o700)
            replaced = True

    monkeypatch.setattr(resolution, "verify_staged_member", change)
    _denied(store, pointer)


@pytest.mark.parametrize(
    "target", ["manifest.json", "README.md", "models/image_encoder/model.safetensors"]
)
def test_mode_change_and_restore_during_read_rejected(tmp_path, monkeypatch, target):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    original = resolution.verify_staged_member

    def change(*args, **kwargs):
        original(*args, **kwargs)
        member = root / target
        member.chmod(0o620)
        member.chmod(0o600)

    monkeypatch.setattr(resolution, "verify_staged_member", change)
    _denied(store, pointer)


def test_other_revision_does_not_enter_closure_or_substitute_pinned_input(tmp_path, monkeypatch):
    store, root, manifest, pointer = _stage(tmp_path, monkeypatch)
    (root.parent / ("imgmodelrev_" + "0" * 32)).mkdir(mode=0o700)
    assert _resolve(store, pointer).manifest == manifest


def test_expected_owner_is_enforced(tmp_path, monkeypatch):
    store, _, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(ProviderError) as error:
        resolution.resolve_sdxl_ip_style_model(store, pointer, expected_owner_uid=os.getuid() + 1)
    assert error.value.code == "SDXL_PROBE_MODEL_INVALID"


def test_adapter_imports_no_tensor_backend_or_runtime_git():
    import ast

    tree = ast.parse(Path(resolution.__file__).read_text())
    modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not modules.intersection({"torch", "diffusers", "transformers", "git", "subprocess"})
