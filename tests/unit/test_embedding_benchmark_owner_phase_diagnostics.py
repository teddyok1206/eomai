"""Content-free bounded owner diagnostics; no model, installed identity or actual timing claim."""

from __future__ import annotations

import json
import logging
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_benchmark_native_observation as owner


@pytest.fixture
def preserved_logger():
    logger = owner._LOGGER
    previous = (logger.handlers[:], logger.level, logger.propagate)
    try:
        yield logger
    finally:
        logger.handlers[:], level, logger.propagate = previous
        logger.setLevel(level)


def test_dedicated_configuration_is_idempotent_and_does_not_change_other_loggers(
    preserved_logger, monkeypatch, capsys
):
    root = logging.getLogger()
    monkeypatch.setattr(root, "level", logging.WARNING)
    root_before = root.handlers[:], root.level
    sibling = logging.getLogger("sqlalchemy.engine")
    sibling_before = sibling.handlers[:], sibling.level, sibling.propagate
    owner.configure_benchmark_observation_logging()
    owner.configure_benchmark_observation_logging()
    assert len(preserved_logger.handlers) == 1 and not preserved_logger.propagate
    owner._flush_owner_phases([(owner._OwnerPhase.ACK, 1, 1_999_999, True)])
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record) == {
        "timestamp",
        "level",
        "job_id",
        "worker_slot",
        "component",
        "event",
        "error_code",
        "message",
    }
    assert record["timestamp"].endswith("Z") and record["level"] == "INFO"
    assert record["event"] == "BENCHMARK_OWNER_PHASE"
    assert record["component"] == "catalog_embedding_benchmark"
    assert record["job_id"] is record["worker_slot"] is record["error_code"] is None
    assert json.loads(record["message"]) == {
        "phase": "ACK",
        "checkpoint_sequence": 1,
        "elapsed_ms": 1,
        "outcome": "COMPLETED",
    }
    assert (root.handlers, root.level) == root_before
    assert (sibling.handlers, sibling.level, sibling.propagate) == sibling_before


def test_failed_configuration_preserves_current_handlers(preserved_logger, monkeypatch):
    before = preserved_logger.handlers[:], preserved_logger.level, preserved_logger.propagate
    monkeypatch.setattr(owner.logging, "StreamHandler", Mock(side_effect=OSError("unavailable")))
    owner.configure_benchmark_observation_logging()
    assert (preserved_logger.handlers, preserved_logger.level, preserved_logger.propagate) == before


@pytest.mark.parametrize("aborted", (False, True))
@pytest.mark.parametrize("logging_failed", (False, True))
def test_phase_capture_performs_no_io_and_preserves_original_exception(
    monkeypatch, aborted, logging_failed
):
    recorder = Mock(side_effect=OSError("private logging failure") if logging_failed else None)
    monkeypatch.setattr(owner, "log_event", recorder)
    monkeypatch.setattr(owner.time, "monotonic_ns", Mock(side_effect=(1_000_000, 4_999_999)))
    observations = []
    original = ValueError("private text token password prompt must never be logged")

    def operation():
        with owner._observe_owner_phase(observations, owner._OwnerPhase.CHECKPOINT_RECEIVE, 1):
            recorder.assert_not_called()
            if aborted:
                raise original

    if aborted:
        with pytest.raises(ValueError) as caught:
            operation()
        assert caught.value is original
    else:
        operation()
    recorder.assert_not_called()
    assert observations == [(owner._OwnerPhase.CHECKPOINT_RECEIVE, 1, 3_999_999, not aborted)]
    owner._flush_owner_phases(observations)
    recorder.assert_called_once()
    args, fields = recorder.call_args
    assert json.loads(args[2]) == {
        "phase": "CHECKPOINT_RECEIVE",
        "checkpoint_sequence": 1,
        "elapsed_ms": 3,
        "outcome": "ABORTED" if aborted else "COMPLETED",
    }
    assert fields == {
        "job_id": None,
        "worker_slot": None,
        "component": "catalog_embedding_benchmark",
        "event": "BENCHMARK_OWNER_PHASE",
    }
    assert "private" not in args[2]


def test_buffer_is_bounded_even_if_an_internal_caller_repeats_capture(monkeypatch):
    clock = Mock(side_effect=range(1000))
    monkeypatch.setattr(owner.time, "monotonic_ns", clock)
    recorder = Mock()
    monkeypatch.setattr(owner, "log_event", recorder)
    observations = []
    for _ in range(owner._MAX_OWNER_PHASES + 1):
        with owner._observe_owner_phase(observations, owner._OwnerPhase.ACK, 1):
            pass
    assert len(observations) == owner._MAX_OWNER_PHASES
    recorder.assert_not_called()
    owner._flush_owner_phases(observations)
    assert recorder.call_count == owner._MAX_OWNER_PHASES


def test_failed_authorization_records_both_nested_owner_spans_without_early_logging(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(owner, "log_event", recorder)
    monkeypatch.setattr(owner.time, "monotonic_ns", Mock(side_effect=(1, 2, 3, 4)))
    observations = []
    original = ValueError("private authorization failure")
    with (
        pytest.raises(ValueError) as caught,
        owner._observe_owner_phase(observations, owner._OwnerPhase.ACK, 1),
        owner._observe_owner_phase(observations, owner._OwnerPhase.AUTHORIZATION, 1),
    ):
        raise original
    assert caught.value is original
    assert observations == [
        (owner._OwnerPhase.AUTHORIZATION, 1, 1, False),
        (owner._OwnerPhase.ACK, 1, 3, False),
    ]
    recorder.assert_not_called()
    owner._flush_owner_phases(observations)
    assert recorder.call_count == 2
    assert all(json.loads(call.args[2])["outcome"] == "ABORTED" for call in recorder.call_args_list)


@pytest.mark.parametrize("aborted", (False, True))
def test_failed_diagnostic_clock_does_not_change_operation(monkeypatch, aborted):
    monkeypatch.setattr(owner.time, "monotonic_ns", Mock(side_effect=OSError("clock unavailable")))
    observations = []
    original = ValueError("original failure")

    def operation():
        with owner._observe_owner_phase(observations, owner._OwnerPhase.CHECKPOINT_RECEIVE, 1):
            if aborted:
                raise original

    if aborted:
        with pytest.raises(ValueError) as caught:
            operation()
        assert caught.value is original
    else:
        operation()
    assert observations == []


@pytest.mark.parametrize(
    "observation",
    (
        ("private phase", 1, 0, True),
        (owner._OwnerPhase.ACK, True, 0, True),
        (owner._OwnerPhase.ACK, -1, 0, True),
        (owner._OwnerPhase.ACK, 22, 0, True),
        (owner._OwnerPhase.ACK, 1, "private elapsed", True),
        (owner._OwnerPhase.ACK, 1, -1, True),
        (owner._OwnerPhase.ACK, 1, 0, "private outcome"),
    ),
)
def test_invalid_internal_metadata_does_not_cross_logging_boundary(monkeypatch, observation):
    recorder = Mock()
    monkeypatch.setattr(owner, "log_event", recorder)
    owner._flush_owner_phases([observation])
    recorder.assert_not_called()
