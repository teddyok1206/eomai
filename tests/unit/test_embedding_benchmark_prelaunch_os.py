"""Synthetic PID1/proc metadata tests; no native unit start or root observation grant."""

import subprocess
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_prelaunch_os as module

from tests.unit.embedding_benchmark_prelaunch_failure_fixtures import observation


@pytest.fixture
def machine(monkeypatch, tmp_path):
    controller = observation().controller
    execution = "7" * 32
    supervisor = (
        Path("/var/lib") / controller.unit.removesuffix(".service") / "benchmark_goal_supervisor.py"
    )
    sample = tmp_path / "stat-sample"
    sample.touch()
    real_stat = module.os.stat

    def stat(path, *args, **kwargs):
        if str(path) == "/proc/12345":
            raise FileNotFoundError()
        if path == supervisor:
            return real_stat(sample, *args, **kwargs)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "stat", stat)
    monkeypatch.setattr(module.os, "listxattr", lambda *args, **kwargs: [])
    boot = tmp_path / "boot-id"
    boot.write_text("12345678-1234-1234-1234-123456789abc\n", encoding="ascii")
    monkeypatch.setattr(module, "_BOOT", boot)
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 1001)

    class Snapshots:
        def __init__(self, uid):
            assert uid == 0
            self.reads = []
            self.checks = 0

        def read(self, path, *, sha256, maximum):
            self.reads.append((path, sha256, maximum))
            if path == supervisor:
                return f'SOURCE = "{controller.source_commit}"\n'.encode()
            return b"unit fixture"

        def assert_unchanged(self):
            self.checks += 1

    monkeypatch.setattr(module, "NumericalRuntimeFileSnapshots", Snapshots)
    native_service = module.CPU_BENCHMARK_TEMPLATE.replace(
        "@.service", "@" + execution + ".service"
    )
    native_socket = module.CPU_BENCHMARK_SOCKET.replace("@.socket", "@" + execution + ".socket")

    def unit(name, fragment):
        return dict.fromkeys(module._COMMON, "") | {
            "Id": name,
            "LoadState": "loaded",
            "ActiveState": "inactive",
            "SubState": "dead",
            "FragmentPath": fragment,
            "NeedDaemonReload": "no",
            "ControlPID": "0",
            "ActiveEnterTimestampMonotonic": "0",
            "ActiveExitTimestampMonotonic": "0",
            "InactiveExitTimestampMonotonic": "0",
        }

    service_defaults = dict.fromkeys(module._SERVICE, "0") | {"Restart": "no", "Result": "success"}
    units = {
        controller.unit: unit(controller.unit, "/run/systemd/transient/" + controller.unit)
        | service_defaults
        | {
            "InvocationID": controller.invocation_id,
            "ActiveState": "failed",
            "SubState": "failed",
            "Result": "exit-code",
            "ExecMainStatus": "1",
            "ExecMainStartTimestampMonotonic": "100",
            "ExecMainExitTimestampMonotonic": "200",
            "ExecStart": (
                f"{{ path={module._PYTHON} ; argv[]={module._PYTHON} -I -B {supervisor} ; }}"
            ),
        },
        native_service: unit(native_service, "/etc/systemd/system/" + module.CPU_BENCHMARK_TEMPLATE)
        | service_defaults,
        native_socket: unit(native_socket, "/etc/systemd/system/" + module.CPU_BENCHMARK_SOCKET),
    }
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[:2] == ("/usr/bin/systemctl", "show")
        values = units[args[2]]
        keys = [value.removeprefix("--property=") for value in args[3:]]
        assert set(values) == set(keys)
        return subprocess.CompletedProcess(
            args, 0, "".join(f"{key}={values[key]}\n" for key in keys).encode(), b""
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    capture = module.CapturedBenchmarkPrelaunchMachine(
        controller, execution_id=execution, owner_pid=12345, expires_ns=1000
    )
    return capture, units, native_service, native_socket, calls, boot


def test_fixed_metadata_read_only_snapshot_is_stable_and_hashes_small_members_once(machine):
    capture, _units, service, socket, calls, _boot = machine
    first = capture.observe()
    assert first == capture.observe()
    assert dict(first.native_service)["Id"] == service
    assert dict(first.native_socket)["Id"] == socket
    assert first.snapshot_value()["boot_id"] == first.boot_id
    assert len(capture._files.reads) == 3
    assert len(calls) == 6
    for args, kwargs in calls:
        assert args[1] == "show" and "shell" not in kwargs
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=module._ENV)
        assert "DB_PASSWORD" not in kwargs["env"]


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("Id", "other.service"),
        ("LoadState", "not-found"),
        ("ActiveState", "active"),
        ("SubState", "running"),
        ("InvocationID", "a" * 32),
        ("FragmentPath", "/tmp/unit.service"),
        ("DropInPaths", "/etc/systemd/system/override.conf"),
        ("NeedDaemonReload", "yes"),
        ("Job", "1"),
        ("ControlGroup", "/system.slice/still-running"),
        ("MainPID", "22"),
        ("ControlPID", "23"),
        ("ExecMainStartTimestampMonotonic", "12"),
        ("ExecMainExitTimestampMonotonic", "12"),
        ("NFileDescriptorStore", "1"),
        ("Restart", "always"),
        ("NRestarts", "1"),
        ("Result", "exit-code"),
        ("ActiveEnterTimestampMonotonic", "12"),
        ("ActiveExitTimestampMonotonic", "12"),
        ("InactiveExitTimestampMonotonic", "12"),
    ],
)
def test_started_drifted_or_live_native_service_is_not_absence_proof(machine, field, bad):
    capture, units, service, _socket, _calls, _boot = machine
    units[service][field] = bad
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
        capture.observe()


@pytest.mark.parametrize(
    "field", ("ControlPID", "ActiveEnterTimestampMonotonic", "InactiveExitTimestampMonotonic")
)
def test_socket_control_or_previous_activation_is_not_absence_proof(machine, field):
    capture, units, _service, socket, _calls, _boot = machine
    units[socket][field] = "4"
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
        capture.observe()


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("InvocationID", "f" * 32),
        ("MainPID", "1"),
        ("ControlPID", "1"),
        ("ExecMainStatus", "0"),
        ("ExecMainStartTimestampMonotonic", "0"),
        ("ExecMainExitTimestampMonotonic", "99"),
        ("ExecStart", "{ argv[]=/bin/sh -c something ; }"),
    ],
)
def test_wrong_or_unfinished_controller_rejected(machine, field, bad):
    capture, units, _service, _socket, _calls, _boot = machine
    units[capture.controller.unit][field] = bad
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
        capture.observe()


def test_deadline_live_owner_acl_and_changed_runtime_rejected(machine, monkeypatch):
    capture, _units, _service, _socket, _calls, _boot = machine
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 1000)
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
        capture.observe()
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 1001)
    real_stat = module.os.stat

    def live_owner(path, *args, **kwargs):
        if str(path) == "/proc/12345":
            return real_stat("/proc/1", *args, **kwargs)
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "stat", live_owner)
        with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_OWNER_STILL_PRESENT"):
            capture.observe()
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "listxattr", lambda *args, **kwargs: ["system.posix_acl_access"])
        with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
            capture.observe()

    def changed():
        raise ValueError("INSTALLED_RUNTIME_FILE_CHANGED")

    monkeypatch.setattr(capture._files, "assert_unchanged", changed)
    with pytest.raises(ValueError, match="INSTALLED_RUNTIME_FILE_CHANGED"):
        capture.observe()


@pytest.mark.parametrize("bad", (b"", b"f" * 128, b"not-a-boot-id\n", b"\xff" * 36 + b"\n"))
def test_boot_metadata_bounded_and_validated(machine, bad):
    capture, _units, _service, _socket, _calls, boot = machine
    boot.write_bytes(bad)
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
        capture.observe()


@pytest.mark.parametrize(
    "fault", ("stderr", "exit", "missing", "duplicate", "oversized", "timeout")
)
def test_pid1_failure_never_means_no_processes(machine, monkeypatch, fault):
    capture, _units, _service, _socket, _calls, _boot = machine

    def run(args, **kwargs):
        if fault == "timeout":
            raise subprocess.TimeoutExpired(args, 10)
        return subprocess.CompletedProcess(
            args,
            1 if fault == "exit" else 0,
            b"x" * 16385
            if fault == "oversized"
            else b"Id=x\nId=x\n"
            if fault == "duplicate"
            else b"",
            b"failed" if fault == "stderr" else b"",
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
        capture.observe()


@pytest.mark.parametrize(
    "raw", (b'SOURCE = "wrong"\n', b'SOURCE = "first"\nSOURCE = "second"\n', b"broken = (\n")
)
def test_supervisor_source_assignment_must_match_exact_protected_release(machine, monkeypatch, raw):
    capture = machine[0]
    snapshots = type(capture._files)
    monkeypatch.setattr(snapshots, "read", lambda *args, **kwargs: raw)
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE"):
        module.CapturedBenchmarkPrelaunchMachine(
            capture.controller, execution_id=capture.execution_id, owner_pid=12345, expires_ns=1000
        )
