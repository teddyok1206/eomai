from __future__ import annotations

from typing import cast

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.models import JobRecord
from eom_orchestrator.workflow_job_retirement import (
    WorkflowJobRetirementBinding,
    WorkflowJobRetirementError,
    fence_workflow_platform_jobs,
    require_workflow_platform_jobs_fenced,
)
from eom_workflow import RoleWorkerInput, WorkflowRequest
from eom_workflow.models import ArtifactSpec
from sqlalchemy.orm import Session

PROTOCOL_VERSION = "workflow-role/1.18.0"


def _worker_request() -> WorkflowRequest:
    return WorkflowRequest.model_validate(
        {
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "content_pack": {
                "pack_key": "generated-knowledge-item",
                "environment": "development",
            },
            "profiles": {
                "authoring": "generated-knowledge-authoring",
                "review": "generated-knowledge-review",
                "image": "generated-stimulus-drawing",
                "registration": "generated-structured-registration",
            },
            "source_intake": {"batch_ids": []},
            "registry_intent": {"mode": "CREATE_ITEM"},
            "item_brief": {
                "subject": "integrated-science",
                "topic": "test-topic",
                "task_type": "data_interpretation",
                "difficulty": "hard",
                "quality_profile": "deep",
                "original_request_sha256": "3" * 64,
            },
            "execution_preset_key": "knowledge-grounded-item",
            "educational_retrieval": {
                "corpus_key": "science-core",
                "query_kind": "ITEM_PREPARATION",
                "curriculum_root_key": "test.topic",
                "topic_keys": [],
                "required_item_elements": ["choice", "paragraph"],
                "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
            },
        }
    )


def _binding(digit: str) -> WorkflowJobRetirementBinding:
    return WorkflowJobRetirementBinding(
        job_id="job_" + digit * 32,
        workflow_id="workflow_" + digit * 32,
        step_run_id="steprun_" + digit * 32,
        attempt=1,
        role="authoring",
    )


def _job(
    binding: WorkflowJobRetirementBinding,
    *,
    request_workflow_id: str | None = None,
    valid_request_hash: bool = True,
) -> JobRecord:
    logical_artifact_id = "artifact_" + binding.job_id[-32:]
    revision_id = "rev_" + binding.job_id[-32:]
    worker_input = RoleWorkerInput(
        protocol_version=PROTOCOL_VERSION,
        job_id=binding.job_id,
        workflow_id=(request_workflow_id or binding.workflow_id),
        step_run_id=binding.step_run_id,
        attempt=binding.attempt,
        role="authoring",
        request=_worker_request(),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id=logical_artifact_id,
            revision_id=revision_id,
        ),
    )
    request = worker_input.model_dump(mode="json")
    task_type = "workflow_authoring"
    request_hash = content_sha256(
        {
            "protocol_version": PROTOCOL_VERSION,
            "task_type": task_type,
            "request": request,
        }
    )
    return JobRecord(
        job_id=binding.job_id,
        protocol_version=PROTOCOL_VERSION,
        idempotency_key="retirement-provenance:" + binding.job_id,
        request_hash=request_hash if valid_request_hash else "sha256:" + "f" * 64,
        task_type=task_type,
        request=request,
        status="RUNNING",
        logical_artifact_id=logical_artifact_id,
        revision_id=revision_id,
    )


class _JobSession:
    def __init__(self, jobs: tuple[JobRecord, ...]) -> None:
        self.jobs = jobs

    def scalars(self, _query: object) -> tuple[JobRecord, ...]:
        return self.jobs


def test_foreign_job_provenance_is_rejected_before_any_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _binding("1")
    second = _binding("2")
    jobs = (
        _job(first),
        _job(second, request_workflow_id="workflow_" + "9" * 32),
    )
    transitions: list[str] = []
    monkeypatch.setattr(
        "eom_orchestrator.workflow_job_retirement.transition_job",
        lambda _session, job_id, *_args, **_kwargs: transitions.append(job_id),
    )

    with pytest.raises(WorkflowJobRetirementError) as raised:
        fence_workflow_platform_jobs(
            cast(Session, _JobSession(jobs)),
            bindings=(first, second),
            reason_code="SUPERSEDED_BY_CORRECTED_PROTOCOL",
        )

    assert raised.value.code == "PRODUCTION_RETIREMENT_JOB_PROVENANCE_MISMATCH"
    assert transitions == []


def test_job_request_hash_mismatch_is_rejected_before_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding("4")
    transitions: list[str] = []
    monkeypatch.setattr(
        "eom_orchestrator.workflow_job_retirement.transition_job",
        lambda _session, job_id, *_args, **_kwargs: transitions.append(job_id),
    )

    with pytest.raises(WorkflowJobRetirementError) as raised:
        fence_workflow_platform_jobs(
            cast(Session, _JobSession((_job(binding, valid_request_hash=False),))),
            bindings=(binding,),
            reason_code="SUPERSEDED_BY_CORRECTED_PROTOCOL",
        )

    assert raised.value.code == "PRODUCTION_RETIREMENT_JOB_PROVENANCE_MISMATCH"
    assert transitions == []


def test_receipt_fence_revalidates_job_provenance() -> None:
    binding = _binding("3")
    foreign = _job(binding, request_workflow_id="workflow_" + "8" * 32)

    with pytest.raises(WorkflowJobRetirementError) as raised:
        require_workflow_platform_jobs_fenced(
            cast(Session, _JobSession((foreign,))),
            bindings=(binding,),
        )

    assert raised.value.code == "PRODUCTION_RETIREMENT_JOB_PROVENANCE_MISMATCH"
