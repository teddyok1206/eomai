"""Real disposable Document→analysis→shared Graph→RAG, synthetic model response only.

The reviewed textbook seed uses the existing document applications and curriculum
builder. A per-test corpus key isolates the test, not a production parallel Graph.
No live account/model, production DB, worker auth or production NAS is used.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateEvidenceBundleCommand,
    CreateKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeAnalysisSelection,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisWorkerProposalV6,
    PublishKnowledgeGraphSnapshotCommandV2,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.material_knowledge_analysis import (
    EvidenceBundleManifestV6,
    KnowledgeAnalysisRequestV12,
)
from eom_catalog_service import material_graph_learning
from eom_catalog_service.curriculum_graph_structure import (
    build_integrated_science_structure_manifest,
    integrated_science_curriculum_units,
)
from eom_catalog_service.knowledge_graph_publication_service import KnowledgeGraphPublicationService
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.material_graph_learning import (
    MaterialAnalysisControls,
    MaterialGraphLearningService,
)
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy.orm import Session

from tests.integration import test_knowledge_analysis_service as knowledge
from tests.integration.test_material_knowledge_creation_storage import (
    controls as controls,
)
from tests.integration.test_material_knowledge_creation_storage import (
    coordinator_case as coordinator_case,
)
from tests.integration.test_material_knowledge_creation_storage import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_material_knowledge_creation_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_knowledge_creation_storage import (
    material_knowledge_case as material_knowledge_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ACCESS = "accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9"


def _seed_reviewed_textbook_graph(engine, settings, directory, corpus):
    """Actual immutable licensed-textbook baseline, confined to synthetic fixtures."""
    directory.mkdir()
    source_root = directory / "sources"
    source_root.mkdir()
    units = tuple(
        sorted(
            unit.unit_code
            for unit in integrated_science_curriculum_units()
            if unit.unit_level == "MINOR"
        )
    )
    chunks = units[:16], units[16:32], units[32:]
    _, first = knowledge._document_source(
        engine,
        settings,
        source_root,
        multimodal=True,
        curriculum_unit_keys=tuple(sorted((*chunks[0], *chunks[1]))),
    )
    _, second = knowledge._document_source(
        engine, settings, source_root, multimodal=True, curriculum_unit_keys=chunks[2]
    )
    service = knowledge.KnowledgeAnalysisApplicationService(engine, settings)
    accepted = []
    for index, (document, start, end, codes) in enumerate(
        ((first, 1, 1, chunks[0]), (first, 2, 2, chunks[1]), (second, 1, 2, chunks[2]))
    ):
        run = service.create(
            CreateKnowledgeAnalysisCommand(
                source=EducationalDocumentKnowledgeAnalysisSelection(
                    source_class="TEXTBOOK",
                    document_revision_id=document,
                    first_physical_page=start,
                    last_physical_page=end,
                    curriculum_unit_keys=codes,
                ),
                preset_key="knowledge-analysis",
                general_knowledge_mode="DISABLED",
                risk_policy_revision_id=knowledge.POLICY_ID,
                requested_by=knowledge.OPERATOR_ID,
                idempotency_key="material-seed:" + uuid4().hex,
            )
        )
        with Session(engine) as session:
            request = KnowledgeAnalysisRequestV8.model_validate(
                session.get(KnowledgeAnalysisRunRecord, run.analysis_run_id).canonical_request
            )
        knowledge._complete_proposal(
            engine,
            settings,
            run_id=run.analysis_run_id,
            staging_root=directory / f"proposal-{index}",
            proposal_override=knowledge._proposal(request),
        )
        result = service.reconcile(
            ReconcileKnowledgeAnalysisCommand(
                analysis_run_id=run.analysis_run_id, requested_by=knowledge.OPERATOR_ID
            )
        )
        assert result.state == "ACCEPTED"
        accepted.append(run.analysis_run_id)
    publication = KnowledgeGraphPublicationService(engine, settings)
    with publication.sessions() as session:
        resolved = publication.resolve_accepted_analyses(session, tuple(accepted))
        analyses = tuple(resolved[key].analysis for key in accepted)
    now = datetime.now(UTC)
    structure = build_integrated_science_structure_manifest(
        analyses, reviewed_by_operator_id=knowledge.OPERATOR_ID, created_at=now
    )
    pointer = publication.commit_structure_manifest(structure)
    value = dict(
        schema_version="knowledge-graph-publication/2.0",
        corpus_key=corpus,
        display_name="Synthetic shared material corpus",
        accepted_analysis_run_ids=sorted(accepted),
        structure_manifest=pointer.model_dump(mode="json"),
        expected_current_snapshot_revision_id=None,
        publisher_version="2.0.0",
        published_by_operator_id=knowledge.OPERATOR_ID,
        idempotency_key="material-seed-publish:" + uuid4().hex,
        requested_at=now.isoformat().replace("+00:00", "Z"),
    )
    from eom_identifiers import content_sha256

    created = publication.publish(
        PublishKnowledgeGraphSnapshotCommandV2.model_validate(
            value | dict(request_sha256=content_sha256(value))
        )
    )
    return publication, created, tuple(accepted)


def test_uploaded_explanation_joins_reviewed_graph_and_material_evidence_replays(
    creative_engine, material_knowledge_case, tmp_path, monkeypatch
):
    from eom_identifiers import content_sha256

    case = material_knowledge_case
    corpus = "material-fixture-" + uuid4().hex[:16]
    monkeypatch.setattr(material_graph_learning, "INTEGRATED_SCIENCE_CORPUS_KEY", corpus)
    publication, before, baseline = _seed_reviewed_textbook_graph(
        creative_engine, case.settings, tmp_path / "seed", corpus
    )
    created = case.service.create_material_with_pinned_preset(
        case.command,
        preset_id=case.presets.document.preset_id,
        preset_revision_id=case.presets.document.preset_revision_id,
    )
    with Session(creative_engine) as session:
        request = KnowledgeAnalysisRequestV12.model_validate(
            session.get(KnowledgeAnalysisRunRecord, created.analysis_run_id).canonical_request
        )
    source = request.source.artifact_member
    image = next(
        member
        for member in request.source.materialization_members
        if member.member_kind == "PAGE_IMAGE"
    )
    proposal = KnowledgeAnalysisWorkerProposalV6.model_validate(
        dict(
            schema_version="knowledge-analysis-worker-proposal/6.0",
            analysis_request_id=request.analysis_request_id,
            normalized_markdown="# Synthetic material reading\n",
            anchors=[
                dict(
                    anchor_id="anchor_material_page_1",
                    artifact_revision_id=source.artifact_revision_id,
                    member_path=source.member_path,
                    anchor_kind="PARAGRAPH",
                    locator="physical_page=1;paragraph=1",
                    excerpt_sha256="sha256:" + "c" * 64,
                )
            ],
            nodes=[
                dict(
                    node_id="knode_concept_material_reading",
                    node_type="CONCEPT",
                    stable_key="concept:material-reading",
                    label="material reading",
                    anchor_ids=["anchor_material_page_1"],
                )
            ],
            edges=[],
            claims=[],
            component_observations=[],
            unresolved_ambiguities=[],
            page_image_observations=[
                dict(
                    physical_page=1,
                    image_sha256=image.sha256,
                    observation_state="OBSERVED",
                    anchor_ids=["anchor_material_page_1"],
                )
            ],
            general_knowledge_used=False,
            completed_at=datetime.now(UTC),
        )
    )
    knowledge._complete_proposal(
        creative_engine,
        case.settings,
        run_id=created.analysis_run_id,
        staging_root=tmp_path / "material-proposal",
        proposal_override=proposal,
    )
    accepted = case.service.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=created.analysis_run_id, requested_by=case.actor
        )
    )
    if accepted.state == "NEEDS_REVIEW":
        accepted = case.service.accept_validated_without_review(
            analysis_run_id=created.analysis_run_id, requested_by=case.actor
        )
    assert accepted.state == "ACCEPTED"
    graph = MaterialGraphLearningService(
        creative_engine,
        settings=case.settings,
        controls=MaterialAnalysisControls(
            case.presets.item,
            case.presets.document,
            case.presets.solution,
            knowledge.POLICY_ID,
            ACCESS,
        ),
    )
    after = graph.publish_document(analysis_run_id=created.analysis_run_id, operator_id=case.actor)
    assert after != before.graph_snapshot.graph_snapshot_revision_id
    assert (
        graph.publish_document(analysis_run_id=created.analysis_run_id, operator_id=case.actor)
        == after
    )
    current = publication.current_structure_context(corpus)
    assert set(current.accepted_analysis_run_ids) == {*baseline, created.analysis_run_id}
    previous = publication.structure_context_for_snapshot(
        before.graph_snapshot.graph_snapshot_revision_id
    )
    assert set(previous.accepted_analysis_run_ids) == set(baseline)
    assert previous.structure.schema_version == "knowledge-graph-structure-manifest/2.0"
    assert current.structure.schema_version == previous.structure.schema_version
    value = dict(
        operation="CREATE_EVIDENCE_BUNDLE",
        graph_snapshot_revision_id=after,
        query_kind="ITEM_PREPARATION",
        curriculum_scope=None,
        topic_keys=["material-reading"],
        target_item_revision_id=None,
        required_item_elements=[],
        source_classes=["INTERNAL_GUIDE"],
        evidence_budget=dict(
            max_documents=2,
            max_item_revisions=0,
            max_graph_nodes=8,
            max_claims=2,
            max_context_tokens=2000,
        ),
        access_policy_revision_id=ACCESS,
        requester_role="ADMIN",
        requester_permission_keys=["knowledge_graph:read", "knowledge_graph:retrieve"],
        requested_by=case.actor,
        idempotency_key="material-evidence:" + uuid4().hex,
    )
    command = CreateEvidenceBundleCommand.model_validate(
        value
        | dict(
            submission_sha256=content_sha256(
                {key: child for key, child in value.items() if key != "idempotency_key"}
            )
        )
    )
    retrieval = KnowledgeRetrievalApplicationService(creative_engine, case.settings)
    evidence = retrieval.create_material_evidence(command)
    assert evidence.schema_version == "evidence-bundle-publication-result/6.0"
    assert retrieval.create_material_evidence(command) == evidence
    pointer = evidence.manifest_artifact
    manifest = EvidenceBundleManifestV6.model_validate_json(
        publication.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=2 * 1024 * 1024,
        )
    )
    assert len(manifest.entries) == 1
    assert manifest.entries[0].source == request.source
