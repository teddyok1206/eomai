from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisBatchCommand,
    CreateKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeAnalysisSelection,
    ExecuteKnowledgeAnalysisRange,
    KnowledgeAnalysisBatchRangeRequest,
    KnowledgeAnalysisBatchRangeRequestV2,
    KnowledgeAnalysisBatchRequest,
    KnowledgeAnalysisBatchRequestV2,
    KnowledgeAnalysisBatchSourceRange,
    KnowledgeAnalysisBatchSourceRangeV2,
    KnowledgeAnalysisRequestV6,
    ReconcileKnowledgeAnalysisCommand,
    ReuseAcceptedKnowledgeAnalysisRange,
    ReviewKnowledgeAnalysisCommand,
)
from eom_catalog_service.knowledge_analysis_batch_models import (
    KnowledgeAnalysisBatchEventRecord,
    KnowledgeAnalysisBatchRangeRecord,
    KnowledgeAnalysisBatchRecord,
)
from eom_catalog_service.knowledge_analysis_batch_service import (
    KnowledgeAnalysisBatchService,
    KnowledgeAnalysisBatchServiceError,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_identifiers import content_sha256
from eom_orchestrator.control_bootstrap import bootstrap_knowledge_analysis_control_plane
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, func, select, text

from tests.integration.test_knowledge_analysis_service import (
    OPERATOR_ID,
    POLICY_ID,
    _complete_proposal,
    _document_source,
    _ensure_dependencies,
    _settings,
)

pytestmark = pytest.mark.integration


def _batch_command(
    document_revision_id: str,
    range_count: int = 2,
    *,
    first_page: int = 1,
    reuse_accepted_analysis_run_id: str | None = None,
) -> CreateKnowledgeAnalysisBatchCommand:
    request = KnowledgeAnalysisBatchRequest(
        risk_policy_revision_id=POLICY_ID,
        ranges=tuple(
            KnowledgeAnalysisBatchRangeRequest(
                ordinal=ordinal,
                source=KnowledgeAnalysisBatchSourceRange(
                    document_revision_id=document_revision_id,
                    first_physical_page=first_page + ordinal,
                    last_physical_page=first_page + ordinal,
                    curriculum_unit_keys=("1-(1)",),
                ),
                execution=(
                    ReuseAcceptedKnowledgeAnalysisRange(
                        accepted_analysis_run_id=reuse_accepted_analysis_run_id
                    )
                    if reuse_accepted_analysis_run_id is not None
                    else ExecuteKnowledgeAnalysisRange()
                ),
            )
            for ordinal in range(range_count)
        ),
    )
    authorized_at = datetime(2026, 8, 26, 1, tzinfo=UTC)
    canonical = {
        "request": request.model_dump(mode="json"),
        "requested_by": OPERATOR_ID,
    }
    return CreateKnowledgeAnalysisBatchCommand(
        request=request,
        requested_by=OPERATOR_ID,
        authorized_at=authorized_at,
        idempotency_key=f"knowledge-analysis-batch-integration:{uuid4().hex}",
        submission_sha256=content_sha256(canonical),
    )


def _unmapped_batch_command(document_revision_id: str) -> CreateKnowledgeAnalysisBatchCommand:
    request = KnowledgeAnalysisBatchRequestV2(
        risk_policy_revision_id=POLICY_ID,
        ranges=tuple(
            KnowledgeAnalysisBatchRangeRequestV2(
                ordinal=ordinal,
                source=KnowledgeAnalysisBatchSourceRangeV2(
                    document_revision_id=document_revision_id,
                    first_physical_page=ordinal + 1,
                    last_physical_page=ordinal + 1,
                    curriculum_unit_keys=() if ordinal == 0 else ("1-(1)",),
                ),
                execution=ExecuteKnowledgeAnalysisRange(),
            )
            for ordinal in range(2)
        ),
    )
    canonical = {"request": request.model_dump(mode="json"), "requested_by": OPERATOR_ID}
    return CreateKnowledgeAnalysisBatchCommand(
        request=request,
        requested_by=OPERATOR_ID,
        authorized_at=datetime(2026, 8, 26, 1, tzinfo=UTC),
        idempotency_key=f"knowledge-analysis-batch-unmapped:{uuid4().hex}",
        submission_sha256=content_sha256(canonical),
    )


def _make_submitted_range_due(
    engine: Engine,
    *,
    range_id: str,
) -> None:
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        row = session.get(KnowledgeAnalysisBatchRangeRecord, range_id)
        assert row is not None and row.state == "SUBMITTED"
        row.next_action_at = datetime.now(UTC) - timedelta(seconds=1)


def test_batch_executes_fifo_with_one_active_range_and_no_duplicate_submission(
    integration_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    document_revision_id = _document_source(integration_engine, catalog_settings, tmp_path)[1]
    service = KnowledgeAnalysisBatchService(integration_engine, catalog_settings)
    command = _unmapped_batch_command(document_revision_id)

    read_calls = 0
    read_member = service.artifacts.read_member

    def counted_read_member(**values: Any) -> bytes:
        nonlocal read_calls
        read_calls += 1
        return read_member(**values)

    monkeypatch.setattr(service.artifacts, "read_member", counted_read_member)

    created = service.create(command)
    assert read_calls == 2
    assert created.state == "QUEUED"
    assert service.create(command) == created
    replay_after_lost_response = CreateKnowledgeAnalysisBatchCommand(
        request=command.request,
        requested_by=command.requested_by,
        authorized_at=command.authorized_at + timedelta(minutes=1),
        idempotency_key=command.idempotency_key,
        submission_sha256=command.submission_sha256,
    )
    assert service.create(replay_after_lost_response) == created

    services = tuple(
        KnowledgeAnalysisBatchService(integration_engine, catalog_settings) for _ in range(2)
    )
    runner_ids = ("batch-runner-a", "batch-runner-b")

    def claim(index: int) -> tuple[str, str] | None:
        return services[index]._claim_next_range(runner_id=runner_ids[index])

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(executor.map(claim, range(2)))
    winners = tuple((index, value) for index, value in enumerate(claims) if value is not None)
    assert len(winners) == 1
    winner_index, claimed = winners[0]
    assert claimed is not None and claimed[0] == created.batch_id

    service._submit_claimed(*claimed, runner_id=runner_ids[winner_index])
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        ranges = tuple(
            session.scalars(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id)
                .order_by(KnowledgeAnalysisBatchRangeRecord.ordinal)
            )
        )
        assert tuple(row.state for row in ranges) == ("SUBMITTED", "PENDING")
        assert ranges[0].curriculum_unit_keys == []
        assert ranges[1].curriculum_unit_keys == ["1-(1)"]
        assert ranges[0].submission_attempts == 1
        assert ranges[0].analysis_run_id is not None
        first_range_id = ranges[0].range_id
        first_run_id = ranges[0].analysis_run_id
        second_range_id = ranges[1].range_id
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeAnalysisRunRecord)
                .where(
                    KnowledgeAnalysisRunRecord.idempotency_key
                    == f"analysis-batch-range:{first_range_id}"
                )
            )
            == 1
        )

    assert not service.advance_once(runner_id="batch-runner-c")
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=first_run_id,
        staging_root=tmp_path / "batch-proposal-0",
    )
    _make_submitted_range_due(integration_engine, range_id=first_range_id)
    assert service.advance_once(runner_id="batch-runner-c")

    with sessions() as session:
        first = session.get(KnowledgeAnalysisBatchRangeRecord, first_range_id)
        second = session.get(KnowledgeAnalysisBatchRangeRecord, second_range_id)
        assert first is not None and first.state == "ACCEPTED"
        assert second is not None and second.state == "PENDING"

    assert service.advance_once(runner_id="batch-runner-c")
    with sessions() as session:
        second = session.get(KnowledgeAnalysisBatchRangeRecord, second_range_id)
        assert second is not None and second.state == "SUBMITTED"
        assert second.submission_attempts == 1
        assert second.analysis_run_id is not None
        second_run_id = second.analysis_run_id

    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=second_run_id,
        staging_root=tmp_path / "batch-proposal-1",
    )
    _make_submitted_range_due(integration_engine, range_id=second_range_id)
    assert service.advance_once(runner_id="batch-runner-c")

    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        ranges = tuple(
            session.scalars(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id)
                .order_by(KnowledgeAnalysisBatchRangeRecord.ordinal)
            )
        )
        events = tuple(
            session.scalars(
                select(KnowledgeAnalysisBatchEventRecord)
                .where(KnowledgeAnalysisBatchEventRecord.batch_id == created.batch_id)
                .order_by(KnowledgeAnalysisBatchEventRecord.sequence)
            )
        )
        assert batch is not None and batch.state == "SUCCEEDED"
        assert tuple(row.state for row in ranges) == ("ACCEPTED", "ACCEPTED")
        assert tuple(row.submission_attempts for row in ranges) == (1, 1)
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        serialized = " ".join(str(event.payload) for event in events)
        assert "session" not in serialized.lower()
        assert "token" not in serialized.lower()


def test_v8_batch_executes_one_multimodal_range_exactly_once(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v8").resolve(),
        source_commit="8" * 40,
        actor_id="phase7-integration",
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
    created = service.create(_batch_command(document_revision_id, range_count=1))

    assert service.advance_once(runner_id="v8-batch-runner")
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        range_row = session.scalar(
            select(KnowledgeAnalysisBatchRangeRecord).where(
                KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id
            )
        )
        assert range_row is not None and range_row.state == "SUBMITTED"
        assert range_row.analysis_schema_ref.endswith("bundle-manifest/2.0")
        assert range_row.submission_attempts == 1
        assert range_row.analysis_run_id is not None
        range_id = range_row.range_id
        run_id = range_row.analysis_run_id
        run = session.get(KnowledgeAnalysisRunRecord, run_id)
        assert run is not None
        request = KnowledgeAnalysisRequestV6.model_validate(run.canonical_request)
        assert request.source.page_image_count == 1
        assert request.worker_proposal_schema_ref.endswith("worker-proposal/4.0")

    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=run_id,
        staging_root=tmp_path / "v8-batch-proposal",
    )
    _make_submitted_range_due(integration_engine, range_id=range_id)
    assert service.advance_once(runner_id="v8-batch-runner")
    assert not service.advance_once(runner_id="v8-batch-runner")
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        range_row = session.get(KnowledgeAnalysisBatchRangeRecord, range_id)
        assert batch is not None and batch.state == "SUCCEEDED"
        accepted_count = session.scalar(
            select(func.count()).where(
                KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id,
                KnowledgeAnalysisBatchRangeRecord.state == "ACCEPTED",
            )
        )
        assert accepted_count == 1
        assert range_row is not None and range_row.state == "ACCEPTED"
        assert range_row.submission_attempts == 1


def test_batch_failure_blocks_later_ranges_without_retry(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    document_revision_id = _document_source(integration_engine, catalog_settings, tmp_path)[1]
    service = KnowledgeAnalysisBatchService(integration_engine, catalog_settings)
    created = service.create(_batch_command(document_revision_id))
    assert service.advance_once(runner_id="batch-runner-failure")

    sessions = build_session_factory(integration_engine)
    with transaction(sessions) as session:
        first = session.scalar(
            select(KnowledgeAnalysisBatchRangeRecord)
            .where(KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id)
            .order_by(KnowledgeAnalysisBatchRangeRecord.ordinal)
            .limit(1)
        )
        assert first is not None and first.analysis_run_id is not None
        run = session.get(KnowledgeAnalysisRunRecord, first.analysis_run_id)
        assert run is not None
        run.state = "FAILED"
        run.error_code = "KNOWLEDGE_ANALYSIS_WORKER_FAILED"
        run.completed_at = datetime.now(UTC)
        run.lock_version += 1
        first.next_action_at = datetime.now(UTC) - timedelta(seconds=1)

    assert service.advance_once(runner_id="batch-runner-failure")
    assert not service.advance_once(runner_id="batch-runner-failure")
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
        assert batch.failure_code == "KNOWLEDGE_ANALYSIS_BATCH_RANGE_FAILED"
        assert tuple(row.state for row in ranges) == ("FAILED", "PENDING")
        assert tuple(row.submission_attempts for row in ranges) == (1, 0)


def test_expired_claim_replays_the_same_analysis_create_once(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    document_revision_id = _document_source(integration_engine, catalog_settings, tmp_path)[1]
    service = KnowledgeAnalysisBatchService(integration_engine, catalog_settings)
    created = service.create(_batch_command(document_revision_id, range_count=1))
    claimed = service._claim_next_range(runner_id="batch-runner-crashed")
    assert claimed is not None

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        row = session.get(KnowledgeAnalysisBatchRangeRecord, claimed[1])
        assert batch is not None and row is not None
        source = service._resolve_and_verify_range_source(session, row)
        range_command = service._range_create_command(
            batch=batch,
            range_id=row.range_id,
            source=source,
            predecessor_analysis_run_id=None,
        )
        preset_id = batch.preset_id
        preset_revision_id = batch.preset_revision_id
    first = service.analysis.create_with_pinned_preset(
        range_command,
        preset_id=preset_id,
        preset_revision_id=preset_revision_id,
    )

    with transaction(sessions) as session:
        row = session.get(KnowledgeAnalysisBatchRangeRecord, claimed[1])
        assert row is not None and row.state == "CLAIMED"
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    assert service.advance_once(runner_id="batch-runner-recovery")
    with sessions() as session:
        row = session.get(KnowledgeAnalysisBatchRangeRecord, claimed[1])
        assert row is not None and row.state == "SUBMITTED"
        assert row.analysis_run_id == first.analysis_run_id
        assert row.submission_attempts == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeAnalysisRunRecord)
                .where(KnowledgeAnalysisRunRecord.idempotency_key == range_command.idempotency_key)
            )
            == 1
        )

    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=first.analysis_run_id,
        staging_root=tmp_path / "batch-recovered-proposal",
    )
    _make_submitted_range_due(integration_engine, range_id=claimed[1])
    assert service.advance_once(runner_id="batch-runner-recovery")
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, claimed[0])
        row = session.get(KnowledgeAnalysisBatchRangeRecord, claimed[1])
        assert batch is not None and batch.state == "SUCCEEDED"
        assert row is not None and row.state == "ACCEPTED"


def test_reuse_accepted_range_validates_exact_pointers_and_creates_no_run(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
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
            idempotency_key=f"batch-reuse-source:{uuid4().hex}",
        )
    )
    _complete_proposal(
        integration_engine,
        catalog_settings,
        run_id=created_run.analysis_run_id,
        staging_root=tmp_path / "batch-reuse-proposal",
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
                notes="Integration fixture approval for exact batch reuse.",
                decided_by=OPERATOR_ID,
                idempotency_key=f"batch-reuse-review:{uuid4().hex}",
            )
        )
    assert accepted.state == "ACCEPTED"

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        before = int(
            session.scalar(select(func.count()).select_from(KnowledgeAnalysisRunRecord)) or 0
        )
    service = KnowledgeAnalysisBatchService(
        integration_engine,
        catalog_settings,
        analysis=analysis,
    )
    result = service.create(
        _batch_command(
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

    mismatched = _batch_command(
        document_revision_id,
        range_count=1,
        first_page=2,
        reuse_accepted_analysis_run_id=created_run.analysis_run_id,
    )
    with pytest.raises(KnowledgeAnalysisBatchServiceError) as raised:
        service.create(mismatched)
    assert raised.value.code == "KNOWLEDGE_ANALYSIS_BATCH_REUSE_INVALID"


def test_corrupt_pinned_source_blocks_before_analysis_submission(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    orchestrator_settings, catalog_settings = _settings(tmp_path)
    _ensure_dependencies(integration_engine, orchestrator_settings)
    document_revision_id = _document_source(integration_engine, catalog_settings, tmp_path)[1]
    service = KnowledgeAnalysisBatchService(integration_engine, catalog_settings)
    created = service.create(_batch_command(document_revision_id, range_count=1))
    sessions = build_session_factory(integration_engine)
    with transaction(sessions) as session:
        row = session.scalar(
            select(KnowledgeAnalysisBatchRangeRecord).where(
                KnowledgeAnalysisBatchRangeRecord.batch_id == created.batch_id
            )
        )
        assert row is not None
        range_id = row.range_id
        row.source_sha256 = "sha256:" + "0" * 64

    assert service.advance_once(runner_id="batch-runner-stale-source")
    assert not service.advance_once(runner_id="batch-runner-stale-source")
    with sessions() as session:
        batch = session.get(KnowledgeAnalysisBatchRecord, created.batch_id)
        row = session.get(KnowledgeAnalysisBatchRangeRecord, range_id)
        assert batch is not None and batch.state == "BLOCKED"
        assert row is not None and row.state == "FAILED"
        assert row.error_code == "KNOWLEDGE_ANALYSIS_SOURCE_STALE"
        assert row.analysis_run_id is None
        assert row.submission_attempts == 0


def test_batch_claim_query_uses_reviewed_partial_index(integration_engine: Engine) -> None:
    with integration_engine.connect() as connection:
        indexes = {
            str(name): str(definition)
            for name, definition in connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'app' "
                    "AND tablename = 'knowledge_analysis_batch_ranges'"
                )
            )
        }
    assert "ix_knowledge_analysis_batch_range_claim" in indexes
    claim_index = indexes["ix_knowledge_analysis_batch_range_claim"]
    assert " WHERE " in claim_index
    assert all(state in claim_index for state in ("PENDING", "CLAIMED", "SUBMITTED"))
    assert "next_action_at" in claim_index
    assert "uq_knowledge_analysis_batch_active_range" in indexes
