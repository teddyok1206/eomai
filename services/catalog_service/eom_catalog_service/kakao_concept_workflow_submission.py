"""Application composition: the source owner links the existing Workflow submission once."""

from eom_catalog_contracts.kakao_concept_tasks import KakaoConceptCreate, KakaoConceptMutation
from eom_operator_identity import ActorContext
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.execution_resolver import read_current_execution_preset
from eom_orchestrator.kakao_concept_plan_resolution import validate_kakao_concept_execution_plan
from eom_orchestrator.preset_model_selection import validated_preset
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.kakao_concept_request import KakaoConceptWork
from eom_workflow_runner.kakao_concept_start import (
    SubmittedKakaoConcept,
    submit_kakao_concept_workflow,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import admitted_workflow_definition
from sqlalchemy import select

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_models import KakaoConceptPhaseRecord, KakaoConceptTaskRecord
from .kakao_concept_task_service import KakaoConceptSourceAuthority, KakaoConceptTaskService


def read_kakao_concept_submission_runtime(
    service: KakaoConceptTaskService,
    *,
    authority: KakaoConceptSourceAuthority | None = None,
) -> tuple[WorkflowDefinitionRecord, ExecutionPresetRevision]:
    """New work selects current once; an accepted PLAN replay reads its exact original pins."""
    if authority is not None and authority.service is not service:
        raise KakaoArchiveError("KAKAO_CONCEPT_WORK_NOT_ACCEPTED")
    with service.sessions.begin() as session:
        definition = admitted_workflow_definition(
            session, definition_key="kakao-concepts", definition_version="1.0.0"
        )
        if definition is None:
            raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_UNAVAILABLE")
        if authority is None:
            preset = read_current_execution_preset(
                session,
                preset_key="kakao-concepts",
                workflow_role_schema_version="workflow-role/1.41.0",
            )
        else:
            task = service.accepted_intent_row(
                session, authority.intent, operator_id=authority.owner_operator_id
            )
            phase = session.get(KakaoConceptPhaseRecord, (task.task_id, "PLAN"))
            if phase is None or phase.workflow_id is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_INPUT_NOT_PREPARED")
            work = KakaoConceptWork.model_validate(phase.work_input)
            authority.reauthorize(session, operator_id=task.owner_operator_id, work=work)
            workflow = session.get(WorkflowInstanceRecord, phase.workflow_id)
            record = session.scalar(
                select(ResolvedExecutionPlanRecord).where(
                    ResolvedExecutionPlanRecord.workflow_id == phase.workflow_id
                )
            )
            plan = validate_kakao_concept_execution_plan(
                record, workflow_id=phase.workflow_id, step_key="assist", work=work
            )
            if workflow is None or (
                workflow.definition_id,
                workflow.definition_hash,
                workflow.created_actor_type,
                workflow.created_actor_id,
                plan.workflow_definition_sha256,
            ) != (
                definition.definition_id,
                definition.definition_hash,
                "human",
                task.owner_operator_id,
                definition.definition_hash,
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_POINTER_INVALID")
            row = session.get(ExecutionPresetRevisionRecord, plan.preset_revision_id)
            logical = session.get(ExecutionPresetRecord, plan.preset_id)
            if (
                row is None
                or logical is None
                or (logical.preset_key, logical.state, row.state)
                != ("kakao-concepts", "ACTIVE", "RELEASED")
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_UNAVAILABLE")
            accepted_preset = validated_preset(row)
            if not isinstance(accepted_preset, ExecutionPresetRevision):
                raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_POINTER_INVALID")
            preset = accepted_preset
            if (
                preset.state != "RELEASED"
                or "workflow-role/1.41.0" not in preset.compatible_workflow_protocols
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_POINTER_INVALID")
            if (preset.preset_id, preset.preset_revision_id, preset.content_sha256) != (
                plan.preset_id,
                plan.preset_revision_id,
                plan.preset_sha256,
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_POINTER_INVALID")
        session.expunge(definition)
        return definition, preset


def start_kakao_concept_task(
    service: KakaoConceptTaskService,
    *,
    actor: ActorContext,
    command: KakaoConceptCreate,
    idempotency_key: str,
) -> tuple[KakaoConceptMutation, SubmittedKakaoConcept]:
    """Accept and submit PLAN through the original actor; a replay never invents another job."""
    mutation = service.create_task(actor, command, idempotency_key=idempotency_key)
    work = service.prepare_plan(actor, command.source_binding_id, mutation.task.task_id)
    authority = service.source_authority(actor, command.source_binding_id, mutation.task.task_id)
    with service.sessions() as session:
        phase = session.get(KakaoConceptPhaseRecord, (mutation.task.task_id, "PLAN"))
        submitted = phase is not None and phase.workflow_id is not None
    definition, preset = read_kakao_concept_submission_runtime(
        service, authority=authority if submitted else None
    )
    return mutation, submit_accepted_kakao_concept_phase(
        authority, work=work, definition=definition, expected_preset=preset
    )


def submit_kakao_concept_phase(
    service: KakaoConceptTaskService,
    *,
    actor: ActorContext,
    work: KakaoConceptWork,
    definition: WorkflowDefinitionRecord,
    expected_preset: ExecutionPresetRevision,
) -> SubmittedKakaoConcept:
    """The public Workflow owner writes execution rows; source checks preserve the phase link."""
    authority = service.source_authority(actor, work.source_binding_id, work.task_id)
    if actor.operator_id is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
    return submit_accepted_kakao_concept_phase(
        authority, work=work, definition=definition, expected_preset=expected_preset
    )


def submit_accepted_kakao_concept_phase(
    authority: KakaoConceptSourceAuthority,
    *,
    work: KakaoConceptWork,
    definition: WorkflowDefinitionRecord,
    expected_preset: ExecutionPresetRevision,
) -> SubmittedKakaoConcept:
    """Continue the original accepted human intent without replaying its expired API session."""
    service, owner = authority.service, authority.owner_operator_id
    with service.sessions.begin() as session:
        task = session.scalar(
            select(KakaoConceptTaskRecord)
            .where(KakaoConceptTaskRecord.task_id == work.task_id)
            .with_for_update()
        )
        if task is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        authority.reauthorize(session, operator_id=owner, work=work)
        phase = session.get(KakaoConceptPhaseRecord, (work.task_id, work.phase))
        assert phase is not None
        with session.begin_nested():
            submitted = submit_kakao_concept_workflow(
                session,
                definition=definition,
                work=work,
                operator_id=owner,
                idempotency_key=f"kakao-concept:{work.task_id}:{work.phase.lower()}",
                source_authorizer=authority,
                expected_preset=expected_preset,
            )
            if phase.workflow_id is None:
                phase.workflow_id = submitted.workflow_id
                session.flush()
            elif phase.workflow_id != submitted.workflow_id:
                raise KakaoArchiveError("KAKAO_CONCEPT_WORKFLOW_CHANGED")
            authority.reauthorize(session, operator_id=owner, work=work)
        return submitted
