"""Single-purpose queue runner for Item Revision HWPX application builds."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time

from eom_catalog_service.registry_service import RegistryService
from eom_orchestrator.database import build_engine

from eom_hwpx_manager.application_service import HwpxApplicationService
from eom_hwpx_manager.download_server import HwpxDownloadServer
from eom_hwpx_manager.errors import HwpxManagerError


def run_once() -> int:
    engine = build_engine()
    try:
        record = HwpxApplicationService(
            engine,
            registry=RegistryService(engine),
        ).process_next()
        if record is None:
            print("hwpx_application_build=IDLE")
            return 2
        print(f"hwpx_application_build={record.build_id}:{record.state}")
        return 0
    except HwpxManagerError as exc:
        print(
            f"hwpx_application_build=FAILED error_code={exc.code.value}",
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            "hwpx_application_build=FAILED error_code=HWPX_RUNNER_INTERNAL_ERROR",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


def serve(interval_seconds: float) -> int:
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    download_engine = build_engine()
    download_server: HwpxDownloadServer | None = None
    server_thread: threading.Thread | None = None
    try:
        download_server = HwpxDownloadServer(
            HwpxApplicationService(
                download_engine,
                registry=RegistryService(download_engine),
            )
        )
        server_thread = threading.Thread(
            target=download_server.serve_forever,
            name="eom-hwpx-download",
            daemon=True,
        )
        server_thread.start()
        while not stopping:
            result = run_once()
            if result == 2:
                time.sleep(interval_seconds)
            elif result != 0:
                return result
        return 0
    except Exception:
        print(
            "hwpx_application_manager=FAILED error_code=HWPX_MANAGER_BOUNDARY_UNAVAILABLE",
            file=sys.stderr,
        )
        return 1
    finally:
        if download_server is not None:
            download_server.shutdown()
            download_server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=5)
        download_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="eom-hwpx-application-runner")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("run-once")
    server = subcommands.add_parser("serve")
    server.add_argument("--interval-seconds", type=float, default=2.0)
    arguments = parser.parse_args()
    if arguments.command == "run-once":
        raise SystemExit(run_once())
    if not 0.25 <= arguments.interval_seconds <= 60:
        parser.error("interval must be between 0.25 and 60 seconds")
    raise SystemExit(serve(arguments.interval_seconds))


if __name__ == "__main__":
    main()
