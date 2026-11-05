"""Uploaded source pointers stay distinct from licensed single-Artifact textbooks."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    EducationalDocumentKnowledgeSourceV4,
    KnowledgeAnalysisWorkerProposalV6,
    KnowledgeArtifactMemberPointer,
)
from eom_catalog_contracts.material_knowledge_analysis import (
    CreateMaterialKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeSourceV5,
    KnowledgeAnalysisProposalReceiptV11,
    KnowledgeAnalysisRequestV12,
    KnowledgeGraphSnapshotManifestV10,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    build_education_graph_projection,
    serialize_education_graph_projection,
)
from eom_catalog_service.knowledge_proposal_resolution import resolve_knowledge_analysis_proposal
from eom_identifiers import content_sha256
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ResolvedExecutionPlanV34
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.models import KnowledgeAnalysisProposalRoleResultV12
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    result_schema_protocol,
    validate_codex_structured_output_schema,
    validate_role_input,
    validate_role_result,
)
from pydantic import ValidationError

from tests.unit.test_knowledge_analysis_document_contracts import (
    multimodal_document_source,
    request_v8,
    stable_identity_proposal,
)
from tests.unit.test_material_learning_contracts import member, unit
from tests.unit.test_material_learning_role_contracts import material_plan, worker_input


def source():
    value = multimodal_document_source()
    values = [
        entry for entry in value["materialization_members"] if entry["member_kind"] != "INDEX"
    ]
    chunks = {}
    for entry in values:
        page = entry["physical_page"]
        seed = str(page + 2)
        entry["artifact_id"], entry["artifact_revision_id"] = (
            "artifact_" + seed * 32,
            "rev_" + seed * 32,
        )
        if entry["member_kind"] == "PAGE_TEXT":
            entry["media_type"] = "text/markdown"
            entry["schema_ref"] = "eom://schemas/material-learning/page-text/1.0"
        pointer = member(
            "analysis/chunk.json", "application/json", "material-learning/page-chunk/1.0"
        )
        pointer.update(
            artifact_id=entry["artifact_id"], artifact_revision_id=entry["artifact_revision_id"]
        )
        chunks[page] = pointer
    value.update(
        source_profile="UPLOADED_MATERIAL_V1",
        material_id="material_" + "1" * 32,
        material_revision_id="materialrev_" + "2" * 32,
        source_role="MAIN",
        document_manifest=member(
            "document/document-revision.json",
            "application/json",
            "material-learning/document-revision/1.0",
        ),
        original_source={
            key: item for key, item in value["artifact_member"].items() if key != "logical_name"
        },
        selected_regions=[unit("EXPLANATION", page=1)["anchors"][0]],
        chunk_manifests=list(chunks.values()),
        materialization_members=values,
        materialization_bytes=sum(entry["bytes"] for entry in values),
    )
    value["analysis_bundle_manifest"]["schema_ref"] = (
        "eom://schemas/material-learning/page-bundle/1.0"
    )
    value["rights_attestation"]["schema_ref"] = "eom://schemas/material-learning/rights/1.0"
    return value


def analysis_request():
    value = request_v8()
    value.update(
        schema_version="knowledge-analysis-request/12.0",
        source=source(),
        accepted_result_schema_ref="eom://schemas/knowledge/knowledge-analysis-result/12.0",
    )
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return value


def test_create_command_preserves_regions_and_is_not_a_textbook_purchase():
    selected = source()
    selection = {
        key: selected[key]
        for key in (
            "source_kind",
            "source_class",
            "document_revision_id",
            "first_physical_page",
            "last_physical_page",
            "selected_regions",
            "curriculum_unit_keys",
        )
    }
    command = CreateMaterialKnowledgeAnalysisCommand.model_validate(
        {
            "source": selection,
            "preset_key": "material-knowledge-analysis",
            "risk_policy_revision_id": "analysisriskrev_" + "a" * 32,
            "requested_by": "operator_" + "b" * 32,
            "idempotency_key": "material-analysis:unit-example",
        }
    )
    assert command.source.selected_regions[0].source_role == "MAIN"
    assert command.general_knowledge_mode == "DISABLED"
    bad = command.model_dump(mode="json")
    bad["source"]["selected_regions"][0]["physical_page"] = 99
    with pytest.raises(ValidationError):
        CreateMaterialKnowledgeAnalysisCommand.model_validate(bad)


def test_material_proposal_uses_same_stable_nodes_and_exact_new_receipt(tmp_path):
    request = KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    proposal = KnowledgeAnalysisWorkerProposalV6.model_validate(stable_identity_proposal(request))
    staged, receipt = stage_knowledge_analysis_proposal(
        proposal=proposal,
        request=request,
        job_id="job_" + "1" * 32,
        logical_artifact_id="artifact_" + "2" * 32,
        revision_id="rev_" + "3" * 32,
        staging=tmp_path,
    )
    assert isinstance(receipt, KnowledgeAnalysisProposalReceiptV11)
    assert receipt.source == request.source
    assert receipt.counts.nodes == len(proposal.nodes)

    class StagedReader:
        def read_member(self, **pointer):
            payload = (staged.directory / pointer["member_path"]).read_bytes()
            assert len(payload) == pointer["max_bytes"]
            return payload

    restored = resolve_knowledge_analysis_proposal(StagedReader(), receipt)
    assert restored == proposal


def test_uploaded_explanation_projects_through_existing_graph_identity_owner():
    request = KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    proposal = KnowledgeAnalysisWorkerProposalV6.model_validate(stable_identity_proposal(request))
    analysis = AcceptedAnalysisProposal(
        analysis_run_id="analysisrun_" + "4" * 32,
        source=request.source,
        accepted_result=KnowledgeArtifactMemberPointer(
            artifact_id="artifact_" + "5" * 32,
            artifact_revision_id="rev_" + "6" * 32,
            sha256="sha256:" + "7" * 64,
            media_type="application/json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/12.0",
            logical_name="accepted-result.json",
            member_path="evidence/accepted-result.json",
        ),
        proposal=proposal,
    )
    projection = build_education_graph_projection((analysis,), None)
    assert len(projection.nodes) == len(proposal.nodes)
    for node in projection.nodes:
        for pointer in node.source_pointers:
            assert pointer.source_kind == "DOCUMENT_REVISION"
            assert pointer.source_revision_id == request.source.document_revision_id
    serialized = serialize_education_graph_projection(projection)
    assert serialized.members["projections/nodes.jsonl"]


def test_shared_snapshot_keeps_uploaded_source_without_licensed_textbook_coercion():
    def pointer(path, media="application/x-ndjson"):
        return dict(
            artifact_id="artifact_" + "8" * 32,
            artifact_revision_id="rev_" + "8" * 32,
            sha256="sha256:" + "8" * 64,
            schema_ref="eom://schemas/knowledge/knowledge-graph-projection/4.0",
            media_type=media,
            logical_name=Path(path).name,
            member_path=path,
        )

    structure = pointer("evidence/graph-structure-manifest.json", "application/json")
    structure["schema_ref"] = "eom://schemas/knowledge/knowledge-graph-structure-manifest/6.0"
    value = dict(
        graph_id="graph_" + "7" * 32,
        graph_snapshot_revision_id="graphrev_" + "8" * 32,
        revision_number=1,
        previous_graph_snapshot_revision_id=None,
        publisher_version="1.8.0",
        source_revisions=[source()],
        analysis_results=[pointer("evidence/accepted-result.json", "application/json")],
        structure_manifest=structure,
        projections={
            "nodes": pointer("projections/nodes.jsonl"),
            "edges": pointer("projections/edges.jsonl"),
            "curriculum_closure": pointer("projections/curriculum-closure.jsonl"),
            "markdown": pointer("projections/graph.md", "text/markdown"),
            "lexical_index": pointer("projections/lexical-index.json", "application/json"),
        },
        counts=dict(source_revisions=1, nodes=2, edges=1, anchors=1),
        snapshot_sha256="sha256:" + "9" * 64,
        created_at="2026-11-05T22:00:00Z",
    )
    parsed = KnowledgeGraphSnapshotManifestV10.model_validate(value)
    assert parsed.source_revisions[0].source_profile == "UPLOADED_MATERIAL_V1"
    bad = parsed.model_dump(mode="json")
    bad["source_revisions"].append(bad["source_revisions"][0])
    bad["counts"]["source_revisions"] = 2
    with pytest.raises(ValueError, match="unique"):
        KnowledgeGraphSnapshotManifestV10.model_validate(bad)


def test_multichunk_source_preserves_actual_schema_and_original_pdf():
    parsed = EducationalDocumentKnowledgeSourceV5.model_validate(source())
    assert len(parsed.chunk_manifests) == 2
    assert {member.media_type for member in parsed.materialization_members} == {
        "text/markdown",
        "image/png",
    }
    with pytest.raises(ValidationError):
        EducationalDocumentKnowledgeSourceV4.model_validate(parsed.model_dump(mode="json"))


@pytest.mark.parametrize(
    "case",
    ["charset", "foreign_chunk", "missing_page", "mixed_role", "old_rights", "duplicate_chunk"],
)
def test_source_rejects_lost_provenance_or_fake_old_bundle(case):
    value = source()
    if case == "charset":
        value["materialization_members"][0]["media_type"] = "text/markdown; charset=utf-8"
    elif case == "foreign_chunk":
        value["materialization_members"][0]["artifact_revision_id"] = "rev_" + "0" * 32
    elif case == "missing_page":
        value["materialization_members"].pop()
        value["materialization_bytes"] = sum(
            member["bytes"] for member in value["materialization_members"]
        )
    elif case == "mixed_role":
        value["selected_regions"][0]["source_role"] = "SOLUTIONS"
    elif case == "old_rights":
        value["rights_attestation"]["schema_ref"] = (
            "eom://schemas/educational-document/rights-attestation/1.0"
        )
    else:
        value["chunk_manifests"].append(deepcopy(value["chunk_manifests"][0]))
    with pytest.raises((ValueError, ValidationError)):
        EducationalDocumentKnowledgeSourceV5.model_validate(value)


def test_new_request_reuses_exact_stable_proposal_and_full_page_outputs():
    parsed = KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    assert parsed.worker_proposal_schema_ref.endswith("worker-proposal/6.0")
    assert len(parsed.requested_outputs) == 8
    changed = analysis_request()
    changed["source"]["source_class"] = "INTERNAL_GUIDE"
    with pytest.raises(ValueError, match="hash"):
        KnowledgeAnalysisRequestV12.model_validate(changed)


def test_new_knowledge_role_and_codex_schema_bind_the_actual_pages_and_proposal():
    request = KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    raw = worker_input()
    raw.update(
        protocol_version="workflow-role/1.38.0",
        request={
            "request_name": "KNOWLEDGE_ANALYSIS_REQUEST",
            "analysis_request": request.model_dump(mode="json"),
        },
    )
    parsed = validate_role_input(raw, "support", "workflow-role/1.38.0")
    projected = constrained_result_schema("knowledge-analysis-proposal-result@12.0", parsed)
    validate_codex_structured_output_schema(projected)
    validate_codex_structured_output_schema(
        load_codex_result_schema("knowledge-analysis-proposal-result@12.0")
    )
    proposal = stable_identity_proposal(request)
    result = {
        key: raw[key]
        for key in (
            "schema_version",
            "protocol_version",
            "job_id",
            "workflow_id",
            "step_run_id",
            "role",
            "artifact",
        )
    }
    result.update(status="ok", completed_at="2026-11-05T21:00:00Z", output={"proposal": proposal})
    assert isinstance(
        validate_role_result(result, "support", "knowledge-analysis-proposal-result@12.0"),
        KnowledgeAnalysisProposalRoleResultV12,
    )
    assert (
        result_schema_protocol("knowledge-analysis-proposal-result@12.0") == "workflow-role/1.38.0"
    )
    compiled = compile_definition(
        Path(__file__).resolve().parents[2] / "config/workflows/knowledge-analysis.v12.yaml",
        {"support"},
    )
    assert compiled.definition.definition_version == "12.0.0"


def knowledge_plan():
    request = KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    value = material_plan()
    value.pop("work_input")
    value.update(
        schema_version="resolved-execution-plan/34.0",
        workflow_definition_key="knowledge-analysis",
        workflow_definition_version="12.0.0",
        resolver_version="34.0.0",
        analysis_request_id=request.analysis_request_id,
        analysis_request_sha256=request.request_sha256,
        document_source=request.source.model_dump(mode="json"),
        preset_id=request.execution_preset_id,
        preset_revision_id=request.execution_preset_revision_id,
        preset_sha256=request.execution_preset_sha256,
    )
    value["steps"][0]["step_key"] = "analyze"
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def test_new_material_knowledge_plan_has_an_exact_source_only_successor():
    request = KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    value = knowledge_plan()
    validate_control_contract("resolved-execution-plan-v34", value)
    assert ResolvedExecutionPlanV34.model_validate(value).document_source == request.source
