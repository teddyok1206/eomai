"""Immutable maintenance-only execution proofs, distinct from admission and quality.

Ordered tuples preserve a bounded execution ledger; sets validate identities in O(n).
No worker IO, storage, authentication, or inferred provider-model identity belongs here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import BeforeValidator, Field, field_validator, model_validator

from eom_workflow.control_plane import FrozenModel, ReasoningEffort, Sha256, UtcDatetime
from eom_workflow.control_schemas import (
    CONTROL_SCHEMA_RESOURCES,
    load_control_schema,
    validate_control_contract,
)


def _require_wire_utc(value: object) -> object:
    if not isinstance(value, (str, datetime)):
        raise ValueError("timestamp must be a UTC datetime or ISO wire string")
    if isinstance(value, str) and not value.endswith("Z"):
        raise ValueError("wire timestamp must use UTC Z")
    return value


CompatibilityUtc = Annotated[UtcDatetime, BeforeValidator(_require_wire_utc)]
CompatibilityRunId = Annotated[str, Field(pattern=r"^codexcompat_[0-9a-f]{32}$")]
CompatibilityCaseId = Annotated[str, Field(pattern=r"^compatcase_[0-9a-f]{32}$")]
CompatibilityFailureCode = Literal[
    "WORKER_EXEC_FAILED", "WORKER_RESULT_INVALID", "RESULT_CONTENT_MISMATCH"
]
CompatibilityNotRunCode = Literal[
    "PREVIOUS_FAILURE",
    "MAINTENANCE_LOST",
    "RUNTIME_CHANGED",
    "REQUEST_EXPIRED",
    "UNCERTAIN_EXECUTION",
    "LOCAL_PREPARATION_FAILED",
]
_FAILURE_CODES = frozenset(
    {"WORKER_EXEC_FAILED", "WORKER_RESULT_INVALID", "RESULT_CONTENT_MISMATCH"}
)
_NOT_RUN_CODES = frozenset(
    {
        "PREVIOUS_FAILURE",
        "MAINTENANCE_LOST",
        "RUNTIME_CHANGED",
        "REQUEST_EXPIRED",
        "UNCERTAIN_EXECUTION",
        "LOCAL_PREPARATION_FAILED",
    }
)


class CodexCompatibilityCase(FrozenModel):
    case_id: CompatibilityCaseId
    slot_id: Literal["01", "02", "03", "04", "05", "06"]
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    assignment_revision_id: str | None = Field(pattern=r"^authassignrev_[0-9a-f]{32}$")
    expected_resource_version: int = Field(ge=1, strict=True)
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: ReasoningEffort


class CodexCompatibilityRequest(FrozenModel):
    schema_version: Literal["codex-compatibility-request/1.0"] = "codex-compatibility-request/1.0"
    run_id: CompatibilityRunId
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: CompatibilityUtc
    expires_at: CompatibilityUtc
    max_model_calls: int = Field(ge=1, le=64, strict=True)
    cases: tuple[CodexCompatibilityCase, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def bounded_immutable_request(self) -> CodexCompatibilityRequest:
        if not timedelta(0) < self.expires_at - self.created_at <= timedelta(hours=2):
            raise ValueError(
                "compatibility request lifespan must be positive and at most two hours"
            )
        if self.max_model_calls < len(self.cases):
            raise ValueError("model-call budget must cover every requested case")
        ids = {case.case_id for case in self.cases}
        pairs = {(case.binding_id, case.model, case.reasoning_effort) for case in self.cases}
        if len(ids) != len(self.cases) or len(pairs) != len(self.cases):
            raise ValueError(
                "compatibility case IDs and binding/model/effort triples must be unique"
            )
        return self


class CodexCompatibilityRuntime(FrozenModel):
    cli_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    cli_launcher_sha256: Sha256
    cli_binary_sha256: Sha256
    worker_exec_sha256: Sha256
    contract_sha256: Sha256


class CodexCompatibilityCaseResult(CodexCompatibilityCase):
    job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    status: Literal["PASS", "FAIL", "NOT_RUN"]
    error_code: CompatibilityFailureCode | CompatibilityNotRunCode | None
    invocation_sha256: Sha256 | None
    result_sha256: Sha256 | None
    elapsed_ms: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def honest_execution_result(self) -> CodexCompatibilityCaseResult:
        if self.status == "PASS":
            if (
                self.error_code is not None
                or self.invocation_sha256 is None
                or self.result_sha256 is None
            ):
                raise ValueError("passing execution requires exact invocation and result hashes")
        elif self.status == "FAIL":
            if self.error_code not in _FAILURE_CODES or self.invocation_sha256 is None:
                raise ValueError("failed execution requires its invocation hash and failure code")
        elif (
            self.error_code not in _NOT_RUN_CODES
            or self.invocation_sha256 is not None
            or self.result_sha256 is not None
            or self.elapsed_ms != 0
        ):
            raise ValueError("unexecuted cases cannot claim execution hashes or elapsed time")
        return self


def _case_pins(case: CodexCompatibilityCase) -> tuple[str, str, str, str | None, int, str, str]:
    return (
        case.case_id,
        case.slot_id,
        case.binding_id,
        case.assignment_revision_id,
        case.expected_resource_version,
        case.model,
        case.reasoning_effort,
    )


class CodexCompatibilityReport(FrozenModel):
    schema_version: Literal["codex-compatibility-report/1.0"] = "codex-compatibility-report/1.0"
    request: CodexCompatibilityRequest
    request_sha256: Sha256
    scope: Literal["LIVE_EXECUTION_SMOKE"] = "LIVE_EXECUTION_SMOKE"
    quality_evaluated: Literal[False] = False
    started_at: CompatibilityUtc
    completed_at: CompatibilityUtc
    runtime: CodexCompatibilityRuntime
    model_calls: int = Field(ge=0, le=64, strict=True)
    cases: tuple[CodexCompatibilityCaseResult, ...] = Field(min_length=1, max_length=64)

    @field_validator("quality_evaluated", mode="before")
    @classmethod
    def no_quality_claim(cls, value: object) -> Literal[False]:
        if value is not False:
            raise ValueError("compatibility execution cannot claim educational quality")
        return False

    @model_validator(mode="after")
    def exact_execution_ledger(self) -> CodexCompatibilityReport:
        if self.request_sha256 != compatibility_request_sha256(self.request):
            raise ValueError("compatibility request content hash differs")
        if (
            self.started_at < self.request.created_at
            or self.completed_at < self.started_at
            or self.started_at > self.request.expires_at
        ):
            raise ValueError("compatibility report timestamps contradict the approved request")
        if len(self.cases) != len(self.request.cases) or any(
            _case_pins(actual) != _case_pins(requested)
            for actual, requested in zip(self.cases, self.request.cases, strict=True)
        ):
            raise ValueError("compatibility report must preserve every ordered requested case pin")
        if len({case.job_id for case in self.cases}) != len(self.cases):
            raise ValueError("each compatibility case requires a distinct execution identity")
        calls = sum(case.status in {"PASS", "FAIL"} for case in self.cases)
        if self.model_calls != calls or calls > self.request.max_model_calls:
            raise ValueError(
                "model-call count must equal conclusively executed cases within budget"
            )
        stopped = False
        for case in self.cases:
            if stopped and case.status != "NOT_RUN":
                raise ValueError(
                    "compatibility execution cannot resume after failure or uncertainty"
                )
            stopped = case.status != "PASS"
        return self


class CodexCompatibilityInvocation(FrozenModel):
    schema_version: Literal["codex-compatibility-invocation/1.0"] = (
        "codex-compatibility-invocation/1.0"
    )
    run_id: CompatibilityRunId
    case_id: CompatibilityCaseId
    request_sha256: Sha256
    job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: ReasoningEffort
    image_sha256: Sha256
    invocation_sha256: Sha256

    @model_validator(mode="after")
    def exact_invocation_hash(self) -> CodexCompatibilityInvocation:
        if self.invocation_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"invocation_sha256"})
        ):
            raise ValueError("compatibility invocation content hash differs")
        return self


def compatibility_request_sha256(request: CodexCompatibilityRequest) -> str:
    return content_sha256(request.model_dump(mode="json"))


def compatibility_contract_sha256() -> str:
    """Pin the immutable installed schema resources without trusting a checkout."""

    pins = {}
    for name in (
        "codex-compatibility-request",
        "codex-compatibility-report",
        "codex-compatibility-invocation",
        "codex-compatibility-probe-result",
    ):
        load_control_schema(name)
        pins[name] = CONTROL_SCHEMA_RESOURCES[name].sha256
    return content_sha256(pins)


def load_compatibility_request(document: object) -> CodexCompatibilityRequest:
    validate_control_contract("codex-compatibility-request", document)
    return CodexCompatibilityRequest.model_validate(document)


def load_compatibility_report(document: object) -> CodexCompatibilityReport:
    validate_control_contract("codex-compatibility-report", document)
    return CodexCompatibilityReport.model_validate(document)


def load_compatibility_invocation(document: object) -> CodexCompatibilityInvocation:
    validate_control_contract("codex-compatibility-invocation", document)
    return CodexCompatibilityInvocation.model_validate(document)


class CodexCompatibilityProbeResult(FrozenModel):
    schema_version: Literal["codex-compatibility-probe-result/1.0"] = (
        "codex-compatibility-probe-result/1.0"
    )
    run_id: CompatibilityRunId
    case_id: CompatibilityCaseId
    request_sha256: Sha256
    arithmetic_sum: int = Field(ge=0, le=1000, strict=True)
    rectangle_count: int = Field(ge=0, le=5, strict=True)
    outline_circle_count: int = Field(ge=0, le=5, strict=True)
    left_shape: Literal["square", "circle", "triangle"]
    right_shape: Literal["square", "circle", "triangle"]


def load_compatibility_probe_result(document: object) -> CodexCompatibilityProbeResult:
    validate_control_contract("codex-compatibility-probe-result", document)
    return CodexCompatibilityProbeResult.model_validate(document)
