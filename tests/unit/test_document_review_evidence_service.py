from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    CreateDocumentReviewEvidenceCommand,
    CreateDocumentReviewTextbookEvidenceCommand,
    EvidenceBundlePublicationResultV4,
    EvidenceBundlePublicationResultV5,
    PdfReviewDocumentPointer,
    validate_contract,
)
from eom_catalog_service.document_review_evidence_service import (
    DocumentReviewEvidenceService,
    DocumentReviewEvidenceServiceError,
    _rank_topic_key_rows,
)
from eom_catalog_service.review_textbook_evidence_service import ReviewTextbookEvidenceService
from eom_identifiers import content_sha256


def _document(seed: str) -> PdfReviewDocumentPointer:
    artifact_id = "artifact_" + seed * 32
    revision_id = "rev_" + seed * 32
    return PdfReviewDocumentPointer.model_validate(
        {
            "document_id": "document_" + seed * 32,
            "document_revision_id": "documentrev_" + seed * 32,
            "original_filename": f"review-{seed}.pdf",
            "source_pdf": {
                "artifact_id": artifact_id,
                "artifact_revision_id": revision_id,
                "member_path": "source/original.pdf",
                "sha256": "sha256:" + seed * 64,
                "schema_ref": "eom://schemas/document-review/pdf-source/1.0",
                "media_type": "application/pdf",
                "content_length": 4096,
            },
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "width_px": 1200,
                    "height_px": 1800,
                    "rotation_degrees": 0,
                    "page_image": {
                        "artifact_id": artifact_id,
                        "artifact_revision_id": revision_id,
                        "member_path": "pages/page-0001.png",
                        "sha256": "sha256:" + seed * 64,
                        "schema_ref": "eom://schemas/document-review/pdf-page-render/1.0",
                        "media_type": "image/png",
                        "content_length": 2048,
                    },
                    "text_layer": None,
                }
            ],
        }
    )


def _member(seed: str, *, manifest: bool) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": (
            "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
            if manifest
            else "eom://schemas/knowledge/evidence-bundle-context/1.0"
        ),
        "media_type": "application/json" if manifest else "text/markdown",
        "logical_name": "manifest.json" if manifest else "context.md",
        "member_path": "evidence/manifest.json" if manifest else "evidence/context.md",
    }


def _publication(
    *, version: str = "5.0"
) -> EvidenceBundlePublicationResultV5 | EvidenceBundlePublicationResultV4:
    value: dict[str, object] = {
        "schema_version": f"evidence-bundle-publication-result/{version}",
        "evidence_bundle_id": "evidence_" + "3" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "4" * 32,
        "revision_number": 1,
        "state": "PUBLISHED",
        "retrieval_request_id": "retrieval_" + "5" * 32,
        "retrieval_request_sha256": "sha256:" + "5" * 64,
        "graph_snapshot": {
            "graph_id": "graph_" + "6" * 32,
            "graph_snapshot_revision_id": "graphrev_" + "7" * 32,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "8" * 32,
                "artifact_revision_id": "rev_" + "8" * 32,
                "sha256": "sha256:" + "8" * 64,
                "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
                "member_path": "projections/manifest.json",
            },
            "manifest_sha256": "sha256:" + "8" * 64,
        },
        "access_policy_revision_id": "accessrev_" + "9" * 32,
        "access_policy_sha256": "sha256:" + "9" * 64,
        "requester_permissions_sha256": "sha256:" + "a" * 64,
        "manifest_artifact": _member("b", manifest=True),
        "manifest_sha256": "sha256:" + "c" * 64,
        "context_artifact": _member("d", manifest=False),
        "budget": {
            "document_count": 1,
            "item_revision_count": 1,
            "graph_node_count": 2,
            "claim_count": 1,
            "estimated_context_tokens": 1000,
        },
        "published_at": "2026-09-24T00:00:00Z",
        "result_sha256": "sha256:" + "0" * 64,
    }
    if version == "4.0":
        manifest = value["manifest_artifact"]
        assert isinstance(manifest, dict)
        manifest["schema_ref"] = "eom://schemas/knowledge/evidence-bundle-manifest/4.0"
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    model = (
        EvidenceBundlePublicationResultV5 if version == "5.0" else EvidenceBundlePublicationResultV4
    )
    return model.model_validate(value)


def _command() -> CreateDocumentReviewEvidenceCommand:
    value: dict[str, object] = {
        "schema_version": "document-review-evidence-request/1.0",
        "operation": "CREATE_DOCUMENT_REVIEW_EVIDENCE",
        "documents": [
            {"role": "QUESTION", "document": _document("1").model_dump(mode="json")},
            {"role": "SOLUTION", "document": _document("2").model_dump(mode="json")},
        ],
        "corpus_key": "integrated-science-textbooks",
        "source_classes": ["APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK"],
        "evidence_budget": {
            "max_documents": 8,
            "max_item_revisions": 8,
            "max_graph_nodes": 32,
            "max_claims": 16,
            "max_context_tokens": 8000,
        },
        "access_policy_revision_id": "accessrev_" + "9" * 32,
        "access_policy_sha256": "sha256:" + "9" * 64,
        "requester_role": "ADMIN",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "e" * 32,
        "idempotency_key": "document-review-evidence:test",
    }
    value["submission_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "idempotency_key"}
    )
    return CreateDocumentReviewEvidenceCommand.model_validate(value)


def _textbook_command(*, paired: bool) -> CreateDocumentReviewTextbookEvidenceCommand:
    value: dict[str, object] = {
        "schema_version": "document-review-textbook-evidence-request/1.0",
        "operation": "CREATE_DOCUMENT_REVIEW_TEXTBOOK_EVIDENCE",
        "review_input_sha256": "sha256:" + "a" * 64,
        "documents": (
            [
                {"role": "QUESTION", "document": _document("1").model_dump(mode="json")},
                {"role": "SOLUTION", "document": _document("2").model_dump(mode="json")},
            ]
            if paired
            else [{"role": "DOCUMENT", "document": _document("1").model_dump(mode="json")}]
        ),
        "corpus_key": "integrated-science-textbooks",
        "evidence_budget": {
            "max_documents": 8,
            "max_item_revisions": 0,
            "max_graph_nodes": 32,
            "max_claims": 16,
            "max_context_tokens": 8000,
        },
        "access_policy_revision_id": "accessrev_" + "9" * 32,
        "access_policy_sha256": "sha256:" + "9" * 64,
        "requester_role": "REVIEWER",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "e" * 32,
    }
    value["submission_sha256"] = content_sha256(value)
    value["idempotency_key"] = "document-review-textbook-unit-test"
    validate_contract("document-review-textbook-evidence-request", value)
    return CreateDocumentReviewTextbookEvidenceCommand.model_validate(value)


def _service(publication: object) -> DocumentReviewEvidenceService:
    service = object.__new__(DocumentReviewEvidenceService)
    service.artifacts = SimpleNamespace(read_member=Mock(return_value=b"%PDF-1.7"))
    service.retrieval = SimpleNamespace(create_item_production=Mock(return_value=publication))
    service._open_extractor = Mock(
        return_value=("sha256:" + "f" * 64, os.open("/dev/null", os.O_RDONLY))
    )
    service._extract_terms = Mock(side_effect=({"energy", "force"}, {"energy", "motion"}))
    service._resolve_topic_keys = Mock(return_value=("concept.energy", "concept.motion"))
    return service


def test_topic_key_ranking_is_bounded_deterministic_and_filters_invalid_keys() -> None:
    assert _rank_topic_key_rows(
        (
            ("energy", "concept.energy", 2),
            ("force", "concept.motion", 10),
            ("motion", "concept.motion", 10),
            ("unsafe", "INVALID KEY", 1),
        ),
        limit=2,
    ) == ("concept.energy", "concept.motion")


def test_document_review_evidence_plan_requires_solution_enriched_publication() -> None:
    service = _service(_publication())
    plan = service.create(_command())
    assert plan.topic_keys == ("concept.energy", "concept.motion")
    assert tuple(value.role for value in plan.documents) == ("QUESTION", "SOLUTION")
    submitted = service.retrieval.create_item_production.call_args.args[0]
    assert submitted.solution_evidence_requirement == "REQUIRE_ACCEPTED_SOLUTION_REPORT"
    assert submitted.requirement.topic_keys == plan.topic_keys
    original = _command()
    assert submitted.idempotency_key == "document-review-evidence:" + content_sha256(
        {
            "idempotency_key": original.idempotency_key,
            "submission_sha256": original.submission_sha256,
        }
    ).removeprefix("sha256:")

    legacy_service = _service(_publication(version="4.0"))
    with pytest.raises(DocumentReviewEvidenceServiceError) as captured:
        legacy_service.create(_command())
    assert captured.value.code == "DOCUMENT_REVIEW_EVIDENCE_SOLUTION_MISSING"


def test_document_review_evidence_rejects_missing_text_or_graph_scope() -> None:
    no_text = _service(_publication())
    no_text._extract_terms = Mock(return_value=set())
    with pytest.raises(DocumentReviewEvidenceServiceError) as captured:
        no_text.create(_command())
    assert captured.value.code == "DOCUMENT_REVIEW_EVIDENCE_TEXT_MISSING"

    no_scope = _service(_publication())
    no_scope._resolve_topic_keys = Mock(return_value=())
    with pytest.raises(DocumentReviewEvidenceServiceError) as captured:
        no_scope.create(_command())
    assert captured.value.code == "DOCUMENT_REVIEW_EVIDENCE_SCOPE_MISSING"


@pytest.mark.parametrize("paired", [False, True])
def test_document_review_textbook_scope_is_exact_and_excludes_item_sources(
    monkeypatch, paired: bool
) -> None:
    command = _textbook_command(paired=paired)
    observed: list[object] = []
    sentinel = object()

    def capture_create(self, *, review_input_sha256, command):
        observed.append((review_input_sha256, command))
        return sentinel

    monkeypatch.setattr(ReviewTextbookEvidenceService, "create", capture_create)
    service = _service(_publication())
    assert service.create_textbook(command) is sentinel
    assert len(observed) == 1
    review_hash, retrieval = observed[0]
    assert review_hash == command.review_input_sha256
    assert retrieval.requirement.source_classes == ("TEXTBOOK",)
    assert retrieval.solution_evidence_requirement == "NONE"
    assert retrieval.idempotency_key.startswith("document-review-textbook:")
    assert retrieval.evidence_budget.max_item_revisions == 0
    assert service.artifacts.read_member.call_count == len(command.documents)


def test_document_review_textbook_command_rejects_wrong_single_role() -> None:
    valid = _textbook_command(paired=False).model_dump(mode="json")
    valid["documents"][0]["role"] = "QUESTION"
    valid["submission_sha256"] = content_sha256(
        {
            key: item
            for key, item in valid.items()
            if key not in {"idempotency_key", "submission_sha256"}
        }
    )
    with pytest.raises(ValueError, match="single or exact paired"):
        CreateDocumentReviewTextbookEvidenceCommand.model_validate(valid)


def test_document_review_textbook_error_response_schema() -> None:
    validate_contract(
        "document-review-textbook-evidence-response",
        {
            "schema_version": "document-review-textbook-evidence-response/1.0",
            "operation": "CREATE_DOCUMENT_REVIEW_TEXTBOOK_EVIDENCE",
            "status": "ERROR",
            "error_code": "REVIEW_TEXTBOOK_SOURCE_MISSING",
        },
    )
