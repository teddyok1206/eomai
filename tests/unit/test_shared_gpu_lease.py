"""Synthetic local mutex tests; no production lock/group, root, model or GPU access."""

from __future__ import annotations

import ast
import errno
import fcntl
import grp
import inspect
import os
import select
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_gpu_lease import SHARED_GPU_LOCK_PATH, SharedGpuLeaseError
from eom_gpu_lease import lease as adapter

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> adapter._LeasePolicy:
    parent = tmp_path / "run" / "eom-gpu-lease"
    parent.mkdir(parents=True, mode=0o750)
    parent.parent.chmod(0o755)
    parent.chmod(0o750)
    path = parent / "gpu0.lock"
    path.write_bytes(b"")
    path.chmod(0o640)
    value = adapter._LeasePolicy(path, tmp_path, os.geteuid(), os.getegid())
    device = path.stat().st_dev
    mountinfo = f"1 0 {os.major(device)}:{os.minor(device)} / /synthetic rw - tmpfs tmpfs rw\n"
    monkeypatch.setattr(adapter, "_read_mountinfo", lambda: mountinfo)
    return value


def _invalid(policy: adapter._LeasePolicy) -> None:
    with pytest.raises(SharedGpuLeaseError, match="INVALID") as error:
        adapter._claim(policy)
    assert error.value.code == "INVALID"


def _child_code() -> str:
    return """import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from eom_gpu_lease import lease as adapter
path, anchor = Path(sys.argv[2]), Path(sys.argv[3])
device = path.stat().st_dev
device_id = f'{os.major(device)}:{os.minor(device)}'
adapter._read_mountinfo = lambda: f'1 0 {device_id} / /synthetic rw - tmpfs tmpfs rw\\n'
policy = adapter._LeasePolicy(path, anchor, os.geteuid(), os.getegid())
try:
    lease = adapter._claim(policy)
except adapter.SharedGpuLeaseError as error:
    print(error.code, flush=True)
else:
    print('OWNED', flush=True)
    if len(sys.argv) > 4:
        sys.stdin.readline()
    lease.close()
"""


def _child_arguments(policy: adapter._LeasePolicy) -> list[str]:
    return [
        sys.executable,
        "-I",
        "-c",
        _child_code(),
        str(ROOT / "packages/gpu_lease"),
        str(policy.path),
        str(policy.anchor),
    ]


def _child_claim(policy: adapter._LeasePolicy) -> str:
    completed = subprocess.run(_child_arguments(policy), capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_public_claim_is_fixed_and_has_no_authority_or_path_parameter() -> None:
    assert str(SHARED_GPU_LOCK_PATH) == "/run/eom-gpu-lease/gpu0.lock"
    assert not inspect.signature(adapter.acquire_shared_gpu_lease).parameters
    assert not inspect.signature(adapter.shared_gpu_lease).parameters


def test_readonly_existing_descriptor_and_no_mutation(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[int] = []
    original_open = os.open

    def checked_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_RDWR)
        descriptor = original_open(path, flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("worker mutation is forbidden")

    monkeypatch.setattr(os, "open", checked_open)
    for name in ("write", "chmod", "fchmod", "chown", "fchown", "rename", "unlink", "mkdir"):
        monkeypatch.setattr(os, name, forbidden)
    lease = adapter._claim(policy)
    descriptor = lease.fileno()
    assert fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert not os.get_inheritable(descriptor)
    lease.close()
    lease.close()
    with pytest.raises(SharedGpuLeaseError):
        lease.fileno()
    for held in opened:
        with pytest.raises(OSError, match="Bad file descriptor"):
            os.fstat(held)
    assert policy.path.read_bytes() == b""


def test_kernel_rejects_write_on_shared_readonly_fd(policy: adapter._LeasePolicy) -> None:
    lease = adapter._claim(policy)
    try:
        with pytest.raises(OSError) as error:
            os.write(lease.fileno(), b"x")
        assert error.value.errno == errno.EBADF
    finally:
        lease.close()


def test_nondestructive_handle_revalidation_preserves_contention_and_rejects_closed(
    policy: adapter._LeasePolicy,
) -> None:
    lease = adapter._claim(policy)
    try:
        lease.assert_valid()
        assert _child_claim(policy) == "BUSY"
        lease.assert_valid()
    finally:
        lease.close()
    with pytest.raises(SharedGpuLeaseError, match="INVALID"):
        lease.assert_valid()
    assert _child_claim(policy) == "OWNED"


def test_nondestructive_handle_validation_rejects_drift_without_releasing(
    policy: adapter._LeasePolicy,
) -> None:
    lease = adapter._claim(policy)
    duplicate = os.dup(lease.fileno())
    policy.path.chmod(0o600)
    try:
        with pytest.raises(SharedGpuLeaseError, match="INVALID"):
            lease.assert_valid()
        assert os.fstat(lease.fileno()).st_ino == policy.path.stat().st_ino
        with pytest.raises(SharedGpuLeaseError, match="INVALID"):
            lease.close()
        policy.path.chmod(0o640)
        assert _child_claim(policy) == "BUSY"
    finally:
        os.close(duplicate)
    assert _child_claim(policy) == "OWNED"


@pytest.mark.parametrize("mode", [0o600, 0o660, 0o644, 0o440, 0o777])
def test_wrong_file_modes_fail_without_chmod(policy: adapter._LeasePolicy, mode: int) -> None:
    policy.path.chmod(mode)
    _invalid(policy)
    assert policy.path.stat().st_mode & 0o777 == mode


@pytest.mark.parametrize("mode", [0o700, 0o770, 0o755, 0o777])
def test_wrong_parent_modes_fail(policy: adapter._LeasePolicy, mode: int) -> None:
    policy.path.parent.chmod(mode)
    _invalid(policy)


def test_wrong_owner_and_group_fail(policy: adapter._LeasePolicy) -> None:
    _invalid(
        adapter._LeasePolicy(policy.path, policy.anchor, policy.owner_uid + 1, policy.group_gid)
    )
    _invalid(
        adapter._LeasePolicy(policy.path, policy.anchor, policy.owner_uid, policy.group_gid + 1)
    )


def test_missing_file_is_not_created(policy: adapter._LeasePolicy) -> None:
    policy.path.unlink()
    _invalid(policy)
    assert not policy.path.exists()


def test_symlink_file_and_ancestor_fail(policy: adapter._LeasePolicy) -> None:
    original = policy.path.with_name("original.lock")
    policy.path.rename(original)
    policy.path.symlink_to(original)
    _invalid(policy)
    policy.path.unlink()
    original.rename(policy.path)
    parent = policy.path.parent
    renamed = parent.with_name("renamed")
    parent.rename(renamed)
    parent.symlink_to(renamed, target_is_directory=True)
    _invalid(policy)


def test_hardlink_nonregular_and_nonempty_files_fail(policy: adapter._LeasePolicy) -> None:
    duplicate = policy.path.with_name("duplicate.lock")
    os.link(policy.path, duplicate)
    _invalid(policy)
    duplicate.unlink()
    policy.path.write_bytes(b"unexpected")
    _invalid(policy)
    policy.path.unlink()
    os.mkfifo(policy.path, mode=0o640)
    _invalid(policy)


def test_writable_ancestor_fails(policy: adapter._LeasePolicy) -> None:
    ancestor = policy.path.parent.parent
    ancestor.chmod(0o775)
    _invalid(policy)


@pytest.mark.parametrize("filesystem", ["ext4", "nfs", "cifs", "overlay"])
def test_non_tmpfs_mount_fails(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch, filesystem: str
) -> None:
    device = policy.path.stat().st_dev
    monkeypatch.setattr(
        adapter,
        "_read_mountinfo",
        lambda: (
            f"1 0 {os.major(device)}:{os.minor(device)} / /synthetic rw - {filesystem} source rw\n"
        ),
    )
    _invalid(policy)


@pytest.mark.parametrize(
    "mountinfo", ["", "invalid", "1 0 invalid / /synthetic rw - tmpfs tmpfs rw"]
)
def test_missing_or_malformed_mountinfo_fails(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch, mountinfo: str
) -> None:
    monkeypatch.setattr(adapter, "_read_mountinfo", lambda: mountinfo)
    _invalid(policy)


def test_inode_replacement_between_open_and_claim_fails_and_closes_all_fds(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_open = os.open
    opened: list[int] = []

    def replaced_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        opened.append(descriptor)
        if path == policy.path.name:
            policy.path.rename(policy.path.with_name("old.lock"))
            policy.path.write_bytes(b"")
            policy.path.chmod(0o640)
        return descriptor

    monkeypatch.setattr(os, "open", replaced_open)
    _invalid(policy)
    for descriptor in opened:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_replacement_during_busy_claim_is_invalid_not_busy(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    def replace_and_contend(descriptor: int, operation: int) -> None:
        policy.path.rename(policy.path.with_name("old.lock"))
        policy.path.write_bytes(b"")
        policy.path.chmod(0o640)
        raise BlockingIOError(errno.EWOULDBLOCK, "synthetic busy")

    monkeypatch.setattr(fcntl, "flock", replace_and_contend)
    _invalid(policy)


@pytest.mark.parametrize("change", ["file_mode", "file_inode", "parent_inode"])
def test_epoch_drift_at_close_fails_but_releases_all_fds(
    policy: adapter._LeasePolicy, change: str
) -> None:
    lease = adapter._claim(policy)
    descriptor = lease.fileno()
    if change == "file_mode":
        policy.path.chmod(0o600)
    elif change == "file_inode":
        policy.path.rename(policy.path.with_name("old.lock"))
        policy.path.write_bytes(b"")
        policy.path.chmod(0o640)
    else:
        policy.path.parent.rename(policy.path.parent.with_name("old-parent"))
        policy.path.parent.mkdir(mode=0o750)
    with pytest.raises(SharedGpuLeaseError, match="INVALID"):
        lease.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_first_fstat_failure_does_not_leak_just_opened_directory(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_open, original_fstat = os.open, os.fstat
    opened: list[int] = []

    def remember(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def fail_once(descriptor: int) -> os.stat_result:
        if len(opened) == 1:
            raise OSError(errno.EIO, "synthetic fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(os, "open", remember)
    monkeypatch.setattr(os, "fstat", fail_once)
    _invalid(policy)
    with pytest.raises(OSError, match="Bad file descriptor"):
        original_fstat(opened[0])


def test_close_failure_is_stable_and_still_attempts_every_other_fd(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = adapter._claim(policy)
    descriptor = lease.fileno()
    original_close = os.close
    closed: list[int] = []

    def failing_close(value: int) -> None:
        original_close(value)
        closed.append(value)
        if value == descriptor:
            raise OSError(errno.EIO, "synthetic close diagnostic")

    monkeypatch.setattr(os, "close", failing_close)
    with pytest.raises(SharedGpuLeaseError, match="INVALID"):
        lease.close()
    assert len(closed) == len(policy.path.parent.relative_to(policy.anchor).parts) + 2
    assert descriptor in closed


def test_independent_process_contention_and_last_dup_close(policy: adapter._LeasePolicy) -> None:
    lease = adapter._claim(policy)
    duplicate = os.dup(lease.fileno())
    assert _child_claim(policy) == "BUSY"
    lease.close()
    try:
        assert _child_claim(policy) == "BUSY"
    finally:
        os.close(duplicate)
    assert _child_claim(policy) == "OWNED"


def test_process_death_releases_kernel_mutex_not_gpu_cleanup_proof(
    policy: adapter._LeasePolicy,
) -> None:
    process = subprocess.Popen(
        [*_child_arguments(policy), "hold"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 10)[0]
        assert process.stdout.readline().strip() == "OWNED"
        with pytest.raises(SharedGpuLeaseError, match="BUSY"):
            adapter._claim(policy)
        process.kill()
        process.communicate(timeout=10)
        lease = adapter._claim(policy)
        lease.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_missing_dedicated_group_and_root_gid_fail_without_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> Any:
        raise KeyError(name)

    monkeypatch.setattr(grp, "getgrnam", missing)
    with pytest.raises(SharedGpuLeaseError, match="INVALID"):
        adapter.acquire_shared_gpu_lease()
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=0))
    with pytest.raises(SharedGpuLeaseError, match="INVALID"):
        adapter.acquire_shared_gpu_lease()


def test_package_is_python311_parseable_and_imports_stdlib_only() -> None:
    path = ROOT / "packages/gpu_lease/eom_gpu_lease/lease.py"
    tree = ast.parse(path.read_text(), feature_version=(3, 11))
    imports = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imports <= sys.stdlib_module_names
