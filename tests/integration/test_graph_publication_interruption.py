"""Owner handoff reuses accepted analysis across Graph commit/response interruption."""

from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisRequestV2,
    PublishKnowledgeGraphSnapshotCommand,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_publication_service import KnowledgeGraphPublicationService
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from tests.integration.test_knowledge_analysis_service import (
    NOW,
    OPERATOR_ID,
    _command,
    _complete_proposal,
    _ensure_dependencies,
    _proposal_with_edge,
    _settings,
    _source,
)

pytestmark = pytest.mark.integration


class PublicationInterrupted(RuntimeError):
    pass


@pytest.mark.parametrize(
    "stage", ["before_artifact", "before_database", "before_commit", "after_commit"]
)
def test_graph_publication_interruption_reuses_analysis_and_exact_publication(
    integration_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    intake_id, source_file_id = _source(integration_engine, catalog_settings, tmp_path)
    analysis = KnowledgeAnalysisApplicationService(integration_engine, catalog_settings)
    created = analysis.create(
        _command(intake_id, source_file_id, source_class="TEXTBOOK", idempotency_key=uuid4().hex)
    )
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        run = session.get(KnowledgeAnalysisRunRecord, created.analysis_run_id)
        assert run is not None
        request = KnowledgeAnalysisRequestV2.model_validate(run.canonical_request)
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=created.analysis_run_id,
        staging_root=tmp_path / "proposal",
        proposal_override=_proposal_with_edge(request),
    )
    accepted = analysis.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=created.analysis_run_id, requested_by=OPERATOR_ID
        )
    )
    assert accepted.state == "ACCEPTED"
    with sessions() as session:
        run = session.get(KnowledgeAnalysisRunRecord, created.analysis_run_id)
        assert run is not None and run.platform_job_id is not None
        workflow_id, platform_job_id = run.workflow_id, run.platform_job_id
    value = {
        "schema_version": "knowledge-graph-publication/1.0",
        "corpus_key": "interrupt-" + uuid4().hex[:12],
        "display_name": "Isolated interruption fixture",
        "accepted_analysis_run_ids": [created.analysis_run_id],
        "structure_manifest": None,
        "expected_current_snapshot_revision_id": None,
        "publisher_version": "1.0.0",
        "published_by_operator_id": OPERATOR_ID,
        "idempotency_key": "interrupt:" + uuid4().hex,
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    command = PublishKnowledgeGraphSnapshotCommand.model_validate(
        {**value, "request_sha256": content_sha256(value)}
    )
    owner = KnowledgeGraphPublicationService(integration_engine, catalog_settings)

    def interrupt(*_args, **_kwargs):
        raise PublicationInterrupted(stage)

    def before_commit(session):
        # Other Artifact transactions must finish normally. Interrupt only the
        # publication transaction after all rows have been flushed, before commit.
        if session.scalar(
            select(KnowledgeGraphPublicationRecord.publication_id).where(
                KnowledgeGraphPublicationRecord.idempotency_key == command.idempotency_key
            )
        ):
            interrupt()

    committed = []
    original_commit = owner._commit_database_snapshot

    def after_commit(**kwargs):
        committed.append(original_commit(**kwargs))
        interrupt()

    if stage == "before_commit":
        event.listen(Session, "before_commit", before_commit)
    try:
        with monkeypatch.context() as patch:
            if stage == "before_artifact":
                patch.setattr(owner, "_commit_projection", interrupt)
            elif stage == "before_database":
                patch.setattr(owner, "_commit_database_snapshot", interrupt)
            elif stage == "after_commit":
                patch.setattr(owner, "_commit_database_snapshot", after_commit)
            with pytest.raises(PublicationInterrupted, match=stage):
                owner.publish(command)
    finally:
        if stage == "before_commit":
            event.remove(Session, "before_commit", before_commit)

    def counts(session):
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (KnowledgeAnalysisRunRecord, JobRecord, ArtifactRevisionRecord)
        )

    with sessions() as session:
        publications = session.scalars(
            select(KnowledgeGraphPublicationRecord).where(
                KnowledgeGraphPublicationRecord.idempotency_key == command.idempotency_key
            )
        ).all()
        assert len(publications) == (1 if stage == "after_commit" else 0)
        run = session.get(KnowledgeAnalysisRunRecord, created.analysis_run_id)
        assert run is not None and run.state == "ACCEPTED"
        before_replay = counts(session)
        if stage != "after_commit":
            assert (
                session.scalar(
                    select(KnowledgeCorpusRecord).where(
                        KnowledgeCorpusRecord.corpus_key == command.corpus_key
                    )
                )
                is None
            )

    # A new application instance models the successor owner. It does not submit
    # an analysis/model job or change identity to work around the lost response.
    successor = KnowledgeGraphPublicationService(integration_engine, catalog_settings)
    recovered = successor.publish(command)
    assert recovered.state == "PUBLISHED" and recovered.revision_number == 1
    assert not committed or recovered == committed[0]
    with sessions() as session:
        after_recovery = counts(session)
        assert after_recovery[0] == before_replay[0]
        run = session.get(KnowledgeAnalysisRunRecord, created.analysis_run_id)
        assert run is not None and run.state == "ACCEPTED"
        assert (run.workflow_id, run.platform_job_id) == (workflow_id, platform_job_id)
        if stage != "before_artifact":
            assert after_recovery == before_replay
        snapshot = session.get(
            KnowledgeGraphSnapshotRecord, recovered.graph_snapshot.graph_snapshot_revision_id
        )
        assert snapshot is not None
        membership = session.scalar(
            select(KnowledgeSnapshotAnalysisRecord).where(
                KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                == snapshot.graph_snapshot_revision_id,
                KnowledgeSnapshotAnalysisRecord.analysis_run_id == created.analysis_run_id,
            )
        )
        assert membership is not None
    assert successor.publish(command) == recovered
    with sessions() as session:
        assert counts(session) == after_recovery
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeGraphPublicationRecord)
                .where(KnowledgeGraphPublicationRecord.idempotency_key == command.idempotency_key)
            )
            == 1
        )
