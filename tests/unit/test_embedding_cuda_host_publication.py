"""Synthetic publication/cache-unit ports; no sudo, root acceptance, model or GPU use."""

from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import parse_cuda_host_extension_bytes
from eom_catalog_service import embedding_cuda_host_capture as capture
from eom_catalog_service import embedding_cuda_host_publication as publication
from eom_catalog_service import embedding_host_configuration_capture as base_capture
from eom_catalog_service import embedding_runtime_host_closure as host

from tests.unit.test_embedding_host_configuration_files import _fixture, _write
from tests.unit.test_embedding_runtime_host_closure import _cache


def fixture(tmp_path, monkeypatch, *, schema_ref=capture.CUDA_HOST_SCHEMA_REF):
    recipe = capture.cuda_host_library_recipe(schema_ref)
    base = _fixture(tmp_path / "base", monkeypatch)
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

    def generate(workspace, final, stage, cpu_files, *, schema_ref):
        assert capture.cuda_host_library_recipe(schema_ref) == recipe
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


@pytest.mark.parametrize("outcome", (0, 1, "timeout"))
def test_cache_generator_records_terminal_or_unknown_outcome_without_native_execution(
    tmp_path, monkeypatch, outcome
):
    actual_generate = publication._generate_cache
    request, _root, _source, _generated = fixture(tmp_path, monkeypatch)
    workspace = tmp_path / "real-generator-port"
    workspace.mkdir(mode=0o700)
    stage = workspace / "revision"
    stage.mkdir(mode=0o700)
    final = publication._ROOT / request.configuration_id / request.configuration_revision_id
    sources = {}
    fixed = []
    for name, _route in host.embedding_host_loader_cache_routes():
        path = tmp_path / name
        raw = b"syntheticCPU:" + name.encode()
        _write(path, raw)
        sources[name] = path
        fixed.append((path, len(raw), hashlib.sha256(raw).hexdigest()))
    monkeypatch.setattr(host, "_SONAMES", sources)
    monkeypatch.setattr(host, "_FILES", tuple(fixed))
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
        if outcome == 0:
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
        return SimpleNamespace(returncode=outcome)

    monkeypatch.setattr(subprocess, "run", run)
    owner = publication.NumericalRuntimeFileSnapshots(os.geteuid())
    if outcome == 0:
        raw = actual_generate(workspace, final, stage, owner)
        capture.validate_cuda_host_loader_cache(raw, final)
    else:
        with pytest.raises(publication.CudaHostPublicationError):
            actual_generate(workspace, final, stage, owner)
    import json

    recorded = json.loads((workspace / "cache-unit-outcome.json").read_bytes())
    assert recorded["state"] == (
        "SUCCEEDED" if outcome == 0 else "FAILED" if outcome == 1 else "OUTCOME_UNKNOWN"
    )
    assert recorded["scope"] == "CACHE_ONLY_NOT_NATIVE_ADMISSION" and len(calls) == 1
    assert (workspace / "cache-unit.stderr").read_bytes() == b"synthetic diagnostic only\n"
