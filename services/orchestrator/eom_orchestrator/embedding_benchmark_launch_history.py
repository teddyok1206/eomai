"""Six ordered reservations in the original Job; never permission to execute a unit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from eom_catalog_contracts.embedding_benchmark_budget600_failure import (
    BenchmarkBudget600FailureDecision,
    BenchmarkBudget600PoststartObservation,
    BenchmarkBudget600PredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_budget1200_failure import (
    BenchmarkBudget1200FailureDecision,
    BenchmarkBudget1200PoststartObservation,
    BenchmarkBudget1200PredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_budget1200_retry_failure import (
    BenchmarkBudget1200RetryFailureDecision,
    BenchmarkBudget1200RetryPoststartObservation,
    BenchmarkBudget1200RetryPredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    POSTSTART_FAILURE_CODE,
    POSTSTART_FAILURE_EVENT,
    BenchmarkPoststartFailureDecision,
    BenchmarkPoststartObservation,
    BenchmarkPoststartPredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_preack_recovery import (
    PREACK_RECOVERY_EVENT,
    BenchmarkPreackRecoveryDecision,
    require_benchmark_preack_observation,
)
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    PRELAUNCH_FAILURE_CODE,
    PRELAUNCH_FAILURE_EVENT,
    BenchmarkPrelaunchFailureDecision,
    BenchmarkPrelaunchObservation,
    BenchmarkPrelaunchPredecessorReference,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkLaunchReceipt,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_identifiers import sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkJobAdmissionError,
    BenchmarkSourceAdmission,
    read_terminal_benchmark_job_in_session,
    require_benchmark_job_in_session,
)
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.state_machine import ALLOWED_TRANSITIONS, JobState

RESERVED_EVENT = "BENCHMARK_LAUNCH_RESERVED"
RECORDED_EVENT = "BENCHMARK_LAUNCH_RECORDED"
PREDECESSOR_EVENT = "BENCHMARK_PRELAUNCH_SUCCESSOR_REGISTERED"
POSTSTART_PREDECESSOR_EVENT = "BENCHMARK_POSTSTART_SUCCESSOR_REGISTERED"
type BenchmarkPredecessorReference = (
    BenchmarkPrelaunchPredecessorReference
    | BenchmarkPoststartPredecessorReference
    | BenchmarkBudget600PredecessorReference
    | BenchmarkBudget1200PredecessorReference
    | BenchmarkBudget1200RetryPredecessorReference
)


class BenchmarkResultReader(Protocol):
    def read_in_session(
        self, session: Session, request: BenchmarkOwnerRequest, pointer: ArtifactMemberPointer
    ) -> bytes:
        """Resolve exact authorized fixed members, never arbitrary worker-chosen paths.

        CPU near-tie reference reads additionally validate their same-Artifact f64
        member, original source/space closure and frozen complete-span clustering.
        """
        ...


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchRecord:
    invocation: BenchmarkWorkerInvocation
    receipt: BenchmarkLaunchReceipt | None


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchHistory:
    job_state: str
    launches: tuple[BenchmarkLaunchRecord, ...]
    prelaunch_failure: BenchmarkPrelaunchFailureRecord | None = None
    predecessor: BenchmarkPredecessorReference | None = None
    poststart_failure: BenchmarkPoststartFailureRecord | None = None
    retired_preack_launches: tuple[RetiredBenchmarkPreackLaunch, ...] = ()


@dataclass(frozen=True, slots=True)
class RetiredBenchmarkPreackLaunch:
    invocation: BenchmarkWorkerInvocation
    decision: BenchmarkPreackRecoveryDecision
    event_sequence: int


@dataclass(frozen=True, slots=True)
class BenchmarkPrelaunchFailureRecord:
    decision: BenchmarkPrelaunchFailureDecision
    event_sequence: int


@dataclass(frozen=True, slots=True)
class BenchmarkPoststartFailureRecord:
    decision: (
        BenchmarkPoststartFailureDecision
        | BenchmarkBudget600FailureDecision
        | BenchmarkBudget1200FailureDecision
        | BenchmarkBudget1200RetryFailureDecision
    )
    event_sequence: int


@dataclass(frozen=True, slots=True)
class CompletedBenchmarkLaunch:
    invocation: BenchmarkWorkerInvocation
    receipt: BenchmarkLaunchReceipt
    result: BenchmarkWorkerResult


def _require_receipt(
    invocation: BenchmarkWorkerInvocation, receipt: BenchmarkLaunchReceipt
) -> None:
    if (
        receipt.job_id != invocation.job_id
        or receipt.execution_id != invocation.execution_id
        or receipt.launch_ordinal != invocation.launch_ordinal
        or receipt.device != invocation.device
        or receipt.invocation_sha256 != invocation.invocation_sha256
        or receipt.observed_runtime_sha256 != invocation.runtime.numerical_runtime.runtime_sha256
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RECEIPT_CONFLICT")


def _history(
    session: Session,
    job: JobRecord,
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    *,
    ancestors: frozenset[str] = frozenset(),
) -> BenchmarkLaunchHistory:
    # Each recovery revision has at most one pinned parent. Bound corrupt/cyclic
    # chains rather than recurse through caller-selected latest revisions forever.
    if job.job_id in ancestors or len(ancestors) >= 32:
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_HISTORY_INVALID")
    ancestors = ancestors | {job.job_id}
    rows = tuple(
        session.scalars(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == job.job_id)
            .order_by(JobEventRecord.sequence)
            .limit(33)
        )
    )
    launches: list[BenchmarkLaunchRecord] = []
    execution_ids: set[str] = set()
    retired: list[RetiredBenchmarkPreackLaunch] = []
    recovered_ordinals: set[int] = set()
    if len(rows) > 32 or tuple(row.sequence for row in rows) != tuple(range(1, len(rows) + 1)):
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
    state = JobState.VALIDATED
    failure = None
    poststart_failure = None
    predecessor = None
    for row in rows[2:]:
        if row.event == PREACK_RECOVERY_EVENT:
            try:
                recovery = BenchmarkPreackRecoveryDecision.model_validate(row.data)
                if (
                    state != JobState.RUNNING
                    or (row.from_state, row.to_state) != ("RUNNING", "RUNNING")
                    or not launches
                    or launches[-1].receipt is not None
                    or recovery.actor_id != request.operator_audit_id
                    or launches[-1].invocation.launch_ordinal in recovered_ordinals
                ):
                    raise ValueError()
                original = launches[-1].invocation
                require_benchmark_preack_observation(request, original, recovery.observation)
            except (ValueError, SchemaError):
                raise BenchmarkJobAdmissionError("BENCHMARK_PREACK_HISTORY_INVALID") from None
            # Remove only from the executable projection. The original reservation,
            # failure proof and used execution identity remain append-only history.
            launches.pop()
            recovered_ordinals.add(original.launch_ordinal)
            retired.append(RetiredBenchmarkPreackLaunch(original, recovery, row.sequence))
            continue
        if row.event in {PREDECESSOR_EVENT, POSTSTART_PREDECESSOR_EVENT}:
            if (
                state != JobState.VALIDATED
                or (row.from_state, row.to_state) != ("VALIDATED", "VALIDATED")
                or row.sequence != 3
                or predecessor is not None
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_HISTORY_INVALID")
            try:
                predecessor = (
                    BenchmarkPrelaunchPredecessorReference.model_validate(row.data)
                    if row.event == PREDECESSOR_EVENT
                    else (
                        BenchmarkBudget600PredecessorReference.model_validate(row.data)
                        if row.data.get("schema_version")
                        == "embedding-benchmark-poststart-failure/1.1"
                        else (
                            BenchmarkBudget1200RetryPredecessorReference.model_validate(row.data)
                            if row.data.get("schema_version")
                            == "embedding-benchmark-poststart-failure/1.3"
                            else (
                                BenchmarkBudget1200PredecessorReference.model_validate(row.data)
                                if row.data.get("schema_version")
                                == "embedding-benchmark-poststart-failure/1.2"
                                else BenchmarkPoststartPredecessorReference.model_validate(row.data)
                            )
                        )
                    )
                )
            except (ValueError, SchemaError):
                raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_HISTORY_INVALID") from None
            _require_predecessor_in_session(
                session, request, inputs, predecessor, ancestors=ancestors
            )
            continue
        if row.event == PRELAUNCH_FAILURE_EVENT:
            try:
                decision = BenchmarkPrelaunchFailureDecision.model_validate(row.data)
            except (ValueError, SchemaError):
                raise BenchmarkJobAdmissionError("BENCHMARK_PRELAUNCH_HISTORY_INVALID") from None
            if (
                state != JobState.RUNNING
                or (row.from_state, row.to_state) != ("RUNNING", "FAILED")
                or failure is not None
                or poststart_failure is not None
                or len(launches) != 1
                or launches[0].receipt is not None
                or decision.actor_id != request.operator_audit_id
                or decision.decided_at < decision.observation.observed_at
                or job.error_code != PRELAUNCH_FAILURE_CODE
                or job.completed_at is None
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_PRELAUNCH_HISTORY_INVALID")
            require_benchmark_prelaunch_observation(
                request, launches[0].invocation, decision.observation
            )
            failure = BenchmarkPrelaunchFailureRecord(decision, row.sequence)
            state = JobState.FAILED
            continue
        if row.event == POSTSTART_FAILURE_EVENT:
            try:
                poststart_decision = (
                    BenchmarkBudget600FailureDecision.model_validate(row.data)
                    if row.data.get("schema_version") == "embedding-benchmark-poststart-failure/1.1"
                    else (
                        BenchmarkBudget1200RetryFailureDecision.model_validate(row.data)
                        if row.data.get("schema_version")
                        == "embedding-benchmark-poststart-failure/1.3"
                        else (
                            BenchmarkBudget1200FailureDecision.model_validate(row.data)
                            if row.data.get("schema_version")
                            == "embedding-benchmark-poststart-failure/1.2"
                            else BenchmarkPoststartFailureDecision.model_validate(row.data)
                        )
                    )
                )
            except (ValueError, SchemaError):
                raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_HISTORY_INVALID") from None
            if (
                state != JobState.RUNNING
                or (row.from_state, row.to_state) != ("RUNNING", "FAILED")
                or failure is not None
                or poststart_failure is not None
                or len(launches) != 1
                or launches[0].receipt is not None
                or poststart_decision.actor_id != request.operator_audit_id
                or job.error_code != POSTSTART_FAILURE_CODE
                or job.completed_at is None
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_HISTORY_INVALID")
            require_benchmark_poststart_observation(
                request, launches[0].invocation, poststart_decision.observation
            )
            poststart_failure = BenchmarkPoststartFailureRecord(poststart_decision, row.sequence)
            state = JobState.FAILED
            continue
        if row.event not in {RESERVED_EVENT, RECORDED_EVENT}:
            if row.from_state != state or row.to_state not in ALLOWED_TRANSITIONS[state]:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
            state = JobState(row.to_state)
            continue
        if state != JobState.RUNNING:
            raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
        if (row.from_state, row.to_state) != ("RUNNING", "RUNNING"):
            raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
        value = parse_embedding_device_benchmark(row.data)
        if row.event == RESERVED_EVENT:
            if (
                not isinstance(value, BenchmarkWorkerInvocation)
                or (launches and launches[-1].receipt is None)
                or value.job_id != job.job_id
                or value.launch_ordinal != len(launches) + 1
                or value.execution_id in execution_ids
                or (
                    launches
                    and launches[-1].receipt is not None
                    and launches[-1].receipt.cleanup != "CONFIRMED"
                )
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
            validate_benchmark_invocation(request, value, inputs)
            execution_ids.add(value.execution_id)
            launches.append(BenchmarkLaunchRecord(value, None))
        else:
            if (
                not isinstance(value, BenchmarkLaunchReceipt)
                or not launches
                or launches[-1].receipt is not None
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
            _require_receipt(launches[-1].invocation, value)
            launches[-1] = BenchmarkLaunchRecord(launches[-1].invocation, value)
    if state != job.status or len(launches) > 6:
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
    return BenchmarkLaunchHistory(
        job.status, tuple(launches), failure, predecessor, poststart_failure, tuple(retired)
    )


def require_benchmark_poststart_observation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    observation: BenchmarkPoststartObservation
    | BenchmarkBudget600PoststartObservation
    | BenchmarkBudget1200PoststartObservation
    | BenchmarkBudget1200RetryPoststartObservation,
) -> (
    BenchmarkPoststartObservation
    | BenchmarkBudget600PoststartObservation
    | BenchmarkBudget1200PoststartObservation
    | BenchmarkBudget1200RetryPoststartObservation
):
    """Link actual-start failure metadata; a parsed value is never root/OS authority."""
    try:
        checked = (
            BenchmarkBudget1200RetryPoststartObservation.model_validate(observation)
            if isinstance(observation, BenchmarkBudget1200RetryPoststartObservation)
            else (
                BenchmarkBudget600PoststartObservation.model_validate(observation)
                if isinstance(observation, BenchmarkBudget600PoststartObservation)
                else (
                    BenchmarkBudget1200PoststartObservation.model_validate(observation)
                    if isinstance(observation, BenchmarkBudget1200PoststartObservation)
                    else BenchmarkPoststartObservation.model_validate(observation)
                )
            )
        )
        if isinstance(checked, BenchmarkBudget1200RetryPoststartObservation):
            embedding_device_benchmark_bytes(request)
    except (ValueError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_OBSERVATION_INVALID") from None
    if (
        invocation.device != "CPU"
        or invocation.launch_ordinal != 1
        or request.execution_policy.timeout_seconds
        != (
            600
            if isinstance(checked, BenchmarkBudget600PoststartObservation)
            else (
                1200
                if isinstance(
                    checked,
                    (
                        BenchmarkBudget1200PoststartObservation,
                        BenchmarkBudget1200RetryPoststartObservation,
                    ),
                )
                else 180
            )
        )
        or (
            isinstance(checked, BenchmarkBudget1200RetryPoststartObservation)
            and (
                request.schema_version != "embedding-device-benchmark-request/1.2"
                or invocation.schema_version != "embedding-device-benchmark-invocation/1.2"
                or request.execution_policy.schema_version
                != "embedding-device-benchmark-policy/1.2"
                or invocation.execution_policy != request.execution_policy
            )
        )
        or checked.job_id != invocation.job_id
        or checked.execution_id != invocation.execution_id
        or checked.request_sha256 != request.request_sha256
        or checked.request_sha256 != invocation.owner_request_sha256
        or checked.invocation_sha256 != invocation.invocation_sha256
        or checked.invocation_raw_sha256
        != sha256_bytes(embedding_device_benchmark_bytes(invocation))
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_OBSERVATION_CONFLICT")
    return checked


def require_benchmark_prelaunch_observation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    observation: BenchmarkPrelaunchObservation,
) -> BenchmarkPrelaunchObservation:
    """Pure original-invocation linkage, never proof of root origin or current OS state."""
    try:
        checked = BenchmarkPrelaunchObservation.model_validate(observation)
    except (ValueError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_PRELAUNCH_OBSERVATION_INVALID") from None
    if (
        invocation.device != "CPU"
        or invocation.launch_ordinal != 1
        or checked.job_id != invocation.job_id
        or checked.execution_id != invocation.execution_id
        or checked.request_sha256 != request.request_sha256
        or checked.request_sha256 != invocation.owner_request_sha256
        or checked.invocation_sha256 != invocation.invocation_sha256
        or checked.invocation_raw_sha256
        != sha256_bytes(embedding_device_benchmark_bytes(invocation))
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_PRELAUNCH_OBSERVATION_CONFLICT")
    return checked


def require_benchmark_prelaunch_predecessor(
    session: Session,
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    reference: BenchmarkPrelaunchPredecessorReference,
    *,
    ancestors: frozenset[str] = frozenset(),
) -> BenchmarkOwnerRequest:
    """Resolve only the indexed pinned terminal parent; no latest/JSON scan or parent lock.

    Terminal parent state/history is immutable through supported application APIs.
    Avoid acquiring an old parent lock while already holding the new Job lock.
    Current source authority belongs to the caller; all semantic source/runtime
    pins are equal, and the admitted inputs must reproduce the parent's exact bytes
    when only the immutable benchmark revision is restored.
    """
    try:
        reference = BenchmarkPrelaunchPredecessorReference.model_validate(reference)
    except (ValueError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_REFERENCE_INVALID") from None
    row = session.get(JobRecord, reference.job_id, populate_existing=True)
    if row is None:
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_MISSING")
    try:
        parent = BenchmarkOwnerRequest.model_validate(row.request)
    except (ValueError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_HISTORY_INVALID") from None
    excluded = {"benchmark_revision_id", "input_manifest", "request_sha256"}
    if (
        parent.benchmark_revision_id == request.benchmark_revision_id
        or parent.model_dump(mode="json", exclude=excluded)
        != request.model_dump(mode="json", exclude=excluded)
        or parent.request_sha256 != reference.request_sha256
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_SELECTION_CONFLICT")
    job = read_terminal_benchmark_job_in_session(session, parent, job_id=reference.job_id)
    # A shallow immutable projection reuses row/text values; no second canonical
    # Item payload or large DB value is created for predecessor resolution.
    parent_inputs = inputs.model_copy(
        update={"benchmark_revision_id": parent.benchmark_revision_id}
    )
    history = _history(session, job, parent, parent_inputs, ancestors=ancestors)
    failure = history.prelaunch_failure
    if (
        job.status != JobState.FAILED
        or failure is None
        or BenchmarkPrelaunchPredecessorReference.from_decision(
            failure.decision, event_sequence=failure.event_sequence
        )
        != reference
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_CLOSURE_REQUIRED")
    return parent


def record_benchmark_prelaunch_predecessor_in_session(
    session: Session,
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    reference: BenchmarkPrelaunchPredecessorReference,
    *,
    job_id: str,
) -> bool:
    return _record_predecessor_in_session(session, request, inputs, reference, job_id=job_id)


def require_benchmark_poststart_predecessor(
    session: Session,
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    reference: (
        BenchmarkPoststartPredecessorReference
        | BenchmarkBudget600PredecessorReference
        | BenchmarkBudget1200PredecessorReference
        | BenchmarkBudget1200RetryPredecessorReference
    ),
    *,
    ancestors: frozenset[str] = frozenset(),
) -> BenchmarkOwnerRequest:
    """Resolve exact failed-parent links across the fixed 180→600→1200 budget path.

    Source text, tokens, numerical recipe, runtime, model, Graph and access-policy
    pins stay equal. A new budget cannot launder an arbitrary content/model change.
    """
    try:
        reference = (
            BenchmarkBudget1200RetryPredecessorReference.model_validate(reference)
            if isinstance(reference, BenchmarkBudget1200RetryPredecessorReference)
            else (
                BenchmarkBudget600PredecessorReference.model_validate(reference)
                if isinstance(reference, BenchmarkBudget600PredecessorReference)
                else (
                    BenchmarkBudget1200PredecessorReference.model_validate(reference)
                    if isinstance(reference, BenchmarkBudget1200PredecessorReference)
                    else BenchmarkPoststartPredecessorReference.model_validate(reference)
                )
            )
        )
    except (ValueError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_REFERENCE_INVALID") from None
    row = session.get(JobRecord, reference.job_id, populate_existing=True)
    if row is None:
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_MISSING")
    try:
        parent = BenchmarkOwnerRequest.model_validate(row.request)
    except (ValueError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_HISTORY_INVALID") from None
    excluded = {
        "schema_version",
        "benchmark_revision_id",
        "input_manifest",
        "execution_policy",
        "request_sha256",
    }
    policy_excluded = {
        "schema_version",
        "policy_revision_id",
        "timeout_seconds",
        "policy_sha256",
    }
    predecessor_v11 = isinstance(reference, BenchmarkBudget600PredecessorReference)
    predecessor_v13 = isinstance(reference, BenchmarkBudget1200RetryPredecessorReference)
    predecessor_v12 = isinstance(reference, BenchmarkBudget1200PredecessorReference)
    expected_parent_version, expected_successor_version, expected_timeout, successor_timeout = (
        (
            "embedding-device-benchmark-request/1.1",
            "embedding-device-benchmark-request/1.2",
            600,
            1200,
        )
        if predecessor_v11
        else (
            (
                "embedding-device-benchmark-request/1.2",
                "embedding-device-benchmark-request/1.2",
                1200,
                1200,
            )
            if predecessor_v12 or predecessor_v13
            else (
                "embedding-device-benchmark-request/1.0",
                "embedding-device-benchmark-request/1.1",
                180,
                600,
            )
        )
    )
    if (
        parent.benchmark_revision_id == request.benchmark_revision_id
        or parent.request_sha256 != reference.request_sha256
        or parent.schema_version != expected_parent_version
        or request.schema_version != expected_successor_version
        or parent.model_dump(mode="json", exclude=excluded)
        != request.model_dump(mode="json", exclude=excluded)
        or parent.execution_policy.timeout_seconds != expected_timeout
        or request.execution_policy.timeout_seconds != successor_timeout
        or parent.execution_policy.policy_revision_id == request.execution_policy.policy_revision_id
        or parent.execution_policy.model_dump(mode="json", exclude=policy_excluded)
        != request.execution_policy.model_dump(mode="json", exclude=policy_excluded)
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_SUCCESSOR_SELECTION_CONFLICT")
    job = read_terminal_benchmark_job_in_session(session, parent, job_id=reference.job_id)
    parent_inputs = inputs.model_copy(
        update={"benchmark_revision_id": parent.benchmark_revision_id}
    )
    history = _history(session, job, parent, parent_inputs, ancestors=ancestors)
    failure = history.poststart_failure
    if job.status != JobState.FAILED or failure is None:
        raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_PREDECESSOR_CLOSURE_REQUIRED")
    if predecessor_v11:
        if not isinstance(failure.decision, BenchmarkBudget600FailureDecision) or (
            BenchmarkBudget600PredecessorReference.from_decision(
                failure.decision, event_sequence=failure.event_sequence
            )
            != reference
        ):
            raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_PREDECESSOR_CLOSURE_REQUIRED")
    elif predecessor_v13:
        if not isinstance(failure.decision, BenchmarkBudget1200RetryFailureDecision) or (
            BenchmarkBudget1200RetryPredecessorReference.from_decision(
                failure.decision, event_sequence=failure.event_sequence
            )
            != reference
        ):
            raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_PREDECESSOR_CLOSURE_REQUIRED")
    elif predecessor_v12:
        if not isinstance(failure.decision, BenchmarkBudget1200FailureDecision) or (
            BenchmarkBudget1200PredecessorReference.from_decision(
                failure.decision, event_sequence=failure.event_sequence
            )
            != reference
        ):
            raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_PREDECESSOR_CLOSURE_REQUIRED")
    elif not isinstance(failure.decision, BenchmarkPoststartFailureDecision) or (
        BenchmarkPoststartPredecessorReference.from_decision(
            failure.decision, event_sequence=failure.event_sequence
        )
        != reference
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_PREDECESSOR_CLOSURE_REQUIRED")
    return parent


def _require_predecessor_in_session(
    session: Session,
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    reference: BenchmarkPredecessorReference,
    *,
    ancestors: frozenset[str] = frozenset(),
) -> BenchmarkOwnerRequest:
    if isinstance(
        reference,
        (
            BenchmarkPoststartPredecessorReference,
            BenchmarkBudget600PredecessorReference,
            BenchmarkBudget1200PredecessorReference,
            BenchmarkBudget1200RetryPredecessorReference,
        ),
    ):
        return require_benchmark_poststart_predecessor(
            session, request, inputs, reference, ancestors=ancestors
        )
    return require_benchmark_prelaunch_predecessor(
        session, request, inputs, reference, ancestors=ancestors
    )


def record_benchmark_poststart_predecessor_in_session(
    session: Session,
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    reference: (
        BenchmarkPoststartPredecessorReference
        | BenchmarkBudget600PredecessorReference
        | BenchmarkBudget1200PredecessorReference
        | BenchmarkBudget1200RetryPredecessorReference
    ),
    *,
    job_id: str,
) -> bool:
    return _record_predecessor_in_session(session, request, inputs, reference, job_id=job_id)


def _record_predecessor_in_session(
    session: Session,
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    reference: BenchmarkPredecessorReference,
    *,
    job_id: str,
) -> bool:
    """Append the explicit successor pin under the caller's current source fence.

    Must run in the same root as original target registration. It never creates
    a Job, authenticates an actor, or grants permission to launch a model.
    """
    job = require_benchmark_job_in_session(session, request, job_id=job_id)
    history = _history(session, job, request, inputs)
    if history.predecessor is not None:
        if history.predecessor != reference:
            raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_REFERENCE_CONFLICT")
        return False
    if job.status != JobState.VALIDATED or history.launches:
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_TARGET_ALREADY_STARTED")
    _require_predecessor_in_session(session, request, inputs, reference)
    sequence = session.scalar(
        select(func.coalesce(func.max(JobEventRecord.sequence), 0) + 1).where(
            JobEventRecord.job_id == job_id
        )
    )
    if sequence != 3:
        raise BenchmarkJobAdmissionError("BENCHMARK_PREDECESSOR_HISTORY_INVALID")
    job.updated_at = datetime.now(UTC)
    session.add(
        JobEventRecord(
            job_id=job_id,
            sequence=sequence,
            from_state="VALIDATED",
            to_state="VALIDATED",
            event=POSTSTART_PREDECESSOR_EVENT
            if isinstance(
                reference,
                (
                    BenchmarkPoststartPredecessorReference,
                    BenchmarkBudget600PredecessorReference,
                    BenchmarkBudget1200PredecessorReference,
                    BenchmarkBudget1200RetryPredecessorReference,
                ),
            )
            else PREDECESSOR_EVENT,
            data=reference.model_dump(mode="json"),
        )
    )
    session.flush()
    _history(session, job, request, inputs)
    return True


def _append(
    session: Session,
    job: JobRecord,
    event: str,
    value: BenchmarkWorkerInvocation | BenchmarkLaunchReceipt | BenchmarkPreackRecoveryDecision,
) -> None:
    # The original Job row is already locked, including exact event replays.
    sequence = session.scalar(
        select(func.coalesce(func.max(JobEventRecord.sequence), 0) + 1).where(
            JobEventRecord.job_id == job.job_id
        )
    )
    if sequence is None:
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
    job.updated_at = datetime.now(UTC)
    session.add(
        JobEventRecord(
            job_id=job.job_id,
            sequence=sequence,
            from_state="RUNNING",
            to_state="RUNNING",
            event=event,
            data=value.model_dump(mode="json"),
        )
    )
    session.flush()


class BenchmarkLaunchJournal:
    """Short current-source-fenced roots, not a scheduler, launcher or Artifact publisher."""

    def __init__(
        self, source_admission: BenchmarkSourceAdmission, result_reader: BenchmarkResultReader
    ) -> None:
        self.source_admission, self.result_reader = source_admission, result_reader

    def _result(
        self,
        session: Session,
        request: BenchmarkOwnerRequest,
        invocation: BenchmarkWorkerInvocation,
        receipt: BenchmarkLaunchReceipt,
    ) -> BenchmarkWorkerResult:
        raw = self.result_reader.read_in_session(session, request, receipt.worker_result)
        result = parse_embedding_device_benchmark_bytes(raw)
        if (
            not isinstance(result, BenchmarkWorkerResult)
            or embedding_device_benchmark_bytes(result) != raw
            or sha256_bytes(raw) != receipt.worker_result.sha256
            or result.execution_id != invocation.execution_id
            or result.invocation_sha256 != invocation.invocation_sha256
            or result.launch_ordinal != invocation.launch_ordinal
            or result.device != invocation.device
        ):
            raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RESULT_CONFLICT")
        return result

    def read(
        self, session: Session, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> BenchmarkLaunchHistory:
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=job_id)
            return _history(session, job, request, inputs)

    def reserve(
        self,
        session: Session,
        request: BenchmarkOwnerRequest,
        invocation: BenchmarkWorkerInvocation,
    ) -> tuple[BenchmarkLaunchHistory, bool]:
        embedding_device_benchmark_bytes(invocation)
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=invocation.job_id)
            validate_benchmark_invocation(request, invocation, inputs)
            history = _history(session, job, request, inputs)
            if invocation.launch_ordinal <= len(history.launches):
                if history.launches[invocation.launch_ordinal - 1].invocation != invocation:
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RESERVATION_CONFLICT")
                return history, False
            if (
                job.status != JobState.RUNNING
                or invocation.launch_ordinal != len(history.launches) + 1
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_NOT_RUNNABLE")
            if history.launches:
                previous = history.launches[-1]
                receipt = previous.receipt
                if receipt is None or receipt.cleanup != "CONFIRMED":
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_PREVIOUS_UNRESOLVED")
                if (
                    self._result(session, request, previous.invocation, receipt).status
                    != "COMPLETED"
                ):
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_PREVIOUS_NOT_COMPLETED")
            used = {row.invocation.execution_id for row in history.launches} | {
                row.invocation.execution_id for row in history.retired_preack_launches
            }
            if invocation.execution_id in used:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_EXECUTION_REUSED")
            _append(session, job, RESERVED_EVENT, invocation)
            return _history(session, job, request, inputs), True

    def recover_preack(
        self,
        session: Session,
        request: BenchmarkOwnerRequest,
        decision: BenchmarkPreackRecoveryDecision,
    ) -> tuple[BenchmarkLaunchHistory, bool]:
        """Append under the original Job row lock; caller owns live root/source fences."""
        checked = BenchmarkPreackRecoveryDecision.model_validate(decision)
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=checked.job_id)
            history = _history(session, job, request, inputs)
            for retired in history.retired_preack_launches:
                if retired.invocation.execution_id == checked.execution_id:
                    if retired.decision.observation != checked.observation:
                        raise BenchmarkJobAdmissionError("BENCHMARK_PREACK_REPLAY_CONFLICT")
                    return history, False
            if (
                job.status != JobState.RUNNING
                or not history.launches
                or history.launches[-1].receipt is not None
                or checked.actor_id != request.operator_audit_id
                or checked.observation.launch_ordinal
                in {row.invocation.launch_ordinal for row in history.retired_preack_launches}
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_PREACK_NOT_RECOVERABLE")
            require_benchmark_preack_observation(
                request, history.launches[-1].invocation, checked.observation
            )
            _append(session, job, PREACK_RECOVERY_EVENT, checked)
            return _history(session, job, request, inputs), True

    def record(
        self, session: Session, request: BenchmarkOwnerRequest, receipt: BenchmarkLaunchReceipt
    ) -> tuple[BenchmarkLaunchHistory, bool]:
        embedding_device_benchmark_bytes(receipt)
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=receipt.job_id)
            history = _history(session, job, request, inputs)
            if receipt.launch_ordinal > len(history.launches):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_NOT_RESERVED")
            prior = history.launches[receipt.launch_ordinal - 1]
            _require_receipt(prior.invocation, receipt)
            if prior.receipt is not None:
                if prior.receipt != receipt:
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RECEIPT_CONFLICT")
                return history, False
            if job.status != JobState.RUNNING:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_NOT_RUNNABLE")
            # Retain valid FAILED/UNCERTAIN evidence, but never invent a published result.
            self._result(session, request, prior.invocation, receipt)
            _append(session, job, RECORDED_EVENT, receipt)
            return _history(session, job, request, inputs), True

    def require_completed(
        self, session: Session, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> tuple[BenchmarkLaunchReceipt, ...]:
        """Current exact evidence for all six launches, not parent success or device approval."""
        return tuple(
            launch.receipt
            for launch in self.require_completed_launches(session, request, job_id=job_id)
        )

    def require_completed_launches(
        self, session: Session, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> tuple[CompletedBenchmarkLaunch, ...]:
        """Reuse each canonical result read for final assessment, never duplicate its parsing."""
        completed = self.require_completed_prefix(session, request, job_id=job_id)
        if len(completed) != 6:
            raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_SERIES_INCOMPLETE")
        return completed

    def require_completed_prefix(
        self, session: Session, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> tuple[CompletedBenchmarkLaunch, ...]:
        """Validate a clean same-Job progress boundary, not a complete six-run verdict."""
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=job_id)
            history = _history(session, job, request, inputs)
            if not 1 <= len(history.launches) <= 6:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_SERIES_INCOMPLETE")
            completed: list[CompletedBenchmarkLaunch] = []
            for launch in history.launches:
                receipt = launch.receipt
                if receipt is None or receipt.cleanup != "CONFIRMED":
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_SERIES_INCOMPLETE")
                result = self._result(session, request, launch.invocation, receipt)
                if result.status != "COMPLETED":
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_SERIES_INCOMPLETE")
                completed.append(CompletedBenchmarkLaunch(launch.invocation, receipt, result))
            return tuple(completed)
