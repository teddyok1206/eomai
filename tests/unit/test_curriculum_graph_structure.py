from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from eom_catalog_contracts import (
    EducationalDocumentKnowledgeSourceV4,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphSnapshotManifestV5,
    KnowledgeGraphStructureManifestV2,
    PublishKnowledgeGraphSnapshotCommandV2,
    validate_contract,
)
from eom_catalog_service.curriculum_graph_structure import (
    CurriculumGraphStructureError,
    build_integrated_science_structure_manifest,
    integrated_science_curriculum_units,
    integrated_science_framework_revision_id,
    validate_integrated_science_structure_manifest,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    KnowledgeGraphProjectionError,
    build_education_graph_projection,
    serialize_education_graph_projection,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_SCHEMA_HASH,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError

NOW = datetime(2026, 8, 31, 3, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32


def _hex(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _analysis(code: str, ordinal: int) -> AcceptedAnalysisProposal:
    identity = _hex(f"{code}:{ordinal}")
    artifact_id = "artifact_" + identity[:32]
    revision_id = "rev_" + identity[32:64]
    document_id = "edudoc_" + _hex(f"document:{identity}")[:32]
    document_revision_id = "edudocrev_" + _hex(f"revision:{identity}")[:32]
    source = EducationalDocumentKnowledgeSourceV4.model_validate(
        {
            "source_kind": "DOCUMENT_REVISION",
            "source_class": "TEXTBOOK",
            "document_id": document_id,
            "document_revision_id": document_revision_id,
            "lifecycle_state": "APPROVED",
            "artifact_member": {
                "artifact_id": artifact_id,
                "artifact_revision_id": revision_id,
                "member_path": "source/original.pdf",
                "sha256": "sha256:" + _hex(f"pdf:{identity}"),
                "bytes": 1024,
                "schema_ref": "eom://schemas/educational-document/pdf-source/1.0",
                "media_type": "application/pdf",
                "logical_name": "original.pdf",
            },
            "analysis_bundle_manifest": {
                "artifact_id": artifact_id,
                "artifact_revision_id": revision_id,
                "member_path": "analysis/manifest.json",
                "sha256": "sha256:" + _hex(f"manifest:{identity}"),
                "schema_ref": (
                    "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
                ),
                "media_type": "application/json",
                "logical_name": "manifest.json",
            },
            "rights_attestation": {
                "artifact_id": artifact_id,
                "artifact_revision_id": revision_id,
                "member_path": "rights/attestation.json",
                "sha256": "sha256:" + _hex(f"rights:{identity}"),
                "schema_ref": "eom://schemas/educational-document/rights-attestation/1.0",
                "media_type": "application/json",
                "logical_name": "attestation.json",
            },
            "first_physical_page": 1,
            "last_physical_page": 1,
            "curriculum_unit_keys": [code],
            "materialization_members": [
                {
                    "member_kind": "INDEX",
                    "physical_page": None,
                    "artifact_id": artifact_id,
                    "artifact_revision_id": revision_id,
                    "member_path": "analysis/index.md",
                    "materialized_path": "source/document/index.md",
                    "sha256": "sha256:" + _hex(f"index:{identity}"),
                    "bytes": 10,
                    "schema_ref": ("eom://schemas/educational-document/extracted-markdown/1.0"),
                    "media_type": "text/markdown; charset=utf-8",
                    "logical_name": "index.md",
                    "width_pixels": None,
                    "height_pixels": None,
                },
                {
                    "member_kind": "PAGE_TEXT",
                    "physical_page": 1,
                    "artifact_id": artifact_id,
                    "artifact_revision_id": revision_id,
                    "member_path": "analysis/pages/page-000001.md",
                    "materialized_path": "source/document/pages/page-000001.md",
                    "sha256": "sha256:" + _hex(f"page:{identity}"),
                    "bytes": 20,
                    "schema_ref": ("eom://schemas/educational-document/extracted-markdown/1.0"),
                    "media_type": "text/markdown; charset=utf-8",
                    "logical_name": "page-000001.md",
                    "width_pixels": None,
                    "height_pixels": None,
                },
                {
                    "member_kind": "PAGE_IMAGE",
                    "physical_page": 1,
                    "artifact_id": artifact_id,
                    "artifact_revision_id": revision_id,
                    "member_path": "analysis/images/page-000001.png",
                    "materialized_path": "source/document/images/page-000001.png",
                    "sha256": "sha256:" + _hex(f"image:{identity}"),
                    "bytes": 100,
                    "schema_ref": "eom://schemas/educational-document/page-image/1.0",
                    "media_type": "image/png",
                    "logical_name": "page-000001.png",
                    "width_pixels": 1600,
                    "height_pixels": 2200,
                },
            ],
            "materialization_bytes": 130,
            "page_image_count": 1,
        }
    )
    anchor_id = "anchor_page_1"
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(
        {
            "schema_version": "knowledge-analysis-worker-proposal/1.0",
            "analysis_request_id": "knowledgeanalysis_" + identity[:32],
            "normalized_markdown": "# Reviewed source\n",
            "anchors": [
                {
                    "anchor_id": anchor_id,
                    "artifact_revision_id": revision_id,
                    "member_path": "source/original.pdf",
                    "anchor_kind": "PAGE",
                    "locator": "physical_page=1",
                    "excerpt_sha256": "sha256:" + _hex(f"excerpt:{identity}"),
                }
            ],
            "nodes": [
                {
                    "node_id": "knode_concept",
                    "node_type": "CONCEPT",
                    "stable_key": "concept.integrated-science",
                    "label": "통합과학 개념",
                    "anchor_ids": [anchor_id],
                }
            ],
            "edges": [],
            "claims": [],
            "component_observations": [],
            "unresolved_ambiguities": [],
            "general_knowledge_used": False,
            "completed_at": NOW,
        }
    )
    return AcceptedAnalysisProposal(
        analysis_run_id="analysisrun_" + identity[:32],
        source=source,
        accepted_result=KnowledgeArtifactMemberPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            sha256="sha256:" + _hex(f"accepted:{identity}"),
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/8.0",
            media_type="application/json",
            logical_name="accepted-result.json",
            member_path="evidence/accepted-result.json",
        ),
        proposal=proposal,
    )


def _complete_analyses() -> tuple[AcceptedAnalysisProposal, ...]:
    codes = tuple(
        unit.unit_code
        for unit in integrated_science_curriculum_units()
        if unit.unit_level == "MINOR"
    )
    return tuple(
        sorted(
            (_analysis(code, index) for index, code in enumerate(codes)),
            key=lambda item: item.analysis_run_id,
        )
    )


def test_reviewed_outline_builds_complete_deterministic_structure_and_projection() -> None:
    analyses = _complete_analyses()
    first = build_integrated_science_structure_manifest(
        analyses, reviewed_by_operator_id=OPERATOR_ID, created_at=NOW
    )
    second = build_integrated_science_structure_manifest(
        analyses, reviewed_by_operator_id=OPERATOR_ID, created_at=NOW
    )

    assert first == second
    assert first.framework_revision_id == integrated_science_framework_revision_id()
    assert len(first.curriculum_units) == 43
    assert len(first.analysis_curriculum_bindings) == 35
    validate_integrated_science_structure_manifest(first)
    validate_contract("knowledge-graph-structure-manifest-v2", first.model_dump(mode="json"))

    projection = build_education_graph_projection(analyses, first)
    assert len(projection.nodes) == 44
    assert len(projection.edges) == 76
    assert len(projection.curriculum_units) == 43
    assert len(projection.curriculum_closure) == 119
    assert any(node.label == "물질과 규칙성" for node in projection.nodes)
    assert KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_SCHEMA_HASH == (
        "sha256:741859c2e778560b3fba01e651fcf76e4c894dd5ab630cdcb0f4a475dc7cef60"
    )


def test_reviewed_projection_preserves_worker_label_aliases_and_indexes_them() -> None:
    analyses = list(_complete_analyses())
    proposal = analyses[0].proposal
    nodes = list(proposal.nodes)
    nodes[0] = nodes[0].model_copy(update={"label": "Integrated science concept"})
    analyses[0] = analyses[0].__class__(
        analysis_run_id=analyses[0].analysis_run_id,
        source=analyses[0].source,
        accepted_result=analyses[0].accepted_result,
        proposal=proposal.model_copy(update={"nodes": tuple(nodes)}),
    )
    ordered = tuple(sorted(analyses, key=lambda item: item.analysis_run_id))
    structure = build_integrated_science_structure_manifest(
        ordered, reviewed_by_operator_id=OPERATOR_ID, created_at=NOW
    )

    projection = build_education_graph_projection(ordered, structure)
    concept = next(
        node for node in projection.nodes if node.stable_key == "concept.integrated-science"
    )
    assert concept.label == "통합과학 개념"
    assert concept.aliases == ("Integrated science concept",)

    serialized = serialize_education_graph_projection(projection)
    assert all(
        metadata["schema_ref"] == "eom://schemas/knowledge/knowledge-graph-projection/3.0"
        for path, metadata in serialized.metadata.items()
        if path != "projections/graph.md"
    )
    node_documents = [
        json.loads(line) for line in serialized.members["projections/nodes.jsonl"].splitlines()
    ]
    concept_document = next(
        node for node in node_documents if node["stable_key"] == "concept.integrated-science"
    )
    assert concept_document["aliases"] == ["Integrated science concept"]
    validate_contract("knowledge-graph-projection-v3", concept_document)
    lexical = json.loads(serialized.members["projections/lexical-index.json"])
    validate_contract("knowledge-graph-projection-v3", lexical)
    terms = {entry["term"] for entry in lexical["entries"]}
    assert {"통합과학", "integrated", "science", "concept"}.issubset(terms)


def test_structure_rejects_outline_drift_binding_gaps_and_source_mismatch() -> None:
    analyses = _complete_analyses()
    structure = build_integrated_science_structure_manifest(
        analyses, reviewed_by_operator_id=OPERATOR_ID, created_at=NOW
    )
    forged = structure.model_copy(update={"outline_sha256": "sha256:" + "0" * 64})
    with pytest.raises(CurriculumGraphStructureError):
        validate_integrated_science_structure_manifest(forged)

    missing = structure.model_copy(update={"analysis_curriculum_bindings": ()})
    with pytest.raises(
        KnowledgeGraphProjectionError,
        match="exactly cover classified source ranges",
    ):
        build_education_graph_projection(analyses, missing)

    wrong_source = analyses[0].source.model_copy(update={"curriculum_unit_keys": ("1-(1)",)})
    wrong_analyses = (
        analyses[0].__class__(
            analysis_run_id=analyses[0].analysis_run_id,
            source=wrong_source,
            accepted_result=analyses[0].accepted_result,
            proposal=analyses[0].proposal,
        ),
        *analyses[1:],
    )
    with pytest.raises(KnowledgeGraphProjectionError):
        build_education_graph_projection(
            tuple(sorted(wrong_analyses, key=lambda item: item.analysis_run_id)), structure
        )


def test_structure_model_rejects_nonminor_analysis_target() -> None:
    analyses = _complete_analyses()
    structure = build_integrated_science_structure_manifest(
        analyses, reviewed_by_operator_id=OPERATOR_ID, created_at=NOW
    )
    value = structure.model_dump(mode="json")
    value["analysis_curriculum_bindings"][0]["curriculum_unit_ids"] = [
        next(
            unit.curriculum_unit_id
            for unit in structure.curriculum_units
            if unit.unit_level == "MAJOR"
        )
    ]
    value["manifest_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="MINOR"):
        KnowledgeGraphStructureManifestV2.model_validate(value)


def test_v2_publication_and_v5_snapshot_pin_exact_structure_pointer() -> None:
    analysis = _complete_analyses()[0]
    structure_pointer = KnowledgeArtifactMemberPointer(
        artifact_id="artifact_" + "9" * 32,
        artifact_revision_id="rev_" + "9" * 32,
        sha256="sha256:" + "9" * 64,
        schema_ref="eom://schemas/knowledge/knowledge-graph-structure-manifest/2.0",
        media_type="application/json",
        logical_name="graph-structure-manifest.json",
        member_path="evidence/graph-structure-manifest.json",
    )
    command_value = {
        "schema_version": "knowledge-graph-publication/2.0",
        "corpus_key": "integrated-science-textbooks",
        "display_name": "통합과학 교과서 지식 그래프",
        "accepted_analysis_run_ids": [analysis.analysis_run_id],
        "structure_manifest": structure_pointer.model_dump(mode="json"),
        "expected_current_snapshot_revision_id": None,
        "publisher_version": "2.0.0",
        "published_by_operator_id": OPERATOR_ID,
        "idempotency_key": "curriculum-graph-publication-v2-test",
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "request_sha256": "sha256:" + "0" * 64,
    }
    command_value["request_sha256"] = content_sha256(
        {key: item for key, item in command_value.items() if key != "request_sha256"}
    )
    validate_contract("knowledge-graph-publication-v2", command_value)
    command = PublishKnowledgeGraphSnapshotCommandV2.model_validate(command_value)
    assert command.structure_manifest == structure_pointer

    unsafe_display = {**command_value, "display_name": "검토됨\n지시"}
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("knowledge-graph-publication-v2", unsafe_display)
    with pytest.raises(ValueError, match="control character"):
        PublishKnowledgeGraphSnapshotCommandV2.model_validate(unsafe_display)
    unsafe_key = {**command_value, "idempotency_key": "invalid key with spaces"}
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("knowledge-graph-publication-v2", unsafe_key)

    def pointer(path: str, logical_name: str) -> dict[str, object]:
        return {
            "artifact_id": "artifact_" + "8" * 32,
            "artifact_revision_id": "rev_" + "8" * 32,
            "sha256": "sha256:" + "8" * 64,
            "schema_ref": "eom://schemas/knowledge/knowledge-graph-projection/3.0",
            "media_type": "application/x-ndjson",
            "logical_name": logical_name,
            "member_path": path,
        }

    snapshot_value = {
        "schema_version": "knowledge-graph-snapshot-manifest/5.0",
        "graph_id": "graph_" + "7" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "7" * 32,
        "revision_number": 1,
        "previous_graph_snapshot_revision_id": None,
        "state": "PUBLISHED",
        "ontology_version": "education-knowledge-graph/1.0",
        "publisher_version": "2.0.0",
        "source_revisions": [analysis.source.model_dump(mode="json")],
        "analysis_results": [analysis.accepted_result.model_dump(mode="json")],
        "structure_manifest": structure_pointer.model_dump(mode="json"),
        "projections": {
            "nodes": pointer("projections/nodes.jsonl", "nodes.jsonl"),
            "edges": pointer("projections/edges.jsonl", "edges.jsonl"),
            "curriculum_closure": pointer(
                "projections/curriculum-closure.jsonl", "curriculum-closure.jsonl"
            ),
            "markdown": {
                **pointer("projections/graph.md", "graph.md"),
                "media_type": "text/markdown",
            },
            "lexical_index": {
                **pointer("projections/lexical-index.json", "lexical-index.json"),
                "media_type": "application/json",
            },
        },
        "counts": {"source_revisions": 1, "nodes": 44, "edges": 76, "anchors": 1},
        "snapshot_sha256": "sha256:" + "7" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    validate_contract("knowledge-graph-snapshot-manifest-v5", snapshot_value)
    snapshot = KnowledgeGraphSnapshotManifestV5.model_validate(snapshot_value)
    assert snapshot.structure_manifest == structure_pointer


def test_v5_snapshot_allows_distinct_ranges_of_one_document_revision() -> None:
    analyses = _complete_analyses()[:2]
    second_source = analyses[1].source.model_copy(
        update={
            "document_id": analyses[0].source.document_id,
            "document_revision_id": analyses[0].source.document_revision_id,
            "artifact_member": analyses[0].source.artifact_member,
            "analysis_bundle_manifest": analyses[0].source.analysis_bundle_manifest,
            "rights_attestation": analyses[0].source.rights_attestation,
            "first_physical_page": 2,
            "last_physical_page": 2,
            "materialization_members": tuple(
                member.model_copy(
                    update={
                        "physical_page": (2 if member.physical_page is not None else None),
                        "member_path": (
                            member.member_path.replace("000001", "000002")
                            if member.physical_page is not None
                            else member.member_path
                        ),
                        "materialized_path": (
                            member.materialized_path.replace("000001", "000002")
                            if member.physical_page is not None
                            else member.materialized_path
                        ),
                        "logical_name": (
                            member.logical_name.replace("000001", "000002")
                            if member.physical_page is not None
                            else member.logical_name
                        ),
                    }
                )
                for member in analyses[0].source.materialization_members
            ),
        }
    )
    pointer = KnowledgeArtifactMemberPointer(
        artifact_id="artifact_" + "9" * 32,
        artifact_revision_id="rev_" + "9" * 32,
        sha256="sha256:" + "9" * 64,
        schema_ref="eom://schemas/knowledge/knowledge-graph-structure-manifest/2.0",
        media_type="application/json",
        logical_name="graph-structure-manifest.json",
        member_path="evidence/graph-structure-manifest.json",
    )

    def projection_pointer(path: str, logical_name: str, media_type: str) -> dict[str, object]:
        return {
            "artifact_id": "artifact_" + "8" * 32,
            "artifact_revision_id": "rev_" + "8" * 32,
            "sha256": "sha256:" + "8" * 64,
            "schema_ref": "eom://schemas/knowledge/knowledge-graph-projection/3.0",
            "media_type": media_type,
            "logical_name": logical_name,
            "member_path": path,
        }

    value = {
        "schema_version": "knowledge-graph-snapshot-manifest/5.0",
        "graph_id": "graph_" + "7" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "7" * 32,
        "revision_number": 1,
        "previous_graph_snapshot_revision_id": None,
        "state": "PUBLISHED",
        "ontology_version": "education-knowledge-graph/1.0",
        "publisher_version": "2.0.0",
        "source_revisions": [
            analyses[0].source.model_dump(mode="json"),
            second_source.model_dump(mode="json"),
        ],
        "analysis_results": [
            analyses[0].accepted_result.model_dump(mode="json"),
            analyses[1].accepted_result.model_dump(mode="json"),
        ],
        "structure_manifest": pointer.model_dump(mode="json"),
        "projections": {
            "nodes": projection_pointer(
                "projections/nodes.jsonl", "nodes.jsonl", "application/x-ndjson"
            ),
            "edges": projection_pointer(
                "projections/edges.jsonl", "edges.jsonl", "application/x-ndjson"
            ),
            "curriculum_closure": projection_pointer(
                "projections/curriculum-closure.jsonl",
                "curriculum-closure.jsonl",
                "application/x-ndjson",
            ),
            "markdown": projection_pointer("projections/graph.md", "graph.md", "text/markdown"),
            "lexical_index": projection_pointer(
                "projections/lexical-index.json", "lexical-index.json", "application/json"
            ),
        },
        "counts": {"source_revisions": 2, "nodes": 1, "edges": 0, "anchors": 2},
        "snapshot_sha256": "sha256:" + "7" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    assert len(KnowledgeGraphSnapshotManifestV5.model_validate(value).source_revisions) == 2
    value["source_revisions"][1] = analyses[0].source.model_dump(mode="json")
    with pytest.raises(ValueError, match="source selections"):
        KnowledgeGraphSnapshotManifestV5.model_validate(value)
