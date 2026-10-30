"""Actual PostgreSQL claims under a new purpose; model/source/unit evidence is synthetic.

Only the marker-guarded disposable database is allowed. Existing official control,
plan, Job and lease owners are used. No worker, account login, NAS or GPU is invoked.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import (
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    WorkerCapacityPolicyRevisionRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    acquire_worker_lease,
    publish_capacity_policy_revision,
    publish_execution_preset_revision,
    record_capacity_policy_revision,
    record_execution_preset_revision,
    terminalize_worker_lease,
)
from eom_orchestrator.execution_resolver import ExecutionStepRequirement, resolve_execution_plan
from eom_orchestrator.models import WorkerSlotRecord
from eom_workflow.control_plane import WorkerRole
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration import test_control_plane_persistence as fixture
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_creative_report_capacity import capacity_value

pytestmark = pytest.mark.integration


@pytest.fixture
def capacity_case(guarded_engine):
    with Session(guarded_engine) as session, session.begin():
        original, _, _ = fixture._complete_control_plane(
            session, roles=(WorkerRole.SUPPORT, WorkerRole.ITEM_MANAGEMENT)
        )
        fixture._complete_control_plane(
            session, roles=(WorkerRole.SUPPORT,), slot_id_by_role={WorkerRole.SUPPORT: "06"}
        )
        capacity = capacity_value()
        identity = uuid4().hex
        capacity.update(
            capacity_policy_id="capacity_" + identity,
            capacity_policy_revision_id="capacityrev_" + identity,
        )
        capacity["content_sha256"] = content_sha256(
            {key: value for key, value in capacity.items() if key != "content_sha256"}
        )
        row = record_capacity_policy_revision(
            session,
            policy_key="creative-reports-" + identity,
            document=capacity,
            created_by="disposable-test",
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=row.capacity_policy_id,
            capacity_policy_revision_id=row.capacity_policy_revision_id,
        )
        old_plan = session.get(ResolvedExecutionPlanRecord, original)
        previous = session.get(ExecutionPresetRevisionRecord, old_plan.preset_revision_id)
        preset = deepcopy(previous.canonical_document)
        role = next(value for value in preset["role_policies"] if value["role"] == "support")
        role.update(worker_pool_key="creative-reports", timeout_seconds=7200)
        preset.update(
            preset_id="execpreset_" + identity,
            preset_revision_id="execpresetrev_" + identity,
            capacity_policy_revision_id=row.capacity_policy_revision_id,
            role_policies=[role],
        )
        preset["content_sha256"] = content_sha256(
            {key: value for key, value in preset.items() if key != "content_sha256"}
        )
        key = "creative-report-test-" + identity
        stored = record_execution_preset_revision(
            session, preset_key=key, document=preset, created_by="disposable-test"
        )
        publish_execution_preset_revision(
            session, preset_id=stored.preset_id, preset_revision_id=stored.preset_revision_id
        )
        requests = []
        for _ in range(4):
            workflow = fixture._workflow(session)
            dependencies = ResolvedPlanDependencyEvidence(
                workflow_id=workflow.workflow_id,
                workflow_definition_key=workflow.definition_key,
                workflow_definition_version=workflow.definition_version,
                workflow_definition_sha256=workflow.definition_hash,
                workflow_role_schema_version=workflow.role_schema_version,
                content_pack_release_id="packrel_" + uuid4().hex,
                content_pack_sha256="sha256:" + uuid4().hex * 2,
            )
            plan = resolve_execution_plan(
                session,
                preset_key=key,
                dependencies=dependencies,
                steps=(ExecutionStepRequirement("support", WorkerRole.SUPPORT),),
                resolved_at=fixture.NOW,
            )
            job = fixture._job(session, workflow_id=workflow.workflow_id, role="support")
            requests.append((plan.plan_id, job.job_id))
        legacy_plan, legacy_workflow, _ = fixture._complete_control_plane(session)
        legacy_job = fixture._job(session, workflow_id=legacy_workflow)
        case = SimpleNamespace(
            engine=guarded_engine,
            requests=tuple(requests),
            legacy=(legacy_plan, legacy_job.job_id),
            capacity_id=row.capacity_policy_revision_id,
        )
    try:
        yield case
    finally:
        # Release only synthetic leases belonging to this test, preserving their history.
        with Session(guarded_engine) as session, session.begin():
            jobs = tuple(job for _, job in (*case.requests, case.legacy))
            leases = tuple(
                session.scalars(
                    select(WorkerLeaseRecord).where(
                        WorkerLeaseRecord.job_id.in_(jobs),
                        WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                    )
                )
            )
            for lease in leases:
                terminalize_worker_lease(
                    session,
                    lease_id=lease.lease_id,
                    terminal_state="RELEASED",
                    reason_code="TEST_CLEANUP",
                    released_at=fixture.NOW + timedelta(minutes=10),
                )


def claim(case, index):
    plan_id, job_id = case.requests[index]
    with Session(case.engine) as session, session.begin():
        lease = acquire_worker_lease(
            session,
            plan_id=plan_id,
            step_key="support",
            job_id=job_id,
            attempt=1,
            workload_class="KNOWLEDGE_ANALYSIS",
            acquired_at=fixture.NOW + timedelta(minutes=1),
            ttl=timedelta(hours=2),
        )
        return lease.lease_id, lease.worker_slot_id


def test_three_concurrent_claims_use_distinct_fixed_identities_and_replay(capacity_case):
    gate = Barrier(3)

    def submit(index):
        gate.wait(timeout=15)
        return claim(capacity_case, index)

    with ThreadPoolExecutor(max_workers=3) as executor:
        claims = tuple(executor.map(submit, range(3)))
    assert {slot for _, slot in claims} == {"04", "05", "06"}
    assert len({lease for lease, _ in claims}) == 3
    assert claim(capacity_case, 0) == claims[0]
    with pytest.raises(ControlPlaneError) as captured:
        claim(capacity_case, 3)
    assert captured.value.code == "CONTROL_CAPACITY_EXHAUSTED"
    with Session(capacity_case.engine) as session:
        assert session.get(WorkerSlotRecord, "04").role == "item_management"


def test_new_purpose_cannot_exceed_global_ceiling_across_legacy_policy(capacity_case):
    for index in range(3):
        claim(capacity_case, index)
    with Session(capacity_case.engine) as session, session.begin():
        plan_id, job_id = capacity_case.legacy
        with pytest.raises(ControlPlaneError) as captured:
            acquire_worker_lease(
                session,
                plan_id=plan_id,
                step_key="authoring",
                job_id=job_id,
                attempt=1,
                workload_class="CODEX",
                acquired_at=fixture.NOW + timedelta(minutes=1),
                ttl=timedelta(minutes=30),
            )
        assert captured.value.code == "CONTROL_CAPACITY_EXHAUSTED"


def test_concurrent_same_job_replay_keeps_one_original_lease(capacity_case):
    gate = Barrier(3)

    def submit(_):
        gate.wait(timeout=15)
        return claim(capacity_case, 0)

    with ThreadPoolExecutor(max_workers=3) as executor:
        claims = tuple(executor.map(submit, range(3)))
    assert len(set(claims)) == 1
    with Session(capacity_case.engine) as session:
        assert (
            len(
                tuple(
                    session.scalars(
                        select(WorkerLeaseRecord).where(
                            WorkerLeaseRecord.job_id == capacity_case.requests[0][1]
                        )
                    )
                )
            )
            == 1
        )


def test_wrong_native_role_cannot_turn_delegation_into_unrestricted_support(capacity_case):
    # Uncommitted synthetic tampering is rolled back; no operating slot is changed.
    with Session(capacity_case.engine) as session:
        try:
            session.get(WorkerSlotRecord, "04").role = "support"
            session.flush()
            for plan_id, job_id in capacity_case.requests[:2]:
                lease = acquire_worker_lease(
                    session,
                    plan_id=plan_id,
                    step_key="support",
                    job_id=job_id,
                    attempt=1,
                    workload_class="KNOWLEDGE_ANALYSIS",
                    acquired_at=fixture.NOW + timedelta(minutes=1),
                    ttl=timedelta(hours=2),
                )
                assert lease.worker_slot_id in {"05", "06"}
            plan_id, job_id = capacity_case.requests[2]
            with pytest.raises(ControlPlaneError) as captured:
                acquire_worker_lease(
                    session,
                    plan_id=plan_id,
                    step_key="support",
                    job_id=job_id,
                    attempt=1,
                    workload_class="KNOWLEDGE_ANALYSIS",
                    acquired_at=fixture.NOW + timedelta(minutes=1),
                    ttl=timedelta(hours=2),
                )
            assert captured.value.code == "CONTROL_ELIGIBLE_SLOT_UNAVAILABLE"
        finally:
            session.rollback()


def test_three_report_history_prevents_destructive_schema_downgrade(capacity_case):
    from importlib import import_module

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = import_module("migrations.versions.20261030_0064_creative_report_capacity")
    with capacity_case.engine.begin() as connection:
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="CREATIVE_REPORT_CAPACITY_HISTORY_EXISTS"),
        ):
            migration.downgrade()
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == "20261030_0064"
        )


def test_database_keeps_predecessor_analysis_ceiling_at_two(capacity_case):
    with Session(capacity_case.engine) as session, session.begin():
        original = session.get(WorkerCapacityPolicyRevisionRecord, capacity_case.capacity_id)
        values = {
            column.name: getattr(original, column.name)
            for column in WorkerCapacityPolicyRevisionRecord.__table__.columns
            if column.name != "created_at"
        }
        values.update(
            capacity_policy_revision_id="capacityrev_" + uuid4().hex,
            revision_number=2,
            schema_version="worker-capacity-policy/1.3",
        )
        # Deliberately invalid adapter row: the DB guard must independently reject it.
        with pytest.raises(IntegrityError) as captured, session.begin_nested():
            session.add(WorkerCapacityPolicyRevisionRecord(**values))
            session.flush()
        assert captured.value.orig.diag.constraint_name == "ck_capacity_policy_host_limits"


def test_changed_capacity_tables_match_migration_metadata(capacity_case):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from eom_orchestrator.models import Base

    # Scoped to this change; the separate full-composition audit stays strict.
    def included(_object, name, kind, _reflected, _compare_to):
        return kind != "table" or name.startswith("worker_capacity_")

    with capacity_case.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": included})
        assert compare_metadata(context, Base.metadata) == []
