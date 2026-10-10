"""V21 native FK/immutable/unique/fence checks in the existing guarded owner DB.

Control documents and Workflow requests are synthetic. Candidate availability
is explicitly fake; no source grant, protected bytes, model or worker is tested.
Only the concurrency test commits its synthetic metadata in the disposable DB.
The existing marker/head guard remains the sole environment entry boundary.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import inference_transfer_resolution as resolution
from eom_orchestrator.control_models import (
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetRolePolicyRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_workflow.control_plane import (
    ExecutionPresetRevision,
    InstructionBundleManifest,
    WorkerCapacityPolicy,
)
from eom_workflow.inference_transfer import TRANSFER_PAIR_PROTOCOL
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.repository import (
    CommandType,
    claim_next_command,
    command_lease_identity,
    enqueue_command,
)
from eom_workflow_runner.state_machine import CommandState, transition_command
from psycopg.errors import ForeignKeyViolation, RaiseException
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.integration.test_inference_transfer_workflow_admission import _submit
from tests.unit.inference_transfer_execution_fixtures import transfer_instruction
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.inference_transfer_workflow_fixtures import OPERATOR_ID, workflow_request

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
FIXTURE_OWNER = "synthetic-transfer-plan-persistence"


def _sha_document(body: dict[str, Any]) -> dict[str, Any]:
    return body | {"content_sha256": content_sha256(body)}


def _synthetic_artifact(session: Session, pointer: Any) -> None:
    """Seed small FK metadata, not a real published file or NAS materialization."""
    job_id = "job_" + uuid4().hex
    session.add(
        JobRecord(
            job_id=job_id,
            protocol_version=TRANSFER_PAIR_PROTOCOL,
            idempotency_key="synthetic-plan-artifact-" + uuid4().hex,
            request_hash=sha("1"),
            task_type="synthetic_metadata_only",
            request={"fixture_only": True},
            status="SUCCEEDED",
            logical_artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
        )
    )
    session.flush()
    session.add(
        ArtifactRecord(
            logical_artifact_id=pointer.artifact_id,
            job_id=job_id,
            artifact_type="synthetic_metadata_only",
            approved=True,
        )
    )
    session.flush()
    session.add(
        ArtifactRevisionRecord(
            revision_id=pointer.artifact_revision_id,
            logical_artifact_id=pointer.artifact_id,
            job_id=job_id,
            content_hash=pointer.sha256,
            manifest_hash=sha("1"),
            content_bytes=1,
            nas_path="/disposable/synthetic_metadata_only/no_file",
            manifest={
                "files": [
                    {
                        "file_name": pointer.logical_name,
                        "sha256": pointer.sha256,
                        "schema_ref": pointer.schema_ref,
                        "media_type": pointer.media_type,
                    }
                ]
            },
            result={"fixture_only": True},
            approved=True,
        )
    )
    session.flush()


def _controls(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_protocol_version(
        session, TRANSFER_PAIR_PROTOCOL, role_schema_bundle_hash(TRANSFER_PAIR_PROTOCOL)
    )
    logical = session.scalar(
        select(ExecutionPresetRecord).where(
            ExecutionPresetRecord.preset_key == resolution.PRESET_KEY
        )
    )
    if logical is not None:
        assert logical.created_by == FIXTURE_OWNER
        row = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        assert row is not None
        preset = ExecutionPresetRevision.model_validate(row.canonical_document)
    else:
        instruction_body = transfer_instruction().model_dump(mode="json")
        instruction_body.pop("content_sha256")
        instruction_body.update(
            bundle_id="instrbundle_" + uuid4().hex, bundle_revision_id="instrrev_" + uuid4().hex
        )
        for component in instruction_body["components"]:
            component["artifact"].update(
                artifact_id="artifact_" + uuid4().hex, artifact_revision_id="rev_" + uuid4().hex
            )
        instruction = InstructionBundleManifest.model_validate(_sha_document(instruction_body))
        manifest_pointer = {
            "artifact_id": "artifact_" + uuid4().hex,
            "artifact_revision_id": "rev_" + uuid4().hex,
            "sha256": content_sha256(instruction.model_dump(mode="json")),
            "schema_ref": "eom://schemas/workflow/instruction-bundle-manifest/1.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
        }
        from eom_workflow.control_plane import ControlArtifactPointer

        pointer = ControlArtifactPointer.model_validate(manifest_pointer)
        for member in (pointer, *(part.artifact for part in instruction.components)):
            _synthetic_artifact(session, member)
        session.add(
            ExecutionBundleRecord(
                bundle_id=instruction.bundle_id,
                bundle_kind="INSTRUCTION",
                bundle_key="synthetic-transfer-" + uuid4().hex,
                state="ACTIVE",
                created_by=FIXTURE_OWNER,
            )
        )
        session.flush()
        session.add(
            ExecutionBundleRevisionRecord(
                bundle_id=instruction.bundle_id,
                bundle_revision_id=instruction.bundle_revision_id,
                bundle_kind="INSTRUCTION",
                revision_number=1,
                schema_version=instruction.schema_version,
                state="RELEASED",
                manifest_artifact_id=pointer.artifact_id,
                manifest_artifact_revision_id=pointer.artifact_revision_id,
                manifest_sha256=pointer.sha256,
                content_sha256=instruction.content_sha256,
                canonical_document=instruction.model_dump(mode="json"),
                created_by=FIXTURE_OWNER,
            )
        )
        capacity_body = {
            "schema_version": "worker-capacity-policy/1.0",
            "capacity_policy_id": "capacity_" + uuid4().hex,
            "capacity_policy_revision_id": "capacityrev_" + uuid4().hex,
            "revision_number": 1,
            "state": "RELEASED",
            "max_configured_slots": 5,
            "max_active_codex": 3,
            "max_active_per_slot": 1,
            "max_active_gpu": 1,
            "max_active_knowledge_analysis": 1,
            "pools": [
                {
                    "pool_key": "customer-support",
                    "roles": ["support"],
                    "slot_keys": ["slot05"],
                    "max_active": 1,
                }
            ],
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        }
        capacity = WorkerCapacityPolicy.model_validate(_sha_document(capacity_body))
        session.add(
            WorkerCapacityPolicyRecord(
                capacity_policy_id=capacity.capacity_policy_id,
                policy_key="synthetic-transfer-" + uuid4().hex,
                state="ACTIVE",
                created_by=FIXTURE_OWNER,
            )
        )
        session.flush()
        session.add(
            WorkerCapacityPolicyRevisionRecord(
                **{
                    key: getattr(capacity, key)
                    for key in (
                        "capacity_policy_id",
                        "capacity_policy_revision_id",
                        "revision_number",
                        "schema_version",
                        "state",
                        "max_configured_slots",
                        "max_active_codex",
                        "max_active_per_slot",
                        "max_active_gpu",
                        "max_active_knowledge_analysis",
                        "content_sha256",
                    )
                },
                canonical_document=capacity.model_dump(mode="json"),
                created_by=FIXTURE_OWNER,
            )
        )
        session.flush()
        preset_body = {
            "schema_version": "execution-preset-revision/1.0",
            "preset_id": "execpreset_" + uuid4().hex,
            "preset_revision_id": "execpresetrev_" + uuid4().hex,
            "revision_number": 1,
            "state": "RELEASED",
            "display_name": "Synthetic transfer persistence metadata",
            "description": "Not operating controls or a current model admission.",
            "role_policies": [
                {
                    "role": "support",
                    "model_candidates": [
                        {"model": "synthetic-never-invoked", "reasoning_effort": "high"}
                    ],
                    "instruction_bundle": {
                        "bundle_id": instruction.bundle_id,
                        "bundle_revision_id": instruction.bundle_revision_id,
                        "manifest_artifact": manifest_pointer,
                        "manifest_sha256": pointer.sha256,
                    },
                    "reference_bundle": None,
                    "worker_pool_key": "customer-support",
                    "timeout_seconds": 300,
                    "sandbox": "read-only",
                    "network": "disabled",
                }
            ],
            "capacity_policy_revision_id": capacity.capacity_policy_revision_id,
            "general_knowledge_policy": "DENY",
            "compatible_workflow_protocols": [TRANSFER_PAIR_PROTOCOL],
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        }
        preset = ExecutionPresetRevision.model_validate(_sha_document(preset_body))
        logical = ExecutionPresetRecord(
            preset_id=preset.preset_id,
            preset_key=resolution.PRESET_KEY,
            state="ACTIVE",
            created_by=FIXTURE_OWNER,
        )
        session.add(logical)
        session.flush()
        session.add(
            ExecutionPresetRevisionRecord(
                **{
                    key: getattr(preset, key)
                    for key in (
                        "preset_id",
                        "preset_revision_id",
                        "revision_number",
                        "schema_version",
                        "state",
                        "display_name",
                        "description",
                        "capacity_policy_revision_id",
                        "general_knowledge_policy",
                        "content_sha256",
                    )
                },
                compatible_workflow_protocols=list(preset.compatible_workflow_protocols),
                canonical_document=preset.model_dump(mode="json"),
                created_by=FIXTURE_OWNER,
            )
        )
        session.flush()
        policy = preset.role_policies[0]
        session.add(
            ExecutionPresetRolePolicyRecord(
                preset_revision_id=preset.preset_revision_id,
                role=str(policy.role),
                model_candidates=[
                    value.model_dump(mode="json") for value in policy.model_candidates
                ],
                instruction_bundle_revision_id=policy.instruction_bundle.bundle_revision_id,
                reference_bundle_revision_id=None,
                worker_pool_key=policy.worker_pool_key,
                timeout_seconds=policy.timeout_seconds,
                sandbox=policy.sandbox,
                network=policy.network,
            )
        )
        session.flush()
        logical.current_revision_id = preset.preset_revision_id
        session.flush()
    # This is a persistence test, not native model availability evidence.
    monkeypatch.setattr(
        resolution,
        "preset_model_options",
        lambda *args, **kwargs: {"support": preset.role_policies[0].model_candidates},
    )


def _seed(session: Session, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    _controls(session, monkeypatch)
    request = workflow_request(request_id="transferrequest_" + uuid4().hex)
    workflow, created = _submit(
        session,
        request=request,
        actor_id=OPERATOR_ID,
        idempotency_key="synthetic-plan-workflow-" + uuid4().hex,
    )
    assert created
    session.flush()
    return SimpleNamespace(request=request, workflow=workflow)


def _resolve(session: Session, value: SimpleNamespace, **overrides: Any) -> Any:
    return resolution.resolve_inference_transfer_execution_plan(
        session,
        **(
            {
                "workflow_id": value.workflow.workflow_id,
                "workflow_definition_version": value.workflow.definition_version,
                "workflow_definition_sha256": value.workflow.definition_hash,
                "workflow_role_schema_version": value.workflow.role_schema_version,
                "workflow_request": value.request,
                "core_prompt_sha256": sha("5"),
                "prompt_sha256": sha("6"),
                "resolved_at": NOW,
            }
            | overrides
        ),
    )


def test_actual_v21_rows_replay_exact_wrapper_plan_and_single_step(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        value = _seed(session, monkeypatch)
        first = _resolve(session, value)
        session.expire_all()
        second = _resolve(session, value, resolved_at=NOW + timedelta(minutes=1))
        assert first == second and second.resolved_at == NOW
        row = session.get(ResolvedExecutionPlanRecord, first.plan_id)
        assert row is not None and row.canonical_document == first.model_dump(mode="json")
        assert row.preset_revision_id == first.preset_revision_id
        assert (
            row.canonical_document["requester_permissions_sha256"]
            == value.request.requester_permissions_sha256
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResolvedExecutionPlanStepRecord)
                .where(ResolvedExecutionPlanStepRecord.plan_id == first.plan_id)
            )
            == 1
        )


def test_actual_workflow_foreign_key_is_not_bypassed_by_valid_v21_json(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        value = _seed(session, monkeypatch)
        with pytest.raises(IntegrityError) as error, session.begin_nested():
            _resolve(session, value, workflow_id="workflow_" + uuid4().hex)
        assert isinstance(error.value.orig, ForeignKeyViolation)
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResolvedExecutionPlanRecord)
                .where(ResolvedExecutionPlanRecord.workflow_id == value.workflow.workflow_id)
            )
            == 0
        )


@pytest.mark.parametrize("target", ["resolved_execution_plans", "resolved_execution_plan_steps"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_actual_plan_and_step_history_reject_mutation(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch, target: str, operation: str
) -> None:
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        value = _seed(session, monkeypatch)
        plan = _resolve(session, value)
        statement = (
            f"UPDATE app.{target} SET plan_id=plan_id WHERE plan_id=:id"
            if operation == "UPDATE"
            else f"DELETE FROM app.{target} WHERE plan_id=:id"
        )
        with pytest.raises(ProgrammingError) as error, session.begin_nested():
            session.execute(text(statement), {"id": plan.plan_id})
        assert isinstance(error.value.orig, RaiseException)
        assert error.value.orig.sqlstate == "P0001"
        assert error.value.orig.diag.message_primary == (
            "immutable Codex control-plane record cannot be changed"
        )
        row = session.get(ResolvedExecutionPlanRecord, plan.plan_id)
        assert row is not None and row.plan_sha256 == plan.plan_sha256
        assert (
            session.get(ResolvedExecutionPlanStepRecord, (plan.plan_id, "compare_pair")) is not None
        )


def test_actual_unique_workflow_guard_classifies_raced_resolver_without_repair(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = stage_owner_connection.engine
    with Session(engine) as session, session.begin():
        value = _seed(session, monkeypatch)
        # Only this explicitly guarded concurrency test commits disposable metadata.
        session.expunge(value.workflow)
    barrier = Barrier(2)
    original = resolution.lock_current_execution_preset

    def lock(session: Session, **kwargs: Any) -> Any:
        barrier.wait(timeout=10)
        return original(session, **kwargs)

    monkeypatch.setattr(resolution, "lock_current_execution_preset", lock)

    def resolve(_index: int) -> tuple[str, str]:
        try:
            with Session(engine) as session, session.begin():
                plan = _resolve(session, value)
                return "CREATED", plan.plan_id
        except ControlPlaneError as error:
            return "CONFLICT", error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(resolve, range(2)))
    assert sorted(kind for kind, _ in outcomes) == ["CONFLICT", "CREATED"]
    assert next(code for kind, code in outcomes if kind == "CONFLICT") == "CONTROL_PLAN_CONFLICT"
    with Session(engine) as session:
        row = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == value.workflow.workflow_id
            )
        )
        assert row is not None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResolvedExecutionPlanStepRecord)
                .where(ResolvedExecutionPlanStepRecord.plan_id == row.plan_id)
            )
            == 1
        )


def test_actual_runner_fence_rejects_reclaimed_lease_before_plan_write(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = sessionmaker(
        bind=stage_owner_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    with sessions() as session, session.begin():
        value = _seed(session, monkeypatch)
        command, created = enqueue_command(
            session,
            workflow_id=value.workflow.workflow_id,
            command_type=CommandType.ADVANCE_WORKFLOW,
            payload={},
            actor_type="system",
            actor_id="synthetic-runner",
            source="synthetic-fixture",
            idempotency_key="synthetic-fence-" + uuid4().hex,
        )
        assert created
        first = claim_next_command(
            session,
            runner_id="synthetic-first",
            lease_seconds=60,
            workflow_id=value.workflow.workflow_id,
        )
        assert first is command
        transition_command(command, CommandState.PROCESSING)
        old = command_lease_identity(command)
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.flush()
        assert (
            claim_next_command(
                session,
                runner_id="synthetic-second",
                lease_seconds=60,
                workflow_id=value.workflow.workflow_id,
            )
            is command
        )
        current = command_lease_identity(command)
        assert current != old
    runner = WorkflowRunner.__new__(WorkflowRunner)
    runner.sessions = sessions
    runner.runner_config = SimpleNamespace(
        command_lease_seconds=60, command_lease_heartbeat_seconds=60
    )
    with (
        pytest.raises(WorkflowError) as error,
        runner._command_lease_scope(old),
        runner._fenced_transaction() as session,
    ):
        _resolve(session, value)
    assert error.value.code == WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResolvedExecutionPlanRecord)
                .where(ResolvedExecutionPlanRecord.workflow_id == value.workflow.workflow_id)
            )
            == 0
        )
    with runner._command_lease_scope(current), runner._fenced_transaction() as session:
        plan = _resolve(session, value)
    with sessions() as session:
        assert session.get(ResolvedExecutionPlanRecord, plan.plan_id) is not None
