from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest
from eom_api.errors import ApiError
from eom_api.services.command_adapter import CommandAdapter
from eom_api_contracts.workflows import WorkflowActionRequest
from eom_catalog_service.models import ContentPackRecord, ContentPackReleaseRecord
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_content_pack import ContentPackError
from eom_workflow import WorkflowRequest
from eom_workflow_runner.repository import (
    CommandType,
    workflow_business_fingerprint,
    workflow_request_storage_document,
)
from pydantic import ValidationError


def _request(*, production_request_digit: str = "1", call_digit: str = "2") -> WorkflowRequest:
    return WorkflowRequest.model_validate(
        {
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "content_pack": {
                "pack_key": "generated-knowledge-item",
                "environment": "development",
            },
            "profiles": {
                "authoring": "generated-knowledge-authoring",
                "review": "generated-knowledge-review",
                "image": "generated-stimulus-drawing",
                "registration": "generated-structured-registration",
            },
            "source_intake": {"batch_ids": []},
            "registry_intent": {"mode": "CREATE_ITEM"},
            "item_brief": {
                "subject": "통합과학",
                "topic": "생태계 평형",
                "task_type": "data_interpretation",
                "difficulty": "hard",
                "quality_profile": "deep",
                "original_request_sha256": "3" * 64,
            },
            "execution_preset_key": "knowledge-grounded-item",
            "educational_retrieval": {
                "corpus_key": "science-core",
                "query_kind": "ITEM_PREPARATION",
                "curriculum_root_key": "ecology.balance",
                "topic_keys": [],
                "required_item_elements": ["choice", "paragraph"],
                "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
            },
            "production_occurrence": {
                "production_request_id": "productionreq_" + production_request_digit * 32,
                "workflow_call_id": "workflowcall_" + call_digit * 32,
            },
            "expected_resolution": {
                "workflow_definition_key": "generic-item-development",
                "workflow_definition_version": "1.8.0",
                "workflow_definition_sha256": "sha256:" + "4" * 64,
                "content_pack_release_id": "packrel_" + "5" * 32,
                "content_pack_key": "generated-knowledge-item",
                "content_pack_version": "1.13.0",
                "content_pack_bundle_sha256": "sha256:" + "6" * 64,
                "content_pack_source_tree_sha256": "sha256:" + "7" * 64,
                "execution_preset_id": "execpreset_" + "8" * 32,
                "execution_preset_revision_id": "execpresetrev_" + "9" * 32,
                "execution_preset_key": "knowledge-grounded-item",
                "execution_preset_content_sha256": "sha256:" + "a" * 64,
            },
        }
    )


def test_production_occurrence_changes_business_fingerprint_but_replays_exactly() -> None:
    definition = cast(
        Any,
        SimpleNamespace(
            definition_key="generic-item-development",
            definition_version="1.8.0",
            definition_hash="sha256:" + "4" * 64,
        ),
    )
    first = _request()
    replay = _request()
    new_run = _request(production_request_digit="b")
    new_call = _request(call_digit="c")

    assert workflow_business_fingerprint(definition, first) == workflow_business_fingerprint(
        definition, replay
    )
    assert workflow_business_fingerprint(definition, first) != workflow_business_fingerprint(
        definition, new_run
    )
    assert workflow_business_fingerprint(definition, first) != workflow_business_fingerprint(
        definition, new_call
    )
    stored = workflow_request_storage_document(first)
    assert stored["production_occurrence"] == first.production_occurrence.model_dump(mode="json")
    assert stored["expected_resolution"] == first.expected_resolution.model_dump(mode="json")


def test_production_identity_and_resolution_never_enter_worker_request() -> None:
    request = _request()
    worker_document = request.worker_request().model_dump(mode="json")

    assert worker_document == {
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
    }
    assert "production_occurrence" not in worker_document
    assert "expected_resolution" not in worker_document


def test_production_occurrence_and_expected_resolution_are_atomic() -> None:
    document = _request().model_dump(mode="json")
    with pytest.raises(ValidationError, match="supplied together"):
        WorkflowRequest.model_validate(document | {"expected_resolution": None})
    with pytest.raises(ValidationError, match="catalog selection"):
        WorkflowRequest.model_validate(
            document
            | {
                "expected_resolution": {
                    **document["expected_resolution"],
                    "content_pack_key": "another-pack",
                }
            }
        )


@pytest.mark.parametrize(
    "action",
    (
        CommandType.APPROVE_WORKFLOW,
        CommandType.REQUEST_REWORK,
        CommandType.CANCEL_WORKFLOW,
    ),
)
def test_public_mutation_guard_rejects_production_workflow(action: CommandType) -> None:
    session = Mock()
    session.get.return_value = SimpleNamespace(
        initial_request=workflow_request_storage_document(_request())
    )
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = cast(Any, lambda: nullcontext(session))

    with pytest.raises(ApiError) as raised:
        adapter.require_public_workflow_action_allowed("workflow_" + "f" * 32, action)

    assert raised.value.status == 403
    assert raised.value.error_code == "WORKFLOW_PRODUCTION_OCCURRENCE_INTERNAL_ONLY"


def test_internal_command_path_can_cancel_production_workflow() -> None:
    workflow = SimpleNamespace(
        lock_version=7,
        initial_request=workflow_request_storage_document(_request()),
    )
    session = Mock()
    session.scalar.return_value = workflow
    command = SimpleNamespace(command_id="command_" + "d" * 32)
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = cast(Any, object())

    with (
        patch(
            "eom_api.services.command_adapter.transaction",
            return_value=nullcontext(session),
        ),
        patch(
            "eom_api.services.command_adapter.enqueue_command",
            return_value=(command, True),
        ) as enqueue,
    ):
        result = adapter.workflow_action(
            "workflow_" + "f" * 32,
            CommandType.CANCEL_WORKFLOW,
            WorkflowActionRequest(),
            cast(Any, SimpleNamespace(actor_id="operator_" + "e" * 32)),
            expected_version=7,
            idempotency_key="internal-production-cancel",
        )

    assert result == (command.command_id, 7)
    enqueue.assert_called_once()


class _PackBindingSession:
    def __init__(self, *, active: bool = True, bundle_digit: str = "6") -> None:
        self.activation = SimpleNamespace(
            activation_id="activation_" + "1" * 32,
            environment="development",
            active=active,
        )
        self.release = SimpleNamespace(
            content_pack_release_id="packrel_" + "5" * 32,
            content_pack_id="pack_" + "1" * 32,
            state="RELEASED",
            version="1.13.0",
            bundle_sha256="sha256:" + bundle_digit * 64,
            source_tree_sha256="sha256:" + "7" * 64,
            manifest_sha256="sha256:" + "d" * 64,
        )
        self.pack = SimpleNamespace(
            content_pack_id=self.release.content_pack_id,
            pack_key="generated-knowledge-item",
        )

    def scalar(self, _statement: object) -> object | None:
        return self.activation if self.activation.active else None

    def get(self, model: object, _identity: object) -> object | None:
        if model is ContentPackReleaseRecord:
            return self.release
        if model is ContentPackRecord:
            return self.pack
        raise AssertionError(f"unexpected model: {model}")


def _catalog_without_io() -> WorkflowCatalogService:
    service = object.__new__(WorkflowCatalogService)
    service._require_compatibility = lambda *_args: None  # type: ignore[method-assign]
    service._require_item_brief_release = lambda *_args: None  # type: ignore[method-assign]
    service._profile_snapshots = lambda *_args: {  # type: ignore[method-assign]
        "authoring": {"required_context": []},
        "review": {"required_context": []},
        "image": {"required_context": []},
        "registration": {"required_context": []},
    }
    return service


def test_exact_pack_binding_uses_the_pinned_active_release() -> None:
    request = _request()
    session = _PackBindingSession()

    context = _catalog_without_io().bind_request(
        request,
        definition_key="generic-item-development",
        definition_version="1.8.0",
        session=cast(Any, session),
    )

    assert context["content_pack"] == {
        "release_id": "packrel_" + "5" * 32,
        "pack_key": "generated-knowledge-item",
        "version": "1.13.0",
        "release_sha256": "sha256:" + "6" * 64,
        "source_tree_sha256": "sha256:" + "7" * 64,
        "manifest_sha256": "sha256:" + "d" * 64,
        "activation_id": "activation_" + "1" * 32,
        "environment": "development",
    }


def test_exact_pack_binding_rejects_deactivation_and_hash_drift() -> None:
    service = _catalog_without_io()
    with pytest.raises(ContentPackError):
        service.bind_request(
            _request(),
            definition_key="generic-item-development",
            definition_version="1.8.0",
            session=cast(Any, _PackBindingSession(active=False)),
        )
    with pytest.raises(ContentPackError, match="stale or mismatched"):
        service.bind_request(
            _request(),
            definition_key="generic-item-development",
            definition_version="1.8.0",
            session=cast(Any, _PackBindingSession(bundle_digit="e")),
        )
