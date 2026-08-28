from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_api_contracts.auth import LoginRequest
from eom_api_contracts.common import ArtifactPointer
from eom_api_contracts.control_plane import CreateExecutionPresetDraftRequest
from eom_api_contracts.knowledge_analysis import (
    CreateKnowledgeAnalysisRequest,
    KnowledgeAnalysisReviewRequest,
)
from eom_api_contracts.knowledge_retrieval import CreateEvidenceBundleRequest
from eom_api_contracts.operators import CreateOperatorRequest
from eom_api_contracts.workflows import (
    WorkflowKnowledgeProvenanceView,
    WorkflowStartRequest,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "api" / "v1"


def test_api_json_schemas_are_draft_2020_12() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    assert schemas
    for path in schemas:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(document)


def test_request_contracts_forbid_unknown_fields_and_redact_secrets() -> None:
    login = LoginRequest(
        username="admin",
        password="TEST_ONLY valid password 42",
        client_name="contract-test",
    )
    assert "TEST_ONLY valid password 42" not in repr(login)
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {
                "username": "admin",
                "password": "TEST_ONLY valid password 42",
                "client_name": "contract-test",
                "unknown": True,
            }
        )


def test_operator_contract_never_serializes_temporary_password() -> None:
    request = CreateOperatorRequest(
        username="review01",
        display_name="검토자",
        temporary_password="TEST_ONLY temporary password 42",
        initial_roles=("REVIEWER",),
    )
    assert "TEST_ONLY temporary password 42" not in request.model_dump_json()


def test_pack_pinned_workflow_requires_valid_source_intake_pointer() -> None:
    base = {
        "definition_key": "generic-item-development",
        "definition_version": "1.1.0",
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
        "pack_key": "generic-placeholder",
    }
    with pytest.raises(ValidationError, match="source intake batch"):
        WorkflowStartRequest.model_validate({**base, "source_intake_batch_ids": []})
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate({**base, "source_intake_batch_ids": ["not-an-intake"]})
    value = WorkflowStartRequest.model_validate(
        {**base, "source_intake_batch_ids": ["intake_" + "0" * 32]}
    )
    assert value.source_intake_batch_ids == ("intake_" + "0" * 32,)


def test_knowledge_item_workflow_is_source_optional_but_template_constrained() -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": "1.2.0",
        "request_name": "KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "general-knowledge-item",
        "source_intake_batch_ids": [],
        "item_brief": {
            "subject": "일반 과학",
            "topic": "변인 사이의 선형 관계",
            "task_type": "data_interpretation",
            "difficulty": "medium",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "balanced",
            "original_request_sha256": "0" * 64,
        },
        "stimulus_asset_key": "eom-question-template-reference-v1",
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.source_intake_batch_ids == ()
    assert parsed.item_brief is not None and parsed.item_brief.choice_count == 5
    with pytest.raises(ValidationError, match="fixed workflow contract"):
        WorkflowStartRequest.model_validate(request | {"image_mode": "skip"})


@pytest.mark.parametrize("definition_version", ["1.3.0", "1.4.0", "1.5.0"])
def test_generated_item_workflow_requires_image_role_without_a_prebuilt_stimulus(
    definition_version: str,
) -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": definition_version,
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "source_intake_batch_ids": [],
        "item_brief": {
            "subject": "일반 과학",
            "topic": "변인 사이의 선형 관계",
            "task_type": "data_interpretation",
            "difficulty": "medium",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "balanced",
            "original_request_sha256": "0" * 64,
        },
        "stimulus_asset_key": None,
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.pack_key == "generated-knowledge-item"
    assert parsed.stimulus_asset_key is None
    with pytest.raises(ValidationError, match="generated item request"):
        WorkflowStartRequest.model_validate(
            request | {"source_intake_batch_ids": ["intake_" + "1" * 32]}
        )
    with pytest.raises(ValidationError, match="generated item request"):
        WorkflowStartRequest.model_validate(
            request | {"stimulus_asset_key": "eom-question-template-reference-v1"}
        )


def test_generated_item_accepts_bounded_educational_intent_not_graph_controls() -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": "1.5.0",
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "execution_preset_key": "knowledge-grounded-item",
        "item_brief": {
            "subject": "통합과학",
            "topic": "판 경계와 지진 자료",
            "task_type": "data_interpretation",
            "difficulty": "hard",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "deep",
            "original_request_sha256": "0" * 64,
        },
        "educational_retrieval": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "science-core",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": "earth.plate-boundary",
            "topic_keys": ["earth.plate-boundary"],
            "required_item_elements": ["statement_set", "table"],
            "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        },
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.educational_retrieval is not None
    assert parsed.educational_retrieval.corpus_key == "science-core"
    with pytest.raises(ValidationError, match="execution preset"):
        WorkflowStartRequest.model_validate(request | {"execution_preset_key": None})
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate(
            request
            | {
                "educational_retrieval": {
                    **request["educational_retrieval"],
                    "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
                }
            }
        )


def test_artifact_pointer_can_pin_one_safe_member_without_exposing_storage_path() -> None:
    pointer = ArtifactPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        artifact_member="source/diagram.png",
        sha256="sha256:" + "3" * 64,
        schema_ref="urn:eom:schema:content-intake-source:1.0",
        media_type="image/png",
        logical_uri="nas://artifacts/artifact_1/rev_2",
    )
    assert pointer.artifact_member == "source/diagram.png"
    with pytest.raises(ValidationError, match="artifact member"):
        ArtifactPointer.model_validate(pointer.model_dump() | {"artifact_member": "../diagram.png"})


def test_workflow_knowledge_provenance_is_pointer_only_and_closed() -> None:
    value = {
        "schema_version": "workflow-knowledge-provenance/1.0",
        "plan_id": "execplan_" + "1" * 32,
        "plan_sha256": "sha256:" + "1" * 64,
        "preset_revision_id": "execpresetrev_" + "2" * 32,
        "corpus_key": "science-core",
        "query_kind": "ITEM_PREPARATION",
        "curriculum_root_key": "earth.plate-boundary",
        "required_item_elements": ["equation", "image", "statement_set", "table"],
        "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        "graph_snapshot_revision_id": "graphrev_" + "3" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "4" * 32,
        "retrieval_request_id": "retrieval_" + "5" * 32,
        "retrieval_request_sha256": "sha256:" + "5" * 64,
        "access_policy_revision_id": "accessrev_" + "6" * 32,
        "access_policy_sha256": "sha256:" + "6" * 64,
        "evidence_manifest_sha256": "sha256:" + "7" * 64,
        "resolved_at": "2026-08-24T04:00:00Z",
    }
    projection = WorkflowKnowledgeProvenanceView.model_validate(value)
    assert projection.evidence_bundle_revision_id == "evidencerev_" + "4" * 32
    with pytest.raises(ValidationError):
        WorkflowKnowledgeProvenanceView.model_validate(
            value | {"context_path": "/srv/eom/private/context.md"}
        )


def test_execution_preset_draft_contract_keeps_v1_and_v2_families_exact() -> None:
    role = {
        "role": "authoring",
        "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
        "instruction_bundle": {
            "bundle_id": "instrbundle_" + "1" * 32,
            "bundle_revision_id": "instrrev_" + "1" * 32,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "1" * 32,
                "artifact_revision_id": "rev_" + "1" * 32,
                "sha256": "sha256:" + "1" * 64,
                "schema_ref": "eom://schemas/workflow/instruction-bundle-manifest/1.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
            },
            "manifest_sha256": "sha256:" + "1" * 64,
        },
        "reference_bundle": None,
        "worker_pool_key": "authoring",
        "timeout_seconds": 1800,
        "sandbox": "read-only",
        "network": "disabled",
    }
    base = {
        "preset_key": "standard-item",
        "display_name": "Standard item",
        "description": "Reviewed fresh-session item policy.",
        "role_policies": [role],
        "capacity_policy_revision_id": "capacityrev_" + "2" * 32,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": ["workflow-role/1.3.0"],
    }
    legacy = CreateExecutionPresetDraftRequest.model_validate(base)
    assert legacy.schema_version == "execution-preset-revision/1.0"
    with pytest.raises(ValidationError, match="cannot declare evidence access"):
        CreateExecutionPresetDraftRequest.model_validate(
            base | {"role_policies": [role | {"evidence_access": "EVIDENCE_CONTEXT"}]}
        )
    retrieval_policy = {
        "access_policy_revision_id": "accessrev_" + "3" * 32,
        "access_policy_sha256": "sha256:" + "3" * 64,
        "allowed_corpus_keys": ["science-core"],
        "allowed_query_kinds": ["ITEM_PREPARATION"],
        "allowed_source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        "maximum_budget": {
            "max_documents": 4,
            "max_item_revisions": 4,
            "max_graph_nodes": 32,
            "max_claims": 16,
            "max_context_tokens": 8000,
        },
    }
    grounded = CreateExecutionPresetDraftRequest.model_validate(
        base
        | {
            "schema_version": "execution-preset-revision/2.0",
            "role_policies": [role | {"evidence_access": "EVIDENCE_CONTEXT"}],
            "retrieval_policy": retrieval_policy,
        }
    )
    assert grounded.retrieval_policy is not None
    with pytest.raises(ValidationError):
        CreateExecutionPresetDraftRequest.model_validate(
            grounded.model_dump(mode="json")
            | {"retrieval_policy": retrieval_policy | {"allowed_corpus_keys": ["/srv/eom/private"]}}
        )


def test_knowledge_analysis_request_is_discriminated_and_retry_is_explicit() -> None:
    request: CreateKnowledgeAnalysisRequest = CreateKnowledgeAnalysisRequest.model_validate(
        {
            "source": {
                "source_kind": "APPROVED_ITEM_REVISION",
                "source_class": "APPROVED_ITEM",
                "item_revision_id": "itemrev_" + "1" * 32,
            },
            "preset_key": "knowledge-analysis",
            "general_knowledge_mode": "DISABLED",
            "risk_policy_revision_id": "analysisriskrev_" + "2" * 32,
            "predecessor_analysis_run_id": "analysisrun_" + "3" * 32,
        }
    )
    assert request.source.source_kind == "APPROVED_ITEM_REVISION"
    assert request.predecessor_analysis_run_id == "analysisrun_" + "3" * 32
    with pytest.raises(ValidationError):
        CreateKnowledgeAnalysisRequest.model_validate(
            request.model_dump(mode="json")
            | {
                "source": {
                    "source_kind": "APPROVED_ITEM_REVISION",
                    "source_class": "TEXTBOOK",
                    "item_revision_id": "itemrev_" + "1" * 32,
                }
            }
        )

    document_request = CreateKnowledgeAnalysisRequest.model_validate(
        {
            "source": {
                "source_kind": "DOCUMENT_REVISION",
                "source_class": "TEXTBOOK",
                "document_revision_id": "edudocrev_" + "4" * 32,
                "first_physical_page": 10,
                "last_physical_page": 12,
                "curriculum_unit_keys": ["1-(1)", "1-(2)"],
            },
            "preset_key": "knowledge-analysis",
            "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
            "risk_policy_revision_id": "analysisriskrev_" + "5" * 32,
            "predecessor_analysis_run_id": None,
        }
    )
    assert document_request.source.source_kind == "DOCUMENT_REVISION"
    assert document_request.source.curriculum_unit_keys == ("1-(1)", "1-(2)")
    with pytest.raises(ValidationError):
        CreateKnowledgeAnalysisRequest.model_validate(
            document_request.model_dump(mode="json")
            | {
                "source": document_request.source.model_dump(mode="json")
                | {"last_physical_page": 42}
            }
        )


def test_knowledge_analysis_review_rejects_unsafe_or_empty_notes() -> None:
    assert KnowledgeAnalysisReviewRequest(decision="APPROVE", notes="Reviewed.").decision == (
        "APPROVE"
    )
    for notes in ("", "unsafe\x00note"):
        with pytest.raises(ValidationError):
            KnowledgeAnalysisReviewRequest(decision="REJECT", notes=notes)


def test_evidence_bundle_request_is_bounded_sorted_and_pointer_only() -> None:
    request = CreateEvidenceBundleRequest.model_validate(
        {
            "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
            "query_kind": "ITEM_PREPARATION",
            "curriculum_scope": None,
            "topic_keys": ["earth.plate-boundary"],
            "target_item_revision_id": None,
            "required_item_elements": [],
            "source_classes": ["TEXTBOOK"],
            "evidence_budget": {
                "max_documents": 4,
                "max_item_revisions": 0,
                "max_graph_nodes": 32,
                "max_claims": 8,
                "max_context_tokens": 4000,
            },
            "access_policy_revision_id": "accessrev_" + "2" * 32,
        }
    )
    assert request.topic_keys == ("earth.plate-boundary",)
    with pytest.raises(ValidationError, match="sorted and unique"):
        CreateEvidenceBundleRequest.model_validate(
            request.model_dump(mode="json") | {"source_classes": ["TEXTBOOK", "CURRICULUM"]}
        )
