"""Bounded Catalog read-stage metadata; never authority, content or exception prose."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from enum import StrEnum
from time import perf_counter_ns

from eom_identifiers import canonical_json_bytes
from eom_orchestrator.logging import JsonFormatter, log_event


class InferenceTransferReadStage(StrEnum):
    RESOLVE_COMPLETED_BEFORE = "RESOLVE_COMPLETED_BEFORE"
    COMPOSE_CONTEXT = "COMPOSE_CONTEXT"
    RESOLVE_COMPLETED_AFTER = "RESOLVE_COMPLETED_AFTER"
    FINAL_PROVENANCE = "FINAL_PROVENANCE"
    LOCK_POPULATION = "LOCK_POPULATION"
    PREFETCH_PROVENANCE = "PREFETCH_PROVENANCE"
    ADMIT_CANDIDATES = "ADMIT_CANDIDATES"
    SOLUTION_PROFILES = "SOLUTION_PROFILES"
    MATERIALIZE_ENTRIES = "MATERIALIZE_ENTRIES"
    PUBLIC_SOLUTION_REPORTS = "PUBLIC_SOLUTION_REPORTS"
    PUBLIC_INDEX_PREPARATION = "PUBLIC_INDEX_PREPARATION"


_LOGGER = logging.getLogger(__name__)


@contextmanager
def observe_read_failure() -> Iterator[None]:
    """Expose only bounded exception classes/code sites, never values or stack locals."""
    try:
        yield
    except Exception as original:
        with suppress(Exception):
            failures = []
            current: BaseException | None = original
            seen: set[int] = set()
            for _ in range(3):
                if current is None or id(current) in seen:
                    break
                seen.add(id(current))
                sites: list[str] = []
                frame = current.__traceback__
                for _ in range(64):
                    if frame is None:
                        break
                    module = frame.tb_frame.f_globals.get("__name__")
                    if type(module) is str and re.fullmatch(r"eom_[a-z0-9_.]{1,120}", module):
                        sites.append(f"{module}:{frame.tb_lineno}")
                    frame = frame.tb_next
                name = type(current).__name__
                failures.append(
                    {
                        "error_type": name
                        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name)
                        else "Exception",
                        "sites": sites[-2:],
                    }
                )
                current = current.__cause__ or current.__context__
            log_event(
                _LOGGER,
                logging.INFO,
                canonical_json_bytes({"failures": failures}).decode(),
                job_id=None,
                worker_slot=None,
                component="catalog_similarity_read",
                event="SIMILARITY_READ_FAILURE",
            )
        raise


def configure_read_stage_logging() -> None:
    """Enable only this closed metadata channel, never root/SQL/HTTP logging."""
    with suppress(Exception):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        _LOGGER.handlers[:] = [handler]
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.propagate = False


@contextmanager
def observe_read_stage(stage: InferenceTransferReadStage) -> Iterator[None]:
    """Preserve work/exception behavior even when optional diagnostics fail."""
    started: int | None = None
    with suppress(Exception):
        started = perf_counter_ns()
    completed = False
    try:
        yield
        completed = True
    finally:
        # No exception/argument values cross this logging boundary. Invalid
        # internal callers or a failed handler must not change the read result.
        with suppress(Exception):
            if started is not None and type(stage) is InferenceTransferReadStage:
                elapsed_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
                log_event(
                    _LOGGER,
                    logging.INFO,
                    canonical_json_bytes(
                        {
                            "stage": stage.value,
                            "elapsed_ms": elapsed_ms,
                            "outcome": "COMPLETED" if completed else "ABORTED",
                        }
                    ).decode("utf-8"),
                    job_id=None,
                    worker_slot=None,
                    component="catalog_similarity_read",
                    event="SIMILARITY_READ_STAGE",
                )
