"""Fixed-unit fake process/metadata tests; no systemd or privileged execution."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_orchestrator import inference_transfer_cpu_systemd as cpu
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.inference_transfer_experiment_ports import (
    CpuExperimentRunError,
    LocalExperimentInput,
)
from eom_orchestrator.worker_systemd import FixedUnitStatus

from tests.unit.inference_transfer_fixtures import NOW, sha

EXECUTION = "embeddingexecution_" + "a" * 32


def observation(kind: str, *, main: bool = False) -> cpu.CpuUnitObservation:
    template = cpu.CPU_TEMPLATE if main else cpu.PREPARE_TEMPLATE
    running = kind == "running"
    fresh = kind == "fresh"
    failed = kind in {"failed", "timeout"}
    status = FixedUnitStatus(
        load_state="loaded",
        active_state="inactive" if fresh else "failed" if failed else "active",
        sub_state="dead" if fresh else "failed" if failed else "running" if running else "exited",
        result="timeout" if kind == "timeout" else "exit-code" if failed else "success",
        exec_main_code=0 if fresh or running else 1,
        exec_main_status=1 if failed else 0,
        exec_main_started_monotonic=0 if fresh else 10,
        need_daemon_reload=False,
    )
    return cpu.CpuUnitObservation(
        status=status,
        main_pid=123 if running else 0,
        exited_monotonic=0 if fresh or running else 20,
        invocation_id="" if fresh else "a" * 32,
        fragment_path=str(cpu.UNIT_ROOT / template),
        drop_in_paths="",
    )


def fake_launcher(
    monkeypatch: pytest.MonkeyPatch, states: list[cpu.CpuUnitObservation]
) -> tuple[LocalExperimentInput, list[Any], list[LocalExperimentInput]]:
    calls: list[Any] = []
    copied: list[LocalExperimentInput] = []
    values = iter(states)
    monkeypatch.setattr(
        cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    monkeypatch.setattr(cpu, "require_cpu_runtime", lambda: None)
    monkeypatch.setattr(cpu, "inspect_cpu_unit", lambda *_a, **_k: next(values))
    monkeypatch.setattr(cpu, "materialize_cpu_output", copied.append)

    def start(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(cpu.subprocess, "run", start)
    return (
        LocalExperimentInput(cpu.OWNER_ROOT / EXECUTION, EXECUTION, NOW, sha(), 100),
        calls,
        copied,
    )


def test_fixed_units_require_confirmed_terminal_stable_identity_and_one_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = [observation("success"), observation("success", main=True)]
    prepared, calls, copied = fake_launcher(
        monkeypatch, [observation("fresh"), observation("fresh", main=True), *final, *final]
    )
    cpu.FixedCpuExperimentLauncher().run(prepared)
    assert copied == [prepared] and len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == (cpu.SYSTEMCTL, "--no-ask-password", "start", cpu.cpu_unit_names(EXECUTION)[1])
    assert "--wait" not in argv
    assert kwargs["timeout"] == 1830 and kwargs["env"] == cpu._ENVIRONMENT


@pytest.mark.parametrize("state", ["success", "running", "failed", "timeout"])
def test_already_attempted_or_running_unit_is_never_restarted(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    prepared, calls, copied = fake_launcher(
        monkeypatch, [observation("fresh"), observation(state, main=True)]
    )
    with pytest.raises(CpuExperimentRunError, match="UNCERTAIN"):
        cpu.FixedCpuExperimentLauncher().run(prepared)
    assert calls == copied == []


@pytest.mark.parametrize(
    "prepare_state,main_state,outcome",
    [
        ("success", "failed", "KNOWN_FAILED"),
        ("failed", "fresh", "KNOWN_FAILED"),
        ("success", "timeout", "UNCERTAIN"),
        ("success", "running", "UNCERTAIN"),
        ("success", "fresh", "UNCERTAIN"),
    ],
)
def test_start_return_code_is_not_execution_authority(
    monkeypatch: pytest.MonkeyPatch, prepare_state: str, main_state: str, outcome: str
) -> None:
    prepared, calls, copied = fake_launcher(
        monkeypatch,
        [
            observation("fresh"),
            observation("fresh", main=True),
            observation(prepare_state),
            observation(main_state, main=True),
        ],
    )
    with pytest.raises(CpuExperimentRunError, match=outcome):
        cpu.FixedCpuExperimentLauncher().run(prepared)
    assert len(calls) == 1 and copied == []


def test_timeout_is_uncertain_and_never_materializes_or_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _calls, copied = fake_launcher(
        monkeypatch, [observation("fresh"), observation("fresh", main=True)]
    )
    calls = 0

    def timeout(*_a: Any, **_k: Any) -> Any:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired("fixed-start", 1830)

    monkeypatch.setattr(cpu.subprocess, "run", timeout)
    with pytest.raises(CpuExperimentRunError, match="UNCERTAIN"):
        cpu.FixedCpuExperimentLauncher().run(prepared)
    assert calls == 1 and copied == []


def test_post_materialization_invocation_change_cannot_return_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = [observation("success"), observation("success", main=True)]
    prepared, _calls, copied = fake_launcher(
        monkeypatch,
        [
            observation("fresh"),
            observation("fresh", main=True),
            *final,
            final[0],
            replace(final[1], invocation_id="b" * 32),
        ],
    )
    with pytest.raises(CpuExperimentRunError, match="UNCERTAIN"):
        cpu.FixedCpuExperimentLauncher().run(prepared)
    assert copied == [prepared]


def test_missing_installed_runtime_has_no_ambient_fallback_or_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, calls, copied = fake_launcher(monkeypatch, [])

    def missing() -> None:
        raise FileNotFoundError("fixed CPU interpreter missing")

    monkeypatch.setattr(cpu, "require_cpu_runtime", missing)
    with pytest.raises(CpuExperimentRunError, match="KNOWN_FAILED"):
        cpu.FixedCpuExperimentLauncher().run(prepared)
    assert calls == copied == []


def status_document(**updates: str) -> bytes:
    values = dict(
        LoadState="loaded",
        ActiveState="active",
        SubState="exited",
        Result="success",
        ExecMainCode="1",
        ExecMainStatus="0",
        ExecMainStartTimestampMonotonic="10",
        ExecMainExitTimestampMonotonic="20",
        NeedDaemonReload="no",
        MainPID="0",
        InvocationID="a" * 32,
        FragmentPath=str(cpu.UNIT_ROOT / cpu.CPU_TEMPLATE),
        DropInPaths="",
    )
    values.update(updates)
    return "\n".join(f"{key}={value}" for key, value in values.items()).encode()


@pytest.mark.parametrize(
    "changes",
    [
        {"FragmentPath": "/tmp/alternate.service"},
        {"DropInPaths": "/tmp/extra.conf"},
        {"NeedDaemonReload": "yes"},
        {"NeedDaemonReload": "unknown"},
        {"LoadState": "not-found"},
        {"MainPID": "-1"},
        {"ExecMainExitTimestampMonotonic": "-1"},
    ],
)
def test_status_rejects_wrong_release_dropin_reload_and_negative_fields(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str]
) -> None:
    monkeypatch.setattr(
        cpu.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, status_document(**changes), b""),
    )
    with pytest.raises(ValueError, match="STATUS_INVALID"):
        cpu.inspect_cpu_unit(cpu.cpu_unit_names(EXECUTION)[1], template=cpu.CPU_TEMPLATE)


@pytest.mark.parametrize("kind", ["duplicate", "missing", "unknown", "oversized", "utf8"])
def test_status_wire_is_closed_bounded_and_unique(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    payload = status_document()
    if kind == "duplicate":
        payload += b"\nMainPID=0"
    elif kind == "missing":
        payload = payload.replace(b"MainPID=0\n", b"")
    elif kind == "unknown":
        payload += b"\nUnexpected=value"
    elif kind == "oversized":
        payload = b"x" * (16 * 1024 + 1)
    else:
        payload += b"\xff"
    monkeypatch.setattr(
        cpu.subprocess, "run", lambda *_a, **_k: subprocess.CompletedProcess([], 0, payload, b"")
    )
    with pytest.raises(ValueError):
        cpu.inspect_cpu_unit(cpu.cpu_unit_names(EXECUTION)[1], template=cpu.CPU_TEMPLATE)


@pytest.mark.parametrize("change", ["atime", "mtime", "inode", "size"])
def test_unit_file_identity_ignores_atime_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    template = tmp_path / "fixed.service"
    payload = b"[Service]\nType=oneshot\n"
    template.write_bytes(payload)
    template.chmod(0o644)
    monkeypatch.setattr(cpu, "UNIT_ROOT", tmp_path)
    monkeypatch.setattr(cpu, "_ROOT_UID", os.geteuid())
    monkeypatch.setattr(cpu, "_root_path", lambda path: path)
    original = os.fstat
    calls = 0

    def changed(fd: int) -> Any:
        nonlocal calls
        calls += 1
        value = original(fd)
        if calls != 2:
            return value
        fields = {
            name: getattr(value, name)
            for name in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_gid",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
                "st_atime_ns",
            )
        }
        fields[
            {"atime": "st_atime_ns", "mtime": "st_mtime_ns", "inode": "st_ino", "size": "st_size"}[
                change
            ]
        ] += 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(cpu.os, "fstat", changed)
    if change == "atime":
        cpu._require_template(template.name, hashlib.sha256(payload).hexdigest())
    else:
        with pytest.raises(ValueError, match="TEMPLATE_INVALID"):
            cpu._require_template(template.name, hashlib.sha256(payload).hexdigest())


def test_installed_templates_are_exact_hashed_and_cpu_boundary_is_fixed() -> None:
    root = Path(__file__).resolve().parents[2]
    for name, expected in (
        (cpu.PREPARE_TEMPLATE, cpu.PREPARE_TEMPLATE_SHA256),
        (cpu.CPU_TEMPLATE, cpu.CPU_TEMPLATE_SHA256),
    ):
        payload = (root / "infra" / "systemd" / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected
        text = payload.decode()
        assert "Type=oneshot\nRemainAfterExit=yes" in text
        assert "Restart=no" in text and "LimitFSIZE=64M" in text
        assert "StandardError=null" in text and "StartLimitBurst=1" in text
        assert "systemd-run" not in text and "RuntimeMaxSec" not in text
    main = (root / "infra/systemd" / cpu.CPU_TEMPLATE).read_text()
    assert "Requires=eom-embedding-experiment-prepare@%i.service" in main
    assert "User=eom-embedding-experiment\nGroup=eom-embedding-experiment" in main
    assert " -I -m eom_catalog_service.inference_transfer_cpu_stdio " in main
    assert "InaccessiblePaths=/run/eom-embedding-experiments" in main
    assert "PrivateNetwork=yes" in main and "PrivateDevices=yes" in main
    assert "TimeoutStartSec=1800" in main
