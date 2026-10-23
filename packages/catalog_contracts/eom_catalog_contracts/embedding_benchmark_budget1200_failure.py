"""Versioned CPU1 post-start failure closure for the 1200-second benchmark family."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    MAX_POSTSTART_FAILURE_BYTES,
    BenchmarkPoststartOutputMember,
)
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    BenchmarkFailedControllerPin,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkExecutionId,
    benchmark_local_output_members,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

BUDGET1200_POSTSTART_SCHEMA = "embedding-benchmark-poststart-failure-v1.2"
BUDGET1200_POSTSTART_SCHEMA_REF = (
    "eom://schemas/knowledge/embedding-benchmark-poststart-failure/1.2"
)
type _Tick = Annotated[int, Field(ge=1, le=2**63 - 1, strict=True)]


class _Budget1200Contract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_wire(cls, value: object) -> object:
        return similarity_contract_document(
            value, BUDGET1200_POSTSTART_SCHEMA, MAX_POSTSTART_FAILURE_BYTES
        )


class BenchmarkBudget1200TerminalProof(FrozenModel):
    native_service: str = Field(
        pattern=r"^eom-embedding-benchmark-cpu-budget1200@[0-9a-f]{32}\.service$"
    )
    native_socket: str = Field(
        pattern=r"^eom-embedding-benchmark-cpu-budget1200@[0-9a-f]{32}\.socket$"
    )
    native_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    retirement_raw_sha256: Sha256
    main_pid: Literal[0]
    control_pid: Literal[0]
    descriptor_store_count: Literal[0]
    cgroup_empty: Literal[True]
    socket_inactive: Literal[True]
    retirement: Literal["CONFIRMED"]


class BenchmarkBudget1200PoststartObservation(_Budget1200Contract):
    schema_version: Literal["embedding-benchmark-poststart-failure/1.2"]
    kind: Literal["ROOT_OBSERVATION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    device: Literal["CPU"]
    launch_ordinal: Literal[1]
    association_sha256: Sha256
    prepared_sha256: Sha256
    completion_sha256: Sha256
    invocation_raw_sha256: Sha256
    completion_raw_sha256: Sha256
    original_outcome: Literal["FAILED"]
    cleanup: Literal["CONFIRMED"]
    started_ns: _Tick
    completed_ns: _Tick
    controller: BenchmarkFailedControllerPin
    terminal: BenchmarkBudget1200TerminalProof
    outputs: tuple[BenchmarkPoststartOutputMember, ...] = Field(min_length=16, max_length=16)
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    snapshot_sha256: Sha256
    observed_at: UtcDatetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_failed_execution(self) -> BenchmarkBudget1200PoststartObservation:
        if self.completed_ns <= self.started_ns:
            raise ValueError("BENCHMARK_BUDGET1200_COMPLETION_TIME_INVALID")
        prefix = "eom-embedding-benchmark-cpu-budget1200@" + self.execution_id
        if (self.terminal.native_service, self.terminal.native_socket) != (
            prefix + ".service",
            prefix + ".socket",
        ):
            raise ValueError("BENCHMARK_BUDGET1200_TERMINAL_EXECUTION_INVALID")
        if (
            tuple(member.member_name for member in self.outputs)
            != benchmark_local_output_members(1)
            or not any(member.byte_count for member in self.outputs)
            or sum(member.byte_count for member in self.outputs) > MAX_BENCHMARK_OUTPUT_BYTES
        ):
            raise ValueError("BENCHMARK_BUDGET1200_OUTPUT_LAYOUT_INVALID")
        _require_hash(self, "observation_sha256")
        return self


class BenchmarkBudget1200FailureDecision(_Budget1200Contract):
    schema_version: Literal["embedding-benchmark-poststart-failure/1.2"]
    kind: Literal["FAILURE_DECISION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    from_state: Literal["RUNNING"]
    to_state: Literal["FAILED"]
    error_code: Literal["BENCHMARK_POSTSTART_EXECUTION_FAILED"]
    observation: BenchmarkBudget1200PoststartObservation
    actor_id: ActorId
    decided_at: UtcDatetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_observation(self) -> BenchmarkBudget1200FailureDecision:
        if _pins(self) != _pins(self.observation) or self.decided_at < self.observation.observed_at:
            raise ValueError("BENCHMARK_BUDGET1200_DECISION_LINKAGE_INVALID")
        _require_hash(self, "decision_sha256")
        return self


class BenchmarkBudget1200PredecessorReference(_Budget1200Contract):
    schema_version: Literal["embedding-benchmark-poststart-failure/1.2"]
    kind: Literal["PREDECESSOR_REFERENCE"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    event_sequence: int = Field(ge=7, le=32, strict=True)
    decision_sha256: Sha256

    @classmethod
    def from_decision(
        cls, decision: BenchmarkBudget1200FailureDecision, *, event_sequence: int
    ) -> BenchmarkBudget1200PredecessorReference:
        checked = BenchmarkBudget1200FailureDecision.model_validate(decision)
        return cls(
            schema_version="embedding-benchmark-poststart-failure/1.2",
            kind="PREDECESSOR_REFERENCE",
            job_id=checked.job_id,
            execution_id=checked.execution_id,
            request_sha256=checked.request_sha256,
            invocation_sha256=checked.invocation_sha256,
            event_sequence=event_sequence,
            decision_sha256=checked.decision_sha256,
        )


type BenchmarkBudget1200FailureMessage = Annotated[
    BenchmarkBudget1200PoststartObservation
    | BenchmarkBudget1200FailureDecision
    | BenchmarkBudget1200PredecessorReference,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[BenchmarkBudget1200FailureMessage] = TypeAdapter(
    BenchmarkBudget1200FailureMessage
)


def _pins(value: FrozenModel) -> tuple[str, str, str, str]:
    fields = value.model_dump(mode="python")
    return (
        fields["job_id"],
        fields["execution_id"],
        fields["request_sha256"],
        fields["invocation_sha256"],
    )


def _require_hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("BENCHMARK_BUDGET1200_FAILURE_HASH_INVALID")


def benchmark_budget1200_failure_bytes(value: BenchmarkBudget1200FailureMessage) -> bytes:
    checked = _ADAPTER.validate_python(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_benchmark_budget1200_failure(raw: bytes) -> BenchmarkBudget1200FailureMessage:
    document = parse_rootlocal_evidence_document(raw, MAX_POSTSTART_FAILURE_BYTES)
    value = _ADAPTER.validate_python(document)
    if benchmark_budget1200_failure_bytes(value) != raw:
        raise ValueError("BENCHMARK_BUDGET1200_FAILURE_NONCANONICAL")
    return value
