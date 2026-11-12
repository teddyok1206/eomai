"""Shared-slot claims against a marker-guarded disposable PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexCapabilitySnapshotRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    acquire_worker_lease,
    begin_expired_lease_reconciliation,
    publish_capacity_policy_revision,
    publish_execution_preset_revision,
    record_capability_snapshot,
    record_capacity_policy_revision,
    record_execution_preset_revision,
    terminalize_worker_lease,
)
from eom_orchestrator.execution_resolver import ExecutionStepRequirement, resolve_execution_plan
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.preset_model_selection import current_model_preset, validated_preset
from eom_orchestrator.settings import Settings
from eom_orchestrator.shared_slot_controls import (
    prepare_shared_slot_controls,
    release_shared_slot_controls,
)
from eom_workflow.control_plane import CodexCapabilitySnapshot, WorkerRole
from eom_workflow.shared_worker_capacity import (
    ORDINARY_SLOT_IDS,
    SharedWorkerCapacityPolicy,
    ordinary_slot_probe_order,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tests.integration import test_control_plane_persistence as fixture
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_shared_worker_capacity import capacity_value

pytestmark = pytest.mark.integration
ROLES = tuple(
    WorkerRole(value) for value in ("authoring", "review", "image", "item_management", "support")
)


@pytest.fixture
def shared_case(guarded_engine):
    with Session(guarded_engine) as session, session.begin():
        original, _, _ = fixture._complete_control_plane(session, roles=ROLES)
        identity = uuid4().hex
        capacity = capacity_value() | {
            "capacity_policy_id": "capacity_" + identity,
            "capacity_policy_revision_id": "capacityrev_" + identity,
        }
        capacity = SharedWorkerCapacityPolicy.model_validate(capacity).model_dump(mode="json")
        capacity["content_sha256"] = content_sha256(
            {k: v for k, v in capacity.items() if k != "content_sha256"}
        )
        row = record_capacity_policy_revision(
            session,
            policy_key="shared-" + identity,
            document=capacity,
            created_by="disposable-test",
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=row.capacity_policy_id,
            capacity_policy_revision_id=row.capacity_policy_revision_id,
        )
        prior = session.get(ResolvedExecutionPlanRecord, original)
        base = session.get(ExecutionPresetRevisionRecord, prior.preset_revision_id)
        preset = deepcopy(base.canonical_document)
        preset.update(
            preset_id="execpreset_" + identity,
            preset_revision_id="execpresetrev_" + identity,
            capacity_policy_revision_id=row.capacity_policy_revision_id,
        )
        preset["content_sha256"] = content_sha256(
            {k: v for k, v in preset.items() if k != "content_sha256"}
        )
        key = "shared-" + identity
        stored = record_execution_preset_revision(
            session, preset_key=key, document=preset, created_by="disposable-test"
        )
        publish_execution_preset_revision(
            session, preset_id=stored.preset_id, preset_revision_id=stored.preset_revision_id
        )
        requests = []
        for role in (*ROLES, WorkerRole.SUPPORT, WorkerRole.IMAGE):
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
                steps=(ExecutionStepRequirement(role.value, role),),
                resolved_at=fixture.NOW,
            )
            job = fixture._job(session, workflow_id=workflow.workflow_id, role=role.value)
            requests.append((plan.plan_id, job.job_id, role.value))
        case = SimpleNamespace(
            engine=guarded_engine,
            requests=tuple(requests),
            baseline=validated_preset(base),
            original_plan_id=original,
        )
    try:
        yield case
    finally:
        with Session(guarded_engine) as session, session.begin():
            jobs = tuple(job for _, job, _ in case.requests)
            for lease in session.scalars(
                select(WorkerLeaseRecord).where(
                    WorkerLeaseRecord.job_id.in_(jobs),
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                )
            ):
                terminalize_worker_lease(
                    session,
                    lease_id=lease.lease_id,
                    terminal_state="RELEASED",
                    reason_code="TEST_CLEANUP",
                    released_at=fixture.NOW + timedelta(hours=2),
                )


def claim(case, index, *, session=None):
    plan, job, role = case.requests[index]

    def reserve(db):
        result = acquire_worker_lease(
            db,
            plan_id=plan,
            step_key=role,
            job_id=job,
            attempt=1,
            workload_class="CODEX",
            acquired_at=fixture.NOW + timedelta(minutes=1),
            ttl=timedelta(minutes=30),
        )
        return result.lease_id, result.worker_slot_id

    if session is not None:
        return reserve(session)
    with Session(case.engine) as db, db.begin():
        return reserve(db)


def test_four_mixed_roles_claim_distinct_slots_replay_and_fifth_waits(shared_case):
    barrier = Barrier(4)

    def reserve(index):
        barrier.wait(timeout=15)
        return claim(shared_case, index)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(reserve, range(4)))
    assert len({lease for lease, _ in results}) == 4
    assert len({slot for _, slot in results}) == 4
    assert {slot for _, slot in results} <= set(ORDINARY_SLOT_IDS)
    assert claim(shared_case, 0) == results[0]
    with pytest.raises(ControlPlaneError, match="global worker capacity"):
        claim(shared_case, 4)
    with Session(shared_case.engine) as db, db.begin():
        terminalize_worker_lease(
            db,
            lease_id=results[0][0],
            terminal_state="RELEASED",
            reason_code="TEST_DRAINED",
            released_at=fixture.NOW + timedelta(minutes=2),
        )
    assert claim(shared_case, 4)[1] in ORDINARY_SLOT_IDS


@pytest.mark.parametrize("index", range(5))
def test_all_execution_roles_use_stable_probe_not_native_role(shared_case, index):
    _, job, _ = shared_case.requests[index]
    assert claim(shared_case, index)[1] == ordinary_slot_probe_order(job)[0]


@pytest.mark.parametrize(
    "condition", ("disabled", "binding_expired", "capability_expired", "quota", "model_missing")
)
def test_probe_skips_unavailable_first_identity(shared_case, condition):
    _, job, _ = shared_case.requests[4]
    order = ordinary_slot_probe_order(job)
    # Roll back the synthetic fault and lease together; no shared fixture state leaks.
    with Session(shared_case.engine) as db, db.begin():
        first = order[0]
        binding = db.scalar(
            select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == first)
        )
        snapshot = db.scalar(
            select(CodexCapabilitySnapshotRecord)
            .where(CodexCapabilitySnapshotRecord.binding_id == binding.binding_id)
            .order_by(
                CodexCapabilitySnapshotRecord.observed_at.desc(),
                CodexCapabilitySnapshotRecord.capability_snapshot_id.desc(),
            )
        )
        assert snapshot.observed_at <= fixture.NOW, "fresh disposable fixture clock required"
        if condition == "disabled":
            db.get(WorkerSlotRecord, first).enabled = False
        elif condition == "binding_expired":
            binding.valid_until = fixture.NOW + timedelta(seconds=30)
            binding.observed_at = fixture.NOW + timedelta(seconds=10)
            binding.resource_version += 1
        else:
            # Append a newer supported observation; never mutate accepted snapshots.
            value = deepcopy(snapshot.canonical_document)
            value.update(
                capability_snapshot_id="capsnap_" + uuid4().hex,
                observed_at=(fixture.NOW + timedelta(seconds=30)).isoformat(),
                valid_until=(
                    fixture.NOW
                    + timedelta(seconds=45 if condition == "capability_expired" else 3600)
                ).isoformat(),
            )
            if condition == "quota":
                value["capabilities"][0]["state"] = "UNAVAILABLE"
            elif condition == "model_missing":
                value["capabilities"][0]["model"] = "other-model"
            value = CodexCapabilitySnapshot.model_validate(value).model_dump(mode="json")
            value["snapshot_sha256"] = content_sha256(
                {k: v for k, v in value.items() if k != "snapshot_sha256"}
            )
            record_capability_snapshot(db, document=value)
        db.flush()
        result = claim(shared_case, 4, session=db)
        assert result[1] == order[1]
        db.rollback()


def test_expired_unknown_lease_remains_busy_until_supported_reconciliation(shared_case):
    lease_id, slot = claim(shared_case, 0)
    with Session(shared_case.engine) as db, db.begin():
        lease = begin_expired_lease_reconciliation(
            db, lease_id=lease_id, observed_at=fixture.NOW + timedelta(hours=1)
        )
        assert lease.state == "RECONCILING"
    assert claim(shared_case, 0) == (lease_id, slot)
    assert claim(shared_case, 1)[1] != slot


def test_same_job_concurrent_replay_has_one_identity(shared_case):
    gate = Barrier(4)

    def reserve(_):
        gate.wait(timeout=15)
        return claim(shared_case, 4)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(reserve, range(4)))
    assert len(set(results)) == 1


def prepare(case, session):
    return prepare_shared_slot_controls(
        session,
        baselines=(case.baseline,),
        operator_id="operator_" + "f" * 32,
        created_at=fixture.NOW,
        require_installed_units=lambda: None,
    )


def append_draft(session, baseline, *, unrelated):
    """Append synthetic immutable alternatives using the normal revision owner."""
    from eom_orchestrator.preset_lifecycle import create_execution_preset_draft

    logical = session.get(ExecutionPresetRecord, baseline.preset_id)
    roles = [p.model_dump(mode="json") for p in baseline.role_policies]
    if unrelated:
        roles[0]["model_candidates"][0]["model"] = "unpublished-editor-model"
    return create_execution_preset_draft(
        session,
        preset_key=logical.preset_key,
        display_name=baseline.display_name,
        description=baseline.description,
        role_policies=roles,
        capacity_policy_revision_id=baseline.capacity_policy_revision_id,
        general_knowledge_policy=str(baseline.general_knowledge_policy),
        compatible_workflow_protocols=list(baseline.compatible_workflow_protocols),
        created_by="disposable-test",
        created_at=fixture.NOW,
    )


def test_unrelated_draft_is_preserved_and_exact_transition_is_reused(shared_case):
    with Session(shared_case.engine) as db, db.begin():
        unrelated = append_draft(db, shared_case.baseline, unrelated=True)
        original = deepcopy(unrelated.canonical_document)
        first = prepare(shared_case, db)
        assert first.drafts[0].preset_revision_id != unrelated.preset_revision_id
        assert first.drafts[0].role_policies == shared_case.baseline.role_policies
        assert prepare(shared_case, db) == first
        db.refresh(unrelated)
        assert unrelated.state == "DRAFT"
        assert unrelated.canonical_document == original
        assert (
            db.get(ExecutionPresetRecord, shared_case.baseline.preset_id).current_revision_id
            == shared_case.baseline.preset_revision_id
        )
        db.rollback()


def test_multiple_matching_transition_drafts_fail_without_choosing_latest(shared_case):
    with Session(shared_case.engine) as db, db.begin():
        first = prepare(shared_case, db)
        duplicate = append_draft(db, first.drafts[0], unrelated=False)
        assert duplicate.preset_revision_id != first.drafts[0].preset_revision_id
        with pytest.raises(ControlPlaneError) as error:
            prepare(shared_case, db)
        assert error.value.code == "CONTROL_SHARED_DRAFT_CONFLICT"
        db.rollback()


def test_prepare_reuses_draft_capacity_and_preserves_running_plan(shared_case):
    with Session(shared_case.engine) as db, db.begin():
        prior = deepcopy(
            db.get(ResolvedExecutionPlanRecord, shared_case.original_plan_id).canonical_document
        )
        first = prepare(shared_case, db)
        assert prepare(shared_case, db) == first
        assert all(
            tuple(p.slot_keys) == tuple("slot" + slot for slot in ORDINARY_SLOT_IDS)
            for p in first.capacity.pools
        )
        assert first.drafts[0].role_policies == shared_case.baseline.role_policies
        assert first.drafts[0].state == "DRAFT"
        assert (
            db.get(ResolvedExecutionPlanRecord, shared_case.original_plan_id).canonical_document
            == prior
        )
        db.rollback()


def test_four_concurrent_prepare_commands_create_one_draft(shared_case):
    with Session(shared_case.engine) as db, db.begin():
        unrelated = append_draft(db, shared_case.baseline, unrelated=True)
        unrelated_id = unrelated.preset_revision_id
        unrelated_document = deepcopy(unrelated.canonical_document)
    barrier = Barrier(4)

    def submit(_):
        barrier.wait(timeout=15)
        with Session(shared_case.engine) as db, db.begin():
            result = prepare(shared_case, db)
            return result.capacity.capacity_policy_revision_id, result.drafts[0].preset_revision_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = tuple(pool.map(submit, range(4)))
    assert len(set(results)) == 1
    with Session(shared_case.engine) as db:
        assert db.get(ExecutionPresetRevisionRecord, unrelated_id).canonical_document == (
            unrelated_document
        )
    assert results[0][1] != unrelated_id


def test_shared_transition_replay_recognizes_exact_published_successor(shared_case):
    with Session(shared_case.engine) as db, db.begin():
        prepared = prepare(shared_case, db)
        document = prepared.drafts[0].model_dump(mode="json")
        document.update(
            state="RELEASED",
            revision_number=document["revision_number"] + 1,
            preset_revision_id="execpresetrev_" + uuid4().hex,
        )
        document["content_sha256"] = content_sha256(
            {k: v for k, v in document.items() if k != "content_sha256"}
        )
        logical = db.get(ExecutionPresetRecord, shared_case.baseline.preset_id)
        successor = record_execution_preset_revision(
            db, preset_key=logical.preset_key, document=document, created_by="test"
        )
        publish_execution_preset_revision(
            db, preset_id=successor.preset_id, preset_revision_id=successor.preset_revision_id
        )
        replay = prepare(shared_case, db)
        assert replay.drafts[0].preset_revision_id == successor.preset_revision_id
        assert current_model_preset(db, shared_case.baseline) == replay.drafts[0]
        original = db.get(ResolvedExecutionPlanRecord, shared_case.original_plan_id)
        assert original.preset_revision_id == shared_case.baseline.preset_revision_id
        db.rollback()


def test_missing_installed_units_prevents_any_capacity_or_draft_write(shared_case):
    def unavailable():
        raise ValueError("units unavailable")

    with Session(shared_case.engine) as db, db.begin():
        with pytest.raises(ValueError, match="units unavailable"):
            prepare_shared_slot_controls(
                db,
                baselines=(shared_case.baseline,),
                operator_id="test",
                created_at=fixture.NOW,
                require_installed_units=unavailable,
            )
        assert not db.new


def test_shared_release_uses_real_publication_and_replay_preserves_old_plan(
    shared_case, tmp_path, monkeypatch
):
    from eom_orchestrator import shared_slot_controls as owner

    # Native model availability has independent real-DB tests. This case exercises
    # control publication/lifecycle with synthetic acceptance, never inference.
    monkeypatch.setattr(
        owner, "validate_preset_model_admission", lambda *_args, **_kw: ("SYNTHETIC",)
    )
    (tmp_path / "artifacts").mkdir()
    publisher = ControlArtifactPublisher(
        shared_case.engine,
        Settings(staging_root=tmp_path / "staging", nas_artifact_root=tmp_path / "artifacts"),
    )
    authorization = []
    options = dict(
        baselines=(shared_case.baseline,),
        operator_id="operator_" + "f" * 32,
        source_commit="a" * 40,
        created_at=fixture.NOW,
        authorize=authorization.append,
        require_installed_units=lambda: None,
    )
    sessions = sessionmaker(shared_case.engine, expire_on_commit=False)
    first = release_shared_slot_controls(sessions, publisher, **options)
    assert first.drafts[0].state == "RELEASED"
    assert first.drafts[0].role_policies == shared_case.baseline.role_policies
    assert len(authorization) == 3
    publications = tuple((tmp_path / "artifacts").rglob("manifest.json"))
    assert publications
    assert release_shared_slot_controls(sessions, publisher, **options) == first
    assert tuple((tmp_path / "artifacts").rglob("manifest.json")) == publications
    with sessions() as db:
        old = db.get(ResolvedExecutionPlanRecord, shared_case.original_plan_id)
        assert old.preset_revision_id == shared_case.baseline.preset_revision_id


def test_image_limit_follows_execution_role_not_the_selected_physical_slot(shared_case):
    claim(shared_case, 2)
    with pytest.raises(ControlPlaneError, match="GPU worker capacity"):
        claim(shared_case, 6)
    # Non-image work can still use another free identity under the host ceiling.
    claim(shared_case, 4)


def test_support_on_native_gpu_identity_does_not_block_shared_image_work(shared_case):
    with Session(shared_case.engine) as db, db.begin():
        for slot in ORDINARY_SLOT_IDS:
            db.get(WorkerSlotRecord, slot).enabled = slot == "03"
        db.flush()
        assert claim(shared_case, 4, session=db)[1] == "03"
        for slot in ORDINARY_SLOT_IDS:
            db.get(WorkerSlotRecord, slot).enabled = True
        db.flush()
        assert claim(shared_case, 2, session=db)[1] != "03"
        db.rollback()
