"""Pure pinned BASE equivalence for a contour-trained, LORA-only successor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import Field, model_validator

from eom_image_contracts.models import FrozenModel, ImageEvaluationArtifactMember
from eom_image_contracts.sdxl_lora_evaluation import parse_sdxl_evaluation_metadata
from eom_image_contracts.sdxl_native_evaluation import (
    SdxlNativeEvaluationSources,
    SdxlNativeLoraEvaluationPinV4,
)
from eom_image_contracts.sdxl_native_geometry import (
    GeometryArm,
    LocalImageSdxlNativeGeometryCommandV3,
    LocalImageSdxlNativeGeometryResult,
    LocalImageSdxlNativeGeometryResultV3,
    SdxlNativeGeometryBudget,
    SdxlNativeGeometryOutput,
    validate_sdxl_native_geometry_result,
)


class GeometryBaselineReuse(FrozenModel):
    prior_command: ImageEvaluationArtifactMember
    prior_result: ImageEvaluationArtifactMember

    @model_validator(mode="after")
    def exact_prior_family(self) -> Self:
        for family, pointer in (("command", self.prior_command), ("result", self.prior_result)):
            if (
                pointer.schema_ref
                != "eom://schemas/image-provider/local-image-sdxl-lora-evaluation-"
                + family
                + "/1.5"
                or pointer.member_path != "manifests/sdxl-lora-evaluation-" + family + ".json"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("SDXL_GEOMETRY_BASELINE_POINTER_INVALID")
        return self


class ReusedGeometryBudget(SdxlNativeGeometryBudget):
    maximum_generations: int = Field(ge=2, le=4, multiple_of=2)


class LocalImageSdxlReusedGeometryCommand(LocalImageSdxlNativeGeometryCommandV3):
    schema_version: Literal["local-image-sdxl-lora-evaluation-command/1.6"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPinV4
    baseline_reuse: GeometryBaselineReuse
    budget: ReusedGeometryBudget

    def generated_arms(self) -> tuple[GeometryArm, ...]:
        return ("LORA",)

    def validate_result_lineage(self, result: LocalImageSdxlNativeGeometryResult) -> None:
        if (
            not isinstance(result, LocalImageSdxlReusedGeometryResult)
            or result.baseline_reuse != self.baseline_reuse
        ):
            raise ValueError("SDXL_NATIVE_GEOMETRY_BASELINE_REUSE_MISMATCH")

    @model_validator(mode="after")
    def bounded_cases(self) -> Self:
        ids = tuple(case.sample_id for case in self.cases)
        if ids != tuple(sorted(set(ids))) or (
            self.budget.maximum_generations != 2 * len(ids)
            or self.evaluation.adapter_strength != 1.0
        ):
            raise ValueError("SDXL_NATIVE_GEOMETRY_CASE_OR_BUDGET_INVALID")
        return self


class LocalImageSdxlReusedGeometryResult(LocalImageSdxlNativeGeometryResultV3):
    schema_version: Literal["local-image-sdxl-lora-evaluation-result/1.6"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPinV4
    baseline_reuse: GeometryBaselineReuse
    generation_calls: int = Field(ge=0, le=4)
    outputs: tuple[SdxlNativeGeometryOutput, ...] = Field(max_length=4)

    @model_validator(mode="after")
    def newly_generated_lora_only(self) -> Self:
        if any(output.arm != "LORA" for output in self.outputs):
            raise ValueError("SDXL_GEOMETRY_BASE_GENERATION_FORBIDDEN")
        return self


@dataclass(frozen=True, slots=True)
class ReusedGeometryBaseline:
    command: LocalImageSdxlNativeGeometryCommandV3
    result: LocalImageSdxlNativeGeometryResultV3

    @property
    def base_outputs(self) -> tuple[SdxlNativeGeometryOutput, ...]:
        return tuple(output for output in self.result.outputs if output.arm == "BASE")


def parse_reused_geometry_baseline(
    command: LocalImageSdxlReusedGeometryCommand,
    sources: SdxlNativeEvaluationSources,
    *,
    prior_command_payload: bytes,
    prior_result_payload: bytes,
) -> ReusedGeometryBaseline:
    """Authenticate metadata and identical BASE inputs before weights/GPU/PNG I/O.

    The old adapter's LORA is not reused; its training need not be loaded again.
    BASE equivalence follows the exact model, captions, negative policy, canvases,
    numerics and old command/result relation. Current native admission separately
    verifies all frozen training source lineage. No old pixel is restaged.
    """
    prior = parse_sdxl_evaluation_metadata(
        command.baseline_reuse.prior_command,
        prior_command_payload,
        "sdxl-lora-evaluation-command-v6",
        LocalImageSdxlNativeGeometryCommandV3,
    )
    result = parse_sdxl_evaluation_metadata(
        command.baseline_reuse.prior_result,
        prior_result_payload,
        "sdxl-lora-evaluation-result-v6",
        LocalImageSdxlNativeGeometryResultV3,
    )
    if (
        result.status != "SUCCEEDED"
        or result.completed_at > command.created_at
        or prior.evaluation.baseline_command != command.evaluation.baseline_command
        or prior.cases != command.cases
        or prior.numerics != command.numerics
        or prior.negative_prompt_sha256 != command.negative_prompt_sha256
        or prior.conditioning_policy != command.conditioning_policy
        or prior.case_relation != command.case_relation
    ):
        raise ValueError("SDXL_GEOMETRY_BASELINE_INPUT_MISMATCH")
    validate_sdxl_native_geometry_result(prior, sources, result)
    return ReusedGeometryBaseline(prior, result)
