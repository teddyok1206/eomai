"""Evaluation-only contracts for the FLUX.2 reference line-art probe."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.visual_reference import (
    LocalImageReferenceConditioningOutput,
    LocalImageReferenceSimplification,
    LocalImageReferenceSimplificationMetrics,
    LocalImageReferenceSimplifierRuntime,
    VisualReferencePngArtifactPointer,
)

MODEL_CANDIDATE_SCHEMA_REF = "eom://schemas/image-provider/local-image-model-candidate-manifest/1.0"
FLUX2_PROBE_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-flux2-reference-probe-plan/1.0"
)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


class LocalImageCandidateFile(FrozenModel):
    relative_path: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$",
    )
    size_bytes: int = Field(ge=1, le=64 * 1024 * 1024 * 1024)
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        if ".." in value.split("/") or "//" in value:
            raise ValueError("candidate model path is unsafe")
        return value


class Flux2KleinUpstream(FrozenModel):
    repo_id: Literal["black-forest-labs/FLUX.2-klein-base-4B"]
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_url: Literal["https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B"]
    license_id: Literal["Apache-2.0"]


class LocalImageModelCandidateManifest(FrozenModel):
    schema_version: Literal["local-image-model-candidate-manifest/1.0"]
    model_id: str = Field(pattern=r"^imgmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    provider_family: Literal["diffusers-flux2-klein-base-4b"]
    runtime_contract_version: Literal["eom-local-image-candidate-runner/1.0"]
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    upstream: Flux2KleinUpstream
    files: tuple[LocalImageCandidateFile, ...] = Field(min_length=1, max_length=256)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def exact_identity_and_file_set(self) -> Self:
        paths = tuple(value.relative_path for value in self.files)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("candidate model files must be uniquely sorted")
        model_identity = content_sha256(self.upstream.repo_id).removeprefix("sha256:")[:32]
        revision_identity = content_sha256(
            {
                "upstream": self.upstream.model_dump(mode="json"),
                "files": [value.model_dump(mode="json") for value in self.files],
            }
        ).removeprefix("sha256:")[:32]
        if self.model_id != f"imgmodel_{model_identity}":
            raise ValueError("candidate model ID mismatch")
        if self.model_revision_id != f"imgmodelrev_{revision_identity}":
            raise ValueError("candidate model revision ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("candidate model manifest hash mismatch")
        return self


class Flux2ReferenceProbeCase(FrozenModel):
    case_id: str = Field(pattern=r"^imgflux2case_[0-9a-f]{32}$")
    subject_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    source_crop: ImageEvaluationArtifactMember
    visual_reference: VisualReferencePngArtifactPointer
    conditioning: LocalImageReferenceConditioningOutput
    simplification_metrics: LocalImageReferenceSimplificationMetrics
    simplifier_runtime: LocalImageReferenceSimplifierRuntime
    prompt_en: str = Field(min_length=20, max_length=1200, pattern=r"^[ -~]+$")
    prompt_sha256: Sha256
    seed: int = Field(ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def exact_case_identity(self) -> Self:
        if (
            self.source_crop.schema_ref
            != "eom://schemas/image-provider/"
            "local-image-science-corpus-visual-pilot-candidate-image/1.0"
            or self.source_crop.media_type != "image/png"
            or not self.source_crop.member_path.startswith("crops/imgsciviscandidate_")
            or not self.source_crop.member_path.endswith(".png")
        ):
            raise ValueError("FLUX.2 source crop pointer is incompatible")
        if self.prompt_sha256 != text_sha256(self.prompt_en):
            raise ValueError("FLUX.2 probe prompt hash mismatch")
        identity = content_sha256(self.model_dump(mode="json", exclude={"case_id"})).removeprefix(
            "sha256:"
        )[:32]
        if self.case_id != f"imgflux2case_{identity}":
            raise ValueError("FLUX.2 probe case ID mismatch")
        return self


class LocalImageFlux2ReferenceProbePlan(FrozenModel):
    schema_version: Literal["local-image-flux2-reference-probe-plan/1.0"]
    plan_id: str = Field(pattern=r"^imgflux2probe_[0-9a-f]{32}$")
    candidate_model_manifest: ImageEvaluationArtifactMember
    candidate_model_manifest_sha256: Sha256
    activation_policy: Literal["FORBIDDEN"]
    generation_width_px: Literal[800]
    generation_height_px: Literal[512]
    delivery_width_px: Literal[800]
    delivery_height_px: Literal[500]
    inference_steps: Literal[50]
    guidance_scale_milli: Literal[4000]
    dtype: Literal["bfloat16"]
    cpu_offload: Literal[True]
    simplification: LocalImageReferenceSimplification
    cases: tuple[Flux2ReferenceProbeCase, ...] = Field(min_length=3, max_length=12)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def exact_plan(self) -> Self:
        pointer = self.candidate_model_manifest
        if (
            pointer.schema_ref != MODEL_CANDIDATE_SCHEMA_REF
            or pointer.media_type != "application/json"
            or self.candidate_model_manifest_sha256 != pointer.sha256
        ):
            raise ValueError("FLUX.2 candidate manifest pointer mismatch")
        keys = tuple(value.case_id for value in self.cases)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("FLUX.2 probe cases must be uniquely sorted")
        if len({value.subject_key for value in self.cases}) != len(self.cases):
            raise ValueError("FLUX.2 probe subjects must be unique")
        identity = content_sha256(
            self.model_dump(
                mode="json",
                exclude={"plan_id", "created_at", "created_by", "plan_sha256"},
            )
        ).removeprefix("sha256:")[:32]
        if self.plan_id != f"imgflux2probe_{identity}":
            raise ValueError("FLUX.2 probe plan ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("FLUX.2 probe plan hash mismatch")
        return self


class Flux2ReferenceProbeInput(FrozenModel):
    case_id: str = Field(pattern=r"^imgflux2case_[0-9a-f]{32}$")
    relative_path: str = Field(pattern=r"^inputs/references/imgflux2case_[0-9a-f]{32}\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)
    conditioning_relative_path: str = Field(
        pattern=r"^inputs/references/imgflux2case_[0-9a-f]{32}-conditioning\.png$"
    )
    conditioning_sha256: Sha256
    conditioning_size_bytes: int = Field(ge=64, le=8 * 1024 * 1024)

    @model_validator(mode="after")
    def path_matches_case(self) -> Self:
        if self.relative_path != f"inputs/references/{self.case_id}.png":
            raise ValueError("FLUX.2 staged input path mismatch")
        if self.conditioning_relative_path != f"inputs/references/{self.case_id}-conditioning.png":
            raise ValueError("FLUX.2 staged conditioning path mismatch")
        return self


class LocalImageFlux2ReferenceProbeCommand(FrozenModel):
    schema_version: Literal["local-image-flux2-reference-probe-command/1.0"]
    run_id: str = Field(pattern=r"^imgflux2proberun_[0-9a-f]{32}$")
    plan: ImageEvaluationArtifactMember
    plan_sha256: Sha256
    staged_plan_path: Literal["inputs/probe-plan.json"]
    staged_model_manifest_path: Literal["inputs/model-manifest.json"]
    model_root: Literal["/opt/eom-evaluation-models/flux2-klein-base-4b"]
    inputs: tuple[Flux2ReferenceProbeInput, ...] = Field(min_length=3, max_length=12)
    output_directory: Literal["outputs"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    timeout_seconds: int = Field(ge=600, le=7200)
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if (
            self.plan.schema_ref != FLUX2_PROBE_PLAN_SCHEMA_REF
            or self.plan.media_type != "application/json"
            or self.plan_sha256 != self.plan.sha256
        ):
            raise ValueError("FLUX.2 probe plan pointer mismatch")
        keys = tuple(value.case_id for value in self.inputs)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("FLUX.2 probe inputs must be uniquely sorted")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        ).removeprefix("sha256:")[:32]
        if self.run_id != f"imgflux2proberun_{identity}":
            raise ValueError("FLUX.2 probe run ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("FLUX.2 probe command hash mismatch")
        return self


class Flux2ReferenceProbeOutput(FrozenModel):
    case_id: str = Field(pattern=r"^imgflux2case_[0-9a-f]{32}$")
    kind: Literal["CANDIDATE", "CONDITIONING"]
    relative_path: str = Field(
        pattern=r"^outputs/imgflux2case_[0-9a-f]{32}-(candidate|conditioning)\.png$"
    )
    media_type: Literal["image/png"]
    size_bytes: int = Field(ge=1, le=64 * 1024 * 1024)
    sha256: Sha256
    width_px: Literal[800]
    height_px: Literal[500, 504]

    @model_validator(mode="after")
    def dimensions_and_path_match_kind(self) -> Self:
        expected_kind = self.kind.lower()
        if self.relative_path != f"outputs/{self.case_id}-{expected_kind}.png":
            raise ValueError("FLUX.2 output path mismatch")
        expected_height = 500 if self.kind == "CANDIDATE" else 504
        if self.height_px != expected_height:
            raise ValueError("FLUX.2 output dimensions mismatch")
        return self


class Flux2ReferenceProbeMeasurement(FrozenModel):
    case_id: str = Field(pattern=r"^imgflux2case_[0-9a-f]{32}$")
    elapsed_milliseconds: int = Field(ge=1, le=7_200_000)
    peak_gpu_memory_bytes: int = Field(ge=1, le=32 * 1024 * 1024 * 1024)


class Flux2ReferenceProbeRuntime(FrozenModel):
    python_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    torch_version: str = Field(min_length=1, max_length=64)
    diffusers_version: str = Field(min_length=1, max_length=64)
    transformers_version: str = Field(min_length=1, max_length=64)
    cuda_version: str = Field(min_length=1, max_length=32)
    gpu_name: Literal["NVIDIA GeForce RTX 5080"]
    compute_capability: Literal["12.0"]


Flux2ProbeErrorCode = Literal[
    "FLUX2_PROBE_EXEC_FAILED",
    "FLUX2_PROBE_GPU_UNAVAILABLE",
    "FLUX2_PROBE_INPUT_HASH_MISMATCH",
    "FLUX2_PROBE_INPUT_INVALID",
    "FLUX2_PROBE_MODEL_INVALID",
    "FLUX2_PROBE_OOM",
    "FLUX2_PROBE_OUTPUT_INVALID",
]


class LocalImageFlux2ReferenceProbeResult(FrozenModel):
    schema_version: Literal["local-image-flux2-reference-probe-result/1.0"]
    run_id: str = Field(pattern=r"^imgflux2proberun_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^imgflux2probe_[0-9a-f]{32}$")
    plan_sha256: Sha256
    command_sha256: Sha256
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    activation_policy: Literal["FORBIDDEN"]
    status: Literal["FAILED", "SUCCEEDED"]
    error_code: Flux2ProbeErrorCode | None
    outputs: tuple[Flux2ReferenceProbeOutput, ...] = Field(max_length=24)
    measurements: tuple[Flux2ReferenceProbeMeasurement, ...] = Field(max_length=12)
    runtime: Flux2ReferenceProbeRuntime | None
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("FLUX.2 probe completion precedes start")
        if self.status == "FAILED":
            if (
                self.error_code is None
                or self.outputs
                or self.measurements
                or self.runtime is not None
            ):
                raise ValueError("failed FLUX.2 probe result must be empty and coded")
        else:
            if self.error_code is not None or self.runtime is None:
                raise ValueError("successful FLUX.2 probe result is incomplete")
            output_keys = tuple((value.case_id, value.kind) for value in self.outputs)
            if output_keys != tuple(sorted(set(output_keys))):
                raise ValueError("FLUX.2 probe outputs must be uniquely sorted")
            output_cases: dict[str, set[str]] = {}
            for value in self.outputs:
                output_cases.setdefault(value.case_id, set()).add(value.kind)
            measurement_ids = tuple(value.case_id for value in self.measurements)
            if measurement_ids != tuple(sorted(set(measurement_ids))):
                raise ValueError("FLUX.2 probe measurements must be uniquely sorted")
            if set(measurement_ids) != set(output_cases) or any(
                kinds != {"CANDIDATE", "CONDITIONING"} for kinds in output_cases.values()
            ):
                raise ValueError("FLUX.2 successful result lacks exact case outputs")
            if not 3 <= len(measurement_ids) <= 12:
                raise ValueError("FLUX.2 successful result case count is invalid")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("FLUX.2 probe result hash mismatch")
        return self


def validate_flux2_probe_command(
    manifest: LocalImageModelCandidateManifest,
    plan: LocalImageFlux2ReferenceProbePlan,
    command: LocalImageFlux2ReferenceProbeCommand,
) -> None:
    """Bind the staged manifest, plan, and command in O(C)."""

    if plan.candidate_model_manifest.sha256 != content_sha256(manifest.model_dump(mode="json")):
        raise ValueError("FLUX.2 plan does not bind the candidate manifest bytes")
    if command.plan.sha256 != content_sha256(plan.model_dump(mode="json")):
        raise ValueError("FLUX.2 command does not bind the probe plan bytes")
    cases = {value.case_id: value for value in plan.cases}
    inputs = {value.case_id: value for value in command.inputs}
    if set(cases) != set(inputs):
        raise ValueError("FLUX.2 command input coverage mismatch")
    for case_id, case in cases.items():
        staged = inputs[case_id]
        if (
            staged.sha256 != case.visual_reference.sha256
            or staged.size_bytes != case.visual_reference.size_bytes
            or staged.conditioning_sha256 != case.conditioning.sha256
            or staged.conditioning_size_bytes != case.conditioning.size_bytes
        ):
            raise ValueError("FLUX.2 command input pointer mismatch")


def validate_flux2_probe_result(
    plan: LocalImageFlux2ReferenceProbePlan,
    command: LocalImageFlux2ReferenceProbeCommand,
    manifest: LocalImageModelCandidateManifest,
    result: LocalImageFlux2ReferenceProbeResult,
) -> None:
    """Bind a result to exact execution inputs without reinterpreting quality."""

    if (
        result.run_id != command.run_id
        or result.plan_id != plan.plan_id
        or result.plan_sha256 != plan.plan_sha256
        or result.command_sha256 != command.command_sha256
        or result.model_revision_id != manifest.model_revision_id
    ):
        raise ValueError("FLUX.2 result execution binding mismatch")
    if result.status == "SUCCEEDED" and {value.case_id for value in result.measurements} != {
        value.case_id for value in plan.cases
    }:
        raise ValueError("FLUX.2 result plan coverage mismatch")
    if result.status == "SUCCEEDED":
        conditioning_by_case = {
            value.case_id: value for value in result.outputs if value.kind == "CONDITIONING"
        }
        for case in plan.cases:
            output = conditioning_by_case[case.case_id]
            if (
                output.sha256 != case.conditioning.sha256
                or output.size_bytes != case.conditioning.size_bytes
            ):
                raise ValueError("FLUX.2 result conditioning binding mismatch")
