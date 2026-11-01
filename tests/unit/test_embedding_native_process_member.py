"""Real Linux non-dumpable metadata and fixed-member negative guards; no model or GPU."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_runtime_files as runtime
from eom_catalog_service.embedding_batch_owner_identity import embedding_batch_owner_start_ticks


@pytest.mark.skipif(os.getuid() == 0, reason="Non-root process storage-owner distinction")
def test_actual_non_dumpable_process_keeps_credential_fence_and_old_file_guard():
    code = (
        "import ctypes,os,time; "
        "assert ctypes.CDLL(None).prctl(4,0,0,0,0)==0; "
        "print(os.getpid(),flush=True); time.sleep(20)"
    )
    with subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", code], stdout=subprocess.PIPE, text=True
    ) as child:
        try:
            assert child.stdout is not None and int(child.stdout.readline()) == child.pid
            before = embedding_batch_owner_start_ticks(child.pid, uid=os.getuid(), gid=os.getgid())
            for member in ("stat", "status", "cgroup", "cmdline"):
                path = Path("/proc") / str(child.pid) / member
                assert path.lstat().st_uid == 0
                with pytest.raises(runtime.InstalledRuntimeProofError, match="FILE_UNPROTECTED"):
                    runtime.read_live_runtime_os_file(path, maximum=131072, owner_uid=os.getuid())
                assert (
                    runtime.read_live_native_process_member(
                        path, maximum=131072, owner_uid=os.getuid()
                    )
                    == path.read_bytes()
                )
            assert (
                embedding_batch_owner_start_ticks(child.pid, uid=os.getuid(), gid=os.getgid())
                == before
            )
            with pytest.raises(ValueError):
                embedding_batch_owner_start_ticks(child.pid, uid=os.getuid() + 1, gid=os.getgid())
        finally:
            child.terminate()
            child.wait(timeout=5)


@pytest.mark.parametrize(
    "path",
    (
        "/etc/passwd",
        "/opt/eom/stat",
        "/proc/self/stat",
        "/proc/0/stat",
        "/proc/01/status",
        "/proc/2147483648/stat",
        "/proc/123/environ",
        "/proc/123/root",
        "/proc/123/fd/0",
        "/proc/123/fdinfo/01",
        "/proc/123/fdinfo/1/extra",
        "/proc/123/../status",
    ),
)
def test_non_kernel_or_unbounded_member_is_not_a_storage_owner_exception(path):
    with pytest.raises(runtime.InstalledRuntimeProofError, match="PROCESS_MEMBER_INVALID"):
        runtime.read_live_native_process_member(Path(path), maximum=100, owner_uid=1000)


@pytest.mark.parametrize("uid", (False, 0, -1, 2**32, 1.0))
def test_actual_worker_uid_is_required(uid):
    with pytest.raises(runtime.InstalledRuntimeProofError, match="PROCESS_MEMBER_INVALID"):
        runtime.read_live_native_process_member(Path("/proc/123/stat"), maximum=100, owner_uid=uid)


@pytest.mark.parametrize("member", ("stat", "status", "cgroup", "cmdline", "maps", "fdinfo/4"))
@pytest.mark.parametrize("leaf_uid", (0, 1000, 2000))
def test_fixed_leaf_owner_is_pinned_into_original_protected_open(monkeypatch, member, leaf_uid):
    class MetadataPath(type(Path())):
        def lstat(self):
            return SimpleNamespace(st_uid=leaf_uid)

    path = MetadataPath("/proc/123") / member
    calls = []

    def read(value, *, maximum, owner_uid, leaf_owner_uid):
        calls.append((value, maximum, owner_uid, leaf_owner_uid))
        return b"kernel data, not process authority"

    monkeypatch.setattr(runtime, "read_live_runtime_os_file", read)
    if leaf_uid == 2000:
        with pytest.raises(
            runtime.InstalledRuntimeProofError, match="PROCESS_MEMBER_OWNER_INVALID"
        ):
            runtime.read_live_native_process_member(path, maximum=4096, owner_uid=1000)
        assert not calls
    else:
        assert runtime.read_live_native_process_member(path, maximum=4096, owner_uid=1000)
        assert calls == [(path, 4096, 1000, leaf_uid)]
