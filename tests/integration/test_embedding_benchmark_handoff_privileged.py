"""Opt-in real DAC/ACL only, private /run fixtures; no Job/DB/NAS/GPU/model admission."""

from __future__ import annotations

import os
import pwd
import signal
import socket
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_device_benchmark import benchmark_sample_program
from eom_catalog_service import embedding_benchmark_activation as activation
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service import embedding_device_benchmark_files as capture
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_device_benchmark_files import BenchmarkWorkerLocalFiles
from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile

from tests.unit.embedding_benchmark_environment_fixtures import (
    environment_metadata,
    stage_installation,
)
from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)

pytestmark = pytest.mark.privileged


@contextmanager
def actual_workflow_owner() -> Iterator[tuple[int, Callable[[], None]]]:
    """Only this test's child; no credential, process-global UID change or production unit."""
    account = pwd.getpwnam("eom-workflow-runner")
    waiting, release = os.pipe2(os.O_CLOEXEC)
    ready, started = os.pipe2(os.O_CLOEXEC)
    child = os.fork()
    if child == 0:
        try:
            os.close(release)
            os.close(ready)
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            # Match an actual exec'd owner: setuid without exec leaves proc files root-owned.
            os.dup2(waiting, 0, inheritable=True)
            os.dup2(started, 3, inheritable=True)
            executable = "/srv/eom/conda/envs/eom-api/bin/python"
            os.execve(
                executable,
                [
                    executable,
                    "-I",
                    "-B",
                    "-c",
                    "import os;os.write(3,b'1');os.close(3);os.read(0,1)",
                ],
                {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"},
            )
        except BaseException:
            os._exit(1)
    os.close(waiting)
    os.close(started)
    alive = True

    def stop() -> None:
        nonlocal alive
        if alive:
            os.close(release)
            _, status = os.waitpid(child, 0)
            alive = False
            assert os.waitstatus_to_exitcode(status) == 0

    try:
        assert os.read(ready, 1) == b"1"
        yield child, stop
    finally:
        os.close(ready)
        stop()


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_real_native_uid_uses_inherited_input_and_only_precreated_outputs(
    monkeypatch: pytest.MonkeyPatch, ordinal: int
) -> None:
    if os.environ.get("EOM_RUN_BENCHMARK_HANDOFF_PRIVILEGED") != "1":
        pytest.skip("explicit private benchmark filesystem OS gate required")
    assert os.geteuid() == 0
    invocation = worker_invocation(ordinal)
    native = pwd.getpwnam(fixed_native_embedding_profile(invocation.runtime.profile).worker_user)
    other = pwd.getpwnam(
        "eom-embedding-cuda" if invocation.device == "CPU" else "eom-embedding-index-cpu"
    )
    with tempfile.TemporaryDirectory(prefix="eom-benchmark-handoff-os-", dir="/run") as directory:
        parent = Path(directory)
        parent.chmod(0o711)
        root = parent / "benchmark"
        root.mkdir(mode=0o711)
        root.chmod(0o711)
        monkeypatch.setattr(handoff, "_HANDOFF_ROOT", root)
        monkeypatch.setattr(capture, "_HANDOFF_ROOT", root)
        prepared = handoff.prepare_benchmark_handoff(owner_request(), invocation, staged_inputs())
        execution = root / invocation.execution_id
        borrowed = os.open(execution / "invocation.json", os.O_RDONLY | os.O_CLOEXEC)
        try:
            for account in (native, other):
                child = os.fork()
                if child == 0:
                    try:
                        os.setgroups([])
                        os.setgid(account.pw_gid)
                        os.setuid(account.pw_uid)
                        assert os.getuid() == os.geteuid() == account.pw_uid != 0
                        assert not os.getgroups()
                        with pytest.raises(PermissionError):
                            os.listdir(root)
                        with pytest.raises(PermissionError):
                            (execution / "invocation.json").read_bytes()
                        with pytest.raises(PermissionError):
                            (execution / "inputs/benchmark-inputs.json").open("wb")
                        with pytest.raises(PermissionError):
                            (execution / "outputs/extra.json").touch()
                        if account == other:
                            with pytest.raises(PermissionError):
                                os.listdir(execution)
                        else:
                            with BenchmarkWorkerLocalFiles(
                                borrowed,
                                profile=invocation.runtime.profile,
                                execution_id=invocation.execution_id,
                                invocation_raw_sha256=prepared.invocation_raw_sha256,
                            ) as files:
                                assert files.read_invocation() == invocation
                                assert files.read_inputs(invocation) == staged_inputs()
                                files.write_vectors(
                                    benchmark_sample_program(ordinal)[0], b"\0" * (6 * 4096)
                                )
                                files.assert_current()
                            with pytest.raises(PermissionError):
                                (execution / "outputs/cold-documents.f32").unlink()
                        os._exit(0)
                    except BaseException:
                        os._exit(1)
                _, status = os.waitpid(child, 0)
                assert os.waitstatus_to_exitcode(status) == 0
            assert os.lseek(borrowed, 0, os.SEEK_CUR) == 0
            assert (execution / "outputs/cold-documents.f32").stat().st_size == 6 * 4096
        finally:
            os.close(borrowed)


def test_real_native_accepts_exact_workflow_owner_peer_without_binding_or_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("EOM_RUN_BENCHMARK_HANDOFF_PRIVILEGED") != "1":
        pytest.skip("explicit private benchmark filesystem OS gate required")
    assert os.geteuid() == 0
    native = pwd.getpwnam("eom-embedding-index-cpu")
    owner = pwd.getpwnam("eom-workflow-runner")
    invocation = worker_invocation()
    with tempfile.TemporaryDirectory(prefix="eom-bench-peer-", dir="/run") as directory:
        root = Path(directory)
        root.chmod(0o711)
        namespace = root / "b"
        namespace.mkdir(mode=0o711)
        namespace.chmod(0o711)
        monkeypatch.setattr(handoff, "_HANDOFF_ROOT", namespace)
        monkeypatch.setattr(activation, "_HANDOFF_ROOT", namespace)
        handoff.prepare_benchmark_handoff(owner_request(), invocation, staged_inputs())
        path = namespace / invocation.execution_id / "control.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        os.chown(path, owner.pw_uid, owner.pw_gid)
        path.chmod(0o600)
        listener.listen(1)
        listener.setblocking(False)
        go_read, go_write = os.pipe2(os.O_CLOEXEC)
        children: set[int] = set()
        try:
            owner_pid = os.fork()
            if owner_pid == 0:
                try:
                    os.setgroups([])
                    os.setgid(owner.pw_gid)
                    os.setuid(owner.pw_uid)
                    listener.close()  # Owner is only the client, not an accept-capability holder.
                    os.close(go_write)
                    assert os.read(go_read, 1) == b"1"
                    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    client.connect(str(path))
                    assert client.recv(1) == b""
                    client.close()
                    os._exit(0)
                except BaseException:
                    os._exit(1)
            children.add(owner_pid)
            native_pid = os.fork()
            if native_pid == 0:
                try:
                    os.setgroups([])
                    os.setgid(native.pw_gid)
                    os.setuid(native.pw_uid)
                    os.close(go_read)
                    os.close(go_write)
                    assert os.getuid() == native.pw_uid != owner.pw_uid
                    with pytest.raises(PermissionError):
                        os.listdir(namespace)
                    channel = activation.capture_benchmark_worker_channel(
                        invocation,
                        activation_fd=listener.fileno(),
                        expected_peer=BenchmarkUnixPeer(owner_pid, owner.pw_uid, owner.pw_gid),
                        peer_fence=lambda actual: None,
                        expires_ns=time.monotonic_ns() + 3 * 10**9,
                    )
                    channel.assert_initial_invocation(invocation)
                    channel.close()
                    assert listener.fileno() >= 0 and path.is_socket()
                    os._exit(0)
                except BaseException:
                    os._exit(1)
            children.add(native_pid)
            os.write(go_write, b"1")
            deadline = time.monotonic() + 5
            while children and time.monotonic() < deadline:
                for child in tuple(children):
                    finished, status = os.waitpid(child, os.WNOHANG)
                    if finished:
                        children.remove(child)
                        assert os.waitstatus_to_exitcode(status) == 0
                if children:
                    time.sleep(0.01)
            assert not children
        finally:
            # Only this test's unreaped fork children; these PIDs cannot be reused yet.
            for child in children:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
            os.close(go_read)
            os.close(go_write)
            listener.close()


@pytest.mark.parametrize("late_owner_exit", (False, True))
def test_real_root_environment_private_access_and_process_exit_fence(
    monkeypatch: pytest.MonkeyPatch,
    late_owner_exit: bool,
) -> None:
    if os.environ.get("EOM_RUN_BENCHMARK_HANDOFF_PRIVILEGED") != "1":
        pytest.skip("explicit private benchmark filesystem OS gate required")
    assert os.geteuid() == 0
    metadata = environment_metadata()
    with tempfile.TemporaryDirectory(prefix="eom-bench-env-", dir="/run") as directory:
        root = Path(directory)
        root.chmod(0o711)
        namespace = root / "b"
        namespace.mkdir(mode=0o711)
        namespace.chmod(0o711)
        config, evidence = stage_installation(root, metadata)
        monkeypatch.setattr(handoff, "_HANDOFF_ROOT", namespace)
        monkeypatch.setattr(capture, "_HANDOFF_ROOT", namespace)
        monkeypatch.setattr(handoff, "_CONFIG_ROOT", config)
        monkeypatch.setattr(handoff, "_EVIDENCE_ROOT", evidence)
        prepared = handoff.prepare_benchmark_handoff(
            metadata.request,
            metadata.invocation,
            metadata.inputs,
        )
        path = namespace / prepared.execution_id / "launch.env"
        with actual_workflow_owner() as (owner_pid, stop):
            if late_owner_exit:
                original = handoff._new_member

                def write_then_exit(
                    parent: int, name: str, raw: bytes, uid: int, gid: int, mode: int
                ) -> None:
                    original(parent, name, raw, uid, gid, mode)
                    stop()

                monkeypatch.setattr(handoff, "_new_member", write_then_exit)
                with pytest.raises(ValueError):
                    handoff.prepare_cpu_benchmark_environment(
                        prepared,
                        metadata.invocation,
                        backend=metadata.backend,
                        owner_pid=owner_pid,
                        expires_ns=time.monotonic_ns() + 10 * 10**9,
                    )
                assert path.is_file() and path.stat().st_uid == 0
            else:
                result = handoff.prepare_cpu_benchmark_environment(
                    prepared,
                    metadata.invocation,
                    backend=metadata.backend,
                    owner_pid=owner_pid,
                    expires_ns=time.monotonic_ns() + 10 * 10**9,
                )
                assert result.state == "STAGED_NOT_LAUNCHED" and result.owner_start_ticks > 0
                assert (
                    result.owner_pid == owner_pid and path.stat().st_uid == path.stat().st_gid == 0
                )
                assert path.stat().st_mode & 0o777 == 0o600
                assert (
                    b"EOM_BENCHMARK_OWNER_PID=" + str(owner_pid).encode() + b"\n"
                    in path.read_bytes()
                )
                for name in ("eom-workflow-runner", "eom-embedding-index-cpu"):
                    account = pwd.getpwnam(name)
                    child = os.fork()
                    if child == 0:
                        try:
                            os.setgroups([])
                            os.setgid(account.pw_gid)
                            os.setuid(account.pw_uid)
                            with pytest.raises(PermissionError):
                                path.read_bytes()
                            os._exit(0)
                        except BaseException:
                            os._exit(1)
                    _, status = os.waitpid(child, 0)
                    assert os.waitstatus_to_exitcode(status) == 0
        assert path.stat().st_mode & 0o777 == 0o600
