"""Actual-principal application composition using fake ports only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from eom_catalog_contracts.inference_transfer_experiment import ExperimentBudget
from eom_orchestrator.inference_transfer_experiment_execution import (
    InferenceTransferExperimentExecution,
)
from eom_orchestrator.inference_transfer_experiment_invocation import (
    AuthenticatedInferenceTransferExperimentOwner,
)
from eom_orchestrator.inference_transfer_snapshot_staging import (
    SnapshotExperimentStageCommand,
    SnapshotReadFailure,
)

from tests.unit.inference_transfer_experiment_fixtures import experiment_request
from tests.unit.inference_transfer_snapshot_fixtures import (
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
)
from tests.unit.test_inference_transfer_owner_http import ACTOR, principal


class Session:
    def __init__(self, *, actor_id: str = ACTOR):
        self.actor_id = actor_id
        self.calls: list[tuple[str, Any]] = []
        self.result: Any = None

    def read(self) -> Any:
        self.calls.append(("ME", None))
        return principal(operator_id=self.actor_id)

    def execute(self, actor_id: str, request: Any) -> Any:
        self.calls.append((actor_id, request))
        return self.result


class Execution:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, dict[str, Any]]] = []
        self.result = object()
        self.failure: Exception | None = None

    def execute(self, actor: Any, command: Any, **kwargs: Any) -> Any:
        self.calls.append((actor, command, kwargs))
        if self.failure is not None:
            raise self.failure
        return self.result


def command(**budget: Any) -> SnapshotExperimentStageCommand:
    example = experiment_request()
    return SnapshotExperimentStageCommand(
        snapshot_prepare(),
        example.experiment_id,
        example.experiment_revision_id,
        example.model_spec,
        ExperimentBudget(**({"maximum_queries": 4} | budget)),
    )


def test_inventory_has_no_query_model_workspace_or_publication() -> None:
    session = Session()
    prepare = snapshot_prepare(query_item_revision_ids=())
    session.result = snapshot_prepare_result(
        header=snapshot_header(prepare=prepare, actor_id=ACTOR)
    )
    owner = AuthenticatedInferenceTransferExperimentOwner(session)
    assert owner.inventory(prepare) == session.result
    assert session.calls == [("ME", None), (ACTOR, prepare)]
    assert owner.execution is None


def test_inventory_rejects_item_queries_before_any_read() -> None:
    session = Session()
    with pytest.raises(SnapshotReadFailure):
        AuthenticatedInferenceTransferExperimentOwner(session).inventory(snapshot_prepare())
    assert session.calls == []


def test_inventory_does_not_accept_valid_hash_foreign_actor() -> None:
    session = Session()
    prepare = snapshot_prepare(query_item_revision_ids=())
    session.result = snapshot_prepare_result(header=snapshot_header(prepare=prepare))
    with pytest.raises(SnapshotReadFailure) as caught:
        AuthenticatedInferenceTransferExperimentOwner(session).inventory(prepare)
    assert caught.value.code == "INFERENCE_TRANSFER_FORBIDDEN"


def test_execute_captures_actual_actor_and_utc_time_no_caller_clock() -> None:
    session, execution = Session(), Execution()
    owner = AuthenticatedInferenceTransferExperimentOwner(
        session, cast(InferenceTransferExperimentExecution, execution)
    )
    selected = command()
    before = datetime.now(UTC)
    assert (
        owner.execute(selected, execution_id="embeddingexecution_" + "d" * 32) is execution.result
    )
    after = datetime.now(UTC)
    actor, checked, parameters = execution.calls[0]
    assert actor.actor_id == ACTOR and checked == selected
    assert parameters["execution_id"] == "embeddingexecution_" + "d" * 32
    assert before <= parameters["created_at"] <= after
    assert parameters["created_at"].tzinfo == UTC
    assert session.calls == [("ME", None)]


@pytest.mark.parametrize(
    "changes",
    [
        {"maximum_queries": 5},
        {"top_k": 9},
        {"batch_size": 5},
        {"threads": 5},
    ],
)
def test_pilot_budget_cannot_be_widened_by_a_frozen_command(changes: dict[str, Any]) -> None:
    session, execution = Session(), Execution()
    with pytest.raises(SnapshotReadFailure):
        AuthenticatedInferenceTransferExperimentOwner(
            session, cast(InferenceTransferExperimentExecution, execution)
        ).execute(command(**changes), execution_id="embeddingexecution_" + "d" * 32)
    assert session.calls == [] and execution.calls == []


@pytest.mark.parametrize(
    "prepare",
    [
        snapshot_prepare(population_scope="ALL_ADMITTED_GRAPH_ITEMS"),
        snapshot_prepare(
            population_scope="ALL_ADMITTED_GRAPH_ITEMS", source_classes=("APPROVED_ITEM",)
        ),
        snapshot_prepare(query_item_revision_ids=()),
        snapshot_prepare(query_item_revision_ids=tuple("itemrev_" + seed * 32 for seed in "abcde")),
    ],
)
def test_original_scope_and_selected_query_bounds_fail_before_read(prepare: Any) -> None:
    session, execution = Session(), Execution()
    with pytest.raises(SnapshotReadFailure):
        AuthenticatedInferenceTransferExperimentOwner(
            session, cast(InferenceTransferExperimentExecution, execution)
        ).execute(
            replace(command(), prepare_request=prepare),
            execution_id="embeddingexecution_" + "d" * 32,
        )
    assert session.calls == [] and execution.calls == []


def test_unavailable_execution_is_not_a_fake_success() -> None:
    session = Session()
    with pytest.raises(SnapshotReadFailure) as caught:
        AuthenticatedInferenceTransferExperimentOwner(session).execute(
            command(), execution_id="embeddingexecution_" + "d" * 32
        )
    assert caught.value.code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE" and session.calls == []


def test_execution_failure_is_not_retried_with_a_new_identity() -> None:
    session, execution = Session(), Execution()
    execution.failure = SnapshotReadFailure("INFERENCE_TRANSFER_FORBIDDEN")
    with pytest.raises(SnapshotReadFailure):
        AuthenticatedInferenceTransferExperimentOwner(
            session, cast(InferenceTransferExperimentExecution, execution)
        ).execute(command(), execution_id="embeddingexecution_" + "d" * 32)
    assert len(execution.calls) == 1


def test_model_copy_malformed_prepare_is_revalidated_before_actor_read() -> None:
    session = Session()
    malformed = command().prepare_request.model_copy(
        update={"prepare_sha256": "sha256:" + "f" * 64}
    )
    with pytest.raises(ValueError):
        AuthenticatedInferenceTransferExperimentOwner(session).execute(
            replace(command(), prepare_request=malformed),
            execution_id="embeddingexecution_" + "d" * 32,
        )
    assert session.calls == []
