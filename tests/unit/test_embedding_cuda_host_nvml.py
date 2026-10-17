"""Strict NVML successor with synthetic file/ELF ports; never live GPU admission."""

from __future__ import annotations

import copy
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import (
    CUDA_HOST_NVML_MANIFEST_REF,
    CUDA_HOST_NVML_SCHEMA,
    CudaHostExtensionPointer,
    CudaHostExtensionPointerV11,
    CudaHostExtensionSnapshot,
    CudaHostExtensionSnapshotV11,
    cuda_host_extension_bytes,
    parse_cuda_host_extension_bytes,
    parse_cuda_host_extension_pointer,
    validate_cuda_host_extension_pointer,
)
from eom_catalog_contracts.embedding_cuda_installation_evidence import (
    validate_rootlocal_cuda_installation_metadata_references,
)
from eom_catalog_contracts.embedding_host_configuration import (
    host_configuration_snapshot_bytes,
    parse_host_configuration_snapshot,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalInstallationEvidenceError,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    parse_installed_embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service import embedding_cuda_host_capture as capture
from eom_catalog_service import embedding_cuda_host_publication as publication
from eom_catalog_service.embedding_runtime_files import InstalledRuntimeProofError
from eom_catalog_service.embedding_runtime_prefix_closure import (
    parse_installed_embedding_prefix_audit_input,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_embedding_cuda_host_capture import fixture as files_fixture
from tests.unit.test_embedding_cuda_host_closure import compose, ports
from tests.unit.test_embedding_cuda_host_extension import body, rehash
from tests.unit.test_embedding_cuda_host_publication import fixture as publication_fixture
from tests.unit.test_embedding_cuda_installation_evidence import metadata as installation_metadata
from tests.unit.test_embedding_cuda_installation_input import native, prefix_document
from tests.unit.test_embedding_host_configuration_contracts import snapshot_body
from tests.unit.test_embedding_host_configuration_files import _write
from tests.unit.test_embedding_runtime_host_closure import _cache

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def nvml_body():
    document = body()
    document["schema_version"] = "embedding-cuda-host-extension/1.1"
    document["libraries"].append(
        {
            "role": "CUDA_NVML",
            "member_name": "libnvidia-ml.so.1",
            "byte_count": 2283608,
            "sha256": "sha256:" + "7" * 64,
        }
    )
    return rehash(document)


def nvml_pointer(snapshot):
    raw = cuda_host_extension_bytes(snapshot)
    return CudaHostExtensionPointerV11(
        schema_ref=CUDA_HOST_NVML_MANIFEST_REF,
        configuration_id=snapshot.configuration_id,
        configuration_revision_id=snapshot.configuration_revision_id,
        manifest_byte_count=len(raw),
        manifest_raw_sha256=sha256_bytes(raw),
        snapshot_sha256=snapshot.snapshot_sha256,
    )


def test_schema_first_mirror_export_and_exact_raw_pointer_closure():
    schema = load_schema(CUDA_HOST_NVML_SCHEMA)
    Draft202012Validator.check_schema(schema)
    resource = CATALOG_SCHEMA_RESOURCES[CUDA_HOST_NVML_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    snapshot = CudaHostExtensionSnapshotV11.model_validate(nvml_body())
    pointer = nvml_pointer(snapshot)
    base = parse_host_configuration_snapshot(snapshot_body())
    assert (
        validate_cuda_host_extension_pointer(
            pointer,
            snapshot,
            cuda_host_extension_bytes(snapshot),
            base,
            host_configuration_snapshot_bytes(base),
        )
        == snapshot
    )
    assert parse_cuda_host_extension_bytes(cuda_host_extension_bytes(snapshot)) == snapshot
    assert parse_cuda_host_extension_pointer(pointer) == pointer
    import eom_catalog_contracts as public

    assert public.CudaHostExtensionSnapshotV11 is CudaHostExtensionSnapshotV11
    assert public.CudaHostExtensionPointerV11 is CudaHostExtensionPointerV11


def test_every_preexisting_registry_entry_and_schema_byte_is_preserved():
    previous = {
        name: asdict(value)
        for name, value in CATALOG_SCHEMA_RESOURCES.items()
        if name
        not in {
            CUDA_HOST_NVML_SCHEMA,
            "embedding-native-runtime-config-v1.3",
            "embedding-prefix-audit-input-v1.3",
        }
    }
    # Independently extracted from committed501ec6fa, not the edited registry.
    assert len(previous) == 329
    assert content_sha256(previous) == (
        "sha256:b7bb6abaa3dcccf8da91d3e462abee2b588a3b8858bc9c45cea790f9bb4cfd4d"
    )
    for name in previous:
        resource = CATALOG_SCHEMA_RESOURCES[name]
        raw = (ROOT / resource.canonical_path).read_bytes()
        assert sha256_bytes(raw) == resource.sha256
        assert (
            raw
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
            ).read_bytes()
        )


def test_neither_predecessor_type_nor_successor_accepts_another_format():
    snapshot = CudaHostExtensionSnapshotV11.model_validate(nvml_body())
    pointer = nvml_pointer(snapshot)
    with pytest.raises(ERRORS):
        CudaHostExtensionSnapshot.model_validate(snapshot.model_dump(mode="json"))
    with pytest.raises(ERRORS):
        CudaHostExtensionPointer.model_validate(pointer.model_dump(mode="json"))
    with pytest.raises(ERRORS):
        CudaHostExtensionSnapshotV11.model_validate(body())
    for reference in (capture.CUDA_HOST_SCHEMA_REF, capture.CUDA_HOST_NVML_SCHEMA_REF):
        selection = capture.CudaHostExtensionPin(
            reference,
            pointer.configuration_id,
            pointer.configuration_revision_id,
            pointer.manifest_byte_count,
            pointer.manifest_raw_sha256,
            pointer.snapshot_sha256,
        )
        if reference == capture.CUDA_HOST_SCHEMA_REF:
            with pytest.raises(capture.CudaHostExtensionError, match="POINTER_INVALID"):
                capture._manifest(cuda_host_extension_bytes(snapshot), selection)
        else:
            assert (
                len(capture._manifest(cuda_host_extension_bytes(snapshot), selection).libraries)
                == 7
            )


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "duplicate",
        "reordered",
        "wrong-role",
        "wrong-name",
        "oversize",
        "bool",
        "path",
    ),
)
def test_closed_ordered_seven_member_metadata_rejects_corruption(fault):
    changed = nvml_body()
    if fault == "missing":
        changed["libraries"].pop()
    elif fault == "duplicate":
        changed["libraries"].append(copy.deepcopy(changed["libraries"][-1]))
    elif fault == "reordered":
        changed["libraries"][0], changed["libraries"][-1] = (
            changed["libraries"][-1],
            changed["libraries"][0],
        )
    else:
        key, value = {
            "wrong-role": ("role", "NVML_PLUGIN"),
            "wrong-name": ("member_name", "/usr/lib/libnvidia-ml.so.1"),
            "oversize": ("byte_count", 8 * 1024**2 + 1),
            "bool": ("byte_count", True),
            "path": ("path", "/tmp/vendor.so"),
        }[fault]
        changed["libraries"][-1][key] = value
    with pytest.raises(ERRORS):
        CudaHostExtensionSnapshotV11.model_validate(rehash(changed))


def test_nvml_changes_seed_but_identity_does_not_and_unknown_version_is_rejected():
    original = CudaHostExtensionSnapshotV11.model_validate(nvml_body())
    changed = nvml_body()
    changed["configuration_revision_id"] = "embeddingcudahostrev_" + "9" * 32
    assert CudaHostExtensionSnapshotV11.model_validate(rehash(changed)).host_seed_sha256 == (
        original.host_seed_sha256
    )
    changed["libraries"][-1]["sha256"] = "sha256:" + "8" * 64
    assert CudaHostExtensionSnapshotV11.model_validate(rehash(changed)).host_seed_sha256 != (
        original.host_seed_sha256
    )
    raw = cuda_host_extension_bytes(original)
    with pytest.raises(ERRORS):
        parse_cuda_host_extension_bytes(b" " + raw)
    with pytest.raises(ERRORS):
        parse_cuda_host_extension_bytes(raw.replace(b"/1.1", b"/1.2", 1))
    with pytest.raises(capture.CudaHostExtensionError, match="POINTER_INVALID"):
        capture.cuda_host_library_recipe(CUDA_HOST_NVML_MANIFEST_REF.replace("/1.1", "/1.2"))


def test_explicit_nvml_pointer_cannot_be_relabelled_as_predecessor_or_latest():
    snapshot = CudaHostExtensionSnapshotV11.model_validate(nvml_body())
    pointer = nvml_pointer(snapshot)
    with pytest.raises(capture.CudaHostExtensionError, match="POINTER_INVALID"):
        capture.parse_cuda_host_extension_pin(pointer.model_dump(mode="json"))
    assert (
        capture.parse_cuda_host_extension_pin(
            pointer.model_dump(mode="json"),
            expected_schema_ref=CUDA_HOST_NVML_MANIFEST_REF,
        ).schema_ref
        == CUDA_HOST_NVML_MANIFEST_REF
    )
    relabelled = CudaHostExtensionPointer.model_validate(
        pointer.model_dump(mode="json") | {"schema_ref": capture.CUDA_HOST_SCHEMA_REF}
    )
    base = parse_host_configuration_snapshot(snapshot_body())
    with pytest.raises(ValueError, match="closure differs"):
        validate_cuda_host_extension_pointer(
            relabelled,
            snapshot,
            cuda_host_extension_bytes(snapshot),
            base,
            host_configuration_snapshot_bytes(base),
        )
    raw = cuda_host_extension_bytes(snapshot)
    duplicate = raw.replace(
        b'"schema_version":"embedding-cuda-host-extension/1.1"',
        b'"schema_version":"embedding-cuda-host-extension/1.1",'
        b'"schema_version":"embedding-cuda-host-extension/1.1"',
    )
    with pytest.raises(ERRORS):
        parse_cuda_host_extension_bytes(duplicate)
    forged_nvml = snapshot.libraries[-1].model_copy(update={"byte_count": True})
    with pytest.raises(ERRORS):
        cuda_host_extension_bytes(
            snapshot.model_copy(update={"libraries": (*snapshot.libraries[:-1], forged_nvml)})
        )


def test_old_runtime_config_prefix_input_and_receipt_remain_closed(tmp_path, monkeypatch):
    snapshot = CudaHostExtensionSnapshotV11.model_validate(nvml_body())
    pointer = nvml_pointer(snapshot)
    config, _bundle, _proof = native()
    document = config.model_dump(mode="json")
    document["cuda_host_extension"] = pointer.model_dump(mode="json")
    document["config_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "config_sha256"}
    )
    with pytest.raises(ERRORS):
        parse_installed_embedding_native_runtime_config_bytes(canonical_json_bytes(document))
    document = prefix_document(tmp_path, monkeypatch)
    document["cuda_host_extension"] = pointer.model_dump(mode="json")
    document["host_seed_sha256"] = snapshot.host_seed_sha256
    with pytest.raises(ValueError):
        parse_installed_embedding_prefix_audit_input(canonical_json_bytes(document))
    case = installation_metadata()
    case.update(host_snapshot=snapshot, host_snapshot_raw=cuda_host_extension_bytes(snapshot))
    with pytest.raises(RootLocalInstallationEvidenceError):
        validate_rootlocal_cuda_installation_metadata_references(**case)


def test_synthetic_public_and_stdlib_file_resolution_checks_the_same_seven_members(
    tmp_path, monkeypatch
):
    value = files_fixture(tmp_path, monkeypatch, schema_ref=capture.CUDA_HOST_NVML_SCHEMA_REF)
    selected = value.resolve()
    assert isinstance(selected.snapshot, CudaHostExtensionSnapshotV11)
    assert len(selected.captured.libraries) == len(value.libraries) == 7
    assert selected.captured.selection.schema_ref == CUDA_HOST_NVML_MANIFEST_REF
    selected.assert_unchanged()
    with pytest.raises(capture.CudaHostExtensionError, match="CACHE_ROUTE_INVALID"):
        capture.validate_cuda_host_loader_cache(value.cache.read_bytes(), value.manifest.parent)
    capture.validate_cuda_host_loader_cache(
        value.cache.read_bytes(),
        value.manifest.parent,
        schema_ref=CUDA_HOST_NVML_MANIFEST_REF,
    )


@pytest.mark.parametrize("fault", ("missing", "hash", "symlink", "additional-member"))
def test_nvml_file_identity_and_closed_namespace_fail_explicitly(tmp_path, monkeypatch, fault):
    value = files_fixture(tmp_path, monkeypatch, schema_ref=capture.CUDA_HOST_NVML_SCHEMA_REF)
    member = value.libraries[-1]
    if fault == "missing":
        member.unlink()
    elif fault == "hash":
        _write(member, b"changed bytes")
    elif fault == "symlink":
        member.unlink()
        member.symlink_to(value.libraries[0])
    else:
        _write(member.parent / "undeclared.so.1", b"extra")
    with pytest.raises(capture.CudaHostExtensionError):
        value.resolve()


def test_nvml_cache_route_cannot_resolve_the_system_library(tmp_path, monkeypatch):
    value = files_fixture(tmp_path, monkeypatch, schema_ref=capture.CUDA_HOST_NVML_SCHEMA_REF)
    document = parse_cuda_host_extension_bytes(value.manifest.read_bytes()).model_dump(mode="json")
    raw = _cache(
        tuple(
            (
                entry.name,
                "/usr/lib/libnvidia-ml.so.1" if entry.name == "libnvidia-ml.so.1" else entry.path,
                entry.abi,
                entry.osversion,
                entry.hardware,
            )
            for entry in capture.read_embedding_loader_cache_entries(value.cache.read_bytes())
        )
    )
    _write(value.cache, raw)
    document["loader_cache"].update(byte_count=len(raw), sha256=sha256_bytes(raw))
    value.repin(document)
    with pytest.raises(capture.CudaHostExtensionError, match="CACHE_ROUTE_INVALID"):
        value.resolve()


def test_seven_library_elf_and_fd_closure_accepts_only_captured_nvml_not_system_fallback(
    tmp_path, monkeypatch
):
    value, selected, witness, base, _ = ports(
        tmp_path,
        monkeypatch,
        schema_ref=capture.CUDA_HOST_NVML_SCHEMA_REF,
    )
    with compose(selected, witness) as combined:
        assert len(base.descriptors) == 7
        nvml = value.libraries[-1]
        epoch = nvml.stat()
        combined.assert_mapped_file(nvml, device=epoch.st_dev, inode=epoch.st_ino)
        with pytest.raises(InstalledRuntimeProofError, match="MAPPED_FILE_UNAVAILABLE"):
            combined.assert_mapped_file(
                Path("/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.580.126.09"),
                device=epoch.st_dev,
                inode=epoch.st_ino,
            )
        with pytest.raises(InstalledRuntimeProofError, match="MAPPED_FILE_UNAVAILABLE"):
            combined.assert_mapped_file(nvml, device=epoch.st_dev, inode=epoch.st_ino + 1)
    assert base.closed


def test_nine_member_publication_and_idempotent_reuse_preserve_exact_version(tmp_path, monkeypatch):
    request, root, _sources, generated = publication_fixture(
        tmp_path,
        monkeypatch,
        schema_ref=capture.CUDA_HOST_NVML_SCHEMA_REF,
    )
    created = publication.publish_cuda_host_extension(request)
    assert created.disposition == "CREATED" and len(generated) == 1
    final = root / request.configuration_id / request.configuration_revision_id
    raw = (final / "snapshot.json").read_bytes()
    assert len(tuple(final.iterdir())) == 9
    assert isinstance(parse_cuda_host_extension_bytes(raw), CudaHostExtensionSnapshotV11)
    assert publication.publish_cuda_host_extension(request).pointer == created.pointer
    assert len(generated) == 1 and (final / "snapshot.json").read_bytes() == raw
    with pytest.raises(capture.CudaHostExtensionError, match="POINTER_INVALID"):
        publication.publish_cuda_host_extension(
            replace(request, schema_ref=capture.CUDA_HOST_SCHEMA_REF)
        )
    assert (final / "snapshot.json").read_bytes() == raw
