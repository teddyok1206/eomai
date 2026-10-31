"""Actual marked disposable PostgreSQL public Item acceptance; source/QUERY/IAM synthetic."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.services import command_adapter as module
from eom_api.services.item_similarity_start import (
    PUBLIC_SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
    SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator.control_models import (
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_orchestrator.settings import Settings
from eom_orchestrator.similarity_context_artifact import publish_public_solution_similarity_context
from eom_workflow.public_similarity_control import PreparedPublicSimilarityPlan
from eom_workflow_runner.item_similarity_preparation import PreparedPublicItemSimilarity
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_similarity_item_start_persistence import item as item
from tests.integration.test_similarity_item_start_persistence import start
from tests.unit.public_similarity_materialization_fixtures import public_materialization_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def public_item(item, tmp_path, monkeypatch):
    place = tmp_path / "public-context"
    place.mkdir()
    ordinary = item.expected_plan_schema == "resolved-execution-plan/24.0"
    case = public_materialization_case(place, monkeypatch, ordinary=ordinary, registered=True)
    publisher = ControlFileSetPublisher(
        item.engine,
        Settings(
            staging_root=tmp_path / "pg-staging",
            nas_artifact_root=tmp_path / "pg-artifacts",
            workspace_root=tmp_path / "pg-workspace",
        ),
    )
    receipt = publish_public_solution_similarity_context(
        publisher,
        context=case["context"],
        expected_request=case["context"].request,
        idempotency_key="synthetic-public-pg:" + uuid4().hex,
        source_commit="a" * 40,
    )
    old = item.prepared
    resolution = old.resolution.model_copy(
        update={
            "content_pack_version": "1.20.18",
            "content_pack_bundle_sha256": SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.18"],
        }
    )
    item.data.runtime["content_pack"].update(
        version="1.20.18", release_sha256=resolution.content_pack_bundle_sha256
    )
    item.prepared = PreparedPublicItemSimilarity(
        PreparedPublicSimilarityPlan(receipt.delivery, case["context"]),
        receipt,
        old.workflow_request_sha256,
        old.evidence_result_sha256,
        old.preset_content_sha256,
        resolution,
        CompletedSimilarityQuerySelection(
            workflow_id="workflow_" + uuid4().hex,
            workflow_request_sha256="sha256:" + "a" * 64,
            context_request_sha256=case["context"].request.request_sha256,
        ),
        old.operator_id,
    )
    item.expected_plan_schema = (
        "resolved-execution-plan/31.0" if ordinary else "resolved-execution-plan/30.0"
    )
    return item


def assert_public_rows(item, result):
    with item.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, result[1])
        plan = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
            )
        )
        assert plan.canonical_document["schema_version"] == item.expected_plan_schema
        assert PUBLIC_SIMILARITY_PREPARATION_ACCEPTANCE_KEY in workflow.runtime_context
        assert SIMILARITY_PREPARATION_ACCEPTANCE_KEY not in workflow.runtime_context
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
            )
            == 1
        )
        assert session.scalar(
            select(func.count())
            .select_from(ResolvedExecutionPlanStepRecord)
            .where(ResolvedExecutionPlanStepRecord.plan_id == plan.plan_id)
        ) == len(plan.canonical_document["steps"])
        assert all(not isinstance(value, bytes) for value in plan.canonical_document.values())


def test_public_item_postgres_same_request_replays_one_plan_acceptance_and_start(public_item):
    one = start(public_item)
    assert start(public_item) == one
    assert_public_rows(public_item, one)


def test_public_item_postgres_concurrent_creation_accepts_one_plan_and_command(public_item):
    barrier = Barrier(2)

    def submit(_number):
        barrier.wait(timeout=30)
        return start(public_item)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(submit, range(2)))
    assert results[0] == results[1]
    assert_public_rows(public_item, results[0])


def test_public_item_postgres_interruption_rolls_back_then_replays_without_losing_publication(
    public_item, monkeypatch
):
    original = module.similarity_start_context

    def interrupt(*args):
        raise ApiError(503, "TEST_INTERRUPTED", "synthetic", "after actual plan flush")

    monkeypatch.setattr(module, "similarity_start_context", interrupt)
    with pytest.raises(ApiError, match="TEST_INTERRUPTED"):
        start(public_item)
    with public_item.sessions() as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord.workflow_id).where(
                    WorkflowInstanceRecord.idempotency_key == public_item.key
                )
            )
            is None
        )
        assert (
            session.get(
                ArtifactRevisionRecord,
                public_item.prepared.publication.delivery.context_member.artifact_revision_id,
            )
            is not None
        )
    monkeypatch.setattr(module, "similarity_start_context", original)
    assert_public_rows(public_item, start(public_item))


def test_public_item_postgres_other_preparation_cannot_replace_accepted_fingerprint(public_item):
    result = start(public_item)
    original = public_item.prepared
    public_item.prepared = replace(
        original,
        query_selection=original.query_selection.model_copy(
            update={"workflow_request_sha256": "sha256:" + "0" * 64}
        ),
    )
    with pytest.raises(ApiError, match="CONTROL_SIMILARITY_PREPARATION_CONFLICT"):
        start(public_item)
    public_item.prepared = original
    assert start(public_item) == result
    assert_public_rows(public_item, result)
