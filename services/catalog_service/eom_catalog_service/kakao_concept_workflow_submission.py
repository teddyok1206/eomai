"""Application composition: the source owner links the existing Workflow submission once."""

from eom_operator_identity import ActorContext
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.kakao_concept_request import KakaoConceptWork
from eom_workflow_runner.kakao_concept_start import (
    SubmittedKakaoConcept,
    submit_kakao_concept_workflow,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord
from sqlalchemy import select

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_models import KakaoConceptPhaseRecord, KakaoConceptTaskRecord
from .kakao_concept_task_service import KakaoConceptSourceAuthority, KakaoConceptTaskService


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
