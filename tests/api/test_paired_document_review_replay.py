from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.errors import ApiError
from eom_api.services.catalog_application_client import CatalogApplicationClientError
from eom_api.services.command_adapter import CommandAdapter
from eom_catalog_contracts import (
    CreateDocumentReviewEvidenceCommand,
    EvidenceBudget,
    PdfReviewDocumentPointer,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from eom_workflow import (
    PairedDocumentReviewRequest,
    PairedDocumentReviewRequestV2,
    build_paired_document_review_request,
)


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


def _document(marker: str) -> PdfReviewDocumentPointer:
    member = {
        "artifact_id": "artifact_" + marker * 32,
        "artifact_revision_id": "rev_" + marker * 32,
        "member_path": "source/original.pdf",
        "sha256": "sha256:" + marker * 64,
        "schema_ref": "eom://schemas/document-review/pdf-source/1.0",
        "media_type": "application/pdf",
        "content_length": 4096,
    }
    return PdfReviewDocumentPointer.model_validate(
        {
            "document_id": "document_" + marker * 32,
            "document_revision_id": "documentrev_" + marker * 32,
            "original_filename": f"review-{marker}.pdf",
            "source_pdf": member,
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "width_px": 1200,
                    "height_px": 1800,
                    "rotation_degrees": 0,
                    "page_image": {
                        **member,
                        "member_path": "pages/page-0001.png",
                        "schema_ref": "eom://schemas/document-review/pdf-page-render/1.0",
                        "media_type": "image/png",
                    },
                    "text_layer": None,
                }
            ],
        }
    )


def test_paired_review_first_start_hashes_complete_versioned_evidence_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = build_paired_document_review_request(
        question_document=_document("1"),
        solution_document=_document("2"),
        preset_key="MOCK_EXAM",
        additional_guidance=None,
    )
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = cast(Any, lambda: _ReplaySession(None, None))
    permissions = frozenset(
        {PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE, PermissionKey.HWPX_BUILD_CREATE}
    )
    actor = SimpleNamespace(actor_id="operator_" + "3" * 32, permissions=permissions)
    policy = SimpleNamespace(
        allowed_corpus_keys=("integrated-science-textbooks",),
        allowed_source_classes=("APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK"),
        maximum_budget=EvidenceBudget(
            max_documents=8,
            max_item_revisions=8,
            max_graph_nodes=32,
            max_claims=16,
            max_context_tokens=8000,
        ),
        access_policy_revision_id="accessrev_" + "4" * 32,
        access_policy_sha256="sha256:" + "4" * 64,
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.current_knowledge_backed_preset",
        lambda *_args, **_kwargs: SimpleNamespace(retrieval_policy=policy),
    )
    observed: list[CreateDocumentReviewEvidenceCommand] = []

    def receive(command: CreateDocumentReviewEvidenceCommand) -> None:
        # Validate the real first-start payload, not a hand-built contract fixture.
        value = command.model_dump(mode="json")
        assert value["schema_version"] == "document-review-evidence-request/1.0"
        assert command.submission_sha256 == content_sha256(
            {
                key: item
                for key, item in value.items()
                if key not in {"idempotency_key", "submission_sha256"}
            }
        )
        assert CreateDocumentReviewEvidenceCommand.model_validate(value) == command
        observed.append(command)
        raise CatalogApplicationClientError("CATALOG_APPLICATION_UNAVAILABLE", "test stop")

    adapter.catalog_application = cast(
        Any, SimpleNamespace(create_document_review_evidence=receive)
    )
    with pytest.raises(ApiError) as failure:
        adapter.start_paired_document_review(
            request, cast(Any, actor), idempotency_key="first-paired-start"
        )
    assert failure.value.error_code == "CATALOG_APPLICATION_UNAVAILABLE"
    assert len(observed) == 1
    assert observed[0].documents[0].document == request.documents[0].document
    assert observed[0].requested_by == actor.actor_id
