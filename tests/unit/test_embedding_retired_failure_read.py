"""Concrete failure-reader composition; root/file/systemd leaves are synthetic."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_retired_failure_read as application
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.worker_systemd import FixedUnitStatus
from eom_workflow.embedding_encoding_recovery import RetiredEmbeddingRootFailure
from pydantic import TypeAdapter

from tests.unit.test_embedding_gpu_batch_controller import driver as driver
from tests.unit.test_embedding_gpu_batch_controller import machine as machine


@pytest.fixture
def original(driver, monkeypatch):
    retired = replace(
        driver.retired,
        original_terminal=replace(
            driver.retired.original_terminal,
            original_outcome="FAILED",
            terminal_unit=replace(
                driver.retired.original_terminal.terminal_unit,
                status=FixedUnitStatus("loaded", "failed", "failed", "exit-code", 1, 1, 100, False),
            ),
        ),
    )
    codec = TypeAdapter(type(retired))
    body = dict(
        event="EMBEDDING_GPU_BATCH_RETIRED_NOT_PUBLISHED",
        observation=codec.dump_python(retired, mode="json"),
    )
    raw = canonical_json_bytes(body)
    proof = RetiredEmbeddingRootFailure(
        allocation_attempt_id=driver.ready.readiness.allocation_attempt_id,
        invocation_id=driver.ready.unit.invocation_id,
        retirement_sha256=sha256_bytes(raw),
        retired_at=retired.observed_at_utc,
        parent_plan_job_id="job_" + "e" * 32,
        parent_request_sha256="sha256:" + "f" * 64,
        original_outcome="FAILED",
        stored_descriptors=0,
    )
    reader = Mock(spec=application.NumericalRuntimeFileSnapshots)
    reader.read.return_value = raw
    monkeypatch.setattr(application, "NumericalRuntimeFileSnapshots", lambda: reader)
    observe = Mock(return_value=retired.retired_unit)
    monkeypatch.setattr(application, "observe_stopped_gpu_unit", observe)
    monkeypatch.setattr(application.os, "getresuid", lambda: (0, 0, 0))
    return SimpleNamespace(proof=proof, retired=retired, body=body, reader=reader, observe=observe)


def test_exact_original_failed_retirement_and_late_os_file_fences(original):
    with application.read_retired_embedding_failure(original.proof) as resolved:
        assert resolved.proof == original.proof
        assert (
            resolved.allocation_request_sha256
            == original.retired.original_terminal.ready.readiness.allocation_request_sha256
        )
        args, kw = original.reader.read.call_args
        assert str(args[0]).endswith(original.proof.invocation_id + "/retirement/result.json")
        assert kw == dict(sha256=original.proof.retirement_sha256, maximum=256 * 1024)
    original.reader.assert_unchanged.assert_called_once()
    assert original.observe.call_count == 2


@pytest.mark.parametrize(
    "fault", ("success", "invocation", "allocation", "fdstore", "pid", "outcome", "extra", "time")
)
def test_ambiguous_or_changed_record_never_enters_mutation_window(original, fault):
    body = original.body
    record = body["observation"]
    if fault == "success":
        record["original_terminal"]["original_outcome"] = "SUCCEEDED"
    elif fault == "outcome":
        record["original_terminal"]["terminal_unit"]["status"]["result"] = "success"
        record["original_terminal"]["terminal_unit"]["status"]["active_state"] = "active"
        record["original_terminal"]["terminal_unit"]["status"]["sub_state"] = "exited"
        record["original_terminal"]["terminal_unit"]["status"]["exec_main_status"] = 0
    elif fault == "invocation":
        record["retired_unit"]["invocation_id"] = "f" * 32
    elif fault == "allocation":
        record["original_terminal"]["ready"]["readiness"]["allocation_attempt_id"] = (
            "embeddingallocation_" + "f" * 32
        )
    elif fault == "fdstore":
        record["retired_unit"]["stored_descriptors"] = 1
    elif fault == "pid":
        record["original_terminal"]["terminal_unit"]["main_pid"] = 100
    elif fault == "extra":
        body["authority"] = "ADMIN"
    else:
        record["observed_at_utc"] = "2026-10-24T00:00:01Z"
    original.reader.read.return_value = canonical_json_bytes(body)
    with pytest.raises(ValueError), application.read_retired_embedding_failure(original.proof):
        pytest.fail("invalid original entered mutation window")


def test_actual_root_identity_and_hash_error_are_not_empty_result(original, monkeypatch):
    monkeypatch.setattr(application.os, "getresuid", lambda: (1000, 1000, 1000))
    with (
        pytest.raises(ValueError, match="ROOT_OWNER_REQUIRED"),
        application.read_retired_embedding_failure(original.proof),
    ):
        pytest.fail("nonroot entered window")
    original.reader.read.assert_not_called()
    monkeypatch.setattr(application.os, "getresuid", lambda: (0, 0, 0))
    original.reader.read.side_effect = ValueError("synthetic pinned file hash mismatch")
    with (
        pytest.raises(ValueError, match="hash mismatch"),
        application.read_retired_embedding_failure(original.proof),
    ):
        pytest.fail("bad hash entered window")


def test_a_late_file_or_exact_unit_change_is_not_success(original):
    original.reader.assert_unchanged.side_effect = ValueError("synthetic record changed")
    with (
        pytest.raises(ValueError, match="record changed"),
        application.read_retired_embedding_failure(original.proof),
    ):
        pass
    original.reader.assert_unchanged.side_effect = None
    original.observe.side_effect = (
        original.retired.retired_unit,
        replace(original.retired.retired_unit, stored_descriptors=1),
    )
    with (
        pytest.raises(ValueError, match="RETIREMENT_CHANGED"),
        application.read_retired_embedding_failure(original.proof),
    ):
        pass
