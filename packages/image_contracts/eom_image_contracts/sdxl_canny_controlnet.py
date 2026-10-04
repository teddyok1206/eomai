"""Standalone pinned spatial controller; never duplicates the existing SDXL base/VAE."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import FrozenModel, ModelFile, Sha256, content_sha256

SDXL_CANNY_CONTROLLER_REPO = "diffusers/controlnet-canny-sdxl-1.0"
SDXL_CANNY_CONTROLLER_REVISION = "eb115a19a10d14909256db740ed109532ab1483c"
SDXL_CANNY_CONTROLLER_FILES = MappingProxyType(
    {
        "LICENSE.standard.md": ModelFile(
            relative_path="LICENSE.standard.md",
            size_bytes=14109,
            sha256="sha256:19b6998b569b53ac1fc2158a8a3202c8699a9a4605b47075715d9c96be7fb6d0",
        ),
        "README.md": ModelFile(
            relative_path="README.md",
            size_bytes=3580,
            sha256="sha256:78be0e56618abb9aef9a880ce74a4ba7219c97a35d9f27a2763b23475004264c",
        ),
        "config.json": ModelFile(
            relative_path="config.json",
            size_bytes=1309,
            sha256="sha256:81f9bfed178f666c332892cd568a78ed8918fe08aaee994d05428a75ab44f2ca",
        ),
        "diffusion_pytorch_model.fp16.safetensors": ModelFile(
            relative_path="diffusion_pytorch_model.fp16.safetensors",
            size_bytes=2502139136,
            sha256="sha256:b2e7d3921058a442cc80430d1ec8847f42599c705e2451c95e77cf4dcf8d6c25",
        ),
        "hub-license-identifiers.md": ModelFile(
            relative_path="hub-license-identifiers.md",
            size_bytes=11962,
            sha256="sha256:e4bd957c932364110c4f5a41c547f0541a3d08d9f76b63c223039ecb956dc444",
        ),
    }
)


class SdxlCannyControllerLicense(FrozenModel):
    license_id: Literal["CreativeML-Open-RAIL++-M"] = "CreativeML-Open-RAIL++-M"
    declared_identifier: Literal["openrail++"] = "openrail++"
    basis: Literal["HUB_DECLARATION_WITH_HUB_LINKED_STANDARD_TEXT"] = (
        "HUB_DECLARATION_WITH_HUB_LINKED_STANDARD_TEXT"
    )
    controller_own_license_file: Literal[False] = False
    card_revision: Literal["eb115a19a10d14909256db740ed109532ab1483c"] = (
        "eb115a19a10d14909256db740ed109532ab1483c"
    )
    identifier_mapping_revision: Literal["fd6cf1f56e1514af08c5a7262d9f79b3becb810d"] = (
        "fd6cf1f56e1514af08c5a7262d9f79b3becb810d"
    )
    standard_text_repo: Literal["stabilityai/stable-diffusion-xl-base-1.0"] = (
        "stabilityai/stable-diffusion-xl-base-1.0"
    )
    standard_text_revision: Literal["462165984030d82259a11f4367a4eed129e94a7b"] = (
        "462165984030d82259a11f4367a4eed129e94a7b"
    )
    standard_text_member: Literal["LICENSE.md"] = "LICENSE.md"


class SdxlCannyControllerPointer(FrozenModel):
    model_id: str = Field(pattern=r"^imgmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    provider_family: Literal["diffusers-sdxl-controlnet-canny"] = "diffusers-sdxl-controlnet-canny"
    runtime_contract_version: Literal["eom-local-image-sdxl-canny-runner/1.0"] = (
        "eom-local-image-sdxl-canny-runner/1.0"
    )


class LocalImageSdxlCannyControllerManifest(SdxlCannyControllerPointer):
    schema_version: Literal["local-image-sdxl-canny-controller-manifest/1.0"]
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    upstream_repo: Literal["diffusers/controlnet-canny-sdxl-1.0"]
    upstream_revision: Literal["eb115a19a10d14909256db740ed109532ab1483c"]
    source_url: Literal["https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0"]
    supported_base_repo: Literal["stabilityai/stable-diffusion-xl-base-1.0"]
    license: SdxlCannyControllerLicense
    files: tuple[ModelFile, ...] = Field(min_length=5, max_length=5)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("controller timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def exact_controller(self) -> Self:
        if self.files != tuple(
            SDXL_CANNY_CONTROLLER_FILES[name] for name in sorted(SDXL_CANNY_CONTROLLER_FILES)
        ):
            raise ValueError("controller files are not the exact pinned whitelist")
        identity = content_sha256(
            {"provider_family": self.provider_family, "upstream_repo": self.upstream_repo}
        )[7:39]
        revision = content_sha256(
            {
                "upstream_revision": self.upstream_revision,
                "license": self.license.model_dump(mode="json"),
                "files": [file.model_dump(mode="json") for file in self.files],
            }
        )[7:39]
        if self.model_id != "imgmodel_" + identity:
            raise ValueError("controller logical identity mismatch")
        if self.model_revision_id != "imgmodelrev_" + revision:
            raise ValueError("controller revision identity mismatch")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("controller manifest hash mismatch")
        return self


def sdxl_canny_controller_pointer(
    manifest: LocalImageSdxlCannyControllerManifest,
) -> SdxlCannyControllerPointer:
    return SdxlCannyControllerPointer.model_validate(
        manifest.model_dump(
            mode="json",
            include={
                "model_id",
                "model_revision_id",
                "manifest_sha256",
                "provider_family",
                "runtime_contract_version",
            },
        )
    )
