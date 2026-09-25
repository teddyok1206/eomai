"""Strict value contracts for the isolated local image provider."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def content_json_bytes(value: object) -> bytes:
    """Serialize one image-contract value with the hash contract's canonical encoding."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_sha256(value: object) -> str:
    payload = content_json_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def text_sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _safe_prompt(value: str) -> str:
    if value != value.strip() or value != unicodedata.normalize("NFC", value):
        raise ValueError("prompt must be trimmed NFC text")
    for character in value:
        if character in {"\n", "\t"}:
            continue
        if unicodedata.category(character).startswith("C"):
            raise ValueError("prompt contains a control character")
    return value


class ModelFile(FrozenModel):
    relative_path: str = Field(
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    size_bytes: int = Field(ge=1, le=8 * 1024 * 1024 * 1024)
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
            raise ValueError("model file path is unsafe")
        return value


class UpstreamModel(FrozenModel):
    repo_id: Literal["segmind/SSD-1B"] = "segmind/SSD-1B"
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_url: Literal["https://huggingface.co/segmind/SSD-1B"] = (
        "https://huggingface.co/segmind/SSD-1B"
    )
    license_id: Literal["Apache-2.0"] = "Apache-2.0"


class LocalImageModelManifest(FrozenModel):
    schema_version: Literal["local-image-model-manifest/1.0"] = "local-image-model-manifest/1.0"
    model_id: str = Field(pattern=r"^imgmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    provider_family: Literal["diffusers-ssd-1b"] = "diffusers-ssd-1b"
    runtime_contract_version: Literal["eom-local-image-provider/1.0"] = (
        "eom-local-image-provider/1.0"
    )
    state: Literal["APPROVED"] = "APPROVED"
    upstream: UpstreamModel
    files: tuple[ModelFile, ...] = Field(min_length=1, max_length=64)
    created_at: datetime
    approved_at: datetime
    approved_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    manifest_sha256: Sha256

    @field_validator("created_at", "approved_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_file_set_and_hash(self) -> LocalImageModelManifest:
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("model files must be uniquely sorted by relative path")
        if self.approved_at < self.created_at:
            raise ValueError("model approval precedes creation")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("model manifest hash mismatch")
        return self


class LocalImageModelPointer(FrozenModel):
    model_id: str = Field(pattern=r"^imgmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    provider_family: Literal["diffusers-ssd-1b"] = "diffusers-ssd-1b"
    runtime_contract_version: Literal["eom-local-image-provider/1.0"] = (
        "eom-local-image-provider/1.0"
    )


class SamplerContract(FrozenModel):
    contract: Literal["euler-discrete/ssd-1b-v1"] = "euler-discrete/ssd-1b-v1"
    inference_steps: int = Field(ge=1, le=50)
    guidance_scale: float = Field(ge=0, le=20)
    dtype: Literal["float16"] = "float16"


class LocalImageProviderBinding(FrozenModel):
    schema_version: Literal["local-image-provider-binding/1.0"] = "local-image-provider-binding/1.0"
    state: Literal["ENABLED"] = "ENABLED"
    route_contract: Literal["eom-local-generative-background/1.0"] = (
        "eom-local-generative-background/1.0"
    )
    model: LocalImageModelPointer
    sampler: SamplerContract
    timeout_seconds: int = Field(ge=30, le=900)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def binding_hash_matches(self) -> LocalImageProviderBinding:
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("local image provider binding hash mismatch")
        return self


class GenerationCanvas(FrozenModel):
    width_px: Literal[800] = 800
    height_px: Literal[504] = 504


class DeliveryCanvas(FrozenModel):
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500


class LocalImageGenerationRequest(FrozenModel):
    schema_version: Literal["local-image-generation-request/1.0"] = (
        "local-image-generation-request/1.0"
    )
    request_id: str = Field(pattern=r"^imgreq_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]+$")
    model: LocalImageModelPointer
    prompt: str = Field(min_length=1, max_length=4000)
    prompt_sha256: Sha256
    negative_prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    negative_prompt_sha256: Sha256 | None = None
    seed: int = Field(ge=0, le=2**32 - 1)
    sampler: SamplerContract
    generation_canvas: GenerationCanvas = Field(default_factory=GenerationCanvas)
    delivery_canvas: DeliveryCanvas = Field(default_factory=DeliveryCanvas)
    output_member: Literal["generated-background.png"] = "generated-background.png"
    timeout_seconds: int = Field(ge=30, le=900)
    request_sha256: Sha256

    @field_validator("prompt", "negative_prompt")
    @classmethod
    def safe_prompts(cls, value: str | None) -> str | None:
        return None if value is None else _safe_prompt(value)

    @model_validator(mode="after")
    def hashes_match_input(self) -> LocalImageGenerationRequest:
        if self.prompt_sha256 != text_sha256(self.prompt):
            raise ValueError("prompt hash mismatch")
        expected_negative = (
            None if self.negative_prompt is None else text_sha256(self.negative_prompt)
        )
        if self.negative_prompt_sha256 != expected_negative:
            raise ValueError("negative prompt hash mismatch")
        expected_request = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected_request:
            raise ValueError("local image request hash mismatch")
        return self


class LocalImageOutput(FrozenModel):
    member_path: Literal["generated-background.png"] = "generated-background.png"
    media_type: Literal["image/png"] = "image/png"
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    mode: Literal["RGB"] = "RGB"
    size_bytes: int = Field(ge=1, le=8 * 1024 * 1024)
    sha256: Sha256


class LocalImageRuntime(FrozenModel):
    provider_version: Literal["eom-local-image-provider/1.0"] = "eom-local-image-provider/1.0"
    python_version: str = Field(min_length=1, max_length=64)
    torch_version: str = Field(min_length=1, max_length=64)
    diffusers_version: str = Field(min_length=1, max_length=64)
    transformers_version: str = Field(min_length=1, max_length=64)
    cuda_version: str = Field(min_length=1, max_length=64)
    gpu_name: str = Field(min_length=1, max_length=128)
    compute_capability: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    peak_gpu_memory_bytes: int = Field(ge=1)


class LocalImageGenerationReceipt(FrozenModel):
    schema_version: Literal["local-image-generation-receipt/1.0"] = (
        "local-image-generation-receipt/1.0"
    )
    request_id: str = Field(pattern=r"^imgreq_[0-9a-f]{32}$")
    request_sha256: Sha256
    model: LocalImageModelPointer
    prompt_sha256: Sha256
    negative_prompt_sha256: Sha256 | None
    seed: int = Field(ge=0, le=2**32 - 1)
    sampler: SamplerContract
    output: LocalImageOutput
    runtime: LocalImageRuntime
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=900_000)
    receipt_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def receipt_is_consistent(self) -> LocalImageGenerationReceipt:
        if self.completed_at < self.started_at:
            raise ValueError("local image completion precedes start")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("local image receipt hash mismatch")
        return self


class LocalImageOverlayInput(FrozenModel):
    member_path: Literal["generated-overlay.png"] = "generated-overlay.png"
    media_type: Literal["image/png"] = "image/png"
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    mode: Literal["RGBA"] = "RGBA"
    size_bytes: int = Field(ge=1, le=8 * 1024 * 1024)
    sha256: Sha256


class LocalImageCompositeRequest(FrozenModel):
    schema_version: Literal["local-image-composite-request/1.0"] = (
        "local-image-composite-request/1.0"
    )
    generation: LocalImageGenerationRequest
    overlay: LocalImageOverlayInput
    final_output_member: Literal["generated-stimulus.png"] = "generated-stimulus.png"
    composite_request_sha256: Sha256

    @model_validator(mode="after")
    def composite_request_hash_matches(self) -> LocalImageCompositeRequest:
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"composite_request_sha256"})
        )
        if self.composite_request_sha256 != expected:
            raise ValueError("local image composite request hash mismatch")
        return self


class LocalImageFinalOutput(FrozenModel):
    member_path: Literal["generated-stimulus.png"] = "generated-stimulus.png"
    media_type: Literal["image/png"] = "image/png"
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    mode: Literal["RGB"] = "RGB"
    size_bytes: int = Field(ge=1, le=8 * 1024 * 1024)
    sha256: Sha256


class LocalImageCompositorRuntime(FrozenModel):
    contract: Literal["eom-local-image-compositor/1.0"] = "eom-local-image-compositor/1.0"
    pillow_version: str = Field(min_length=1, max_length=64)


class LocalImageCompositeReceipt(FrozenModel):
    schema_version: Literal["local-image-composite-receipt/1.0"] = (
        "local-image-composite-receipt/1.0"
    )
    composite_request_sha256: Sha256
    generation: LocalImageGenerationReceipt
    overlay: LocalImageOverlayInput
    output: LocalImageFinalOutput
    compositor: LocalImageCompositorRuntime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=900_000)
    receipt_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def composite_receipt_is_consistent(self) -> LocalImageCompositeReceipt:
        if self.completed_at < self.generation.completed_at:
            raise ValueError("composition completion precedes generation")
        if self.duration_ms < self.generation.duration_ms:
            raise ValueError("composition duration is shorter than generation")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("local image composite receipt hash mismatch")
        return self


class ImageEvaluationArtifactMember(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    sha256: Sha256

    @field_validator("member_path")
    @classmethod
    def safe_member_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
            raise ValueError("evaluation artifact member path is unsafe")
        return value


class ImageEvaluationBoundingBox(FrozenModel):
    left: int = Field(ge=0, le=9999)
    top: int = Field(ge=0, le=9999)
    right: int = Field(ge=1, le=10000)
    bottom: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def positive_area(self) -> ImageEvaluationBoundingBox:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("evaluation bounding box must have positive area")
        return self


class ImageEvaluationSourceSnapshot(FrozenModel):
    graph_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    graph_manifest_sha256: Sha256
    target_count: int = Field(ge=1, le=1_000_000)
    target_set_sha256: Sha256


ImageEvaluationVariantId = Literal[
    "ASSESSMENT_STYLE_EN",
    "CURRENT_KO",
    "ENGLISH_SUBJECT",
]


class ImageEvaluationVariant(FrozenModel):
    variant_id: ImageEvaluationVariantId
    label: str = Field(min_length=1, max_length=120)
    policy_revision: str = Field(min_length=1, max_length=160)


class ImageEvaluationVisualPattern(FrozenModel):
    pattern_id: str = Field(pattern=r"^visualpattern_[0-9a-f]{32}$")
    representation_kind: Literal["APPARATUS", "COMPOSITE", "DIAGRAM", "PHOTOGRAPH"]
    rendering_mode: Literal["MIXED", "RASTER", "VECTOR_LIKE"]
    color_mode: Literal["GRAYSCALE", "LIMITED_COLOR", "MONOCHROME"]
    background: Literal["OTHER_OBSERVED", "TRANSPARENT", "WHITE"]
    panel_layout: Literal["GRID", "HORIZONTAL", "OVERLAID", "SINGLE", "VERTICAL"]
    features: tuple[
        Literal[
            "ARROWS",
            "BOUNDARY",
            "CALLOUT",
            "DATA_POINTS",
            "GRID",
            "LABELS",
            "LEADER_LINES",
            "LEGEND",
            "MULTIPLE_PANELS",
            "NUMBERED_STEPS",
            "PATTERN_FILL",
            "SCALE",
            "SYMBOL_KEY",
            "TRAJECTORY",
        ],
        ...,
    ] = Field(max_length=24)
    pedagogical_function: Literal[
        "CLASSIFICATION",
        "COMPARISON",
        "CONTEXT",
        "PRIMARY_DATA",
        "PROCESS",
        "SPATIAL_RELATION",
    ]
    composition_summary_sha256: Sha256
    reconstruction_guidance_sha256: Sha256

    @model_validator(mode="after")
    def stable_features(self) -> ImageEvaluationVisualPattern:
        if self.features != tuple(sorted(self.features)) or len(self.features) != len(
            set(self.features)
        ):
            raise ValueError("evaluation visual features must be uniquely sorted")
        return self


class ImageEvaluationPrompt(FrozenModel):
    variant_id: ImageEvaluationVariantId
    positive_prompt: str = Field(min_length=1, max_length=4000)
    positive_prompt_sha256: Sha256
    negative_prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt_sha256: Sha256

    @field_validator("positive_prompt", "negative_prompt")
    @classmethod
    def safe_prompt_text(cls, value: str) -> str:
        return _safe_prompt(value)

    @model_validator(mode="after")
    def prompt_hashes_match(self) -> ImageEvaluationPrompt:
        if self.positive_prompt_sha256 != text_sha256(self.positive_prompt):
            raise ValueError("evaluation positive prompt hash mismatch")
        if self.negative_prompt_sha256 != text_sha256(self.negative_prompt):
            raise ValueError("evaluation negative prompt hash mismatch")
        return self


class ImageEvaluationSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsample_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    visual_pattern: ImageEvaluationVisualPattern
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    source_page_image: ImageEvaluationArtifactMember
    physical_page: int = Field(ge=1, le=100_000)
    bounding_box: ImageEvaluationBoundingBox | None
    seed: int = Field(ge=0, le=2**32 - 1)
    prompts: tuple[ImageEvaluationPrompt, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def coherent_sample(self) -> ImageEvaluationSample:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("evaluation source page image must be PNG")
        variant_ids = tuple(prompt.variant_id for prompt in self.prompts)
        if variant_ids != tuple(sorted(variant_ids)) or len(variant_ids) != len(set(variant_ids)):
            raise ValueError("evaluation prompts must be uniquely sorted by variant")
        return self


class LocalImageQualityEvaluationPlan(FrozenModel):
    schema_version: Literal["local-image-quality-evaluation-plan/1.0"] = (
        "local-image-quality-evaluation-plan/1.0"
    )
    evaluation_id: str = Field(pattern=r"^imageeval_[0-9a-f]{32}$")
    created_at: datetime
    source_snapshot: ImageEvaluationSourceSnapshot
    provider_binding: LocalImageProviderBinding
    selection_method: Literal["STRATIFIED_DETERMINISTIC_V1"] = "STRATIFIED_DETERMINISTIC_V1"
    population_pattern_count: int = Field(ge=1, le=1_000_000)
    variants: tuple[ImageEvaluationVariant, ...] = Field(min_length=2, max_length=8)
    samples: tuple[ImageEvaluationSample, ...] = Field(min_length=1, max_length=64)
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def coherent_plan(self) -> LocalImageQualityEvaluationPlan:
        variant_ids = tuple(variant.variant_id for variant in self.variants)
        if variant_ids != tuple(sorted(variant_ids)) or len(variant_ids) != len(set(variant_ids)):
            raise ValueError("evaluation variants must be uniquely sorted")
        sample_ids = tuple(sample.sample_id for sample in self.samples)
        if sample_ids != tuple(sorted(sample_ids)) or len(sample_ids) != len(set(sample_ids)):
            raise ValueError("evaluation samples must be uniquely sorted")
        for sample in self.samples:
            if tuple(prompt.variant_id for prompt in sample.prompts) != variant_ids:
                raise ValueError("evaluation sample prompt variants do not match the plan")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("local image quality evaluation plan hash mismatch")
        return self


class ImageEvaluationMetrics(FrozenModel):
    grayscale_fraction_milli: int = Field(ge=0, le=1000)
    white_background_fraction_milli: int = Field(ge=0, le=1000)
    dark_ink_fraction_milli: int = Field(ge=0, le=1000)
    edge_fraction_milli: int = Field(ge=0, le=1000)
    ink_bbox_coverage_milli: int = Field(ge=0, le=1000)
    ocr_glyph_count: int = Field(ge=0, le=10_000)


class ImageEvaluationManualReview(FrozenModel):
    semantic_fidelity: int = Field(ge=1, le=5)
    assessment_style: int = Field(ge=1, le=5)
    unwanted_text: bool
    extra_objects: bool
    cropped_subject: bool
    notes: str = Field(max_length=500)


class ImageEvaluationOutput(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsample_[0-9a-f]{32}$")
    variant_id: ImageEvaluationVariantId
    request: LocalImageGenerationRequest
    receipt: LocalImageGenerationReceipt
    metrics: ImageEvaluationMetrics
    manual_review: ImageEvaluationManualReview | None

    @model_validator(mode="after")
    def request_receipt_match(self) -> ImageEvaluationOutput:
        if (
            self.receipt.request_id != self.request.request_id
            or self.receipt.request_sha256 != self.request.request_sha256
            or self.receipt.model != self.request.model
            or self.receipt.prompt_sha256 != self.request.prompt_sha256
            or self.receipt.negative_prompt_sha256 != self.request.negative_prompt_sha256
            or self.receipt.seed != self.request.seed
            or self.receipt.sampler != self.request.sampler
        ):
            raise ValueError("evaluation generation request and receipt do not match")
        return self


class LocalImageQualityEvaluationResult(FrozenModel):
    schema_version: Literal["local-image-quality-evaluation-result/1.0"] = (
        "local-image-quality-evaluation-result/1.0"
    )
    evaluation_id: str = Field(pattern=r"^imageeval_[0-9a-f]{32}$")
    plan_sha256: Sha256
    status: Literal["AUTOMATED_COMPLETE", "MANUAL_COMPLETE", "PARTIAL", "FAILED"]
    completed_at: datetime
    outputs: tuple[ImageEvaluationOutput, ...] = Field(max_length=512)
    result_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def coherent_result(self) -> LocalImageQualityEvaluationResult:
        keys = tuple((output.sample_id, output.variant_id) for output in self.outputs)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("evaluation outputs must be uniquely sorted")
        if self.status == "MANUAL_COMPLETE" and any(
            output.manual_review is None for output in self.outputs
        ):
            raise ValueError("manual-complete evaluation requires every manual review")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("local image quality evaluation result hash mismatch")
        return self


def validate_quality_evaluation_result(
    plan: LocalImageQualityEvaluationPlan,
    result: LocalImageQualityEvaluationResult,
) -> None:
    """Cross-check one result against the exact immutable evaluation plan."""

    if result.evaluation_id != plan.evaluation_id or result.plan_sha256 != plan.plan_sha256:
        raise ValueError("evaluation result does not bind the exact plan")
    samples = {sample.sample_id: sample for sample in plan.samples}
    expected_keys = {
        (sample.sample_id, variant.variant_id)
        for sample in plan.samples
        for variant in plan.variants
    }
    actual_keys = {(output.sample_id, output.variant_id) for output in result.outputs}
    if result.status in {"AUTOMATED_COMPLETE", "MANUAL_COMPLETE"} and actual_keys != expected_keys:
        raise ValueError("complete evaluation result lacks exact sample-variant coverage")
    if not actual_keys.issubset(expected_keys):
        raise ValueError("evaluation result contains an unplanned output")
    for output in result.outputs:
        sample = samples[output.sample_id]
        prompt = next(prompt for prompt in sample.prompts if prompt.variant_id == output.variant_id)
        request = output.request
        if (
            request.model != plan.provider_binding.model
            or request.sampler != plan.provider_binding.sampler
            or request.timeout_seconds != plan.provider_binding.timeout_seconds
            or request.seed != sample.seed
            or request.prompt != prompt.positive_prompt
            or request.prompt_sha256 != prompt.positive_prompt_sha256
            or request.negative_prompt != prompt.negative_prompt
            or request.negative_prompt_sha256 != prompt.negative_prompt_sha256
        ):
            raise ValueError("evaluation output drifts from its planned generation input")
