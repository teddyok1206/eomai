"""Drain local evidence before retiring the isolated native worker service."""

from __future__ import annotations

from threading import Event, Thread

from eom_orchestrator.general_chat_worker_server import ChatWorkerRpcServer


def serve_chat_worker(server: ChatWorkerRpcServer, *, stop: Event, retirement: Event) -> int:
    finished = Event()

    def stop_accepting() -> None:
        while not finished.wait(0.2):
            if stop.is_set() or retirement.is_set():
                server.stop()
                return

    watcher = Thread(target=stop_accepting, name="chat-worker-drain")
    watcher.start()
    try:
        server.serve()
    finally:
        finished.set()
        watcher.join()
        # In-flight handlers publish/reply before native close/systemd restart.
        # Interrupted unknown answers keep their exclusive pending markers.
        server.close()
    return 75 if retirement.is_set() and not stop.is_set() else 0
