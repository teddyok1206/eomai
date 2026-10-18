"""Synthetic OS/unit seams + real bounded file checks; NOT privileged acceptance."""

from __future__ import annotations

import copy
import hashlib
import os
import pickle
import stat
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identity_service import local_indexing_runtime as runtime
from eom_operator_identity import LocalIndexingRuntimeConfiguration, local_indexing_runtime_bytes

from tests.unit.test_local_indexing_runtime_contracts import document


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def put(path: Path, raw: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o644)
    return path


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Test-owned temporary tree, fake unit/proc/interpreter; never root proof."""
    started = time.time_ns() + 10_000_000_000
    prefix, releases = tmp_path / "prefix", tmp_path / "releases"
    source = "4" * 40
    release = releases / source
    site = release / "site-packages"
    executable = put(prefix / "bin/python3.12", b"synthetic interpreter\n")
    unit_path = put(tmp_path / runtime._UNIT_NAME, b"synthetic fixed unit\n")
    config_path = tmp_path / "runtime.json"
    payloads = (
        {runtime._ENTRY: b"# synthetic entry\n", "eom_workflow_runner/__init__.py": b""},
        {"eom_api_contracts/__init__.py": b"# synthetic contracts\n"},
    )
    hashes: list[str] = []
    for filename, members in zip(
        ("eom_platform-0.1.0-py3-none-any.whl", "eom_api_contracts-0.1.0-py3-none-any.whl"),
        payloads,
        strict=True,
    ):
        wheel = release / filename
        wheel.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, raw in members.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, raw)
                put(site / name, raw)
        wheel.chmod(0o644)
        hashes.append(digest(wheel.read_bytes()))
    values = document()
    values.update(
        platform_wheel_sha256=hashes[0],
        api_contracts_wheel_sha256=hashes[1],
        interpreter_sha256=digest(executable.read_bytes()),
        unit_sha256=digest(unit_path.read_bytes()),
    )
    config = LocalIndexingRuntimeConfiguration.model_validate(values)
    raw = local_indexing_runtime_bytes(config)
    put(config_path, raw)
    pin = runtime.LocalIndexingRuntimePin(config.service, source, digest(raw))
    for directory in tmp_path.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o755)
    unit = {
        "User": "eom-workflow-runner",
        "ActiveState": "active",
        "MainPID": str(os.getpid()),
        "ExecMainPID": str(os.getpid()),
        "FragmentPath": str(unit_path),
        "DropInPaths": "",
        "ControlGroup": "/system.slice/" + runtime._UNIT_NAME,
        "InvocationID": "a" * 32,
        "ExecMainStartTimestamp": "Wed 2026-10-14 00:00:00.000000 UTC",
    }
    boot = ["11111111-2222-3333-4444-555555555555"]
    fake_sys = SimpleNamespace(
        flags=SimpleNamespace(isolated=1),
        dont_write_bytecode=True,
        executable=str(executable),
        argv=[str(site / runtime._ENTRY)],
        modules={"__main__": SimpleNamespace(__file__=str(site / runtime._ENTRY))},
    )

    def synthetic_ancestors(_self: object, path: Path) -> None:
        # /tmp is deliberately untrusted in production. Replace only that OS-root
        # seam; the actual file descriptor/hash/namespace/epoch code still runs.
        if not path.is_relative_to(tmp_path) or ".." in path.parts:
            raise runtime._unavailable()
        for parent in path.parents:
            if not parent.is_relative_to(tmp_path):
                break
            value = parent.lstat()
            if not stat.S_ISDIR(value.st_mode) or value.st_mode & 0o022 or parent.is_symlink():
                raise runtime._unavailable()

    def synthetic_ancestors_many(self: object, paths: tuple[Path, ...]) -> None:
        for path in paths:
            synthetic_ancestors(self, path)

    monkeypatch.setattr(runtime, "_ROOT_UID", os.getuid())
    monkeypatch.setattr(runtime, "_PREFIX", prefix)
    monkeypatch.setattr(runtime, "_RELEASES", releases)
    monkeypatch.setattr(runtime, "_UNIT_PATH", unit_path)
    monkeypatch.setattr(runtime, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(runtime, "sys", fake_sys)
    monkeypatch.setattr(runtime, "_executable", lambda: executable)
    monkeypatch.setattr(runtime, "_self_unit", lambda: (dict(unit), started))
    monkeypatch.setattr(runtime, "_live", lambda _path, _maximum: boot[0])
    monkeypatch.setattr(runtime._ProtectedFiles, "ancestors", synthetic_ancestors)
    monkeypatch.setattr(runtime._ProtectedFiles, "ancestors_many", synthetic_ancestors_many)
    return dict(
        pin=pin,
        config=config,
        path=config_path,
        unit_path=unit_path,
        unit=unit,
        boot=boot,
        prefix=prefix,
        release=release,
        site=site,
        executable=executable,
        sys=fake_sys,
        started=started,
    )


def check(
    capture: runtime.AuthenticatedLocalIndexingRuntime, pin: runtime.LocalIndexingRuntimePin
) -> None:
    capture.assert_current(
        service=pin.service,
        runtime_source_commit=pin.runtime_source_commit,
        configuration_sha256=pin.configuration_sha256,
    )


def test_fixed_owner_selection_is_bound_to_actual_capture_epoch(installed, tmp_path, monkeypatch):
    path = put(tmp_path / "owner-selection.json", b'{"test_only":"non-secret selection"}')
    monkeypatch.setattr(runtime, "_OWNER_SELECTION_PATH", path)
    capture = runtime.capture_local_indexing_runtime(installed["pin"])
    assert capture.read_owner_configuration() == path.read_bytes()
    check(capture, installed["pin"])
    path.write_bytes(b'{"test_only":"changed"}')
    with pytest.raises(runtime.IndexingRuntimeAdmissionError, match="CHANGED"):
        check(capture, installed["pin"])


@pytest.mark.parametrize("fault", ["missing", "writable", "symlink", "oversized", "late"])
def test_owner_selection_fails_closed_before_any_source_authority(
    installed, tmp_path, monkeypatch, fault
):
    path = put(tmp_path / "owner-selection.json", b"{}")
    monkeypatch.setattr(runtime, "_OWNER_SELECTION_PATH", path)
    if fault == "missing":
        path.unlink()
    elif fault == "writable":
        path.chmod(0o666)
    elif fault == "symlink":
        other = put(tmp_path / "other.json", b"{}")
        path.unlink()
        path.symlink_to(other)
    elif fault == "oversized":
        path.write_bytes(b" " * (64 * 1024 + 1))
    else:
        os.utime(path, ns=(installed["started"] + 1, installed["started"] + 1))
    capture = runtime.capture_local_indexing_runtime(installed["pin"])
    with pytest.raises(runtime.IndexingRuntimeAdmissionError, match="CHANGED"):
        capture.read_owner_configuration()


def test_actual_developer_process_is_denied_before_protected_configuration_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> bytes:
        pytest.fail("developer process must not read protected configuration")

    config = LocalIndexingRuntimeConfiguration.model_validate(document())
    pin = runtime.LocalIndexingRuntimePin(
        config.service, config.runtime_source_commit, "sha256:" + "0" * 64
    )
    monkeypatch.setattr(runtime._ProtectedFiles, "read", forbidden)
    with pytest.raises(runtime.IndexingRuntimeAdmissionError, match="UNAVAILABLE"):
        runtime.capture_local_indexing_runtime(pin)


def test_synthetic_capture_rechecks_files_and_cannot_be_serialized_or_transferred(
    installed: dict[str, Any],
) -> None:
    capture = runtime.capture_local_indexing_runtime(installed["pin"])
    check(capture, installed["pin"])
    assert not hasattr(capture, "permissions") and not hasattr(capture, "operator_id")
    for action in (lambda: pickle.dumps(capture), lambda: copy.copy(capture)):
        with pytest.raises(TypeError):
            action()
    capture.close()
    with pytest.raises(runtime.IndexingRuntimeAdmissionError, match="CHANGED"):
        check(capture, installed["pin"])


@pytest.mark.parametrize(
    "fault",
    [
        "config",
        "unit",
        "binary",
        "installed_code",
        "entrypoint",
        "argv",
        "unowned_module",
        "wheel",
        "extra_member",
    ],
)
def test_synthetic_capture_rejects_wrong_bytes_origin_or_namespace(
    installed: dict[str, Any],
    fault: str,
) -> None:
    if fault in {"config", "unit", "binary"}:
        target = installed[{"config": "path", "unit": "unit_path", "binary": "executable"}[fault]]
        target.write_bytes(target.read_bytes() + b"changed")
    elif fault == "installed_code":
        put(installed["site"] / runtime._ENTRY, b"changed")
    elif fault == "entrypoint":
        installed["sys"].modules["__main__"].__file__ = "/unapproved.py"
    elif fault == "argv":
        installed["sys"].argv.append("--grant=ADMIN")
    elif fault == "unowned_module":
        installed["sys"].modules["foreign"] = SimpleNamespace(__file__="/unapproved.py")
    elif fault == "wheel":
        put(installed["release"] / "eom_platform-0.1.0-py3-none-any.whl", b"not a wheel")
    else:
        put(installed["site"] / "eom_workflow_runner/extra.py", b"unexpected")
    with pytest.raises(runtime.IndexingRuntimeAdmissionError, match="UNAVAILABLE") as caught:
        runtime.capture_local_indexing_runtime(installed["pin"])
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "fault", ["config", "code", "unit", "invocation", "boot", "new_module", "new_file", "wrong_pin"]
)
def test_synthetic_capture_invalidated_by_late_replacement_or_different_instance(
    installed: dict[str, Any],
    fault: str,
) -> None:
    pin = installed["pin"]
    capture = runtime.capture_local_indexing_runtime(pin)
    if fault in {"config", "unit", "code"}:
        target = installed[{"config": "path", "unit": "unit_path", "code": "executable"}[fault]]
        replacement = put(target.with_name(target.name + ".replacement"), target.read_bytes())
        replacement.replace(target)
    elif fault == "invocation":
        installed["unit"]["InvocationID"] = "b" * 32
    elif fault == "boot":
        installed["boot"][0] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    elif fault == "new_module":
        installed["sys"].modules["foreign"] = SimpleNamespace(__file__="/unapproved.py")
    elif fault == "new_file":
        put(installed["site"] / "eom_workflow_runner/late.py", b"unexpected")
    else:
        pin = runtime.LocalIndexingRuntimePin(pin.service, "9" * 40, pin.configuration_sha256)
    with pytest.raises(runtime.IndexingRuntimeAdmissionError, match="CHANGED"):
        check(capture, pin)


@pytest.mark.parametrize(
    "fault", ["symlink", "hardlink", "writable", "directory", "oversize", "newer_than_start"]
)
def test_real_file_checks_reject_unsafe_or_changed_materialization(
    installed: dict[str, Any],
    fault: str,
) -> None:
    target = installed["path"]
    if fault == "symlink":
        real = target.rename(target.with_name("real.json"))
        target.symlink_to(real)
    elif fault == "hardlink":
        os.link(target, target.with_name("hardlink.json"))
    elif fault == "writable":
        target.chmod(0o666)
    elif fault == "directory":
        target.unlink()
        target.mkdir()
    elif fault == "oversize":
        target.write_bytes(b"x" * 4097)
    else:
        os.utime(target, ns=(installed["started"] + 1, installed["started"] + 1))
    with pytest.raises(runtime.IndexingRuntimeAdmissionError, match="UNAVAILABLE"):
        runtime.capture_local_indexing_runtime(installed["pin"])


def test_unit_observation_is_fixed_bounded_and_not_caller_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object]] = []
    output = "\n".join(name + "=synthetic" for name in sorted(runtime._PROPERTIES)).encode()

    def run(argv: object, **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=output, stderr=b"")

    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert set(runtime._unit()) == runtime._PROPERTIES
    argv, kwargs = calls[0]
    assert argv[0:5] == (
        "/usr/bin/systemctl",
        "--no-pager",
        "--timestamp=us",
        "show",
        runtime._UNIT_NAME,
    )
    assert kwargs["timeout"] == 2 and "PGPASSWORD" not in kwargs["env"]
    for raw in (
        output + b"\nUser=duplicate",
        b"User=x",
        b"x" * 8193,
        output + b"\nEnvironment=secret",
    ):
        output = raw
        with pytest.raises(ValueError):
            runtime._unit()


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "uid",
        "euid",
        "not_isolated",
        "bytecode",
        "user",
        "inactive",
        "pid",
        "exec_pid",
        "fragment",
        "dropin",
        "cgroup",
        "invocation",
        "proc_cgroup",
        "timestamp",
    ],
)
def test_actual_self_unit_decision_checks_process_and_unit_independently(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    user = SimpleNamespace(pw_uid=12345)
    monkeypatch.setattr(runtime.pwd, "getpwnam", lambda name: user)
    monkeypatch.setattr(runtime.os, "getuid", lambda: 999 if fault == "uid" else 12345)
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 999 if fault == "euid" else 12345)
    monkeypatch.setattr(
        runtime,
        "sys",
        SimpleNamespace(
            flags=SimpleNamespace(isolated=fault != "not_isolated"),
            dont_write_bytecode=fault != "bytecode",
        ),
    )
    unit = {
        "User": "eom-workflow-runner",
        "ActiveState": "active",
        "MainPID": str(os.getpid()),
        "ExecMainPID": str(os.getpid()),
        "FragmentPath": str(runtime._UNIT_PATH),
        "DropInPaths": "",
        "ControlGroup": "/system.slice/" + runtime._UNIT_NAME,
        "InvocationID": "a" * 32,
        "ExecMainStartTimestamp": "Wed 2026-10-14 00:00:00.000000 UTC",
    }
    changes = {
        "user": ("User", "root"),
        "inactive": ("ActiveState", "activating"),
        "pid": ("MainPID", "1"),
        "exec_pid": ("ExecMainPID", "1"),
        "fragment": ("FragmentPath", "/tmp/unapproved.service"),
        "dropin": ("DropInPaths", "/etc/systemd/system/override.conf"),
        "cgroup": ("ControlGroup", "/another.slice/unapproved"),
        "invocation": ("InvocationID", "not-an-invocation"),
        "timestamp": ("ExecMainStartTimestamp", "not-a-timestamp"),
    }
    if fault in changes:
        key, value = changes[fault]
        unit[key] = value
    monkeypatch.setattr(runtime, "_unit", lambda: unit)
    monkeypatch.setattr(
        runtime,
        "_live",
        lambda _path, _max: (
            "0::" + ("/different" if fault == "proc_cgroup" else unit["ControlGroup"])
        ),
    )
    if fault == "none":
        actual, started = runtime._self_unit()
        assert actual == unit and started == 1791936000 * 1_000_000_000
    else:
        with pytest.raises(ValueError):
            runtime._self_unit()


@pytest.fixture
def precise_unit(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Actual parser/epoch comparison, explicit synthetic OS process metadata."""
    monkeypatch.setattr(runtime.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.getuid()))
    monkeypatch.setattr(
        runtime,
        "sys",
        SimpleNamespace(flags=SimpleNamespace(isolated=True), dont_write_bytecode=True),
    )
    unit = {
        "User": "eom-workflow-runner",
        "ActiveState": "active",
        "MainPID": str(os.getpid()),
        "ExecMainPID": str(os.getpid()),
        "FragmentPath": str(runtime._UNIT_PATH),
        "DropInPaths": "",
        "ControlGroup": "/system.slice/" + runtime._UNIT_NAME,
        "InvocationID": "a" * 32,
        "ExecMainStartTimestamp": "Wed 2026-10-14 00:00:00.996677 UTC",
    }
    monkeypatch.setattr(runtime, "_unit", lambda: dict(unit))
    monkeypatch.setattr(runtime, "_live", lambda _path, _max: "0::" + unit["ControlGroup"])
    return unit


@pytest.mark.parametrize("after", (None, "mtime", "ctime"))
def test_same_second_before_start_is_valid_and_post_start_write_still_rejected(
    precise_unit, monkeypatch: pytest.MonkeyPatch, after: str | None
) -> None:
    observed, started = runtime._self_unit()
    base = 1791936000 * 1_000_000_000
    assert observed == precise_unit and started == base + 996_677_000
    metadata = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=stat.S_IFREG | 0o444,
        st_uid=runtime._ROOT_UID,
        st_gid=0,
        st_nlink=1,
        st_size=2,
        st_mtime_ns=base + 134_310_796,
        st_ctime_ns=base + 143_310_832,
    )
    if after is not None:
        setattr(metadata, "st_" + after + "_ns", started + 1)
    monkeypatch.setattr(Path, "lstat", lambda _self: metadata)
    files = runtime._ProtectedFiles(started)
    if after is None:
        assert files.observe(Path("/opt/selected-before-start.json")) is metadata
    else:
        with pytest.raises(runtime.IndexingRuntimeAdmissionError):
            files.observe(Path("/opt/selected-after-start.json"))


@pytest.mark.parametrize(
    "timestamp",
    (
        "Wed 2026-10-14 00:00:00 UTC",
        "Wed 2026-10-14 00:00:00.9 UTC",
        "Wed 2026-10-14 00:00:00.996677000 UTC",
        "Wed 2026-10-14 00:00:00.996677 KST",
    ),
)
def test_missing_or_noncanonical_start_precision_never_falls_back_to_seconds(
    precise_unit, timestamp: str
) -> None:
    precise_unit["ExecMainStartTimestamp"] = timestamp
    with pytest.raises(ValueError):
        runtime._self_unit()
