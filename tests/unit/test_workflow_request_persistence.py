import hashlib
from copy import deepcopy

import pytest
from eom_catalog_contracts import ContentTeamMaterialRequirementV1, KnowledgeAnalysisRequestV2
from eom_identifiers import content_sha256
from eom_workflow import ContentTeamItemBriefV4, WorkflowRequest
from eom_workflow.models import ContentPackSelection, RegistryIntent, WorkflowProfiles
from eom_workflow_runner.repository import (
    load_persisted_workflow_request,
    workflow_request_storage_document,
)
from pydantic import ValidationError


def _analysis_request_document() -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "knowledge-analysis-request/2.0",
        "analysis_request_id": "knowledgeanalysis_" + "1" * 32,
        "source": {
            "source_kind": "CONTENT_INTAKE_FILE",
            "source_class": "TEXTBOOK",
            "intake_batch_id": "intake_" + "2" * 32,
            "source_file_id": "sourcefile_" + "3" * 32,
            "lifecycle_state": "ELIGIBLE",
            "artifact_member": {
                "artifact_id": "artifact_" + "4" * 32,
                "artifact_revision_id": "rev_" + "5" * 32,
                "member_path": "source.pdf",
                "materialized_path": "source/source.pdf",
                "sha256": "sha256:" + "6" * 64,
                "bytes": 123,
                "schema_ref": None,
                "media_type": "application/pdf",
                "logical_name": "source.pdf",
            },
        },
        "execution_preset_id": "execpreset_" + "7" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "8" * 32,
        "execution_preset_sha256": "sha256:" + "9" * 64,
        "worker_proposal_schema_ref": (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
        ),
        "accepted_result_schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/2.0",
        "predecessor_analysis_run_id": None,
        "prior_graph_snapshot": None,
        "requested_outputs": [
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
        "general_knowledge_mode": "DISABLED",
        "risk_policy_revision_id": "analysisriskrev_" + "a" * 32,
        "created_at": "2026-08-24T00:00:00Z",
    }
    document["request_sha256"] = content_sha256(document)
    return document


def _workflow_request() -> WorkflowRequest:
    return WorkflowRequest(
        request_name="KNOWLEDGE_ANALYSIS_REQUEST",
        image_mode="skip",
        analysis_request=KnowledgeAnalysisRequestV2.model_validate(_analysis_request_document()),
    )


def _material_workflow_request(*, form: str, panel_count: int | None) -> WorkflowRequest:
    guidance = "검토된 자료 형식을 사용하여 새로운 통합과학 문항을 작성한다."
    guidance_sha256 = hashlib.sha256(guidance.encode("utf-8")).hexdigest()
    return WorkflowRequest(
        request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
        image_mode="required" if form in {"AUTO", "IMAGE", "MIXED"} else "skip",
        content_pack=ContentPackSelection(
            pack_key="generated-knowledge-item",
            environment="development",
        ),
        profiles=WorkflowProfiles(
            authoring="content-team-authoring",
            review="content-team-review",
            image=("generated-stimulus-drawing" if form in {"AUTO", "IMAGE", "MIXED"} else None),
            registration="content-team-registration",
        ),
        registry_intent=RegistryIntent(mode="CREATE_ITEM"),
        item_brief=ContentTeamItemBriefV4(
            subject="통합과학",
            topic="측정 자료 해석",
            task_type=form,
            difficulty="MEDIUM",
            authoring_guidance=guidance,
            authoring_guidance_sha256=f"sha256:{guidance_sha256}",
            original_request_sha256=guidance_sha256,
            material_requirement=ContentTeamMaterialRequirementV1.model_validate(
                {"form": form, "panel_count": panel_count}
            ),
        ),
    )


def test_storage_preserves_schema_required_nullable_analysis_pointers() -> None:
    stored = workflow_request_storage_document(_workflow_request())

    assert "content_pack" not in stored
    assert stored["analysis_request"]["predecessor_analysis_run_id"] is None
    assert stored["analysis_request"]["prior_graph_snapshot"] is None


@pytest.mark.parametrize("form", ["AUTO", "TEXT", "DATA", "INQUIRY"])
def test_storage_preserves_schema_required_nullable_material_panel_count(form: str) -> None:
    stored = workflow_request_storage_document(
        _material_workflow_request(form=form, panel_count=None)
    )

    assert stored["item_brief"]["material_requirement"]["panel_count"] is None
    assert "mock_exam_slot" not in stored["item_brief"]


@pytest.mark.parametrize("form", ["AUTO", "TEXT", "DATA", "INQUIRY"])
def test_loader_recovers_legacy_omitted_nullable_material_panel_count(form: str) -> None:
    stored = workflow_request_storage_document(
        _material_workflow_request(form=form, panel_count=None)
    )
    legacy = deepcopy(stored)
    del legacy["item_brief"]["material_requirement"]["panel_count"]

    loaded = load_persisted_workflow_request(legacy)

    assert isinstance(loaded.item_brief, ContentTeamItemBriefV4)
    assert loaded.item_brief.material_requirement.panel_count is None
    assert workflow_request_storage_document(loaded) == stored


def test_loader_does_not_invent_nonnullable_material_panel_count() -> None:
    stored = workflow_request_storage_document(
        _material_workflow_request(form="TABLE", panel_count=1)
    )
    del stored["item_brief"]["material_requirement"]["panel_count"]

    with pytest.raises(ValidationError, match="panel_count"):
        load_persisted_workflow_request(stored)


def test_text_analysis_workflow_rejects_image_materialization_mode() -> None:
    with pytest.raises(ValidationError, match="matching image mode"):
        WorkflowRequest(
            request_name="KNOWLEDGE_ANALYSIS_REQUEST",
            image_mode="required",
            analysis_request=KnowledgeAnalysisRequestV2.model_validate(
                _analysis_request_document()
            ),
        )


def test_loader_recovers_only_legacy_omitted_nulls_and_revalidates_hash() -> None:
    stored = workflow_request_storage_document(_workflow_request())
    legacy = deepcopy(stored)
    del legacy["analysis_request"]["predecessor_analysis_run_id"]
    del legacy["analysis_request"]["prior_graph_snapshot"]

    loaded = load_persisted_workflow_request(legacy)

    assert loaded.analysis_request is not None
    assert loaded.analysis_request.predecessor_analysis_run_id is None
    assert loaded.analysis_request.prior_graph_snapshot is None
    assert workflow_request_storage_document(loaded) == stored


def test_loader_rejects_legacy_shape_when_canonical_request_hash_is_invalid() -> None:
    legacy = workflow_request_storage_document(_workflow_request())
    del legacy["analysis_request"]["predecessor_analysis_run_id"]
    del legacy["analysis_request"]["prior_graph_snapshot"]
    legacy["analysis_request"]["request_sha256"] = "sha256:" + "f" * 64

    with pytest.raises(ValidationError, match="request hash does not match"):
        load_persisted_workflow_request(legacy)


def test_loader_does_not_relax_missing_nonnullable_analysis_fields() -> None:
    stored = workflow_request_storage_document(_workflow_request())
    del stored["analysis_request"]["risk_policy_revision_id"]

    with pytest.raises(ValidationError, match="risk_policy_revision_id"):
        load_persisted_workflow_request(stored)
