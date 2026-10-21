"""Failure metadata only; neither parsed observations nor closure references grant authority."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkExecutionId
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

PRELAUNCH_FAILURE_SCHEMA = "embedding-benchmark-prelaunch-failure"
PRELAUNCH_FAILURE_SCHEMA_REF = "eom://schemas/knowledge/embedding-benchmark-prelaunch-failure/1.0"
MAX_PRELAUNCH_FAILURE_BYTES = 16 * 1024
PRELAUNCH_FAILURE_EVENT = "BENCHMARK_PRELAUNCH_FAILURE_CLOSED"
PRELAUNCH_FAILURE_CODE = "BENCHMARK_PRELAUNCH_PREPARATION_FAILED"


class _PrelaunchContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_wire(cls, value: object) -> object:
        return similarity_contract_document(
            value, PRELAUNCH_FAILURE_SCHEMA, MAX_PRELAUNCH_FAILURE_BYTES
        )


class BenchmarkFailedControllerPin(FrozenModel):
    unit: str = Field(pattern=r"^eom-gpu-benchmark-[A-Za-z0-9-]+\.service$")
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    supervisor_raw_sha256: Sha256


class BenchmarkPrelaunchObservation(_PrelaunchContract):
    schema_version: Literal["embedding-benchmark-prelaunch-failure/1.0"]
    kind: Literal["ROOT_OBSERVATION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    device: Literal["CPU"]
    launch_ordinal: Literal[1]
    association_sha256: Sha256
    uncertainty_sha256: Sha256
    invocation_raw_sha256: Sha256
    uncertainty_raw_sha256: Sha256
    controller: BenchmarkFailedControllerPin
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    snapshot_sha256: Sha256
    output_count: Literal[16]
    disposition: Literal["PREPARATION_FAILED_BEFORE_NATIVE_START"]
    observed_at: UtcDatetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def sealed_observation(self) -> BenchmarkPrelaunchObservation:
        _require_hash(self, "observation_sha256")
        return self


class BenchmarkPrelaunchFailureDecision(_PrelaunchContract):
    schema_version: Literal["embedding-benchmark-prelaunch-failure/1.0"]
    kind: Literal["FAILURE_DECISION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    from_state: Literal["RUNNING"]
    to_state: Literal["FAILED"]
    error_code: Literal["BENCHMARK_PRELAUNCH_PREPARATION_FAILED"]
    observation: BenchmarkPrelaunchObservation
    actor_id: ActorId
    decided_at: UtcDatetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_original_observation(self) -> BenchmarkPrelaunchFailureDecision:
        if _pins(self) != _pins(self.observation):
            raise ValueError("BENCHMARK_PRELAUNCH_DECISION_LINKAGE_INVALID")
        _require_hash(self, "decision_sha256")
        return self


class BenchmarkPrelaunchPredecessorReference(_PrelaunchContract):
    schema_version: Literal["embedding-benchmark-prelaunch-failure/1.0"]
    kind: Literal["PREDECESSOR_REFERENCE"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    event_sequence: int = Field(ge=7, le=32, strict=True)
    decision_sha256: Sha256

    @classmethod
    def from_decision(
        cls, decision: BenchmarkPrelaunchFailureDecision, *, event_sequence: int
    ) -> BenchmarkPrelaunchPredecessorReference:
        checked = BenchmarkPrelaunchFailureDecision.model_validate(decision)
        return cls(
            schema_version="embedding-benchmark-prelaunch-failure/1.0",
            kind="PREDECESSOR_REFERENCE",
            job_id=checked.job_id,
            execution_id=checked.execution_id,
            request_sha256=checked.request_sha256,
            invocation_sha256=checked.invocation_sha256,
            event_sequence=event_sequence,
            decision_sha256=checked.decision_sha256,
        )


type BenchmarkPrelaunchFailureMessage = Annotated[
    BenchmarkPrelaunchObservation
    | BenchmarkPrelaunchFailureDecision
    | BenchmarkPrelaunchPredecessorReference,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[BenchmarkPrelaunchFailureMessage] = TypeAdapter(
    BenchmarkPrelaunchFailureMessage
)


def _pins(
    value: BenchmarkPrelaunchObservation | BenchmarkPrelaunchFailureDecision,
) -> tuple[str, str, str, str]:
    return value.job_id, value.execution_id, value.request_sha256, value.invocation_sha256


def _require_hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("BENCHMARK_PRELAUNCH_FAILURE_HASH_INVALID")


def benchmark_prelaunch_failure_bytes(value: BenchmarkPrelaunchFailureMessage) -> bytes:
    checked = _ADAPTER.validate_python(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_benchmark_prelaunch_failure(raw: bytes) -> BenchmarkPrelaunchFailureMessage:
    document = parse_rootlocal_evidence_document(raw, MAX_PRELAUNCH_FAILURE_BYTES)
    value = _ADAPTER.validate_python(document)
    if benchmark_prelaunch_failure_bytes(value) != raw:
        raise ValueError("BENCHMARK_PRELAUNCH_FAILURE_NONCANONICAL")
    return value
