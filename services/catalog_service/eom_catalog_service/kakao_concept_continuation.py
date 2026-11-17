"""Continue accepted PLAN results through existing Catalog/Workflow owners, not a new queue."""

import threading
from dataclasses import dataclass
from typing import Literal

from eom_kakao_archive_contracts.concepts import ConceptPlan
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import Select, and_, select
from sqlalchemy.orm import aliased

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_models import KakaoConceptPhaseRecord, KakaoConceptTaskRecord
from .kakao_concept_phase_results import read_kakao_concept_phase_result
from .kakao_concept_task_service import KakaoConceptTaskService
from .kakao_concept_workflow_submission import (
    read_kakao_concept_submission_runtime,
    submit_accepted_kakao_concept_phase,
)


@dataclass(frozen=True, slots=True)
class KakaoConceptContinuation:
    task_id: str | None
    state: Literal["IDLE", "WAITING", "NEEDS_INPUT", "SUBMITTED", "ERROR"]
    workflow_id: str | None = None
    error_code: str | None = None


def ready_kakao_concept_continuations(*, after: str | None = None) -> Select[tuple[str, str]]:
    """One small candidate. Existing PK/FK joins, no result JSON or large history body."""
    plan = aliased(KakaoConceptPhaseRecord)
    compose = aliased(KakaoConceptPhaseRecord)
    query = (
        select(KakaoConceptTaskRecord.task_id, KakaoConceptTaskRecord.owner_operator_id)
        .join(plan, and_(plan.task_id == KakaoConceptTaskRecord.task_id, plan.phase == "PLAN"))
        .join(WorkflowInstanceRecord, WorkflowInstanceRecord.workflow_id == plan.workflow_id)
        .outerjoin(
            compose,
            and_(compose.task_id == KakaoConceptTaskRecord.task_id, compose.phase == "COMPOSE"),
        )
        .where(
            KakaoConceptTaskRecord.intent_artifact_id.is_not(None),
            WorkflowInstanceRecord.state == "COMPLETED",
            compose.workflow_id.is_(None),
        )
        .order_by(KakaoConceptTaskRecord.task_id)
        .limit(1)
    )
    return query if after is None else query.where(KakaoConceptTaskRecord.task_id > after)


class KakaoConceptCoordinator:
    def __init__(self, service: KakaoConceptTaskService) -> None:
        self.service = service
        self._cursor: str | None = None
        self._tick = threading.Lock()

    def advance_once(self) -> KakaoConceptContinuation:
        if not self._tick.acquire(blocking=False):
            return KakaoConceptContinuation(None, "WAITING")
        task_id = None
        try:
            with self.service.sessions() as session:
                candidate = session.execute(
                    ready_kakao_concept_continuations(after=self._cursor)
                ).first()
            if candidate is None:
                self._cursor = None
                return KakaoConceptContinuation(None, "IDLE")
            task_id, owner = candidate
            # A source refusal must not starve other accepted tasks. This is not durable state.
            self._cursor = task_id
            authority = self.service.accepted_source_authority(task_id=task_id, operator_id=owner)
            completed = read_kakao_concept_phase_result(authority, "PLAN")
            if not isinstance(completed.result.output.output, ConceptPlan):
                raise KakaoArchiveError("KAKAO_CONCEPT_PLAN_RESULT_MISMATCH")
            if completed.result.output.output.status != "PLANNED":
                return KakaoConceptContinuation(task_id, "NEEDS_INPUT")
            definition, preset = read_kakao_concept_submission_runtime(
                self.service, authority=authority
            )
            current_definition, current = read_kakao_concept_submission_runtime(self.service)
            if (
                definition.definition_hash != current_definition.definition_hash
                or preset != current
            ):
                raise ControlPlaneError(
                    "CONTROL_PRESET_POINTER_STALE", "accepted concept preset changed"
                )
            # Original page reads/crop/publication happen outside the submission transaction.
            work = self.service.prepare_accepted_compose(authority)
            submitted = submit_accepted_kakao_concept_phase(
                authority, work=work, definition=definition, expected_preset=preset
            )
            return KakaoConceptContinuation(task_id, "SUBMITTED", submitted.workflow_id)
        except (KakaoArchiveError, ControlPlaneError) as error:
            return KakaoConceptContinuation(task_id, "ERROR", error_code=error.code)
        except Exception:
            # Existing phase/Artifact/Workflow identity remains recoverable; no model auto-retry.
            return KakaoConceptContinuation(
                task_id, "ERROR", error_code="KAKAO_CONCEPT_CONTINUATION_FAILED"
            )
        finally:
            self._tick.release()
