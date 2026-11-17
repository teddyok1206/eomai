"""Current-authorized projections of existing concept tasks and canonical completed results."""

from typing import Literal

from eom_catalog_contracts.kakao_concept_rpc import (
    ConceptBlockView,
    ConceptCaptureView,
    ConceptCitationView,
    ConceptHistory,
    ConceptRectangleView,
    ConceptSummary,
    ConceptView,
)
from eom_catalog_contracts.kakao_concept_tasks import KakaoConceptTask
from eom_kakao_archive_contracts.concepts import (
    ConceptComposeRequest,
    ConceptComposition,
    ConceptPlan,
)
from eom_operator_identity import ActorContext, PermissionKey
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import select

from .artifacts import VerifiedArtifactMemberStream
from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_binding_scope,
)
from .kakao_concept_composition import read_kakao_concept_composition
from .kakao_concept_models import KakaoConceptPhaseRecord, KakaoConceptTaskRecord
from .kakao_concept_pages import MAX_PAGE_BYTES
from .kakao_concept_phase_results import CompletedKakaoConceptPhase, read_kakao_concept_phase_result
from .kakao_concept_task_service import KakaoConceptTaskService
from .kakao_room_models import KakaoRoomRecord


def concept_summary(task: KakaoConceptTask | KakaoConceptTaskRecord) -> ConceptSummary:
    return ConceptSummary(**{key: getattr(task, key) for key in ConceptSummary.model_fields})


def list_kakao_concepts(
    service: KakaoConceptTaskService,
    actor: ActorContext,
    binding: str,
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> ConceptHistory:
    if not 1 <= limit <= 100:
        raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
    with service.sessions() as session:
        owner, _ = authorize_kakao_binding_scope(
            session, actor, binding, PermissionKey.KAKAO_ARCHIVE_EDIT, lock=False
        )
        authorize_kakao_binding_scope(
            session, actor, binding, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
        )
        query = (
            select(KakaoConceptTaskRecord)
            .join(KakaoRoomRecord, KakaoRoomRecord.room_id == KakaoConceptTaskRecord.room_id)
            .where(
                KakaoConceptTaskRecord.owner_operator_id == owner,
                KakaoConceptTaskRecord.source_binding_id == binding,
                KakaoRoomRecord.state == "ACTIVE",
            )
            .order_by(KakaoConceptTaskRecord.task_id)
            .limit(limit + 1)
        )
        if cursor is not None:
            query = query.where(KakaoConceptTaskRecord.task_id > cursor)
        rows = tuple(session.scalars(query))
        return ConceptHistory(
            items=tuple(concept_summary(row) for row in rows[:limit]),
            next_cursor=rows[limit - 1].task_id if len(rows) > limit else None,
        )


def project_kakao_concept_result(
    task: ConceptSummary,
    completed: CompletedKakaoConceptPhase,
) -> ConceptView:
    result = completed.result.output.output
    if isinstance(result, ConceptPlan):
        return ConceptView(
            task=task,
            state="NEEDS_INPUT" if result.status == "NEEDS_INPUT" else "SEARCHING",
            result_sha256=completed.pin.sha256 if result.status == "NEEDS_INPUT" else None,
            focus_summary=result.focus_summary,
            limitations=result.limitations,
        )
    request = completed.request
    if not isinstance(result, ConceptComposition) or not isinstance(request, ConceptComposeRequest):
        raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
    evidence = {value.evidence_key: value for value in request.context.evidence}
    pages = {value.page_key: value for value in request.context.pages}
    blocks = tuple(
        ConceptBlockView(
            title=block.title,
            relevance=block.relevance,
            explanation=block.explanation,
            citations=tuple(
                ConceptCitationView(
                    title=evidence[citation.evidence_key].display_title,
                    location=evidence[citation.evidence_key].location,
                    kind="ORIGINAL_PASSAGE"
                    if citation.quote is not None
                    else "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE",
                    quote=citation.quote,
                )
                for citation in block.citations
            ),
            captures=tuple(
                ConceptCaptureView(
                    page_key=capture.page_key,
                    physical_page=pages[capture.page_key].physical_page,
                    rectangle=ConceptRectangleView.model_validate(capture.rectangle.model_dump()),
                    reason=capture.reason,
                    source_title=evidence[pages[capture.page_key].evidence_key].display_title,
                )
                for capture in block.captures
            ),
        )
        for block in result.blocks
    )
    return ConceptView(
        task=task,
        state="NEEDS_INPUT" if result.status == "NEEDS_INPUT" else "COMPLETED",
        result_sha256=completed.pin.sha256,
        focus_summary=result.focus_summary,
        blocks=blocks,
        staff_checks=tuple(f"{check.observation}\n{check.reason}" for check in result.staff_checks),
        limitations=tuple(dict.fromkeys((*request.context.limitations, *result.limitations))),
    )


def read_kakao_concept(
    service: KakaoConceptTaskService,
    actor: ActorContext,
    binding: str,
    task_id: str,
) -> ConceptView:
    task = service.get_task(actor, binding, task_id)
    summary = concept_summary(task)
    if task.intent is None:
        return ConceptView(task=summary, state="PREPARING")
    authority = service.source_authority(actor, binding, task_id)
    with service.sessions() as session:
        phases = {
            phase_name: workflow_state
            for phase_name, workflow_state in session.execute(
                select(KakaoConceptPhaseRecord.phase, WorkflowInstanceRecord.state)
                .join(
                    WorkflowInstanceRecord,
                    WorkflowInstanceRecord.workflow_id == KakaoConceptPhaseRecord.workflow_id,
                )
                .where(KakaoConceptPhaseRecord.task_id == task_id)
            ).all()
        }
    phase: Literal["PLAN", "COMPOSE"] = "COMPOSE" if "COMPOSE" in phases else "PLAN"
    state = phases.get(phase)
    if state in {"FAILED", "CANCELLED"}:
        return ConceptView(task=summary, state=state)
    if state == "COMPLETED":
        return project_kakao_concept_result(
            summary, read_kakao_concept_phase_result(authority, phase)
        )
    if state is None:
        return ConceptView(task=summary, state="PREPARING")
    if state not in {"REQUESTED", "RUNNING"}:
        raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
    running = state == "RUNNING"
    display: Literal["COMPOSE_RUNNING", "COMPOSE_PENDING", "PLAN_RUNNING", "PLAN_PENDING"] = (
        ("COMPOSE_RUNNING" if running else "COMPOSE_PENDING")
        if phase == "COMPOSE"
        else ("PLAN_RUNNING" if running else "PLAN_PENDING")
    )
    return ConceptView(task=summary, state=display)


def open_kakao_concept_page(
    service: KakaoConceptTaskService,
    actor: ActorContext,
    binding: str,
    task_id: str,
    page_key: str,
) -> VerifiedArtifactMemberStream:
    authority = service.source_authority(actor, binding, task_id)
    completed = read_kakao_concept_phase_result(authority, "COMPOSE")
    request, knowledge = read_kakao_concept_composition(authority, completed.work)
    if not isinstance(completed.result.output.output, ConceptComposition):
        raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
    # Only actual completed proposals may expose a page, not arbitrary model/caller paths.
    selected = {
        capture.page_key
        for block in completed.result.output.output.blocks
        for capture in block.captures
    }
    page = next((page for page in request.context.pages if page.page_key == page_key), None)
    pin = next(
        (pin for pin in knowledge.pages if f"{pin.evidence_key}P{pin.physical_page}" == page_key),
        None,
    )
    if (
        page_key not in selected
        or page is None
        or pin is None
        or page.member.sha256 != pin.original.sha256
    ):
        raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_POINTER_INVALID")
    opened = service.artifacts.open_verified_member(
        artifact_id=pin.original.artifact_id,
        revision_id=pin.original.artifact_revision_id,
        member_path=pin.original.member_path,
        schema_ref=pin.original.schema_ref,
        media_type=pin.original.media_type,
        sha256=pin.original.sha256,
        max_bytes=MAX_PAGE_BYTES,
    )
    try:
        if opened.content_length != page.member.size_bytes:
            raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_POINTER_INVALID")
        with service.sessions() as session:
            authority.reauthorize(
                session, operator_id=authority.owner_operator_id, work=completed.work
            )
        return opened
    except BaseException:
        opened.stream.close()
        raise
