"""Real disposable PostgreSQL queue/recovery checks with a file-free renderer port.

These tests prove admission, locks, pointers and lifecycle, not native rendering
or educational content quality. Builder/native output has independent fixtures.
"""

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier, Lock
from typing import Any
from uuid import uuid4

import pytest
from eom_catalog_contracts import CuratedDocumentAssemblyManifestV1
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRecord,
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_hwpx_contracts.curated_build import CuratedHwpxBuildInput
from eom_hwpx_manager.curated_application_service import (
    CuratedBuildPending,
    CuratedBuildReceipt,
    CuratedHwpxApplicationService,
    CuratedRecoveryState,
)
from eom_hwpx_manager.curated_build_models import HwpxCuratedBuildRecord
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.unit.test_curated_document_assembly_resolution import _actor
from tests.unit.test_curated_hwpx_build import build_inputs, build_manifest, build_receipt

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


class _ManagerCrash(BaseException):
    pass


class _Assemblies:
    def __init__(self, manifest: CuratedDocumentAssemblyManifestV1) -> None:
        self.manifest = manifest
        self.revoked = False

    def authorize_delivery_build(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDocumentAssemblyManifestV1:
        return self.read_for_delivery(
            assembly_id,
            assembly_revision_id=assembly_revision_id,
            manifest_sha256=manifest_sha256,
            actor=actor,
        )

    def read_for_delivery(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDocumentAssemblyManifestV1:
        if self.revoked or actor.operator_id != self.manifest.created_by:
            raise ValueError("test operator denied")
        assert assembly_id == self.manifest.assembly_id
        assert assembly_revision_id == self.manifest.assembly_revision_id
        assert manifest_sha256 == self.manifest.manifest_sha256
        return self.manifest


class _Renderer:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)
        self.pin_calls = 0
        self.render_calls = 0
        self.committed: set[str] = set()
        self.rendered: set[str] = set()
        self.barrier: Barrier | None = None
        self.lock = Lock()
        self.pending_once = False
        self.crash_once = False
        self.unit_active = False
        self.failure = False

    def pin_inputs(self, manifest: CuratedDocumentAssemblyManifestV1) -> CuratedHwpxBuildInput:
        with self.lock:
            self.pin_calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        return build_inputs(manifest)

    def build_may_be_active(self, _build_id: str) -> bool:
        return self.unit_active

    def finish(
        self,
        record: HwpxCuratedBuildRecord,
        inputs: CuratedHwpxBuildInput,
        *,
        validated: Callable[[str], None],
    ) -> CuratedBuildReceipt:
        assert content_sha256(inputs.model_dump(mode="json")) == record.input_plan_sha256
        with self.lock:
            if record.build_id not in self.rendered:
                self.render_calls += 1
                self.rendered.add(record.build_id)
        with transaction(self.sessions) as session:
            ensure_protocol_version(session, "curated-test/1.0", "sha256:" + "f" * 64)
            job, created = submit_structured_job(
                session,
                job_id=record.planned_job_id,
                protocol_version="curated-test/1.0",
                idempotency_key="curated-test:" + record.build_id,
                task_type="curated-test",
                request={"input_plan_sha256": record.input_plan_sha256},
                logical_artifact_id=record.planned_artifact_id,
                revision_id=record.planned_artifact_revision_id,
            )
            if created:
                for state in (
                    JobState.VALIDATED,
                    JobState.QUEUED,
                    JobState.CLAIMED,
                    JobState.RUNNING,
                ):
                    transition_job(session, job.job_id, state, "CURATED_TEST_" + state.value)
        if self.failure:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "synthetic preservation failure",
            )
        if self.crash_once:
            self.crash_once = False
            raise _ManagerCrash()
        validated(record.planned_job_id)
        if self.pending_once:
            self.pending_once = False
            raise CuratedBuildPending("same output awaiting commit")
        receipt = build_receipt(record)
        with transaction(self.sessions) as session:
            job = session.get(JobRecord, record.planned_job_id)
            assert job is not None
            if job.status != "SUCCEEDED":
                for state in (JobState.VALIDATING_RESULT, JobState.COMMITTING):
                    transition_job(session, job.job_id, state, "CURATED_TEST_" + state.value)
                create_artifact_records(
                    session,
                    job=job,
                    content_hash=receipt.output_sha256,
                    manifest_hash="sha256:" + "a" * 64,
                    content_bytes=receipt.output_size_bytes,
                    nas_path="/tmp/disposable-curated-fixture/" + record.build_id,
                    manifest={"fixture": "NO_BINARY_MATERIALIZED"},
                    result={"fixture": True},
                )
                transition_job(session, job.job_id, JobState.SUCCEEDED, "CURATED_TEST_COMMITTED")
        self.committed.add(record.build_id)
        return receipt


@dataclass
class _Case:
    engine: Engine
    service: CuratedHwpxApplicationService
    actor: ActorContext
    manifest: CuratedDocumentAssemblyManifestV1
    assemblies: _Assemblies
    renderer: _Renderer

    def request(self, suffix: str = "main") -> tuple[HwpxCuratedBuildRecord, bool]:
        return self.service.request_build(
            self.manifest.assembly_id,
            assembly_revision_id=self.manifest.assembly_revision_id,
            manifest_sha256=self.manifest.manifest_sha256,
            actor=self.actor,
            idempotency_key="curated-request-" + suffix,
        )


@pytest.fixture
def case(creative_engine: Engine) -> Iterator[_Case]:
    # creative_engine validates both the test-state marker and exact owner URL;
    # no installed production DB secret fallback is permitted.
    suffix = uuid4().hex
    actor = _actor(
        PermissionKey.ITEM_READ, PermissionKey.HWPX_BUILD_CREATE, PermissionKey.HWPX_READ
    )
    actor = actor.model_copy(update={"operator_id": "operator_" + suffix})
    value = build_manifest().model_dump(mode="json")
    value.update(
        assembly_id="assembly_" + suffix,
        assembly_revision_id="assemblyrev_" + suffix,
        created_by=actor.actor_id,
    )
    value["manifest_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "manifest_sha256"}
    )
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(value)
    sessions = build_session_factory(creative_engine)
    with transaction(sessions) as session:
        session.add(
            OperatorRecord(
                operator_id=actor.actor_id,
                username="test-" + suffix,
                normalized_username="test-" + suffix,
                display_name="Disposable HWPX test",
                status="ACTIVE",
                must_change_password=False,
                created_by="disposable-test",
                role_version=1,
                lock_version=1,
            )
        )
        session.add(
            CuratedDocumentAssemblyRecord(
                assembly_id=manifest.assembly_id,
                created_by=actor.actor_id,
            )
        )
        session.flush()
        session.add(
            CuratedDocumentAssemblyRevisionRecord(
                assembly_revision_id=manifest.assembly_revision_id,
                assembly_id=manifest.assembly_id,
                revision_number=1,
                revision_state="INPUT_PINNED",
                selection_sha256=manifest.selection_sha256,
                request_sha256="sha256:" + "a" * 64,
                manifest_sha256=manifest.manifest_sha256,
                canonical_document=manifest.model_dump(mode="json"),
                idempotency_key="fixture-" + suffix,
                created_by=actor.actor_id,
                created_at=manifest.created_at,
            )
        )
        session.flush()
        aggregate = session.get(CuratedDocumentAssemblyRecord, manifest.assembly_id)
        aggregate.current_revision_id = manifest.assembly_revision_id
    assemblies = _Assemblies(manifest)
    renderer = _Renderer(creative_engine)
    service = CuratedHwpxApplicationService(
        creative_engine, assemblies=assemblies, renderer=renderer
    )
    yield _Case(creative_engine, service, actor, manifest, assemblies, renderer)
    # Leave terminal history intact. Resolve intentional pending fixtures before
    # the next independent FIFO case; the entire disposable DB is removed later.
    assemblies.revoked = False
    renderer.barrier = None
    renderer.unit_active = renderer.failure = renderer.pending_once = renderer.crash_once = False
    for _ in range(20):
        if service.process_next() is None:
            break
    for _ in range(20):
        if service.recover_interrupted().state is CuratedRecoveryState.NONE:
            break


def test_request_replay_and_completed_poll_do_not_pin_or_render_again(case: _Case) -> None:
    record, created = case.request()
    assert created and record.state == "REQUESTED"
    assert record.initiator_context["permissions"] == []
    assert "password" not in record.initiator_context
    replay, created = case.request()
    assert not created and replay.build_id == record.build_id and case.renderer.pin_calls == 1
    result = case.service.process_next()
    assert result.build_id == record.build_id and result.state == "SUCCEEDED"
    assert result.section_count == 4  # Three selections can contain four native sections.
    for _ in range(3):
        current = case.service.get_build(record.build_id, actor=case.actor)
        replay, created = case.request()
        assert current.output_sha256 == replay.output_sha256 == result.output_sha256
        assert not created and replay.build_id == record.build_id
    assert case.renderer.pin_calls == case.renderer.render_calls == 1


def test_concurrent_admission_has_one_build_and_preserves_first_input_pin(case: _Case) -> None:
    case.renderer.barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: case.request(), range(2)))
    assert sum(created for _record, created in results) == 1
    assert len({record.build_id for record, _created in results}) == 1
    case.renderer.barrier = None
    assert case.service.process_next().state == "SUCCEEDED"
    assert case.renderer.render_calls == 1


def test_concurrent_fifo_claims_execute_one_request_only_once(case: _Case) -> None:
    record, _ = case.request()
    barrier = Barrier(4)

    def claim(_index: int) -> Any:
        barrier.wait(timeout=10)
        return case.service.process_next()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert [result.build_id for result in results if result is not None] == [record.build_id]
    assert case.renderer.render_calls == 1


def test_crash_after_render_recovers_exact_job_artifact_and_no_new_render(case: _Case) -> None:
    record, _ = case.request()
    case.renderer.crash_once = True
    with pytest.raises(_ManagerCrash):
        case.service.process_next()
    assert case.service.get_build(record.build_id, actor=case.actor).state == "RUNNING"
    recovery = case.service.recover_interrupted()
    assert recovery.state is CuratedRecoveryState.RECOVERED
    assert recovery.record.state == "SUCCEEDED"
    assert recovery.record.planned_job_id == record.planned_job_id
    assert recovery.record.output_artifact_id == record.planned_artifact_id
    assert recovery.record.output_artifact_revision_id == record.planned_artifact_revision_id
    assert case.renderer.render_calls == 1


def test_validation_commit_wait_and_live_unit_keep_original_request(case: _Case) -> None:
    record, _ = case.request()
    case.renderer.pending_once = True
    assert case.service.process_next().state == "VALIDATING"
    case.renderer.unit_active = True
    active = case.service.recover_interrupted()
    assert active.state is CuratedRecoveryState.ACTIVE
    assert active.record.build_id == record.build_id
    assert case.renderer.render_calls == 1
    case.renderer.unit_active = False
    assert case.service.recover_interrupted().record.state == "SUCCEEDED"
    assert case.renderer.render_calls == 1


def test_advisory_owner_prevents_duplicate_recovery(case: _Case) -> None:
    record, _ = case.request()
    case.renderer.pending_once = True
    case.service.process_next()
    with case.service._build_lock(record.build_id) as acquired:
        assert acquired
        assert case.service.recover_interrupted().state is CuratedRecoveryState.ACTIVE
    assert case.service.recover_interrupted().record.state == "SUCCEEDED"
    assert case.renderer.render_calls == 1


def test_failed_history_is_not_reinterpreted_or_retried_by_poll(case: _Case) -> None:
    record, _ = case.request()
    case.renderer.failure = True
    failed = case.service.process_next()
    assert failed.state == "FAILED" and failed.failure_code == "HWPX_STRUCTURAL_VALIDATION_FAILED"
    case.renderer.failure = False
    replay, created = case.request()
    assert not created and replay.state == "FAILED" and replay.build_id == record.build_id
    assert case.service.recover_interrupted().state is CuratedRecoveryState.NONE
    assert case.renderer.render_calls == 1 and case.service.process_next() is None
    with case.engine.begin() as connection:
        with pytest.raises(DBAPIError) as immutable, connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE hwpx_curated_builds SET state='REQUESTED',validation_state='PENDING',"
                    "completed_at=NULL,failure_code=NULL WHERE build_id=:id"
                ),
                {"id": record.build_id},
            )
        assert immutable.value.orig.sqlstate == "23514"


def test_source_revocation_blocks_replay_and_execution_without_renderer_call(case: _Case) -> None:
    record, _ = case.request()
    case.assemblies.revoked = True
    with pytest.raises(ValueError, match="denied"):
        case.request()
    result = case.service.process_next()
    assert result.build_id == record.build_id and result.state == "FAILED"
    assert case.renderer.render_calls == 0


def test_revocation_during_render_blocks_artifact_commit(
    case: _Case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, _ = case.request()
    original = case.renderer.finish

    def finish(current, inputs, *, validated):
        def revoke(job_id):
            case.assemblies.revoked = True
            validated(job_id)

        return original(current, inputs, validated=revoke)

    monkeypatch.setattr(case.renderer, "finish", finish)
    result = case.service.process_next()
    assert result.build_id == record.build_id and result.state == "FAILED"
    assert record.build_id not in case.renderer.committed
    assert case.renderer.render_calls == 1


def test_pinned_metadata_is_immutable_and_null_success_evidence_is_rejected(case: _Case) -> None:
    record, _ = case.request()
    with case.engine.begin() as connection:
        with pytest.raises(DBAPIError) as immutable, connection.begin_nested():
            connection.execute(
                text("UPDATE hwpx_curated_builds SET input_plan_sha256=:hash WHERE build_id=:id"),
                {"hash": "sha256:" + "f" * 64, "id": record.build_id},
            )
        assert immutable.value.orig.sqlstate == "23514"
        with pytest.raises(DBAPIError) as invalid, connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE hwpx_curated_builds SET state='SUCCEEDED',validation_state='PASS',"
                    "started_at=now(),completed_at=now() WHERE build_id=:id"
                ),
                {"id": record.build_id},
            )
        assert invalid.value.orig.sqlstate == "23514"
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema='app' "
                    "AND table_name='hwpx_curated_builds' AND data_type='bytea'"
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT pg_column_size(input_plan) FROM hwpx_curated_builds WHERE build_id=:id"
                ),
                {"id": record.build_id},
            )
            < 16384
        )


def test_fifo_query_uses_partial_index(case: _Case) -> None:
    case.request()
    with case.engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = connection.exec_driver_sql(
            "EXPLAIN (FORMAT JSON) SELECT build_id FROM hwpx_curated_builds "
            "WHERE state='REQUESTED' ORDER BY created_at,build_id LIMIT 1"
        ).scalar_one()
    assert "ix_hwpx_curated_requested_fifo" in str(plan)
