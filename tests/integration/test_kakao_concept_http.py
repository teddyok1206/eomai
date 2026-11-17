"""Actual BFF/API/UDS/source DB and canonical results; synthetic worker and textbook discovery."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_service.kakao_concept_continuation import KakaoConceptCoordinator
from eom_identifiers import sha256_bytes
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.models import JobRecord
from eom_orchestrator.repository import submit_structured_job
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.models import RoleWorkerInput
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import create_step_run
from eom_workflow_runner.role_execution_binding import bind_platform_role_job
from eom_workflow_runner.state_machine import StepState, transition_step
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_kakao_concept_task_storage import (
    _complete_synthetic_concept_plan,
)
from tests.integration.test_kakao_concept_task_storage import (
    concept_composition_store as concept_composition_store,
)
from tests.integration.test_kakao_concept_task_storage import (
    concept_execution_store as concept_execution_store,
)
from tests.integration.test_kakao_concept_task_storage import (
    concept_store as concept_store,
)
from tests.integration.test_kakao_question_http import question_api, studio_api
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
BASE = "/studio/api/v1/kakao-archive/concepts"


def test_real_public_start_replay_progress_history_and_no_get_execution(
    concept_execution_store, tmp_path
):
    value = concept_execution_store
    task, intent = value.service.get_intent(
        value.actor, value.work.source_binding_id, value.work.task_id
    )
    with Session(value.engine) as session:
        from eom_catalog_service.kakao_concept_models import KakaoConceptTaskRecord

        key = session.get(KakaoConceptTaskRecord, task.task_id).idempotency_key
        before = session.scalar(select(func.count()).select_from(WorkflowCommandRecord))
    coordinator = KakaoConceptCoordinator(value.service)
    with (
        question_api(
            value.store, tmp_path, concepts=value.service, concept_coordinator=coordinator
        ) as (api, _, _),
        studio_api(api, value.actor.operator_id) as (web, csrf),
    ):
        body = intent.request.model_dump(mode="json")
        headers = {"Idempotency-Key": key, "X-CSRF-Token": csrf}
        assert web.post(BASE, json=body, headers={"Idempotency-Key": key}).status_code == 403
        first = web.post(BASE, json=body, headers=headers)
        assert first.status_code == 202, first.text
        assert first.json()["task"]["task_id"] == task.task_id and first.json()["replayed"]
        assert web.post(BASE, json=body, headers=headers).json() == first.json()
        wrong = {**body, "additional_instructions": "different"}
        assert web.post(BASE, json=wrong, headers=headers).status_code == 409
        params = {"source_binding_id": task.source_binding_id}
        for _ in range(2):
            read = web.get(BASE + "/" + task.task_id, params=params)
            assert read.status_code == 200, read.text
            assert read.json()["state"] == "PLAN_PENDING"
            assert not read.json()["blocks"] and read.json()["result_sha256"] is None
        history = web.get(BASE, params=params)
        assert history.status_code == 200, history.text
        assert [item["task_id"] for item in history.json()["items"]] == [task.task_id]
        _complete_synthetic_concept_plan(value)
        read = web.get(BASE + "/" + task.task_id, params=params)
        assert read.status_code == 200 and read.json()["state"] == "SEARCHING", read.text
        assert web.get(BASE + "/" + task.task_id + "/pages/E1P1", params=params).status_code == 409
    with Session(value.engine) as session:
        assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == before
        assert session.get(WorkflowInstanceRecord, value.submitted.workflow_id).state == "COMPLETED"


def compose_worker(value, work, submitted):
    """Stage a new successful synthetic child, not a state rewrite of any failed work."""
    with Session(value.engine, expire_on_commit=False) as session, session.begin():
        row = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == submitted.workflow_id
            )
        )
        pinned = KakaoConceptExecutionPlan.model_validate(row.canonical_document)
        step = create_step_run(
            session,
            workflow_id=submitted.workflow_id,
            step_key="assist",
            step_type="agent",
            worker_role="support",
            result_schema="kakao-concepts-result@1.0",
            input_pointer_manifest={},
            max_attempts=1,
        )
        worker = RoleWorkerInput(
            protocol_version="workflow-role/1.41.0",
            job_id="job_" + uuid4().hex,
            workflow_id=submitted.workflow_id,
            step_run_id=step.step_run_id,
            attempt=1,
            role="support",
            request={
                "request_name": "KAKAO_CONCEPT_REQUEST",
                "work_input": work.model_dump(mode="json"),
            },
            upstream_artifacts=(),
            artifact={
                "logical_artifact_id": "artifact_" + uuid4().hex,
                "revision_id": "rev_" + uuid4().hex,
            },
        )
        job, _ = submit_structured_job(
            session,
            job_id=worker.job_id,
            protocol_version=worker.protocol_version,
            idempotency_key="concept-http-child-" + uuid4().hex,
            task_type="workflow_support",
            request=worker.model_dump(mode="json"),
            logical_artifact_id=worker.artifact.logical_artifact_id,
            revision_id=worker.artifact.revision_id,
        )
        transition_job(session, job.job_id, JobState.VALIDATED, "SYNTHETIC_VALIDATED")
        transition_job(session, job.job_id, JobState.QUEUED, "SYNTHETIC_QUEUED")
        transition_step(step, StepState.RUNNING)
        bind_platform_role_job(
            session,
            workflow_id=submitted.workflow_id,
            step_run_id=step.step_run_id,
            step_key="assist",
            attempt=1,
            worker_role="support",
            job_id=job.job_id,
        )
    return SimpleNamespace(
        **{
            **vars(value),
            "work": work,
            "submitted": submitted,
            "pinned": pinned,
            "worker": worker,
            "selection": SimpleNamespace(step_run_id=step.step_run_id),
        }
    )


def test_canonical_composition_and_original_png_via_studio_without_new_inference(
    concept_composition_store, tmp_path
):
    from eom_catalog_service.kakao_concept_models import KakaoConceptPhaseRecord
    from eom_catalog_service.kakao_concept_workflow_submission import (
        read_kakao_concept_submission_runtime,
        submit_accepted_kakao_concept_phase,
    )

    value, reader, original = concept_composition_store
    task_id, binding = value.work.task_id, value.work.source_binding_id
    authority = value.service.source_authority(value.actor, binding, task_id)
    work = value.service.prepare_compose(value.actor, binding, task_id)
    definition, preset = read_kakao_concept_submission_runtime(value.service, authority=authority)
    submitted = submit_accepted_kakao_concept_phase(
        authority, work=work, definition=definition, expected_preset=preset
    )
    child = compose_worker(value, work, submitted)
    result = {
        "phase": "COMPOSE",
        "status": "DRAFT_READY",
        "focus_summary": "합성 질문의 기초 개념",
        "blocks": [
            {
                "title": "기초 개념",
                "relevance": "합성 질문과의 연결",
                "explanation": "검증된 교재 설명을 참고합니다.",
                "citations": [{"evidence_key": "E1", "passage_key": None, "quote": None}],
                "captures": [
                    {
                        "page_key": "E1P1",
                        "rectangle": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
                        "reason": "원본 그림",
                    }
                ],
            }
        ],
        "staff_checks": [],
        "limitations": [],
    }
    _complete_synthetic_concept_plan(child, output=result)
    with (
        question_api(
            value.store,
            tmp_path,
            concepts=value.service,
            concept_coordinator=KakaoConceptCoordinator(value.service),
        ) as (api, _, _),
        studio_api(api, value.actor.operator_id) as (web, _csrf),
    ):
        params = {"source_binding_id": binding}
        for _ in range(2):
            read = web.get(BASE + "/" + task_id, params=params)
            assert read.status_code == 200, read.text
            body = read.json()
            assert body["state"] == "COMPLETED" and body["result_sha256"]
            assert body["blocks"][0]["captures"][0]["physical_page"] == 1
            assert "work_input" not in read.text and "relative_path" not in read.text
            image = web.get(BASE + "/" + task_id + "/pages/E1P1", params=params)
            assert image.status_code == 200, image.text
            assert sha256_bytes(image.content) == original.sha256
        assert web.get(BASE + "/" + task_id + "/pages/E1P2", params=params).status_code == 409
    reader.retrieve.assert_called_once()
    with Session(value.engine) as session:
        phase = session.get(KakaoConceptPhaseRecord, (task_id, "COMPOSE"))
        assert phase.workflow_id == submitted.workflow_id
        assert session.get(JobRecord, child.worker.job_id).status == "SUCCEEDED"
