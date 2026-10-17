"""Synthetic unprivileged ownership fixtures: not root/installation/model acceptance."""

from __future__ import annotations

import os
import pwd
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_handoff as module
from eom_catalog_service import embedding_device_benchmark_files as capture
from eom_catalog_service.embedding_benchmark_handoff import (
    BenchmarkHandoffError,
    prepare_benchmark_handoff,
)
from eom_catalog_service.embedding_benchmark_layout import benchmark_read_acl
from eom_catalog_service.embedding_device_benchmark_files import BenchmarkWorkerLocalFiles
from eom_identifiers import sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)


def synthetic_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "benchmark"
    root.mkdir(mode=0o711)
    root.chmod(0o711)
    for adapter in (module, capture):
        monkeypatch.setattr(adapter, "_ROOT_UID", os.getuid())
        monkeypatch.setattr(adapter, "_ROOT_GID", os.getgid())
        monkeypatch.setattr(adapter, "_HANDOFF_ROOT", root)

    def account(name: str) -> Any:
        return SimpleNamespace(
            pw_uid=os.getuid() + (1 if name == "eom-workflow-runner" else 0),
            pw_gid=os.getgid(),
        )

    monkeypatch.setattr(pwd, "getpwnam", account)
    return root


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_prepare_then_existing_capture_exact_layout_and_separate_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ordinal: int
) -> None:
    root = synthetic_root(tmp_path, monkeypatch)
    request, invocation, inputs = owner_request(), worker_invocation(ordinal), staged_inputs()
    prepared = prepare_benchmark_handoff(request, invocation, inputs)
    assert prepared.state == "STAGED_NOT_ADMITTED"
    assert prepared.job_id == invocation.job_id
    assert prepared.invocation_sha256 == invocation.invocation_sha256
    assert prepared.invocation_raw_sha256 == sha256_bytes(
        embedding_device_benchmark_bytes(invocation)
    )
    assert prepared.invocation_raw_sha256 != prepared.invocation_sha256
    assert prepared.input_set_sha256 == inputs.input_set_sha256
    assert prepared.input_raw_sha256 == invocation.local_input.sha256
    execution = root / invocation.execution_id
    assert sorted(path.name for path in execution.iterdir()) == [
        "inputs",
        "invocation.json",
        "outputs",
    ]
    assert tuple(sorted(path.name for path in (execution / "outputs").iterdir())) == tuple(
        sorted(benchmark_local_output_members(ordinal))
    )
    assert all(path.stat().st_size == 0 for path in (execution / "outputs").iterdir())
    borrowed = os.open(execution / "invocation.json", os.O_RDONLY | os.O_CLOEXEC)
    try:
        with BenchmarkWorkerLocalFiles(
            borrowed,
            profile=invocation.runtime.profile,
            execution_id=invocation.execution_id,
            invocation_raw_sha256=prepared.invocation_raw_sha256,
        ) as files:
            assert files.read_invocation() == invocation
            assert files.read_inputs(invocation) == inputs
            files.assert_current()
        assert os.lseek(borrowed, 0, os.SEEK_CUR) == 0
    finally:
        os.close(borrowed)


def test_validate_before_any_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = synthetic_root(tmp_path, monkeypatch)
    invalid = worker_invocation().model_copy(update={"input_set_sha256": "sha256:" + "a" * 64})
    with pytest.raises(ValueError):
        prepare_benchmark_handoff(owner_request(), invalid, staged_inputs())
    assert not tuple(root.iterdir())


def test_root_required_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = synthetic_root(tmp_path, monkeypatch)
    monkeypatch.setattr(module.os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(BenchmarkHandoffError, match="ROOT_REQUIRED"):
        prepare_benchmark_handoff(owner_request(), worker_invocation(), staged_inputs())
    assert not tuple(root.iterdir())


@pytest.mark.parametrize("fault", ("missing", "symlink", "mode", "default_acl"))
def test_fixed_root_must_be_preinstalled_and_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root = synthetic_root(tmp_path, monkeypatch)
    if fault == "missing":
        root.rmdir()
    elif fault == "symlink":
        root.rename(tmp_path / "other")
        root.symlink_to(tmp_path / "other")
    elif fault == "mode":
        root.chmod(0o777)
    else:
        os.setxattr(root, "system.posix_acl_default", benchmark_read_acl(os.getuid(), "DIRECTORY"))
    with pytest.raises(BenchmarkHandoffError):
        prepare_benchmark_handoff(owner_request(), worker_invocation(), staged_inputs())
    assert not (root / worker_invocation().execution_id).exists()


def test_concurrent_preparation_has_one_winner_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = synthetic_root(tmp_path, monkeypatch)
    request, invocation, inputs = owner_request(), worker_invocation(), staged_inputs()

    def prepare() -> str:
        try:
            return prepare_benchmark_handoff(request, invocation, inputs).state
        except BenchmarkHandoffError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _: prepare(), range(2)))
    assert results == ["BENCHMARK_HANDOFF_ALREADY_EXISTS", "STAGED_NOT_ADMITTED"]
    path = root / invocation.execution_id / "invocation.json"
    inode, raw = path.stat().st_ino, path.read_bytes()
    with pytest.raises(BenchmarkHandoffError, match="ALREADY_EXISTS"):
        prepare_benchmark_handoff(request, invocation, inputs)
    assert path.stat().st_ino == inode and path.read_bytes() == raw


def test_partial_failure_stays_private_and_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = synthetic_root(tmp_path, monkeypatch)
    original = module._new_member

    def fail(parent: int, name: str, payload: bytes, uid: int, gid: int, mode: int) -> None:
        if name == "benchmark-inputs.json":
            raise OSError("synthetic local I/O failure")
        original(parent, name, payload, uid, gid, mode)

    monkeypatch.setattr(module, "_new_member", fail)
    with pytest.raises(BenchmarkHandoffError, match="PREPARE_FAILED"):
        prepare_benchmark_handoff(owner_request(), worker_invocation(), staged_inputs())
    execution = root / worker_invocation().execution_id
    assert stat.S_IMODE(execution.stat().st_mode) == 0o700
    assert (execution / "invocation.json").is_file()
    with pytest.raises(BenchmarkHandoffError, match="ALREADY_EXISTS"):
        prepare_benchmark_handoff(owner_request(), worker_invocation(), staged_inputs())


@pytest.mark.parametrize("ordinal", (False, True, 0, 7, 1.0, "1"))
def test_output_members_reject_implicit_or_invalid_ordinals(ordinal: Any) -> None:
    with pytest.raises(ValueError):
        benchmark_local_output_members(ordinal)


@pytest.mark.parametrize("uid", (False, True, 0, -1, 2**32 - 1, 1.0, "1"))
def test_acl_rejects_implicit_or_invalid_uids(uid: Any) -> None:
    with pytest.raises(ValueError):
        benchmark_read_acl(uid, "DIRECTORY")
