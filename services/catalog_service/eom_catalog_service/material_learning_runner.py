"""Thin installed process adapter; all task/state/model rules stay in application owners."""

import json
import os
import re
import signal
from dataclasses import asdict
from threading import Event

from eom_orchestrator.database import build_engine, recoverable_database_error_code
from eom_orchestrator.settings import Settings
from sqlalchemy.exc import DBAPIError

from eom_catalog_service.material_learning_runtime import (
    MaterialLearningRuntimePins,
    build_material_learning_runtime,
)
from eom_catalog_service.settings import CatalogSettings


def stable_material_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if code is None and type(error) is ValueError and len(error.args) == 1:
        code = error.args[0]
    return (
        code
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", code)
        else "MATERIAL_LEARNING_PROCESSING_FAILED"
    )


def main() -> None:
    if os.geteuid() != 0:
        raise ValueError("MATERIAL_LEARNING_TRUSTED_OWNER_REQUIRED")
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    engine = build_engine()
    try:
        runtime = build_material_learning_runtime(
            engine,
            MaterialLearningRuntimePins.from_environment(),
            platform=Settings.from_environment(),
            catalog=CatalogSettings.from_environment(),
        )
        previous = None
        while not stopped.is_set():
            try:
                progress = runtime.processing.advance_once()
                marker = (progress.run_id, progress.task_id, progress.phase)
                if marker != previous:
                    print(json.dumps(asdict(progress), sort_keys=True), flush=True)
                    previous = marker
                # Child commands are driven by the installed global Workflow
                # Runner. This loop never becomes a parallel model executor or
                # blocks the durable material lease while a Codex turn runs.
                stopped.wait(
                    10
                    if progress.phase
                    in {"IDLE", "PAUSED", "RUNNING", "ANALYZING", "WAITING_FOR_CAPACITY"}
                    else 1
                )
            except DBAPIError as error:
                code = recoverable_database_error_code(error)
                if code is None:
                    raise
                print(json.dumps({"phase": "WAITING_FOR_DATABASE", "error_code": code}), flush=True)
                stopped.wait(30)
    except Exception as error:
        print(
            json.dumps(
                {
                    "phase": "STOPPED",
                    "error_code": stable_material_error_code(error),
                    "error_type": type(error).__name__,
                }
            ),
            flush=True,
        )
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
