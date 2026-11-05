"""Single-item startup recovery against the disposable application database."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_hwpx_manager.application_service import (
    HwpxApplicationService,
    HwpxRenderer,
    ItemRecoveryState,
    ItemRevisionResolver,
)
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.kordoc_service import KordocBuildReceipt
from eom_hwpx_manager.models import HwpxApplicationBuildRecord
from eom_hwpx_manager.renderer_recovery import recover_item_renderer_job
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.repository import ensure_protocol_version, submit_structured_job
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from tests.item_registry.test_registry_persistence import _approved_revision

pytestmark = pytest.mark.integration


def _build_row(session: Session, *, state: str = "RUNNING") -> HwpxApplicationBuildRecord:
    item, revision, source = _approved_revision(session)
    operator = OperatorRecord(
        operator_id="operator_" + "c" * 32,
        username="hwpx-test-operator",
        normalized_username="hwpx-test-operator",
        display_name="HWPX Test Operator",
        status="ACTIVE",
        must_change_password=False,
        role_version=1,
        created_by="test-suite",
        lock_version=1,
    )
    session.add(operator)
    session.flush()
    row = HwpxApplicationBuildRecord(
        build_id="hwpxbuild_" + "d" * 32,
        item_id=item.item_id,
        item_revision_id=revision.item_revision_id,
        source_artifact_id=source.logical_artifact_id,
        source_artifact_revision_id=source.revision_id,
        source_sha256="sha256:" + "2" * 64,
        source_schema_ref="eom.hwpx.markdown-document/1.0",
        source_media_type="text/markdown",
        renderer="kordoc",
        renderer_version="4.9.0",
        options={},
        request_sha256="sha256:" + "e" * 64,
        idempotency_key="item-recovery-test",
        created_by_operator_id=operator.operator_id,
        state=state,
        validation_state="PENDING",
        started_at=datetime.now(UTC),
        resource_version=2,
    )
    session.add(row)
    session.flush()
    return row


def _service(session: Session, engine: Engine, renderer: Mock) -> HwpxApplicationService:
    service = HwpxApplicationService(
        engine, registry=cast(ItemRevisionResolver, Mock()), renderer=cast(HwpxRenderer, renderer)
    )
    service.sessions = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    return service


@pytest.mark.parametrize("state", ("RUNNING", "VALIDATING"))
def test_committed_result_recovers_original_build_once(
    db_session: Session, integration_engine: Engine, state: str
) -> None:
    row = _build_row(db_session, state=state)
    source = db_session.scalar(
        select(JobRecord).where(JobRecord.revision_id == row.source_artifact_revision_id)
    )
    assert source is not None
    receipt = KordocBuildReceipt(
        build_id=row.build_id,
        job_id=source.job_id,
        artifact_id=source.logical_artifact_id,
        artifact_revision_id=source.revision_id,
        output_sha256=row.source_sha256,
        status="SUCCEEDED",
        native_equation_count=1,
        native_table_count=1,
        kordoc_version="4.9.0",
    )
    renderer = Mock()
    renderer.build_may_be_active.return_value = False
    renderer.recover_interrupted_item_result.return_value = receipt
    service = _service(db_session, integration_engine, renderer)
    result = service.recover_interrupted()
    assert result.state is ItemRecoveryState.TERMINALIZED
    assert result.record is not None and result.record.state == "SUCCEEDED"
    assert result.record.build_id == row.build_id
    assert service.recover_interrupted().state is ItemRecoveryState.NONE
    renderer.build.assert_not_called()
    renderer.recover_interrupted_item_result.assert_called_once()


def test_live_renderer_is_not_terminalized_or_resubmitted(
    db_session: Session, integration_engine: Engine
) -> None:
    row = _build_row(db_session)
    renderer = Mock()
    renderer.build_may_be_active.return_value = True
    service = _service(db_session, integration_engine, renderer)
    assert service.recover_interrupted().state is ItemRecoveryState.ACTIVE
    db_session.refresh(row)
    assert row.state == "RUNNING" and row.resource_version == 2
    renderer.recover_interrupted_item_result.assert_not_called()
    renderer.build.assert_not_called()


def test_orphan_without_commit_fails_once_and_preserves_terminal_evidence(
    db_session: Session, integration_engine: Engine
) -> None:
    row = _build_row(db_session)
    renderer = Mock()
    renderer.build_may_be_active.return_value = False
    renderer.recover_interrupted_item_result.return_value = None
    service = _service(db_session, integration_engine, renderer)
    result = service.recover_interrupted()
    assert result.record is not None and result.record.state == "FAILED"
    assert result.record.failure_code == "HWPX_BUILD_INTERRUPTED"
    version = result.record.resource_version
    assert service.recover_interrupted().state is ItemRecoveryState.NONE
    assert service.get_build(row.build_id).resource_version == version
    renderer.build.assert_not_called()


def test_renderer_recovery_checks_pinned_source_and_concurrent_terminalization(
    integration_engine: Engine,
) -> None:
    sessions = build_session_factory(integration_engine)
    key = "recovery-review-" + new_job_id()
    job_id = new_job_id()
    source_revision = new_revision_id()
    expected_hash = "sha256:" + "a" * 64
    with transaction(sessions) as session:
        ensure_protocol_version(session, "hwpx-recovery-test/1.0", "sha256:" + "b" * 64)
        submit_structured_job(
            session,
            job_id=job_id,
            protocol_version="hwpx-recovery-test/1.0",
            idempotency_key=key,
            task_type="hwpx-kordoc-build",
            request={"source": {"artifact_revision_id": source_revision, "sha256": expected_hash}},
            logical_artifact_id=new_logical_artifact_id(),
            revision_id=new_revision_id(),
        )
    kwargs: dict[str, Any] = {
        "job_key": key,
        "task_type": "hwpx-kordoc-build",
        "build_id": "hwpxbuild_" + "d" * 32,
        "source_revision_id": source_revision,
        "source_sha256": expected_hash,
    }
    try:
        with pytest.raises(HwpxManagerError) as stale:
            recover_item_renderer_job(
                sessions, **(kwargs | {"source_sha256": "sha256:" + "c" * 64})
            )
        assert stale.value.code is HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT
        with sessions() as session:
            assert session.get(JobRecord, job_id).status == "CREATED"
        barrier = Barrier(2)

        def recover() -> str | None:
            barrier.wait(timeout=5)
            return recover_item_renderer_job(sessions, **kwargs)

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert list(executor.map(lambda _: recover(), range(2))) == [None, None]
        with sessions() as session:
            assert session.get(JobRecord, job_id).status == "FAILED"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(JobEventRecord)
                    .where(
                        JobEventRecord.job_id == job_id,
                        JobEventRecord.event == "HWPX_ITEM_MANAGER_INTERRUPTED",
                    )
                )
                == 1
            )
    finally:
        with transaction(sessions) as session:
            session.execute(delete(JobEventRecord).where(JobEventRecord.job_id == job_id))
            session.execute(delete(JobRecord).where(JobRecord.job_id == job_id))
