"""Tiny local fixtures exercise resolution, not actual model or visual acceptance."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import FrozenInstanceError
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

    monkeypatch.setattr(resolution, "open_verified_directory", forbidden)
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
            directory = (root / target).resolve()
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


def _open_load_inputs(store, pointer):
    return resolution.open_sdxl_ip_style_load_inputs(store, pointer, expected_owner_uid=os.getuid())


def _assert_closed(inputs):
    for fd in (inputs.encoder_weights_fd, inputs.adapter_weights_fd):
        with pytest.raises(OSError):
            os.fstat(fd)


def test_load_inputs_keep_verified_readonly_inode_open_then_close_without_second_hash(
    tmp_path, monkeypatch
):
    store, root, manifest, pointer = _stage(tmp_path, monkeypatch)
    streams = []
    verify = resolution.verify_staged_member

    def observe(*args, **kwargs):
        streams.append(args[1])
        return verify(*args, **kwargs)

    monkeypatch.setattr(resolution, "verify_staged_member", observe)
    with _open_load_inputs(store, pointer) as inputs:
        assert inputs.manifest == manifest
        assert inputs.encoder_config == _payloads()["models/image_encoder/config.json"]
        for fd, name in (
            (inputs.encoder_weights_fd, "models/image_encoder/model.safetensors"),
            (inputs.adapter_weights_fd, "sdxl_models/ip-adapter_sdxl_vit-h.safetensors"),
        ):
            opened, current = os.fstat(fd), (root / name).stat()
            assert (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
            assert os.pread(fd, current.st_size, 0) == _payloads()[name]
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            assert flags & os.O_ACCMODE == os.O_RDONLY and flags & os.O_NONBLOCK
            assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
            with pytest.raises(OSError):
                os.write(fd, b"x")
        with pytest.raises(FrozenInstanceError):
            inputs.encoder_weights_fd = 99
        assert streams == ["model.safetensors", "ip-adapter_sdxl_vit-h.safetensors"]
    _assert_closed(inputs)
    assert streams == ["model.safetensors", "ip-adapter_sdxl_vit-h.safetensors"]


@pytest.mark.parametrize("member", (*_payloads(), "manifest.json"))
@pytest.mark.parametrize("fault", ["replace", "modify", "mode-restore", "delete"])
def test_successful_body_cannot_escape_member_mutation_during_model_open(
    tmp_path, monkeypatch, member, fault
):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(ProviderError) as caught, _open_load_inputs(store, pointer) as inputs:
        target = root / member
        if fault == "replace":
            candidate = tmp_path / "replacement"
            candidate.write_bytes(target.read_bytes())
            candidate.chmod(0o600)
            candidate.replace(target)
            # Loader reads the same held inode, not the replacement path.
            if member.endswith("model.safetensors"):
                assert os.pread(inputs.encoder_weights_fd, 128, 0) == _payloads()[member]
        elif fault == "modify":
            raw = target.read_bytes()
            target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        elif fault == "mode-restore":
            target.chmod(0o620)
            target.chmod(0o600)
        else:
            target.unlink()
    assert caught.value.code == "SDXL_PROBE_MODEL_INVALID"
    _assert_closed(inputs)


@pytest.mark.parametrize(
    "directory", ["", "models", "models/image_encoder", "sdxl_models", "..", "../.."]
)
@pytest.mark.parametrize("fault", ["replace", "writable"])
def test_successful_body_cannot_escape_directory_mutation(tmp_path, monkeypatch, directory, fault):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(ProviderError) as caught, _open_load_inputs(store, pointer) as inputs:
        target = (root / directory).resolve()
        if fault == "replace":
            target.rename(tmp_path / "removed-tree")
            target.mkdir(mode=0o700)
        else:
            target.chmod(0o770)
    assert caught.value.code == "SDXL_PROBE_MODEL_INVALID"
    _assert_closed(inputs)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("consumer"),
        ValueError("consumer"),
        OSError("consumer"),
        ProviderError("SDXL_PROBE_OOM"),
        KeyboardInterrupt(),
    ],
)
def test_consumer_failure_not_reclassified_and_all_handles_closed(tmp_path, monkeypatch, error):
    store, _, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(type(error)) as caught, _open_load_inputs(store, pointer) as inputs:
        raise error
    assert caught.value is error
    _assert_closed(inputs)


def test_changed_model_does_not_hide_behind_a_consumer_failure(tmp_path, monkeypatch):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(ProviderError) as caught, _open_load_inputs(store, pointer) as inputs:
        (root / "models/image_encoder/model.safetensors").chmod(0o620)
        raise ProviderError("SDXL_PROBE_OOM")
    assert caught.value.code == "SDXL_PROBE_MODEL_INVALID"
    _assert_closed(inputs)


def test_tree_closure_change_during_load_fails(tmp_path, monkeypatch):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(ProviderError), _open_load_inputs(store, pointer) as inputs:
        (root / "sdxl_models/extra.bin").write_bytes(b"untrusted")
    _assert_closed(inputs)


def test_fifo_open_race_is_nonblocking_and_cannot_leak_handles(tmp_path, monkeypatch):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    original_open = os.open
    opened = []

    def change_before_handoff_open(name, flags, *args, **kwargs):
        if name == "model.safetensors" and flags & os.O_NONBLOCK:
            target = root / "models/image_encoder/model.safetensors"
            target.unlink()
            os.mkfifo(target, 0o600)
            fd = original_open(name, flags, *args, **kwargs)
            opened.append(fd)
            return fd
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(resolution.os, "open", change_before_handoff_open)
    with pytest.raises(ProviderError) as caught, _open_load_inputs(store, pointer):
        pytest.fail("FIFO handoff admitted")
    assert caught.value.code == "SDXL_PROBE_MODEL_INVALID" and len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


@pytest.mark.parametrize("attribute", ["encoder_weights_fd", "adapter_weights_fd"])
def test_premature_handle_close_rejects_scope_and_closes_remaining_handles(
    tmp_path, monkeypatch, attribute
):
    store, _, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(ProviderError) as caught, _open_load_inputs(store, pointer) as inputs:
        os.close(getattr(inputs, attribute))
    assert caught.value.code == "SDXL_PROBE_MODEL_INVALID"
    _assert_closed(inputs)


@pytest.mark.parametrize("fault", ["manifest", "extra", "directory", "revision"])
def test_changed_metadata_or_namespace_checked_even_on_consumer_failure(
    tmp_path, monkeypatch, fault
):
    store, root, _, pointer = _stage(tmp_path, monkeypatch)
    with pytest.raises(ProviderError) as caught, _open_load_inputs(store, pointer) as inputs:
        if fault == "manifest":
            (root / "manifest.json").chmod(0o620)
        elif fault == "extra":
            (root / "sdxl_models/extra.bin").write_bytes(b"untrusted")
        elif fault == "directory":
            (root / "models").chmod(0o770)
        else:
            root.rename(tmp_path / "removed-revision")
            root.mkdir(mode=0o700)
        raise OSError("numerical consumer failure")
    assert caught.value.code == "SDXL_PROBE_MODEL_INVALID"
    _assert_closed(inputs)
