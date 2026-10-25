"""Guarded PostgreSQL publication/admission/plan roots; synthetic IAM/source and no compute."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
)
from eom_workflow.embedding_batch_plan_family import (
    parse_embedding_batch_plan_request,
    validate_embedding_batch_allocation,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_bulk_plan_fixtures import bulk_planning_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan_admission import source_case

pytestmark = pytest.mark.integration


@pytest.fixture(params=("legacy", "bulk"))
def admitted(guarded_engine, tmp_path, monkeypatch, request):
    nas = tmp_path / "nas"
    nas.mkdir()
    publisher = ControlFileSetPublisher(
        guarded_engine, Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas)
    )
    case = bulk_planning_case() if request.param == "bulk" else None
    value = source_case(tmp_path, monkeypatch, publisher=publisher, planned=case, key=uuid4().hex)
    value.request = parse_embedding_batch_plan_request(
        seal(
            value.request.model_dump(mode="json") | {"batch_id": "embeddingbatch_" + uuid4().hex},
            "request_sha256",
        )
    )
    control = seal(
        value.case.allocation.control_request.model_dump(mode="json")
        | {
            "parent_request_sha256": value.request.request_sha256,
            "child_set_sha256": content_sha256(list(value.request.child_selection_sha256s)),
        },
        "message_sha256",
    )
    value.allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            value.case.allocation.model_dump(mode="json")
            | {"request_sha256": value.request.request_sha256, "control_request": control},
            "record_sha256",
        )
    )
    validate_embedding_batch_allocation(value.request, value.case.policy, value.allocation)
    value.store = EmbeddingBatchPlanStore(value.request, value.selection, value.case.policy)
    return value


def test_two_admitted_controllers_keep_original_allocation_and_one_dispatch_owner(admitted):
    value = admitted
    barrier = Barrier(2)

    def allocate():
        with (
            Session(value.engine) as session,
            session.begin(),
            value.owner.admit(session, value.request),
        ):
            barrier.wait(timeout=10)
            return value.store.allocate(session, value.allocation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(allocate) for _ in range(2)]
        result = [future.result(timeout=30) for future in futures]
    assert sorted(created for _, created in result) == [False, True]
    assert result[0][0] == result[1][0]
    with Session(value.engine) as session, session.begin():
        with value.owner.admit(session, value.request):
            assert value.store.allocate(session, value.allocation) == (result[0][0], False)
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == value.store.key)
            )
            == 1
        )


@pytest.mark.parametrize("failure", ["interruption", "late_revocation"])
def test_original_root_does_not_commit_plan_after_interruption_or_late_denial(admitted, failure):
    value = admitted
    with (
        pytest.raises((ValueError, RuntimeError)),
        Session(value.engine) as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        value.store.allocate(session, value.allocation)
        if failure == "interruption":
            raise RuntimeError("synthetic interruption before allocation dispatch")
        value.denied = True
    value.denied = False
    with Session(value.engine) as session, session.begin():
        with value.owner.admit(session, value.request):
            assert value.store.read(session) is None
        assert session.get(JobRecord, value.saved_selection.owner_job_id).status == "SUCCEEDED"


def test_replay_requires_current_source_authority_without_changing_original_history(admitted):
    value = admitted
    with (
        Session(value.engine) as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        original, created = value.store.allocate(session, value.allocation)
        assert created
    value.denied = True
    with (
        pytest.raises(ValueError),
        Session(value.engine) as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        pytest.fail("replay bypassed current source authority")
    value.denied = False
    with (
        Session(value.engine) as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        assert value.store.read(session) == original


def test_concurrent_first_observation_publication_returns_one_original_artifact(admitted):
    value = admitted
    barrier = Barrier(2)
    key = "batch-selection-concurrent:" + uuid4().hex

    def publish():
        barrier.wait(timeout=10)
        return value.controls.publish_batch_selection(value.selection, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish) for _ in range(2)]
        result = [future.result(timeout=30) for future in futures]
    assert result[0] == result[1]
    assert result[0].member != value.saved_selection.member
    assert result[0].member.sha256 == value.saved_selection.member.sha256
