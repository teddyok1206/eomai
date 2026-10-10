from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.services.command_adapter import CommandAdapter, _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_contracts import EvidenceBudget
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_workflow import compile_definition
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import workflow_request_storage_document

from tests.api.test_knowledge_backed_workflow_start import _request


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id="operator_" + "4" * 32,
        session_id="apisession_" + "5" * 32,
        request_id="request_" + "6" * 32,
        authentication_time=datetime(2026, 10, 10, tzinfo=UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )


def _definition(version: str = "1.13.0") -> SimpleNamespace:
    compiled = compile_definition(
        Path(f"config/workflows/generic-item-development.v{version.removesuffix('.0')}.yaml"),
        {"authoring", "image", "review", "item_management"},
    )
    return SimpleNamespace(
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        canonical_definition=compiled.as_dict(),
        source_path=compiled.source_path,
        definition_hash=compiled.sha256,
    )


class _ReadSession:
    def __init__(self, definition: object) -> None:
        self.definition = definition

    def __enter__(self) -> _ReadSession:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def scalar(self, statement: Any) -> object | None:
        if statement.column_descriptions[0].get("entity") is WorkflowInstanceRecord:
            return None
        return self.definition


@pytest.mark.parametrize("mode", ("standard", "knowledge", "variation"))
def test_fresh_item_admission_bounds_completed_reuse_to_exact_selected_preset(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    grounded = mode != "standard"
    definition = _definition("1.14.0" if mode == "variation" else "1.13.0")
    request = _request("1.13.0")
    if not grounded:
        request = WorkflowStartRequest.model_validate(
            request.model_dump(mode="json")
            | {"execution_preset_key": "standard-item", "educational_retrieval": None}
        )
    elif mode == "variation":
        assert request.educational_retrieval is not None
        request = WorkflowStartRequest.model_validate(
            request.model_dump(mode="json")
            | {
                "definition_version": "1.14.0",
                "educational_retrieval": request.educational_retrieval.model_dump(mode="json")
                | {
                    "schema_version": "educational-retrieval-requirement/2.0",
                    "past_exam_variation": {
                        "schema_version": "past-exam-variation-request/1.0",
                        "source_item_revision_id": "itemrev_" + "8" * 32,
                        "variation_axes": ["CONTEXT"],
                        "preserve_core_concept": True,
                        "preserve_cognitive_target": True,
                        "copy_policy": "NO_STEM_CHOICE_ANSWER_COPY",
                    },
                },
            }
        )
    command = SimpleNamespace(command_id="wfcmd_" + "1" * 32)
    workflow = SimpleNamespace(workflow_id="workflow_" + "2" * 32, lock_version=7)
    preset = SimpleNamespace(preset_revision_id="execpresetrev_" + "3" * 32)
    if grounded:
        preset.retrieval_policy = SimpleNamespace(
            maximum_budget=EvidenceBudget(
                max_documents=2,
                max_item_revisions=2,
                max_graph_nodes=8,
                max_claims=2,
                max_context_tokens=2000,
            ),
            access_policy_revision_id="accessrev_" + "3" * 32,
            access_policy_sha256="sha256:" + "3" * 64,
        )
    events: list[str] = []
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = cast(Any, lambda: _ReadSession(definition))
    adapter._workflow_start_replay = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    adapter._resolve_past_exam_source_material_requirement = (  # type: ignore[method-assign]
        lambda _request: None
    )
    adapter.catalog = cast(Any, SimpleNamespace(bind_request=lambda *_args, **_kwargs: {}))
    adapter.catalog_application = cast(
        Any, SimpleNamespace(create_item_production_evidence=lambda _command: object())
    )

    def select_preset(*_args: object, **_kwargs: object) -> object:
        events.append("select-current")
        return preset

    def create(*_args: object, **kwargs: object) -> tuple[object, bool]:
        events.append("completed-lookup")
        assert kwargs["completed_preset_revision_id"] == preset.preset_revision_id
        return workflow, False

    @contextmanager
    def fake_transaction(_sessions: object):
        yield SimpleNamespace(scalar=lambda _statement: command)

    monkeypatch.setattr(
        "eom_api.services.command_adapter.admitted_workflow_definition",
        lambda *_args, **_kwargs: definition,
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.current_knowledge_backed_preset", select_preset
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.lock_current_execution_preset", select_preset
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.validate_educational_retrieval_policy",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("eom_api.services.command_adapter.create_workflow_instance", create)
    monkeypatch.setattr("eom_api.services.command_adapter.transaction", fake_transaction)

    assert adapter.start_workflow(request, _actor(), idempotency_key="api:" + "7" * 64) == (
        command.command_id,
        workflow.workflow_id,
        workflow.lock_version,
    )
    assert events == ["select-current", "completed-lookup"]


def test_transport_replay_never_consults_changed_current_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request("1.13.0")
    workflow_request = _workflow_request_from_api(request)
    actor = _actor()
    command = SimpleNamespace(command_id="wfcmd_" + "1" * 32)
    old_workflow = SimpleNamespace(
        created_actor_type="human",
        created_actor_id=actor.actor_id,
        definition_key=request.definition_key,
        definition_version=request.definition_version,
        initial_request=workflow_request_storage_document(workflow_request),
        workflow_id="workflow_" + "2" * 32,
        lock_version=7,
    )

    class ReplaySession(_ReadSession):
        def scalar(self, statement: Any) -> object:
            if statement.column_descriptions[0].get("entity") is WorkflowInstanceRecord:
                return old_workflow
            return command

    def forbidden_current(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("transport replay must not consult current release")

    adapter = object.__new__(CommandAdapter)
    adapter.sessions = cast(Any, lambda: ReplaySession(object()))
    monkeypatch.setattr(
        "eom_api.services.command_adapter.lock_current_execution_preset", forbidden_current
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.current_knowledge_backed_preset", forbidden_current
    )

    assert adapter.start_workflow(request, actor, idempotency_key="api:" + "7" * 64) == (
        command.command_id,
        old_workflow.workflow_id,
        old_workflow.lock_version,
    )
