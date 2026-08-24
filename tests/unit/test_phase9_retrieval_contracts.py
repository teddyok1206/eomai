from __future__ import annotations

import pytest
from eom_catalog_contracts import (
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    CreateEvidenceBundleCommand,
    EducationRetrievalAccessPolicy,
    EducationRetrievalRequestV2,
    EvidenceBundleManifestV2,
    EvidenceBundlePublicationResult,
    EvidenceEntryV2,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

NOW = "2026-08-24T00:00:00Z"
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def _artifact_member(
    *,
    member_path: str,
    schema_ref: str,
    media_type: str,
    sha256: str = SHA_A,
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + "1" * 32,
        "artifact_revision_id": "rev_" + "2" * 32,
        "sha256": sha256,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "logical_name": member_path.rsplit("/", 1)[-1],
        "member_path": member_path,
    }


def _graph_snapshot() -> dict[str, object]:
    return {
        "graph_id": "graph_" + "3" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "4" * 32,
        "manifest_artifact": _artifact_member(
            member_path="evidence/graph-snapshot-manifest.json",
            schema_ref="eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
            media_type="application/json",
            sha256=SHA_B,
        ),
        "manifest_sha256": SHA_B,
    }


def _source() -> dict[str, object]:
    return {
        "source_kind": "APPROVED_ITEM_REVISION",
        "source_class": "APPROVED_ITEM",
        "item_id": "item_" + "5" * 32,
        "item_revision_id": "itemrev_" + "6" * 32,
        "lifecycle_state": "APPROVED",
        "artifact_member": {
            **_artifact_member(
                member_path="source/item.json",
                schema_ref="eom.assessment.item-content/1.0",
                media_type="application/json",
                sha256=SHA_C,
            ),
            "materialized_path": "source/item.json",
            "bytes": 1024,
        },
    }


def _policy_value() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "education-retrieval-access-policy/1.0",
        "access_policy_revision_id": "accessrev_" + "7" * 32,
        "state": "RELEASED",
        "allowed_query_kinds": [
            "APPROVED_ITEM_STRUCTURE",
            "CURRICULUM_COMPONENTS",
            "ITEM_PREPARATION",
        ],
        "allowed_requester_roles": ["ADMIN", "EDITOR", "REVIEWER", "WORKER"],
        "allowed_source_classes": [
            "APPROVED_ITEM",
            "CURRICULUM",
            "INTERNAL_GUIDE",
            "PAST_EXAM",
            "TEXTBOOK",
        ],
        "answer_bearing_roles": ["ADMIN", "EDITOR", "REVIEWER"],
        "maximum_budget": {
            "max_documents": 16,
            "max_item_revisions": 16,
            "max_graph_nodes": 128,
            "max_claims": 64,
            "max_context_tokens": 16000,
        },
        "created_at": NOW,
    }
    value["content_sha256"] = content_sha256(value)
    return value


def _request_value(policy: EducationRetrievalAccessPolicy) -> dict[str, object]:
    permissions = ["knowledge_graph:read", "knowledge_graph:retrieve"]
    value: dict[str, object] = {
        "schema_version": "education-retrieval-request/2.0",
        "retrieval_request_id": "retrieval_" + "8" * 32,
        "graph_snapshot": _graph_snapshot(),
        "query_kind": "APPROVED_ITEM_STRUCTURE",
        "curriculum_scope": {
            "framework_revision_id": "curriculumrev_" + "9" * 32,
            "root_unit_id": "currunit_" + "a" * 32,
            "include_descendants": True,
        },
        "topic_keys": ["earth.system"],
        "target_item_revision_id": None,
        "required_item_elements": ["statement_set", "table"],
        "source_classes": ["APPROVED_ITEM", "PAST_EXAM"],
        "retrieval_mode": "HYBRID_LOCAL_MULTIHOP",
        "evidence_budget": {
            "max_documents": 8,
            "max_item_revisions": 8,
            "max_graph_nodes": 64,
            "max_claims": 32,
            "max_context_tokens": 8000,
        },
        "access_policy_revision_id": policy.access_policy_revision_id,
        "access_policy_sha256": policy.content_sha256,
        "requester_role": "EDITOR",
        "requester_operator_id": "operator_" + "b" * 32,
        "requester_permission_keys": permissions,
        "requester_permissions_sha256": content_sha256({"permission_keys": permissions}),
        "requested_at": NOW,
    }
    value["request_sha256"] = content_sha256(value)
    return value


def _entry() -> dict[str, object]:
    return {
        "evidence_id": "evidenceitem_" + "c" * 32,
        "evidence_kind": "ITEM_REVISION",
        "use": "REFERENCE_PATTERN",
        "source": _source(),
        "graph_node_ids": ["knode_item"],
        "anchor_ids": ["anchor_item"],
        "relevance_milli": 900,
        "answer_bearing": False,
    }


def _manifest_value(request: EducationRetrievalRequestV2) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "evidence-bundle-manifest/2.0",
        "evidence_bundle_id": "evidence_" + "d" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "e" * 32,
        "revision_number": 1,
        "retrieval_request_id": request.retrieval_request_id,
        "retrieval_request_sha256": request.request_sha256,
        "graph_snapshot": request.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": request.access_policy_revision_id,
        "access_policy_sha256": request.access_policy_sha256,
        "requester_permissions_sha256": request.requester_permissions_sha256,
        "materials": {
            "context_markdown": _artifact_member(
                member_path="evidence/context.md",
                schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
                media_type="text/markdown",
            )
        },
        "entries": [_entry()],
        "budget": {
            "document_count": 0,
            "item_revision_count": 1,
            "graph_node_count": 1,
            "claim_count": 0,
            "estimated_context_tokens": 400,
        },
        "created_at": NOW,
    }
    value["manifest_sha256"] = content_sha256(value)
    return value


def test_phase9_resolved_request_policy_manifest_and_result_validate() -> None:
    policy_value = _policy_value()
    validate_contract("education-retrieval-access-policy", policy_value)
    policy = EducationRetrievalAccessPolicy.model_validate(policy_value)

    request_value = _request_value(policy)
    validate_contract("education-retrieval-request-v2", request_value)
    request = EducationRetrievalRequestV2.model_validate(request_value)

    manifest_value = _manifest_value(request)
    validate_contract("evidence-bundle-manifest-v2", manifest_value)
    manifest = EvidenceBundleManifestV2.model_validate(manifest_value)

    result_value: dict[str, object] = {
        "schema_version": "evidence-bundle-publication-result/1.0",
        "evidence_bundle_id": manifest.evidence_bundle_id,
        "evidence_bundle_revision_id": manifest.evidence_bundle_revision_id,
        "revision_number": 1,
        "state": "PUBLISHED",
        "retrieval_request_id": request.retrieval_request_id,
        "retrieval_request_sha256": request.request_sha256,
        "graph_snapshot": request.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": policy.access_policy_revision_id,
        "access_policy_sha256": policy.content_sha256,
        "manifest_artifact": _artifact_member(
            member_path="evidence/manifest.json",
            schema_ref="eom://schemas/knowledge/evidence-bundle-manifest/2.0",
            media_type="application/json",
            sha256=manifest.manifest_sha256,
        ),
        "manifest_sha256": manifest.manifest_sha256,
        "budget": manifest.budget.model_dump(mode="json"),
        "published_at": NOW,
    }
    result_value["result_sha256"] = content_sha256(result_value)
    validate_contract("evidence-bundle-publication-result", result_value)
    EvidenceBundlePublicationResult.model_validate(result_value)

    assert request.curriculum_scope is not None
    command_value: dict[str, object] = {
        "operation": "CREATE_EVIDENCE_BUNDLE",
        "graph_snapshot_revision_id": request.graph_snapshot.graph_snapshot_revision_id,
        "query_kind": request.query_kind,
        "curriculum_scope": request.curriculum_scope.model_dump(mode="json"),
        "topic_keys": list(request.topic_keys),
        "target_item_revision_id": None,
        "required_item_elements": list(request.required_item_elements),
        "source_classes": list(request.source_classes),
        "evidence_budget": request.evidence_budget.model_dump(mode="json"),
        "access_policy_revision_id": policy.access_policy_revision_id,
        "requester_role": request.requester_role,
        "requester_permission_keys": list(request.requester_permission_keys),
        "requested_by": request.requester_operator_id,
        "idempotency_key": "phase9-evidence-test-key",
    }
    command_value["submission_sha256"] = content_sha256(
        {key: value for key, value in command_value.items() if key != "idempotency_key"}
    )
    validate_contract("catalog-application-request-v3", command_value)
    command = CatalogApplicationRequest.model_validate(command_value).root
    assert isinstance(command, CreateEvidenceBundleCommand)
    response_value = {
        "status": "OK",
        "operation": "CREATE_EVIDENCE_BUNDLE",
        "evidence": result_value,
    }
    validate_contract("catalog-application-response-v3", response_value)
    CatalogApplicationResponse.model_validate(response_value)


def test_phase9_request_rejects_permission_hash_and_unsorted_filters() -> None:
    policy = EducationRetrievalAccessPolicy.model_validate(_policy_value())
    bad_hash = _request_value(policy)
    bad_hash["requester_permissions_sha256"] = SHA_A
    bad_hash["request_sha256"] = content_sha256(
        {key: value for key, value in bad_hash.items() if key != "request_sha256"}
    )
    with pytest.raises(ValidationError, match="permission-set hash"):
        EducationRetrievalRequestV2.model_validate(bad_hash)

    unsorted = _request_value(policy)
    unsorted["required_item_elements"] = ["table", "statement_set"]
    unsorted["request_sha256"] = content_sha256(
        {key: value for key, value in unsorted.items() if key != "request_sha256"}
    )
    with pytest.raises(ValidationError, match="must be sorted and unique"):
        EducationRetrievalRequestV2.model_validate(unsorted)


def test_phase9_answer_bearing_and_budget_contracts_fail_closed() -> None:
    answer = _entry()
    answer["answer_bearing"] = True
    with pytest.raises(ValidationError, match="AVOID_COPY"):
        EvidenceEntryV2.model_validate(answer)

    policy = EducationRetrievalAccessPolicy.model_validate(_policy_value())
    request = EducationRetrievalRequestV2.model_validate(_request_value(policy))
    mismatch = _manifest_value(request)
    budget = mismatch["budget"]
    assert isinstance(budget, dict)
    mismatch["budget"] = {**budget, "item_revision_count": 0}
    mismatch["manifest_sha256"] = content_sha256(
        {key: value for key, value in mismatch.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="counts do not match"):
        EvidenceBundleManifestV2.model_validate(mismatch)


def test_phase9_schemas_reject_unknown_fields_before_typed_validation() -> None:
    policy = _policy_value()
    policy["unbounded_query"] = True
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("education-retrieval-access-policy", policy)
