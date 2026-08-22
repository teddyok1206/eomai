"""Long-running orchestrator-owned Catalog application boundary."""

from __future__ import annotations

import argparse
import signal
import threading

from eom_orchestrator.database import build_engine

from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.item_content_import import StructuredItemContentImportService
from eom_catalog_service.registry_service import RegistryService


def serve() -> int:
    engine = build_engine()
    server: CatalogApplicationServer | None = None
    thread: threading.Thread | None = None
    stopping = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server = CatalogApplicationServer(
            StructuredItemContentImportService(engine),
            RegistryService(engine),
        )
        thread = threading.Thread(
            target=server.serve_forever,
            name="eom-catalog-application",
            daemon=True,
        )
        thread.start()
        while not stopping.wait(timeout=1):
            if not thread.is_alive():
                return 1
        return 0
    except Exception:
        return 1
    finally:
        if server is not None and thread is not None and thread.is_alive():
            server.shutdown()
        if server is not None:
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="eom-catalog-application-runner")
    parser.add_argument("command", choices=("serve",))
    arguments = parser.parse_args()
    if arguments.command != "serve":  # pragma: no cover - argparse owns the invariant
        parser.error("unsupported command")
    raise SystemExit(serve())


if __name__ == "__main__":
    main()
