"""Content-free snapshot diagnostics through the real dispatch and fake owner ports."""

from __future__ import annotations

import json
import logging
from typing import Any, cast
from unittest.mock import Mock

import eom_catalog_service.inference_transfer_snapshot_dispatch as dispatch_module
import pytest
from eom_catalog_contracts.inference_transfer_experiment import SuppliedGraphBaseline
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareRequest,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotBindingReply,
    parse_binding_reply,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_service import (
    InferenceTransferSnapshotApplicationService,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.logging import JsonFormatter
from jsonschema import ValidationError as SchemaError
from pydantic import BaseModel
from pydantic import ValidationError as ModelError
from pydantic_core import InitErrorDetails, PydanticCustomError

from tests.unit.inference_transfer_fixtures import profile, sha
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
    model_category: str = "OTHER",
    field_categories: tuple[str, ...] = ("OTHER",),
    validation_categories: tuple[str, ...] = ("TYPE",),
) -> None:
    records = [record for record in caplog.records if record.name == LOGGER_NAME]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is None
    assert record.stack_info is None
    assert record.args == ()
    expected: dict[str, object] = {
        "event": "SNAPSHOT_VALIDATION_FAILED",
        "phase": phase,
        "validation_stage": stage,
        "error_kind": kind,
    }
    if kind == "FROZEN_MODEL":
        expected.update(
            model_category=model_category,
            field_categories=list(field_categories),
            validation_categories=list(validation_categories),
        )
    assert json.loads(record.getMessage()) == expected
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
        validation_categories=("VALUE_INVARIANT",),
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


def _categorized_model_error(
    title: str,
    errors: tuple[tuple[str, tuple[str | int, ...]], ...],
) -> ModelError:
    details: list[InitErrorDetails] = [
        {
            "type": PydanticCustomError(
                code, SECRET + " {private_context}", {"private_context": SECRET}
            ),
            "loc": location,
            "input": {"private-input": SECRET, "password": SECRET},
        }
        for code, location in errors
    ]
    return ModelError.from_exception_data(title, details)


def _dispatch_model_failure(
    caplog: pytest.LogCaptureFixture, error: ModelError
) -> InferenceTransferSnapshotBindingReply:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    request, _ = binding_pair("READ")
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.read.side_effect = error
    return _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )


@pytest.mark.parametrize(
    "title,category",
    [
        ("InferenceTransferSnapshotReadResult", "READ_RESULT"),
        ("InferenceTransferSnapshotRecord", "SOURCE_RECORD"),
        ("CreateEvidenceBundleCommand", "BASELINE_COMMAND"),
        ("SuppliedGraphBaseline", "BASELINE_RESULT"),
        ("EducationRetrievalRequestV2", "GRAPH_REQUEST"),
        ("InferenceTransferSnapshotPrepareResult", "PREPARE_RESULT"),
        ("InferenceTransferSnapshotHeader", "PREPARE_HEADER"),
        ("InferenceTransferSnapshotReadRequest", "READ_REQUEST"),
        (SECRET, "OTHER"),
        ("InferenceTransferSnapshotReadResult " + SECRET, "OTHER"),
        ("_InvalidOwnerValue", "OTHER"),
    ],
)
def test_pydantic_title_is_mapped_only_by_exact_allowlisted_identity(
    caplog: pytest.LogCaptureFixture, title: str, category: str
) -> None:
    reply = _dispatch_model_failure(caplog, _categorized_model_error(title, (("value_error", ()),)))
    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    _diagnostic(
        caplog,
        phase="READ",
        stage="OWNER_SERVICE",
        kind="FROZEN_MODEL",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        model_category=category,
        field_categories=("ROOT",),
        validation_categories=("VALUE_INVARIANT",),
    )
    if category != title:
        assert title not in caplog.text


@pytest.mark.parametrize(
    "field,category",
    [
        ("header", "HEADER"),
        ("index", "INDEX"),
        ("index_entry", "INDEX_ENTRY"),
        ("source", "SOURCE"),
        ("staged_entry", "STAGED_ENTRY"),
        ("records", "RECORDS"),
        ("baselines", "BASELINES"),
        ("limitations", "LIMITATIONS"),
        ("query", "QUERY"),
        ("ordered_candidates", "CANDIDATES"),
        ("topic_keys", "TOPIC_KEYS"),
        ("evidence_budget", "EVIDENCE_BUDGET"),
        ("requester_permission_keys", "PERMISSIONS"),
        ("requester_role", "ROLE"),
        ("requested_by", "ACTOR"),
        ("source_classes", "SOURCE_CLASSES"),
        ("header_sha256", "HEADER_HASH"),
        ("read_sha256", "READ_HASH"),
        ("result_sha256", "RESULT_HASH"),
        ("submission_sha256", "COMMAND_HASH"),
        (SECRET, "OTHER"),
        ("records." + SECRET, "OTHER"),
        (12345, "OTHER"),
    ],
)
def test_only_static_top_field_is_classified_never_nested_location_or_identifier(
    caplog: pytest.LogCaptureFixture, field: str | int, category: str
) -> None:
    error = _categorized_model_error(
        "InferenceTransferSnapshotReadResult", (("missing", (field, SECRET, 17)),)
    )
    _dispatch_model_failure(caplog, error)
    _diagnostic(
        caplog,
        phase="READ",
        stage="OWNER_SERVICE",
        kind="FROZEN_MODEL",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        model_category="READ_RESULT",
        field_categories=(category,),
        validation_categories=("MISSING",),
    )
    assert "12345" not in caplog.text


@pytest.mark.parametrize(
    "validation_type,category",
    [
        ("value_error", "VALUE_INVARIANT"),
        ("too_long", "SIZE_OR_COUNT"),
        ("too_short", "SIZE_OR_COUNT"),
        ("string_too_long", "TEXT_SIZE"),
        ("string_too_short", "TEXT_SIZE"),
        ("extra_forbidden", "CLOSED_FIELDS"),
        ("literal_error", "VERSION_OR_ENUM"),
        ("enum", "VERSION_OR_ENUM"),
        ("string_pattern_mismatch", "FORMAT"),
        ("int_parsing", "TYPE"),
        ("int_type", "TYPE"),
        ("string_type", "TYPE"),
        ("tuple_type", "TYPE"),
        ("model_type", "TYPE"),
        ("missing", "MISSING"),
        (SECRET, "OTHER"),
    ],
)
def test_validation_categories_are_closed_and_custom_message_and_context_never_logged(
    caplog: pytest.LogCaptureFixture, validation_type: str, category: str
) -> None:
    _dispatch_model_failure(
        caplog,
        _categorized_model_error(
            "SuppliedGraphBaseline", ((validation_type, ("ordered_candidates",)),)
        ),
    )
    _diagnostic(
        caplog,
        phase="READ",
        stage="OWNER_SERVICE",
        kind="FROZEN_MODEL",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        model_category="BASELINE_RESULT",
        field_categories=("CANDIDATES",),
        validation_categories=(category,),
    )
    assert "private_context" not in caplog.text


def test_categories_are_sorted_unique_and_bounded_independently_of_error_payload_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fields = (
        "source_classes",
        "header",
        "records",
        "query",
        "index",
        "baselines",
        "limitations",
        "staged_entry",
        "evidence_budget",
        "topic_keys",
        "requested_by",
        "requester_role",
        "requester_permission_keys",
        "ordered_candidates",
        "read_sha256",
        "result_sha256",
    )
    errors: tuple[tuple[str, tuple[str | int, ...]], ...] = tuple(
        ("missing" if index % 2 else "int_parsing", (field, SECRET))
        for index, field in enumerate(fields)
    )
    errors += (("value_error", (SECRET,)),) * 50
    _dispatch_model_failure(
        caplog, _categorized_model_error("InferenceTransferSnapshotReadResult", errors)
    )
    record = next(record for record in caplog.records if record.name == LOGGER_NAME)
    diagnostic = json.loads(record.getMessage())
    actual_fields = diagnostic["field_categories"]
    actual_types = diagnostic["validation_categories"]
    assert actual_fields == sorted(set(actual_fields)) and len(actual_fields) <= 16
    assert actual_types == sorted(set(actual_types)) and len(actual_types) <= 16
    assert set(actual_fields).issubset(
        {
            "SOURCE_CLASSES",
            "HEADER",
            "RECORDS",
            "QUERY",
            "INDEX",
            "BASELINES",
            "LIMITATIONS",
            "STAGED_ENTRY",
            "EVIDENCE_BUDGET",
            "TOPIC_KEYS",
            "ACTOR",
            "ROLE",
            "PERMISSIONS",
            "CANDIDATES",
            "READ_HASH",
            "RESULT_HASH",
            "OTHER",
        }
    )
    assert {"MISSING", "TYPE"}.issubset(actual_types)
    assert SECRET not in JsonFormatter().format(record) and SECRET not in caplog.text


def test_no_pydantic_message_input_context_or_unknown_title_location_survives_rendered_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = _categorized_model_error(SECRET, ((SECRET, (SECRET,)),))
    assert SECRET in str(error)
    assert SECRET in repr(error)
    _dispatch_model_failure(caplog, error)
    _diagnostic(
        caplog,
        phase="READ",
        stage="OWNER_SERVICE",
        kind="FROZEN_MODEL",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        field_categories=("OTHER",),
        validation_categories=("OTHER",),
    )
    record = next(record for record in caplog.records if record.name == LOGGER_NAME)
    rendered: dict[str, Any] = json.loads(JsonFormatter().format(record))
    assert not {"exc_info", "traceback", "input", "context", "error_detail"}.intersection(rendered)


def test_category_extraction_failure_cannot_break_sanitized_dispatch_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _ = binding_pair("READ")
    owner = Mock(spec=InferenceTransferSnapshotApplicationService)
    owner.read.side_effect = _model_error()
    broken_categories = Mock(side_effect=ValueError(SECRET))
    monkeypatch.setattr(dispatch_module, "_model_failure_categories", broken_categories)
    reply = _reply(
        dispatch_module.dispatch_snapshot_frame(owner, canonical_json_bytes(request) + b"\n")
    )
    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    broken_categories.assert_called_once()


def test_actual_oversize_graph_baseline_reports_bounded_specific_categories(
    caplog: pytest.LogCaptureFixture,
) -> None:
    query = InferenceTransferProfilePointer.from_profile(profile("a"))
    candidates = tuple(
        query.model_copy(
            update={
                "profile_id": f"inferenceprofile_{index:032x}",
                "profile_revision_id": f"inferenceprofilerev_{index:032x}",
            }
        )
        for index in range(256)
    )
    with pytest.raises(ModelError) as captured:
        SuppliedGraphBaseline.model_validate(
            {
                "query": query,
                "command_sha256": sha("c"),
                "result_sha256": sha("d"),
                "ordered_candidates": candidates,
            }
        )
    error = captured.value
    assert error.title == "SuppliedGraphBaseline"
    assert (
        error.errors(include_input=False, include_context=False, include_url=False)[0]["type"]
        == "too_long"
    )
    _dispatch_model_failure(caplog, error)
    _diagnostic(
        caplog,
        phase="READ",
        stage="OWNER_SERVICE",
        kind="FROZEN_MODEL",
        code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        model_category="BASELINE_RESULT",
        field_categories=("CANDIDATES",),
        validation_categories=("SIZE_OR_COUNT",),
    )
    assert query.profile_id not in caplog.text
    assert candidates[0].profile_revision_id not in caplog.text
