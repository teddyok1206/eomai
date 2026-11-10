"""A real procfs dumpability change is not a worker credential change; no GPU or service IO."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import PosixPath

import pytest
from eom_catalog_service import embedding_runtime_files as runtime
from eom_catalog_service.embedding_batch_owner_identity import embedding_batch_owner_start_ticks


@pytest.mark.skipif(os.getuid() == 0, reason="Requires distinct root and unprivileged proc owners")
@pytest.mark.parametrize("initial_dumpable", (0, 1))
@pytest.mark.parametrize("member", ("stat", "status", "cgroup"))
@pytest.mark.parametrize("transition_at", ("after_lstat", "during_read"))
def test_legal_proc_owner_transition_between_lstat_and_open_keeps_same_worker(
    monkeypatch: pytest.MonkeyPatch, initial_dumpable: int, member: str, transition_at: str
) -> None:
    code = "\n".join(
        (
            "import ctypes, os, sys",
            "libc = ctypes.CDLL(None)",
            f"assert libc.prctl(4, {initial_dumpable}, 0, 0, 0) == 0",
            "print(os.getpid(), flush=True)",
            "assert sys.stdin.readline().strip() == 'switch'",
            f"assert libc.prctl(4, {1 - initial_dumpable}, 0, 0, 0) == 0",
            "print('switched', flush=True)",
            "sys.stdin.readline()",
        )
    )
    with subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            assert child.stdin is not None and child.stdout is not None
            assert int(child.stdout.readline()) == child.pid
            uid, gid = os.getuid(), os.getgid()
            before = embedding_batch_owner_start_ticks(child.pid, uid=uid, gid=gid)
            initial_owner = uid if initial_dumpable else 0
            final_owner = 0 if initial_dumpable else uid
            switched = False
            target = PosixPath("/proc") / str(child.pid) / member

            def switch() -> None:
                nonlocal switched
                switched = True
                assert child.stdin is not None and child.stdout is not None
                child.stdin.write("switch\n")
                child.stdin.flush()
                assert child.stdout.readline().strip() == "switched"
                assert target.lstat().st_uid == final_owner
                # Real/effective/saved/filesystem UID/GID and birth stay identical.
                assert embedding_batch_owner_start_ticks(child.pid, uid=uid, gid=gid) == before

            class TransitionPath(PosixPath):
                def lstat(self) -> os.stat_result:
                    observed = super().lstat()
                    if not switched and transition_at == "after_lstat":
                        assert observed.st_uid == initial_owner
                        switch()
                    return observed

            original_read = os.read

            def read(descriptor: int, maximum: int) -> bytes:
                raw = original_read(descriptor, maximum)
                if not switched and os.readlink(f"/proc/self/fd/{descriptor}") == str(target):
                    switch()
                return raw

            if transition_at == "during_read":
                monkeypatch.setattr(os, "read", read)
            path = TransitionPath("/proc") / str(child.pid) / member
            assert runtime.read_live_native_process_member(path, maximum=131072, owner_uid=uid)
            assert switched
            assert embedding_batch_owner_start_ticks(child.pid, uid=uid, gid=gid) == before
        finally:
            child.terminate()
            child.wait(timeout=5)


def _sequence_path(owners: tuple[int, ...]) -> tuple[PosixPath, list[int]]:
    observed: list[int] = []
    values = iter(owners)

    class MetadataPath(PosixPath):
        def lstat(self) -> os.stat_result:
            owner = next(values)
            observed.append(owner)
            return os.stat_result((0, 0, 0, 0, owner, 0, 0, 0, 0, 0))

    return MetadataPath("/proc/123/stat"), observed


@pytest.mark.parametrize("owners", ((0, 1000), (1000, 0)))
@pytest.mark.parametrize("code", ("FILE_UNPROTECTED", "FILE_CHANGED", "ANCESTOR_CHANGED"))
def test_only_legal_changed_owner_retries_the_entire_protected_reader(
    monkeypatch: pytest.MonkeyPatch, owners: tuple[int, ...], code: str
) -> None:
    path, observations = _sequence_path(owners)
    reads: list[int | None] = []

    def read(
        value: PosixPath, *, maximum: int, owner_uid: int, leaf_owner_uid: int | None
    ) -> bytes:
        assert value is path and maximum == 4096 and owner_uid == 1000
        reads.append(leaf_owner_uid)
        if len(reads) == 1:
            raise runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_" + code)
        return b"protected coherent reread"

    monkeypatch.setattr(runtime, "read_live_runtime_os_file", read)
    assert runtime.read_live_native_process_member(path, maximum=4096, owner_uid=1000)
    assert reads == list(owners) == observations


def test_second_protected_failure_is_terminal_and_preserves_first_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, observations = _sequence_path((1000, 0))
    first = runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_FILE_UNPROTECTED")
    second = runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_ANCESTOR_CHANGED")
    reads: list[int | None] = []

    def read(
        _path: PosixPath, *, maximum: int, owner_uid: int, leaf_owner_uid: int | None
    ) -> bytes:
        reads.append(leaf_owner_uid)
        raise first if len(reads) == 1 else second

    monkeypatch.setattr(runtime, "read_live_runtime_os_file", read)
    with pytest.raises(runtime.InstalledRuntimeProofError) as failure:
        runtime.read_live_native_process_member(path, maximum=4096, owner_uid=1000)
    assert failure.value is first
    assert reads == observations == [1000, 0]


@pytest.mark.parametrize("fresh_owner", (1000, 2000))
def test_same_or_foreign_owner_cannot_turn_a_protection_failure_into_retry(
    monkeypatch: pytest.MonkeyPatch, fresh_owner: int
) -> None:
    path, observations = _sequence_path((1000, fresh_owner))
    error = runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_FILE_UNPROTECTED")
    reads = 0

    def read(_path: PosixPath, **_kwargs: object) -> bytes:
        nonlocal reads
        reads += 1
        raise error

    monkeypatch.setattr(runtime, "read_live_runtime_os_file", read)
    with pytest.raises(runtime.InstalledRuntimeProofError) as failure:
        runtime.read_live_native_process_member(path, maximum=4096, owner_uid=1000)
    assert failure.value is error
    assert reads == 1 and observations == [1000, fresh_owner]


@pytest.mark.parametrize(
    "code", ("OS_OBSERVATION_EMPTY", "OS_OBSERVATION_TOO_LARGE", "FILE_UNAVAILABLE", "PATH_INVALID")
)
def test_unrelated_failure_does_not_reobserve_or_retry(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    path, observations = _sequence_path((1000,))
    error = runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_" + code)

    def read(_path: PosixPath, **_kwargs: object) -> bytes:
        raise error

    monkeypatch.setattr(runtime, "read_live_runtime_os_file", read)
    with pytest.raises(runtime.InstalledRuntimeProofError) as failure:
        runtime.read_live_native_process_member(path, maximum=4096, owner_uid=1000)
    assert failure.value is error and observations == [1000]


def test_unrelated_second_failure_is_not_replaced_by_first_protection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, observations = _sequence_path((1000, 0))
    first = runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_FILE_UNPROTECTED")
    second = runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_OS_OBSERVATION_TOO_LARGE")
    reads = 0

    def read(_path: PosixPath, **_kwargs: object) -> bytes:
        nonlocal reads
        reads += 1
        raise first if reads == 1 else second

    monkeypatch.setattr(runtime, "read_live_runtime_os_file", read)
    with pytest.raises(runtime.InstalledRuntimeProofError) as failure:
        runtime.read_live_native_process_member(path, maximum=4096, owner_uid=1000)
    assert failure.value is second
    assert reads == 2 and observations == [1000, 0]


def test_failed_owner_reobservation_preserves_original_error_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = 0
    error = runtime.InstalledRuntimeProofError("INSTALLED_RUNTIME_FILE_UNPROTECTED")

    class MissingPath(PosixPath):
        def lstat(self) -> os.stat_result:
            nonlocal observations
            observations += 1
            if observations > 1:
                raise FileNotFoundError()
            return os.stat_result((0, 0, 0, 0, 1000, 0, 0, 0, 0, 0))

    reads = 0

    def read(_path: PosixPath, **_kwargs: object) -> bytes:
        nonlocal reads
        reads += 1
        raise error

    monkeypatch.setattr(runtime, "read_live_runtime_os_file", read)
    with pytest.raises(runtime.InstalledRuntimeProofError) as failure:
        runtime.read_live_native_process_member(
            MissingPath("/proc/123/stat"), maximum=4096, owner_uid=1000
        )
    assert failure.value is error
    assert reads == 1 and observations == 2
