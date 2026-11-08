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

from eom_catalog_service.item_origin_models import AssessmentOccurrenceRevisionRecord
from eom_catalog_service.registry_service import RegistryService
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine

from eom_hwpx_manager.application_service import (
    HwpxApplicationService,
    ItemRecoveryState,
    SecureHwpxDownload,
)
from eom_hwpx_manager.curated_application_service import (
    CuratedHwpxApplicationService,
    CuratedRecoveryState,
)
from eom_hwpx_manager.curated_composition import build_curated_application
from eom_hwpx_manager.download_server import HwpxDownloadServer
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.exam_application_service import (
    ExamHwpxApplicationService,
    ExamRecoveryState,
)
from eom_hwpx_manager.runtime_privileges import manager_runtime_privileges_ready
from eom_hwpx_manager.settings import HwpxSettings

# The standalone runner composes a narrower module graph than the Application API.
# Register the identity-owned FK target explicitly so SQLAlchemy can flush state
# transitions for HwpxApplicationBuildRecord without relying on incidental imports.
_RUNTIME_MODEL_TABLES = (OperatorRecord.__table__, AssessmentOccurrenceRevisionRecord.__table__)


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


def run_once(*, verify_privileges: bool = True, queue_offset: int = 0) -> int:
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
        item_service = HwpxApplicationService(
            engine,
            registry=registry,
        )
        exam_service = ExamHwpxApplicationService(engine, registry=registry)
        queues: tuple[
            tuple[
                str,
                HwpxApplicationService | ExamHwpxApplicationService | CuratedHwpxApplicationService,
            ],
            ...,
        ] = (
            ("item", item_service),
            ("assessment", exam_service),
            ("curated", build_curated_application(engine)),
        )
        offset = queue_offset % len(queues)
        queues = queues[offset:] + queues[:offset]
        for queue_name, service in queues:
            record = service.process_next()
            if record is not None:
                print(f"hwpx_application_build={record.build_id}:{record.state} queue={queue_name}")
                return 0
        print("hwpx_application_build=IDLE")
        return 2
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
    queue_offset = 0

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
        curated_service = build_curated_application(download_engine)

        class DownloadResolver:
            def secure_download(self, build_id: str) -> SecureHwpxDownload:
                try:
                    return item_service.secure_download(build_id)
                except HwpxManagerError as exc:
                    if exc.code is not HwpxManagerErrorCode.HWPX_APPLICATION_BUILD_NOT_FOUND:
                        raise
                return exam_service.secure_download(build_id)

            def secure_curated_download(self, build_id: str) -> SecureHwpxDownload:
                # The API authenticates the live requester. The broker also
                # reauthorizes the persisted initiator and exact saved sources.
                return curated_service.secure_broker_download(build_id)

        download_server = HwpxDownloadServer(DownloadResolver())
        server_thread = threading.Thread(
            target=download_server.serve_forever,
            name="eom-hwpx-download",
            daemon=True,
        )
        server_thread.start()
        recovering_interrupted = True
        while not stopping:
            curated_recovery = curated_service.recover_interrupted()
            if curated_recovery.state is CuratedRecoveryState.RECOVERED:
                assert curated_recovery.record is not None
                print(
                    f"hwpx_curated_build={curated_recovery.record.build_id}:{curated_recovery.record.state}"
                )
            if recovering_interrupted:
                item_recovery = item_service.recover_interrupted()
                if item_recovery.state is ItemRecoveryState.ACTIVE:
                    time.sleep(interval_seconds)
                    continue
                if item_recovery.state is ItemRecoveryState.TERMINALIZED:
                    assert item_recovery.record is not None
                    print(
                        f"hwpx_item_build={item_recovery.record.build_id}:{item_recovery.record.state}"
                    )
                    continue
                recovery = exam_service.recover_interrupted()
                if recovery.state is ExamRecoveryState.ACTIVE:
                    assert recovery.record is not None
                    print(f"hwpx_assessment_build={recovery.record.build_id}:RECOVERING")
                    time.sleep(interval_seconds)
                    continue
                if recovery.state is ExamRecoveryState.TERMINALIZED:
                    assert recovery.record is not None
                    print(
                        f"hwpx_assessment_build={recovery.record.build_id}:{recovery.record.state}"
                    )
                    continue
                recovering_interrupted = False
            result = run_once(verify_privileges=False, queue_offset=queue_offset)
            queue_offset = (queue_offset + 1) % 3
            if result == 2:
                time.sleep(interval_seconds)
            elif result != 0:
                # `process_next` has already terminalized a claimed build before surfacing its
                # sanitized failure. Keep the independent FIFO service alive for later builds;
                # the bounded poll interval also prevents a tight loop on an unavailable adapter.
                time.sleep(interval_seconds)
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
