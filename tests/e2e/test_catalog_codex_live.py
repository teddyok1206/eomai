from __future__ import annotations

import os

import pytest
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.models import JobRecord
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import func, select

pytestmark = [pytest.mark.integration, pytest.mark.catalog_codex_live]


def _workflow_id(variable: str) -> str:
    if os.environ.get("EOM_RUN_CATALOG_CODEX_LIVE") != "1":
        pytest.skip("set EOM_RUN_CATALOG_CODEX_LIVE=1 to validate catalog workflows")
    value = os.environ.get(variable)
    if value is None:
        pytest.fail(f"set {variable} to a completed catalog workflow ID")
    return value


def test_live_create_and_revise_item_workflows_are_pinned_and_idempotent() -> None:
    create_id = _workflow_id("EOM_CATALOG_CREATE_WORKFLOW_ID")
    revise_id = _workflow_id("EOM_CATALOG_REVISE_WORKFLOW_ID")
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        created = session.get(WorkflowInstanceRecord, create_id)
        revised = session.get(WorkflowInstanceRecord, revise_id)
        assert created is not None and revised is not None
        assert created.state == revised.state == "COMPLETED"
        assert created.definition_version == revised.definition_version == "1.1.0"
        create_pack = created.runtime_context["content_pack"]
        revise_pack = revised.runtime_context["content_pack"]
        assert create_pack["release_id"] == revise_pack["release_id"]
        assert create_pack["release_sha256"] == revise_pack["release_sha256"]
        assert len(created.runtime_context["prompt_artifacts"]) == 3
        assert len(revised.runtime_context["prompt_artifacts"]) == 3

        create_registration = created.runtime_context["item_registration"]
        revise_registration = revised.runtime_context["item_registration"]
        assert create_registration["item_id"] == revise_registration["item_id"]
        assert create_registration["revision_number"] == 1
        assert revise_registration["revision_number"] == 2
        item = session.get(ItemRecord, create_registration["item_id"])
        first = session.get(ItemRevisionRecord, create_registration["item_revision_id"])
        second = session.get(ItemRevisionRecord, revise_registration["item_revision_id"])
        assert item is not None and first is not None and second is not None
        assert item.current_revision_id == second.item_revision_id
        assert first.revision_state == "SUPERSEDED"
        assert first.superseded_by_revision_id == second.item_revision_id
        assert second.revision_state == "APPROVED"
        revision_count = session.scalar(
            select(func.count())
            .select_from(ItemRevisionRecord)
            .where(ItemRevisionRecord.item_id == item.item_id)
        )
        assert revision_count == 2

        for workflow_id in (create_id, revise_id):
            steps = list(
                session.scalars(
                    select(WorkflowStepRunRecord).where(
                        WorkflowStepRunRecord.workflow_id == workflow_id,
                        WorkflowStepRunRecord.platform_job_id.is_not(None),
                    )
                )
            )
            slots: dict[str | None, str | None] = {}
            for step in steps:
                assert step.platform_job_id is not None
                job = session.get(JobRecord, step.platform_job_id)
                assert job is not None
                slots[step.worker_role] = job.worker_slot_id
            assert slots == {"authoring": "01", "review": "02", "item_management": "04"}
    engine.dispose()
