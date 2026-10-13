"""Actual local flock and synthetic systemd/cgroups; no protected runtime or model."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_orchestrator import native_embedding_cpu_execution as cpu
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity

from tests.unit.test_native_embedding_query_handoff import prepared


@pytest.mark.parametrize("purpose", ("INDEX", "QUERY"))
def test_fixed_unit_names_are_purpose_bound_and_no_arbitrary_units(
    purpose: cpu.NativeCpuPurpose,
) -> None:
    assert cpu.native_cpu_unit_names(purpose, "a" * 32) == (
        f"eom-embedding-native-{purpose.lower()}-prepare@{'a' * 32}.service",
        f"eom-embedding-native-cpu-{purpose.lower()}@{'a' * 32}.service",
    )
    for value in ("../unsafe", "a" * 31, "a" * 33, "G" * 32, True):
        with pytest.raises(cpu.NativeCpuExecutionError):
            cpu.native_cpu_unit_names(purpose, value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "unit",
    (
        "eom-embedding-native-cpu-index@",
        "eom-embedding-native-index-prepare@",
        "eom-embedding-native-cpu-query@",
        "eom-embedding-native-query-prepare@",
    ),
)
def test_active_prepare_or_worker_of_either_purpose_blocks_new_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unit: str,
) -> None:
    observed: list[tuple[str, ...]] = []

    def status(args: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed.append(args)
        return subprocess.CompletedProcess(
            args, 0, f"{unit}{'a' * 32}.service loaded active running title\n".encode(), b""
        )

    monkeypatch.setattr(cpu.subprocess, "run", status)
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    with pytest.raises(cpu.NativeCpuExecutionError, match="BUSY"):
        cpu.require_no_active_native_cpu_execution()
    assert all(pattern in observed[0] for pattern in cpu._UNIT_GLOBS)


def test_empty_active_list_still_checks_both_prepare_and_worker_cgroups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = [pattern.replace("*", "a" * 32) for pattern in cpu._UNIT_GLOBS]
    for group in groups:
        (tmp_path / group).mkdir()
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(cpu.os, "fstat", lambda _fd: SimpleNamespace(st_uid=0))
    monkeypatch.setattr(
        cpu.subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )
    reads: list[str] = []
    monkeypatch.setattr(cpu, "require_empty_native_cpu_cgroup", reads.append)
    cpu.require_no_active_native_cpu_execution()
    assert set(reads) == set(groups) and len(reads) == 4


@pytest.mark.parametrize(
    "bad", (b"unexpected.service loaded active running title\n", b"\xff", b"x" * 65537)
)
def test_invalid_unit_inventory_fails_closed_before_capacity_reuse(
    monkeypatch: pytest.MonkeyPatch,
    bad: bytes,
) -> None:
    monkeypatch.setattr(
        cpu.subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args, 0, bad, b""),
    )
    with pytest.raises(cpu.NativeCpuExecutionError, match="CAPACITY_UNAVAILABLE"):
        cpu.require_no_active_native_cpu_execution()


def test_shared_flock_retains_existing_index_lock_path_and_denies_second_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(cpu, "CAPACITY_ROOT", root)
    monkeypatch.setattr(
        cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    with (
        cpu.native_cpu_capacity(),
        pytest.raises(cpu.NativeCpuExecutionError, match="BUSY"),
        cpu.native_cpu_capacity(),
    ):
        pass
    assert (root / ".cpu-capacity.lock").stat().st_size == 0
    with cpu.native_cpu_capacity():
        pass


def test_resource_guard_revalidates_raw_values_without_silently_dropping_fields() -> None:
    resources = prepared().workflow_request.resource_profile
    cpu.validate_fixed_native_cpu_resources(resources)
    for change in (
        {"unknown": "ADMIN"},
        {"batch_size": True},
        {"resource_profile_sha256": "sha256:" + "0" * 64},
    ):
        with pytest.raises(ValueError):
            cpu.validate_fixed_native_cpu_resources(resources.model_copy(update=change))


@pytest.mark.parametrize("nested", (False, True))
def test_actual_file_reads_detect_surviving_child_in_flat_or_default_template_slice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    nested: bool,
) -> None:
    """Actual temporary file reads; only root UID metadata is a synthetic seam."""
    unit = "eom-embedding-native-index-prepare@" + "a" * 32 + ".service"
    parent = tmp_path
    if nested:
        parent = tmp_path / r"system-eom\x2dembedding\x2dnative\x2dindex\x2dprepare.slice"
        parent.mkdir()
    group = parent / unit
    group.mkdir()
    (group / "cgroup.procs").write_bytes(b"1234\n")
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(cpu.os, "fstat", lambda _fd: SimpleNamespace(st_uid=0))
    monkeypatch.setattr(
        cpu.subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args, 0, b"", b""),
    )
    with pytest.raises(cpu.NativeCpuExecutionError, match="UNCERTAIN"):
        cpu.require_no_active_native_cpu_execution()
    (group / "cgroup.procs").write_bytes(b"")
    cpu.require_no_active_native_cpu_execution()


def test_missing_kernel_base_or_symlinked_slice_is_not_a_quiescence_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = "eom-embedding-native-index-prepare@" + "a" * 32 + ".service"
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path / "missing")
    with pytest.raises(cpu.NativeCpuExecutionError, match="UNCERTAIN"):
        cpu.require_empty_native_cpu_cgroup(unit)
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(cpu.os, "fstat", lambda _fd: SimpleNamespace(st_uid=0))
    target = tmp_path / "unrelated"
    target.mkdir()
    (tmp_path / r"system-eom\x2dembedding\x2dnative\x2dindex\x2dprepare.slice").symlink_to(target)
    with pytest.raises(OSError):
        cpu.require_empty_native_cpu_cgroup(unit)


def test_invalid_kernel_owner_does_not_leak_retained_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert os.geteuid() != 0
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(3):
        with pytest.raises(cpu.NativeCpuExecutionError, match="UNCERTAIN"):
            cpu.require_empty_native_cpu_cgroup(
                "eom-embedding-native-cpu-query@" + "a" * 32 + ".service"
            )
    assert len(os.listdir("/proc/self/fd")) == before


def test_missing_membership_file_is_not_confused_with_an_absent_terminal_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = "eom-embedding-native-cpu-query@" + "a" * 32 + ".service"
    group = tmp_path / unit
    group.mkdir()
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(cpu.os, "fstat", lambda _fd: SimpleNamespace(st_uid=0))
    with pytest.raises(cpu.NativeCpuExecutionError, match="UNCERTAIN"):
        cpu.require_empty_native_cpu_cgroup(unit)
    group.rmdir()
    cpu.require_empty_native_cpu_cgroup(unit)
