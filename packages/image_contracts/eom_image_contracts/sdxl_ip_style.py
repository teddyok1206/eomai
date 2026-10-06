"""Pinned evaluation-only style component, independent of morphology and base weights."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import FrozenModel, ModelFile, Sha256, content_sha256

SDXL_IP_STYLE_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-ip-style-model-manifest/1.0"
)
SDXL_IP_STYLE_FILES = MappingProxyType(
    {
        file.relative_path: file
        for file in (
            ModelFile(
                relative_path="LICENSE.code.txt",
                size_bytes=11357,
                sha256="sha256:c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
            ),
            ModelFile(
                relative_path="NOTICE.encoder.md",
                size_bytes=8209,
                sha256="sha256:14db420f00ddf78a07194dc4cdc57977d979e0f2c34994137679046defdf6577",
            ),
            ModelFile(
                relative_path="README.md",
                size_bytes=3091,
                sha256="sha256:ba3a50dc2093d0eb075890e9af7409382874669d83939e64323246d0c4403cf8",
            ),
            ModelFile(
                relative_path="models/image_encoder/config.json",
                size_bytes=560,
                sha256="sha256:625d37b31afbf2f0792a87846b3654ee23f20568409e35b78a1f795b04e1a7a1",
            ),
            ModelFile(
                relative_path="models/image_encoder/model.safetensors",
                size_bytes=2528373448,
                sha256="sha256:6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030",
            ),
            ModelFile(
                relative_path="sdxl_models/ip-adapter_sdxl_vit-h.safetensors",
                size_bytes=698391064,
                sha256="sha256:ebf05d918348aec7abb02a5e9ecef77e0aaea6914a5c4ea13f50d45eb1681831",
            ),
        )
    }
)


class SdxlIpStyleLicense(FrozenModel):
    hub_identifier: Literal["apache-2.0"] = "apache-2.0"
    basis: Literal["HUB_CARD_AND_DECLARED_ENCODER_ORIGIN"] = "HUB_CARD_AND_DECLARED_ENCODER_ORIGIN"
    hub_own_license_file: Literal[False] = False
    code_repo: Literal["tencent-ailab/IP-Adapter"] = "tencent-ailab/IP-Adapter"
    code_revision: Literal["62e4af9d0c1ac7d5f8dd386a0ccf2211346af1a2"] = (
        "62e4af9d0c1ac7d5f8dd386a0ccf2211346af1a2"
    )
    code_license_id: Literal["Apache-2.0"] = "Apache-2.0"
    encoder_origin_repo: Literal["laion/CLIP-ViT-H-14-laion2B-s32B-b79K"] = (
        "laion/CLIP-ViT-H-14-laion2B-s32B-b79K"
    )
    encoder_origin_revision: Literal["1c2b8495b28150b8a4922ee1c8edee224c284c0c"] = (
        "1c2b8495b28150b8a4922ee1c8edee224c284c0c"
    )
    encoder_origin_license_id: Literal["MIT"] = "MIT"
    repack_equivalence_verified: Literal[False] = False


class SdxlIpStylePreprocessing(FrozenModel):
    policy: Literal["WHOLE_REFERENCE_WHITE_FIT_RGB_224/1.0"] = (
        "WHOLE_REFERENCE_WHITE_FIT_RGB_224/1.0"
    )
    width_px: Literal[224] = 224
    height_px: Literal[224] = 224
    resize_interpolation: Literal["BICUBIC"] = "BICUBIC"
    pillow_version: Literal["11.3.0"] = "11.3.0"
    transformers_version: Literal["4.56.2"] = "4.56.2"
    processor_resize: Literal[False] = False
    processor_center_crop: Literal[False] = False
    image_mean: tuple[
        Annotated[float, Field(ge=0.48145466, le=0.48145466, strict=True)],
        Annotated[float, Field(ge=0.4578275, le=0.4578275, strict=True)],
        Annotated[float, Field(ge=0.40821073, le=0.40821073, strict=True)],
    ] = (
        0.48145466,
        0.4578275,
        0.40821073,
    )
    image_std: tuple[
        Annotated[float, Field(ge=0.26862954, le=0.26862954, strict=True)],
        Annotated[float, Field(ge=0.26130258, le=0.26130258, strict=True)],
        Annotated[float, Field(ge=0.27577711, le=0.27577711, strict=True)],
    ] = (
        0.26862954,
        0.26130258,
        0.27577711,
    )
    rescale_factor: float = Field(
        default=0.00392156862745098,
        ge=0.00392156862745098,
        le=0.00392156862745098,
        strict=True,
    )


class SdxlIpStyleModelPointer(FrozenModel):
    model_id: str = Field(pattern=r"^imgmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    provider_family: Literal["diffusers-sdxl-ip-adapter-global-vit-h"] = (
        "diffusers-sdxl-ip-adapter-global-vit-h"
    )
    runtime_contract_version: Literal["eom-local-image-sdxl-ip-style-runner/1.0"] = (
        "eom-local-image-sdxl-ip-style-runner/1.0"
    )


class LocalImageSdxlIpStyleModelManifest(SdxlIpStyleModelPointer):
    schema_version: Literal["local-image-sdxl-ip-style-model-manifest/1.0"]
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    upstream_repo: Literal["h94/IP-Adapter"]
    upstream_revision: Literal["018e402774aeeddd60609b4ecdb7e298259dc729"]
    supported_base_repo: Literal["stabilityai/stable-diffusion-xl-base-1.0"] = (
        "stabilityai/stable-diffusion-xl-base-1.0"
    )
    license: SdxlIpStyleLicense
    preprocessing: SdxlIpStylePreprocessing
    files: tuple[ModelFile, ...] = Field(min_length=6, max_length=6)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("SDXL_IP_STYLE_TIMESTAMP_NOT_UTC")
        return value

    @model_validator(mode="after")
    def exact_identity_and_closure(self) -> Self:
        if self.files != tuple(SDXL_IP_STYLE_FILES[name] for name in sorted(SDXL_IP_STYLE_FILES)):
            raise ValueError("SDXL_IP_STYLE_FILE_CLOSURE_MISMATCH")
        identity = content_sha256(
            {"provider_family": self.provider_family, "upstream_repo": self.upstream_repo}
        )[7:39]
        revision = content_sha256(
            {
                "upstream_revision": self.upstream_revision,
                "license": self.license.model_dump(mode="json"),
                "preprocessing": self.preprocessing.model_dump(mode="json"),
                "files": [file.model_dump(mode="json") for file in self.files],
            }
        )[7:39]
        if self.model_id != "imgmodel_" + identity:
            raise ValueError("SDXL_IP_STYLE_LOGICAL_ID_MISMATCH")
        if self.model_revision_id != "imgmodelrev_" + revision:
            raise ValueError("SDXL_IP_STYLE_REVISION_ID_MISMATCH")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("SDXL_IP_STYLE_MANIFEST_HASH_MISMATCH")
        return self


def sdxl_ip_style_model_pointer(
    manifest: LocalImageSdxlIpStyleModelManifest,
) -> SdxlIpStyleModelPointer:
    return SdxlIpStyleModelPointer.model_validate(
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


def validate_sdxl_ip_style_model_pointer(
    pointer: SdxlIpStyleModelPointer,
    manifest: LocalImageSdxlIpStyleModelManifest,
) -> None:
    if pointer != sdxl_ip_style_model_pointer(manifest):
        raise ValueError("SDXL_IP_STYLE_POINTER_MISMATCH")
