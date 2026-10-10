"""Actual principal → bounded inventory/experiment; the existing execution owns side effects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from eom_api_contracts.auth import CurrentOperator
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    parse_snapshot_request,
    parse_snapshot_result,
    validate_snapshot_prepare_result,
)

from eom_orchestrator.inference_transfer_experiment_execution import (
    CommittedInferenceTransferExperiment,
    InferenceTransferExperimentExecution,
)
from eom_orchestrator.inference_transfer_snapshot_staging import (
    AuthenticatedSnapshotActor,
    SnapshotExperimentStageCommand,
    SnapshotReadFailure,
    SnapshotReadPort,
)


class AuthenticatedExperimentSession(SnapshotReadPort, Protocol):
    def read(self) -> CurrentOperator: ...


def _prepare(
    value: InferenceTransferSnapshotPrepareRequest,
) -> InferenceTransferSnapshotPrepareRequest:
    checked = parse_snapshot_request(value.model_dump(mode="json"))
    if (
        not isinstance(checked, InferenceTransferSnapshotPrepareRequest)
        or checked.population_scope != "OCCURRENCE_BACKED_PAST_EXAM"
        or checked.source_classes != ("PAST_EXAM",)
        or len(checked.query_item_revision_ids) > 4
    ):
        raise SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID")
    return checked


class AuthenticatedInferenceTransferExperimentOwner:
    """Neither OS identity nor returned metadata is treated as API authority."""

    def __init__(
        self,
        session: AuthenticatedExperimentSession,
        execution: InferenceTransferExperimentExecution | None = None,
    ) -> None:
        self.session, self.execution = session, execution

    def inventory(
        self, request: InferenceTransferSnapshotPrepareRequest
    ) -> InferenceTransferSnapshotPrepareResult:
        request = _prepare(request)
        if request.query_item_revision_ids:
            raise SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID")
        actor = CurrentOperator.model_validate(self.session.read().model_dump(mode="json"))
        raw = self.session.execute(actor.operator_id, request)
        result = parse_snapshot_result(raw.model_dump(mode="json"))
        if not isinstance(result, InferenceTransferSnapshotPrepareResult):
            raise SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
        validate_snapshot_prepare_result(request, result)
        if result.header.actor_id != actor.operator_id:
            raise SnapshotReadFailure("INFERENCE_TRANSFER_FORBIDDEN")
        return result

    def execute(
        self, command: SnapshotExperimentStageCommand, *, execution_id: str
    ) -> CommittedInferenceTransferExperiment:
        prepare = _prepare(command.prepare_request)
        budget = command.budget.model_validate(command.budget.model_dump(mode="json"))
        if (
            not prepare.query_item_revision_ids
            or budget.maximum_queries > 4
            or budget.top_k != 8
            or budget.batch_size > 4
            or budget.threads > 4
        ):
            raise SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID")
        if self.execution is None:
            raise SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
        actor = CurrentOperator.model_validate(self.session.read().model_dump(mode="json"))
        checked = SnapshotExperimentStageCommand(
            prepare,
            command.experiment_id,
            command.experiment_revision_id,
            command.model_spec,
            budget,
        )
        return self.execution.execute(
            AuthenticatedSnapshotActor(actor.operator_id),
            checked,
            execution_id=execution_id,
            created_at=datetime.now(UTC),
        )
