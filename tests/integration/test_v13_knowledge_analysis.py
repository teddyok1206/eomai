from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeAnalysisSelection,
    ReconcileKnowledgeAnalysisCommand,
    ReviewKnowledgeAnalysisCommand,
)
from eom_catalog_service.knowledge_analysis_batch_models import (
    KnowledgeAnalysisBatchRangeRecord,
    KnowledgeAnalysisBatchRecord,
)
from eom_catalog_service.knowledge_analysis_batch_service import KnowledgeAnalysisBatchService
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_orchestrator.control_bootstrap import bootstrap_knowledge_analysis_control_plane
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, func, select

from tests.integration.test_knowledge_analysis_batch_service import (
    _make_submitted_range_due,
    _parallel_batch_command,
)
from tests.integration.test_knowledge_analysis_service import (
    OPERATOR_ID,
    POLICY_ID,
    _complete_proposal,
    _document_source,
    _ensure_dependencies,
    _settings,
)

pytestmark = pytest.mark.integration


def test_parallel_batch_reuses_semantically_identical_v12_result_by_pointer(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    _assert_parallel_batch_reuses_semantically_identical_v12_result_by_pointer(
        integration_engine,
        tmp_path,
    )


def test_bounded_parallel_batch_claims_exactly_two_and_accepts_out_of_order(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v13").resolve(),
        source_commit="d" * 40,
        actor_id="parallel-batch-integration",
        evaluation_cases_total=3,
        settings=orchestrator_settings,
    )
    document_revision_id = _document_source(
        integration_engine,
        catalog_settings,
        tmp_path,
        multimodal=True,
    )[1]
    service = KnowledgeAnalysisBatchService(integration_engine, catalog_settings)
    created = service.create(_parallel_batch_command(document_revision_id, range_count=2))
    services = tuple(
        KnowledgeAnalysisBatchService(integration_engine, catalog_settings) for _ in range(3)
    )
    runner_ids = ("parallel-runner-a", "parallel-runner-b", "parallel-runner-c")

    def claim(index: int) -> tuple[str, str] | None:
        return services[index]._claim_next_range(runner_id=runner_ids[index])

    with ThreadPoolExecutor(max_workers=3) as executor:
        claims = tuple(executor.map(claim, range(3)))
    winners = [(index, value) for index, value in enumerate(claims) if value is not None]
    assert 1 <= len(winners) <= 2
    if len(winners) == 1:
        supplemental = services[2]._claim_next_range(runner_id="parallel-runner-supplemental")
        assert supplemental is not None
        winners.append((3, supplemental))
    assert len({claimed[1] for _, claimed in winners if claimed is not None}) == 2
    assert service._claim_next_range(runner_id="parallel-runner-over-capacity") is None
    for index, claimed in winners:
        assert claimed is not None
        runner_id = runner_ids[index] if index < 3 else "parallel-runner-supplemental"
        executor_service = services[index] if index < 3 else services[2]
        executor_service._submit_claimed(*claimed, runner_id=runner_id)

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        ranges = tuple(
            session.scalars(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id)
                .order_by(KnowledgeAnalysisBatchRangeRecord.ordinal)
            )
        )
        assert batch is not None
        assert (batch.scheduling_mode, batch.max_in_flight) == ("BOUNDED_PARALLEL", 2)
        assert tuple(row.state for row in ranges) == ("SUBMITTED", "SUBMITTED")
        assert len({row.analysis_run_id for row in ranges}) == 2
        range_ids = tuple(row.range_id for row in ranges)
        run_ids = tuple(str(row.analysis_run_id) for row in ranges)

    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=run_ids[1],
        staging_root=tmp_path / "parallel-proposal-1",
    )
    _make_submitted_range_due(integration_engine, range_id=range_ids[1])
    assert service.advance_once(runner_id="parallel-runner-finalizer")
    with sessions() as session:
        first = session.get(KnowledgeAnalysisBatchRangeRecord, range_ids[0])
        second = session.get(KnowledgeAnalysisBatchRangeRecord, range_ids[1])
        assert first is not None and first.state == "SUBMITTED"
        assert second is not None and second.state == "ACCEPTED"

    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=run_ids[0],
        staging_root=tmp_path / "parallel-proposal-0",
    )
    _make_submitted_range_due(integration_engine, range_id=range_ids[0])
    assert service.advance_once(runner_id="parallel-runner-finalizer")
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        assert batch is not None and batch.state == "SUCCEEDED"


def test_bounded_parallel_batch_collects_failure_while_sibling_finishes(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v13").resolve(),
        source_commit="e" * 40,
        actor_id="parallel-failure-integration",
        evaluation_cases_total=3,
        settings=orchestrator_settings,
    )
    document_revision_id = _document_source(
        integration_engine,
        catalog_settings,
        tmp_path,
        multimodal=True,
    )[1]
    service = KnowledgeAnalysisBatchService(integration_engine, catalog_settings)
    created = service.create(_parallel_batch_command(document_revision_id, range_count=2))

    claims = tuple(
        service._claim_next_range(runner_id=f"parallel-failure-runner-{index}")
        for index in range(2)
    )
    assert all(claim is not None for claim in claims)
    for index, claim in enumerate(claims):
        assert claim is not None
        service._submit_claimed(
            *claim,
            runner_id=f"parallel-failure-runner-{index}",
        )

    sessions = build_session_factory(integration_engine)
    with transaction(sessions) as session:
        ranges = tuple(
            session.scalars(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id)
                .order_by(KnowledgeAnalysisBatchRangeRecord.ordinal)
            )
        )
        assert len(ranges) == 2
        assert ranges[0].analysis_run_id is not None
        failed_run = session.get(KnowledgeAnalysisRunRecord, ranges[0].analysis_run_id)
        assert failed_run is not None
        failed_run.state = "FAILED"
        failed_run.error_code = "KNOWLEDGE_ANALYSIS_WORKER_FAILED"
        failed_run.completed_at = datetime.now(UTC)
        failed_run.lock_version += 1
        ranges[0].next_action_at = datetime.now(UTC) - timedelta(seconds=1)
        failed_range_id = ranges[0].range_id
        sibling_range_id = ranges[1].range_id
        sibling_run_id = str(ranges[1].analysis_run_id)

    assert service.advance_once(runner_id="parallel-failure-finalizer")
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        failed = session.get(KnowledgeAnalysisBatchRangeRecord, failed_range_id)
        sibling = session.get(KnowledgeAnalysisBatchRangeRecord, sibling_range_id)
        assert batch is not None and batch.state == "RUNNING"
        assert batch.failure_code is None
        assert failed is not None and failed.state == "FAILED"
        assert sibling is not None and sibling.state == "SUBMITTED"

    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=sibling_run_id,
        staging_root=tmp_path / "parallel-failure-sibling-proposal",
    )
    _make_submitted_range_due(integration_engine, range_id=sibling_range_id)
    assert service.advance_once(runner_id="parallel-failure-finalizer")
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        ranges = tuple(
            session.scalars(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id)
                .order_by(KnowledgeAnalysisBatchRangeRecord.ordinal)
            )
        )
        assert batch is not None and batch.state == "BLOCKED"
        assert batch.failure_code == "KNOWLEDGE_ANALYSIS_BATCH_RANGE_FAILURES_COLLECTED"
        assert tuple(row.state for row in ranges) == ("FAILED", "ACCEPTED")
        assert tuple(row.submission_attempts for row in ranges) == (1, 1)


def test_v14_reuses_the_immutable_v13_parallel_capacity_revision(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, _ = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    v13 = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v13").resolve(),
        source_commit="d" * 40,
        actor_id="parallel-v13-integration",
        evaluation_cases_total=3,
        settings=orchestrator_settings,
    )

    v14 = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v14").resolve(),
        source_commit="f" * 40,
        actor_id="page-evidence-v14-integration",
        evaluation_cases_total=3,
        settings=orchestrator_settings,
    )

    assert v14.capacity_policy_revision_id == v13.capacity_policy_revision_id
    assert v14.instruction_bundle_revision_id != v13.instruction_bundle_revision_id
    assert v14.preset_revision_id != v13.preset_revision_id


def _assert_parallel_batch_reuses_semantically_identical_v12_result_by_pointer(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v12").resolve(),
        source_commit="c" * 40,
        actor_id="semantic-reuse-v12-integration",
        evaluation_cases_total=3,
        settings=orchestrator_settings,
    )
    document_revision_id = _document_source(integration_engine, catalog_settings, tmp_path)[1]
    analysis = KnowledgeAnalysisApplicationService(integration_engine, catalog_settings)
    created_run = analysis.create(
        CreateKnowledgeAnalysisCommand(
            source=EducationalDocumentKnowledgeAnalysisSelection(
                source_class="TEXTBOOK",
                document_revision_id=document_revision_id,
                first_physical_page=1,
                last_physical_page=1,
                curriculum_unit_keys=("1-(1)",),
            ),
            preset_key="knowledge-analysis",
            general_knowledge_mode="AUXILIARY_UNATTRIBUTED",
            risk_policy_revision_id=POLICY_ID,
            predecessor_analysis_run_id=None,
            requested_by=OPERATOR_ID,
            idempotency_key=f"semantic-reuse-v12-source:{uuid4().hex}",
        )
    )
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=created_run.analysis_run_id,
        staging_root=tmp_path / "semantic-reuse-v12-proposal",
    )
    accepted = analysis.reconcile(
        ReconcileKnowledgeAnalysisCommand(
            analysis_run_id=created_run.analysis_run_id,
            requested_by=OPERATOR_ID,
        )
    )
    if accepted.state == "NEEDS_REVIEW":
        accepted = analysis.review(
            ReviewKnowledgeAnalysisCommand(
                analysis_run_id=created_run.analysis_run_id,
                expected_version=accepted.resource_version,
                decision="APPROVE",
                notes="Integration fixture approval for V12-to-V13 semantic reuse.",
                decided_by=OPERATOR_ID,
                idempotency_key=f"semantic-reuse-v12-review:{uuid4().hex}",
            )
        )
    assert accepted.state == "ACCEPTED"

    bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v13").resolve(),
        source_commit="d" * 40,
        actor_id="semantic-reuse-v13-integration",
        evaluation_cases_total=3,
        settings=orchestrator_settings,
    )
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        before = int(
            session.scalar(select(func.count()).select_from(KnowledgeAnalysisRunRecord)) or 0
        )
    result = KnowledgeAnalysisBatchService(
        integration_engine,
        catalog_settings,
        analysis=analysis,
    ).create(
        _parallel_batch_command(
            document_revision_id,
            range_count=1,
            reuse_accepted_analysis_run_id=created_run.analysis_run_id,
        )
    )
    assert result.state == "SUCCEEDED"
    with sessions() as session:
        row = session.scalar(
            select(KnowledgeAnalysisBatchRangeRecord).where(
                KnowledgeAnalysisBatchRangeRecord.batch_id == result.batch_id
            )
        )
        after = int(
            session.scalar(select(func.count()).select_from(KnowledgeAnalysisRunRecord)) or 0
        )
        assert row is not None and row.state == "ACCEPTED"
        assert row.analysis_run_id == created_run.analysis_run_id
        assert row.submission_attempts == 0
        assert after == before
