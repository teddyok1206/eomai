"""Synthetic PID1/source/retirement reads; never real systemd effects or native computation."""

import os
import subprocess
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_poststart_os as module
from eom_catalog_service import embedding_benchmark_unit_control as unit_control
from eom_catalog_service.embedding_benchmark_cpu_driver import RootBenchmarkCpuRetirement
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.worker_systemd import FixedUnitStatus
from pydantic import TypeAdapter

from tests.unit.embedding_benchmark_poststart_failure_fixtures import observation
from tests.unit.embedding_device_benchmark_fixtures import owner_request, worker_invocation


@pytest.fixture
def machine(monkeypatch, tmp_path):
    seen = observation()
    controller = seen.controller
    execution = seen.execution_id
    supervisor = Path("/var/lib/eom-gpu-benchmark-synthetic/benchmark_recovery_supervisor.py")
    monkeypatch.setattr(module.os, "listxattr", lambda *_a, **_kw: [])
    boot = tmp_path / "boot"
    boot.write_bytes(b"00000000-0000-0000-0000-000000000001\n")
    monkeypatch.setattr(module, "_BOOT", boot)
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 1001)
    cgroups = []
    monkeypatch.setattr(module, "require_empty_native_cpu_cgroup", cgroups.append)
    real_stat = os.stat

    def metadata(path, *args, **kwargs):
        if str(path) == "/proc/1073741824":
            raise FileNotFoundError()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "stat", metadata)

    class Snapshots:
        def __init__(self, uid):
            assert uid == 0
            self.reads = []
            self.source = controller.source_commit
            self.changed = False

        def read(self, path, *, sha256, maximum):
            self.reads.append((path, sha256, maximum))
            return f'SOURCE = "{self.source}"\n'.encode() if path == supervisor else b"unit"

        def assert_unchanged(self):
            if self.changed:
                raise ValueError("INSTALLED_RUNTIME_FILE_CHANGED")

    monkeypatch.setattr(module, "NumericalRuntimeFileSnapshots", Snapshots)

    def dead(name, fragment, service):
        return (
            dict.fromkeys(module._COMMON + (module._SERVICE if service else ()), "")
            | {
                "Id": name,
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "SubState": "dead",
                "FragmentPath": fragment,
                "NeedDaemonReload": "no",
                "ControlPID": "0",
            }
            | (
                {
                    "MainPID": "0",
                    "NFileDescriptorStore": "0",
                    "Restart": "no",
                    "NRestarts": "0",
                    "Result": "success",
                    "ExecMainStartTimestampMonotonic": "0",
                    "ExecMainExitTimestampMonotonic": "0",
                    "ExecMainStatus": "0",
                }
                if service
                else {}
            )
        )

    native = seen.terminal.native_service
    socket = seen.terminal.native_socket
    units = {
        controller.unit: dead(controller.unit, "/run/systemd/transient/" + controller.unit, True)
        | {
            "ActiveState": "failed",
            "SubState": "failed",
            "InvocationID": controller.invocation_id,
            "Result": "exit-code",
            "ExecMainStatus": "1",
            "ExecMainStartTimestampMonotonic": "100",
            "ExecMainExitTimestampMonotonic": "200",
            "ExecStart": (
                f"{{ path={module._PYTHON} ; argv[]={module._PYTHON} -I -B {supervisor} ; }}"
            ),
        },
        native: dead(native, "/etc/systemd/system/" + unit_control.CPU_BENCHMARK_TEMPLATE, True),
        socket: dead(socket, "/etc/systemd/system/" + unit_control.CPU_BENCHMARK_SOCKET, False),
    }
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[:2] == ("/usr/bin/systemctl", "show")
        keys = tuple(v.removeprefix("--property=") for v in args[3:])
        values = units[args[2]]
        assert set(keys) == set(values)
        return subprocess.CompletedProcess(
            args, 0, "".join(f"{k}={values[k]}\n" for k in keys).encode(), b""
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    capture = module.CapturedBenchmarkPoststartMachine(
        controller,
        execution_id=execution,
        native_invocation_id=seen.terminal.native_invocation_id,
        owner_pid=2**30,
        expires_ns=1000,
    )
    return capture, units, native, socket, boot, calls, cgroups


def test_current_snapshot_reads_only_fixed_metadata_and_hashes_program_once(machine):
    captured, _units, native, _socket, _boot, calls, cgroups = machine
    assert captured.observe() == captured.observe()
    assert len(captured._files.reads) == 3 and cgroups == [native] * 3
    for args, kwargs in calls:
        assert args[1] == "show" and "shell" not in kwargs
        assert kwargs == {"capture_output": True, "check": False, "timeout": 10, "env": module._ENV}


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("Id", "other.service"),
        ("LoadState", "not-found"),
        ("ActiveState", "active"),
        ("SubState", "running"),
        ("InvocationID", "f" * 32),
        ("MainPID", "2"),
        ("ControlPID", "2"),
        ("NFileDescriptorStore", "1"),
        ("ControlGroup", "/still-live"),
        ("DropInPaths", "/override"),
        ("NeedDaemonReload", "yes"),
        ("Job", "1"),
        ("Restart", "always"),
        ("NRestarts", "1"),
        ("Result", "timeout"),
    ),
)
def test_native_live_changed_or_uncertain_metadata_is_not_retired(machine, field, bad):
    captured, units, native, _socket, _boot, _calls, _cgroups = machine
    units[native][field] = bad
    with pytest.raises(ValueError):
        captured.observe()


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("InvocationID", "f" * 32),
        ("MainPID", "2"),
        ("ControlPID", "2"),
        ("ExecMainStatus", "0"),
        ("ExecMainStartTimestampMonotonic", "0"),
        ("ExecMainExitTimestampMonotonic", "99"),
        ("NFileDescriptorStore", "1"),
        ("ExecStart", "{ argv[]=/bin/sh -c unsafe ; }"),
    ),
)
def test_original_failed_controller_identity_is_not_replaceable(machine, field, bad):
    captured, units, _native, _socket, _boot, _calls, _cgroups = machine
    units[captured.controller.unit][field] = bad
    with pytest.raises(ValueError):
        captured.observe()


@pytest.mark.parametrize("field", ("ActiveState", "ControlPID", "ControlGroup", "Job"))
def test_socket_must_be_stopped_and_empty(machine, field):
    captured, units, _native, socket, _boot, _calls, _cgroups = machine
    units[socket][field] = "active"
    with pytest.raises(ValueError):
        captured.observe()


def test_deadline_owner_birth_source_and_cgroup_changes_fail_closed(machine, monkeypatch):
    captured, _units, _native, _socket, _boot, _calls, _cgroups = machine
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 1000)
    with pytest.raises(ValueError):
        captured.observe()
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 1001)
    real_stat = module.os.stat
    with monkeypatch.context() as patch:

        def alive(path, *args, **kwargs):
            return real_stat(
                "/proc/1" if str(path) == "/proc/1073741824" else path, *args, **kwargs
            )

        patch.setattr(module.os, "stat", alive)
        with pytest.raises(ValueError, match="OWNER_STILL_PRESENT"):
            captured.observe()
    with monkeypatch.context() as patch:
        patch.setattr(
            module,
            "require_empty_native_cpu_cgroup",
            lambda _: (_ for _ in ()).throw(ValueError("CGROUP_NOT_EMPTY")),
        )
        with pytest.raises(ValueError, match="CGROUP_NOT_EMPTY"):
            captured.observe()
    captured._files.changed = True
    with pytest.raises(ValueError, match="FILE_CHANGED"):
        captured.observe()


@pytest.mark.parametrize("raw", (b"", b"not a boot id\n", b"a" * 128, b"\xff" * 36 + b"\n"))
def test_boot_identity_is_bounded_and_never_invented(machine, raw):
    captured, _units, _native, _socket, boot, _calls, _cgroups = machine
    boot.write_bytes(raw)
    with pytest.raises((ValueError, UnicodeError)):
        captured.observe()


@pytest.fixture
def retired(tmp_path, monkeypatch):
    root = tmp_path / "lifetimes"
    root.mkdir(mode=0o700)
    request, invocation = owner_request(), worker_invocation(1)
    native = "c" * 32
    unit = "eom-embedding-benchmark-cpu@" + invocation.execution_id + ".service"
    phase = root / unit / native / "retirement"
    phase.mkdir(parents=True, mode=0o700)
    for path in (root, phase.parent.parent, phase.parent, phase):
        path.chmod(0o700)
    original = CpuUnitObservation(
        FixedUnitStatus("loaded", "failed", "failed", "timeout", 2, 15, 150, False),
        0,
        200,
        native,
        "/etc/systemd/system/" + unit_control.CPU_BENCHMARK_TEMPLATE,
        "",
    )
    retirement = RootBenchmarkCpuRetirement(
        original, StoppedGpuUnit("loaded", "", 0), "2026-10-22T12:00:00Z"
    )
    document = {
        "event": "BENCHMARK_CPU_RETIRED_NOT_ADMITTED",
        "execution_id": invocation.execution_id,
        "job_id": invocation.job_id,
        "invocation_sha256": invocation.invocation_sha256,
        "observation": TypeAdapter(RootBenchmarkCpuRetirement).dump_python(retirement, mode="json"),
        "admission_granted": False,
    }
    raw = canonical_json_bytes(document)
    result = phase / "result.json"
    result.write_bytes(raw)
    result.chmod(0o400)
    intent = phase / "intent.json"
    intent.write_bytes(
        canonical_json_bytes(
            document
            | {
                "event": "BENCHMARK_CPU_RETIREMENT_INTENT",
                "observation": TypeAdapter(CpuUnitObservation).dump_python(original, mode="json"),
            }
        )
    )
    intent.chmod(0o400)
    monkeypatch.setattr(module, "BENCHMARK_LIFETIME_ROOT", root)
    monkeypatch.setattr(module, "_ROOT_UID", os.getuid())
    monkeypatch.setattr(module, "_ROOT_GID", os.getgid())
    return request, invocation, result, document, root


def test_root_reader_pins_actual_saved_original_timeout_and_intent_without_effects(retired):
    request, invocation, path, _document, _root = retired
    captured = module.read_root_poststart_retirement(request, invocation)
    assert captured.raw_sha256 == sha256_bytes(path.read_bytes())
    assert captured.native_invocation_id == "c" * 32
    assert captured.retirement.original_terminal.status.result == "timeout"
    captured.assert_current()


@pytest.mark.parametrize(
    "fault",
    (
        "job",
        "execution",
        "invocation",
        "event",
        "admission",
        "extra",
        "succeeded",
        "no-start",
        "bad-native",
        "descriptors",
        "timezone",
        "bool",
    ),
)
def test_foreign_fabricated_uncertain_or_coerced_original_retirement_is_rejected(retired, fault):
    request, invocation, path, document, _root = retired
    if fault in {"job", "execution", "invocation", "event"}:
        field = {
            "job": "job_id",
            "execution": "execution_id",
            "invocation": "invocation_sha256",
            "event": "event",
        }[fault]
        document[field] = "foreign"
    elif fault == "admission":
        document["admission_granted"] = True
    elif fault == "extra":
        document["observation"]["permission"] = "ADMIN"
    elif fault == "succeeded":
        document["observation"]["original_terminal"]["status"]["result"] = "success"
    elif fault == "no-start":
        document["observation"]["original_terminal"]["status"]["exec_main_started_monotonic"] = 0
        document["observation"]["original_terminal"]["status"]["exec_main_code"] = 0
    elif fault == "bad-native":
        document["observation"]["original_terminal"]["invocation_id"] = "f" * 32
    elif fault == "descriptors":
        document["observation"]["stopped_unit"]["stored_descriptors"] = 1
    elif fault == "timezone":
        document["observation"]["observed_at_utc"] = "2026-10-22T21:00:00+09:00"
    else:
        document["observation"]["original_terminal"]["main_pid"] = False
    path.chmod(0o600)
    path.write_bytes(canonical_json_bytes(document))
    path.chmod(0o400)
    with pytest.raises(ValueError):
        module.read_root_poststart_retirement(request, invocation)


@pytest.mark.parametrize(
    "fault",
    ("missing-intent", "intent-mismatch", "mode", "hardlink", "symlink", "multiple", "late"),
)
def test_private_retirement_origin_membership_and_late_identity_are_protected(retired, fault):
    request, invocation, path, _document, root = retired
    if fault == "missing-intent":
        path.with_name("intent.json").unlink()
    elif fault == "intent-mismatch":
        intent = path.with_name("intent.json")
        intent.chmod(0o600)
        intent.write_bytes(b"{}")
        intent.chmod(0o400)
    elif fault == "mode":
        path.chmod(0o440)
    elif fault == "hardlink":
        os.link(path, root / "untrusted.alias")
    elif fault == "symlink":
        saved = root / "saved.json"
        path.rename(saved)
        path.symlink_to(saved)
    elif fault == "multiple":
        (path.parent.parent.parent / ("f" * 32)).mkdir(mode=0o700)
    else:
        captured = module.read_root_poststart_retirement(request, invocation)
        path.chmod(0o600)
        path.chmod(0o400)
        with pytest.raises(ValueError):
            captured.assert_current()
        return
    with pytest.raises((ValueError, OSError)):
        module.read_root_poststart_retirement(request, invocation)
