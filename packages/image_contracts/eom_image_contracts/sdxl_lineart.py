"""Frozen SDXL/T2I-Adapter candidate dependencies, separate from released SSD-1B."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import FrozenModel, ModelFile, Sha256, content_sha256

SDXL_LINEART_STACK_SCHEMA_REF = "eom://schemas/image-provider/local-image-sdxl-lineart-stack/1.0"
SdxlLineartComponentRole = Literal["BASE", "LINEART_ADAPTER", "VAE"]

_UPSTREAMS: Mapping[SdxlLineartComponentRole, tuple[str, str]] = MappingProxyType(
    {
        "BASE": ("stabilityai/stable-diffusion-xl-base-1.0", "CreativeML-Open-RAIL++-M"),
        "LINEART_ADAPTER": ("TencentARC/t2i-adapter-lineart-sdxl-1.0", "Apache-2.0"),
        "VAE": ("madebyollin/sdxl-vae-fp16-fix", "MIT"),
    }
)
_REQUIRED_FILES: Mapping[SdxlLineartComponentRole, frozenset[str]] = MappingProxyType(
    {
        "BASE": frozenset(
            {
                "model_index.json",
                "scheduler/scheduler_config.json",
                "text_encoder/config.json",
                "text_encoder/model.fp16.safetensors",
                "text_encoder_2/config.json",
                "text_encoder_2/model.fp16.safetensors",
                "unet/config.json",
                "unet/diffusion_pytorch_model.fp16.safetensors",
                "tokenizer/tokenizer_config.json",
                "tokenizer/vocab.json",
                "tokenizer/merges.txt",
                "tokenizer_2/tokenizer_config.json",
                "tokenizer_2/vocab.json",
                "tokenizer_2/merges.txt",
            }
        ),
        "LINEART_ADAPTER": frozenset({"config.json", "diffusion_pytorch_model.fp16.safetensors"}),
        "VAE": frozenset({"config.json", "diffusion_pytorch_model.safetensors"}),
    }
)


class SdxlLineartUpstream(FrozenModel):
    repo_id: Literal[
        "stabilityai/stable-diffusion-xl-base-1.0",
        "TencentARC/t2i-adapter-lineart-sdxl-1.0",
        "madebyollin/sdxl-vae-fp16-fix",
    ]
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_url: Literal[
        "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
        "https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0",
        "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix",
    ]
    license_id: Literal["CreativeML-Open-RAIL++-M", "Apache-2.0", "MIT"]


class SdxlLineartComponentManifest(FrozenModel):
    component_id: str = Field(pattern=r"^imgstackcomponent_[0-9a-f]{32}$")
    component_revision_id: str = Field(pattern=r"^imgstackcomponentrev_[0-9a-f]{32}$")
    role: SdxlLineartComponentRole
    upstream: SdxlLineartUpstream
    files: tuple[ModelFile, ...] = Field(min_length=1, max_length=64)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_dependency(self) -> Self:
        repo, license_id = _UPSTREAMS[self.role]
        if (
            self.upstream.repo_id != repo
            or self.upstream.source_url != "https://huggingface.co/" + repo
            or self.upstream.license_id != license_id
        ):
            raise ValueError("SDXL component role/upstream/license mismatch")
        paths = tuple(file.relative_path for file in self.files)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("SDXL component file paths must be uniquely sorted")
        if not _REQUIRED_FILES[self.role] <= set(paths):
            raise ValueError("SDXL component is missing required local files")
        if any(
            not path.endswith((".safetensors", ".json", ".txt", ".md")) and path != "LICENSE"
            for path in paths
        ):
            raise ValueError("SDXL component contains executable or unsafe weight files")
        logical = content_sha256({"role": self.role, "repo_id": repo})[7:39]
        revision = content_sha256(
            {
                "upstream": self.upstream.model_dump(mode="json"),
                "files": [file.model_dump(mode="json") for file in self.files],
            }
        )[7:39]
        if self.component_id != "imgstackcomponent_" + logical:
            raise ValueError("SDXL component logical identity mismatch")
        if self.component_revision_id != "imgstackcomponentrev_" + revision:
            raise ValueError("SDXL component revision identity mismatch")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("SDXL component manifest hash mismatch")
        return self


class LocalImageSdxlLineartStack(FrozenModel):
    schema_version: Literal["local-image-sdxl-lineart-stack/1.0"]
    model_id: str = Field(pattern=r"^imgmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    provider_family: Literal["diffusers-sdxl-t2i-lineart"]
    runtime_contract_version: Literal["eom-local-image-sdxl-lineart-runner/1.0"]
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    components: tuple[SdxlLineartComponentManifest, ...] = Field(min_length=3, max_length=3)
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("SDXL stack timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def exact_stack(self) -> Self:
        if tuple(component.role for component in self.components) != tuple(sorted(_UPSTREAMS)):
            raise ValueError("SDXL stack requires exactly the sorted base/adapter/VAE roles")
        identity = content_sha256(
            {"provider_family": self.provider_family, "base_repo_id": _UPSTREAMS["BASE"][0]}
        )[7:39]
        revision = content_sha256(
            {"components": [component.model_dump(mode="json") for component in self.components]}
        )[7:39]
        if self.model_id != "imgmodel_" + identity:
            raise ValueError("SDXL stack logical identity mismatch")
        if self.model_revision_id != "imgmodelrev_" + revision:
            raise ValueError("SDXL stack revision identity mismatch")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("SDXL stack manifest hash mismatch")
        return self
