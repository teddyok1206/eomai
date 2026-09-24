from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.services.command_adapter import CommandAdapter
from eom_workflow import PairedDocumentReviewRequest, PairedDocumentReviewRequestV2


class _ReplaySession:
    def __init__(self, workflow: object, command: object) -> None:
        self._values = iter((workflow, command))

    def __enter__(self) -> _ReplaySession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalar(self, _statement: object) -> object:
        return next(self._values)


def test_paired_review_replays_before_mutable_policy_or_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = SimpleNamespace(key="MOCK_EXAM")
    request = PairedDocumentReviewRequest.model_construct(
        documents=("question", "solution"),
        preset=preset,
        additional_guidance="중복 요청",
        additional_guidance_sha256="sha256:" + "1" * 64,
        locale="ko-KR",
    )
    stored_review = PairedDocumentReviewRequestV2.model_construct(
        documents=request.documents,
        preset=preset,
        additional_guidance=request.additional_guidance,
        additional_guidance_sha256=request.additional_guidance_sha256,
        locale=request.locale,
    )
    workflow = SimpleNamespace(
        initial_request={},
        created_actor_type="human",
        created_actor_id="operator_" + "2" * 32,
        definition_key="pdf-document-review",
        definition_version="1.2.0",
        workflow_id="workflow_" + "3" * 32,
        lock_version=7,
    )
    command = SimpleNamespace(command_id="wfcmd_" + "4" * 32)
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = cast(Any, lambda: _ReplaySession(workflow, command))
    adapter.catalog_application = cast(Any, None)
    monkeypatch.setattr(
        "eom_api.services.command_adapter.load_persisted_workflow_request",
        lambda _value: SimpleNamespace(
            request_name="PAIRED_DOCUMENT_REVIEW_REQUEST",
            paired_document_review_request=stored_review,
        ),
    )

    def forbidden_policy(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("replay consulted mutable current policy")

    monkeypatch.setattr(
        "eom_api.services.command_adapter.current_knowledge_backed_preset",
        forbidden_policy,
    )

    result = adapter.start_paired_document_review(
        request,
        cast(Any, SimpleNamespace(actor_id=workflow.created_actor_id)),
        idempotency_key="review-replay",
    )

    assert result == (command.command_id, workflow.workflow_id, 7)
