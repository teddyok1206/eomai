"""Synthetic publication/cache-unit ports; no sudo, root acceptance, model or GPU use."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import parse_cuda_host_extension_bytes
from eom_catalog_service import embedding_cuda_host_capture as capture
from eom_catalog_service import embedding_cuda_host_publication as publication
from eom_catalog_service import embedding_host_configuration_capture as base_capture
from eom_catalog_service import embedding_runtime_host_closure as host

from tests.unit.test_embedding_host_configuration_files import _fixture, _write
from tests.unit.test_embedding_host_requalification import successor
from tests.unit.test_embedding_runtime_host_closure import _cache


def fixture(tmp_path, monkeypatch, *, schema_ref=capture.CUDA_HOST_SCHEMA_REF, reviewed=False):
    recipe = capture.cuda_host_library_recipe(schema_ref)
    base = _fixture(tmp_path / "base", monkeypatch)
    if reviewed:
        base = successor(base)
    root = tmp_path / "published"
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    specs = {}
    for role, _name, _maximum in recipe.libraries:
        path = source / (role + ".so")
        raw = b"source-is-not-executable:" + role.encode()
        _write(path, raw)
        specs[role] = (path.name, len(raw), hashlib.sha256(raw).hexdigest())
    tool = source / "inert-tool"
    _write(tool, b"inert, never executed")
    monkeypatch.setattr(publication, "_ROOT_UID", os.geteuid())
    monkeypatch.setattr(publication, "_ROOT", root)
    monkeypatch.setattr(publication, "_LOCK", tmp_path / "publication.lock")
    monkeypatch.setattr(publication, "_SYSTEM_LIBRARIES", source)
    monkeypatch.setattr(publication, "_require_cache_unit_quiescent", lambda: None)
    monkeypatch.setattr(publication, "_SOURCES", specs)
    monkeypatch.setattr(
        publication,
        "_TOOL",
        (tool, tool.stat().st_size, hashlib.sha256(tool.read_bytes()).hexdigest()),
    )
    monkeypatch.setattr(capture, "_ROOT", root)
    monkeypatch.setattr(
        capture,
        "NumericalRuntimeFileSnapshots",
        lambda _: publication.NumericalRuntimeFileSnapshots(os.geteuid()),
    )
    generated = []

    def generate(workspace, final, stage, cpu_files, *, base_configuration, schema_ref):
        assert capture.cuda_host_library_recipe(schema_ref) == recipe
        assert base_configuration.selection == base_capture.parse_host_configuration_snapshot_pin(
            base.pointer.model_dump(mode="json")
        )
        generated.append(workspace)
        assert len(tuple(stage.iterdir())) == len(recipe.libraries)
        assert all(p.stat().st_mode & 0o777 == 0o444 for p in stage.iterdir())
        return _cache(
            tuple(
                (name, path, 0x303, 0, 0)
                for name, path in (
                    *host.embedding_host_loader_cache_routes(),
                    *((name, str(final / name)) for _role, name, _maximum in recipe.libraries),
                )
            )
        )

    monkeypatch.setattr(publication, "_generate_cache", generate)
    request = publication.CudaHostPublicationRequest(
        "embeddingcudahost_" + "1" * 32,
        "embeddingcudahostrev_" + "2" * 32,
        base_capture.parse_host_configuration_snapshot_pin(base.pointer.model_dump(mode="json")),
        source / "RDMACM.so",
        schema_ref,
    )
    return request, root, source, generated


def test_atomic_eight_member_publication_and_exact_idempotent_reuse(tmp_path, monkeypatch):
    request, root, source, generated = fixture(tmp_path, monkeypatch)
    created = publication.publish_cuda_host_extension(request)
    assert created.disposition == "CREATED" and len(generated) == 1
    final = root / request.configuration_id / request.configuration_revision_id
    raw = (final / "snapshot.json").read_bytes()
    snapshot = parse_cuda_host_extension_bytes(raw)
    assert len(tuple(final.iterdir())) == 8 and final.stat().st_mode & 0o777 == 0o555
    assert root.stat().st_mode & 0o777 == 0o755 and final.parent.stat().st_mode & 0o777 == 0o755
    assert (
        snapshot.base_configuration.configuration_revision_id
        == request.base_configuration.configuration_revision_id
    )
    (source / "RDMACM.so").unlink()
    reused = publication.publish_cuda_host_extension(request)
    assert (
        reused.disposition == "REUSED" and reused.pointer == created.pointer and len(generated) == 1
    )
    assert (final / "snapshot.json").read_bytes() == raw


def test_publication_applies_explicit_modes_under_protected_owner_umask(tmp_path, monkeypatch):
    request, root, _source, generated = fixture(tmp_path, monkeypatch)
    previous = os.umask(0o077)
    try:
        result = publication.publish_cuda_host_extension(request)
    finally:
        os.umask(previous)
    assert result.disposition == "CREATED" and len(generated) == 1
    assert root.stat().st_mode & 0o777 == 0o755
    assert (root / request.configuration_id).stat().st_mode & 0o777 == 0o755
    assert (root / ".publication").stat().st_mode & 0o777 == 0o700


def test_existing_narrow_directory_is_not_repaired_by_creation_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "_ROOT_UID", os.geteuid())
    existing = tmp_path / "prior-incomplete-directory"
    existing.mkdir(mode=0o700)
    with pytest.raises(publication.CudaHostPublicationError, match="DIRECTORY_MODE_INVALID"):
        publication._mkdir(existing)
    assert existing.stat().st_mode & 0o777 == 0o700


def test_source_mismatch_preserves_failed_workspace_and_never_replays_same_revision(
    tmp_path, monkeypatch
):
    request, root, source, generated = fixture(tmp_path, monkeypatch)
    _write(source / "CUDA_DRIVER.so", b"corrupt")
    with pytest.raises(publication.CudaHostPublicationError, match="SOURCE_SIZE_INVALID"):
        publication.publish_cuda_host_extension(request)
    workspace = root / ".publication" / request.configuration_id / request.configuration_revision_id
    assert (
        workspace.is_dir()
        and not (root / request.configuration_id / request.configuration_revision_id).exists()
    )
    assert generated == []
    with pytest.raises(
        publication.CudaHostPublicationError, match="PREVIOUS_OPERATION_REQUIRES_RECONCILIATION"
    ):
        publication.publish_cuda_host_extension(request)


def test_changed_recipe_cannot_reuse_existing_immutable_revision(tmp_path, monkeypatch):
    request, _root, _source, generated = fixture(tmp_path, monkeypatch)
    publication.publish_cuda_host_extension(request)
    specs = dict(publication._SOURCES)
    path, size, _sha = specs["CUDA_DRIVER"]
    specs["CUDA_DRIVER"] = (path, size, "0" * 64)
    monkeypatch.setattr(publication, "_SOURCES", specs)
    with pytest.raises(publication.CudaHostPublicationError, match="EXISTING_REVISION_CONFLICT"):
        publication.publish_cuda_host_extension(request)
    assert len(generated) == 1


@pytest.mark.parametrize("error", ("CACHE_UNIT_FAILED", "UNIT_OUTCOME_UNKNOWN"))
def test_cache_unit_failure_or_unknown_outcome_does_not_publish_or_retry(
    tmp_path, monkeypatch, error
):
    request, root, _source, _generated = fixture(tmp_path, monkeypatch)
    calls = []

    def failed(*args, **kwargs):
        calls.append(True)
        raise publication.CudaHostPublicationError("CUDA_HOST_PUBLICATION_" + error)

    monkeypatch.setattr(publication, "_generate_cache", failed)
    with pytest.raises(publication.CudaHostPublicationError, match=error):
        publication.publish_cuda_host_extension(request)
    assert not (root / request.configuration_id / request.configuration_revision_id).exists()
    with pytest.raises(publication.CudaHostPublicationError, match="RECONCILIATION"):
        publication.publish_cuda_host_extension(request)
    assert calls == [True]


def test_same_existing_publication_lock_blocks_second_owner_without_a_new_queue(
    tmp_path, monkeypatch
):
    request, _root, _source, generated = fixture(tmp_path, monkeypatch)
    fd = os.open(publication._LOCK, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(publication.CudaHostPublicationError, match="BUSY"):
            publication.publish_cuda_host_extension(request)
        assert generated == []
    finally:
        os.close(fd)


@pytest.mark.parametrize("fault", ("link", "hardlink", "mode"))
def test_unsafe_publication_lock_is_rejected_before_source_work(tmp_path, monkeypatch, fault):
    request, _root, _source, generated = fixture(tmp_path, monkeypatch)
    if fault == "link":
        publication._LOCK.symlink_to(tmp_path / "other")
    else:
        _write(publication._LOCK, b"")
        if fault == "hardlink":
            (tmp_path / "other").hardlink_to(publication._LOCK)
    with pytest.raises((publication.CudaHostPublicationError, OSError)):
        publication.publish_cuda_host_extension(request)
    assert generated == []


def test_cache_command_cannot_touch_global_loader_cache_or_execute_candidate(tmp_path, monkeypatch):
    # Explicit synthetic ownership port, never production root acceptance.
    monkeypatch.setattr(publication, "_ROOT_UID", os.geteuid())
    workspace = tmp_path / "work"
    workspace.mkdir(mode=0o700)
    final = (
        Path("/opt/eom/embedding-cuda-host-extensions")
        / ("embeddingcudahost_" + "1" * 32)
        / ("embeddingcudahostrev_" + "2" * 32)
    )
    command = publication._prepare_cache_command(
        workspace, final, ((tmp_path / "input.so", final / "libcuda.so.1"),)
    )
    assert command[0] == "/usr/bin/systemd-run"
    assert "--property=PrivateMounts=yes" in command and "--property=PrivateDevices=yes" in command
    assert "--property=CapabilityBoundingSet=CAP_SYS_CHROOT" in command
    assert command[-11:] == (
        str(workspace / "ldconfig.real"),
        "-r",
        str(workspace / "build"),
        "-C",
        "/etc/ld.so.cache",
        "-f",
        "/etc/ld.so.conf",
        "-X",
        "-i",
        "-c",
        "new",
    )
    assert "-N" not in command and "-n" not in command
    assert not any("embedding-cuda/bin/python" in word for word in command)


def test_developer_interpreter_cannot_run_protected_owner_entry(capsys):
    assert publication.main([]) == 1
    assert "PROTECTED_OWNER_REQUIRED" in capsys.readouterr().err


def test_unsealed_existing_revision_is_not_implicitly_repaired(tmp_path, monkeypatch):
    request, root, _source, _generated = fixture(tmp_path, monkeypatch)
    publication.publish_cuda_host_extension(request)
    final = root / request.configuration_id / request.configuration_revision_id
    final.chmod(0o700)
    with pytest.raises(publication.CudaHostPublicationError, match="INCOMPLETE"):
        publication.publish_cuda_host_extension(request)
    assert final.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("fault", ("hash", "link", "hardlink"))
def test_source_identity_rejection_keeps_original_input_ownership(tmp_path, monkeypatch, fault):
    request, _root, source, generated = fixture(tmp_path, monkeypatch)
    target = source / "CUDA_DRIVER.so"
    uid = target.stat().st_uid
    if fault == "hash":
        raw = target.read_bytes()
        _write(target, b"x" + raw[1:])
    elif fault == "link":
        target.rename(target.with_name("retained"))
        target.symlink_to("retained")
    else:
        (source / "second-link").hardlink_to(target)
    with pytest.raises(ValueError):
        publication.publish_cuda_host_extension(request)
    assert target.stat().st_uid == uid and generated == []


@pytest.mark.parametrize("state", ("ready", "active", "loaded", "pid", "duplicate", "timeout"))
def test_unit_quiescence_is_authoritative_and_never_resets_or_restarts(state, monkeypatch):
    calls = []
    raw = "LoadState=not-found\nActiveState=inactive\nMainPID=0\nControlPID=0\n"
    if state == "active":
        raw = raw.replace("inactive", "active")
    elif state == "loaded":
        raw = raw.replace("not-found", "loaded")
    elif state == "pid":
        raw = raw.replace("MainPID=0", "MainPID=42")
    elif state == "duplicate":
        raw += "MainPID=0\n"

    def run(command, **kwargs):
        calls.append(command)
        assert command[:3] == ("/usr/bin/systemctl", "show", publication._UNIT)
        if state == "timeout":
            raise subprocess.TimeoutExpired(command, 5)
        return SimpleNamespace(returncode=0, stdout=raw, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    if state == "ready":
        publication._require_cache_unit_quiescent()
    else:
        with pytest.raises(publication.CudaHostPublicationError):
            publication._require_cache_unit_quiescent()
    assert len(calls) == 1


def test_existing_active_unit_blocks_new_copy_before_workspace_creation(tmp_path, monkeypatch):
    request, root, _source, generated = fixture(tmp_path, monkeypatch)

    def busy():
        raise publication.CudaHostPublicationError("CUDA_HOST_PUBLICATION_UNIT_NOT_QUIESCENT")

    monkeypatch.setattr(publication, "_require_cache_unit_quiescent", busy)
    with pytest.raises(publication.CudaHostPublicationError, match="UNIT_NOT_QUIESCENT"):
        publication.publish_cuda_host_extension(request)
    assert not (root / ".publication").exists() and generated == []


def test_publication_import_is_stdlib_only_before_any_candidate_instruction():
    root = Path(publication.__file__).parent.parent
    code = """
import sys
sys.path.insert(0,sys.argv[1])
import eom_catalog_service.embedding_cuda_host_publication
for name in ('pydantic','jsonschema','torch','transformers','sqlalchemy'):
 assert name not in sys.modules
print('STDLIB_PUBLICATION_IMPORT=PASS')
"""
    result = subprocess.run(
        [os.sys.executable, "-I", "-S", "-B", "-c", code, str(root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STDLIB_PUBLICATION_IMPORT=PASS"


@pytest.mark.parametrize("reviewed", (False, True))
@pytest.mark.parametrize(
    "outcome", (0, 1, "timeout", "unknown-baseline", "source-mismatch", "late-base")
)
def test_cache_generator_records_terminal_or_unknown_outcome_without_native_execution(
    tmp_path, monkeypatch, outcome, reviewed
):
    actual_generate = publication._generate_cache
    request, _root, _source, _generated = fixture(tmp_path, monkeypatch, reviewed=reviewed)
    base = base_capture.resolve_host_configuration_snapshot(request.base_configuration)
    workspace = tmp_path / "real-generator-port"
    workspace.mkdir(mode=0o700)
    stage = workspace / "revision"
    stage.mkdir(mode=0o700)
    final = publication._ROOT / request.configuration_id / request.configuration_revision_id
    sources = {}
    fixed = []
    successor_fixed = []
    for name, _route in host.embedding_host_loader_cache_routes():
        path = tmp_path / name
        raw = b"syntheticCPU:" + name.encode()
        updated = raw + b":reviewed" if name == "liblzma.so.5" else raw
        _write(path, updated if reviewed else raw)
        sources[name] = path
        fixed.append((path, len(raw), hashlib.sha256(raw).hexdigest()))
        successor_fixed.append((path, len(updated), hashlib.sha256(updated).hexdigest()))
    # The production selector replaces the sole cache member in either reviewed
    # table. Synthetic SONAME bytes remain real no-follow/epoch-checked files.
    fixed.append((host._CACHE, 48, "0" * 64))
    successor_fixed.append((host._CACHE, 48, "0" * 64))
    monkeypatch.setattr(host, "_SONAMES", sources)
    monkeypatch.setattr(host, "_FILES", tuple(fixed))
    monkeypatch.setattr(
        host,
        "_REVIEWED_HOST_BASELINES",
        MappingProxyType(
            {
                host.FIXED_EMBEDDING_HOST_SEED_SHA256: tuple(fixed),
                host.UBUNTU_LIBLZMA_20261021_HOST_SEED_SHA256: tuple(successor_fixed),
            }
        ),
    )
    if outcome == "unknown-baseline":
        base = replace(base, baseline_host_seed_sha256="sha256:" + "f" * 64)
    elif outcome == "source-mismatch":
        _write(sources["liblzma.so.5"], b"not-the-selected-reviewed-bytes")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert "--property=LimitFSIZE=131072" in command
        assert len([arg for arg in command if arg.startswith("--property=BindReadOnlyPaths=")]) == 1
        assert (
            len(
                next(
                    arg.split("=", 2)[2]
                    for arg in command
                    if arg.startswith("--property=BindReadOnlyPaths=")
                ).split()
            )
            == 21
        )
        kwargs["stderr"].write(b"synthetic diagnostic only\n")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 45)
        if outcome in (0, "late-base"):
            raw = _cache(
                tuple(
                    (name, path, 0x303, 0, 0)
                    for name, path in (
                        *host.embedding_host_loader_cache_routes(),
                        *((name, str(final / name)) for _role, name, _max in capture._LIBRARIES),
                    )
                )
            )
            _write(workspace / "build/etc/ld.so.cache", raw)
            if outcome == "late-base":
                _write(base.cache_path, b"changed-after-the-cache-unit")
        return SimpleNamespace(returncode=0 if outcome == "late-base" else outcome)

    monkeypatch.setattr(subprocess, "run", run)
    owner = publication.NumericalRuntimeFileSnapshots(os.geteuid())
    if outcome == 0:
        raw = actual_generate(workspace, final, stage, owner, base_configuration=base)
        capture.validate_cuda_host_loader_cache(raw, final)
    elif outcome in ("unknown-baseline", "source-mismatch", "late-base"):
        with pytest.raises(ValueError):
            actual_generate(workspace, final, stage, owner, base_configuration=base)
        if outcome != "late-base":
            assert calls == [] and not (workspace / "cache-unit-outcome.json").exists()
            return
    else:
        with pytest.raises(publication.CudaHostPublicationError):
            actual_generate(workspace, final, stage, owner, base_configuration=base)
    import json

    recorded = json.loads((workspace / "cache-unit-outcome.json").read_bytes())
    assert recorded["state"] == (
        "SUCCEEDED"
        if outcome in (0, "late-base")
        else "FAILED"
        if outcome == 1
        else "OUTCOME_UNKNOWN"
    )
    assert recorded["scope"] == "CACHE_ONLY_NOT_NATIVE_ADMISSION" and len(calls) == 1
    assert (workspace / "cache-unit.stderr").read_bytes() == b"synthetic diagnostic only\n"


def test_late_base_snapshot_drift_preserves_workspace_without_publishing(tmp_path, monkeypatch):
    request, root, _source, generated = fixture(tmp_path, monkeypatch, reviewed=True)
    generate = publication._generate_cache

    def changed(*args, **kwargs):
        cache = generate(*args, **kwargs)
        _write(kwargs["base_configuration"].cache_path, b"changed-before-publication")
        return cache

    monkeypatch.setattr(publication, "_generate_cache", changed)
    with pytest.raises(base_capture.HostConfigurationSnapshotError, match="CHANGED"):
        publication.publish_cuda_host_extension(request)
    assert len(generated) == 1
    assert not (root / request.configuration_id / request.configuration_revision_id).exists()
    assert (
        root / ".publication" / request.configuration_id / request.configuration_revision_id
    ).is_dir()


def retained_fixture(tmp_path, monkeypatch, *, schema_ref=capture.CUDA_HOST_NVML_SCHEMA_REF):
    request, root, source, generated = fixture(
        tmp_path, monkeypatch, schema_ref=schema_ref, reviewed=True
    )
    generate = publication._generate_cache

    def complete_cache(workspace, final, stage, cpu_files, **kwargs):
        raw = generate(workspace, final, stage, cpu_files, **kwargs)
        build = workspace / "build"
        for relative in ("etc", "var/cache/ldconfig", "lib", "usr/lib"):
            publication._private_parents(workspace, build / relative)
        publication._write(
            build / "etc/ld.so.conf", ("/lib/x86_64-linux-gnu\n" + str(final) + "\n").encode()
        )
        recipe = capture.cuda_host_library_recipe(request.schema_ref)
        bindings = tuple(
            (source / "not-read", Path(route))
            for _name, route in host.embedding_host_loader_cache_routes()
        ) + tuple((stage / name, final / name) for _role, name, _maximum in recipe.libraries)
        publication._prepare_cache_command(workspace, final, bindings)
        publication._write(build / "etc/ld.so.cache", raw, mode=0o644)
        publication._write(build / "var/cache/ldconfig/aux-cache", b"unused auxiliary", mode=0o600)
        publication._write(workspace / "unit-name", (publication._UNIT + "\n").encode(), mode=0o600)
        publication._write(workspace / "cache-unit.stderr", b"", mode=0o600)
        publication._write(
            workspace / "cache-unit-outcome.json",
            publication._canonical(
                {
                    "unit": publication._UNIT,
                    "scope": "CACHE_ONLY_NOT_NATIVE_ADMISSION",
                    "returncode": 0,
                    "state": "SUCCEEDED",
                }
            ),
            mode=0o600,
        )
        return raw

    monkeypatch.setattr(publication, "_generate_cache", complete_cache)

    def cross_mount(*args):
        raise OSError(errno.EXDEV, "synthetic mount boundary")

    with monkeypatch.context() as patch:
        patch.setattr(publication.os, "rename", cross_mount)
        with pytest.raises(OSError) as error:
            publication.publish_cuda_host_extension(request)
        assert error.value.errno == errno.EXDEV
    workspace = root / ".publication" / request.configuration_id / request.configuration_revision_id
    pointer = publication._pointer_from_raw(
        request, (workspace / "revision/snapshot.json").read_bytes()
    )
    return request, pointer, workspace, root, source, generated


def rewrite_retained(path, raw, mode):
    _write(path, raw)
    path.chmod(mode)


@pytest.mark.parametrize(
    "schema_ref", (capture.CUDA_HOST_SCHEMA_REF, capture.CUDA_HOST_NVML_SCHEMA_REF)
)
def test_explicit_completion_commits_same_identity_without_rebuilding_or_sources(
    tmp_path, monkeypatch, schema_ref
):
    request, pointer, workspace, root, source, generated = retained_fixture(
        tmp_path, monkeypatch, schema_ref=schema_ref
    )
    final = root / request.configuration_id / request.configuration_revision_id
    original = {path.name: path.read_bytes() for path in (workspace / "revision").iterdir()}
    evidence = (workspace / "cache-unit-outcome.json").read_bytes()
    for path in source.iterdir():
        path.unlink()
    with pytest.raises(publication.CudaHostPublicationError, match="REQUIRES_RECONCILIATION"):
        publication.publish_cuda_host_extension(request)
    completed = publication.complete_cuda_host_extension_publication(request, pointer)
    assert completed == publication.CudaHostPublicationResult(pointer, "CREATED")
    assert len(generated) == 1 and not (workspace / "revision").exists()
    assert final.stat().st_mode & 0o777 == 0o555
    assert {path.name: path.read_bytes() for path in final.iterdir()} == original
    assert (workspace / "cache-unit-outcome.json").read_bytes() == evidence
    before = {path: publication._identity(path.lstat()) for path in final.iterdir()}
    replay = publication.complete_cuda_host_extension_publication(request, pointer)
    assert replay == publication.CudaHostPublicationResult(pointer, "REUSED")
    assert {path: publication._identity(path.lstat()) for path in final.iterdir()} == before
    assert len(generated) == 1


@pytest.mark.parametrize("fault", ("raw", "semantic", "size", "revision", "schema", "untyped"))
def test_completion_requires_exact_typed_snapshot_pointer(tmp_path, monkeypatch, fault):
    request, pointer, workspace, root, _source, generated = retained_fixture(tmp_path, monkeypatch)
    if fault == "raw":
        pointer = replace(pointer, manifest_raw_sha256="sha256:" + "0" * 64)
    elif fault == "semantic":
        pointer = replace(pointer, snapshot_sha256="sha256:" + "0" * 64)
    elif fault == "size":
        pointer = replace(pointer, manifest_byte_count=pointer.manifest_byte_count - 1)
    elif fault == "revision":
        pointer = replace(pointer, configuration_revision_id="embeddingcudahostrev_" + "3" * 32)
    elif fault == "schema":
        pointer = replace(pointer, schema_ref=capture.CUDA_HOST_SCHEMA_REF)
    else:
        pointer = SimpleNamespace(**{name: getattr(pointer, name) for name in pointer.__slots__})
    with pytest.raises(ValueError):
        publication.complete_cuda_host_extension_publication(request, pointer)
    assert (workspace / "revision").is_dir() and len(generated) == 1
    assert not (root / request.configuration_id / request.configuration_revision_id).exists()


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "extra-file",
        "extra-directory",
        "payload",
        "payload-mode",
        "payload-link",
        "payload-hardlink",
        "directory-mode",
        "tool",
        "outcome",
        "outcome-extra",
        "outcome-bool",
        "unit",
        "builder-cache",
        "builder-config",
        "placeholder",
        "aux-mode",
        "diagnostic-size",
    ),
)
def test_completion_rejects_partial_changed_or_unsafe_retained_tree(tmp_path, monkeypatch, fault):
    request, pointer, workspace, root, _source, generated = retained_fixture(tmp_path, monkeypatch)
    payload = workspace / "revision/libcuda.so.1"
    if fault == "missing":
        payload.unlink()
    elif fault == "extra-file":
        publication._write(workspace / "unexpected", b"extra")
    elif fault == "extra-directory":
        (workspace / "unexpected").mkdir(mode=0o700)
    elif fault == "payload":
        _write(payload, b"x" + payload.read_bytes()[1:])
    elif fault == "payload-mode":
        payload.chmod(0o644)
    elif fault == "payload-link":
        payload.unlink()
        payload.symlink_to("libibverbs.so.1")
    elif fault == "payload-hardlink":
        (tmp_path / "second-link").hardlink_to(payload)
    elif fault == "directory-mode":
        (workspace / "revision").chmod(0o755)
    elif fault == "tool":
        rewrite_retained(workspace / "ldconfig.real", b"changed", 0o500)
    elif fault.startswith("outcome"):
        raw = (workspace / "cache-unit-outcome.json").read_bytes()
        raw = (
            raw.replace(b"SUCCEEDED", b"OUTCOME_UNKNOWN")
            if fault == "outcome"
            else raw.replace(b'"returncode":0', b'"returncode":false')
            if fault == "outcome-bool"
            else raw[:-1] + b',"extra":0}'
        )
        rewrite_retained(workspace / "cache-unit-outcome.json", raw, 0o600)
    elif fault == "unit":
        rewrite_retained(workspace / "unit-name", b"other.service\n", 0o600)
    elif fault == "builder-cache":
        rewrite_retained(workspace / "build/etc/ld.so.cache", b"changed", 0o644)
    elif fault == "builder-config":
        _write(workspace / "build/etc/ld.so.conf", b"other route")
    elif fault == "placeholder":
        path = workspace / "build/lib/x86_64-linux-gnu/libc.so.6"
        _write(path, b"not empty")
    elif fault == "aux-mode":
        (workspace / "build/var/cache/ldconfig/aux-cache").chmod(0o644)
    else:
        rewrite_retained(workspace / "cache-unit.stderr", b"x" * (128 * 1024 + 1), 0o600)
    with pytest.raises((ValueError, OSError)):
        publication.complete_cuda_host_extension_publication(request, pointer)
    assert (workspace / "revision").is_dir() and len(generated) == 1
    assert not (root / request.configuration_id / request.configuration_revision_id).exists()


@pytest.mark.parametrize(
    "fault",
    (
        "request-base",
        "compiled-library",
        "driver",
        "late-base",
        "late-payload",
        "active",
        "late-active",
    ),
)
def test_completion_rechecks_base_recipe_unit_and_late_epochs(tmp_path, monkeypatch, fault):
    request, pointer, workspace, root, _source, generated = retained_fixture(tmp_path, monkeypatch)
    calls = []

    def quiescent():
        calls.append(True)
        if fault == "active" or (fault == "late-active" and len(calls) == 2):
            raise publication.CudaHostPublicationError("CUDA_HOST_PUBLICATION_UNIT_NOT_QUIESCENT")
        if len(calls) == 2 and fault == "late-payload":
            _write(workspace / "revision/libcuda.so.1", b"late drift")
        if len(calls) == 2 and fault == "late-base":
            selected = base_capture.resolve_host_configuration_snapshot(request.base_configuration)
            _write(selected.cache_path, b"late drift")

    monkeypatch.setattr(publication, "_require_cache_unit_quiescent", quiescent)
    if fault == "request-base":
        request = replace(
            request,
            base_configuration=replace(
                request.base_configuration, manifest_raw_sha256="sha256:" + "0" * 64
            ),
        )
    elif fault == "compiled-library":
        specs = dict(publication._SOURCES)
        path, size, _sha = specs["CUDA_DRIVER"]
        specs["CUDA_DRIVER"] = (path, size, "0" * 64)
        monkeypatch.setattr(publication, "_SOURCES", specs)
    elif fault == "driver":
        monkeypatch.setattr(publication, "_DRIVER", "0.0.0")
    with pytest.raises(ValueError):
        publication.complete_cuda_host_extension_publication(request, pointer)
    assert not (root / request.configuration_id / request.configuration_revision_id).exists()
    assert (workspace / "revision").is_dir() and len(generated) == 1


def test_completion_replay_rejects_conflicting_or_unsealed_final_without_repair(
    tmp_path, monkeypatch
):
    request, pointer, workspace, root, _source, _generated = retained_fixture(tmp_path, monkeypatch)
    publication.complete_cuda_host_extension_publication(request, pointer)
    final = root / request.configuration_id / request.configuration_revision_id
    with pytest.raises(publication.CudaHostPublicationError, match="EXISTING_REVISION_CONFLICT"):
        publication.complete_cuda_host_extension_publication(
            request, replace(pointer, manifest_raw_sha256="sha256:" + "0" * 64)
        )
    final.chmod(0o700)
    with pytest.raises(publication.CudaHostPublicationError, match="EXISTING_REVISION_INCOMPLETE"):
        publication.complete_cuda_host_extension_publication(request, pointer)
    assert final.stat().st_mode & 0o777 == 0o700 and not (workspace / "revision").exists()


def test_completion_uses_the_original_publication_lock(tmp_path, monkeypatch):
    request, pointer, workspace, _root, _source, generated = retained_fixture(tmp_path, monkeypatch)
    fd = os.open(publication._LOCK, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(publication.CudaHostPublicationError, match="BUSY"):
            publication.complete_cuda_host_extension_publication(request, pointer)
    finally:
        os.close(fd)
    assert (workspace / "revision").is_dir() and len(generated) == 1


def test_completion_rename_failure_retains_same_stage_and_never_regenerates(tmp_path, monkeypatch):
    request, pointer, workspace, root, _source, generated = retained_fixture(tmp_path, monkeypatch)
    raw = (workspace / "revision/snapshot.json").read_bytes()

    def cross_mount(*args):
        raise OSError(errno.EXDEV, "synthetic mount boundary")

    with monkeypatch.context() as patch:
        patch.setattr(publication.os, "rename", cross_mount)
        with pytest.raises(OSError) as error:
            publication.complete_cuda_host_extension_publication(request, pointer)
        assert error.value.errno == errno.EXDEV
    assert (workspace / "revision/snapshot.json").read_bytes() == raw
    assert not (root / request.configuration_id / request.configuration_revision_id).exists()
    assert publication.complete_cuda_host_extension_publication(request, pointer).pointer == pointer
    assert len(generated) == 1


def test_completion_rejects_valid_but_different_base_snapshot_selection(tmp_path, monkeypatch):
    request, pointer, workspace, _root, _source, _generated = retained_fixture(
        tmp_path, monkeypatch
    )
    base = base_capture.resolve_host_configuration_snapshot(request.base_configuration)
    document = json.loads(base.snapshot_raw)
    document["configuration_revision_id"] = "embeddinghostconfigrev_" + "3" * 32
    document["snapshot_sha256"] = publication._hash(
        publication._canonical(
            {key: value for key, value in document.items() if key != "snapshot_sha256"}
        )
    )
    raw = publication._canonical(document)
    directory = base.cache_path.parent.parent / document["configuration_revision_id"]
    directory.mkdir(mode=0o700)
    _write(directory / "snapshot.json", raw)
    _write(directory / "ld.so.cache", base.cache_path.read_bytes())
    different = replace(
        request.base_configuration,
        configuration_revision_id=document["configuration_revision_id"],
        manifest_byte_count=len(raw),
        manifest_raw_sha256=publication._hash(raw),
        snapshot_sha256=document["snapshot_sha256"],
    )
    base_capture.resolve_host_configuration_snapshot(different).assert_unchanged()
    with pytest.raises(publication.CudaHostPublicationError, match="RETAINED_REVISION_CONFLICT"):
        publication.complete_cuda_host_extension_publication(
            replace(request, base_configuration=different), pointer
        )
    assert (workspace / "revision").is_dir()


@pytest.mark.parametrize("fault", ("library", "cache-routes", "base-seed"))
def test_completion_does_not_trust_internally_consistent_forged_stage_metadata(
    tmp_path, monkeypatch, fault
):
    request, _pointer, workspace, _root, _source, _generated = retained_fixture(
        tmp_path, monkeypatch
    )
    stage = workspace / "revision"
    document = json.loads((stage / "snapshot.json").read_bytes())
    if fault == "library":
        raw = b"same-role-but-not-the-compiled-library"
        _write(stage / "libcuda.so.1", raw)
        document["libraries"][0].update(byte_count=len(raw), sha256=publication._hash(raw))
    elif fault == "base-seed":
        document["base_host_seed_sha256"] = "sha256:" + "0" * 64
    else:
        recipe = capture.cuda_host_library_recipe(request.schema_ref)
        raw = _cache(
            tuple(
                (name, path, 0x303, 0, 0)
                for name, path in (
                    *host.embedding_host_loader_cache_routes(),
                    *((name, str(stage / name)) for _role, name, _maximum in recipe.libraries),
                )
            )
        )
        _write(stage / "ld.so.cache", raw)
        rewrite_retained(workspace / "build/etc/ld.so.cache", raw, 0o644)
        document["loader_cache"].update(byte_count=len(raw), sha256=publication._hash(raw))
    document["host_seed_sha256"] = publication._hash(
        publication._canonical(
            {
                key: document[key]
                for key in ("base_host_seed_sha256", "driver_release", "libraries", "loader_cache")
            }
        )
    )
    document["snapshot_sha256"] = publication._hash(
        publication._canonical(
            {key: value for key, value in document.items() if key != "snapshot_sha256"}
        )
    )
    raw = publication._canonical(document)
    _write(stage / "snapshot.json", raw)
    pointer = publication._pointer_from_raw(request, raw)
    capture._manifest(raw, pointer)
    with pytest.raises(ValueError):
        publication.complete_cuda_host_extension_publication(request, pointer)
    assert stage.is_dir()


@pytest.mark.parametrize("fault", ("metadata-mode", "directory-mode"))
def test_completion_brackets_exact_permissions_before_first_metadata_epoch_capture(
    tmp_path, monkeypatch, fault
):
    request, pointer, workspace, root, _source, _generated = retained_fixture(tmp_path, monkeypatch)
    verify = publication.NumericalRuntimeFileSnapshots.verify
    changed = []

    def changed_before_capture(self, path, **kwargs):
        if path == workspace / "unit-name":
            target = path if fault == "metadata-mode" else workspace / "build/usr/lib"
            target.chmod(0o644 if fault == "metadata-mode" else 0o755)
            changed.append(target)
        return verify(self, path, **kwargs)

    monkeypatch.setattr(publication.NumericalRuntimeFileSnapshots, "verify", changed_before_capture)
    with pytest.raises(publication.CudaHostPublicationError, match="RETAINED_CHANGED"):
        publication.complete_cuda_host_extension_publication(request, pointer)
    assert len(changed) == 1 and (workspace / "revision").is_dir()
    assert not (root / request.configuration_id / request.configuration_revision_id).exists()
