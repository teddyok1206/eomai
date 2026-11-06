"""Same shared Graph/RAG owners, with an explicitly negotiated uploaded source family."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import KnowledgeAnalysisWorkerProposalV6, KnowledgeArtifactMemberPointer
from eom_catalog_contracts.material_knowledge_analysis import (
    EvidenceBundleManifestV6,
    EvidenceEntryV6,
    KnowledgeAnalysisRequestV12,
)
from eom_catalog_service.curriculum_graph_structure import (
    build_integrated_science_structure_manifest,
    extend_integrated_science_structure_with_documents,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    build_education_graph_projection,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalCandidate,
)
from eom_identifiers import content_sha256

from tests.unit.test_curriculum_graph_structure import _complete_analyses
from tests.unit.test_knowledge_analysis_document_contracts import stable_identity_proposal
from tests.unit.test_knowledge_retrieval_service import _request
from tests.unit.test_material_knowledge_contracts import analysis_request
from tests.unit.test_phase9_retrieval_contracts import _manifest_value


def uploaded_analysis():
    request = KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    return AcceptedAnalysisProposal(
        analysis_run_id="analysisrun_" + "f" * 32,
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
        proposal=KnowledgeAnalysisWorkerProposalV6.model_validate(
            stable_identity_proposal(request)
        ),
    )


def test_document_append_keeps_reviewed_framework_and_existing_bindings_immutable():
    previous = _complete_analyses()
    old = previous[0]
    now = datetime(2026, 11, 5, 23, tzinfo=UTC)
    base = build_integrated_science_structure_manifest(
        previous,
        reviewed_by_operator_id="operator_" + "a" * 32,
        created_at=now,
    )
    before = base.model_dump(mode="json")
    new = uploaded_analysis()
    result = extend_integrated_science_structure_with_documents(base, (new,), created_at=now)
    assert base.model_dump(mode="json") == before
    assert result.curriculum_units == base.curriculum_units
    assert result.reviewed_by_operator_id == base.reviewed_by_operator_id
    assert set(result.source_analysis_run_ids) == {
        *base.source_analysis_run_ids,
        new.analysis_run_id,
    }
    projection = build_education_graph_projection((*previous, new), result)
    assert any(
        pointer.analysis_run_id == new.analysis_run_id
        for node in projection.nodes
        for pointer in node.source_pointers
    )
    with pytest.raises(ValueError, match="membership"):
        extend_integrated_science_structure_with_documents(result, (new,), created_at=now)
    duplicate = replace(new, analysis_run_id=old.analysis_run_id)
    with pytest.raises(ValueError, match="membership"):
        extend_integrated_science_structure_with_documents(base, (duplicate,), created_at=now)


def test_uploaded_rag_keeps_actual_document_and_rights_in_explicit_v6_manifest():
    analysis = uploaded_analysis()
    request = _request()
    entry = KnowledgeRetrievalCandidate(
        analysis_run_id=analysis.analysis_run_id,
        source=analysis.source,
        node_ids=("knode_" + "1" * 32,),
        anchor_ids=("anchor_" + "2" * 32,),
        node_labels=("원문에서 분석한 과학 개념",),
        node_types=("CONCEPT",),
        relevance_milli=990,
        answer_bearing=False,
    )
    entries, context = KnowledgeRetrievalApplicationService._rank_and_render(
        request=request,
        candidates=(entry,),
    )
    assert len(entries) == 1 and isinstance(entries[0], EvidenceEntryV6)
    assert entries[0].source == analysis.source
    assert entries[0].use == "GROUNDING" and "원문에서 분석한 과학 개념" in context
    value = _manifest_value(request)
    value.update(
        schema_version="evidence-bundle-manifest/6.0",
        entries=[entry.model_dump(mode="json") for entry in entries],
        budget=dict(
            document_count=1,
            item_revision_count=0,
            graph_node_count=1,
            claim_count=0,
            estimated_context_tokens=400,
        ),
    )
    value["manifest_sha256"] = content_sha256(
        {key: child for key, child in value.items() if key != "manifest_sha256"}
    )
    manifest = EvidenceBundleManifestV6.model_validate(value)
    assert manifest.entries[0].source.rights_attestation == analysis.source.rights_attestation
    assert (
        KnowledgeRetrievalApplicationService._manifest_schema_version(entries)
        == "evidence-bundle-manifest/6.0"
    )
    protocol, _ = KnowledgeRetrievalApplicationService._evidence_publication_profile(
        manifest.schema_version
    )
    assert protocol == "catalog-knowledge-retrieval/1.4"
