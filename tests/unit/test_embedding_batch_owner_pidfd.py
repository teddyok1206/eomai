"""Real Linux pidfd lifetime only, no GPU, source authority, credentials or signals."""

from __future__ import annotations

import os
import time

import pytest
from eom_catalog_service.embedding_batch_owner_pidfd import EmbeddingBatchOwnerPidfd


def test_original_pidfd_is_cloexec_alive_and_closed_once():
    handle = EmbeddingBatchOwnerPidfd(os.getpid())
    descriptor = handle._descriptor
    assert not os.get_inheritable(descriptor)
    assert not handle.wait_exited(until_ns=time.monotonic_ns())
    handle.close()
    handle.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)
    with pytest.raises(ValueError):
        handle.wait_exited(until_ns=time.monotonic_ns())


def test_kernel_confirms_original_child_exit_before_and_after_reaping():
    source, target = os.pipe2(os.O_CLOEXEC)
    child = os.fork()
    if child == 0:
        os.close(target)
        os.read(source, 1)
        os._exit(0)
    os.close(source)
    handle = EmbeddingBatchOwnerPidfd(child)
    try:
        assert not handle.wait_exited(until_ns=time.monotonic_ns())
        os.write(target, b"1")
        assert handle.wait_exited(until_ns=time.monotonic_ns() + 10**9)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert handle.wait_exited(until_ns=time.monotonic_ns())
    finally:
        os.close(target)
        handle.close()


@pytest.mark.parametrize("pid", (True, 0, -1, 2147483647))
def test_invalid_or_absent_process_never_becomes_a_pid_only_fallback(pid):
    with pytest.raises(ValueError):
        EmbeddingBatchOwnerPidfd(pid)


def test_replaced_descriptor_is_not_closed_as_if_it_were_owned(tmp_path):
    handle = EmbeddingBatchOwnerPidfd(os.getpid())
    descriptor = handle._descriptor
    replacement = os.open(tmp_path / "other", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        os.dup2(replacement, descriptor, inheritable=False)
        with pytest.raises(ValueError):
            handle.wait_exited(until_ns=time.monotonic_ns())
        with pytest.raises(ValueError):
            handle.close()
        assert os.fstat(descriptor).st_ino == os.fstat(replacement).st_ino
    finally:
        os.close(descriptor)
        os.close(replacement)
