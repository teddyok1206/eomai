"""Only closed elapsed-stage metadata may leave the actual Catalog read boundary."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_service import inference_transfer_read_timing as module


@pytest.fixture
def preserved_stage_logger():
    logger = module._LOGGER
    previous = (logger.handlers[:], logger.level, logger.propagate)
    try:
        yield logger
    finally:
        logger.handlers[:], level, logger.propagate = previous
        logger.setLevel(level)


@pytest.mark.parametrize("aborted", (False, True))
def test_startup_emits_real_safe_stderr_without_root_or_sibling_changes(
    preserved_stage_logger, monkeypatch, capsys, aborted
):
    root = logging.getLogger()
    monkeypatch.setattr(root, "level", logging.WARNING)
    root_before = (root.handlers[:], root.level)
    sibling = logging.getLogger("sqlalchemy.engine")
    sibling_before = (sibling.handlers[:], sibling.level, sibling.propagate)
    module.configure_read_stage_logging()
    module.configure_read_stage_logging()
    assert len(preserved_stage_logger.handlers) == 1
    assert preserved_stage_logger.propagate is False
    failure = ValueError("synthetic private input must never reach the logger")

    def operation():
        with module.observe_read_stage(module.InferenceTransferReadStage.COMPOSE_CONTEXT):
            if aborted:
                raise failure

    if aborted:
        with pytest.raises(ValueError) as caught:
            operation()
        assert caught.value is failure
    else:
        operation()
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
    assert record["level"] == "INFO"
    assert record["event"] == "SIMILARITY_READ_STAGE"
    assert record["component"] == "catalog_similarity_read"
    assert record["job_id"] is record["worker_slot"] is record["error_code"] is None
    fields = json.loads(record["message"])
    assert set(fields) == {"stage", "elapsed_ms", "outcome"}
    assert fields["stage"] == "COMPOSE_CONTEXT"
    assert fields["outcome"] == ("ABORTED" if aborted else "COMPLETED")
    assert "private input" not in lines[0]
    assert type(fields["elapsed_ms"]) is int and fields["elapsed_ms"] >= 0
    assert (root.handlers, root.level) == root_before
    assert (sibling.handlers, sibling.level, sibling.propagate) == sibling_before


def test_failed_startup_logging_does_not_change_existing_handlers(
    preserved_stage_logger, monkeypatch
):
    before = (
        preserved_stage_logger.handlers[:],
        preserved_stage_logger.level,
        preserved_stage_logger.propagate,
    )
    monkeypatch.setattr(module.logging, "StreamHandler", Mock(side_effect=OSError("unavailable")))
    module.configure_read_stage_logging()
    assert (
        preserved_stage_logger.handlers,
        preserved_stage_logger.level,
        preserved_stage_logger.propagate,
    ) == before


@pytest.mark.parametrize(
    ("relative", "entry", "before"),
    (
        ("services/catalog_service/eom_catalog_service/application_runner.py", "main", "serve"),
        (
            "services/workflow_runner/eom_workflow_runner/local_indexing_service_entry.py",
            "main",
            "build_local_indexing_service_runtime",
        ),
        (
            "services/workflow_runner/eom_workflow_runner/reference_query_owner_entry.py",
            "_serve_child",
            "build_reference_query_owner_runtime",
        ),
    ),
)
def test_composition_roots_enable_only_dedicated_logging_before_application(
    relative, entry, before
):
    source = ast.parse((Path(__file__).resolve().parents[2] / relative).read_text())
    function = next(
        node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == entry
    )
    calls = sorted(
        (node.lineno, ast.unparse(node.func))
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    )
    names = [name for _line, name in calls]
    assert names.count("configure_read_stage_logging") == 1
    assert names.index("configure_read_stage_logging") < names.index(before)
    assert "logging.basicConfig" not in names and "configure_logging" not in names
    if entry == "_serve_child":
        assert names.index("_require_dropped_identity") < names.index(
            "configure_read_stage_logging"
        )
    elif "build_local_indexing_service_runtime" in names:
        assert names.index("capture_local_indexing_runtime") < names.index(
            "configure_read_stage_logging"
        )


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
