"""Only closed elapsed-stage metadata may leave the actual Catalog read boundary."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from eom_catalog_service import inference_transfer_read_timing as module


@pytest.mark.parametrize("stage", tuple(module.InferenceTransferReadStage))
@pytest.mark.parametrize("aborted", (False, True))
def test_closed_timing_fields_and_original_failure(stage, aborted, monkeypatch):
    recorder = Mock()
    clock = Mock(side_effect=(1_000_000_000, 1_012_999_999))
    monkeypatch.setattr(module, "log_event", recorder)
    monkeypatch.setattr(module, "perf_counter_ns", clock)
    original = ValueError("private query, source and credential must never be logged")

    def operation():
        with module.observe_read_stage(stage):
            if aborted:
                raise original

    if aborted:
        with pytest.raises(ValueError) as failure:
            operation()
        assert failure.value is original
    else:
        operation()
    recorder.assert_called_once()
    args, fields = recorder.call_args
    assert json.loads(args[2]) == {
        "stage": stage.value,
        "elapsed_ms": 12,
        "outcome": "ABORTED" if aborted else "COMPLETED",
    }
    assert fields == {
        "job_id": None,
        "worker_slot": None,
        "component": "catalog_similarity_read",
        "event": "SIMILARITY_READ_STAGE",
    }
    assert clock.call_count == 2


@pytest.mark.parametrize("aborted", (False, True))
def test_failed_logger_does_not_change_business_result(monkeypatch, aborted):
    monkeypatch.setattr(module, "log_event", Mock(side_effect=OSError("log unavailable")))
    failure = RuntimeError("original failure")

    def operation():
        with module.observe_read_stage(module.InferenceTransferReadStage.COMPOSE_CONTEXT):
            if aborted:
                raise failure
            return "original result"

    if aborted:
        with pytest.raises(RuntimeError) as caught:
            operation()
        assert caught.value is failure
    else:
        assert operation() == "original result"


def test_invalid_internal_stage_never_logs_free_text(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(module, "log_event", recorder)
    with module.observe_read_stage("untrusted input, never log"):  # type: ignore[arg-type]
        pass
    recorder.assert_not_called()


def test_nested_observations_remain_independent(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(module, "log_event", recorder)
    monkeypatch.setattr(
        module, "perf_counter_ns", Mock(side_effect=(0, 1_000_000, 3_000_000, 9_000_000))
    )
    with (
        module.observe_read_stage(module.InferenceTransferReadStage.COMPOSE_CONTEXT),
        module.observe_read_stage(module.InferenceTransferReadStage.SOLUTION_PROFILES),
    ):
        pass
    assert [json.loads(call.args[2])["elapsed_ms"] for call in recorder.call_args_list] == [2, 9]


@pytest.mark.parametrize("failure_at_start", (False, True))
def test_unavailable_clock_cannot_fail_work(monkeypatch, failure_at_start):
    recorder = Mock()
    clock = (
        Mock(side_effect=OSError("clock unavailable"))
        if failure_at_start
        else Mock(side_effect=(1_000_000, OSError("clock unavailable")))
    )
    monkeypatch.setattr(module, "log_event", recorder)
    monkeypatch.setattr(module, "perf_counter_ns", clock)
    with module.observe_read_stage(module.InferenceTransferReadStage.COMPOSE_CONTEXT):
        result = "unchanged"
    assert result == "unchanged"
    recorder.assert_not_called()
