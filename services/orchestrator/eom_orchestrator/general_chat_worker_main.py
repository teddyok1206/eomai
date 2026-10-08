"""Fixed isolated service composition; no owner DB/NAS or credential enrollment."""

from __future__ import annotations

import argparse
import os
import pwd
import signal
import sys
from contextlib import suppress
from pathlib import Path
from threading import Event
from uuid import uuid4

from eom_protocol.general_chat_worker_messages import ChatWorkerFault

from eom_orchestrator.general_chat_handoff import ChatLocalHandoff
from eom_orchestrator.general_chat_native_worker import (
    IsolatedCodexChatWorker,
    source_chat_worker_policy,
)
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.general_chat_stdio import CHAT_USER, require_native_chat_identity
from eom_orchestrator.general_chat_worker import ChatWorkerApplication
from eom_orchestrator.general_chat_worker_lifecycle import serve_chat_worker
from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer

HANDOFF_DIRECTORY = Path("/var/lib/eom-general-chat-worker/handoff")
WORKER_SOCKET = Path("/run/eom-general-chat-worker/worker.sock")


def main() -> int:
    parser = argparse.ArgumentParser(description="EOM isolated dedicated chat worker")
    parser.add_argument("--model", required=True, help="Explicit installed model pin; no fallback")
    args = parser.parse_args()
    native: IsolatedCodexChatWorker | None = None
    try:
        # Reject the invoking identity before reading private handoff/native auth.
        require_native_chat_identity()
        worker = pwd.getpwnam(CHAT_USER)
        owner = pwd.getpwnam("eom-general-chat")
        stop = Event()
        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, lambda *_: stop.set())
        selected = source_chat_worker_policy(model=args.model)
        with ChatLocalHandoff(HANDOFF_DIRECTORY, worker_uid=worker.pw_uid) as handoff:
            native = IsolatedCodexChatWorker(policy=selected)
            application = ChatWorkerApplication(
                native,
                handoff,
                policy=selected,
                boot_id="chatboot_" + uuid4().hex,
            )
            endpoint = ChatSocketEndpoint(WORKER_SOCKET, worker.pw_uid, worker.pw_gid)
            server = ChatWorkerRpcServer(application, endpoint=endpoint, owner_uid=owner.pw_uid)
            return serve_chat_worker(server, stop=stop, retirement=native.retirement_requested)
    except Exception as error:
        code = (
            error.code.value
            if isinstance(error, ChatWorkerFault)
            else "GENERAL_CHAT_WORKER_NOT_READY"
        )
        sys.stderr.write(code + "\n")
        return 1
    finally:
        if native is not None:
            with suppress(Exception):
                native.close()


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
