"""Review textbook pointer is not satisfied by policy permission alone."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import CreateItemProductionEvidenceCommand, ReviewTextbookEvidence
from eom_catalog_contracts.knowledge import (
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
    EvidenceBundlePublicationResultV5,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.review_textbook_evidence_service import (
    ReviewTextbookEvidenceError,
    ReviewTextbookEvidenceService,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.test_knowledge_analysis_document_contracts import document_source


def _publication() -> EvidenceBundlePublicationResultV4:
    graph = {
        "graph_id": "graph_" + "1" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "1" * 32,
            "sha256": "sha256:" + "1" * 64,
            "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
            "member_path": "projections/manifest.json",
        },
        "manifest_sha256": "sha256:" + "1" * 64,
    }

    def member(seed: str, *, context: bool) -> dict[str, str]:
        return {
            "artifact_id": "artifact_" + seed * 32,
            "artifact_revision_id": "rev_" + seed * 32,
            "sha256": "sha256:" + seed * 64,
            "schema_ref": (
                "eom://schemas/knowledge/evidence-bundle-context/1.0"
                if context
                else "eom://schemas/knowledge/evidence-bundle-manifest/4.0"
            ),
            "media_type": "text/markdown" if context else "application/json",
            "logical_name": "context.md" if context else "manifest.json",
            "member_path": "evidence/context.md" if context else "evidence/manifest.json",
        }

    value: dict[str, object] = {
        "schema_version": "evidence-bundle-publication-result/4.0",
        "evidence_bundle_id": "evidence_" + "2" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "2" * 32,
        "revision_number": 1,
        "state": "PUBLISHED",
        "retrieval_request_id": "retrieval_" + "3" * 32,
        "retrieval_request_sha256": "sha256:" + "3" * 64,
        "graph_snapshot": graph,
        "access_policy_revision_id": "accessrev_" + "4" * 32,
        "access_policy_sha256": "sha256:" + "4" * 64,
        "requester_permissions_sha256": content_sha256(
            {"permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"]}
        ),
        "manifest_artifact": member("6", context=False),
        "manifest_sha256": "sha256:" + "6" * 64,
        "context_artifact": member("7", context=True),
        "budget": {
            "document_count": 1,
            "item_revision_count": 0,
            "graph_node_count": 1,
            "claim_count": 0,
            "estimated_context_tokens": 1000,
        },
        "published_at": "2026-10-26T00:00:00Z",
    }
    value["result_sha256"] = content_sha256(value)
    return EvidenceBundlePublicationResultV4.model_validate(value)


def _binding() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "review-textbook-evidence/1.0",
        "review_input_sha256": "sha256:" + "8" * 64,
        "requirement": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "integrated-science-textbooks",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": None,
            "topic_keys": ["concept.force"],
            "required_item_elements": ["paragraph"],
            "source_classes": ["TEXTBOOK"],
        },
        "publication": _publication().model_dump(mode="json"),
        "textbook_evidence_ids": ["evidenceitem_" + "9" * 32],
    }
    value["binding_sha256"] = content_sha256(value)
    return value


def _manifest(
    binding: ReviewTextbookEvidence, *, source_class: str = "TEXTBOOK"
) -> EvidenceBundleManifestV4:
    publication = binding.publication
    return cast(
        EvidenceBundleManifestV4,
        SimpleNamespace(
            schema_version="evidence-bundle-manifest/4.0",
            evidence_bundle_id=publication.evidence_bundle_id,
            evidence_bundle_revision_id=publication.evidence_bundle_revision_id,
            retrieval_request_id=publication.retrieval_request_id,
            retrieval_request_sha256=publication.retrieval_request_sha256,
            graph_snapshot=publication.graph_snapshot,
            access_policy_revision_id=publication.access_policy_revision_id,
            access_policy_sha256=publication.access_policy_sha256,
            requester_permissions_sha256=publication.requester_permissions_sha256,
            manifest_sha256=publication.manifest_sha256,
            materials=SimpleNamespace(context_markdown=publication.context_artifact),
            entries=(
                SimpleNamespace(
                    evidence_id=binding.textbook_evidence_ids[0],
                    source=SimpleNamespace(source_class=source_class),
                    use="GROUNDING",
                ),
            ),
        ),
    )


def test_textbook_only_binding_is_schema_and_model_valid() -> None:
    value = _binding()
    validate_contract("review-textbook-evidence", value)
    binding = ReviewTextbookEvidence.model_validate(value)
    binding.verify_manifest(_manifest(binding))


def test_mixed_source_permission_cannot_satisfy_textbook_requirement() -> None:
    value = _binding()
    requirement = value["requirement"]
    assert isinstance(requirement, dict)
    requirement["source_classes"] = ["PAST_EXAM", "TEXTBOOK"]
    value["binding_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "binding_sha256"}
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("review-textbook-evidence", value)
    with pytest.raises(ValidationError, match="textbook sources exclusively"):
        ReviewTextbookEvidence.model_validate(value)


def test_non_textbook_or_stale_manifest_fails_closed() -> None:
    binding = ReviewTextbookEvidence.model_validate(_binding())
    with pytest.raises(ValueError, match="non-textbook source"):
        binding.verify_manifest(_manifest(binding, source_class="PAST_EXAM"))
    stale = _manifest(binding)
    stale.manifest_sha256 = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="differs from pinned publication"):
        binding.verify_manifest(stale)


def test_binding_hash_and_evidence_identity_are_immutable() -> None:
    value = _binding()
    value["textbook_evidence_ids"] = ["evidenceitem_" + "a" * 32]
    with pytest.raises(ValidationError, match="binding hash differs"):
        ReviewTextbookEvidence.model_validate(value)


def _command(
    *, source_classes: list[str] | None = None, policy_sha256: str | None = None
) -> CreateItemProductionEvidenceCommand:
    requirement = _binding()["requirement"]
    assert isinstance(requirement, dict)
    if source_classes is not None:
        requirement["source_classes"] = source_classes
    value: dict[str, object] = {
        "operation": "CREATE_ITEM_PRODUCTION_EVIDENCE",
        "requirement": requirement,
        "evidence_budget": {
            "max_documents": 8,
            "max_item_revisions": 0,
            "max_graph_nodes": 32,
            "max_claims": 16,
            "max_context_tokens": 8000,
        },
        "access_policy_revision_id": "accessrev_" + "4" * 32,
        "access_policy_sha256": policy_sha256 or "sha256:" + "4" * 64,
        "requester_role": "REVIEWER",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "a" * 32,
        "solution_evidence_requirement": "NONE",
    }
    value["submission_sha256"] = content_sha256(value)
    value["idempotency_key"] = "review-textbook-unit-test"
    return CreateItemProductionEvidenceCommand.model_validate(value)


def test_catalog_boundary_publishes_and_reopens_exact_textbook_manifest(monkeypatch) -> None:
    publication = _publication()
    expected = ReviewTextbookEvidence.model_validate(_binding())
    retrieval = SimpleNamespace(create_item_production=Mock(return_value=publication))
    artifacts = SimpleNamespace(read_member=Mock(return_value=b"{}"))
    monkeypatch.setattr(
        "eom_catalog_service.review_textbook_evidence_service.validate_contract",
        lambda _key, _value: None,
    )
    monkeypatch.setattr(
        EvidenceBundleManifestV4,
        "model_validate",
        staticmethod(lambda _value: _manifest(expected)),
    )
    service = ReviewTextbookEvidenceService(retrieval=retrieval, artifacts=artifacts)
    binding = service.create(
        review_input_sha256=expected.review_input_sha256,
        command=_command(),
    )
    assert binding == expected
    assert retrieval.create_item_production.call_count == 1
    assert artifacts.read_member.call_args.kwargs["sha256"] == publication.manifest_artifact.sha256


def test_catalog_boundary_rejects_mixed_scope_before_publication() -> None:
    retrieval = SimpleNamespace(create_item_production=Mock())
    service = ReviewTextbookEvidenceService(
        retrieval=retrieval,
        artifacts=SimpleNamespace(read_member=Mock()),
    )
    with pytest.raises(ReviewTextbookEvidenceError, match="textbook-only"):
        service.create(
            review_input_sha256="sha256:" + "8" * 64,
            command=_command(source_classes=["PAST_EXAM", "TEXTBOOK"]),
        )
    retrieval.create_item_production.assert_not_called()


def test_catalog_boundary_rejects_publication_for_other_authority_before_member_read() -> None:
    publication = _publication()
    artifacts = SimpleNamespace(read_member=Mock())
    service = ReviewTextbookEvidenceService(
        retrieval=SimpleNamespace(create_item_production=Mock(return_value=publication)),
        artifacts=artifacts,
    )
    changed = _command(policy_sha256="sha256:" + "0" * 64)
    with pytest.raises(ReviewTextbookEvidenceError, match="reviewer's released authority"):
        service.create(review_input_sha256="sha256:" + "8" * 64, command=changed)
    artifacts.read_member.assert_not_called()


def test_catalog_boundary_preserves_missing_or_hash_invalid_member_as_stable_error() -> None:
    expected = ReviewTextbookEvidence.model_validate(_binding())
    service = ReviewTextbookEvidenceService(
        retrieval=SimpleNamespace(create_item_production=Mock(return_value=_publication())),
        artifacts=SimpleNamespace(read_member=Mock(side_effect=ValueError("hash mismatch"))),
    )
    with pytest.raises(ReviewTextbookEvidenceError) as captured:
        service.create(review_input_sha256=expected.review_input_sha256, command=_command())
    assert captured.value.code == "REVIEW_TEXTBOOK_MATERIAL_INVALID"


def test_solution_enriched_mixed_bundle_does_not_count_as_textbook_only() -> None:
    value = _publication().model_dump(mode="json")
    value["schema_version"] = "evidence-bundle-publication-result/5.0"
    value["manifest_artifact"]["schema_ref"] = (
        "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
    )
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    publication = EvidenceBundlePublicationResultV5.model_validate(value)
    artifacts = SimpleNamespace(read_member=Mock())
    service = ReviewTextbookEvidenceService(
        retrieval=SimpleNamespace(create_item_production=Mock(return_value=publication)),
        artifacts=artifacts,
    )
    with pytest.raises(ReviewTextbookEvidenceError) as captured:
        service.create(review_input_sha256="sha256:" + "8" * 64, command=_command())
    assert captured.value.code == "REVIEW_TEXTBOOK_SOURCE_MISSING"
    artifacts.read_member.assert_not_called()


def test_catalog_boundary_validates_actual_v3_textbook_manifest_bytes() -> None:
    publication_value = _publication().model_dump(mode="json")
    manifest_value: dict[str, object] = {
        "schema_version": "evidence-bundle-manifest/3.0",
        "evidence_bundle_id": publication_value["evidence_bundle_id"],
        "evidence_bundle_revision_id": publication_value["evidence_bundle_revision_id"],
        "revision_number": 1,
        "retrieval_request_id": publication_value["retrieval_request_id"],
        "retrieval_request_sha256": publication_value["retrieval_request_sha256"],
        "graph_snapshot": publication_value["graph_snapshot"],
        "access_policy_revision_id": publication_value["access_policy_revision_id"],
        "access_policy_sha256": publication_value["access_policy_sha256"],
        "requester_permissions_sha256": publication_value["requester_permissions_sha256"],
        "materials": {"context_markdown": publication_value["context_artifact"]},
        "entries": [
            {
                "evidence_id": "evidenceitem_" + "9" * 32,
                "evidence_kind": "DOCUMENT",
                "use": "GROUNDING",
                "source": document_source(),
                "graph_node_ids": ["knode_document"],
                "anchor_ids": ["anchor_document"],
                "relevance_milli": 1000,
                "answer_bearing": False,
            }
        ],
        "budget": publication_value["budget"],
        "created_at": "2026-10-26T00:00:00Z",
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    validate_contract("evidence-bundle-manifest-v3", manifest_value)
    manifest = EvidenceBundleManifestV3.model_validate(manifest_value)
    payload = canonical_json_bytes(manifest.model_dump(mode="json"))
    publication_value["schema_version"] = "evidence-bundle-publication-result/3.0"
    member = publication_value["manifest_artifact"]
    assert isinstance(member, dict)
    member["schema_ref"] = "eom://schemas/knowledge/evidence-bundle-manifest/3.0"
    member["sha256"] = sha256_bytes(payload)
    publication_value["manifest_sha256"] = manifest.manifest_sha256
    publication_value["result_sha256"] = content_sha256(
        {key: item for key, item in publication_value.items() if key != "result_sha256"}
    )
    publication = EvidenceBundlePublicationResultV3.model_validate(publication_value)
    reader = SimpleNamespace(read_member=Mock(return_value=payload))
    service = ReviewTextbookEvidenceService(
        retrieval=SimpleNamespace(create_item_production=Mock(return_value=publication)),
        artifacts=reader,
    )
    binding = service.create(review_input_sha256="sha256:" + "8" * 64, command=_command())
    assert binding.publication == publication
    assert binding.textbook_evidence_ids == ("evidenceitem_" + "9" * 32,)
    assert reader.read_member.call_args.kwargs["sha256"] == sha256_bytes(payload)
