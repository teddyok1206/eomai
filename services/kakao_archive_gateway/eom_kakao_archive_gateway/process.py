"""Own one unreaped process session; terminate accepted connection children with it."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import suppress

from .grant_file import GatewayRuntimeError

GRACE_SECONDS = 0.25


class GatewayChild:
    def __init__(self, child: subprocess.Popen[bytes]) -> None:
        self.child = child
        self.closed = False
        if os.getpgid(child.pid) != child.pid or os.getsid(child.pid) != child.pid:
            # An invalid injected launch must never signal an unrelated process group.
            child.kill()
            child.wait(timeout=2)
            raise GatewayRuntimeError("KAKAO_GATEWAY_CHILD_SESSION_INVALID")

    def exited(self) -> bool:
        # WNOWAIT retains the leader PID, preventing PGID reuse before final group kill.
        return os.waitid(os.P_PID, self.child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None

    def close(self) -> None:
        if self.closed:
            return
        with suppress(ProcessLookupError):
            os.killpg(self.child.pid, signal.SIGTERM)
        deadline = time.monotonic() + GRACE_SECONDS
        while not self.exited() and time.monotonic() < deadline:
            time.sleep(0.01)
        # Even an exited leader can have live connection children. Kill before reaping.
        with suppress(ProcessLookupError):
            os.killpg(self.child.pid, signal.SIGKILL)
        try:
            self.child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise GatewayRuntimeError("KAKAO_GATEWAY_CHILD_STOP_UNKNOWN") from None
        self.closed = True
        # No cgroup-empty success receipt: the fixed systemd owner confirms that later.
