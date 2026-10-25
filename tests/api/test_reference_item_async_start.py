"""Source-only HTTP/local start checks; native, Identity DB and Catalog authority are synthetic."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.errors import ApiError
from eom_api.services.idempotency_service import IdempotencyClaim, IdempotencyService
from eom_api.services.reference_item_preparation import HttpReferenceItemStartPreparation
from eom_api.services.reference_item_start import ReferenceItemStartApplicationService
from eom_api.services.reference_item_start_ports import ReferenceItemStartPending
from eom_api.settings import ApiSettings
from eom_api_contracts import CommandResult
from eom_api_contracts.workflow_reference_start import (
    WorkflowReferencePreparationPending,
    WorkflowReferenceStartReply,
)
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareReply
from eom_identifiers import content_sha256
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select

from tests.api.helpers import disconnected_services
from tests.api.test_item_similarity_start import start_case as start_case
from tests.unit.item_similarity_start_fixtures import start_source
from tests.unit.test_reference_query_prepare_transport import api_context

ROOT = Path(__file__).resolve().parents[2]
PATH = "/api/v1/workflows/reference-starts"
WORKFLOW = "workflow_" + "b" * 32


def command():
    return CommandResult(
        command_id="wfcmd_" + "c" * 32,
        resource_type="workflow",
        resource_id=WORKFLOW,
        status="ACCEPTED",
        resource_version=1,
        status_url=f"/api/v1/workflows/{WORKFLOW}",
    )


def accepted():
    return WorkflowReferenceStartReply(
        status="ACCEPTED", reference_query_workflow_id=None, command=command()
    )


def pending():
    return WorkflowReferenceStartReply(
        status="PENDING", reference_query_workflow_id=WORKFLOW, command=None
    )


def preparation_pending(workflow_id=None):
    return WorkflowReferencePreparationPending(
        reference_query_workflow_id=workflow_id,
        reference_query_preparation=dict(
            artifact_id="artifact_" + "a" * 32,
            artifact_revision_id="rev_" + "b" * 32,
            member_path="preparation.json",
            sha256="sha256:" + "c" * 64,
            schema_ref="eom://schemas/workflow/reference-query-routed-preparation/1.0",
            media_type="application/json",
        ),
        reference_query_parent_sha256="sha256:" + "d" * 64,
    )


def test_preworkflow_successor_is_schema_first_and_does_not_weaken_old_pending():
    canonical = ROOT / "schemas/api/v1/workflow-reference-start-reply-v2.schema.json"
    packaged = ROOT / "packages/api_contracts/eom_api_contracts/schemas" / canonical.name
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for workflow_id in (None, WORKFLOW):
        value = preparation_pending(workflow_id)
        validator.validate(value.model_dump(mode="json"))
        for fault in (
            {"command": command().model_dump(mode="json")},
            {"reference_query_preparation": None},
            {"reference_query_parent_sha256": None},
            {"actor_id": "ADMIN"},
        ):
            invalid = value.model_dump(mode="json") | fault
            assert not validator.is_valid(invalid)
            with pytest.raises(ValidationError):
                WorkflowReferencePreparationPending.model_validate(invalid)


def test_reply_schema_first_and_packaged_mirror():
    canonical = ROOT / "schemas/api/v1/workflow-reference-start-reply-v1.schema.json"
    packaged = ROOT / "packages/api_contracts/eom_api_contracts/schemas" / canonical.name
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for value in (pending(), accepted()):
        validator.validate(value.model_dump(mode="json"))
    for value in (
        pending().model_dump(mode="json") | {"command": command().model_dump(mode="json")},
        accepted().model_dump(mode="json") | {"command": None},
        pending().model_dump(mode="json") | {"reference_query_workflow_id": None},
        pending().model_dump(mode="json") | {"actor_id": "ADMIN"},
    ):
        assert not validator.is_valid(value)
        with pytest.raises(ValidationError):
            WorkflowReferenceStartReply.model_validate(value)


def test_no_item_workflow_plan_or_command_is_created_while_native_pending(start_case):
    case = start_case
    preparation = Mock()
    preparation.prepare.return_value = ReferenceItemStartPending(WORKFLOW)
    for _ in range(2):
        result = case.adapter.start_reference_workflow(
            case.request,
            case.actor,
            idempotency_key="synthetic-reference-start",
            preparation=preparation,
        )
        assert result == ReferenceItemStartPending(WORKFLOW)
        with case.sessions() as session:
            assert session.scalar(select(func.count()).select_from(WorkflowInstanceRecord)) == 0
            assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == 0
        assert not case.records
    preparation.prepare.return_value = case.prepared
    first = case.adapter.start_reference_workflow(
        case.request,
        case.actor,
        idempotency_key="synthetic-reference-start",
        preparation=preparation,
    )
    assert isinstance(first, tuple) and len(case.records) == 1
    assert case.records[0][0] == "resolved-execution-plan/23.0"
    preparation.prepare.side_effect = AssertionError("receipt replay must not prepare again")
    case.client.create_item_production_evidence.side_effect = AssertionError(
        "no Evidence replay IO"
    )
    case.adapter.catalog.bind_request.side_effect = AssertionError("no mutable Pack lookup")
    assert (
        case.adapter.start_reference_workflow(
            case.request,
            case.actor,
            idempotency_key="synthetic-reference-start",
            preparation=preparation,
        )
        == first
    )


def test_malformed_control_selection_never_dispatches_native_preparation(start_case):
    case = start_case
    case.adapter.catalog.bind_request.side_effect = lambda *args, **kwargs: {"content_pack": {}}
    preparation = Mock()
    with pytest.raises(ApiError, match="CONTROL_SIMILARITY_PREPARATION_INVALID"):
        case.adapter.start_reference_workflow(
            case.request,
            case.actor,
            idempotency_key="synthetic-malformed-selection",
            preparation=preparation,
        )
    preparation.prepare.assert_not_called()
    assert not case.records


@pytest.fixture
def application_case(tmp_path, monkeypatch, request):
    _source, context = api_context(monkeypatch)
    data = start_source(tmp_path, monkeypatch, ordinary=getattr(request, "param", False))
    commands, queries, items, audit = Mock(), Mock(), Mock(), Mock()
    idempotency = IdempotencyService(create_engine("sqlite://"), b"synthetic-source-only" * 2)
    idempotency.claim = Mock(return_value=IdempotencyClaim("idem", lease_owner="current"))
    idempotency.defer = Mock()
    idempotency.complete = Mock()
    idempotency.fail_final = Mock()
    service = ReferenceItemStartApplicationService(
        enabled=True,
        commands=commands,
        queries=queries,
        items=items,
        idempotency=idempotency,
        audit=audit,
    )
    return SimpleNamespace(
        context=context,
        data=data,
        commands=commands,
        queries=queries,
        items=items,
        audit=audit,
        idempotency=idempotency,
        service=service,
    )


def test_pending_yields_claim_but_never_completes_or_fails_it(application_case):
    case = application_case
    case.commands.start_reference_workflow.return_value = ReferenceItemStartPending(WORKFLOW)
    result = case.service.start(
        case.context, case.data.request, idempotency_key="same-original-key"
    )
    assert result == pending()
    case.idempotency.defer.assert_called_once()
    case.idempotency.complete.assert_not_called()
    case.idempotency.fail_final.assert_not_called()
    assert case.audit.append.call_args.kwargs["event_type"] == "REFERENCE_ITEM_PREPARATION_PENDING"


@pytest.mark.parametrize("workflow_id", (None, WORKFLOW))
def test_original_preparation_pointer_yields_claim_without_fake_workflow_or_accepted_command(
    application_case, workflow_id
):
    case = application_case
    expected = preparation_pending(workflow_id)
    case.commands.start_reference_workflow.return_value = ReferenceItemStartPending(
        workflow_id, expected.reference_query_preparation, expected.reference_query_parent_sha256
    )
    result = case.service.start(
        case.context, case.data.request, idempotency_key="same-original-key"
    )
    assert result == expected and result.command is None
    case.idempotency.defer.assert_called_once()
    case.idempotency.complete.assert_not_called()
    case.idempotency.fail_final.assert_not_called()
    assert case.audit.append.call_args.kwargs["target_id"] == (
        workflow_id or expected.reference_query_preparation.artifact_revision_id
    )


def test_ready_completes_only_the_accepted_command_receipt(application_case):
    case = application_case
    value = command()
    case.commands.start_reference_workflow.return_value = (
        value.command_id,
        value.resource_id,
        value.resource_version,
    )
    result = case.service.start(
        case.context, case.data.request, idempotency_key="same-original-key"
    )
    assert result == accepted()
    case.idempotency.complete.assert_called_once()
    assert case.idempotency.complete.call_args.kwargs["body"] == value.model_dump(mode="json")
    case.idempotency.defer.assert_not_called()
    case.idempotency.fail_final.assert_not_called()


def test_key_conflict_is_audited_before_any_query_or_item_work(application_case):
    case = application_case
    case.idempotency.claim.side_effect = ApiError(
        409, "API_IDEMPOTENCY_CONFLICT", "Conflict", "The original request differs."
    )
    with pytest.raises(ApiError, match="API_IDEMPOTENCY_CONFLICT"):
        case.service.start(case.context, case.data.request, idempotency_key="same-original-key")
    assert (
        not case.commands.mock_calls and not case.queries.mock_calls and not case.items.mock_calls
    )
    assert case.audit.append.call_args.kwargs["event_type"] == "IDEMPOTENCY_CONFLICT"


def test_accepted_http_receipt_replay_needs_no_current_controls_or_owner(application_case):
    case = application_case
    case.idempotency.claim.return_value = IdempotencyClaim(
        "idem", replay_body=command().model_dump(mode="json"), replay_status=202
    )
    assert (
        case.service.start(case.context, case.data.request, idempotency_key="same-original-key")
        == accepted()
    )
    assert (
        not case.commands.mock_calls and not case.queries.mock_calls and not case.items.mock_calls
    )
    case.idempotency.defer.assert_not_called()


def test_http_purpose_captures_once_and_preserves_pending_meaning(application_case):
    case = application_case
    services = disconnected_services()
    services.auth = Mock()
    services.auth.authenticate_and_capture_access.return_value = case.context.authenticated_access
    services.auth.authenticate_access.side_effect = AssertionError("one genuine current capture")
    services.audit = case.audit
    services.reference_item_starts = Mock()
    services.reference_item_starts.start.side_effect = [pending(), accepted()]
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            for expected in (pending(), accepted()):
                result = client.post(
                    PATH,
                    json=case.data.request.model_dump(mode="json"),
                    headers={
                        "Authorization": "Bearer synthetic-only",
                        "Idempotency-Key": "original-reference-key",
                    },
                )
                assert result.status_code == 202
                assert result.json()["data"] == expected.model_dump(mode="json")
                assert result.headers["Cache-Control"] == "no-store"
                assert result.headers.get("Retry-After") == (
                    "20" if expected.status == "PENDING" else None
                )
        assert services.auth.authenticate_and_capture_access.call_count == 2
        contexts = [call.args[0] for call in services.reference_item_starts.start.call_args_list]
        assert contexts[0] is not contexts[1]
        assert all(
            value.owner_capture() is case.context.authenticated_access.capture for value in contexts
        )
    finally:
        services.engine.dispose()


def test_native_preparation_key_is_stable_and_bound_to_current_evidence(application_case):
    case = application_case
    source = case.data.source
    actor = case.context.actor()
    sent = []

    def query(_context, value, *, idempotency_key):
        assert _context is case.context and value.idempotency_key == idempotency_key
        assert value.graph_snapshot == source.evidence.graph_snapshot
        assert value.policy_sha256 == source.evidence.access_policy_sha256
        assert value.request_sha256 == content_sha256(
            value.model_dump(mode="json", exclude={"request_sha256"})
        )
        sent.append(value)
        return ReferenceQueryPrepareReply(
            schema_version="system-rag-reference-query-prepare-reply/1.0",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=value.operation_id,
            request_sha256=value.request_sha256,
            status="PENDING",
            workflow_id=WORKFLOW,
            selection=None,
            error_code=None,
        )

    case.queries.prepare.side_effect = query
    preparation = HttpReferenceItemStartPreparation(case.context, case.queries, case.items)
    for _ in range(2):
        assert preparation.prepare(
            actor,
            workflow_request=source.request,
            expected_resolution=source.resolution,
            evidence=source.evidence,
            preset=source.preset,
            idempotency_key="api:" + "d" * 64,
        ) == ReferenceItemStartPending(WORKFLOW)
    assert sent[0] == sent[1]
    assert not case.items.mock_calls


def test_default_disabled_composition_and_invalid_partial_enable():
    services = disconnected_services()
    try:
        assert services.reference_item_starts.enabled is False
        with pytest.raises(ValidationError):
            ApiSettings(reference_item_start_enabled=True)
        assert ApiSettings(
            reference_item_start_enabled=True, reference_query_preparation_enabled=True
        ).reference_item_start_enabled
    finally:
        services.engine.dispose()


def test_incompatible_pack_is_rejected_before_any_native_or_publication(application_case):
    case = application_case
    source = case.data.source
    preparation = HttpReferenceItemStartPreparation(case.context, case.queries, case.items)
    with pytest.raises(ApiError, match="CONTROL_SIMILARITY_PREPARATION_INVALID"):
        preparation.prepare(
            case.context.actor(),
            workflow_request=source.request,
            expected_resolution=source.resolution.model_copy(
                update={"content_pack_version": "1.20.16"}
            ),
            evidence=source.evidence,
            preset=source.preset,
            idempotency_key="api:" + "d" * 64,
        )
    assert not case.queries.mock_calls and not case.items.mock_calls


def test_actor_projection_cannot_replace_current_request_actor(application_case):
    case = application_case
    source = case.data.source
    preparation = HttpReferenceItemStartPreparation(case.context, case.queries, case.items)
    with pytest.raises(ApiError, match="PERMISSION_DENIED"):
        preparation.prepare(
            case.data.actor,
            workflow_request=source.request,
            expected_resolution=source.resolution,
            evidence=source.evidence,
            preset=source.preset,
            idempotency_key="api:" + "d" * 64,
        )
    assert not case.queries.mock_calls and not case.items.mock_calls


def test_missing_authentication_and_public_selector_override_never_dispatch(application_case):
    case = application_case
    services = disconnected_services()
    services.auth = Mock()
    services.auth.authenticate_and_capture_access.return_value = case.context.authenticated_access
    services.audit = case.audit
    services.reference_item_starts = Mock()
    body = case.data.request.model_dump(mode="json")
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            assert client.post(PATH, json=body).status_code == 401
            response = client.post(
                PATH,
                json=body | {"query_selection": {"workflow_id": WORKFLOW}},
                headers={
                    "Authorization": "Bearer synthetic-only",
                    "Idempotency-Key": "original-reference-key",
                },
            )
            assert response.status_code == 422
        services.reference_item_starts.start.assert_not_called()
    finally:
        services.engine.dispose()
