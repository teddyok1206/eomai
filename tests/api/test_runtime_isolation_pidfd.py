from __future__ import annotations

import ctypes
import errno
import os
import sys
from collections.abc import Callable
from contextlib import suppress
from typing import cast

import eom_api.runtime_isolation_pidfd as pidfd_module
import eom_api.runtime_isolation_verifier as verifier_module
import pytest
from eom_api.runtime_isolation_pidfd import (
    LibcPidfdOpen,
    PidfdAcquisitionError,
    PidfdBackend,
    PidfdCapabilityReport,
    PidfdFailure,
    PidfdProvider,
    inspect_pidfd_capability,
)
from eom_api.runtime_isolation_verifier import (
    IsolationVerificationError,
    LinuxRuntimeIsolationAdapter,
    ResultCode,
    ServiceSnapshot,
    main,
)


def _fd_opener(captured: list[int]) -> Callable[[int, int], int]:
    def open_pidfd(_pid: int, flags: int) -> int:
        assert flags == 0
        descriptor = os.open("/dev/null", os.O_RDONLY)
        captured.append(descriptor)
        return descriptor

    return open_pidfd


def _raising_opener(error_number: int) -> Callable[[int, int], int]:
    def open_pidfd(_pid: int, flags: int) -> int:
        assert flags == 0
        raise OSError(error_number, "sanitized test error")

    return open_pidfd


def test_python_pidfd_backend_is_preferred_and_marks_descriptor_close_on_exec() -> None:
    captured: list[int] = []
    provider = PidfdProvider(_fd_opener(captured), _fd_opener([]))

    acquired = provider.open(4242)
    try:
        assert acquired.backend is PidfdBackend.PYTHON_OS_PIDFD
        assert not os.get_inheritable(acquired.descriptor)
    finally:
        os.close(acquired.descriptor)


@pytest.mark.parametrize(
    ("error_number", "failure"),
    [
        (errno.ESRCH, PidfdFailure.PROCESS_EXITED),
        (errno.EPERM, PidfdFailure.PERMISSION_DENIED),
        (errno.ENOSYS, PidfdFailure.KERNEL_UNSUPPORTED),
        (errno.EINVAL, PidfdFailure.KERNEL_UNSUPPORTED),
    ],
)
def test_python_pidfd_expected_errors_are_typed(error_number: int, failure: PidfdFailure) -> None:
    provider = PidfdProvider(_raising_opener(error_number), None)

    with pytest.raises(PidfdAcquisitionError) as caught:
        provider.open(4242)

    assert caught.value.failure is failure
    assert caught.value.error_number == error_number


class _FakeLibcFunction:
    def __init__(self, result: int, error_number: int = 0) -> None:
        self.result = result
        self.error_number = error_number
        self.argtypes: list[object] = []
        self.restype: object = None
        self.calls: list[tuple[int, int]] = []

    def __call__(self, pid: int, flags: int) -> int:
        self.calls.append((pid, flags))
        ctypes.set_errno(self.error_number)
        return self.result


class _FakeLibc:
    def __init__(self, function: _FakeLibcFunction) -> None:
        self.pidfd_open = function


def test_libc_backend_uses_fixed_symbol_signature_and_flags() -> None:
    descriptor = os.open("/dev/null", os.O_RDONLY)
    function = _FakeLibcFunction(descriptor)
    opener = LibcPidfdOpen(_FakeLibc(function))

    try:
        assert opener(4242, 0) == descriptor
        assert function.calls == [(4242, 0)]
        assert function.argtypes == [ctypes.c_int, ctypes.c_uint]
        assert function.restype is ctypes.c_int
    finally:
        os.close(descriptor)
    with pytest.raises(ValueError):
        opener(4242, 1)


def test_libc_backend_propagates_errno_without_negative_descriptor() -> None:
    opener = LibcPidfdOpen(_FakeLibc(_FakeLibcFunction(-1, errno.EPERM)))

    with pytest.raises(OSError) as caught:
        opener(4242, 0)

    assert caught.value.errno == errno.EPERM


def test_invalid_backend_descriptor_is_rejected() -> None:
    provider = PidfdProvider(None, lambda _pid, _flags: -1)

    with pytest.raises(PidfdAcquisitionError) as caught:
        provider.open(4242)

    assert caught.value.failure is PidfdFailure.INVALID_DESCRIPTOR


def test_descriptor_is_closed_when_close_on_exec_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int] = []
    provider = PidfdProvider(_fd_opener(captured), None)
    monkeypatch.setattr(
        os,
        "set_inheritable",
        lambda _descriptor, _inheritable: (_ for _ in ()).throw(OSError(errno.EIO, "test")),
    )

    with pytest.raises(PidfdAcquisitionError) as caught:
        provider.open(4242)

    assert caught.value.failure is PidfdFailure.OPEN_FAILED
    _assert_closed(captured)


def test_missing_python_binding_uses_libc_without_attribute_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int] = []
    libc_opener = _fd_opener(captured)
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.setattr(
        LibcPidfdOpen,
        "detect",
        classmethod(lambda _cls: cast(LibcPidfdOpen, libc_opener)),
    )

    provider = PidfdProvider.from_system()
    acquired = provider.open(4242)
    try:
        assert acquired.backend is PidfdBackend.LIBC_PIDFD
    finally:
        os.close(acquired.descriptor)


def test_capability_check_closes_descriptor() -> None:
    read_fd, write_fd = os.pipe()
    provider = PidfdProvider(None, lambda _pid, _flags: read_fd)
    try:
        report = inspect_pidfd_capability(provider)
        assert report.ready
        assert report.selected_backend is PidfdBackend.LIBC_PIDFD
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        os.close(write_fd)


class _ControlledLinuxAdapter(LinuxRuntimeIsolationAdapter):
    def __init__(
        self,
        provider: PidfdProvider,
        main_pids: tuple[int, ...] = (4242, 4242),
        referenced_pids: tuple[int, ...] = (4242, 4242),
        alive: tuple[bool, ...] = (True, True),
    ) -> None:
        super().__init__(provider)
        self._main_pids = iter(main_pids)
        self._last_main_pid = main_pids[-1]
        self._referenced_pids = iter(referenced_pids)
        self._last_referenced_pid = referenced_pids[-1]
        self._alive_values = iter(alive)
        self._last_alive = alive[-1]
        self.opened_descriptors: list[int] = []
        self.namespace_open_calls = 0

    def _read_systemd_properties(self) -> dict[str, str]:
        with suppress(StopIteration):
            self._last_main_pid = next(self._main_pids)
        return {
            "ActiveState": "active",
            "SubState": "running",
            "MainPID": str(self._last_main_pid),
        }

    def _open_process_directory(self, main_pid: int) -> int:
        assert main_pid == 4242
        descriptor = os.open("/dev/null", os.O_RDONLY)
        self.opened_descriptors.append(descriptor)
        return descriptor

    def _open_mount_namespace(self, proc_fd: int) -> int:
        assert proc_fd in self.opened_descriptors
        self.namespace_open_calls += 1
        descriptor = os.open("/dev/null", os.O_RDONLY)
        self.opened_descriptors.append(descriptor)
        return descriptor

    def _snapshot(
        self,
        properties: dict[str, str],
        main_pid: int,
        proc_fd: int,
        mount_fd: int,
    ) -> ServiceSnapshot:
        assert properties["MainPID"] == str(main_pid)
        assert proc_fd in self.opened_descriptors
        assert mount_fd in self.opened_descriptors
        return cast(ServiceSnapshot, object())

    def _pidfd_referenced_pid(self, pid_fd: int) -> int:
        del pid_fd
        with suppress(StopIteration):
            self._last_referenced_pid = next(self._referenced_pids)
        return self._last_referenced_pid

    def _pidfd_is_alive(self, pid_fd: int) -> bool:
        del pid_fd
        with suppress(StopIteration):
            self._last_alive = next(self._alive_values)
        return self._last_alive


def _root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)


def _assert_closed(descriptors: list[int]) -> None:
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_libc_backend_acquires_and_retains_service_process_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root(monkeypatch)
    pidfds: list[int] = []
    adapter = _ControlledLinuxAdapter(PidfdProvider(None, _fd_opener(pidfds)))

    handle = adapter.open_service()
    descriptors = [handle.pid_fd, handle.proc_fd, handle.mount_namespace_fd]
    assert handle.pidfd_backend is PidfdBackend.LIBC_PIDFD
    assert adapter.namespace_open_calls == 1
    adapter.close_service(handle)
    _assert_closed(descriptors)


@pytest.mark.parametrize(
    ("provider", "code"),
    [
        (PidfdProvider(_raising_opener(errno.ESRCH), None), ResultCode.FAIL_SERVICE_RESTART_RACE),
        (PidfdProvider(_raising_opener(errno.EPERM), None), ResultCode.FAIL_PIDFD_UNAVAILABLE),
        (PidfdProvider(None, None), ResultCode.FAIL_PIDFD_UNAVAILABLE),
    ],
)
def test_pidfd_acquisition_fails_closed_before_namespace_probe(
    monkeypatch: pytest.MonkeyPatch,
    provider: PidfdProvider,
    code: ResultCode,
) -> None:
    _root(monkeypatch)
    adapter = _ControlledLinuxAdapter(provider)

    with pytest.raises(IsolationVerificationError) as caught:
        adapter.open_service()

    assert caught.value.code is code
    assert adapter.namespace_open_calls == 0


def test_pidfd_identity_mismatch_rejects_reused_or_wrong_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root(monkeypatch)
    pidfds: list[int] = []
    adapter = _ControlledLinuxAdapter(
        PidfdProvider(_fd_opener(pidfds), None), referenced_pids=(9999,)
    )

    with pytest.raises(IsolationVerificationError) as caught:
        adapter.open_service()

    assert caught.value.code is ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH
    assert adapter.namespace_open_calls == 0
    _assert_closed(pidfds)


def test_process_exit_after_pidfd_acquisition_is_restart_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root(monkeypatch)
    pidfds: list[int] = []
    adapter = _ControlledLinuxAdapter(
        PidfdProvider(_fd_opener(pidfds), None), referenced_pids=(-1,)
    )

    with pytest.raises(IsolationVerificationError) as caught:
        adapter.open_service()

    assert caught.value.code is ResultCode.FAIL_SERVICE_RESTART_RACE
    assert adapter.namespace_open_calls == 0
    _assert_closed(pidfds)


def test_service_restart_after_namespace_open_fails_and_closes_descriptors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root(monkeypatch)
    pidfds: list[int] = []
    adapter = _ControlledLinuxAdapter(
        PidfdProvider(_fd_opener(pidfds), None), main_pids=(4242, 4243)
    )

    with pytest.raises(IsolationVerificationError) as caught:
        adapter.open_service()

    assert caught.value.code is ResultCode.FAIL_SERVICE_RESTART_RACE
    assert adapter.namespace_open_calls == 1
    _assert_closed([*pidfds, *adapter.opened_descriptors])


@pytest.mark.parametrize("main_pid", [0, 1])
def test_invalid_main_pid_does_not_acquire_pidfd_or_namespace(
    monkeypatch: pytest.MonkeyPatch, main_pid: int
) -> None:
    _root(monkeypatch)
    pidfds: list[int] = []
    adapter = _ControlledLinuxAdapter(
        PidfdProvider(_fd_opener(pidfds), None), main_pids=(main_pid,)
    )

    with pytest.raises(IsolationVerificationError) as caught:
        adapter.open_service()

    assert caught.value.code is ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE
    assert not pidfds
    assert adapter.namespace_open_calls == 0


def test_missing_main_pid_does_not_acquire_pidfd_or_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root(monkeypatch)
    pidfds: list[int] = []

    class MissingMainPidAdapter(_ControlledLinuxAdapter):
        def _read_systemd_properties(self) -> dict[str, str]:
            return {"ActiveState": "active", "SubState": "running"}

    adapter = MissingMainPidAdapter(PidfdProvider(_fd_opener(pidfds), None))

    with pytest.raises(IsolationVerificationError) as caught:
        adapter.open_service()

    assert caught.value.code is ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE
    assert not pidfds
    assert adapter.namespace_open_calls == 0


def test_capability_cli_reports_libc_backend_without_service_probe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = PidfdCapabilityReport(
        ready=True,
        selected_backend=PidfdBackend.LIBC_PIDFD,
        python_binding_available=False,
        libc_backend_available=True,
        fail_closed=True,
        detail_code="PIDFD_READY",
    )
    monkeypatch.setattr(verifier_module, "inspect_pidfd_capability", lambda: report)
    monkeypatch.setattr(sys, "argv", ["eom-api-runtime-isolation", "--capabilities"])
    monkeypatch.setattr(
        verifier_module,
        "verify_runtime_isolation",
        lambda: pytest.fail("capability self-check must not probe the service"),
    )

    main()

    output = capsys.readouterr()
    assert "runtime_isolation_verifier_capability=READY" in output.out
    assert "selected_pidfd_backend=LIBC_PIDFD" in output.out
    assert "python_os_pidfd=UNAVAILABLE" in output.out
    assert "pidfd_policy=FAIL_CLOSED" in output.out
    assert output.err == ""


def test_no_backend_cli_is_typed_and_has_no_traceback_or_namespace_probe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = PidfdCapabilityReport(
        ready=False,
        selected_backend=PidfdBackend.NONE,
        python_binding_available=False,
        libc_backend_available=False,
        fail_closed=True,
        detail_code=PidfdFailure.BACKEND_UNAVAILABLE.value,
    )
    monkeypatch.setattr(verifier_module, "inspect_pidfd_capability", lambda: report)
    monkeypatch.setattr(sys, "argv", ["eom-api-runtime-isolation", "--capabilities"])
    monkeypatch.setattr(
        verifier_module,
        "verify_runtime_isolation",
        lambda: pytest.fail("capability failure must not probe the service"),
    )

    with pytest.raises(SystemExit) as caught:
        main()

    assert caught.value.code == 1
    output = capsys.readouterr()
    assert "runtime_isolation_verifier_capability=BLOCKED" in output.out
    assert "selected_pidfd_backend=NONE" in output.out
    assert PidfdFailure.BACKEND_UNAVAILABLE.value in output.out
    assert "Traceback" not in output.out + output.err


def test_system_capability_selects_supported_backend_without_service_access() -> None:
    report = pidfd_module.inspect_pidfd_capability()

    assert report.ready
    assert report.selected_backend in {
        PidfdBackend.PYTHON_OS_PIDFD,
        PidfdBackend.LIBC_PIDFD,
    }
    assert report.fail_closed
