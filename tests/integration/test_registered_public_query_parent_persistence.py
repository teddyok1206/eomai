"""Guarded PostgreSQL parent1.5 history only; source/child admission is synthetic.

No worker, model, GPU, NAS, production data or numerical success is implied.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_work_batch import PublicSolutionWorkBatchInput
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_workflow.embedding_batch_plan import EmbeddingBatchBound, EmbeddingBatchFailure
from eom_workflow.embedding_batch_plan_v15 import (
    BATCH_PLAN_V15_PROTOCOL,
    BATCH_PLAN_V15_SCHEMA_SHA256,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import encoding_identity, seal
from tests.unit.test_public_solution_query_batch_plan import public_parent_route_case
from tests.unit.test_public_solution_work_batch import public_batch_body
from tests.unit.test_registered_public_query_batch_plan import registered_public_parent_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def planned(guarded_engine):
    value = public_parent_route_case(
        case_factory=partial(
            registered_public_parent_case,
            batch_id="embeddingbatch_" + uuid4().hex,
        )
    )
    value.engine = guarded_engine
    case = value.case
    value.store = EmbeddingBatchPlanStore(case.request, case.selection, case.policy)
    # Match this route's exact numerical space. Child Workflow/source authority
    # remains an explicit synthetic seam, as in the legacy planning-store suite.
    resources = value.decision.selected.profile.resource_profile
    body = public_batch_body(count=1, device="CUDA")
    body.update(
        scope=case.request.scope.model_dump(mode="json"),
        routing_decision_sha256=value.decision.decision_sha256,
        resource_profile_sha256=resources.resource_profile_sha256,
        timeout_seconds=min(resources.timeout_seconds, 180),
    )
    child = body["children"][0]
    child["scope_sha256"] = case.request.scope.scope_sha256
    native = child["request"]
    spaces = case.selection.selected_views("CUDA")[0].index.spaces
    native.update(
        spaces=spaces.model_dump(mode="json"),
        batch_size=resources.batch_size,
        threads=resources.threads,
    )
    for row in native["rows"]:
        row["encoding"] = encoding_identity(
            row["text"], spaces.query, storage_partition=case.request.scope.storage_partition
        ).model_dump(mode="json")
    native["input_set_sha256"] = content_sha256([row["encoding"] for row in native["rows"]])
    child["request"] = seal(native, "request_sha256")
    value.batch = PublicSolutionWorkBatchInput.model_validate(seal(body, "request_sha256"))
    value.bound = EmbeddingBatchBound.model_validate(
        seal(
            dict(
                schema_version="embedding-batch-plan/1.0",
                message_type="BOUND",
                request_sha256=case.request.request_sha256,
                route_record_sha256=value.route.record_sha256,
                batch_request_sha256=value.batch.request_sha256,
                resource_profile_sha256=resources.resource_profile_sha256,
                children=[
                    dict(
                        selection_sha256=case.request.child_selection_sha256s[0],
                        workflow_id="workflow_" + uuid4().hex,
                        step_run_id="steprun_" + uuid4().hex,
                        native_job_id=value.batch.children[0].request.job_id,
                        workflow_request_sha256=content_sha256({"synthetic": "workflow"}),
                        launch_association_sha256=content_sha256({"synthetic": "launch"}),
                        native_input_sha256=value.batch.children[0].request.request_sha256,
                    )
                ],
            ),
            "record_sha256",
        )
    )
    value.failure = EmbeddingBatchFailure.model_validate(
        seal(
            dict(
                schema_version="embedding-batch-plan/1.0",
                message_type="FAILED",
                request_sha256=case.request.request_sha256,
                error_code="SOURCE_REVOKED",
                evidence=case.request.selection_manifest.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )

    def authorize(child):
        assert child == value.bound.children[0], "synthetic child admission differs"

    value.authorize = authorize
    return value


def test_parent15_plan_binding_and_replay_keep_protocol_pin_and_small_history(planned):
    with Session(planned.engine) as session, session.begin():
        _, created = planned.store.allocate(session, planned.allocation)
        assert created
        planned.store.route(session, planned.route)
        original = planned.store.bind(
            session, planned.bound, planned.batch, authorize_child=planned.authorize
        )
    assert original.state == "SUCCEEDED"  # Planning binding, not numerical completion.
    with Session(planned.engine) as session, session.begin():
        assert planned.store.allocate(session, planned.allocation) == (original, False)
        assert planned.store.route(session, planned.route) == original
        assert (
            planned.store.bind(
                session, planned.bound, planned.batch, authorize_child=planned.authorize
            )
            == original
        )
        job = session.get(JobRecord, original.job_id)
        assert job.protocol_version == BATCH_PLAN_V15_PROTOCOL
        assert (
            session.get(ProtocolVersionRecord, job.protocol_version).schema_sha256
            == BATCH_PLAN_V15_SCHEMA_SHA256
        )
        assert "anchors" not in job.request and "vectors" not in job.request
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == original.job_id)
            )
            == 8
        )


def test_parent15_two_controllers_keep_one_original_allocation_and_dispatch_owner(planned):
    barrier = Barrier(2)

    def allocate():
        barrier.wait(timeout=20)
        with Session(planned.engine) as session, session.begin():
            return planned.store.allocate(session, planned.allocation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = tuple(pool.map(lambda _: allocate(), range(2)))
    assert one[0] == two[0]
    assert sorted((one[1], two[1])) == [False, True]


def test_parent15_interrupted_root_leaves_original_committed_prefix_recoverable(planned):
    with pytest.raises(KeyboardInterrupt), Session(planned.engine) as session, session.begin():
        planned.store.allocate(session, planned.allocation)
        raise KeyboardInterrupt("synthetic original root interruption")
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) is None
        original, _ = planned.store.allocate(session, planned.allocation)
    with pytest.raises(KeyboardInterrupt), Session(planned.engine) as session, session.begin():
        planned.store.route(session, planned.route)
        planned.store.bind(session, planned.bound, planned.batch, authorize_child=planned.authorize)
        raise KeyboardInterrupt("synthetic uncommitted route/binding interruption")
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == original


@pytest.mark.parametrize("after_route", [False, True])
def test_parent15_failed_history_cannot_be_bound_or_reinterpreted_as_success(planned, after_route):
    with Session(planned.engine) as session, session.begin():
        planned.store.allocate(session, planned.allocation)
        if after_route:
            planned.store.route(session, planned.route)
        failed = planned.store.record_failure(session, planned.failure)
    with Session(planned.engine) as session, session.begin():
        assert failed.state == "FAILED"
        assert planned.store.record_failure(session, planned.failure) == failed
        assert planned.store.allocate(session, planned.allocation) == (failed, False)
    with pytest.raises(ValueError), Session(planned.engine) as session, session.begin():
        planned.store.bind(session, planned.bound, planned.batch, authorize_child=planned.authorize)
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == failed
