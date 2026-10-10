"""Source/fake verification only: never starts a service, installs, or runs a model."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import io
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from eom_catalog_service import inference_transfer_cpu_verifier as probe
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import inference_transfer_cpu_installation as installation
from eom_orchestrator import inference_transfer_cpu_systemd as cpu

from tests.unit.inference_transfer_fixtures import embedding_model

ROOT = Path(__file__).resolve().parents[2]


def snapshot_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "snapshot_installer", ROOT / "scripts/embedding/_install_experiment_snapshot.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def properties(template: str, *, root: bool = False) -> dict[str, str]:
    result = dict.fromkeys(installation._SANDBOX, "")
    result.update(
        {
            "FragmentPath": "/etc/systemd/system/" + template,
            "NeedDaemonReload": "no",
            "User": "root" if root else "eom-embedding-experiment",
            "Group": "root" if root else "eom-embedding-experiment",
            "NoNewPrivileges": "yes",
            "PrivateNetwork": "yes",
            "PrivateDevices": "yes",
            "ProtectSystem": "strict",
            "RestrictAddressFamilies": "AF_UNIX",
        }
    )
    if root:
        result.update(
            {
                "CapabilityBoundingSet": "cap_chown cap_dac_read_search",
                "ReadWritePaths": "/run/eom-embedding-experiments",
            }
        )
    return result


def test_effective_probe_policy_matches_main_and_root_prepare_is_separate() -> None:
    installation.validate_effective_policies(
        properties(cpu.CPU_TEMPLATE),
        properties(installation.PROBE),
        properties(cpu.PREPARE_TEMPLATE, root=True),
    )


@pytest.mark.parametrize(
    "template,unit,root",
    [
        (
            cpu.CPU_TEMPLATE,
            "eom-embedding-experiment@" + installation._INSTANCE + ".service",
            False,
        ),
        (installation.PROBE, installation.PROBE, False),
        (
            cpu.PREPARE_TEMPLATE,
            "eom-embedding-experiment-prepare@" + installation._INSTANCE + ".service",
            True,
        ),
    ],
)
@pytest.mark.parametrize(
    "omitted", [(), ("ExecStartPre",), ("ExecStartPost",), ("ExecStartPre", "ExecStartPost")]
)
def test_systemctl_fixed_templates_normalize_only_omitted_empty_exec_arrays(
    monkeypatch: pytest.MonkeyPatch, template: str, unit: str, root: bool, omitted: tuple[str, ...]
) -> None:
    expected = properties(template, root=root)
    body = "\n".join(f"{key}={value}" for key, value in expected.items() if key not in omitted)

    def run(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert argv[:4] == (installation.SYSTEMCTL, "--no-pager", "show", unit)
        assert kwargs["timeout"] == 15
        return subprocess.CompletedProcess(argv, 0, body.encode(), b"")

    monkeypatch.setattr(installation.subprocess, "run", run)
    assert installation._properties(unit) == expected


@pytest.mark.parametrize(
    "missing",
    [key for key in installation._SANDBOX if key not in {"ExecStartPre", "ExecStartPost"}],
)
def test_systemctl_other_missing_property_never_normalized(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    expected = properties(installation.PROBE)
    body = "\n".join(f"{key}={value}" for key, value in expected.items() if key != missing)
    monkeypatch.setattr(
        installation.subprocess,
        "run",
        lambda argv, **_k: subprocess.CompletedProcess(argv, 0, body.encode(), b""),
    )
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        installation._properties(installation.PROBE)


@pytest.mark.parametrize(
    "change",
    [
        {"FragmentPath": "/etc/systemd/system/another.service"},
        {"DropInPaths": "/etc/systemd/system/override.conf"},
        {"NeedDaemonReload": "yes"},
    ],
)
def test_systemctl_empty_exec_normalization_requires_exact_effective_template(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, str]
) -> None:
    expected = properties(installation.PROBE) | change
    body = "\n".join(
        f"{key}={value}"
        for key, value in expected.items()
        if key not in {"ExecStartPre", "ExecStartPost"}
    )
    monkeypatch.setattr(
        installation.subprocess,
        "run",
        lambda argv, **_k: subprocess.CompletedProcess(argv, 0, body.encode(), b""),
    )
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        installation._properties(installation.PROBE)


@pytest.mark.parametrize("extra", ["User=root", "UnknownProperty=", "invalid-line"])
def test_systemctl_property_duplicate_unknown_or_malformed_rejected(
    monkeypatch: pytest.MonkeyPatch, extra: str
) -> None:
    body = "\n".join(f"{key}={value}" for key, value in properties(installation.PROBE).items())
    monkeypatch.setattr(
        installation.subprocess,
        "run",
        lambda argv, **_k: subprocess.CompletedProcess(
            argv, 0, (body + "\n" + extra).encode(), b""
        ),
    )
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        installation._properties(installation.PROBE)


def test_systemctl_unknown_unit_rejected_before_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        installation.subprocess, "run", lambda *_a, **_k: pytest.fail("only fixed probe units")
    )
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        installation._properties("arbitrary.service")


def test_systemctl_nonempty_exec_array_is_preserved_not_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = properties(installation.PROBE) | {"ExecStartPre": "{ path=/unapproved ; }"}
    body = "\n".join(f"{key}={value}" for key, value in expected.items() if key != "ExecStartPost")
    monkeypatch.setattr(
        installation.subprocess,
        "run",
        lambda argv, **_k: subprocess.CompletedProcess(argv, 0, body.encode(), b""),
    )
    assert installation._properties(installation.PROBE) == expected
    with pytest.raises(ValueError, match="POLICY_MISMATCH"):
        installation.validate_effective_policies(
            properties(cpu.CPU_TEMPLATE), expected, properties(cpu.PREPARE_TEMPLATE, root=True)
        )


def test_policy_read_always_follows_pinned_template_and_polkit_byte_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[str] = []
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installation, "require_cpu_runtime", lambda: checked.append("main/prepare"))
    monkeypatch.setattr(
        installation, "_checked_file", lambda path, _hash: checked.append(path.name)
    )

    def read(unit: str) -> dict[str, str]:
        assert checked == ["main/prepare", installation.PROBE, installation.POLKIT.name]
        template = installation.PROBE
        if unit.startswith("eom-embedding-experiment-prepare@"):
            template = cpu.PREPARE_TEMPLATE
        elif unit.startswith("eom-embedding-experiment@"):
            template = cpu.CPU_TEMPLATE
        return properties(template, root=template == cpu.PREPARE_TEMPLATE)

    def stop_before_any_launch() -> None:
        raise ValueError("INFERENCE_CPU_PROBE_POLKIT_SCOPE_INVALID")

    monkeypatch.setattr(installation, "_properties", read)
    monkeypatch.setattr(installation, "verify_polkit_scope", stop_before_any_launch)
    monkeypatch.setattr(
        installation.subprocess, "run", lambda *_a, **_k: pytest.fail("no unit started")
    )
    with pytest.raises(ValueError, match="POLKIT_SCOPE_INVALID"):
        installation.verify_fixed_cpu_installation()


@pytest.mark.parametrize("code", sorted(installation._SAFE_FAILURE_CODES))
def test_driver_cli_reports_only_literal_safe_failure_code(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str], code: str
) -> None:
    def fail() -> None:
        raise ValueError(code)

    monkeypatch.setattr(installation, "verify_fixed_cpu_installation", fail)
    assert installation.main() == 1
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == f"CPU_ISOLATION_PROBE=REJECTED ERROR_CODE={code}\n"


@pytest.mark.parametrize(
    "failure,code",
    [
        (ValueError("private document content"), "INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE"),
        (
            ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID\nprivate"),
            "INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE",
        ),
        (RuntimeError("private runtime content"), "INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE"),
        (OSError("private path"), "INFERENCE_CPU_PROBE_OS_UNAVAILABLE"),
        (
            subprocess.TimeoutExpired("private command", 15),
            "INFERENCE_CPU_PROBE_SUBPROCESS_TIMEOUT",
        ),
    ],
)
def test_driver_cli_redacts_unknown_exception_payloads(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    failure: Exception,
    code: str,
) -> None:
    def fail() -> None:
        raise failure

    monkeypatch.setattr(installation, "verify_fixed_cpu_installation", fail)
    assert installation.main() == 1
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == f"CPU_ISOLATION_PROBE=REJECTED ERROR_CODE={code}\n"


@pytest.mark.parametrize(
    "key,value",
    [
        ("DropInPaths", "/etc/override.conf"),
        ("NeedDaemonReload", "yes"),
        ("PrivateNetwork", "no"),
        ("ProtectSystem", "full"),
        ("CapabilityBoundingSet", "cap_sys_admin"),
        ("SupplementaryGroups", "eom"),
        ("User", "eom"),
        ("BindPaths", "/mnt/nas"),
        ("ReadWritePaths", "/"),
    ],
)
def test_effective_policy_drift_rejects(key: str, value: str) -> None:
    observed = properties(installation.PROBE) | {key: value}
    with pytest.raises(ValueError, match="POLICY"):
        installation.validate_effective_policies(
            properties(cpu.CPU_TEMPLATE), observed, properties(cpu.PREPARE_TEMPLATE, root=True)
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("CapabilityBoundingSet", "cap_sys_admin"),
        ("User", "eom"),
        ("ReadWritePaths", "/mnt/nas"),
        ("SupplementaryGroups", "docker"),
    ],
)
def test_prepare_privileged_effective_policy_rejects(key: str, value: str) -> None:
    with pytest.raises(ValueError, match="PREPARE_POLICY"):
        installation.validate_effective_policies(
            properties(cpu.CPU_TEMPLATE),
            properties(installation.PROBE),
            properties(cpu.PREPARE_TEMPLATE, root=True) | {key: value},
        )


def test_probe_main_security_directives_identical_and_fixed_conda_paths() -> None:
    def parse(path: Path) -> dict[str, tuple[str, ...]]:
        rows: dict[str, list[str]] = {}
        for line in path.read_text().splitlines():
            key, delimiter, value = line.partition("=")
            if delimiter:
                rows.setdefault(key, []).append(value)
        return {key: tuple(value) for key, value in rows.items()}

    main = parse(ROOT / "infra/systemd" / cpu.CPU_TEMPLATE)
    verifier = parse(ROOT / "infra/systemd" / installation.PROBE)
    intentional = {
        "Description",
        "Requires",
        "After",
        "ExecStart",
        "StandardInput",
        "StandardOutput",
    }
    assert {key: value for key, value in main.items() if key not in intentional} == {
        key: value for key, value in verifier.items() if key not in intentional
    }
    assert str(cpu.CPU_PYTHON) in main["ExecStart"][0]
    assert cpu.CPU_PYTHON == cpu.PREPARE_PYTHON
    assert "/opt/eom/embedding-models" in main["ReadOnlyPaths"]
    assert (
        hashlib.sha256((ROOT / "infra/systemd" / installation.PROBE).read_bytes()).hexdigest()
        == installation.PROBE_SHA256
    )
    assert (
        hashlib.sha256((ROOT / "infra/polkit/50-eom-worker-units.rules").read_bytes()).hexdigest()
        == installation.POLKIT_SHA256
    )


def test_probe_never_reads_forbidden_opened_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    closed: list[int] = []
    monkeypatch.setattr(probe.os, "open", lambda path, flags: opened.append(str(path)) or 73)
    monkeypatch.setattr(probe.os, "close", closed.append)
    monkeypatch.setattr(probe.os, "read", lambda *_a: pytest.fail("no forbidden content read"))
    with pytest.raises(ValueError, match="FORBIDDEN_ACCESS"):
        probe.denied_file(Path("/etc/eom"))
    assert opened == ["/etc/eom"] and closed == [73]


@pytest.mark.parametrize(
    "exception,expected", [(PermissionError, "DENIED"), (FileNotFoundError, "ABSENT_IN_SANDBOX")]
)
def test_absence_is_not_falsely_called_permission_denial(
    monkeypatch: pytest.MonkeyPatch, exception: type[OSError], expected: str
) -> None:
    def denied(*_a: Any) -> Any:
        raise exception()

    monkeypatch.setattr(probe.os, "open", denied)
    assert probe.denied_file(Path("/dev/nvidia0")) == expected


@pytest.mark.parametrize(
    "code,accepted",
    [
        (errno.EAFNOSUPPORT, True),
        (errno.EPERM, True),
        (errno.EACCES, True),
        (errno.EMFILE, False),
        (errno.ENOMEM, False),
    ],
)
def test_network_negative_requires_policy_errno_not_resource_failure(
    monkeypatch: pytest.MonkeyPatch, code: int, accepted: bool
) -> None:
    monkeypatch.setattr(probe.os, "listdir", lambda _p: ["lo"])

    def denied(*_a: Any, **_k: Any) -> Any:
        raise OSError(code, "not emitted")

    monkeypatch.setattr(probe.socket, "socket", denied)
    if accepted:
        probe.verify_no_network()
    else:
        with pytest.raises(ValueError, match="NETWORK_CHECK_FAILED"):
            probe.verify_no_network()


def test_probe_manifest_materialization_bounded_and_no_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = embedding_model("intfloat/multilingual-e5-small")
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical_json_bytes(spec.model_dump(mode="json")))
    monkeypatch.setattr(probe, "_protected", lambda value: value)
    assert probe.read_cpu_model_spec(tmp_path) == spec
    path.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(ValueError, match="MODEL_MISMATCH"):
        probe.read_cpu_model_spec(tmp_path)
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(ValueError, match="MODEL_MISMATCH"):
        probe.read_cpu_model_spec(tmp_path)
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(OSError):
        probe.read_cpu_model_spec(tmp_path)


def test_probe_failure_redacts_private_exception(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    def fail() -> Any:
        print("private runtime diagnostic")
        raise ValueError("secret request content")

    monkeypatch.setattr(probe, "run_probe", fail)
    assert probe.main() == 1
    captured = capfd.readouterr()
    assert (
        captured.out
        == (
            "INFERENCE_CPU_ISOLATION_PROBE_REJECTED STAGE=PROBE "
            "ERROR_CODE=INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE\n"
        )
        and captured.err == ""
    )


@pytest.mark.parametrize(
    "name,stage",
    [
        ("_verify_runtime_metadata", "RUNTIME_METADATA"),
        ("_verify_runtime_imports", "RUNTIME_IMPORTS"),
        ("_verify_runtime_record", "RUNTIME_RECORD"),
        ("_verify_runtime_requirements", "RUNTIME_REQUIREMENTS"),
    ],
)
def test_runtime_failure_reports_exact_fixed_stage_without_import_or_execution(
    monkeypatch: pytest.MonkeyPatch, name: str, stage: str
) -> None:
    order = (
        "_verify_runtime_metadata",
        "_verify_runtime_imports",
        "_verify_runtime_record",
        "_verify_runtime_requirements",
    )
    observed: list[str] = []

    def check(member: str) -> None:
        observed.append(member)
        if member == name:
            raise RuntimeError("private module path/content")

    for member in order:
        monkeypatch.setattr(probe, member, lambda member=member: check(member))
    with pytest.raises(probe.CpuProbeFailure) as failure:
        probe.verify_installed_runtime()
    assert failure.value.stage == stage
    assert failure.value.code == "INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE"
    assert observed == list(order[: order.index(name) + 1])


def valid_probe_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake OS/runtime/model resolution only; neither imports numerical libs nor launches them."""
    spec = embedding_model("intfloat/multilingual-e5-small")
    for name in ("require_cpu_identity", "verify_installed_runtime", "verify_no_network"):
        monkeypatch.setattr(probe, name, lambda: None)
    monkeypatch.setattr(probe, "read_cpu_model_spec", lambda _root: spec)
    monkeypatch.setattr(probe, "MODEL_MANIFEST", spec.manifest_sha256)
    monkeypatch.setattr(probe, "verify_local_embedding_model_snapshot", lambda *_a: None)
    monkeypatch.setattr(probe, "denied_file", lambda _path: "DENIED")
    monkeypatch.setattr(probe, "denied_socket", lambda _path: "DENIED")


@pytest.mark.parametrize(
    "name,stage",
    [
        ("require_cpu_identity", "IDENTITY"),
        ("verify_installed_runtime", "RUNTIME_METADATA"),
        ("verify_no_network", "NETWORK"),
        ("read_cpu_model_spec", "MODEL_SPEC"),
        ("verify_local_embedding_model_snapshot", "MODEL_SNAPSHOT"),
        ("denied_file", "FILE_DENIAL"),
        ("denied_socket", "SOCKET_DENIAL"),
    ],
)
def test_probe_main_reports_stage_and_fixed_denial_without_partial_pass_or_private_payload(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    name: str,
    stage: str,
) -> None:
    valid_probe_fixture(monkeypatch)

    def fail(*_args: Any) -> Any:
        print("private library diagnostic /protected/path")
        raise PermissionError(errno.EACCES, "private source path and content")

    monkeypatch.setattr(probe, name, fail)
    assert probe.main() == 1
    captured = capfd.readouterr()
    assert (
        captured.out
        == (
            f"INFERENCE_CPU_ISOLATION_PROBE_REJECTED STAGE={stage} "
            "ERROR_CODE=INFERENCE_CPU_PROBE_ACCESS_DENIED\n"
        )
        and captured.err == ""
    )


@pytest.mark.parametrize(
    "failure,code",
    [
        (ValueError("INFERENCE_CPU_PROBE_MODEL_MISMATCH"), "INFERENCE_CPU_PROBE_MODEL_MISMATCH"),
        (ValueError("private content"), "INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE"),
        (
            ValueError("INFERENCE_CPU_PROBE_RECORD_INVALID\nprivate"),
            "INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE",
        ),
        (FileNotFoundError("private path"), "INFERENCE_CPU_PROBE_INPUT_ABSENT"),
        (ImportError("private module path"), "INFERENCE_CPU_PROBE_DEPENDENCY_UNAVAILABLE"),
        (subprocess.TimeoutExpired("private argv", 60), "INFERENCE_CPU_PROBE_SUBPROCESS_TIMEOUT"),
        (
            OSError(errno.EAGAIN, "private resource diagnostic"),
            "INFERENCE_CPU_PROBE_RESOURCE_UNAVAILABLE",
        ),
        (
            OSError(errno.EINVAL, "private resource diagnostic"),
            "INFERENCE_CPU_PROBE_OS_UNAVAILABLE",
        ),
    ],
)
def test_probe_failure_code_mapping_has_closed_safe_output(failure: Exception, code: str) -> None:
    observed = probe._failure("RUNTIME_IMPORTS", failure)
    assert observed.stage == "RUNTIME_IMPORTS" and observed.code == code


def test_probe_nested_runtime_stage_is_retained_and_forged_labels_redacted(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    valid_probe_fixture(monkeypatch)
    failure = probe.CpuProbeFailure(
        "RUNTIME_REQUIREMENTS", "INFERENCE_CPU_PROBE_RESOURCE_UNAVAILABLE"
    )

    def fail() -> None:
        raise failure

    monkeypatch.setattr(probe, "verify_installed_runtime", fail)
    assert probe.main() == 1
    assert capfd.readouterr().out == (
        "INFERENCE_CPU_ISOLATION_PROBE_REJECTED STAGE=RUNTIME_REQUIREMENTS "
        "ERROR_CODE=INFERENCE_CPU_PROBE_RESOURCE_UNAVAILABLE\n"
    )
    failure.stage = "private /path"
    failure.code = "private content"
    assert probe.main() == 1
    assert capfd.readouterr().out == (
        "INFERENCE_CPU_ISOLATION_PROBE_REJECTED STAGE=RUNTIME_METADATA "
        "ERROR_CODE=INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE\n"
    )


def test_probe_fake_success_keeps_zero_forward_labels_only(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    valid_probe_fixture(monkeypatch)
    assert probe.main() == 0
    observed = capfd.readouterr()
    assert observed.err == "" and observed.out.splitlines() == [
        "IDENTITY=PASS",
        "RUNTIME_RECORD=PASS",
        "NETWORK=PASS",
        "MODEL_SNAPSHOT=PASS",
        *(f"{label}=DENIED" for label, _path in probe.DENIED_FILES),
        *(f"{label}=DENIED" for label, _path in probe.DENIED_SOCKETS),
        "MODEL_FORWARD_COUNT=0",
    ]


def test_fixed_polkit_probe_tests_scope_without_unit_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    subjects: list[str] = []

    @contextmanager
    def temporary_subject(user: str) -> Any:
        subjects.append(user)
        uid = 979 if user == "eom-embedding-experiment" else 990
        yield installation.PolkitSubject(123, 456, uid, 122)

    def run(argv: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0 if len(calls) == 1 else 1)

    monkeypatch.setattr(installation.subprocess, "run", run)
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installation, "_temporary_polkit_subject", temporary_subject)
    installation.verify_polkit_scope()
    assert len(calls) == 6 and all(call[0] == "/usr/bin/pkcheck" for call in calls)
    assert subjects == ["eom-workflow-runner"] * 5 + ["eom-embedding-experiment"]
    assert all(call[3:5] == ("--process", "123,456,990") for call in calls[:5])
    assert calls[5][3:5] == ("--process", "123,456,979")
    assert all("systemctl" not in repr(call) and "/usr/sbin/runuser" not in call for call in calls)


@pytest.mark.parametrize("returncode", [2, 126, 127])
def test_polkit_check_error_is_not_interpreted_as_expected_denial(
    monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    @contextmanager
    def subject(_user: str) -> Any:
        yield installation.PolkitSubject(123, 456, 990, 122)

    calls = 0

    def run(argv: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0 if calls == 1 else returncode)

    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installation, "_temporary_polkit_subject", subject)
    monkeypatch.setattr(installation.subprocess, "run", run)
    with pytest.raises(ValueError, match="POLKIT_SCOPE_INVALID"):
        installation.verify_polkit_scope()


def kernel_process_fixture(
    *, pid: int = 123, parent: int = 122, clock: int = 456, uid: int = 990
) -> dict[str, str]:
    fields = ["S", str(parent), *(["0"] * 17), str(clock)]
    return {
        f"/proc/{pid}/stat": f"{pid} (cat) " + " ".join(fields),
        f"/proc/{pid}/status": f"Name:\tcat\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
    }


def test_polkit_subject_is_kernel_uid_parent_starttime_not_root_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = kernel_process_fixture()
    monkeypatch.setattr(Path, "read_text", lambda path, **_k: fixture[str(path)])
    subject = installation._kernel_subject(123, uid=990, parent_pid=122)
    assert subject == installation.PolkitSubject(123, 456, 990, 122)
    assert subject.process_argument == "123,456,990"


@pytest.mark.parametrize(
    "kind", ["uid", "parent", "clock", "stat_pid", "duplicate_uid", "malformed"]
)
def test_polkit_subject_kernel_mismatch_rejected(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    fixture = kernel_process_fixture(
        uid=0 if kind == "uid" else 990,
        parent=999 if kind == "parent" else 122,
        clock=0 if kind == "clock" else 456,
    )
    if kind == "stat_pid":
        fixture["/proc/123/stat"] = fixture["/proc/123/stat"].replace("123 (cat)", "999 (cat)")
    elif kind == "duplicate_uid":
        fixture["/proc/123/status"] += "Uid:\t990\t990\t990\t990\n"
    elif kind == "malformed":
        fixture["/proc/123/stat"] = "malformed"
    monkeypatch.setattr(Path, "read_text", lambda path, **_k: fixture[str(path)])
    with pytest.raises(ValueError, match="SUBJECT_INVALID"):
        installation._kernel_subject(123, uid=990, parent_pid=122)


@pytest.mark.parametrize(
    "payload,valid",
    [(b"123\n", True), (b"0\n", False), (b"123\n456\n", False), (b"1" * 65, False), (b"", False)],
)
def test_polkit_subject_pid_pipe_bounded_exact_line(payload: bytes, valid: bool) -> None:
    reader, writer = os.pipe()
    try:
        os.write(writer, payload)
        os.close(writer)
        writer = -1
        if valid:
            assert installation._read_subject_pid(reader) == 123
        else:
            with pytest.raises(ValueError, match="SUBJECT_INVALID"):
                installation._read_subject_pid(reader)
    finally:
        if writer >= 0:
            os.close(writer)
        os.close(reader)


def test_owned_subject_eof_cleanup_idempotent_no_reported_pid_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO()

        def wait(self, *, timeout: int) -> int:
            assert timeout == 5
            calls.append("wait")
            return 0

        def kill(self) -> None:
            pytest.fail("fixed cat should terminate on stdin EOF")

    monkeypatch.setattr(
        installation.os, "kill", lambda *_a, **_k: pytest.fail("no arbitrary PID signal")
    )
    process = Process()
    installation._close_owned_subject(process)  # type: ignore[arg-type]
    installation._close_owned_subject(process)  # type: ignore[arg-type]
    assert calls == ["wait", "wait"] and process.stdin.closed and process.stdout.closed


def test_owned_subject_cleanup_timeout_kills_only_popen_wrapper_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO()

        def wait(self, *, timeout: int) -> int:
            assert timeout == 5
            calls.append("wait")
            if len(calls) == 1:
                raise subprocess.TimeoutExpired("owned-runuser", 5)
            return 0

        def kill(self) -> None:
            calls.append("owned-wrapper-kill")

    monkeypatch.setattr(
        installation.os, "kill", lambda *_a, **_k: pytest.fail("no reported PID signal")
    )
    process = Process()
    installation._close_owned_subject(process)  # type: ignore[arg-type]
    installation._close_owned_subject(process)  # type: ignore[arg-type]
    assert calls == ["wait", "owned-wrapper-kill", "wait", "wait"]


def test_polkit_pid_pipe_select_timeout_fails_before_any_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Unready:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def register(self, _stream: int, _event: int) -> None:
            pass

        def select(self, timeout: float) -> list[Any]:
            assert 0 < timeout <= 5
            return []

    monkeypatch.setattr(installation.selectors, "DefaultSelector", Unready)
    monkeypatch.setattr(installation.os, "read", lambda *_a: pytest.fail("unready FD not read"))
    with pytest.raises(ValueError, match="SUBJECT_UNAVAILABLE"):
        installation._read_subject_pid(7)


def test_temporary_subject_owned_process_fixed_command_kernel_revalidated_and_cleaned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    process = SimpleNamespace(pid=122, stdout=SimpleNamespace(fileno=lambda: 7), poll=lambda: None)
    subject = installation.PolkitSubject(123, 456, 990, 122)
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installation.pwd, "getpwnam", lambda user: SimpleNamespace(pw_uid=990))

    def launch(argv: tuple[str, ...], **kwargs: Any) -> Any:
        calls.append((argv, kwargs))
        return process

    monkeypatch.setattr(installation.subprocess, "Popen", launch)
    monkeypatch.setattr(
        installation,
        "_read_subject_pid",
        lambda fd: 123 if fd == 7 else pytest.fail("unexpected pipe"),
    )
    checks: list[Any] = []
    monkeypatch.setattr(
        installation,
        "_kernel_subject",
        lambda pid, **kwargs: checks.append((pid, kwargs)) or subject,
    )
    closed: list[Any] = []
    monkeypatch.setattr(installation, "_close_owned_subject", closed.append)
    with installation._temporary_polkit_subject("eom-workflow-runner") as actual:
        assert actual == subject
    assert calls[0][0] == (
        "/usr/sbin/runuser",
        "-u",
        "eom-workflow-runner",
        "--",
        "/bin/sh",
        "-c",
        'printf "%s\\n" "$$"; exec /bin/cat',
    )
    assert len(checks) == 2 and all(
        value == (123, {"uid": 990, "parent_pid": 122}) for value in checks
    )
    assert closed == [process] and calls[0][1]["stdin"] == subprocess.PIPE


def test_no_privileged_probe_or_source_execution_in_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installation.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        installation.subprocess, "run", lambda *_a, **_k: pytest.fail("no root bypass")
    )
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        installation.verify_fixed_cpu_installation()


def test_source_installer_independent_hash_precedes_first_interpreter_and_no_system_python() -> (
    None
):
    source = (ROOT / "scripts/embedding/install_experiment_runtime.sh").read_text()
    first = source.index('"$PREFIX/bin/python" -I -S -B')
    assert source.index('tree_digest "$QUARANTINE"') < first
    assert source.index("EMBEDDING_RUNTIME_LINK_ESCAPE") < first
    assert source.index("EMBEDDING_INSTALLER_HASH_MISMATCH") < first
    assert "--no-preserve=links,ownership,xattr,context" in source and "cp -a" in source
    assert (
        "/usr/bin/python" not in source
        and "conda create" not in source
        and "pip install" not in source
    )
    assert 'mv -T -- "$PREFIX" "$BACKUP"' in source and 'mv -T -- "$QUARANTINE" "$PREFIX"' in source
    assert source.index('mv -T -- "$QUARANTINE" "$PREFIX"') < first
    assert source.index("record_phase STAGED_NOT_ACTIVATED") < first
    assert "rm -" not in source and "reset-failed" not in source
    subprocess.run(
        ("/bin/bash", "-n", str(ROOT / "scripts/embedding/install_experiment_runtime.sh")),
        check=True,
    )


def run_fingerprint_function(
    tmp_path: Path, *, define_only: bool = False
) -> subprocess.CompletedProcess[str]:
    """Exercise real non-root Bash parsing/behavior without fixed-prefix/privileged mutation."""
    if os.geteuid() == 0:
        pytest.skip("non-root fingerprint regression requires an unprivileged test process")
    source = (ROOT / "scripts/embedding/install_experiment_runtime.sh").read_text()
    function = source[source.index("tree_digest() {") : source.index("\nmode=${1:-}")]
    invocation = "declare -F tree_digest >/dev/null" if define_only else 'tree_digest "$1"'
    script = (
        'set -euo pipefail\nfail() { printf "%s\\n" "$1" >&2; exit 1; }\n'
        + function
        + "\n"
        + invocation
    )
    return subprocess.run(
        ("/bin/bash", "-c", script, "fingerprint-test", str(tmp_path)),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
    )


def test_real_nonroot_bash_fingerprint_definition_has_no_output(tmp_path: Path) -> None:
    result = run_fingerprint_function(tmp_path, define_only=True)
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""


@pytest.mark.parametrize("command", ["groupadd", "useradd"])
def test_installer_account_tools_use_fixed_absolute_path_and_readonly_help_with_empty_path(
    command: str,
) -> None:
    source = (ROOT / "scripts/embedding/install_experiment_runtime.sh").read_text()
    assert f"|| /usr/sbin/{command} --system" in source
    assert f"|| {command} --system" not in source
    assert "export PATH=/usr/bin:/bin" in source
    # --help only: no account creation, sudo, privileged service, or model execution.
    result = subprocess.run(
        (f"/usr/sbin/{command}", "--help"),
        capture_output=True,
        timeout=10,
        check=False,
        env={"PATH": "", "LC_ALL": "C"},
    )
    assert result.returncode == 0 and b"Usage:" in result.stdout


def test_real_nonroot_bash_fingerprint_matches_sorted_independent_records(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir/file").write_bytes(b"reviewed data")
    (tmp_path / "link").symlink_to("dir/file")
    digest = hashlib.sha256(b"reviewed data").hexdigest().encode("ascii")
    expected = hashlib.sha256(
        b"D\0./dir\0F\0./dir/file\0" + digest + b"\0L\0./link\0dir/file\0"
    ).hexdigest()
    result = run_fingerprint_function(tmp_path)
    assert result.returncode == 0 and result.stdout == expected + "\n" and result.stderr == ""


@pytest.mark.parametrize("kind", ["fifo", "hardlink", "control_name"])
def test_real_nonroot_bash_fingerprint_rejects_untrusted_fixture(tmp_path: Path, kind: str) -> None:
    if kind == "fifo":
        os.mkfifo(tmp_path / "fifo", 0o600)
    elif kind == "hardlink":
        (tmp_path / "file").write_bytes(b"shared inode")
        os.link(tmp_path / "file", tmp_path / "link")
    else:
        (tmp_path / "bad\nname").write_bytes(b"invalid name")
    result = run_fingerprint_function(tmp_path)
    assert result.returncode != 0 and "EMBEDDING_RUNTIME_" in result.stderr


def test_installer_fixed_reviewed_model_pins_match_acquisition_module() -> None:
    helper = snapshot_helper()
    spec = importlib.util.spec_from_file_location(
        "model_acquisition", ROOT / "scripts/embedding/acquire_e5_small_probe.py"
    )
    assert spec and spec.loader
    acquisition = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acquisition)
    assert {name: (size, digest) for name, size, digest in acquisition.FILES} == {
        name: value for name, value in helper.MODEL_MEMBERS.items() if name != "manifest.json"
    }


def model_parent_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, helper: ModuleType
) -> tuple[Path, dict[str, int], list[tuple[int, int]]]:
    store = tmp_path / "model-store"
    store.mkdir(mode=0o750)
    parent = store / helper.MODEL_ID
    identity = {"uid": 0, "gid": 976}
    ownership_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(helper, "MODEL_STORE", store)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    original_lstat = Path.lstat

    def lstat(path: Path) -> os.stat_result:
        value = original_lstat(path)
        if path == parent:
            fields = list(value)
            fields[4], fields[5] = identity["uid"], identity["gid"]
            return os.stat_result(fields)
        return value

    def chown(path: Path, uid: int, gid: int) -> None:
        assert path == parent
        ownership_calls.append((uid, gid))
        identity.update(uid=uid, gid=gid)

    # Ownership is fake; directory creation, umask and mode changes are real unprivileged FS.
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(helper.os, "chown", chown)
    return parent, identity, ownership_calls


def test_new_fixed_model_parent_survives_real_umask077_with_private_group_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = snapshot_helper()
    parent, _identity, calls = model_parent_fixture(tmp_path, monkeypatch, helper)
    previous = os.umask(0o077)
    try:
        assert helper._prepare_model_parent(976) == parent
    finally:
        os.umask(previous)
    assert parent.stat().st_mode & 0o777 == 0o750 and calls == [(0, 976)]


def test_exact_existing_model_parent_is_reused_without_metadata_or_history_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = snapshot_helper()
    parent, _identity, calls = model_parent_fixture(tmp_path, monkeypatch, helper)
    parent.mkdir(mode=0o750)
    parent.chmod(0o750)
    marker = parent / "preserved-history"
    marker.write_bytes(b"history")
    monkeypatch.setattr(helper.os, "chmod", lambda *_a: pytest.fail("no existing metadata repair"))
    assert helper._prepare_model_parent(976) == parent
    assert calls == [] and marker.read_bytes() == b"history"


@pytest.mark.parametrize("kind", ["mode0700", "mode0755", "uid", "gid", "symlink"])
def test_existing_model_parent_drift_rejects_without_automatic_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    helper = snapshot_helper()
    parent, identity, calls = model_parent_fixture(tmp_path, monkeypatch, helper)
    if kind == "symlink":
        parent.symlink_to(parent.parent, target_is_directory=True)
    else:
        parent.mkdir(mode=0o750)
        parent.chmod(0o700 if kind == "mode0700" else 0o755 if kind == "mode0755" else 0o750)
        if kind == "uid":
            identity["uid"] = 1000
        elif kind == "gid":
            identity["gid"] = 1000
    monkeypatch.setattr(helper.os, "chmod", lambda *_a: pytest.fail("no automatic metadata repair"))
    with pytest.raises(ValueError, match="MODEL_PARENT_INVALID"):
        helper._prepare_model_parent(976)
    assert calls == []


def test_snapshot_hash_rejects_link_hardlink_and_renamed_inode(tmp_path: Path) -> None:
    helper = snapshot_helper()
    target = tmp_path / "file"
    target.write_bytes(b"reviewed bytes")
    assert helper._hash(target) == hashlib.sha256(b"reviewed bytes").hexdigest()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        helper._hash(link)
    hardlink = tmp_path / "hardlink"
    os.link(target, hardlink)
    with pytest.raises(ValueError, match="FILE_INVALID"):
        helper._hash(target)


def model_source(tmp_path: Path, helper: ModuleType) -> tuple[Path, Path]:
    store = tmp_path / "source"
    source = store / helper.MODEL_ID / helper.MODEL_REVISION
    source.mkdir(parents=True, mode=0o700)
    for directory in (store, source.parent, source):
        directory.chmod(0o700)
    (source / "1_Pooling").mkdir(mode=0o700)
    payloads = {"manifest.json": b"TEST_ONLY", "1_Pooling/config.json": b"{}"}
    helper.MODEL_MEMBERS = {
        name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in payloads.items()
    }
    for name, raw in payloads.items():
        (source / name).write_bytes(raw)
        (source / name).chmod(0o600)
    target_parent = tmp_path / "target"
    target_parent.mkdir(mode=0o700)
    return source, target_parent / helper.MODEL_REVISION


def test_model_handoff_copy_uses_new_inodes_and_independent_pins_fake_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = snapshot_helper()
    source, target = model_source(tmp_path, helper)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "chown", lambda *_a, **_k: None)
    helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())
    assert (target / "manifest.json").read_bytes() == b"TEST_ONLY"
    assert (target / "manifest.json").stat().st_ino != (source / "manifest.json").stat().st_ino
    assert (target / "manifest.json").stat().st_mode & 0o777 == 0o440
    with pytest.raises(ValueError, match="TARGET_EXISTS"):
        helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())


@pytest.mark.parametrize("mutation", ["symlink", "hash", "extra", "hardlink", "fifo"])
def test_model_handoff_rejects_untrusted_member_or_extra_file_preserves_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    helper = snapshot_helper()
    source, target = model_source(tmp_path, helper)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "chown", lambda *_a, **_k: None)
    if mutation == "symlink":
        (source / "manifest.json").unlink()
        (source / "manifest.json").symlink_to(source / "1_Pooling/config.json")
    elif mutation == "hash":
        (source / "manifest.json").write_bytes(b"WRONG_RAW")
    elif mutation == "extra":
        (source / "extra").write_bytes(b"unlisted")
    elif mutation == "fifo":
        (source / "manifest.json").unlink()
        os.mkfifo(source / "manifest.json", 0o600)
    else:
        os.link(source / "manifest.json", tmp_path / "hardlink")
    with pytest.raises((ValueError, OSError)):
        helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())
    assert (source / "manifest.json").exists()
    if target.exists():
        assert target.stat().st_mode & 0o777 == 0o700


def test_model_handoff_zero_write_fails_without_infinite_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = snapshot_helper()
    source, target = model_source(tmp_path, helper)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "write", lambda *_a, **_k: 0)
    with pytest.raises(ValueError, match="OUTPUT_WRITE_FAILED"):
        helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())


def test_shared_ancestor_atime_and_content_change_not_selected_directory_identity() -> None:
    helper = snapshot_helper()
    before = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=0o41777,
        st_uid=0,
        st_gid=0,
        st_nlink=3,
        st_size=100,
        st_mtime_ns=1,
        st_ctime_ns=1,
    )
    changed = SimpleNamespace(
        **(vars(before) | {"st_nlink": 4, "st_size": 200, "st_mtime_ns": 2, "st_ctime_ns": 2})
    )
    assert helper._ancestor_identity(before) == helper._ancestor_identity(changed)
    assert helper._epoch(before) != helper._epoch(changed)


@pytest.mark.parametrize("existing", [False, True])
def test_owner_workspace_fixed_child_creation_or_exact_reuse_fake_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    helper = snapshot_helper()
    parent = tmp_path / "owner"
    parent.mkdir(mode=0o700)
    child = parent / "inference-transfer-experiments"
    if existing:
        child.mkdir(mode=0o700)
        (child / "preserved-marker").write_bytes(b"history")
    monkeypatch.setattr(
        helper,
        "Path",
        lambda value: parent if value == "/var/lib/eom-workflow-runner" else Path(value),
    )
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(
        helper.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid()),
    )
    monkeypatch.setattr(helper.os, "fchown", lambda *_a, **_k: None)
    helper.ensure_owner_workspace()
    assert child.stat().st_mode & 0o777 == 0o700
    if existing:
        assert (child / "preserved-marker").read_bytes() == b"history"


@pytest.mark.parametrize("kind", ["symlink", "wrong_mode"])
def test_owner_workspace_rejects_link_or_relaxed_existing_metadata_without_fixup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    helper = snapshot_helper()
    parent = tmp_path / "owner"
    parent.mkdir(mode=0o700)
    child = parent / "inference-transfer-experiments"
    if kind == "symlink":
        child.symlink_to(tmp_path, target_is_directory=True)
    else:
        child.mkdir(mode=0o755)
    monkeypatch.setattr(
        helper,
        "Path",
        lambda value: parent if value == "/var/lib/eom-workflow-runner" else Path(value),
    )
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(
        helper.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid()),
    )
    monkeypatch.setattr(helper.os, "fchown", lambda *_a, **_k: pytest.fail("no metadata repair"))
    with pytest.raises((ValueError, OSError)):
        helper.ensure_owner_workspace()
    if kind == "wrong_mode":
        assert child.stat().st_mode & 0o777 == 0o755


def test_snapshot_mechanical_helper_failure_redacts_raw_validation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = snapshot_helper()
    monkeypatch.setattr(
        sys := helper.sys,
        "argv",
        [
            "installer",
            "--runtime",
            "/invalid",
            "--wheel",
            "/invalid",
            "--wheel-sha256",
            "0" * 64,
            "--model-source",
            "/invalid",
            "--source-uid",
            "1000",
            "--cpu-gid",
            "997",
        ],
    )
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    assert helper.main() == 1
    assert capsys.readouterr().err == "EMBEDDING_RUNTIME_PUBLICATION_REJECTED\n"
    assert sys is helper.sys
