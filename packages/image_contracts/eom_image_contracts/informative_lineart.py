"""Pinned, evaluation-only learned extractor identity; no runtime or acquisition I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import FrozenModel, ModelFile, Sha256, content_sha256

INFORMATIVE_LINEART_MANIFEST_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-informative-lineart-manifest/1.0"
)
_LOCAL_FILES = frozenset({"LICENSE", "config.json", "model.safetensors", "upstream.json"})


class InformativeLineartUpstream(FrozenModel):
    """Author's fine/style-1 distribution, not the ambiguously licensed mirror."""

    repo_id: Literal["carolineec/informativedrawings"]
    repo_type: Literal["space"]
    revision: Literal["bd4b4299be505803e036203a39c02024b4cfee11"]
    source_url: Literal["https://huggingface.co/spaces/carolineec/informativedrawings"]
    license_id: Literal["MIT"]
    license_record_sha256: Literal[
        "sha256:7cb79f3b0f9354c7f47a1ab56b09c0e3bd6c8d96243555be5e28ea79d6e6c8a7"
    ]
    architecture_source_sha256: Literal[
        "sha256:4e989aff7a9f4491e9bf463dff0b7c35f84b52b34a0bf4ca918b525fa7d593d0"
    ]
    weight_filename: Literal["model.pth"]
    weight_bytes: Literal[17173511]
    weight_sha256: Literal[
        "sha256:c686ced2a666b4850b4bb6ccf0748031c3eda9f822de73a34b8979970d90f0c6"
    ]


class InformativeLineartPointer(FrozenModel):
    extractor_id: str = Field(pattern=r"^imgextractor_[0-9a-f]{32}$")
    extractor_revision_id: str = Field(pattern=r"^imgextractorrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    provider_family: Literal["informative-drawings-style1"]
    runtime_contract_version: Literal["eom-informative-lineart-extractor/1.0"]


class LocalImageInformativeLineartManifest(FrozenModel):
    schema_version: Literal["local-image-informative-lineart-manifest/1.0"]
    extractor_id: str = Field(pattern=r"^imgextractor_[0-9a-f]{32}$")
    extractor_revision_id: str = Field(pattern=r"^imgextractorrev_[0-9a-f]{32}$")
    provider_family: Literal["informative-drawings-style1"]
    runtime_contract_version: Literal["eom-informative-lineart-extractor/1.0"]
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    upstream: InformativeLineartUpstream
    conversion_policy: Literal["TORCH_WEIGHTS_ONLY_CPU_TO_SAFETENSORS/1.0"]
    architecture: Literal["RGB_INSTANCE_NORM_RESNET3_SIGMOID/1.0"]
    files: tuple[ModelFile, ...] = Field(min_length=4, max_length=4)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("learned lineart manifest timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def immutable_member_identity(self) -> Self:
        by_path = {file.relative_path: file for file in self.files}
        paths = tuple(file.relative_path for file in self.files)
        if paths != tuple(sorted(_LOCAL_FILES)) or set(by_path) != _LOCAL_FILES:
            raise ValueError("learned lineart files must be the complete uniquely sorted safe set")
        for file in self.files:
            ceiling = 32 * 1024**2 if file.relative_path == "model.safetensors" else 64 * 1024
            if file.size_bytes > ceiling:
                raise ValueError("learned lineart model or metadata exceeds its byte limit")
        logical = content_sha256(
            {
                "provider_family": self.provider_family,
                "repo_id": self.upstream.repo_id,
                "weight_filename": self.upstream.weight_filename,
            }
        )[7:39]
        revision = content_sha256(
            {
                "upstream": self.upstream.model_dump(mode="json"),
                "conversion_policy": self.conversion_policy,
                "architecture": self.architecture,
                "runtime_contract_version": self.runtime_contract_version,
                "files": [file.model_dump(mode="json") for file in self.files],
            }
        )[7:39]
        if self.extractor_id != "imgextractor_" + logical:
            raise ValueError("learned lineart logical identity mismatch")
        if self.extractor_revision_id != "imgextractorrev_" + revision:
            raise ValueError("learned lineart immutable revision mismatch")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("learned lineart manifest hash mismatch")
        return self


def validate_informative_lineart_pointer(
    pointer: InformativeLineartPointer,
    manifest: LocalImageInformativeLineartManifest,
) -> None:
    """Reject a different identity/revision rather than silently resolving latest."""
    if pointer != InformativeLineartPointer(
        extractor_id=manifest.extractor_id,
        extractor_revision_id=manifest.extractor_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        provider_family=manifest.provider_family,
        runtime_contract_version=manifest.runtime_contract_version,
    ):
        raise ValueError("learned lineart pointer does not match its pinned manifest")
