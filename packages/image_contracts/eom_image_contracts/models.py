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
