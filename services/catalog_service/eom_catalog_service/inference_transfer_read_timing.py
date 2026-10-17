"""Bounded Catalog read-stage metadata; never authority, content or exception prose."""

from __future__ import annotations

import logging
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


_LOGGER = logging.getLogger(__name__)


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
