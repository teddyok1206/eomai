from __future__ import annotations

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    ContentIntakeKnowledgeSourceV2,
    EducationRetrievalRequestV2,
)
from eom_catalog_service.knowledge_graph_projection import knowledge_node_terms
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    _Candidate,
)
from eom_identifiers import content_sha256

NOW = "2026-08-24T00:00:00Z"


def _member(seed: str, *, media_type: str, schema_ref: str | None) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": "source/content.json"
        if media_type == "application/json"
        else "source/book.md",
        "materialized_path": "source/content.json"
        if media_type == "application/json"
        else "source/book.md",
        "sha256": "sha256:" + seed * 64,
        "bytes": 512,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "logical_name": "content.json" if media_type == "application/json" else "book.md",
    }


def _request() -> EducationRetrievalRequestV2:
    value: dict[str, object] = {
        "schema_version": "education-retrieval-request/2.0",
        "retrieval_request_id": "retrieval_" + "1" * 32,
        "graph_snapshot": {
            "graph_id": "graph_" + "2" * 32,
            "graph_snapshot_revision_id": "graphrev_" + "3" * 32,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "4" * 32,
                "artifact_revision_id": "rev_" + "4" * 32,
                "sha256": "sha256:" + "4" * 64,
                "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
                "member_path": "projections/manifest.json",
            },
            "manifest_sha256": "sha256:" + "4" * 64,
        },
        "query_kind": "ITEM_PREPARATION",
        "curriculum_scope": None,
        "topic_keys": ["earth.plate-boundary"],
        "target_item_revision_id": None,
        "required_item_elements": [],
        "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        "retrieval_mode": "HYBRID_LOCAL_MULTIHOP",
        "evidence_budget": {
            "max_documents": 2,
            "max_item_revisions": 1,
            "max_graph_nodes": 8,
            "max_claims": 2,
            "max_context_tokens": 2000,
        },
        "access_policy_revision_id": "accessrev_" + "5" * 32,
        "access_policy_sha256": "sha256:" + "5" * 64,
        "requester_role": "ADMIN",
        "requester_operator_id": "operator_" + "6" * 32,
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requester_permissions_sha256": content_sha256(
            {"permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"]}
        ),
        "requested_at": NOW,
        "request_sha256": "sha256:" + "0" * 64,
    }
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return EducationRetrievalRequestV2.model_validate(value)


def test_lexical_terms_are_deterministic_bounded_and_shared_with_publication() -> None:
    assert knowledge_node_terms("earth.plate-boundary", "판 경계 Plate") == (
        "boundary",
        "earth",
        "plate",
        "경계",
    )
    assert knowledge_node_terms("x", "a") == ()
    assert all(len(term) <= 128 for term in knowledge_node_terms("x", "가" * 140))


def test_ranked_context_is_bounded_pointer_oriented_and_marks_answers_avoid_copy() -> None:
    document = ContentIntakeKnowledgeSourceV2(
        source_class="TEXTBOOK",
        intake_batch_id="intake_" + "7" * 32,
        source_file_id="sourcefile_" + "8" * 32,
        artifact_member=_member("8", media_type="text/markdown", schema_ref=None),
    )
    item = ApprovedItemKnowledgeSourceV2(
        source_class="APPROVED_ITEM",
        item_id="item_" + "9" * 32,
        item_revision_id="itemrev_" + "a" * 32,
        artifact_member=_member(
            "a", media_type="application/json", schema_ref="eom.assessment.item-content/1.0"
        ),
    )
    entries, markdown = KnowledgeRetrievalApplicationService._rank_and_render(
        request=_request(),
        candidates=(
            _Candidate(
                source=document,
                node_ids=("knode_plate",),
                anchor_ids=("anchor_plate",),
                node_labels=("plate boundary",),
                node_types=("CONCEPT",),
                relevance_milli=950,
                answer_bearing=False,
            ),
            _Candidate(
                source=item,
                node_ids=("knode_item",),
                anchor_ids=("anchor_item",),
                node_labels=("approved item answer pattern",),
                node_types=("ITEM_REVISION",),
                relevance_milli=900,
                answer_bearing=True,
            ),
        ),
    )
    assert tuple(entry.relevance_milli for entry in entries) == (950, 900)
    assert entries[0].use == "GROUNDING"
    assert entries[1].use == "AVOID_COPY"
    assert "nas://" not in markdown
    assert "/mnt/" not in markdown
    assert len(markdown.encode("utf-8")) < 64 * 1024
