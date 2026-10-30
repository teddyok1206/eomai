"""Protected local process adapter; model work remains in the existing queue."""

import argparse
import fcntl
import json
import os
import re
import signal
import stat
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from eom_orchestrator.database import build_engine
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.creative_cohort_execution import CreativeCohortExecutionService
from eom_catalog_service.creative_learning_cohort import read_creative_execution_scope
from eom_catalog_service.settings import CatalogSettings

STATE_ROOT = Path("/var/lib/eom/creative-learning")


def validate_state_root(root: Path) -> None:
    metadata = root.lstat()
    if (
        root.resolve() != root
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o750
    ):
        raise ValueError("CREATIVE_COHORT_STATUS_ROOT_INVALID")


def write_status(root: Path, cohort_id: str, value: dict[str, object]) -> None:
    """Atomic derived read model; never input authority or a completion receipt."""
    validate_state_root(root)
    if re.fullmatch(r"creativecohort_[0-9a-f]{32}", cohort_id) is None:
        raise ValueError("CREATIVE_COHORT_STATUS_ROOT_INVALID")
    payload = (
        json.dumps(
            {**value, "observed_at": datetime.now(UTC).isoformat()},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    if len(payload) > 16 * 1024:
        raise ValueError("CREATIVE_COHORT_STATUS_TOO_LARGE")
    target = root / (cohort_id + ".json")
    if target.exists() or target.is_symlink():
        before = target.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o640
        ):
            raise ValueError("CREATIVE_COHORT_STATUS_FILE_INVALID")
    temporary = root / (".status-" + uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def stable_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if code is None and type(error) is ValueError and len(error.args) == 1:
        code = error.args[0]
    return (
        code
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", code)
        else "CREATIVE_COHORT_EXECUTION_FAILED"
    )


def progress_poll_delay_seconds(state: str) -> int:
    # VERIFIED already passed the authoritative read boundary. Sleeping after each
    # cached-history reconstruction adds 10 seconds per completed source on restart.
    # Actual pending worker work retains bounded polling and graceful stop checks.
    return 0 if state == "VERIFIED" else 10


def main() -> None:
    parser = argparse.ArgumentParser(prog="eom-creative-learning")
    parser.add_argument(
        "--cohort-revision-id", default=os.environ.get("EOM_CREATIVE_COHORT_REVISION_ID")
    )
    parser.add_argument(
        "--verified-limit",
        type=int,
        default=int(os.environ.get("EOM_CREATIVE_VERIFIED_LIMIT", "3")),
    )
    arguments = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(
        r"rev_[0-9a-f]{32}", arguments.cohort_revision_id or ""
    ):
        parser.error("trusted owner and exact admitted cohort revision are required")
    settings, catalog_settings = Settings.from_environment(), CatalogSettings.from_environment()
    engine = build_engine()
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    descriptor = -1
    owns_lock = False
    cohort = None
    scope = None
    status: dict[str, object] = {}
    try:
        scope, _ = read_creative_execution_scope(
            CatalogArtifactService(engine, catalog_settings),
            ControlFileSetPublisher(engine, settings),
            arguments.cohort_revision_id,
        )
        cohort = scope.cohort
        if not 1 <= arguments.verified_limit <= len(cohort.targets):
            raise ValueError("CREATIVE_COHORT_EXECUTION_LIMIT_INVALID")
        validate_state_root(STATE_ROOT)
        descriptor = os.open(
            # A continuation shares its parent's source set and process fence.
            # Different execution/status IDs must not allow old/new owners together.
            STATE_ROOT / (cohort.cohort_id + ".lock"),
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        lock_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != 0
            or lock_metadata.st_nlink != 1
            or stat.S_IMODE(lock_metadata.st_mode) != 0o600
        ):
            raise ValueError("CREATIVE_COHORT_PROCESS_LOCK_INVALID")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owns_lock = True
        write_status(
            STATE_ROOT,
            scope.cohort_id,
            {"state": "STARTING", "verified_count": 0, "target_count": len(cohort.targets)},
        )
        service = CreativeCohortExecutionService(
            engine, cohort=cohort, settings=settings, catalog_settings=catalog_settings, scope=scope
        )
        previous = None
        while not stopped.is_set():
            progress = service.advance_once()
            status = asdict(progress)
            status["cohort_revision_id"] = arguments.cohort_revision_id
            status["verified_limit"] = arguments.verified_limit
            terminal = progress.verified_count >= arguments.verified_limit
            if terminal:
                status["state"] = (
                    "COMPLETED"
                    if progress.verified_count == len(cohort.targets)
                    else "CANARY_VERIFIED"
                )
            write_status(STATE_ROOT, scope.cohort_id, status)
            marker = (progress.external_number, status["state"], progress.verified_count)
            if marker != previous:
                print(json.dumps(status, ensure_ascii=False, sort_keys=True), flush=True)
                previous = marker
            if terminal:
                break
            stopped.wait(progress_poll_delay_seconds(progress.state))
        if stopped.is_set():
            write_status(STATE_ROOT, scope.cohort_id, {**status, "state": "STOPPED"})
    except Exception as error:
        code = stable_error_code(error)
        safe = {
            **status,
            "state": "STOPPED_TECHNICAL_FAILURE",
            "error_code": code,
            "exception_type": type(error).__name__,
        }
        if scope is not None and owns_lock:
            with suppress(OSError, ValueError):
                write_status(STATE_ROOT, scope.cohort_id, safe)
        print(json.dumps(safe, ensure_ascii=False, sort_keys=True), flush=True)
        raise SystemExit(78) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        engine.dispose()


if __name__ == "__main__":
    main()
