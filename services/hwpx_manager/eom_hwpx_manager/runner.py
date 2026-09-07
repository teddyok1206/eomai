"""Single-purpose queue runner for Item Revision HWPX application builds."""

from __future__ import annotations

import argparse
import os
import signal
import stat
import sys
import threading
import time
from pathlib import Path

from eom_catalog_service.registry_service import RegistryService
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine

from eom_hwpx_manager.application_service import HwpxApplicationService, SecureHwpxDownload
from eom_hwpx_manager.download_server import HwpxDownloadServer
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.exam_application_service import ExamHwpxApplicationService
from eom_hwpx_manager.runtime_privileges import manager_runtime_privileges_ready
from eom_hwpx_manager.settings import HwpxSettings

# The standalone runner composes a narrower module graph than the Application API.
# Register the identity-owned FK target explicitly so SQLAlchemy can flush state
# transitions for HwpxApplicationBuildRecord without relying on incidental imports.
_RUNTIME_MODEL_TABLES = (OperatorRecord.__table__,)


def _runtime_privileges_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            return manager_runtime_privileges_ready(connection)
    except Exception:
        return False


def _runtime_staging_ready(path: Path) -> bool:
    """Create and verify the Manager-private staging root before queue claim."""
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
        metadata = path.lstat()
    except OSError:
        return False
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and not path.is_symlink()
        and metadata.st_uid == os.geteuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
        and os.access(path, os.W_OK | os.X_OK)
    )


def run_once(*, verify_privileges: bool = True) -> int:
    engine = build_engine()
    try:
        if verify_privileges and not _runtime_privileges_ready(engine):
            print(
                "hwpx_application_build=FAILED "
                "error_code=HWPX_MANAGER_DATABASE_PRIVILEGES_UNAVAILABLE",
                file=sys.stderr,
            )
            return 1
        if not _runtime_staging_ready(HwpxSettings.from_environment().staging_root):
            print(
                "hwpx_application_build=FAILED error_code=HWPX_MANAGER_STAGING_UNAVAILABLE",
                file=sys.stderr,
            )
            return 1
        registry = RegistryService(engine)
        item_record = HwpxApplicationService(
            engine,
            registry=registry,
        ).process_next()
        if item_record is not None:
            print(f"hwpx_application_build={item_record.build_id}:{item_record.state}")
            return 0
        exam_record = ExamHwpxApplicationService(engine, registry=registry).process_next()
        if exam_record is None:
            print("hwpx_application_build=IDLE")
            return 2
        print(f"hwpx_application_build={exam_record.build_id}:{exam_record.state}")
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
        if not _runtime_privileges_ready(download_engine):
            print(
                "hwpx_application_manager=FAILED "
                "error_code=HWPX_MANAGER_DATABASE_PRIVILEGES_UNAVAILABLE",
                file=sys.stderr,
            )
            return 1
        registry = RegistryService(download_engine)
        item_service = HwpxApplicationService(download_engine, registry=registry)
        exam_service = ExamHwpxApplicationService(download_engine, registry=registry)

        class DownloadResolver:
            def secure_download(self, build_id: str) -> SecureHwpxDownload:
                try:
                    return item_service.secure_download(build_id)
                except HwpxManagerError as exc:
                    if exc.code is not HwpxManagerErrorCode.HWPX_APPLICATION_BUILD_NOT_FOUND:
                        raise
                return exam_service.secure_download(build_id)

        download_server = HwpxDownloadServer(DownloadResolver())
        server_thread = threading.Thread(
            target=download_server.serve_forever,
            name="eom-hwpx-download",
            daemon=True,
        )
        server_thread.start()
        while not stopping:
            result = run_once(verify_privileges=False)
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
