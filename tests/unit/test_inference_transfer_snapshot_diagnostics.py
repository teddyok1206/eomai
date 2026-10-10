"""Content-free snapshot diagnostics through the real dispatch and fake owner ports."""

from __future__ import annotations

import json
import logging
from typing import cast
from unittest.mock import Mock

import eom_catalog_service.inference_transfer_snapshot_dispatch as dispatch_module
import pytest
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareRequest,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotBindingReply,
    parse_binding_reply,
)
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_service import (
    InferenceTransferSnapshotApplicationService,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.logging import JsonFormatter
from jsonschema import ValidationError as SchemaError
from pydantic import BaseModel
from pydantic import ValidationError as ModelError

from tests.unit.inference_transfer_snapshot_binding_fixtures import binding_pair
from tests.unit.inference_transfer_snapshot_fixtures import (
    snapshot_header,
    snapshot_prepare_result,
)

SECRET = "synthetic-password-token-and-private-item-content"
LOGGER_NAME = "eom_catalog_service.inference_transfer_snapshot_dispatch"


class _InvalidOwnerValue(BaseModel):
    number: int


def _model_error() -> ModelError:
    try:
        _InvalidOwnerValue.model_validate({"number": SECRET})
    except ModelError as error:
        return error
    raise AssertionError("synthetic invalid field unexpectedly passed")


def _schema_error() -> SchemaError:
    return SchemaError(
        SECRET,
        instance={"password": SECRET},
        schema={"private-input": SECRET},
        path=[SECRET],
        context=[SchemaError(SECRET)],
    )


def _reply(raw: bytes) -> InferenceTransferSnapshotBindingReply:
    assert SECRET.encode() not in raw
    return parse_binding_reply(json.loads(raw))


def _diagnostic(
    caplog: pytest.LogCaptureFixture,
    *,
    phase: str,
    stage: str,
    kind: str,
    code: str,
) -> None:
    records = [record for record in caplog.records if record.name == LOGGER_NAME]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is None
    assert record.stack_info is None
    assert record.args == ()
    assert json.loads(record.getMessage()) == {
        "event": "SNAPSHOT_VALIDATION_FAILED",
        "phase": phase,
        "validation_stage": stage,
        "error_kind": kind,
    }
    rendered = JsonFormatter().format(record)
    outer = json.loads(rendered)
    assert outer["component"] == "catalog_snapshot"
    assert outer["event"] == "SNAPSHOT_VALIDATION_FAILED"
    assert outer["error_code"] == code
    request, _ = binding_pair()
    assert isinstance(request.request, InferenceTransferSnapshotPrepareRequest)
    for forbidden in (
        SECRET,
        request.actor_id,
        request.request.graph_snapshot.graph_snapshot_revision_id,
        request.request.graph_snapshot.manifest_sha256,
        "traceback",
        "private-input",
        "password",
    ):
        assert forbidden not in rendered
        assert forbidden not in caplog.text


@pytest.mark.parametrize("phase", ["PREPARE", "READ", "AUTHORIZE"])
@pytest.mark.parametrize(
    "error,kind,code",
    [
        (_schema_error(), "JSON_SCHEMA", "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"),
        (_model_error(), "FROZEN_MODEL", "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"),
        (ValueError(SECRET), "VALUE_VALIDATION", "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"),
        (RuntimeError(SECRET), "UNEXPECTED", "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"),
        (
            InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN"),
            "OWNER_SOURCE",
            "INFERENCE_TRANSFER_FORBIDDEN",
        ),
    ],
)
def test_owner_failure_records_only_closed_phase_and_error_categories(
    caplog: pytest.LogCaptureFixture,
    phase: str,
    error: Exception,
    kind: str,
    code: str,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, _ = binding_pair(phase)
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    getattr(owner, phase.lower()).side_effect = error

    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )

    assert reply.error_code == code and reply.result is None
    _diagnostic(caplog, phase=phase, stage="OWNER_SERVICE", kind=kind, code=code)


def test_forged_owner_error_code_is_not_used_as_a_log_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, _ = binding_pair()
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.prepare.side_effect = InferenceTransferServiceError(SECRET)

    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )

    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    _diagnostic(
        caplog,
        phase="PREPARE",
        stage="OWNER_SERVICE",
        kind="OWNER_SOURCE",
        code="INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE",
    )


@pytest.mark.parametrize("mutation", ["unknown_field", "forged_phase", "missing_newline"])
def test_untrusted_input_diagnostic_does_not_echo_input_or_unvalidated_phase(
    caplog: pytest.LogCaptureFixture, mutation: str
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, _ = binding_pair()
    body = request.model_dump(mode="json")
    if mutation == "unknown_field":
        body["password"] = SECRET
    elif mutation == "forged_phase":
        body["request"]["phase"] = SECRET
    raw = canonical_json_bytes(body) + b"\n"
    if mutation == "missing_newline":
        raw = raw[:-1]
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)

    reply = _reply(dispatch_module.dispatch_snapshot_frame(owner, raw))

    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    owner.prepare.assert_not_called()
    _diagnostic(
        caplog,
        phase="UNKNOWN",
        stage="INPUT_PARSE",
        kind="VALUE_VALIDATION" if mutation == "missing_newline" else "JSON_SCHEMA",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
    )


def test_malformed_owner_output_is_identified_as_reply_schema_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, expected = binding_pair()
    assert expected.result is not None
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.prepare.return_value = expected.result.model_copy(update={"schema_version": SECRET})

    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )

    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    _diagnostic(
        caplog,
        phase="PREPARE",
        stage="REPLY_SCHEMA",
        kind="FROZEN_MODEL",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
    )


def test_reply_json_schema_failure_does_not_log_schema_input_or_context(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, expected = binding_pair()
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.prepare.return_value = expected.result

    def reject_success_reply(value: object) -> InferenceTransferSnapshotBindingReply:
        if isinstance(value, dict) and value.get("status") == "SUCCESS":
            raise _schema_error()
        return parse_binding_reply(value)

    monkeypatch.setattr(dispatch_module, "parse_binding_reply", reject_success_reply)
    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )

    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    _diagnostic(
        caplog,
        phase="PREPARE",
        stage="REPLY_SCHEMA",
        kind="JSON_SCHEMA",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
    )


def test_valid_but_foreign_owner_output_is_identified_as_reply_context_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, _ = binding_pair()
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.prepare.return_value = snapshot_prepare_result(header=snapshot_header(actor_id=SECRET))

    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )

    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    _diagnostic(
        caplog,
        phase="PREPARE",
        stage="REPLY_CONTEXT",
        kind="VALUE_VALIDATION",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
    )


def test_encoding_failure_records_no_serialized_output_or_exception_text(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, expected = binding_pair()
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.prepare.return_value = expected.result

    def failed_success_encoding(value: object) -> bytes:
        if isinstance(value, InferenceTransferSnapshotBindingReply) and value.status == "SUCCESS":
            raise ValueError(SECRET)
        return canonical_json_bytes(value)

    monkeypatch.setattr(dispatch_module, "canonical_json_bytes", failed_success_encoding)
    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )

    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    _diagnostic(
        caplog,
        phase="PREPARE",
        stage="ENCODE",
        kind="VALUE_VALIDATION",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
    )


@pytest.mark.parametrize("phase", ["PREPARE", "READ", "AUTHORIZE"])
def test_success_does_not_emit_failure_diagnostics(
    caplog: pytest.LogCaptureFixture, phase: str
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, expected = binding_pair(phase)
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    getattr(owner, phase.lower()).return_value = expected.result

    actual = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )

    assert actual == expected
    assert not [record for record in caplog.records if record.name == LOGGER_NAME]


def test_oversize_request_preserves_existing_budget_classification_without_input_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    owner = cast(InferenceTransferSnapshotApplicationService, Mock())

    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(
            owner, b" " * (MAX_PRIVATE_SNAPSHOT_FRAME_BYTES + 1)
        )
    )

    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED"
    assert not [record for record in caplog.records if record.name == LOGGER_NAME]


@pytest.mark.parametrize("entry", ["invalid_input", "owner_failure"])
@pytest.mark.parametrize("handler_error", [ValueError(SECRET), RuntimeError(SECRET)])
def test_logging_failure_cannot_replace_the_sanitized_wire_reply(
    monkeypatch: pytest.MonkeyPatch, entry: str, handler_error: Exception
) -> None:
    request, _ = binding_pair()
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.prepare.side_effect = InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
    failed_logger = Mock(side_effect=handler_error)
    monkeypatch.setattr(dispatch_module, "log_event", failed_logger)
    raw = canonical_json_bytes(request)
    if entry == "owner_failure":
        raw += b"\n"

    reply = _reply(dispatch_module.dispatch_snapshot_frame(owner, raw))

    expected = (
        "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
        if entry == "invalid_input"
        else "INFERENCE_TRANSFER_FORBIDDEN"
    )
    assert reply.error_code == expected
    assert reply.result is None
    failed_logger.assert_called_once()
