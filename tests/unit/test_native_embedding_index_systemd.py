"""Synthetic unit observations and genuine local flock; no runtime activation."""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import sha256_file
from eom_orchestrator import native_embedding_cpu_execution as cpu
from eom_orchestrator import native_embedding_index_systemd as launcher
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity

from tests.unit.test_inference_transfer_cpu_systemd import observation
from tests.unit.test_native_embedding_index_handoff import prepared


def setup_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    states: list[tuple[str, str]],
) -> tuple[launcher.FixedNativeIndexLauncher, list[tuple[str, ...]]]:
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(cpu, "CAPACITY_ROOT", root)
    monkeypatch.setattr(
        cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    monkeypatch.setattr(launcher, "require_fixed_cpu_unit_template", lambda *_a: None)
    monkeypatch.setattr(launcher, "require_native_cpu_environment_file", lambda *_a: None)
    monkeypatch.setattr(launcher, "_require_runtime_roots", lambda: None)
    monkeypatch.setattr(launcher, "claim_native_cpu_dispatch", lambda *_a, **_kw: None)
    monkeypatch.setattr(cpu, "require_no_active_native_cpu_execution", lambda: None)
    monkeypatch.setattr(cpu, "require_empty_native_cpu_cgroup", lambda *_a: None)
    reads = iter(states)

    def observe(_self: Any, _id: str) -> Any:
        a, b = next(reads)
        return observation(a), observation(b, main=True)

    monkeypatch.setattr(launcher.FixedNativeIndexLauncher, "_observe", observe)
    monkeypatch.setattr(
        launcher, "materialize_native_index_output", lambda _prepared: "synthetic-result"
    )
    calls: list[tuple[str, ...]] = []

    def start(args: tuple[str, ...], **_kw: Any) -> Any:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(cpu.subprocess, "run", start)
    return launcher.FixedNativeIndexLauncher("a" * 64, "b" * 64, lambda: None), calls


def test_template_hashes_and_root_prepare_dependency_are_real_source() -> None:
    root = Path(__file__).resolve().parents[2] / "infra/systemd"
    assert (
        sha256_file(root / launcher.PREPARE_TEMPLATE)
        == "sha256:" + launcher.PREPARE_TEMPLATE_SHA256
    )
    assert sha256_file(root / launcher.INDEX_TEMPLATE) == "sha256:" + launcher.INDEX_TEMPLATE_SHA256
    text = (root / launcher.INDEX_TEMPLATE).read_text()
    assert "Requires=eom-embedding-native-index-prepare@%i.service" in text


@pytest.mark.parametrize("bad", (None, "missing", "symlink", "writable", "uid", "gid"))
def test_runtime_layout_is_checked_before_a_unit_can_be_started(
    monkeypatch: pytest.MonkeyPatch, bad: str | None
) -> None:
    monkeypatch.setattr(cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(990, 1000))

    def metadata(path: Path) -> Any:
        mode, uid, gid = stat.S_IFDIR | 0o750, 0, 1000
        if path.name.endswith("-probe"):
            mode, gid = stat.S_IFDIR | 0o700, 0
        if path.name.endswith("-query"):
            if bad == "missing":
                raise FileNotFoundError
            if bad == "symlink":
                mode = stat.S_IFLNK | 0o750
            if bad == "writable":
                mode = stat.S_IFDIR | 0o770
            if bad == "uid":
                uid = 990
            if bad == "gid":
                gid = 975
        return SimpleNamespace(st_mode=mode, st_uid=uid, st_gid=gid)

    monkeypatch.setattr(Path, "lstat", metadata)
    if bad is None:
        launcher._require_runtime_roots()
    else:
        with pytest.raises(launcher.NativeIndexLaunchError, match="RUNTIME_LAYOUT_INVALID"):
            launcher._require_runtime_roots()


def test_missing_runtime_layout_is_reported_without_starting_or_consuming_the_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, calls = setup_launcher(tmp_path, monkeypatch, [])

    def missing() -> None:
        raise launcher.NativeIndexLaunchError("NATIVE_INDEX_RUNTIME_LAYOUT_INVALID")

    monkeypatch.setattr(launcher, "_require_runtime_roots", missing)
    with pytest.raises(launcher.NativeIndexLaunchError, match="RUNTIME_LAYOUT_INVALID"):
        adapter.run(prepared())
    assert calls == []


def test_one_start_then_exact_terminal_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, calls = setup_launcher(
        tmp_path, monkeypatch, [("fresh", "fresh"), ("success", "success"), ("success", "success")]
    )
    assert adapter.run(prepared()) == "synthetic-result"
    assert calls == [
        (
            "/usr/bin/systemctl",
            "--no-ask-password",
            "start",
            launcher.native_index_unit_names("a" * 32)[1],
        )
    ]


def test_existing_completed_execution_reuses_result_without_another_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, calls = setup_launcher(
        tmp_path, monkeypatch, [("success", "success"), ("success", "success")]
    )
    assert adapter.run(prepared()) == "synthetic-result"
    assert calls == []


@pytest.mark.parametrize("state", ["running", "failed", "timeout"])
def test_existing_uncertain_or_failed_handle_is_not_restarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    states = [("success", state)] * (2 if state == "failed" else 1)
    adapter, calls = setup_launcher(tmp_path, monkeypatch, states)
    with pytest.raises(
        launcher.NativeIndexLaunchError, match="KNOWN_FAILED" if state == "failed" else "UNCERTAIN"
    ):
        adapter.run(prepared())
    assert calls == []


def test_transport_timeout_reobserves_same_execution_then_accepts_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, calls = setup_launcher(
        tmp_path, monkeypatch, [("fresh", "fresh"), ("success", "success"), ("success", "success")]
    )

    def timeout(args: tuple[str, ...], **_kw: Any) -> None:
        calls.append(args)
        raise subprocess.TimeoutExpired(args, 210)

    monkeypatch.setattr(cpu.subprocess, "run", timeout)
    assert adapter.run(prepared()) == "synthetic-result"
    assert len(calls) == 1


def test_real_flock_prevents_parallel_native_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _adapter, _calls = setup_launcher(tmp_path, monkeypatch, [])
    with (
        cpu.native_cpu_capacity(),
        pytest.raises(cpu.NativeCpuExecutionError, match="BUSY"),
        cpu.native_cpu_capacity(),
    ):
        pass


def test_explicit_runtime_denial_blocks_before_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, calls = setup_launcher(tmp_path, monkeypatch, [])

    def deny() -> None:
        raise ValueError("synthetic runtime changed")

    with pytest.raises(launcher.NativeIndexLaunchError):
        replace(adapter, assert_runtime_current=deny).run(prepared())
    assert calls == []
