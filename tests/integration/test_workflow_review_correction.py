"""Database-backed bounded correction of committed reviewer routing metadata."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest
from eom_catalog_contracts import ContentTeamMaterialRequirementV1
from eom_identifiers import content_sha256, new_job_id
from eom_orchestrator.database import transaction
from eom_orchestrator.models import JobRecord
from eom_workflow import (
    ArtifactPointer,
    KnowledgeAnalysisWorkerRequest,
    LegacyItemEditorialCompatibilityWorkerRequest,
    LegacyItemExtractionWorkerRequest,
    ReviewPolicyCorrection,
    ReviewPolicyCorrectionRequired,
    ReviewRoutingPolicyValues,
    WorkerRequest,
    WorkflowRequest,
    WorkflowReviewCorrectionDirective,
    WorkflowReviewEscalationDirective,
)
from eom_workflow.control_plane import ResolvedStepExecutionV12
from eom_workflow_runner.catalog_port import RegistrationOutcome
from eom_workflow_runner.engine import RoleExecutionResult, RoleJobExecutor, WorkflowRunner
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    enqueue_command,
    list_step_runs,
    list_workflow_events,
)
from eom_workflow_runner.state_machine import CommandState, StepState, WorkflowState
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_workflow_engine import (
    ROLE_SLOTS,
    FailedRoleExecutor,
    FakeRoleExecutor,
    FakeWorkflowCatalog,
    ReadyWorkflowRuntime,
    _close,
    _environment,
    _static_actor_authorizer,
    _verification_review_plan_step,
    _workflow_settings,
)

pytestmark = pytest.mark.integration
DEFINITION = Path("config/workflows/generic-item-development.v1.16.yaml")


class RoutingCorrectionCatalog(FakeWorkflowCatalog):
    """Model independent, workflow-keyed classifier inputs at the existing Catalog port."""

    def __init__(self, *, invalid_results: int, escalate: bool = False) -> None:
        super().__init__()
        self.invalid_results = invalid_results
        self.escalate_primary_review = escalate
        self.classified: list[tuple[ArtifactPointer, ...]] = []
        self.registration_inputs: list[tuple[ArtifactPointer, ...]] = []

    def classify_review_escalation(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        artifacts: tuple[ArtifactPointer, ...],
        plan_step: ResolvedStepExecutionV12,
        source_directive: WorkflowReviewEscalationDirective | None,
    ) -> WorkflowReviewEscalationDirective | None:
        self.classified.append(artifacts)
        if self.escalate_primary_review and source_directive is None:
            return super().classify_review_escalation(
                workflow=workflow,
                artifacts=artifacts,
                plan_step=plan_step,
                source_directive=source_directive,
            )
        if self.invalid_results:
            self.invalid_results -= 1
            score = 4 if source_directive is not None else 1
            expected = ReviewRoutingPolicyValues(
                structural_complexity_score=score,
                reason_codes=("COMPLEX_ITEM",) if source_directive is not None else (),
                decision="COMPLETED" if source_directive is not None else "NOT_REQUIRED",
            )
            raise ReviewPolicyCorrectionRequired(
                ReviewPolicyCorrection(
                    code="REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH",
                    expected=expected,
                    observed=expected.model_copy(update={"structural_complexity_score": score + 1}),
                )
            )
        return super().classify_review_escalation(
            workflow=workflow,
            artifacts=artifacts,
            plan_step=plan_step,
            source_directive=source_directive,
        )

    def register_workflow(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> RegistrationOutcome:
        self.registration_inputs.append(artifacts)
        return super().register_workflow(
            workflow=workflow,
            step=step,
            request=request,
            artifacts=artifacts,
        )


class BoundFakeRoleExecutor(FakeRoleExecutor):
    """Model the actual adapter's persisted step→job binding before post-result policy."""

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: (
            WorkerRequest
            | KnowledgeAnalysisWorkerRequest
            | LegacyItemExtractionWorkerRequest
            | LegacyItemEditorialCompatibilityWorkerRequest
        ),
        upstream: tuple[ArtifactPointer, ...],
        idempotency_key: str,
        prompt_text: str | None,
        material_requirement: ContentTeamMaterialRequirementV1 | None,
    ) -> RoleExecutionResult:
        result = super().execute(
            workflow=workflow,
            step=step,
            request=request,
            upstream=upstream,
            idempotency_key=idempotency_key,
            prompt_text=prompt_text,
            material_requirement=material_requirement,
        )
        with transaction(self.sessions) as session:
            current = session.get(WorkflowStepRunRecord, step.step_run_id)
            assert current is not None
            assert current.platform_job_id in (None, result.job_id)
            current.platform_job_id = result.job_id
        return result


class FailFirstCorrectionExecution(BoundFakeRoleExecutor):
    """A proven pre-commit transport failure is not another committed correction proof."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        super().__init__(sessions)
        self.failed = False
        self.correction_inputs: list[dict[str, object]] = []

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: (
            WorkerRequest
            | KnowledgeAnalysisWorkerRequest
            | LegacyItemExtractionWorkerRequest
            | LegacyItemEditorialCompatibilityWorkerRequest
        ),
        upstream: tuple[ArtifactPointer, ...],
        idempotency_key: str,
        prompt_text: str | None,
        material_requirement: ContentTeamMaterialRequirementV1 | None,
    ) -> RoleExecutionResult:
        correction = step.input_pointer_manifest.get("review_correction_directive")
        if step.step_key == "review" and isinstance(correction, dict):
            self.correction_inputs.append(step.input_pointer_manifest)
            if not self.failed:
                self.failed = True
                self.calls.append((step.step_key, step.attempt, "review"))
                return FailedRoleExecutor(self.sessions).execute(
                    workflow=workflow,
                    step=step,
                    request=request,
                    upstream=upstream,
                    idempotency_key=idempotency_key,
                    prompt_text=prompt_text,
                    material_requirement=material_requirement,
                )
        return super().execute(
            workflow=workflow,
            step=step,
            request=request,
            upstream=upstream,
            idempotency_key=idempotency_key,
            prompt_text=prompt_text,
            material_requirement=material_requirement,
        )


def _configure(
    runner: WorkflowRunner,
    catalog: RoutingCorrectionCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> BoundFakeRoleExecutor:
    runner.catalog = catalog
    if not isinstance(runner.executor, BoundFakeRoleExecutor):
        runner.executor = cast(RoleJobExecutor, BoundFakeRoleExecutor(runner.sessions))
    monkeypatch.setattr(
        runner, "_resolved_v12_review_step", lambda _workflow: _verification_review_plan_step()
    )
    return cast(BoundFakeRoleExecutor, runner.executor)


def _steps(session: Session, workflow_id: str, key: str) -> list[WorkflowStepRunRecord]:
    return [step for step in list_step_runs(session, workflow_id) if step.step_key == key]


@pytest.mark.parametrize("invalid_results", (1, 2))
@pytest.mark.parametrize("image_count", (0, 1))
def test_second_or_third_corrected_proof_registers_without_reauthoring(
    integration_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    invalid_results: int,
    image_count: int,
) -> None:
    runner, executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        f"review-correction-success-{invalid_results}-{image_count}",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=invalid_results)
    catalog.content_team_image_count = image_count
    executor = _configure(runner, catalog, monkeypatch)
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            assert workflow.state == WorkflowState.COMPLETED.value
            assert workflow.rework_cycle_count == 0
            authoring = _steps(session, workflow_id, "authoring")
            images = _steps(session, workflow_id, "image")
            reviews = _steps(session, workflow_id, "review")
            assert len(authoring) == 1
            assert len(images) == 1
            assert images[0].state == (
                StepState.SUCCEEDED.value if image_count else StepState.SKIPPED.value
            )
            assert len(reviews) == invalid_results + 1
            assert [step.state for step in reviews] == [
                *([StepState.FAILED.value] * invalid_results),
                StepState.SUCCEEDED.value,
            ]
            original_inputs = reviews[0].input_pointer_manifest["upstream_artifacts"]
            for index, rejected in enumerate(reviews[:-1], start=1):
                assert rejected.output_pointer_manifest is not None
                job = session.get(JobRecord, rejected.platform_job_id)
                assert job is not None and job.status == "SUCCEEDED"
                successor = reviews[index]
                assert rejected.superseded_by_step_run_id == successor.step_run_id
                directive = WorkflowReviewCorrectionDirective.model_validate(
                    successor.input_pointer_manifest["review_correction_directive"]
                )
                assert directive.source_review.model_dump(mode="json") == (
                    rejected.output_pointer_manifest
                )
                assert directive.reviewed_authoring.model_dump(mode="json") == (
                    authoring[0].output_pointer_manifest
                )
                assert directive.pass_number == index + 1
                assert directive.issue.expected.structural_complexity_score == 1
                assert directive.issue.observed.structural_complexity_score == 2
                assert successor.input_pointer_manifest["upstream_artifacts"] == original_inputs
            final_review = next(
                pointer
                for pointer in catalog.registration_inputs[0]
                if pointer.step_key == "review"
            )
            assert final_review.model_dump(mode="json") == reviews[-1].output_pointer_manifest
            rejected_revisions = {
                step.output_pointer_manifest["revision_id"]
                for step in reviews[:-1]
                if step.output_pointer_manifest is not None
            }
            assert final_review.revision_id not in rejected_revisions
        assert Counter(role for _key, _attempt, role in executor.calls) == {
            "authoring": 1,
            "review": invalid_results + 1,
            "item_management": 1,
            **({"image": 1} if image_count else {}),
        }
        assert len(catalog.registrations) == 1
    finally:
        _close(resources)


def test_third_invalid_proof_exhausts_specific_budget_not_ten_transport_attempts(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        "review-correction-exhausted",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=10)
    executor = _configure(runner, catalog, monkeypatch)
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            assert workflow.state == WorkflowState.FAILED.value
            assert workflow.failure_code == "WORKFLOW_REVIEW_CORRECTION_EXHAUSTED"
            assert workflow.rework_cycle_count == 0
            reviews = _steps(session, workflow_id, "review")
            assert [step.attempt for step in reviews] == [1, 2, 3]
            assert all(step.output_pointer_manifest is not None for step in reviews)
            assert all(step.state == StepState.FAILED.value for step in reviews)
            assert reviews[-1].superseded_by_step_run_id is None
        assert [attempt for key, attempt, _role in executor.calls if key == "review"] == [1, 2, 3]
        assert catalog.registrations == []
    finally:
        _close(resources)


@pytest.mark.parametrize("escalate", (False, True))
@pytest.mark.parametrize("invalid_results", (1, 2))
def test_transport_retry_keeps_exact_correction_directive_and_proof_number(
    integration_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    escalate: bool,
    invalid_results: int,
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        f"review-correction-precommit-{escalate}-{invalid_results}",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=invalid_results, escalate=escalate)
    executor = FailFirstCorrectionExecution(sessions)
    # The established fake fixture is intentionally limited to this Item-only protocol family.
    runner.executor = cast(RoleJobExecutor, executor)
    executor = cast(FailFirstCorrectionExecution, _configure(runner, catalog, monkeypatch))
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.COMPLETED.value
            assert workflow.rework_cycle_count == 0
            reviews = _steps(session, workflow_id, "review")
            assert len(reviews) == invalid_results + 2 + int(escalate)
            assert reviews[-1].state == StepState.SUCCEEDED.value
        assert len(executor.correction_inputs) == invalid_results + 1
        first, retried = executor.correction_inputs[:2]
        assert first["review_correction_directive"] == retried["review_correction_directive"]
        directive = WorkflowReviewCorrectionDirective.model_validate(
            retried["review_correction_directive"]
        )
        assert directive.pass_number == 2
        assert directive.review_pass == ("ESCALATED" if escalate else "PRIMARY")
        assert first["upstream_artifacts"] == retried["upstream_artifacts"]
        if escalate:
            assert first["review_escalation_directive"] == retried["review_escalation_directive"]
        if invalid_results == 2:
            third = WorkflowReviewCorrectionDirective.model_validate(
                executor.correction_inputs[-1]["review_correction_directive"]
            )
            assert third.pass_number == 3
            assert third.source_attempt == (4 if escalate else 3)
            assert third.next_attempt == (5 if escalate else 4)
        assert Counter(role for _key, _attempt, role in executor.calls)["authoring"] == 1
        assert len(catalog.registration_inputs) == 1
    finally:
        _close(resources)


def test_escalated_review_correction_preserves_original_primary_tier_source(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        "review-correction-escalated-source",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=2, escalate=True)
    executor = _configure(runner, catalog, monkeypatch)
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.COMPLETED.value
            reviews = _steps(session, workflow_id, "review")
            assert [step.attempt for step in reviews] == [1, 2, 3, 4]
            assert reviews[0].state == StepState.SUPERSEDED.value
            original_escalation = reviews[1].input_pointer_manifest["review_escalation_directive"]
            for index in (2, 3):
                manifest = reviews[index].input_pointer_manifest
                assert manifest["review_escalation_directive"] == original_escalation
                directive = WorkflowReviewCorrectionDirective.model_validate(
                    manifest["review_correction_directive"]
                )
                assert directive.review_pass == "ESCALATED"
                assert directive.pass_number == index
                assert directive.issue.expected.decision == "COMPLETED"
                assert directive.issue.expected.reason_codes == ("COMPLEX_ITEM",)
                sources = [p for p in manifest["upstream_artifacts"] if p["step_key"] == "review"]
                assert sources == [reviews[0].output_pointer_manifest]
            assert len(workflow.runtime_context["review_escalation_history"]) == 1
            assert workflow.rework_cycle_count == 0
        assert Counter(role for _key, _attempt, role in executor.calls)["authoring"] == 1
    finally:
        _close(resources)


def test_ordinary_catalog_value_error_remains_fail_closed_without_correction(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        "review-correction-untrusted-pointer",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=0)
    executor = _configure(runner, catalog, monkeypatch)

    def invalid_pointer(**_kwargs: object) -> None:
        raise ValueError("review escalation source pointer differs")

    monkeypatch.setattr(catalog, "classify_review_escalation", invalid_pointer)
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.FAILED.value
            assert workflow.failure_code == "WORKFLOW_STEP_FAILED"
            assert len(_steps(session, workflow_id, "review")) == 1
        assert Counter(role for _key, _attempt, role in executor.calls)["review"] == 1
        assert catalog.registrations == []
    finally:
        _close(resources)


def test_completed_correction_command_replay_cannot_create_another_review(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        "review-correction-command-replay",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=1)
    executor = _configure(runner, catalog, monkeypatch)
    try:
        runner.run_until_idle(workflow_id)
        original_calls = tuple(executor.calls)
        with transaction(sessions) as session:
            command = session.scalar(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow_id,
                    WorkflowCommandRecord.command_type == CommandType.ADVANCE_WORKFLOW.value,
                )
            )
            assert command is not None
            replay, created = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.ADVANCE_WORKFLOW,
                payload=command.payload,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                source=command.source,
                idempotency_key=command.idempotency_key,
            )
            assert not created
            assert replay.command_id == command.command_id
            assert replay.state == CommandState.SUCCEEDED.value
        assert runner.run_until_idle(workflow_id) == 0
        assert tuple(executor.calls) == original_calls
    finally:
        _close(resources)


def test_process_crash_after_review_commit_reuses_the_same_job_before_correction(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        "review-correction-crash-after-commit",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=1)
    _configure(runner, catalog, monkeypatch)
    classifier = catalog.classify_review_escalation
    crashed = False

    def crash_once(
        *,
        workflow: WorkflowInstanceRecord,
        artifacts: tuple[ArtifactPointer, ...],
        plan_step: ResolvedStepExecutionV12,
        source_directive: WorkflowReviewEscalationDirective | None,
    ) -> WorkflowReviewEscalationDirective | None:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise SystemExit("isolated process-loss fixture after platform commit")
        return classifier(
            workflow=workflow,
            artifacts=artifacts,
            plan_step=plan_step,
            source_directive=source_directive,
        )

    monkeypatch.setattr(catalog, "classify_review_escalation", crash_once)
    try:
        with pytest.raises(SystemExit):
            runner.run_once(workflow_id)
        with transaction(sessions) as session:
            command = session.scalar(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow_id,
                    WorkflowCommandRecord.state == CommandState.PROCESSING.value,
                )
            )
            assert command is not None
            # Expiry is injected only in this isolated fixture; recovery itself uses the normal
            # claim/lease fence rather than editing a production command or workflow outcome.
            command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            committed = session.scalar(
                select(JobRecord).where(
                    JobRecord.request["workflow_id"].astext == workflow_id,
                    JobRecord.task_type == "workflow_review",
                )
            )
            assert committed is not None and committed.status == "SUCCEEDED"
            source_job_id = committed.job_id
            source_revision_id = committed.revision_id
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.COMPLETED.value
            reviews = _steps(session, workflow_id, "review")
            assert [step.attempt for step in reviews] == [1, 2]
            assert reviews[0].platform_job_id == source_job_id
            assert reviews[0].output_pointer_manifest is not None
            assert reviews[0].output_pointer_manifest["revision_id"] == source_revision_id
            jobs = session.scalars(
                select(JobRecord).where(
                    JobRecord.request["workflow_id"].astext == workflow_id,
                    JobRecord.task_type == "workflow_review",
                )
            ).all()
            assert len(jobs) == 2
            directive = WorkflowReviewCorrectionDirective.model_validate(
                reviews[1].input_pointer_manifest["review_correction_directive"]
            )
            assert directive.source_review.job_id == source_job_id
            assert directive.pass_number == 2
        assert len(catalog.registrations) == 1
    finally:
        _close(resources)


@pytest.mark.parametrize(
    "corruption", ("hash", "job", "budget_reset", "missing_retry_event", "image_pin", "tier")
)
def test_corrupt_correction_binding_fails_closed_before_another_worker_execution(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        f"review-correction-corrupt-{corruption}",
        definition_path=DEFINITION,
    )
    catalog = RoutingCorrectionCatalog(invalid_results=2 if corruption == "budget_reset" else 1)
    catalog.content_team_image_count = 1
    if corruption == "missing_retry_event":
        runner.executor = cast(RoleJobExecutor, FailFirstCorrectionExecution(sessions))
    executor = _configure(runner, catalog, monkeypatch)
    try:
        assert runner.run_once(workflow_id) is not None
        if corruption in {"budget_reset", "missing_retry_event"}:
            assert runner.run_once(workflow_id) is not None
        before_calls = tuple(executor.calls)
        with transaction(sessions) as session:
            reviews = _steps(session, workflow_id, "review")
            ready = reviews[-1]
            assert ready.state == StepState.READY.value
            manifest = dict(ready.input_pointer_manifest)
            raw = dict(manifest["review_correction_directive"])
            if corruption in {"hash", "job"}:
                source = dict(raw["source_review"])
                if corruption == "hash":
                    source["content_hash"] = "sha256:" + "f" * 64
                else:
                    source["job_id"] = new_job_id()
                raw["source_review"] = source
            elif corruption == "budget_reset":
                assert raw["pass_number"] == 3
                raw["pass_number"] = 2
            elif corruption == "tier":
                raw["review_pass"] = "ESCALATED"
                issue = dict(raw["issue"])
                expected = dict(issue["expected"])
                expected["reason_codes"] = ["COMPLEX_ITEM"]
                expected["decision"] = "COMPLETED"
                issue["expected"] = expected
                raw["issue"] = issue
            elif corruption == "image_pin":
                upstream = [dict(pointer) for pointer in manifest["upstream_artifacts"]]
                image = next(pointer for pointer in upstream if pointer["step_key"] == "image")
                image["content_hash"] = "sha256:" + "f" * 64
                manifest["upstream_artifacts"] = upstream
            else:
                event = session.scalar(
                    select(WorkflowEventRecord).where(
                        WorkflowEventRecord.workflow_id == workflow_id,
                        WorkflowEventRecord.event_type == "STEP_RETRY_SCHEDULED",
                    )
                )
                assert event is not None
                # Deliberate corruption is restricted to this disposable fixture; runtime never
                # deletes historical events or repairs persistent state with a direct row update.
                session.delete(event)
            raw["decision_sha256"] = content_sha256(
                {key: value for key, value in raw.items() if key != "decision_sha256"}
            )
            directive = WorkflowReviewCorrectionDirective.model_validate(raw)
            manifest["review_correction_directive"] = directive.model_dump(mode="json")
            ready.input_pointer_manifest = manifest
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.FAILED.value
            assert workflow.failure_code in {
                "WORKFLOW_STEP_FAILED",
                "WORKFLOW_RECONCILIATION_FAILED",
            }
            assert _steps(session, workflow_id, "review")[-1].state == StepState.FAILED.value
            assert workflow.rework_cycle_count == 0
        assert tuple(executor.calls) == before_calls
        assert catalog.registration_inputs == []
    finally:
        _close(resources)


def test_concurrent_runners_reuse_one_correction_successor_and_registration(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This case deliberately uses independent connections: a savepoint-bound fixture cannot
    # demonstrate PostgreSQL concurrent claim/lease fencing. All writes target the disposable DB.
    setup, _fake, setup_sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        f"review-correction-concurrent-{uuid4().hex}",
        definition_path=DEFINITION,
    )
    del setup, _fake, setup_sessions
    connection, outer = resources
    outer.commit()
    connection.close()
    sessions = sessionmaker(bind=integration_engine, expire_on_commit=False)
    catalog = RoutingCorrectionCatalog(invalid_results=1)
    executor = BoundFakeRoleExecutor(sessions)
    runners = tuple(
        WorkflowRunner(
            integration_engine,
            _workflow_settings(),
            cast(RoleJobExecutor, executor),
            catalog=catalog,
            actor_authorizer=_static_actor_authorizer(),
            readiness=ReadyWorkflowRuntime(),
            available_roles=frozenset(ROLE_SLOTS) | {"support"},
            runner_id=f"correction-concurrency-{index}-{uuid4().hex}",
        )
        for index in range(2)
    )
    for runner in runners:
        _configure(runner, catalog, monkeypatch)
    try:
        # First committed invalid proof atomically records one ready successor/advance command.
        assert runners[0].run_once(workflow_id) is not None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda runner: runner.run_once(workflow_id), runners))
        assert sum(result is not None for result in results) == 1
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.COMPLETED.value
            assert len(_steps(session, workflow_id, "review")) == 2
            assert len(_steps(session, workflow_id, "authoring")) == 1
            assert len(_steps(session, workflow_id, "registration")) == 1
        assert Counter(role for _key, _attempt, role in executor.calls)["review"] == 2
        assert len(catalog.registration_inputs) == 1
    finally:
        # Immutable Job/Artifact evidence is retained until the disposable database is removed.
        with integration_engine.begin() as db_connection:
            db_connection.execute(
                delete(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.workflow_id == workflow_id
                )
            )


def test_two_distinct_commands_classifying_the_same_rejected_review_adopt_one_successor(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, _fake, _sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        f"review-correction-overlapping-{uuid4().hex}",
        definition_path=DEFINITION,
    )
    del setup, _fake, _sessions
    connection, outer = resources
    outer.commit()
    connection.close()
    sessions = sessionmaker(bind=integration_engine, expire_on_commit=False)
    catalog = RoutingCorrectionCatalog(invalid_results=0)
    executor = BoundFakeRoleExecutor(sessions)
    runners = tuple(
        WorkflowRunner(
            integration_engine,
            _workflow_settings(),
            cast(RoleJobExecutor, executor),
            catalog=catalog,
            actor_authorizer=_static_actor_authorizer(),
            readiness=ReadyWorkflowRuntime(),
            available_roles=frozenset(ROLE_SLOTS) | {"support"},
            runner_id=f"correction-overlapping-{index}-{uuid4().hex}",
        )
        for index in range(2)
    )
    for runner in runners:
        _configure(runner, catalog, monkeypatch)
    classifier = catalog.classify_review_escalation
    barrier = Barrier(2)

    def interrupted(**_kwargs: object) -> None:
        raise SystemExit("isolated committed-review seed before policy classification")

    def overlapping_classification(
        *,
        workflow: WorkflowInstanceRecord,
        artifacts: tuple[ArtifactPointer, ...],
        plan_step: ResolvedStepExecutionV12,
        source_directive: WorkflowReviewEscalationDirective | None,
    ) -> WorkflowReviewEscalationDirective | None:
        review = next(pointer for pointer in artifacts if pointer.step_key == "review")
        if review.attempt == 1:
            barrier.wait(timeout=10)
            expected = ReviewRoutingPolicyValues(
                structural_complexity_score=1, reason_codes=(), decision="NOT_REQUIRED"
            )
            raise ReviewPolicyCorrectionRequired(
                ReviewPolicyCorrection(
                    code="REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH",
                    expected=expected,
                    observed=expected.model_copy(update={"structural_complexity_score": 2}),
                )
            )
        return classifier(
            workflow=workflow,
            artifacts=artifacts,
            plan_step=plan_step,
            source_directive=source_directive,
        )

    try:
        monkeypatch.setattr(catalog, "classify_review_escalation", interrupted)
        with pytest.raises(SystemExit):
            runners[0].run_once(workflow_id)
        monkeypatch.setattr(catalog, "classify_review_escalation", overlapping_classification)
        with transaction(sessions) as session:
            command_ids = []
            for index in range(2):
                command, created = enqueue_command(
                    session,
                    workflow_id=workflow_id,
                    command_type=CommandType.ADVANCE_WORKFLOW,
                    payload={"reason": "isolated-concurrent-policy-replay"},
                    actor_type="system",
                    actor_id="fixture-concurrent-review",
                    source="test",
                    idempotency_key=f"overlap-correction:{workflow_id}:{index}",
                )
                assert created
                command_ids.append(command.command_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            commands = tuple(pool.map(lambda runner: runner.run_once(workflow_id), runners))
        assert {command.command_id for command in commands if command is not None} == set(
            command_ids
        )
        assert all(command is not None and command.state == "SUCCEEDED" for command in commands)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.RUNNING.value
            assert workflow.failure_code is None
            reviews = _steps(session, workflow_id, "review")
            assert [step.attempt for step in reviews] == [1, 2]
            assert reviews[0].error_code == "REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH"
            assert reviews[0].superseded_by_step_run_id == reviews[1].step_run_id
            events = list_workflow_events(session, workflow_id)
            assert sum(event.event_type == "REVIEW_CORRECTION_SCHEDULED" for event in events) == 1
        runners[0].run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.COMPLETED.value
            assert len(_steps(session, workflow_id, "review")) == 2
            review_jobs = session.scalars(
                select(JobRecord).where(
                    JobRecord.request["workflow_id"].astext == workflow_id,
                    JobRecord.task_type == "workflow_review",
                )
            ).all()
            assert len(review_jobs) == 2
        assert len(catalog.registration_inputs) == 1
    finally:
        with integration_engine.begin() as db_connection:
            db_connection.execute(
                delete(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.workflow_id == workflow_id
                )
            )


def test_corrected_review_enters_existing_authoring_rework_with_a_new_draft_proof_budget(
    integration_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CorrectEachDraftOnce(RoutingCorrectionCatalog):
        def __init__(self) -> None:
            super().__init__(invalid_results=0)
            self.seen_authoring: set[int] = set()

        def classify_review_escalation(
            self,
            *,
            workflow: WorkflowInstanceRecord,
            artifacts: tuple[ArtifactPointer, ...],
            plan_step: ResolvedStepExecutionV12,
            source_directive: WorkflowReviewEscalationDirective | None,
        ) -> WorkflowReviewEscalationDirective | None:
            authoring = next(pointer for pointer in artifacts if pointer.step_key == "authoring")
            if authoring.attempt not in self.seen_authoring:
                self.seen_authoring.add(authoring.attempt)
                self.invalid_results = 1
            return super().classify_review_escalation(
                workflow=workflow,
                artifacts=artifacts,
                plan_step=plan_step,
                source_directive=source_directive,
            )

    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine,
        "skip",
        "review-correction-then-content-rework",
        definition_path=DEFINITION,
    )
    catalog = CorrectEachDraftOnce()
    catalog.review_blocking_codes_by_cycle = [("DIFFICULTY_MISMATCH",), ()]
    executor = _configure(runner, catalog, monkeypatch)
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.state == WorkflowState.COMPLETED.value
            assert workflow.rework_cycle_count == 1
            authoring = _steps(session, workflow_id, "authoring")
            reviews = _steps(session, workflow_id, "review")
            assert [step.attempt for step in authoring] == [1, 2]
            assert [step.attempt for step in reviews] == [1, 2, 3, 4]
            directives = tuple(
                WorkflowReviewCorrectionDirective.model_validate(
                    step.input_pointer_manifest["review_correction_directive"]
                )
                for step in (reviews[1], reviews[3])
            )
            assert [directive.pass_number for directive in directives] == [2, 2]
            assert [directive.reviewed_authoring.attempt for directive in directives] == [1, 2]
            history = workflow.runtime_context["review_rework_history"]
            assert [entry["outcome"] for entry in history] == [
                "REWORK_AUTHORING",
                "READY_FOR_HUMAN",
            ]
            assert history[0]["source_review"] == reviews[1].output_pointer_manifest
            assert history[1]["source_review"] == reviews[3].output_pointer_manifest
            content_feedback = authoring[1].input_pointer_manifest["review_rework_directive"]
            assert content_feedback["source_review"] == reviews[1].output_pointer_manifest
            registration_by_key = {
                pointer.step_key: pointer for pointer in catalog.registration_inputs[0]
            }
            assert registration_by_key["authoring"].model_dump(mode="json") == (
                authoring[-1].output_pointer_manifest
            )
            assert registration_by_key["review"].model_dump(mode="json") == (
                reviews[-1].output_pointer_manifest
            )
        assert Counter(role for _key, _attempt, role in executor.calls) == {
            "authoring": 2,
            "review": 4,
            "item_management": 1,
        }
    finally:
        _close(resources)
