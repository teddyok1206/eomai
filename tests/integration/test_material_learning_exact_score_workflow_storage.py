"""Actual disposable DB identity/transaction tests with an explicitly synthetic source/plan port.

No model, NAS, production DB or browser authority is claimed. The completed plan
resolver/source descriptor owners have their own source/installed/live gates.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning import MaterialLearningWork
from eom_catalog_contracts.source_score import PrintedSourceScoreV2
from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision, ResolvedExecutionPlanV41
from eom_workflow.material_learning_request import (
    MaterialLearningWorkerRequestV2,
    MaterialLearningWorkerRequestV3,
)
from eom_workflow_runner import material_learning_start
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    import_workflow_definition,
    load_persisted_workflow_request,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_material_learning_execution_v3 import OPERATOR, plan_for, requested

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SyntheticScoreSourceOwner:
    worker: MaterialLearningWorkerRequestV3
    calls: int = 0
    deny_on_call: int | None = None

    def reauthorize(
        self, _session: Session, *, operator_id: str, work: MaterialLearningWork
    ) -> MaterialLearningWork:
        raise AssertionError("score3 fixture must not use legacy work-only authorization")

    def authorize_future_input(
        self, _session: Session, *, operator_id: str, work: MaterialLearningWork
    ) -> MaterialLearningWorkerRequestV2:
        raise AssertionError("score3 fixture must not use the scope-only predecessor")

    def authorize_exact_score_input(
        self, _session: Session, *, operator_id: str, work: MaterialLearningWork
    ) -> MaterialLearningWorkerRequestV3:
        self.calls += 1
        if (
            operator_id != OPERATOR
            or self.calls == self.deny_on_call
            or work != self.worker.work_input
        ):
            raise ValueError("synthetic current score source denial")
        return self.worker


@pytest.fixture
def start_arguments(creative_engine, monkeypatch):
    request, worker, _ = requested()
    body = request.work_input.model_dump(mode="json")
    body["task_id"] = "materialtask_" + uuid4().hex
    body["input_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "input_sha256"}
    )
    # This changes only a synthetic task identity; source scope/score stay exact.
    worker = type(worker).model_validate({**worker.model_dump(mode="json"), "work_input": body})
    compiled = compile_definition(ROOT / "config/workflows/material-learning.v3.yaml", {"support"})
    with Session(creative_engine, expire_on_commit=False) as session, session.begin():
        definition, _ = import_workflow_definition(session, compiled)
        session.expunge(definition)

    def plan_port(_session, **values):
        document = plan_for(values["request"]).model_dump(mode="json")
        document.update(
            workflow_id=values["workflow_id"],
            workflow_definition_sha256=values["workflow_definition_sha256"],
        )
        document["plan_sha256"] = content_sha256(
            {key: value for key, value in document.items() if key != "plan_sha256"}
        )
        return ResolvedExecutionPlanV41.model_validate(document)

    monkeypatch.setattr(
        material_learning_start, "resolve_material_learning_plan_for_request", plan_port
    )
    _, preset = _published_preset()
    return worker, dict(
        definition=definition,
        work=worker.work_input,
        operator_id=OPERATOR,
        expected_preset=ExecutionPresetRevision.model_validate(preset.canonical_document),
    )


def submit(session, args, owner, key):
    return material_learning_start.submit_material_learning_workflow(
        session, **args, source_authorizer=owner, idempotency_key=key
    )


def test_score_start_replay_retains_one_request_ready_role_and_command(
    creative_engine, start_arguments
):
    worker, args = start_arguments
    owner, key = SyntheticScoreSourceOwner(worker), "score3-start:" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        first = submit(session, args, owner, key)
    with Session(creative_engine) as session, session.begin():
        replay = submit(session, args, owner, key)
        assert first.workflow_id == replay.workflow_id and first.command_id == replay.command_id
        assert not replay.workflow_created
        row = session.get(WorkflowInstanceRecord, first.workflow_id)
        request = load_persisted_workflow_request(row.initial_request)
        assert request.native_printed_score.points == "1.5"
        assert row.role_schema_version == "workflow-role/1.40.0"
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == first.workflow_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == first.workflow_id)
            )
            == 1
        )


def test_two_concurrent_score_starts_reuse_same_original_command(creative_engine, start_arguments):
    worker, args = start_arguments
    barrier, key = Barrier(2), "score3-race:" + uuid4().hex

    def invoke(_index):
        barrier.wait(timeout=10)
        with Session(creative_engine) as session, session.begin():
            return submit(session, args, SyntheticScoreSourceOwner(worker), key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(invoke, range(2)))
    assert len({value.workflow_id for value in results}) == 1
    assert len({value.command_id for value in results}) == 1
    assert sum(value.workflow_created for value in results) == 1


def test_late_score_authorization_failure_does_not_commit_orphan_work(
    creative_engine, start_arguments
):
    worker, args = start_arguments
    key = "score3-late-denial:" + uuid4().hex
    owner = SyntheticScoreSourceOwner(worker, deny_on_call=4)
    with Session(creative_engine) as session, session.begin():
        with pytest.raises(WorkflowError):
            submit(session, args, owner, key)
        assert owner.calls == 4
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.idempotency_key == key)
            )
            == 0
        )


def test_replay_does_not_accept_a_changed_authoritative_score(creative_engine, start_arguments):
    worker, args = start_arguments
    key = "score3-changed-source:" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        first = submit(session, args, SyntheticScoreSourceOwner(worker), key)
    changed = worker.model_copy(
        update={"native_printed_score": PrintedSourceScoreV2(state="PRINTED", points="2.5")}
    )
    with Session(creative_engine) as session, session.begin():
        with pytest.raises(WorkflowError):
            submit(session, args, SyntheticScoreSourceOwner(changed), key)
        assert (
            session.get(WorkflowInstanceRecord, first.workflow_id).initial_request[
                "native_printed_score"
            ]["points"]
            == "1.5"
        )
