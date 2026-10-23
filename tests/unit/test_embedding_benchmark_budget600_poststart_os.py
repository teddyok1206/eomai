"""A retired timeout is a failed original, not a live native worker or a retry grant."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    BenchmarkFailedControllerPin,
)
from eom_catalog_service import embedding_benchmark_budget600_poststart_os as subject
from eom_identifiers import sha256_bytes


def _rows(invocation: str) -> dict[str, dict[str, str]]:
    controller = dict.fromkeys(subject._COMMON + subject._SERVICE + subject._CONTROLLER, "")
    controller.update(
        Id=subject.CONTROLLER_UNIT,
        LoadState="loaded",
        ActiveState="failed",
        SubState="failed",
        FragmentPath="/run/systemd/transient/" + subject.CONTROLLER_UNIT,
        NeedDaemonReload="no",
        MainPID="0",
        ControlPID="0",
        NFileDescriptorStore="0",
        NRestarts="0",
        Restart="no",
        Result="exit-code",
        ExecMainStatus="1",
        InvocationID=invocation,
        ExecStart="argv[]=/srv/eom/conda/envs/eom-api/bin/python -I -B "
        + str(subject._SUPERVISOR)
        + " ;",
        ExecMainStartTimestampMonotonic="100",
        ExecMainExitTimestampMonotonic="200",
    )
    service = dict.fromkeys(subject._COMMON + subject._SERVICE, "")
    service.update(
        LoadState="not-found",
        ActiveState="inactive",
        SubState="dead",
        NeedDaemonReload="no",
        MainPID="0",
        ControlPID="0",
        NFileDescriptorStore="0",
        NRestarts="0",
        Restart="no",
        Result="success",
    )
    socket = dict.fromkeys(subject._COMMON, "")
    socket.update(
        LoadState="not-found",
        ActiveState="inactive",
        SubState="dead",
        NeedDaemonReload="no",
        ControlPID="0",
    )
    execution = "a" * 32
    return {
        subject.CONTROLLER_UNIT: controller,
        subject._PREFIX + execution + ".service": service
        | {"Id": subject._PREFIX + execution + ".service"},
        subject._PREFIX + execution + ".socket": socket
        | {"Id": subject._PREFIX + execution + ".socket"},
    }


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = "b" * 40
    supervisor = tmp_path / "supervisor.py"
    supervisor.write_text('SOURCE = "' + source + '"\n')
    monkeypatch.setattr(subject, "_SUPERVISOR", supervisor)
    boot = tmp_path / "boot_id"
    boot.write_text("00000000-0000-0000-0000-000000000000\n")
    monkeypatch.setattr(subject, "_BOOT", boot)
    rows = _rows("c" * 32)
    monkeypatch.setattr(subject, "_unit", lambda name, _properties: rows[name].copy())
    monkeypatch.setattr(
        subject,
        "NumericalRuntimeFileSnapshots",
        lambda _owner: SimpleNamespace(
            read=lambda path, **_kw: path.read_bytes(), assert_unchanged=lambda: None
        ),
    )
    checked = []
    monkeypatch.setattr(subject, "require_empty_native_cpu_cgroup", checked.append)
    controller = BenchmarkFailedControllerPin(
        unit=subject.CONTROLLER_UNIT,
        invocation_id="c" * 32,
        source_commit=source,
        supervisor_raw_sha256=sha256_bytes(supervisor.read_bytes()),
    )
    value = subject.CapturedBudget600PoststartMachine(
        controller,
        execution_id="a" * 32,
        native_invocation_id="d" * 32,
        owner_pid=2**31 - 1,
        expires_ns=1,
    )
    return value, rows, checked


def test_retired_budget600_timeout_is_observed_without_restart(machine):
    value, _, checked = machine
    observed = value.observe()
    assert observed.boot_id == "00000000-0000-0000-0000-000000000000"
    assert checked == [subject._PREFIX + "a" * 32 + ".service"] * 2


@pytest.mark.parametrize("fault", ("controller", "native", "socket"))
def test_changed_controller_or_reappearing_native_unit_fails(machine, fault):
    value, rows, _ = machine
    if fault == "controller":
        rows[subject.CONTROLLER_UNIT]["InvocationID"] = "e" * 32
    elif fault == "native":
        rows[subject._PREFIX + "a" * 32 + ".service"]["ActiveState"] = "active"
    else:
        rows[subject._PREFIX + "a" * 32 + ".socket"]["LoadState"] = "loaded"
    with pytest.raises(ValueError):
        value.observe()
