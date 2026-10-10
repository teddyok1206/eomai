"""Pure bounded snapshot assembly; current source authority stays with the read owner.

An actor value is caller-captured context, not a credential. This use case neither
authenticates that value nor stages files, launches models or publishes Artifacts.
Publication must call ``reauthorize_staged_experiment`` after model execution.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentAdmissionScope,
    ExperimentBudget,
    InferenceTransferExperimentRequest,
    SuppliedGraphBaseline,
    profile_key,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    MAX_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotHeader,
    InferenceTransferSnapshotIndexEntry,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRecord,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
    parse_snapshot_request,
    parse_snapshot_result,
    snapshot_baseline_set_sha256,
    snapshot_entry_set_sha256,
    validate_snapshot_authorize_result,
    validate_snapshot_prepare_result,
    validate_snapshot_read_result,
    validate_snapshot_records,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
)
from eom_catalog_contracts.models import ActorId, FrozenModel
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter

_PORT_FAILURES = frozenset(
    {
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
        "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
        "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED",
        "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_BASELINE_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
        "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE",
    }
)


class SnapshotReadFailure(RuntimeError):
    """Sanitized owner failure; only the exact read budget code permits splitting."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _PORT_FAILURES else "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
        super().__init__(self.code)


class SnapshotStagingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SnapshotReadPort(Protocol):
    """Supported owner adapter; adapt bounded errors to ``SnapshotReadFailure``.

    Transport identity/authentication stays in the adapter. The use case cannot
    infer a retryable budget failure from another component's exception text.
    """

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult: ...


@dataclass(frozen=True)
class AuthenticatedSnapshotActor:
    """Actual principal captured by the supported caller, never model authority."""

    actor_id: str

    def __post_init__(self) -> None:
        TypeAdapter(ActorId).validate_python(self.actor_id)


@dataclass(frozen=True)
class SnapshotExperimentStageCommand:
    prepare_request: InferenceTransferSnapshotPrepareRequest
    experiment_id: str
    experiment_revision_id: str
    model_spec: LocalEmbeddingModelSpec
    budget: ExperimentBudget


@dataclass(frozen=True)
class StagedInferenceTransferExperiment:
    request: InferenceTransferExperimentRequest
    header: InferenceTransferSnapshotHeader
    index: tuple[InferenceTransferSnapshotIndexEntry, ...]
    accumulated_received_bytes: int
    limitations: tuple[str, ...]


def _hashed[T: FrozenModel](model: type[T], field: str, **values: Any) -> T:
    """Allocate a small typed value then revalidate its complete canonical document."""
    body = model.model_construct(**values).model_dump(mode="json", exclude={field})
    return model.model_validate(body | {field: content_sha256(body)})


def _received(
    port: SnapshotReadPort,
    actor: AuthenticatedSnapshotActor,
    request: InferenceTransferSnapshotRequest,
    *,
    remaining_bytes: int,
) -> tuple[InferenceTransferSnapshotResult, int]:
    checked_request = parse_snapshot_request(request.model_dump(mode="json"))
    try:
        raw = port.execute(actor.actor_id, checked_request)
    except SnapshotReadFailure:
        raise
    except Exception as exc:
        raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_UNAVAILABLE") from exc
    if not isinstance(
        raw,
        (
            InferenceTransferSnapshotPrepareResult,
            InferenceTransferSnapshotReadResult,
            InferenceTransferSnapshotAuthorizeResult,
        ),
    ):
        raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_REPLY_INVALID")
    body = raw.model_dump(mode="json")
    encoded_size = len(canonical_json_bytes(body))
    if encoded_size > min(MAX_SNAPSHOT_FRAME_BYTES, remaining_bytes):
        raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_BUDGET_EXCEEDED")
    return parse_snapshot_result(body), encoded_size


def _exact_queries(
    prepared: InferenceTransferSnapshotPrepareResult,
) -> tuple[InferenceTransferProfilePointer, ...]:
    by_revision = {row.source_item_revision_id: row for row in prepared.index}
    queries = []
    for revision in prepared.header.prepare.query_item_revision_ids:
        row = by_revision.get(revision)
        if row is None or row.profile is None:
            raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_QUERY_UNAVAILABLE")
        queries.append(row.profile)
    if not queries:
        raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_QUERY_UNAVAILABLE")
    return tuple(sorted(queries, key=profile_key))


def _validated_experiment(
    request: InferenceTransferExperimentRequest,
) -> InferenceTransferExperimentRequest:
    body = request.model_dump(mode="json")
    validate_contract("item-inference-transfer-experiment", body)
    checked = InferenceTransferExperimentRequest.model_validate(body)
    if len(canonical_json_bytes(body)) > checked.budget.maximum_input_bytes:
        raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_BUDGET_EXCEEDED")
    return checked


def stage_snapshot_experiment(
    actor: AuthenticatedSnapshotActor,
    command: SnapshotExperimentStageCommand,
    port: SnapshotReadPort,
) -> StagedInferenceTransferExperiment:
    """Read one complete frozen population; never cache a publication authorization."""
    try:
        prepare = parse_snapshot_request(command.prepare_request.model_dump(mode="json"))
        if not isinstance(prepare, InferenceTransferSnapshotPrepareRequest):
            raise ValueError("staging must begin with PREPARE")
        model = LocalEmbeddingModelSpec.model_validate(command.model_spec.model_dump(mode="json"))
        budget = ExperimentBudget.model_validate(command.budget.model_dump(mode="json"))
        raw, received_bytes = _received(
            port, actor, prepare, remaining_bytes=budget.maximum_input_bytes
        )
        if not isinstance(raw, InferenceTransferSnapshotPrepareResult):
            raise ValueError("owner returned a different phase")
        validate_snapshot_prepare_result(prepare, raw)
        if raw.header.actor_id != actor.actor_id:
            raise ValueError("owner returned another actor's snapshot")
        prepared = raw
        queries = _exact_queries(prepared)
        if (
            prepared.header.profile_count > budget.maximum_profiles
            or len(queries) > budget.maximum_queries
        ):
            raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_BUDGET_EXCEEDED")

        width = prepare.chunk_budget.max_entries
        chunks = deque(
            prepared.index[start : start + width] for start in range(0, len(prepared.index), width)
        )
        records: list[InferenceTransferSnapshotRecord] = []
        baselines: list[SuppliedGraphBaseline] = []
        limitations: set[str] = set()
        while chunks:
            selected = chunks.popleft()
            read = _hashed(
                InferenceTransferSnapshotReadRequest,
                "read_sha256",
                header=prepared.header,
                selected_index_entries=selected,
            )
            try:
                reply, size = _received(
                    port,
                    actor,
                    read,
                    remaining_bytes=budget.maximum_input_bytes - received_bytes,
                )
            except SnapshotReadFailure as exc:
                if exc.code != "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED":
                    raise
                if len(selected) == 1:
                    raise SnapshotStagingError(
                        "INFERENCE_TRANSFER_STAGING_BUDGET_EXCEEDED"
                    ) from exc
                midpoint = len(selected) // 2
                chunks.appendleft(selected[midpoint:])
                chunks.appendleft(selected[:midpoint])
                continue
            received_bytes += size
            if not isinstance(reply, InferenceTransferSnapshotReadResult):
                raise ValueError("owner returned a different phase")
            validate_snapshot_read_result(read, reply, index=prepared.index)
            records.extend(reply.records)
            baselines.extend(reply.baselines)
            limitations.update(reply.limitations)

        full_records = tuple(records)
        validate_snapshot_records(prepared.header, prepared.index, full_records)
        entries = tuple(
            sorted(
                (row.staged_entry for row in full_records if row.staged_entry is not None),
                key=lambda entry: profile_key(
                    InferenceTransferProfilePointer.from_profile(entry.profile)
                ),
            )
        )
        sources = tuple(
            sorted((row.source for row in full_records), key=lambda s: s.item_revision_id)
        )
        scope = ExperimentAdmissionScope(
            actor_id=actor.actor_id,
            graph_snapshot=prepare.graph_snapshot,
            policy_revision_id=prepare.access_policy_revision_id,
            policy_sha256=prepare.access_policy_sha256,
            population_scope=prepare.population_scope,
            projection_version=prepare.projection_version,
            population_sources=sources,
            population_sha256=prepared.header.population_sha256,
            eligible_profile_set_sha256=prepared.header.eligible_profile_set_sha256,
            data_provenance="AUTHORIZED_CORPUS_SNAPSHOT",
            producer_admission="CATALOG_AUTHORIZED_SNAPSHOT",
        )
        experiment = _hashed(
            InferenceTransferExperimentRequest,
            "request_sha256",
            experiment_id=command.experiment_id,
            experiment_revision_id=command.experiment_revision_id,
            scope=scope,
            model_spec=model,
            recipe=prepare.recipe,
            entries=entries,
            queries=queries,
            baselines=tuple(sorted(baselines, key=lambda row: profile_key(row.query))),
            budget=budget,
        )
        return StagedInferenceTransferExperiment(
            request=_validated_experiment(experiment),
            header=prepared.header,
            index=prepared.index,
            accumulated_received_bytes=received_bytes,
            limitations=tuple(sorted(limitations)),
        )
    except (ValueError, JsonSchemaValidationError) as exc:
        raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_INPUT_OR_REPLY_INVALID") from exc


def reauthorize_staged_experiment(
    actor: AuthenticatedSnapshotActor,
    staged: StagedInferenceTransferExperiment,
    port: SnapshotReadPort,
) -> InferenceTransferSnapshotAuthorizeResult:
    """Always ask the owner again after execution and immediately before publication.

    A successful response describes this current read only; it is not a reusable
    authorization token. The commit owner must still preserve its transaction fence.
    """
    try:
        experiment = _validated_experiment(staged.request)
        header = InferenceTransferSnapshotHeader.model_validate(
            staged.header.model_dump(mode="json")
        )
        index = tuple(
            InferenceTransferSnapshotIndexEntry.model_validate(row.model_dump(mode="json"))
            for row in staged.index
        )
        prepared = _hashed(
            InferenceTransferSnapshotPrepareResult,
            "result_sha256",
            header=header,
            index=index,
        )
        scope = experiment.scope
        prepare = header.prepare
        if (
            actor.actor_id != header.actor_id
            or actor.actor_id != scope.actor_id
            or scope.graph_snapshot != prepare.graph_snapshot
            or scope.policy_revision_id != prepare.access_policy_revision_id
            or scope.policy_sha256 != prepare.access_policy_sha256
            or scope.population_scope != prepare.population_scope
            or scope.projection_version != prepare.projection_version
            or scope.population_sha256 != header.population_sha256
            or scope.eligible_profile_set_sha256 != header.eligible_profile_set_sha256
            or scope.data_provenance != "AUTHORIZED_CORPUS_SNAPSHOT"
            or experiment.recipe != prepare.recipe
            or experiment.queries != _exact_queries(prepared)
        ):
            raise ValueError("staged experiment differs from its exact snapshot")
        sources = {source.item_revision_id: source for source in scope.population_sources}
        entries = {
            InferenceTransferProfilePointer.from_profile(entry.profile): entry
            for entry in experiment.entries
        }
        records = tuple(
            InferenceTransferSnapshotRecord(
                index_entry=row,
                source=sources[row.source_item_revision_id],
                staged_entry=None if row.profile is None else entries[row.profile],
            )
            for row in index
        )
        validate_snapshot_records(header, index, records)
        authorization = _hashed(
            InferenceTransferSnapshotAuthorizeRequest,
            "authorization_sha256",
            header=header,
            staged_entry_set_sha256=snapshot_entry_set_sha256(experiment.entries),
            staged_baseline_set_sha256=snapshot_baseline_set_sha256(experiment.baselines),
        )
        reply, _size = _received(
            port, actor, authorization, remaining_bytes=MAX_SNAPSHOT_FRAME_BYTES
        )
        if not isinstance(reply, InferenceTransferSnapshotAuthorizeResult):
            raise ValueError("owner returned a different authorization phase")
        validate_snapshot_authorize_result(authorization, reply)
        return reply
    except (ValueError, KeyError, JsonSchemaValidationError) as exc:
        raise SnapshotStagingError("INFERENCE_TRANSFER_STAGING_INPUT_OR_REPLY_INVALID") from exc
