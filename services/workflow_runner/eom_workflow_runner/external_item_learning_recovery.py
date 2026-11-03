"""Explicit, proof-specific successor preparation; terminal history is never rewritten."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from eom_catalog_contracts.creative_launch_recovery import CreativeLaunchRecovery
from eom_catalog_contracts.creative_preexecution_recovery import CreativePreexecutionRecovery
from eom_catalog_contracts.creative_result_recovery import CreativeResultRecovery
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.office_item_learning import (
    CreativeLearningWorkInput,
    OfficeItemLearningWorkInput,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord, WorkerLeaseRecord
from eom_orchestrator.external_item_learning_execution import (
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow.models import ExternalItemLearningWorkerRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.external_item_learning_admission import (
    ExternalItemLearningSourceAuthorizer,
)
from eom_workflow_runner.external_item_learning_preparation import (
    PreparedExternalItemLearning,
    prepare_external_item_learning_workflow,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import load_persisted_workflow_request
from eom_workflow_runner.role_job_identity import role_job_idempotency_key
from eom_workflow_runner.state_machine import record_workflow_event

RECOVERY_EVENT = "CREATIVE_PREEXECUTION_SUCCESSOR_PREPARED"
RESULT_RECOVERY_EVENT = "CREATIVE_INVALID_RESULT_SUCCESSOR_PREPARED"
LAUNCH_RECOVERY_EVENT = "CREATIVE_FIXED_LAUNCH_SUCCESSOR_PREPARED"
RecoveryRecord = CreativePreexecutionRecovery | CreativeResultRecovery | CreativeLaunchRecovery
RecoveryType = (
    type[CreativePreexecutionRecovery] | type[CreativeResultRecovery] | type[CreativeLaunchRecovery]
)


@dataclass(frozen=True, slots=True)
class _RecoveryRoute:
    schema_version: str
    reason: str
    event_type: str
    context_key: str
    key_namespace: str


_RECOVERY_ROUTES: Mapping[RecoveryType, _RecoveryRoute] = MappingProxyType(
    {
        CreativePreexecutionRecovery: _RecoveryRoute(
            "creative-preexecution-recovery/1.0",
            "NO_PLATFORM_JOB_CREATED",
            RECOVERY_EVENT,
            "creative_preexecution_recovery",
            "creative-no-job-recovery:",
        ),
        CreativeResultRecovery: _RecoveryRoute(
            "creative-result-recovery/1.0",
            "INVALID_RESULT_BEFORE_COMMIT",
            RESULT_RECOVERY_EVENT,
            "creative_result_recovery",
            "creative-invalid-result-recovery:",
        ),
        CreativeLaunchRecovery: _RecoveryRoute(
            "creative-launch-recovery/1.0",
            "FIXED_WORKER_CONTRACT_REJECTED",
            LAUNCH_RECOVERY_EVENT,
            "creative_launch_recovery",
            "creative-fixed-launch-recovery:",
        ),
    }
)
_RECORD_TYPE_BY_EVENT: Mapping[str, RecoveryType] = MappingProxyType(
    {route.event_type: record for record, route in _RECOVERY_ROUTES.items()}
)


def _failed_input(
    session: Session, workflow: WorkflowInstanceRecord
) -> tuple[CreativeLearningWorkInput, WorkflowStepRunRecord]:
    profile = creative_learning_profile(workflow.definition_version)
    original = load_persisted_workflow_request(workflow.initial_request)
    worker = original.worker_request()
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.workflow_id == workflow.workflow_id)
            .limit(2)
        )
    )
    if (
        workflow.definition_key != "external-item-learning"
        or workflow.role_schema_version != profile.role_protocol
        or workflow.created_actor_type != "human"
        or workflow.state != "FAILED"
        or workflow.stage != "FAILED"
        or workflow.failure_code != "WORKFLOW_STEP_FAILED"
        or workflow.current_step_key != "extract"
        or original != load_persisted_workflow_request(workflow.request_payload)
        or not isinstance(worker, ExternalItemLearningWorkerRequest)
        or len(steps) != 1
    ):
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_NOT_ELIGIBLE")
    step = steps[0]
    if (
        step.step_key != "extract"
        or step.step_type != "agent"
        or step.worker_role != "support"
        or step.result_schema != profile.result_schema
        or step.attempt != 1
        or step.state != "FAILED"
        or step.error_code != "WORKFLOW_STEP_FAILED"
        or step.platform_job_id is not None
        or step.output_pointer_manifest is not None
        or step.superseded_by_step_run_id is not None
    ):
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_NOT_ELIGIBLE")
    if (
        session.scalar(
            select(JobRecord.job_id).where(
                JobRecord.idempotency_key
                == role_job_idempotency_key(
                    workflow.workflow_id, "extract", 1, workflow.definition_hash
                )
            )
        )
        or session.scalar(
            select(WorkflowCommandRecord.command_id)
            .where(
                WorkflowCommandRecord.workflow_id == workflow.workflow_id,
                WorkflowCommandRecord.state.in_(("PENDING", "LEASED", "PROCESSING")),
            )
            .limit(1)
        )
        or session.scalar(
            select(WorkerLeaseRecord.lease_id)
            .where(
                WorkerLeaseRecord.workflow_id == workflow.workflow_id,
                WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
            )
            .limit(1)
        )
    ):
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_WORK_EXISTS")
    return worker.work_input, step


def _failed_result_input(
    session: Session, workflow: WorkflowInstanceRecord
) -> tuple[CreativeLearningWorkInput, WorkflowStepRunRecord]:
    work, step, _job = _failed_job_input(session, workflow, failure_code="WORKER_RESULT_INVALID")
    return work, step


def _failed_launch_input(
    session: Session, workflow: WorkflowInstanceRecord
) -> tuple[CreativeLearningWorkInput, WorkflowStepRunRecord]:
    work, step, job = _failed_job_input(session, workflow, failure_code="WORKER_UNAVAILABLE")
    if (
        workflow.definition_version != "3.0.0"
        or not isinstance(work, OfficeItemLearningWorkInput)
        or job.worker_slot_id != "03"
        or job.error_message != "worker timeout does not match fixed unit contract"
    ):
        raise ValueError("CREATIVE_LAUNCH_RECOVERY_NOT_ELIGIBLE")
    return work, step


def _failed_job_input(
    session: Session, workflow: WorkflowInstanceRecord, *, failure_code: str
) -> tuple[CreativeLearningWorkInput, WorkflowStepRunRecord, JobRecord]:
    """A known terminal validation failure, with no commit and no executable work."""
    profile = creative_learning_profile(workflow.definition_version)
    original = load_persisted_workflow_request(workflow.initial_request)
    worker = original.worker_request()
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.workflow_id == workflow.workflow_id)
            .limit(2)
        )
    )
    if (
        workflow.definition_key != "external-item-learning"
        or workflow.role_schema_version != profile.role_protocol
        or workflow.created_actor_type != "human"
        or workflow.state != "FAILED"
        or workflow.stage != "FAILED"
        or workflow.failure_code != failure_code
        or workflow.current_step_key != "extract"
        or original != load_persisted_workflow_request(workflow.request_payload)
        or not isinstance(worker, ExternalItemLearningWorkerRequest)
        or len(steps) != 1
    ):
        raise ValueError("CREATIVE_RESULT_RECOVERY_NOT_ELIGIBLE")
    step = steps[0]
    job = session.scalar(
        select(JobRecord).where(
            JobRecord.idempotency_key
            == role_job_idempotency_key(
                workflow.workflow_id, "extract", 1, workflow.definition_hash
            )
        )
    )
    if (
        step.step_key != "extract"
        or step.step_type != "agent"
        or step.worker_role != "support"
        or step.result_schema != profile.result_schema
        or step.attempt != 1
        or step.state != "FAILED"
        or step.error_code != failure_code
        or step.output_pointer_manifest is not None
        or step.superseded_by_step_run_id is not None
        or job is None
        or step.platform_job_id != job.job_id
        or job.status != "FAILED"
        or job.error_code != failure_code
    ):
        raise ValueError("CREATIVE_RESULT_RECOVERY_NOT_ELIGIBLE")
    for statement in (
        select(ArtifactRecord.logical_artifact_id).where(ArtifactRecord.job_id == job.job_id),
        select(JobEventRecord.event_id).where(
            JobEventRecord.job_id == job.job_id,
            JobEventRecord.to_state.in_(("COMMITTING", "SUCCEEDED")),
        ),
        select(WorkflowCommandRecord.command_id).where(
            WorkflowCommandRecord.workflow_id == workflow.workflow_id,
            WorkflowCommandRecord.state.in_(("PENDING", "LEASED", "PROCESSING")),
        ),
        select(WorkerLeaseRecord.lease_id).where(
            WorkerLeaseRecord.workflow_id == workflow.workflow_id,
            WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
        ),
    ):
        if session.scalar(statement.limit(1)) is not None:
            raise ValueError("CREATIVE_RESULT_RECOVERY_COMMITTED_OR_ACTIVE")
    return worker.work_input, step, job


def _successor_event(session: Session, workflow_id: str) -> RecoveryRecord | None:
    rows = tuple(
        session.scalars(
            select(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.workflow_id == workflow_id,
                WorkflowEventRecord.event_type.in_(tuple(_RECORD_TYPE_BY_EVENT)),
            )
            .order_by(WorkflowEventRecord.sequence)
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_DUPLICATE_LINK")
    if not rows:
        return None
    record_type = _RECORD_TYPE_BY_EVENT[rows[0].event_type]
    return record_type.model_validate(rows[0].payload)


def _record_context_key(record: RecoveryRecord) -> str:
    return _RECOVERY_ROUTES[type(record)].context_key


def resolve_external_item_learning_recovery(
    session: Session, workflow: WorkflowInstanceRecord
) -> WorkflowInstanceRecord:
    """Follow only an explicitly prepared immutable link; no automatic retry.

    The caller reauthorizes the final exact source/plan. Bounded indexed links
    are metadata, not a replacement source list or a new queue.
    """
    seen: set[str] = set()
    for _ in range(16):
        if workflow.workflow_id in seen:
            raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_CYCLE")
        seen.add(workflow.workflow_id)
        if workflow.state != "FAILED":
            return workflow
        record = _successor_event(session, workflow.workflow_id)
        if record is None:
            return workflow
        proof = {
            CreativeResultRecovery: _failed_result_input,
            CreativePreexecutionRecovery: _failed_input,
            CreativeLaunchRecovery: _failed_launch_input,
        }[type(record)]
        work, step = proof(session, workflow)
        successor = session.get(WorkflowInstanceRecord, record.successor_workflow_id)
        if (
            record.predecessor_workflow_id != workflow.workflow_id
            or record.predecessor_step_run_id != step.step_run_id
            or record.operator_id != workflow.created_actor_id
            or record.definition_sha256 != workflow.definition_hash
            or record.work_input_sha256 != work.request_sha256
            or (
                isinstance(record, (CreativeResultRecovery, CreativeLaunchRecovery))
                and record.predecessor_job_id != step.platform_job_id
            )
            or successor is None
            or successor.created_actor_type != "human"
            or successor.created_actor_id != workflow.created_actor_id
            or successor.definition_hash != workflow.definition_hash
            or successor.definition_key != workflow.definition_key
            or successor.definition_version != workflow.definition_version
            or successor.role_schema_version != workflow.role_schema_version
            or successor.initial_request != workflow.initial_request
            or successor.request_payload != workflow.request_payload
            or successor.runtime_context.get(_record_context_key(record))
            != record.model_dump(mode="json")
        ):
            raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_LINK_MISMATCH")
        workflow = successor
    raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_CHAIN_TOO_LONG")


def prepare_unstarted_external_item_learning_recovery(
    session: Session,
    *,
    predecessor_workflow_id: str,
    definition: WorkflowDefinitionRecord,
    work: CreativeLearningWorkInput,
    operator_id: str,
    source_authorizer: ExternalItemLearningSourceAuthorizer,
    page_publisher: ControlFileSetPublisher,
    expected_preset: ExecutionPresetRevision,
) -> PreparedExternalItemLearning:
    """Preserve FAILED, prepare a separate READY successor in the caller transaction."""
    return _prepare_recovery(
        session,
        predecessor_workflow_id=predecessor_workflow_id,
        definition=definition,
        work=work,
        operator_id=operator_id,
        source_authorizer=source_authorizer,
        page_publisher=page_publisher,
        expected_preset=expected_preset,
        proof=_failed_input,
        record_type=CreativePreexecutionRecovery,
    )


def prepare_invalid_result_external_item_learning_recovery(
    session: Session,
    *,
    predecessor_workflow_id: str,
    definition: WorkflowDefinitionRecord,
    work: CreativeLearningWorkInput,
    operator_id: str,
    source_authorizer: ExternalItemLearningSourceAuthorizer,
    page_publisher: ControlFileSetPublisher,
    expected_preset: ExecutionPresetRevision,
) -> PreparedExternalItemLearning:
    """Explicit reviewed re-execution, never an automatic or same-Job retry."""
    return _prepare_recovery(
        session,
        predecessor_workflow_id=predecessor_workflow_id,
        definition=definition,
        work=work,
        operator_id=operator_id,
        source_authorizer=source_authorizer,
        page_publisher=page_publisher,
        expected_preset=expected_preset,
        proof=_failed_result_input,
        record_type=CreativeResultRecovery,
    )


def prepare_failed_launch_external_item_learning_recovery(
    session: Session,
    *,
    predecessor_workflow_id: str,
    definition: WorkflowDefinitionRecord,
    work: CreativeLearningWorkInput,
    operator_id: str,
    source_authorizer: ExternalItemLearningSourceAuthorizer,
    page_publisher: ControlFileSetPublisher,
    expected_preset: ExecutionPresetRevision,
    confirm_unit_absent: Callable[[str, str], bool],
) -> PreparedExternalItemLearning:
    """Explicitly replace a proven fixed-unit prelaunch rejection, never a running Job."""

    def prove(
        session: Session, workflow: WorkflowInstanceRecord
    ) -> tuple[CreativeLearningWorkInput, WorkflowStepRunRecord]:
        original, step = _failed_launch_input(session, workflow)
        assert step.platform_job_id is not None
        if not confirm_unit_absent("03", step.platform_job_id):
            raise ValueError("CREATIVE_LAUNCH_RECOVERY_UNIT_UNCERTAIN")
        return original, step

    return _prepare_recovery(
        session,
        predecessor_workflow_id=predecessor_workflow_id,
        definition=definition,
        work=work,
        operator_id=operator_id,
        source_authorizer=source_authorizer,
        page_publisher=page_publisher,
        expected_preset=expected_preset,
        proof=prove,
        record_type=CreativeLaunchRecovery,
    )


def _prepare_recovery(
    session: Session,
    *,
    predecessor_workflow_id: str,
    definition: WorkflowDefinitionRecord,
    work: CreativeLearningWorkInput,
    operator_id: str,
    source_authorizer: ExternalItemLearningSourceAuthorizer,
    page_publisher: ControlFileSetPublisher,
    expected_preset: ExecutionPresetRevision,
    proof: Callable[
        [Session, WorkflowInstanceRecord],
        tuple[CreativeLearningWorkInput, WorkflowStepRunRecord],
    ],
    record_type: RecoveryType,
) -> PreparedExternalItemLearning:
    if not session.in_transaction():
        raise ValueError("creative recovery requires the caller root transaction")
    parent = session.get(
        WorkflowInstanceRecord,
        predecessor_workflow_id,
        with_for_update=True,
        populate_existing=True,
    )
    if parent is None:
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_PARENT_MISSING")
    original, step = proof(session, parent)
    if (
        original != work
        or parent.created_actor_id != operator_id
        or parent.definition_hash != definition.definition_hash
        or parent.definition_version != definition.definition_version
    ):
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_INPUT_MISMATCH")
    previous = _successor_event(session, parent.workflow_id)
    if previous is not None:
        if not isinstance(previous, record_type):
            raise ValueError("CREATIVE_RECOVERY_PROOF_MISMATCH")
        successor = resolve_external_item_learning_recovery(session, parent)
        source_authorizer.reauthorize(session, operator_id=operator_id, source=work.source)
        plan = validate_external_item_learning_execution_plan(
            session.scalar(
                select(ResolvedExecutionPlanRecord).where(
                    ResolvedExecutionPlanRecord.workflow_id == successor.workflow_id
                )
            ),
            workflow_id=successor.workflow_id,
            step_key="extract",
            request=ExternalItemLearningWorkerRequest(work_input=work),
        )
        successor_step = session.scalar(
            select(WorkflowStepRunRecord).where(
                WorkflowStepRunRecord.workflow_id == successor.workflow_id,
                WorkflowStepRunRecord.step_key == "extract",
                WorkflowStepRunRecord.attempt == 1,
            )
        )
        if (
            successor_step is None
            or plan.preset_revision_id != expected_preset.preset_revision_id
            or plan.preset_sha256 != expected_preset.content_sha256
        ):
            raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_PLAN_MISMATCH")
        return PreparedExternalItemLearning(
            ExternalItemLearningRoleSelection(
                workflow_id=successor.workflow_id,
                step_run_id=successor_step.step_run_id,
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                work_input_sha256=work.request_sha256,
            ),
            False,
            False,
        )
    route = _RECOVERY_ROUTES[record_type]
    key = (
        route.key_namespace
        + content_sha256(
            {
                "predecessor_workflow_id": predecessor_workflow_id,
                "definition_sha256": definition.definition_hash,
                "work_input_sha256": work.request_sha256,
            }
        )[7:]
    )
    prepared = prepare_external_item_learning_workflow(
        session,
        definition=definition,
        work=work,
        operator_id=operator_id,
        idempotency_key=key,
        source_authorizer=source_authorizer,
        page_publisher=page_publisher,
        expected_preset=expected_preset,
        execution_preset_key=load_persisted_workflow_request(
            parent.initial_request
        ).execution_preset_key,
    )
    if not prepared.workflow_created:
        # Same-parent replay is handled above under its row lock. An unrelated
        # active-equivalent READY workflow must not have its provenance replaced.
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_SUCCESSOR_CONFLICT")
    body = {
        "schema_version": route.schema_version,
        "predecessor_workflow_id": predecessor_workflow_id,
        "predecessor_step_run_id": step.step_run_id,
        "successor_workflow_id": prepared.selection.workflow_id,
        "operator_id": operator_id,
        "definition_sha256": definition.definition_hash,
        "work_input_sha256": work.request_sha256,
        "reason": route.reason,
    }
    if record_type is not CreativePreexecutionRecovery:
        assert step.platform_job_id is not None  # established by the proof above
        body["predecessor_job_id"] = step.platform_job_id
    record = record_type.model_validate(body | {"record_sha256": content_sha256(body)})
    created_successor = session.get(WorkflowInstanceRecord, prepared.selection.workflow_id)
    if created_successor is None or created_successor.initial_request != parent.initial_request:
        raise ValueError("CREATIVE_PREEXECUTION_RECOVERY_SUCCESSOR_MISMATCH")
    created_successor.runtime_context = {
        **created_successor.runtime_context,
        _record_context_key(record): record.model_dump(mode="json"),
    }
    record_workflow_event(
        session,
        parent.workflow_id,
        route.event_type,
        actor_type="human",
        actor_id=operator_id,
        command_id=None,
        step_key="extract",
        payload=record.model_dump(mode="json"),
    )
    session.flush()
    return prepared
