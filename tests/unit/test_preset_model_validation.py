"""Exact non-live request/checkpoint pins and bounded processor failure semantics."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ExecutionPresetValidationRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.preset_model_evidence import (
    validated_acceptance_checkpoint,
    validated_job_request,
)
from eom_orchestrator.preset_model_selection import non_live_invocation_cases
from eom_orchestrator.preset_model_validation import PROTOCOL, TASK_TYPE, validated_request
from eom_orchestrator.preset_model_validation_processor import (
    PresetModelValidationProcessor,
    _transient_commit_failure,
)
from eom_orchestrator.preset_policy import execution_preset_policy_sha256
from eom_orchestrator.settings import Settings
from eom_workflow.preset_model_validation import PresetModelValidationRequest
from sqlalchemy.exc import DBAPIError

from tests.unit.test_preset_model_selection import _draft, _preset, _self_hash


def _acceptance() -> tuple[Any, ...]:
    base, draft = _preset(), _draft(_preset())
    requested_at = datetime.now(UTC) - timedelta(seconds=1)
    request = PresetModelValidationRequest(
        preset_revision_id=draft.preset_revision_id,
        preset_content_sha256=draft.content_sha256,
        preset_policy_sha256=execution_preset_policy_sha256(draft),
        base_revision_id=base.preset_revision_id,
        base_content_sha256=base.content_sha256,
        requested_by="operator_" + "1" * 32,
        requested_at=requested_at,
    )
    document = request.model_dump(mode="json")
    command = ExecutionPresetValidationRecord(
        validation_id="job_" + "1" * 32,
        preset_revision_id=request.preset_revision_id,
        base_revision_id=request.base_revision_id,
        requested_by=request.requested_by,
        idempotency_key="validation-fixture",
        request_sha256=content_sha256(document),
        canonical_request=document,
        requested_at=requested_at,
        state="PROCESSING",
    )
    job = JobRecord(
        job_id=command.validation_id,
        protocol_version=PROTOCOL,
        task_type=TASK_TYPE,
        idempotency_key=command.idempotency_key,
        request=document,
        request_hash=content_sha256(
            {"protocol_version": PROTOCOL, "task_type": TASK_TYPE, "request": document}
        ),
        status="COMMITTING",
        logical_artifact_id="artifact_" + "2" * 32,
        revision_id="rev_" + "2" * 32,
    )
    keys = (
        "FIXED_POLICY_PRESERVED",
        "FRESH_ROLE_CAPABILITY",
        "RELEASED_BUNDLE_POINTERS",
        *non_live_invocation_cases(draft),
    )
    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    report = _self_hash(
        {
            "schema_version": "execution-preset-evaluation-report/1.0",
            "evaluated_preset_revision_id": request.preset_revision_id,
            "evaluated_policy_sha256": request.preset_policy_sha256,
            "scope": "NON_LIVE",
            "outcome": "PASS",
            "summary_code": "FAKE_ADAPTER_ACCEPTANCE",
            "cases_total": len(keys),
            "cases_passed": len(keys),
            "quality_score_permille": None,
            "completed_at": completed_at,
            "report_sha256": "sha256:" + "0" * 64,
        },
        "report_sha256",
    )
    cases = _self_hash(
        {
            "schema_version": "preset-model-acceptance-cases/1.0",
            "validation_id": job.job_id,
            "request_sha256": job.request_hash,
            "preset_revision_id": request.preset_revision_id,
            "preset_content_sha256": request.preset_content_sha256,
            "preset_policy_sha256": request.preset_policy_sha256,
            "base_revision_id": request.base_revision_id,
            "base_content_sha256": request.base_content_sha256,
            "evaluator_source_commit": "a" * 40,
            "case_keys": list(keys),
            "completed_at": completed_at,
            "cases_sha256": "sha256:" + "0" * 64,
        },
        "cases_sha256",
    )
    base_row = SimpleNamespace(**base.model_dump(), canonical_document=base.model_dump(mode="json"))
    draft_row = SimpleNamespace(
        **draft.model_dump(), canonical_document=draft.model_dump(mode="json")
    )
    return command, job, request, base_row, draft_row, report, cases


def test_acceptance_has_exact_frozen_request_real_adapter_cases_and_no_quality_claim() -> None:
    command, job, request, base, draft, report, cases = _acceptance()
    assert validated_request(command) == request
    assert validated_job_request(job, command) == request
    accepted_report, accepted_cases = validated_acceptance_checkpoint(
        job=job,
        request=request,
        base=base,
        draft=draft,
        report_document=report,
        cases_document=cases,
        evaluator_source_commit="a" * 40,
    )
    assert accepted_report.scope == "NON_LIVE"
    assert accepted_report.summary_code == "FAKE_ADAPTER_ACCEPTANCE"
    assert accepted_report.quality_score_permille is None
    assert accepted_report.cases_total == len(accepted_cases.case_keys)


def test_job_protocol_identity_fits_existing_database_without_rewriting_schema() -> None:
    assert len(PROTOCOL) <= JobRecord.__table__.c.protocol_version.type.length
    command, _job, *_rest = _acceptance()
    assert command.canonical_request["schema_version"] == "preset-model-validation-request/1.0"
    assert command.canonical_request["schema_version"] != PROTOCOL


@pytest.mark.parametrize(
    "attribute",
    ["job_id", "protocol_version", "task_type", "idempotency_key", "request_hash"],
)
def test_job_replay_rejects_identity_protocol_and_wrapper_hash_drift(attribute: str) -> None:
    command, job, *_rest = _acceptance()
    setattr(job, attribute, "drifted")
    with pytest.raises(ControlPlaneError) as failure:
        validated_job_request(job, command)
    assert failure.value.code == "CONTROL_VALIDATION_REQUEST_INVALID"


def test_canonical_command_hash_and_requested_actor_are_not_interchangeable() -> None:
    command, job, *_rest = _acceptance()
    command.canonical_request = deepcopy(command.canonical_request)
    command.canonical_request["requested_by"] = "operator_" + "7" * 32
    command.request_sha256 = content_sha256(command.canonical_request)
    with pytest.raises(ControlPlaneError, match="request identity"):
        validated_job_request(job, command)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("cases", "validation_id", "job_" + "7" * 32),
        ("cases", "request_sha256", "sha256:" + "7" * 64),
        ("cases", "preset_revision_id", "execpresetrev_" + "7" * 32),
        ("cases", "preset_content_sha256", "sha256:" + "7" * 64),
        ("cases", "base_revision_id", "execpresetrev_" + "7" * 32),
        ("cases", "base_content_sha256", "sha256:" + "7" * 64),
        ("cases", "preset_policy_sha256", "sha256:" + "7" * 64),
        ("cases", "case_keys", ["STATIC_CHECK_ONLY"]),
        ("cases", "cases_sha256", "sha256:" + "7" * 64),
        ("report", "scope", "STATIC"),
        ("report", "outcome", "FAIL"),
        ("report", "summary_code", "CONTRACT_VALIDATION"),
        ("report", "evaluated_preset_revision_id", "execpresetrev_" + "7" * 32),
        ("report", "evaluated_policy_sha256", "sha256:" + "7" * 64),
        ("report", "cases_passed", 1),
        ("report", "cases_total", 1),
        ("report", "quality_score_permille", 950),
        ("report", "report_sha256", "sha256:" + "7" * 64),
    ],
)
def test_recovery_rejects_rehashed_but_wrong_checkpoint_pins(
    target: str,
    field: str,
    value: Any,
) -> None:
    _command, job, request, base, draft, report, cases = _acceptance()
    document = cases if target == "cases" else report
    document[field] = value
    hash_field = "cases_sha256" if target == "cases" else "report_sha256"
    if field != hash_field:
        _self_hash(document, hash_field)
    with pytest.raises(ControlPlaneError) as failure:
        validated_acceptance_checkpoint(
            job=job,
            request=request,
            base=base,
            draft=draft,
            report_document=report,
            cases_document=cases,
            evaluator_source_commit="a" * 40,
        )
    assert failure.value.code == "CONTROL_VALIDATION_CHECKPOINT_INVALID"


def test_recovery_requires_same_installed_evaluator_commit() -> None:
    _command, job, request, base, draft, report, cases = _acceptance()
    with pytest.raises(ControlPlaneError) as failure:
        validated_acceptance_checkpoint(
            job=job,
            request=request,
            base=base,
            draft=draft,
            report_document=report,
            cases_document=cases,
            evaluator_source_commit="b" * 40,
        )
    assert failure.value.code == "CONTROL_VALIDATION_EVALUATOR_CHANGED"


@pytest.mark.parametrize("source", [None, "unknown", "A" * 40])
def test_processor_needs_installed_evaluator_not_ambient_git(source: str | None) -> None:
    processor = object.__new__(PresetModelValidationProcessor)
    processor.settings = Settings(runtime_source_commit=source)
    with pytest.raises(ControlPlaneError) as failure:
        processor._process("job_" + "1" * 32)
    assert failure.value.code == "CONTROL_VALIDATION_EVALUATOR_UNAVAILABLE"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OSError("uncertain committed bytes"), True),
        (ControlPlaneError("CONTROL_VALIDATION_EVALUATOR_CHANGED", "permanent"), False),
        (ValueError("invalid immutable schema"), False),
        (DBAPIError(None, None, SimpleNamespace(sqlstate="23514")), False),
        (DBAPIError(None, None, SimpleNamespace(sqlstate="40001")), True),
        (DBAPIError(None, None, SimpleNamespace(sqlstate="40P01")), True),
        (DBAPIError(None, None, SimpleNamespace(sqlstate="08006")), True),
        (DBAPIError(None, None, SimpleNamespace(sqlstate=None), connection_invalidated=True), True),
    ],
)
def test_commit_recovery_distinguishes_transient_io_from_permanent_contract(
    error: BaseException,
    expected: bool,
) -> None:
    assert _transient_commit_failure(error) is expected


def _processor_fake(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    command, job, *_rest = _acceptance()
    connection = Mock()
    connection.scalar.return_value = True
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    engine = Mock()
    engine.dialect.name = "postgresql"
    engine.connect.return_value = connection
    processor = PresetModelValidationProcessor(engine, Settings(runtime_source_commit="a" * 40))
    session = Mock()
    session.scalar.return_value = command
    session.get.side_effect = lambda model, *_args, **_kw: (
        command if model is ExecutionPresetValidationRecord else job
    )

    @contextmanager
    def fake_transaction(_sessions: Any) -> Any:
        yield session

    def fake_transition(_session: Any, _id: str, target: Any, *_args: Any, **_kw: Any) -> None:
        job.status = str(target)

    monkeypatch.setattr(
        "eom_orchestrator.preset_model_validation_processor.transaction", fake_transaction
    )
    monkeypatch.setattr(
        "eom_orchestrator.preset_model_validation_processor.transition_job", fake_transition
    )
    return processor, command, job, connection


def test_permanent_checkpoint_error_terminalizes_without_retrying_oldest_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor, command, job, connection = _processor_fake(monkeypatch)
    processor._process = Mock(
        side_effect=ControlPlaneError("CONTROL_VALIDATION_CHECKPOINT_INVALID", "altered checkpoint")
    )
    assert processor.process_once() == command.validation_id
    assert command.state == job.status == "FAILED"
    assert command.error_code == "CONTROL_VALIDATION_CHECKPOINT_INVALID"
    assert command.completed_at is not None
    assert processor._retry_after == 0
    assert "pg_advisory_unlock" in str(connection.execute.call_args.args[0])


def test_uncertain_commit_preserves_identity_and_backoff_without_failing_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor, command, job, connection = _processor_fake(monkeypatch)
    before = (command.validation_id, job.logical_artifact_id, job.revision_id, job.request_hash)
    processor._process = Mock(side_effect=OSError("uncertain committed bytes"))
    assert processor.process_once() is None
    assert command.state == "PROCESSING" and job.status == "COMMITTING"
    assert command.completed_at is None and command.error_code is None
    assert (
        command.validation_id,
        job.logical_artifact_id,
        job.revision_id,
        job.request_hash,
    ) == before
    assert processor._retry_after > 0
    assert processor.process_once() is None
    processor._process.assert_called_once_with(command.validation_id)
    assert "pg_advisory_unlock" in str(connection.execute.call_args.args[0])
