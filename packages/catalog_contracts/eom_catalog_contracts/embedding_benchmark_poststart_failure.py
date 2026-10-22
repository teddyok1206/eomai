"""CPU1 failure metadata only; parsed values grant no source, cleanup or retry authority."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    BenchmarkFailedControllerPin,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkExecutionId,
    BenchmarkF32Name,
    benchmark_local_output_members,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

POSTSTART_FAILURE_SCHEMA = "embedding-benchmark-poststart-failure"
POSTSTART_FAILURE_SCHEMA_REF = "eom://schemas/knowledge/embedding-benchmark-poststart-failure/1.0"
MAX_POSTSTART_FAILURE_BYTES = 16 * 1024
POSTSTART_FAILURE_EVENT = "BENCHMARK_POSTSTART_FAILURE_CLOSED"
POSTSTART_FAILURE_CODE = "BENCHMARK_POSTSTART_EXECUTION_FAILED"
_EMPTY_SHA256 = sha256_bytes(b"")
type _Tick = Annotated[int, Field(ge=1, le=2**63 - 1, strict=True)]


class _PoststartContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_wire(cls, value: object) -> object:
        return similarity_contract_document(
            value, POSTSTART_FAILURE_SCHEMA, MAX_POSTSTART_FAILURE_BYTES
        )


class BenchmarkPoststartOutputMember(FrozenModel):
    """Partial local bytes are not a validated vector sample or published Artifact."""

    member_name: (
        BenchmarkF32Name
        | Literal["token-witness.json", "timings.json", "resources.json", "worker-result.json"]
    )
    byte_count: int = Field(ge=0, le=MAX_BENCHMARK_OUTPUT_BYTES, strict=True)
    raw_sha256: Sha256

    @model_validator(mode="after")
    def exact_empty_member(self) -> BenchmarkPoststartOutputMember:
        if self.byte_count == 0 and self.raw_sha256 != _EMPTY_SHA256:
            raise ValueError("BENCHMARK_POSTSTART_EMPTY_MEMBER_HASH_INVALID")
        return self


class BenchmarkPoststartTerminalProof(FrozenModel):
    """Snapshot facts; only the installed adapter can establish actual PID1 provenance."""

    native_service: str = Field(pattern=r"^eom-embedding-benchmark-cpu@[0-9a-f]{32}\.service$")
    native_socket: str = Field(pattern=r"^eom-embedding-benchmark-cpu@[0-9a-f]{32}\.socket$")
    native_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    retirement_raw_sha256: Sha256
    main_pid: Literal[0]
    control_pid: Literal[0]
    descriptor_store_count: Literal[0]
    cgroup_empty: Literal[True]
    socket_inactive: Literal[True]
    retirement: Literal["CONFIRMED"]


class BenchmarkPoststartObservation(_PoststartContract):
    schema_version: Literal["embedding-benchmark-poststart-failure/1.0"]
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
    terminal: BenchmarkPoststartTerminalProof
    outputs: tuple[BenchmarkPoststartOutputMember, ...] = Field(min_length=16, max_length=16)
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    snapshot_sha256: Sha256
    observed_at: UtcDatetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_started_failed_execution(self) -> BenchmarkPoststartObservation:
        # No workflow import: these hashes pin the existing root completion; the
        # trusted adapter must parse its original contract and compare every fact.
        if self.completed_ns <= self.started_ns:
            raise ValueError("BENCHMARK_POSTSTART_COMPLETION_TIME_INVALID")
        prefix = "eom-embedding-benchmark-cpu@" + self.execution_id
        if (self.terminal.native_service, self.terminal.native_socket) != (
            prefix + ".service",
            prefix + ".socket",
        ):
            raise ValueError("BENCHMARK_POSTSTART_TERMINAL_EXECUTION_INVALID")
        if (
            tuple(member.member_name for member in self.outputs)
            != benchmark_local_output_members(1)
            or not any(member.byte_count for member in self.outputs)
            or sum(member.byte_count for member in self.outputs) > MAX_BENCHMARK_OUTPUT_BYTES
        ):
            raise ValueError("BENCHMARK_POSTSTART_OUTPUT_LAYOUT_INVALID")
        _require_hash(self, "observation_sha256")
        return self


class BenchmarkPoststartFailureDecision(_PoststartContract):
    schema_version: Literal["embedding-benchmark-poststart-failure/1.0"]
    kind: Literal["FAILURE_DECISION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    from_state: Literal["RUNNING"]
    to_state: Literal["FAILED"]
    error_code: Literal["BENCHMARK_POSTSTART_EXECUTION_FAILED"]
    observation: BenchmarkPoststartObservation
    actor_id: ActorId
    decided_at: UtcDatetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_original_observation(self) -> BenchmarkPoststartFailureDecision:
        if _pins(self) != _pins(self.observation) or self.decided_at < self.observation.observed_at:
            raise ValueError("BENCHMARK_POSTSTART_DECISION_LINKAGE_INVALID")
        _require_hash(self, "decision_sha256")
        return self


class BenchmarkPoststartPredecessorReference(_PoststartContract):
    schema_version: Literal["embedding-benchmark-poststart-failure/1.0"]
    kind: Literal["PREDECESSOR_REFERENCE"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    event_sequence: int = Field(ge=7, le=32, strict=True)
    decision_sha256: Sha256

    @classmethod
    def from_decision(
        cls, decision: BenchmarkPoststartFailureDecision, *, event_sequence: int
    ) -> BenchmarkPoststartPredecessorReference:
        checked = BenchmarkPoststartFailureDecision.model_validate(decision)
        return cls(
            schema_version="embedding-benchmark-poststart-failure/1.0",
            kind="PREDECESSOR_REFERENCE",
            job_id=checked.job_id,
            execution_id=checked.execution_id,
            request_sha256=checked.request_sha256,
            invocation_sha256=checked.invocation_sha256,
            event_sequence=event_sequence,
            decision_sha256=checked.decision_sha256,
        )


type BenchmarkPoststartFailureMessage = Annotated[
    BenchmarkPoststartObservation
    | BenchmarkPoststartFailureDecision
    | BenchmarkPoststartPredecessorReference,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[BenchmarkPoststartFailureMessage] = TypeAdapter(
    BenchmarkPoststartFailureMessage
)


def _pins(
    value: BenchmarkPoststartObservation | BenchmarkPoststartFailureDecision,
) -> tuple[str, str, str, str]:
    return value.job_id, value.execution_id, value.request_sha256, value.invocation_sha256


def _require_hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("BENCHMARK_POSTSTART_FAILURE_HASH_INVALID")


def benchmark_poststart_failure_bytes(value: BenchmarkPoststartFailureMessage) -> bytes:
    checked = _ADAPTER.validate_python(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_benchmark_poststart_failure(raw: bytes) -> BenchmarkPoststartFailureMessage:
    document = parse_rootlocal_evidence_document(raw, MAX_POSTSTART_FAILURE_BYTES)
    value = _ADAPTER.validate_python(document)
    if benchmark_poststart_failure_bytes(value) != raw:
        raise ValueError("BENCHMARK_POSTSTART_FAILURE_NONCANONICAL")
    return value
