from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.services.command_adapter import CommandAdapter, _workflow_request_from_api
from eom_api.services.current_item_authoring_admission import (
    require_current_item_authoring_grounding,
    require_current_item_authoring_pack,
)
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_workflow import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import workflow_request_storage_document

from tests.api.test_knowledge_backed_workflow_start import _request
from tests.api.test_workflow_start_resolution_contract import _request as _production_request
from tests.unit.test_past_exam_variation_mode import _variation_start


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id="operator_" + "4" * 32,
        session_id="apisession_" + "5" * 32,
        request_id="request_" + "6" * 32,
        authentication_time=datetime(2026, 11, 11, tzinfo=UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )


def _blocked_request(mode: str) -> WorkflowStartRequest:
    if mode == "variation":
        return WorkflowStartRequest.model_validate(_variation_start())
    if mode == "production":
        value = _production_request()
    else:
        value = _request("1.13.0").model_dump(mode="json")
    if mode == "standard":
        value.update(execution_preset_key="standard-item", educational_retrieval=None)
    else:
        retrieval = dict(cast(dict[str, object], value["educational_retrieval"]))
        retrieval["source_classes"] = ["PAST_EXAM"]
        value["educational_retrieval"] = retrieval
    return WorkflowStartRequest.model_validate(value)


@pytest.mark.parametrize("mode", ("standard", "knowledge", "variation", "production"))
@pytest.mark.parametrize("reference_entry", (False, True))
def test_new_item_admission_rejects_before_retrieval_or_workflow_side_effects(
    monkeypatch: pytest.MonkeyPatch, mode: str, reference_entry: bool
) -> None:
    adapter = object.__new__(CommandAdapter)
    replay = Mock(return_value=None)
    adapter._workflow_start_replay = replay  # type: ignore[method-assign]
    sessions = Mock(side_effect=AssertionError("new request must fail before database access"))
    adapter.sessions = cast(Any, sessions)
    catalog = Mock()
    adapter.catalog_application = catalog
    preparation = Mock()
    transaction = Mock(side_effect=AssertionError("new request must not start a transaction"))
    create = Mock(side_effect=AssertionError("new request must not create a workflow"))
    monkeypatch.setattr("eom_api.services.command_adapter.transaction", transaction)
    monkeypatch.setattr("eom_api.services.command_adapter.create_workflow_instance", create)

    with pytest.raises(ApiError) as captured:
        if reference_entry:
            adapter.start_reference_workflow(
                _blocked_request(mode),
                _actor(),
                idempotency_key="new-authoring-admission-0001",
                preparation=preparation,
            )
        else:
            adapter.start_workflow(
                _blocked_request(mode), _actor(), idempotency_key="new-authoring-admission-0001"
            )

    assert captured.value.status == 422
    assert captured.value.error_code == (
        "WORKFLOW_GRAPH_GROUNDING_REQUIRED" if mode == "standard" else "WORKFLOW_TEXTBOOK_REQUIRED"
    )
    replay.assert_called_once()
    sessions.assert_not_called()
    assert catalog.mock_calls == []
    assert preparation.mock_calls == []
    transaction.assert_not_called()
    create.assert_not_called()


@pytest.mark.parametrize("mode", ("standard", "knowledge", "variation", "production"))
def test_exact_historical_replay_precedes_current_authoring_policy(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    request = _blocked_request(mode)
    workflow_request = _workflow_request_from_api(request)
    actor = _actor()
    command = SimpleNamespace(command_id="wfcmd_" + "1" * 32)
    workflow = SimpleNamespace(
        workflow_id="workflow_" + "2" * 32,
        lock_version=7,
        created_actor_type="human",
        created_actor_id=actor.actor_id,
        definition_key=request.definition_key,
        definition_version=request.definition_version,
        initial_request=workflow_request_storage_document(workflow_request),
        runtime_context={
            "accepted_resolution": (
                request.expected_resolution.model_dump(mode="json")
                if request.expected_resolution is not None
                else None
            )
        },
    )

    class ReplaySession:
        def __enter__(self) -> ReplaySession:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def scalar(self, statement: Any) -> object:
            if statement.column_descriptions[0].get("entity") is WorkflowInstanceRecord:
                return workflow
            return command

    adapter = object.__new__(CommandAdapter)
    adapter.sessions = cast(Any, ReplaySession)
    admission = Mock(side_effect=AssertionError("historical replay must not apply current policy"))
    monkeypatch.setattr(
        "eom_api.services.command_adapter.require_current_item_authoring_grounding", admission
    )

    assert adapter.start_workflow(request, actor, idempotency_key="old-authoring-replay-0001") == (
        command.command_id,
        workflow.workflow_id,
        workflow.lock_version,
    )
    admission.assert_not_called()


def test_textbook_scope_admits_without_mutating_pinned_request() -> None:
    request = _workflow_request_from_api(_request())
    before = request.model_dump(mode="json")

    require_current_item_authoring_grounding(request)

    assert request.model_dump(mode="json") == before


def test_current_authoring_policy_does_not_reinterpret_other_workflow_families() -> None:
    request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")

    require_current_item_authoring_grounding(request)
    require_current_item_authoring_pack(request, None)


@pytest.mark.parametrize("fault", ("missing", "key", "old_version", "unrecognized_hash"))
def test_current_pack_admission_requires_exact_resolved_successor(fault: str) -> None:
    request = _workflow_request_from_api(_request())
    pack = {
        "pack_key": "generated-knowledge-item",
        "version": "1.20.19",
        "release_sha256": SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.19"],
    }
    if fault == "key":
        pack["pack_key"] = "other-item"
    elif fault == "old_version":
        pack["version"] = "1.20.18"
    elif fault == "unrecognized_hash":
        pack["release_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ApiError) as captured:
        require_current_item_authoring_pack(
            request, None if fault == "missing" else {"content_pack": pack}
        )
    assert captured.value.status == 409
    assert captured.value.error_code == "WORKFLOW_TEXTBOOK_POLICY_NOT_READY"


def test_current_pack_admission_accepts_exact_successor_without_rewriting_it() -> None:
    request = _workflow_request_from_api(_request())
    pack = {
        "pack_key": "generated-knowledge-item",
        "version": "1.20.19",
        "release_sha256": SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.19"],
    }
    original = dict(pack)
    require_current_item_authoring_pack(request, {"content_pack": pack})
    assert pack == original
