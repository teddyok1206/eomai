from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest
from eom_identifiers import sha256_file
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.schemas import validate_role_result
from eom_workflow_runner.models import (
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import select

pytestmark = [pytest.mark.integration, pytest.mark.workflow_codex_live]

EXPECTED_WORKERS = {
    "authoring": "01",
    "image": "03",
    "review": "02",
    "item_management": "04",
}


def _required_workflow_id(variable: str) -> str:
    if os.environ.get("EOM_RUN_WORKFLOW_CODEX_LIVE") != "1":
        pytest.skip("set EOM_RUN_WORKFLOW_CODEX_LIVE=1 to validate live workflows")
    workflow_id = os.environ.get(variable)
    if workflow_id is None:
        pytest.fail(f"set {variable} to a completed live workflow ID")
    return workflow_id


def _load_workflow(workflow_id: str) -> tuple[WorkflowInstanceRecord, list[WorkflowStepRunRecord]]:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        assert workflow is not None
        steps = list(
            session.scalars(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == workflow_id)
                .order_by(WorkflowStepRunRecord.attempt, WorkflowStepRunRecord.step_run_id)
            )
        )
        events = list(
            session.scalars(
                select(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == workflow_id)
                .order_by(WorkflowEventRecord.sequence)
            )
        )
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert workflow.state == "COMPLETED"
        assert workflow.runtime_context["final_pointer_manifest"]["workflow_id"] == workflow_id
        for step in steps:
            if step.platform_job_id is None:
                continue
            job = session.get(JobRecord, step.platform_job_id)
            assert job is not None
            assert job.status == "SUCCEEDED"
            assert step.result_schema is not None and step.worker_role is not None
            assert job.worker_slot_id == EXPECTED_WORKERS[step.worker_role]
            revision = session.get(ArtifactRevisionRecord, job.revision_id)
            assert revision is not None
            final = Path(revision.nas_path)
            assert final.is_dir()
            assert sha256_file(final / "result.json") == revision.content_hash
            result = json.loads((final / "result.json").read_text(encoding="utf-8"))
            validate_role_result(result, step.worker_role, step.result_schema)
        session.expunge(workflow)
        for step in steps:
            session.expunge(step)
    engine.dispose()
    return workflow, steps


def test_live_image_skip_workflow() -> None:
    workflow_id = _required_workflow_id("EOM_WORKFLOW_SKIP_ID")
    workflow, steps = _load_workflow(workflow_id)
    assert workflow.initial_request == {
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
    }
    image = [step for step in steps if step.step_key == "image"]
    assert len(image) == 1
    assert image[0].state == "SKIPPED"
    assert image[0].platform_job_id is None
    assert Counter(step.worker_role for step in steps if step.platform_job_id) == {
        "authoring": 1,
        "review": 1,
        "item_management": 1,
    }


def test_live_image_required_rework_workflow() -> None:
    workflow_id = _required_workflow_id("EOM_WORKFLOW_REWORK_ID")
    workflow, steps = _load_workflow(workflow_id)
    assert workflow.initial_request == {
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "required",
    }
    assert workflow.rework_cycle_count == 1
    by_step: dict[str, list[WorkflowStepRunRecord]] = {}
    for step in steps:
        by_step.setdefault(step.step_key, []).append(step)
    for key in ("authoring", "image", "review"):
        assert [step.attempt for step in by_step[key]] == [1, 2]
        assert by_step[key][0].state == "SUPERSEDED"
        assert by_step[key][0].output_pointer_manifest is not None
        assert by_step[key][1].state == "SUCCEEDED"
    final_pointers = workflow.runtime_context["final_pointer_manifest"]["artifact_pointers"]
    assert [(pointer["step_key"], pointer["attempt"]) for pointer in final_pointers] == [
        ("authoring", 2),
        ("image", 2),
        ("review", 2),
        ("registration", 1),
    ]
