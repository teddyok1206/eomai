from __future__ import annotations

import importlib
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from shutil import copytree

import pytest
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    embedding_runtime_bundle_bytes,
)
from eom_catalog_service.embedding_bundle_resolver import (
    EmbeddingBundleResolutionError,
    ResolvedEmbeddingBundle,
    resolve_configured_embedding_bundle,
    validate_resolved_embedding_bundle,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.local_embedding_adapter import verify_local_embedding_model_snapshot
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_native_backend_fixtures import (
    configured_bundle,
    stage_protected_numeric_origins,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_runtime_bundle_contracts import _pointer


@pytest.fixture(autouse=True)
def protected_numeric_origins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stage_protected_numeric_origins(tmp_path, monkeypatch)


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_successor_resolves_one_original_payload_without_ml_import_or_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: str
) -> None:
    configured, bundle, model_root, _manifest = configured_bundle(tmp_path, device)  # type: ignore[arg-type]
    before = {
        path: (path.stat().st_ino, path.read_bytes())
        for path in model_root.iterdir()
        if path.is_file()
    }
    monkeypatch.setattr(importlib, "import_module", lambda *_a, **_k: pytest.fail("no ML import"))
    resolved = resolve_configured_embedding_bundle(configured)
    assert resolved.bundle == bundle
    assert resolved.payload.root == model_root
    assert resolved.payload.model_spec == bundle.payload_model_spec
    assert resolved.bundle.execution_model_spec != resolved.payload.model_spec
    assert not (model_root.parent / bundle.execution_model_spec.model_revision_id).exists()
    assert before == {
        path: (path.stat().st_ino, path.read_bytes())
        for path in model_root.iterdir()
        if path.is_file()
    }
    assert (
        verify_local_embedding_model_snapshot(
            configured.payload_store_root,
            bundle.payload_model_spec,
            expected_owner_uid=os.geteuid(),
        )
        == bundle.payload_model_spec
    )
    resolved.assert_unchanged()


@pytest.mark.parametrize(
    "fault",
    ["missing", "hash", "raw_newline", "symlink", "hardlink", "write_mode", "stale", "schema"],
)
def test_bundle_faults_fail_exact_resolution(tmp_path: Path, fault: str) -> None:
    configured, bundle, _root, manifest = configured_bundle(tmp_path)
    if fault == "missing":
        manifest.unlink()
    elif fault == "hash":
        manifest.write_bytes(
            embedding_runtime_bundle_bytes(bundle).replace(b"synthetic-cpu", b"different-cpu")
        )
    elif fault == "raw_newline":
        manifest.write_bytes(manifest.read_bytes() + b"\n")
    elif fault == "symlink":
        source = manifest.with_name("actual.json")
        manifest.rename(source)
        manifest.symlink_to(source)
    elif fault == "hardlink":
        os.link(manifest, manifest.with_name("other.json"))
    elif fault == "write_mode":
        manifest.chmod(0o660)
    elif fault == "schema":
        manifest.write_bytes(
            manifest.read_bytes().replace(
                b"embedding-runtime-bundle/1.0", b"embedding-runtime-bundle/9.0"
            )
        )
    else:
        configured = replace(
            configured,
            pointer=configured.pointer.model_copy(
                update={"bundle_revision_id": "embeddingbundlerev_" + "f" * 32}
            ),
        )
    with pytest.raises(EmbeddingBundleResolutionError):
        resolve_configured_embedding_bundle(configured)


@pytest.mark.parametrize(
    "fault", ["missing", "stale", "hash", "symlink", "hardlink", "write_mode", "raw_manifest"]
)
def test_legacy_payload_faults_stay_fail_closed(tmp_path: Path, fault: str) -> None:
    configured, _bundle, root, _manifest = configured_bundle(tmp_path)
    weight = root / "model.safetensors"
    if fault == "missing":
        weight.unlink()
    elif fault == "stale":
        root.rename(root.with_name("embeddingmodelrev_" + "f" * 32))
    elif fault == "hash":
        weight.write_bytes(b"x" * weight.stat().st_size)
    elif fault == "symlink":
        weight.unlink()
        weight.symlink_to(root / "tokenizer.json")
    elif fault == "hardlink":
        os.link(weight, root / "duplicate.safetensors")
    elif fault == "write_mode":
        weight.chmod(0o660)
    else:
        path = root / "manifest.json"
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(EmbeddingBundleResolutionError):
        resolve_configured_embedding_bundle(configured)


def test_pinned_legacy_newline_flavor_is_accepted_without_rewriting(tmp_path: Path) -> None:
    configured, bundle, root, manifest = configured_bundle(tmp_path)
    raw = canonical_json_bytes(bundle.payload_model_spec.model_dump(mode="json")) + b"\n"
    (root / "manifest.json").write_bytes(raw)
    body = bundle.model_dump(mode="json")
    body["payload_pointer"]["manifest_raw_sha256"] = sha256_bytes(raw)
    bundle = EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
    manifest.write_bytes(embedding_runtime_bundle_bytes(bundle))
    configured = replace(configured, pointer=_pointer(bundle))
    assert resolve_configured_embedding_bundle(configured).payload.manifest.raw == raw
    assert (root / "manifest.json").read_bytes() == raw


@pytest.mark.parametrize("target", ["bundle", "payload", "ancestor"])
def test_resolved_snapshot_detects_file_and_path_replacement(tmp_path: Path, target: str) -> None:
    configured, _bundle, root, manifest = configured_bundle(tmp_path)
    resolved = resolve_configured_embedding_bundle(configured)
    if target == "ancestor":
        moved = configured.payload_store_root.with_name("moved-payloads")
        configured.payload_store_root.rename(moved)
        configured.payload_store_root.symlink_to(moved, target_is_directory=True)
    else:
        path = manifest if target == "bundle" else root / "model.safetensors"
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(path)
    with pytest.raises(EmbeddingBundleResolutionError, match="BUNDLE_CHANGED"):
        resolved.assert_unchanged()


@pytest.mark.parametrize(
    "fault",
    ("forged", "payload", "manifest", "empty_epochs", "bundle", "root", "pointer", "deepcopy"),
)
def test_reuse_requires_original_audited_objects_and_exact_configured_closure(
    tmp_path: Path, fault: str
) -> None:
    configured, _, _, _ = configured_bundle(tmp_path)
    original = resolve_configured_embedding_bundle(configured)
    if fault == "forged":
        resolved = ResolvedEmbeddingBundle(original.bundle, original.payload, original.manifest)
    elif fault == "payload":
        resolved = replace(original, payload=replace(original.payload))
    elif fault == "manifest":
        resolved = replace(original, manifest=replace(original.manifest))
    elif fault == "empty_epochs":
        resolved = replace(original, payload=replace(original.payload, _epochs=()))
    elif fault == "bundle":
        resolved = replace(original, bundle=original.bundle.model_copy())
    elif fault == "deepcopy":
        resolved = deepcopy(original)
    else:
        resolved = original
        if fault == "root":
            configured = replace(configured, payload_store_root=tmp_path / "other")
        else:
            configured = replace(
                configured,
                pointer=configured.pointer.model_copy(
                    update={"bundle_raw_sha256": "sha256:" + "0" * 64}
                ),
            )
    with pytest.raises(EmbeddingBundleResolutionError):
        validate_resolved_embedding_bundle(configured, resolved)


def test_unchanged_copy_can_reuse_same_original_objects_without_payload_byte_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, _, _, _ = configured_bundle(tmp_path)
    original = resolve_configured_embedding_bundle(configured)
    import eom_catalog_service.local_embedding_adapter as legacy

    monkeypatch.setattr(
        legacy,
        "resolve_local_embedding_payload",
        lambda *_args, **_kwargs: pytest.fail("no repeated payload hash"),
    )
    validate_resolved_embedding_bundle(configured, replace(original))


@pytest.mark.parametrize("fault", ("manifest", "ancestor"))
def test_identity_observation_precedes_payload_audit_and_detects_fresh_resolution_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, root, bundle_path = configured_bundle(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    expected = (
        bundle_path,
        root / "manifest.json",
        *(root / pin.member_path for pin in bundle.payload_model_spec.files),
    )
    observed: list[Path] = []

    def observe(path: Path) -> None:
        files.observe_protected_member_identity(path)
        observed.append(path)
        if path == expected[-1]:
            if fault == "manifest":
                replacement = root / "replacement"
                replacement.write_bytes((root / "manifest.json").read_bytes())
                replacement.chmod(0o600)
                replacement.replace(root / "manifest.json")
            else:
                moved = configured.payload_store_root.with_name("original-payload-evidence")
                configured.payload_store_root.rename(moved)
                # Only tiny synthetic fixture bytes are copied at this test race boundary.
                copytree(moved, configured.payload_store_root)

    monkeypatch.setattr(
        importlib, "import_module", lambda *_args, **_kwargs: pytest.fail("no ML import")
    )
    resolved = resolve_configured_embedding_bundle(configured, observe_member_identity=observe)
    assert tuple(observed) == expected
    resolved.assert_unchanged()  # Legacy leaf epochs captured after the race are insufficient.
    with pytest.raises(ValueError):
        files.assert_unchanged()


def test_execution_successor_cannot_be_passed_to_legacy_exact_resolver(tmp_path: Path) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    with pytest.raises(ValueError):
        verify_local_embedding_model_snapshot(
            configured.payload_store_root,
            bundle.execution_model_spec,
            expected_owner_uid=os.geteuid(),
        )
