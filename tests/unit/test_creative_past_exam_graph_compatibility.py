"""Mixed historical and creative sources retain one Graph format and identity space."""

import json
from dataclasses import dataclass, replace

import pytest
from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    AssessmentOccurrenceItemBinding,
    AutomaticItemCurriculumAlignmentBinding,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeGraphStructureManifestV5,
    validate_contract,
)
from eom_catalog_service.curriculum_graph_structure import (
    CurriculumGraphStructureError,
    build_integrated_science_structure_manifest,
    extend_integrated_science_structure_manifest_with_automatic_item_alignments,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    EducationGraphProjection,
    KnowledgeGraphProjectionError,
    KnowledgeNodeIdentityPolicy,
    build_education_graph_projection,
    serialize_education_graph_projection,
)
from eom_identifiers import content_sha256

from tests.unit.test_curriculum_graph_structure import (
    NOW,
    OPERATOR_ID,
    _approved_item_analysis,
    _assessment_placement,
    _automatic_item_alignment,
    _complete_analyses,
)


def _item(ordinal: int, *, past_exam: bool) -> AcceptedAnalysisProposal:
    template = _approved_item_analysis()
    identity = f"{ordinal:032x}"
    source_value = template.source.model_dump(mode="json")
    source_value.update(
        source_class="PAST_EXAM" if past_exam else "APPROVED_ITEM",
        item_id="item_" + identity,
        item_revision_id="itemrev_" + identity,
    )
    source_value["artifact_member"].update(
        artifact_id="artifact_" + identity,
        artifact_revision_id="rev_" + identity,
    )
    source = ApprovedItemKnowledgeSourceV2.model_validate(source_value)
    proposal_value = template.proposal.model_dump(mode="json")
    proposal_value["analysis_request_id"] = "knowledgeanalysis_" + identity
    proposal_value["anchors"][0]["artifact_revision_id"] = (
        source.artifact_member.artifact_revision_id
    )
    proposal_value["nodes"][0].update(
        stable_key="concept.integrated-science", label="통합과학 개념"
    )
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(proposal_value)
    accepted_value = template.accepted_result.model_dump(mode="json")
    accepted_value.update(
        artifact_id="artifact_" + identity,
        artifact_revision_id="rev_" + identity,
        schema_ref=(
            "eom://schemas/knowledge/knowledge-analysis-result/9.0"
            if past_exam
            else "eom://schemas/knowledge/knowledge-analysis-result/2.0"
        ),
    )
    return AcceptedAnalysisProposal(
        analysis_run_id="analysisrun_" + identity,
        source=source,
        accepted_result=type(template.accepted_result).model_validate(accepted_value),
        proposal=proposal,
    )


def _placement(
    analysis: AcceptedAnalysisProposal, ordinal: int, unit: str
) -> AssessmentOccurrenceItemBinding:
    value = _assessment_placement(analysis, unit).model_dump(mode="json")
    identity, occurrence = f"{ordinal:032x}", f"{(ordinal - 1) // 25:032x}"
    value.update(
        item_origin_profile_id="originprofile_" + identity,
        extraction_acceptance_id="itemacceptance_" + identity,
        assessment_occurrence_id="occurrence_" + occurrence,
        assessment_occurrence_revision_id="occurrev_" + occurrence,
        item_number=(ordinal - 1) % 25 + 1,
    )
    value["placement_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "placement_sha256"}
    )
    return AssessmentOccurrenceItemBinding.model_validate(value)


def _alignment(
    analysis: AcceptedAnalysisProposal, unit: str
) -> AutomaticItemCurriculumAlignmentBinding:
    # The old human-reviewed fixture accepts only result/2.0. The production
    # automatic binding supports both exact result/2.0 and visual result/9.0.
    value = _automatic_item_alignment(_approved_item_analysis(), unit).model_dump(mode="json")
    assert isinstance(analysis.source, ApprovedItemKnowledgeSourceV2)
    value.update(
        analysis_run_id=analysis.analysis_run_id,
        item_id=analysis.source.item_id,
        item_revision_id=analysis.source.item_revision_id,
        accepted_result=analysis.accepted_result.model_dump(mode="json"),
    )
    value["alignment_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "alignment_sha256"}
    )
    return AutomaticItemCurriculumAlignmentBinding.model_validate(value)


@dataclass(frozen=True)
class MixedCase:
    baseline: EducationGraphProjection
    extended: EducationGraphProjection
    structure: KnowledgeGraphStructureManifestV5
    creative: AcceptedAnalysisProposal


@pytest.fixture(scope="module", params=tuple(KnowledgeNodeIdentityPolicy))
def mixed(request: pytest.FixtureRequest) -> MixedCase:
    documents = _complete_analyses()
    base = build_integrated_science_structure_manifest(
        documents, reviewed_by_operator_id=OPERATOR_ID, created_at=NOW
    )
    unit = next(u.curriculum_unit_id for u in base.curriculum_units if u.unit_level == "MINOR")
    past = tuple(_item(n, past_exam=True) for n in range(1, 521))
    previous = extend_integrated_science_structure_manifest_with_automatic_item_alignments(
        base,
        tuple(_alignment(a, unit) for a in past),
        created_at=NOW,
        assessment_item_occurrences=tuple(_placement(a, n, unit) for n, a in enumerate(past, 1)),
    )
    assert isinstance(previous, KnowledgeGraphStructureManifestV5)
    ordered = tuple(sorted((*documents, *past), key=lambda a: a.analysis_run_id))
    baseline = build_education_graph_projection(ordered, previous)
    creative = _item(521, past_exam=False)
    structure = extend_integrated_science_structure_manifest_with_automatic_item_alignments(
        previous, (_alignment(creative, unit),), created_at=NOW
    )
    assert isinstance(structure, KnowledgeGraphStructureManifestV5)
    extended = build_education_graph_projection(
        tuple(sorted((*ordered, creative), key=lambda a: a.analysis_run_id)),
        structure,
        node_identity_policy=request.param,
    )
    return MixedCase(baseline, extended, structure, creative)


def test_520_past_exam_sources_and_creative_share_ontology_without_rekeying(
    mixed: MixedCase,
) -> None:
    assert mixed.baseline.projection_schema_version == mixed.extended.projection_schema_version
    old = {n.node_id: n for n in mixed.baseline.nodes}
    new = {n.node_id: n for n in mixed.extended.nodes}
    assert old.keys() <= new.keys()
    for identity, node in old.items():
        assert (node.node_type, node.stable_key) == (
            new[identity].node_type,
            new[identity].stable_key,
        )
        assert set(node.source_pointers) <= set(new[identity].source_pointers)
    old_edges = {e.edge_id: e for e in mixed.baseline.edges}
    new_edges = {e.edge_id: e for e in mixed.extended.edges}
    assert old_edges.keys() <= new_edges.keys()
    for identity, edge in old_edges.items():
        assert (edge.edge_type, edge.from_node_id, edge.to_node_id) == (
            new_edges[identity].edge_type,
            new_edges[identity].from_node_id,
            new_edges[identity].to_node_id,
        )
        assert set(edge.source_pointers) <= set(new_edges[identity].source_pointers)
    concept = next(n for n in new.values() if n.stable_key == "concept.integrated-science")
    assert {p.source_class for p in concept.source_pointers} == {
        "PAST_EXAM",
        "TEXTBOOK",
        "APPROVED_ITEM",
    }
    assert (
        len({p.analysis_run_id for p in concept.source_pointers if p.source_class == "PAST_EXAM"})
        == 520
    )
    creative = [p for p in concept.source_pointers if p.source_class == "APPROVED_ITEM"]
    assert len(creative) == 1
    assert isinstance(mixed.creative.source, ApprovedItemKnowledgeSourceV2)
    assert creative[0].source_revision_id == mixed.creative.source.item_revision_id
    assert creative[0].source_sha256 == mixed.creative.source.artifact_member.sha256


def test_creative_does_not_acquire_a_fabricated_past_exam_occurrence(mixed: MixedCase) -> None:
    assert len(mixed.structure.assessment_item_occurrences) == 520
    assert mixed.creative.analysis_run_id not in {
        p.analysis_run_id for p in mixed.structure.assessment_item_occurrences
    }
    old_occurrences = {
        n.node_id
        for n in mixed.baseline.nodes
        if n.node_type in {"ASSESSMENT_ITEM_OCCURRENCE", "ASSESSMENT_OCCURRENCE_REVISION"}
    }
    assert old_occurrences == {
        n.node_id
        for n in mixed.extended.nodes
        if n.node_type in {"ASSESSMENT_ITEM_OCCURRENCE", "ASSESSMENT_OCCURRENCE_REVISION"}
    }
    for node in mixed.extended.nodes:
        if node.node_id in old_occurrences:
            assert all(p.source_class == "PAST_EXAM" for p in node.source_pointers)


def test_mixed_projection_keeps_canonical_serialization_and_the_existing_schema(
    mixed: MixedCase,
) -> None:
    result = serialize_education_graph_projection(mixed.extended)
    assert result == serialize_education_graph_projection(mixed.extended)
    for member in ("projections/nodes.jsonl", "projections/edges.jsonl"):
        assert result.metadata[member]["schema_ref"] == (
            "eom://schemas/knowledge/knowledge-graph-projection/4.0"
        )
        for line in result.members[member].splitlines():
            validate_contract("knowledge-graph-projection-v4", json.loads(line))


def test_duplicate_creative_source_and_incompatible_node_type_are_rejected(
    mixed: MixedCase,
) -> None:
    alignment = next(
        a
        for a in mixed.structure.automatic_item_curriculum_bindings
        if a.analysis_run_id == mixed.creative.analysis_run_id
    )
    with pytest.raises(CurriculumGraphStructureError, match="duplicate"):
        extend_integrated_science_structure_manifest_with_automatic_item_alignments(
            mixed.structure, (alignment,), created_at=NOW
        )
    # Simulate an invalid stored proposal bypassing its input validator: the common
    # projector must still reject a shared stable key with a conflicting node type.
    nodes = list(mixed.creative.proposal.nodes)
    nodes[0] = nodes[0].model_copy(update={"node_type": "CLAIM"})
    bad = replace(
        mixed.creative,
        proposal=mixed.creative.proposal.model_copy(update={"nodes": tuple(nodes)}),
    )
    analyses = tuple(
        bad if a.analysis_run_id == bad.analysis_run_id else a for a in mixed.extended.analyses
    )
    with pytest.raises(KnowledgeGraphProjectionError, match="conflicting type"):
        build_education_graph_projection(analyses, mixed.structure)
