"""Browser delivery views; no Artifact, NAS path or worker input is exposed."""

from typing import Literal

from pydantic import Field, model_validator

from eom_web_gui.contracts import UtcDatetime, WebModel


class CuratedHwpxSubmission(WebModel):
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CuratedHwpxView(WebModel):
    schema_version: Literal["curated-hwpx-build-view/1.0"]
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    state: Literal["REQUESTED", "RUNNING", "VALIDATING", "SUCCEEDED", "FAILED"]
    validation_state: Literal["PENDING", "PASS", "FAIL"]
    placement_count: int = Field(ge=1, le=200)
    section_count: int | None = Field(default=None, ge=1, le=10000)
    output_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    output_size_bytes: int | None = Field(default=None, ge=1, le=256 * 1024**2)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    download_available: bool

    @model_validator(mode="after")
    def verified_download(self) -> "CuratedHwpxView":
        success = self.state == "SUCCEEDED" and self.validation_state == "PASS"
        if self.download_available != success or (
            success
            and (
                self.output_sha256 is None
                or self.output_size_bytes is None
                or self.completed_at is None
            )
        ):
            raise ValueError("curated download has no validated output evidence")
        return self
