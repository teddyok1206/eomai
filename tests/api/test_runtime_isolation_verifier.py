from __future__ import annotations

import grp
import json
import os
import pwd
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from eom_api.runtime_isolation_pidfd import PidfdBackend
from eom_api.runtime_isolation_verifier import (
    API_BIN,
    API_ENTRYPOINT,
    API_PYTHON,
    AUTH_BROKER_GROUP,
    EXPECTED_INACCESSIBLE_PATHS,
    EXPECTED_READ_ONLY_PATHS,
    FIXED_CHILD_ARGUMENT,
    PROBE_BY_NAME,
    PROBE_INVENTORY,
    AccessExpectation,
    IsolationVerificationError,
    LinuxRuntimeIsolationAdapter,
    NamespaceIdentity,
    ProbeContext,
    ProbeExecution,
    ProbeOperation,
    ProbeResult,
    ResultCode,
    RuntimeIsolationAdapter,
    ServiceProcessHandle,
    ServiceSnapshot,
    StabilityObservation,
    _execution_payload,
    main,
    validate_probe_execution,
    validate_service_snapshot,
    validate_stability,
    verify_runtime_isolation,
)


def _valid_snapshot() -> ServiceSnapshot:
    uid = pwd.getpwnam("eom-api").pw_uid
    gid = grp.getgrnam("eom-api").gr_gid
    auth_broker_gid = grp.getgrnam(AUTH_BROKER_GROUP).gr_gid
    supplementary_gids = tuple(sorted({gid, auth_broker_gid}))
    return ServiceSnapshot(
        active_state="active",
        sub_state="running",
        main_pid=4242,
        start_time_ticks=100,
        unit_user="eom-api",
        unit_group="eom-api",
        unit_supplementary_groups=(AUTH_BROKER_GROUP,),
        exec_start=(
            f"{{ path={API_ENTRYPOINT} ; argv[]={API_ENTRYPOINT} serve ; ignore_errors=no ; }}}}"
        ),
        unit_working_directory="/var/lib/eom-api",
        unit_root_directory="",
        unit_root_image="",
        uid=(uid, uid, uid, uid),
        gid=(gid, gid, gid, gid),
        supplementary_gids=supplementary_gids,
        command_line=(str(API_PYTHON), str(API_ENTRYPOINT), "serve"),
        executable=str(API_BIN / "python3.12"),
        process_working_directory="/var/lib/eom-api",
        process_root="/",
        mount_namespace=NamespaceIdentity(4, 200),
        host_mount_namespace=NamespaceIdentity(4, 100),
        user_namespace=NamespaceIdentity(4, 300),
        host_user_namespace=NamespaceIdentity(4, 300),
        no_new_privileges=True,
        capabilities=(0, 0, 0, 0, 0),
        private_tmp="yes",
        private_users="no",
        private_network="no",
        protect_system="strict",
        protect_home="yes",
        capability_bounding_set="",
        read_only_paths=frozenset(
            {
                "/etc/eom-api/api.yaml",
                "/etc/eom/secrets/api.env",
                "/etc/eom/local-image-provider.json",
            }
        ),
        read_write_paths=frozenset({"/var/lib/eom-api"}),
        inaccessible_paths=frozenset(
            {
                "/home/eom/EOM",
                "/home/eom/EOMIS",
                "/root/.codex",
                "/srv/eom/worker-homes",
                "/mnt/nas",
                "/srv/eom/models/image",
                "/var/run/docker.sock",
                "/etc/eom/secrets/postgres.env",
                "/etc/eom/secrets/dev-slack.env",
                "/etc/eom/secrets/observe.env",
            }
        ),
        restrict_address_families=frozenset({"AF_INET", "AF_INET6", "AF_UNIX"}),
        ip_address_deny=frozenset({"0.0.0.0/0", "::/0"}),
        ip_address_allow=frozenset({"127.0.0.0/8", "::1/128"}),
    )


def _valid_execution(snapshot: ServiceSnapshot) -> ProbeExecution:
    uid = pwd.getpwnam("eom-api").pw_uid
    gid = grp.getgrnam("eom-api").gr_gid
    auth_broker_gid = grp.getgrnam(AUTH_BROKER_GROUP).gr_gid
    context = ProbeContext(
        uid=uid,
        gid=gid,
        supplementary_gids=tuple(sorted({gid, auth_broker_gid})),
        mount_namespace=snapshot.mount_namespace,
        no_new_privileges=True,
        capabilities=(0, 0, 0, 0, 0),
        working_directory="/var/lib/eom-api",
        home="/var/lib/eom-api",
        user="eom-api",
        logname="eom-api",
        environment_sanitized=True,
    )
    results = tuple(
        ProbeResult(
            spec.logical_name,
            ResultCode.PASS_ALLOWED
            if spec.expectation is AccessExpectation.ALLOWED
            else ResultCode.PASS_DENIED,
            "ACCESSIBLE" if spec.expectation is AccessExpectation.ALLOWED else "ACCESS_DENIED",
        )
        for spec in PROBE_INVENTORY
    )
    return ProbeExecution(context, results)


def _stable(snapshot: ServiceSnapshot) -> StabilityObservation:
    return StabilityObservation(
        "active",
        "running",
        snapshot.main_pid,
        snapshot.start_time_ticks,
        snapshot.mount_namespace,
        True,
    )


class _FakeAdapter:
    def __init__(
        self,
        snapshot: ServiceSnapshot,
        execution: ProbeExecution,
        stability: StabilityObservation,
    ) -> None:
        self.snapshot = snapshot
        self.execution = execution
        self.stability = stability
        self.closed = False
        self.fixed_probe_calls = 0

    def open_service(self) -> ServiceProcessHandle:
        return ServiceProcessHandle(self.snapshot, -1, -1, -1, PidfdBackend.LIBC_PIDFD)

    def run_fixed_probe(self, process: ServiceProcessHandle) -> ProbeExecution:
        assert process.snapshot is self.snapshot
        self.fixed_probe_calls += 1
        return self.execution

    def observe_stability(self, process: ServiceProcessHandle) -> StabilityObservation:
        assert process.snapshot is self.snapshot
        return self.stability

    def close_service(self, process: ServiceProcessHandle) -> None:
        assert process.snapshot is self.snapshot
        self.closed = True


def _assert_error(code: ResultCode, function: Callable[[], object]) -> IsolationVerificationError:
    with pytest.raises(IsolationVerificationError) as caught:
        function()
    assert caught.value.code is code
    return caught.value


def test_false_failure_regression_ignores_host_root_access() -> None:
    snapshot = _valid_snapshot()
    adapter = _FakeAdapter(snapshot, _valid_execution(snapshot), _stable(snapshot))
    host_root_can_read_worker_home = True
    old_verifier_passed = not host_root_can_read_worker_home

    report = verify_runtime_isolation(cast(RuntimeIsolationAdapter, adapter))

    assert host_root_can_read_worker_home
    assert not old_verifier_passed, "the previous root verdict was a false failure"
    assert (
        next(result for result in report.results if result.logical_name == "worker_home_read").code
        is ResultCode.PASS_DENIED
    )
    assert adapter.fixed_probe_calls == 1
    assert adapter.closed


def test_api_environment_file_is_manager_only_and_denied_to_service() -> None:
    probe = PROBE_BY_NAME["api_environment_read"]

    assert probe.expectation is AccessExpectation.DENIED
    assert probe.operation is ProbeOperation.READ_FILE
    assert probe.path == Path("/etc/eom/secrets/api.env")
    assert str(probe.path) in EXPECTED_READ_ONLY_PATHS
    assert str(probe.path) not in EXPECTED_INACCESSIBLE_PATHS
    assert (
        next(
            result
            for result in _valid_execution(_valid_snapshot()).results
            if result.logical_name == probe.logical_name
        ).code
        is ResultCode.PASS_DENIED
    )


def test_service_context_failure_has_no_host_root_fallback() -> None:
    snapshot = _valid_snapshot()

    class FailingAdapter(_FakeAdapter):
        def run_fixed_probe(self, process: ServiceProcessHandle) -> ProbeExecution:
            self.fixed_probe_calls += 1
            raise IsolationVerificationError(
                ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE, "fixed_probe"
            )

    adapter = FailingAdapter(snapshot, _valid_execution(snapshot), _stable(snapshot))

    error = _assert_error(
        ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE,
        lambda: verify_runtime_isolation(cast(RuntimeIsolationAdapter, adapter)),
    )

    assert error.logical_name == "fixed_probe"
    assert adapter.fixed_probe_calls == 1
    assert adapter.closed


def test_allowed_probe_unexpectedly_denied_fails() -> None:
    snapshot = _valid_snapshot()
    execution = _valid_execution(snapshot)
    results = tuple(
        replace(result, code=ResultCode.FAIL_UNEXPECTEDLY_DENIED)
        if result.logical_name == "config_read"
        else result
        for result in execution.results
    )

    error = _assert_error(
        ResultCode.FAIL_UNEXPECTEDLY_DENIED,
        lambda: validate_probe_execution(snapshot, replace(execution, results=results)),
    )

    assert error.logical_name == "config_read"


def test_denied_probe_unexpectedly_allowed_fails() -> None:
    snapshot = _valid_snapshot()
    execution = _valid_execution(snapshot)
    results = tuple(
        replace(result, code=ResultCode.FAIL_UNEXPECTEDLY_ALLOWED)
        if result.logical_name == "worker_home_read"
        else result
        for result in execution.results
    )

    error = _assert_error(
        ResultCode.FAIL_UNEXPECTEDLY_ALLOWED,
        lambda: validate_probe_execution(snapshot, replace(execution, results=results)),
    )

    assert error.logical_name == "worker_home_read"


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        (replace(_valid_snapshot(), main_pid=0), ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE),
        (
            replace(_valid_snapshot(), command_line=("/usr/bin/python3", "unexpected")),
            ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH,
        ),
        (
            replace(_valid_snapshot(), uid=(0, 0, 0, 0)),
            ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH,
        ),
        (
            replace(_valid_snapshot(), unit_supplementary_groups=()),
            ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH,
        ),
        (
            replace(
                _valid_snapshot(),
                unit_supplementary_groups=(AUTH_BROKER_GROUP, "eom"),
            ),
            ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH,
        ),
        (
            replace(
                _valid_snapshot(), supplementary_gids=(*_valid_snapshot().supplementary_gids, 0)
            ),
            ResultCode.FAIL_PROCESS_IDENTITY_MISMATCH,
        ),
        (
            replace(
                _valid_snapshot(),
                mount_namespace=_valid_snapshot().host_mount_namespace,
            ),
            ResultCode.FAIL_NAMESPACE_MISMATCH,
        ),
        (
            replace(
                _valid_snapshot(),
                user_namespace=NamespaceIdentity(4, 999),
            ),
            ResultCode.FAIL_NAMESPACE_MISMATCH,
        ),
    ],
)
def test_service_snapshot_fails_closed(snapshot: ServiceSnapshot, code: ResultCode) -> None:
    _assert_error(code, lambda: validate_service_snapshot(snapshot))


def test_probe_identity_mismatch_fails() -> None:
    snapshot = _valid_snapshot()
    execution = _valid_execution(snapshot)
    execution = replace(execution, context=replace(execution.context, uid=0))

    _assert_error(
        ResultCode.FAIL_IDENTITY_MISMATCH,
        lambda: validate_probe_execution(snapshot, execution),
    )


def test_probe_rejects_an_unexpected_supplementary_group() -> None:
    snapshot = _valid_snapshot()
    execution = _valid_execution(snapshot)
    execution = replace(
        execution,
        context=replace(
            execution.context, supplementary_gids=(*execution.context.supplementary_gids, 0)
        ),
    )

    _assert_error(
        ResultCode.FAIL_IDENTITY_MISMATCH,
        lambda: validate_probe_execution(snapshot, execution),
    )


def test_probe_namespace_mismatch_fails() -> None:
    snapshot = _valid_snapshot()
    execution = _valid_execution(snapshot)
    execution = replace(
        execution,
        context=replace(execution.context, mount_namespace=NamespaceIdentity(4, 999)),
    )

    _assert_error(
        ResultCode.FAIL_NAMESPACE_MISMATCH,
        lambda: validate_probe_execution(snapshot, execution),
    )


@pytest.mark.parametrize(
    "observation",
    [
        replace(_stable(_valid_snapshot()), main_pid=4243),
        replace(_stable(_valid_snapshot()), start_time_ticks=101),
        replace(_stable(_valid_snapshot()), process_alive=False),
        replace(
            _stable(_valid_snapshot()),
            mount_namespace=NamespaceIdentity(4, 999),
        ),
    ],
)
def test_service_restart_race_fails(observation: StabilityObservation) -> None:
    _assert_error(
        ResultCode.FAIL_SERVICE_RESTART_RACE,
        lambda: validate_stability(_valid_snapshot(), observation),
    )


def test_probe_inventory_rejects_missing_and_arbitrary_results() -> None:
    snapshot = _valid_snapshot()
    execution = _valid_execution(snapshot)

    _assert_error(
        ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE,
        lambda: validate_probe_execution(
            snapshot, replace(execution, results=execution.results[:-1])
        ),
    )
    _assert_error(
        ResultCode.FAIL_SERVICE_CONTEXT_UNAVAILABLE,
        lambda: validate_probe_execution(
            snapshot,
            replace(
                execution,
                results=(
                    *execution.results,
                    ProbeResult("caller_path", ResultCode.PASS_ALLOWED, "ACCESSIBLE"),
                ),
            ),
        ),
    )


def test_linux_adapter_uses_pinned_namespace_and_fixed_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = _valid_snapshot()
    execution = _valid_execution(snapshot)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    process = ServiceProcessHandle(snapshot, -1, -1, descriptor, PidfdBackend.LIBC_PIDFD)
    captured: dict[str, object] = {}

    def run(arguments: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps(_execution_payload(execution), sort_keys=True, separators=(",", ":")),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", run)
    try:
        actual = LinuxRuntimeIsolationAdapter().run_fixed_probe(process)
    finally:
        os.close(descriptor)

    arguments = cast(tuple[str, ...], captured["arguments"])
    assert arguments[0] == "/usr/bin/nsenter"
    assert f"--mount=/proc/self/fd/{descriptor}" in arguments
    assert "--target" not in arguments
    assert "/usr/bin/setpriv" in arguments
    assert "--bounding-set=-all" in arguments
    assert "--reset-env" in arguments
    assert arguments[-5:] == (
        str(API_PYTHON),
        "-I",
        "-m",
        "eom_api.runtime_isolation_verifier",
        FIXED_CHILD_ARGUMENT,
    )
    assert cast(dict[str, object], captured["kwargs"])["pass_fds"] == (descriptor,)
    assert actual == execution


def test_cli_rejects_arbitrary_arguments_without_running_probe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["eom-api-runtime-isolation", "--path", "/tmp"])

    with pytest.raises(SystemExit) as caught:
        main()

    assert caught.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "FAIL_SERVICE_CONTEXT_UNAVAILABLE fixed_arguments\n"
    assert "/tmp" not in output.err
