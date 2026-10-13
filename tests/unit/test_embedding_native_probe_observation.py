"""Synthetic owner-side process observations; no root/live acceptance claims."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory
from eom_identifiers import sha256_bytes
from eom_orchestrator import embedding_native_probe_observation as owner
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.worker_systemd import FixedUnitStatus

from tests.unit.test_embedding_native_cpu_probe import metadata
from tests.unit.test_embedding_prefix_inventory_export import synthetic_audit

PREFIX = Path("/opt/eom/conda/envs/eom-embedding-index-cpu")
PYTHON = PREFIX / "bin/python3.12"


def test_fixed_template_is_pinned_by_owner_not_by_probe_input() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (
        sha256_bytes((root / "infra/systemd" / owner.CPU_PROBE_TEMPLATE).read_bytes())
        == owner.CPU_PROBE_TEMPLATE_SHA256
    )


@pytest.mark.parametrize(
    "identity", ["a/../b", "../evil", "a" * 31, "b" * 33, "A" * 32, "inferencecpu_" + "a" * 32]
)
def test_unit_instance_only_accepts_this_probe_execution_contract(identity: str) -> None:
    with pytest.raises(ValueError):
        owner._unit(identity)


def maps(*, path: Path = PYTHON, inode: int = 12) -> bytes:
    return (
        f"1000-2000 r--p 00000000 00:01 {inode} {path}\n"
        f"2000-3000 r-xp 00001000 00:01 {inode} {path}\n"
        "4000-5000 rw-p 00000000 00:00 0\n"
        "6000-7000 r-xp 00000000 00:00 0 [vdso]\n"
        "ffffffffff600000-ffffffffff601000 --xp 00000000 00:00 0 [vsyscall]\n"
    ).encode()


def process_stat(pid: int, *, start: int = 987, state: str = "S") -> bytes:
    fields = [state, *(["0"] * 18), str(start), *(["0"] * 28)]
    return f"{pid} (python (probe) name) {' '.join(fields)}\n".encode()


def running() -> CpuUnitObservation:
    return CpuUnitObservation(
        FixedUnitStatus("loaded", "activating", "start", "success", 0, 0, 100, False),
        123,
        0,
        "b" * 32,
        "/etc/systemd/system/" + owner.CPU_PROBE_TEMPLATE,
        "",
    )


def terminal() -> CpuUnitObservation:
    return replace(
        running(),
        main_pid=0,
        exited_monotonic=200,
        status=FixedUnitStatus("loaded", "active", "exited", "success", 1, 0, 100, False),
    )


def test_executable_projection_is_ordered_deduplicated_and_ignores_aslr() -> None:
    observed = owner.parse_native_executable_mappings(maps())
    assert observed == (owner.NativeExecutableMapping(PYTHON, os.makedev(0, 1), 12),)
    assert (
        owner.parse_native_executable_mappings(maps().replace(b"2000-3000", b"2100-3000"))
        == observed
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"0" * (2 * 1024**2 + 1),
        b"garbage\n",
        b"1000-2000 rwxp 0 00:00 0\n",
        b"1000-2000 r-xp 0 00:00 0\n",
        b"1000-2000 r-xs 0 00:01 1 /lib/a.so\n",
        b"1000-2000 r-xp 0 00:01 1 /lib/a.so (deleted)\n",
        b"1000-2000 r-xp 0 00:01 1 /lib/../a.so\n",
        b"1000-2000 r-xp 0 00:01 1 /lib//a.so\n",
        b"1000-2000 r-xp 0 00:01 1 [vdso]\n",
        b"1000-2000 r-xp 0 00:01 1 /a\n1800-3000 r-xp 0 00:01 1 /a\n",
        b"1000-2000 r-xp 0 00:01 1 /a\n2000-3000 r-xp 0 00:01 2 /a\n",
    ],
)
def test_unknown_unsafe_or_racing_mapping_rejected(raw: bytes) -> None:
    with pytest.raises(ValueError):
        owner.parse_native_executable_mappings(raw)


def test_proc_start_time_parser_handles_comm_parentheses_and_rejects_dead_process() -> None:
    assert owner.native_probe_start_ticks(process_stat(123), 123) == 987
    for raw in (
        process_stat(124),
        process_stat(123, start=0),
        process_stat(123, state="Z"),
        b"123 bad",
    ):
        with pytest.raises(ValueError):
            owner.native_probe_start_ticks(raw, 123)


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> Any:
    base = synthetic_audit().inventory
    directory, regular, _ = base.entries
    inventory = replace(
        base,
        entries=(
            replace(directory, relative_member="bin"),
            replace(regular, relative_member="bin/python3.12"),
        ),
    )
    checks: list[object] = []
    monkeypatch.setattr(
        PrefixRuntimeInventory, "assert_unchanged", lambda *_: checks.append("prefix")
    )

    def mapped(path: Path, *, device: int, inode: int) -> None:
        checks.append((path, device, inode))
        if path != Path("/usr/lib/libc.so.6") or (device, inode) != (1, 9):
            raise ValueError("unknown host member")

    host = SimpleNamespace(assert_current=lambda: checks.append("host"), assert_mapped_file=mapped)
    return inventory, host, checks


def test_mapping_uses_existing_prefix_ledger_and_supported_host_seam(ledger: Any) -> None:
    inventory, host, checks = ledger
    raw = maps().replace(
        b"4000-5000 rw-p 00000000 00:00 0", b"4000-5000 r-xp 0 00:01 9 /usr/lib/libc.so.6"
    )
    members = owner.validate_native_executable_mappings(raw, inventory=inventory, host=host)
    assert len(members) == 2
    assert (Path("/usr/lib/libc.so.6"), 1, 9) in checks
    assert checks[:2] == ["prefix", "host"] and checks[-2:] == ["prefix", "host"]


@pytest.mark.parametrize("fault", ["inode", "unknown_prefix", "host", "no_interpreter"])
def test_nonadmitted_mapping_cannot_become_runtime_acceptance(ledger: Any, fault: str) -> None:
    inventory, host, _ = ledger
    raw = {
        "inode": maps(inode=99),
        "unknown_prefix": maps(path=PREFIX / "bin/other"),
        "host": maps(path=Path("/usr/lib/unknown.so")),
        "no_interpreter": maps(path=Path("/usr/lib/libc.so.6"), inode=9),
    }[fault]
    with pytest.raises(ValueError):
        owner.validate_native_executable_mappings(raw, inventory=inventory, host=host)


@pytest.fixture
def process(ledger: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    inventory, host, _ = ledger
    _, _, report = metadata()
    _, cgroup = owner._unit(report.execution_id)
    state: dict[str, Any] = {
        "unit": running(),
        "start": 987,
        "cgroup": cgroup,
        "pids": (123,),
        "maps": maps(),
    }
    monkeypatch.setattr(owner, "_require_root", lambda: None)
    monkeypatch.setattr(
        owner, "require_native_cpu_probe_unit", lambda: (report.worker_uid, report.worker_gid)
    )
    monkeypatch.setattr(owner, "inspect_cpu_unit", lambda *_args, **_kwargs: state["unit"])
    monkeypatch.setattr(owner, "_cgroup_members", lambda *_: state["pids"])

    def read(path: Path, *, maximum: int, owner_uid: int) -> bytes:
        assert str(path.parent) == "/proc/123" and owner_uid == report.worker_uid
        return {
            "stat": process_stat(123, start=state["start"]),
            "cgroup": f"0::{state['cgroup']}\n".encode(),
            "maps": state["maps"],
        }[path.name]

    monkeypatch.setattr(owner, "read_live_runtime_os_file", read)
    return report, inventory, host, state


def test_exact_active_process_ack_and_terminal_are_separate(
    process: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, inventory, host, state = process
    observed = owner.observe_native_cpu_probe_process(report, inventory=inventory, host=host)
    assert observed.pid == 123 and observed.start_time_ticks == 987
    calls: list[object] = []

    def acknowledge(command: object, **_kwargs: object) -> Any:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(owner.subprocess, "run", acknowledge)
    owner.acknowledge_native_cpu_probe(observed, report, inventory=inventory, host=host)
    assert len(calls) == 1 and "--signal=SIGUSR1" in calls[0]
    with pytest.raises(ValueError, match="TERMINATION_UNCERTAIN"):
        owner.verify_native_cpu_probe_terminal(observed)
    state.update(unit=terminal(), pids=())
    assert owner.verify_native_cpu_probe_terminal(observed).succeeded


@pytest.mark.parametrize("fault", ["unit", "pid", "cgroup", "extra_process", "start"])
def test_process_drift_prevents_acknowledgement(
    process: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    report, inventory, host, state = process
    observed = owner.observe_native_cpu_probe_process(report, inventory=inventory, host=host)
    if fault == "unit":
        state["unit"] = replace(state["unit"], invocation_id="c" * 32)
    elif fault == "pid":
        state["unit"] = replace(state["unit"], main_pid=124)
    elif fault == "cgroup":
        state["cgroup"] = "/another/unit"
    elif fault == "extra_process":
        state["pids"] = (123, 124)
    else:
        state["start"] += 1
    monkeypatch.setattr(
        owner.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must not signal changed process"),
    )
    with pytest.raises(ValueError):
        owner.acknowledge_native_cpu_probe(observed, report, inventory=inventory, host=host)


@pytest.mark.parametrize("fault", ["invocation", "failed", "process"])
def test_terminal_failure_or_orphan_is_not_success(process: Any, fault: str) -> None:
    report, inventory, host, state = process
    observed = owner.observe_native_cpu_probe_process(report, inventory=inventory, host=host)
    state.update(unit=terminal(), pids=())
    if fault == "invocation":
        state["unit"] = replace(terminal(), invocation_id="c" * 32)
    elif fault == "failed":
        state["unit"] = replace(terminal(), status=replace(terminal().status, exec_main_status=1))
    else:
        state["pids"] = (456,)
    with pytest.raises(ValueError, match="TERMINATION_UNCERTAIN"):
        owner.verify_native_cpu_probe_terminal(observed)
