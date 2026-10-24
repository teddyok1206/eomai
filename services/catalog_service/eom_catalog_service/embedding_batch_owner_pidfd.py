"""One owned Linux pidfd for the original peer; no signals, process control or source grant."""

from __future__ import annotations

import ctypes
import os
import select
import time


class EmbeddingBatchOwnerPidfd:
    """Kernel identity survives PID reuse and the short /proc exit transition.

    The caller validates original UID/GID/birth before and after opening. This
    adapter only observes that same process exiting; it cannot authenticate an
    actor or authorize active work. libc is required because the installed Conda
    Python does not expose os.pidfd_open. There is no weaker PID-only fallback.
    """

    def __init__(self, pid: int) -> None:
        if type(pid) is not int or not 0 < pid < 2**31:
            raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_INVALID")
        library = ctypes.CDLL(None, use_errno=True)
        opener = getattr(library, "pidfd_open", None)
        if opener is None:
            raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_UNAVAILABLE")
        opener.argtypes = (ctypes.c_int, ctypes.c_uint)
        opener.restype = ctypes.c_int
        descriptor = int(opener(pid, 0))
        if descriptor < 0:
            raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_UNAVAILABLE")
        self._descriptor = descriptor
        self._closed = False
        self._identity: tuple[int, int, int] | None = None
        try:
            stat = os.fstat(descriptor)
            self._identity = (stat.st_dev, stat.st_ino, stat.st_mode)
            if os.get_inheritable(descriptor):
                raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_INVALID")
            if self.wait_exited(until_ns=time.monotonic_ns()):
                raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_ALREADY_EXITED")
        except BaseException:
            self.close()
            raise

    def wait_exited(self, *, until_ns: int) -> bool:
        """Bounded by the original deadline; no new work or release authority."""
        if self._closed or type(until_ns) is not int:
            raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_INVALID")
        stat = os.fstat(self._descriptor)
        if (stat.st_dev, stat.st_ino, stat.st_mode) != self._identity:
            raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_CHANGED")
        poll = select.poll()
        poll.register(self._descriptor, select.POLLIN | select.POLLHUP)
        remaining = max(0, until_ns - time.monotonic_ns())
        # Only settling after a verified terminal frame may wait; callers pass
        # no more than 100ms and never exceed the original allocation deadline.
        milliseconds = min(100, (remaining + 999_999) // 1_000_000)
        events = poll.poll(milliseconds)
        if not events:
            return False
        if (
            len(events) != 1
            or events[0][0] != self._descriptor
            or events[0][1] & (select.POLLNVAL | select.POLLERR)
        ):
            raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_CHANGED")
        return bool(events[0][1] & (select.POLLIN | select.POLLHUP))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._identity is not None:
                stat = os.fstat(self._descriptor)
                if (stat.st_dev, stat.st_ino, stat.st_mode) != self._identity:
                    raise ValueError("EMBEDDING_BATCH_OWNER_PIDFD_CHANGED")
            os.close(self._descriptor)
