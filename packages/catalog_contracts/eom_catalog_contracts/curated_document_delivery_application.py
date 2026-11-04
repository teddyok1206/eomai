"""Pinned delivery authorization and metadata materialization at the Catalog boundary."""

from typing import Literal, Self

from eom_hwpx_contracts.curated_build import CuratedHwpxBuildInput
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.models import ContentTeamHandoffSnapshot
from pydantic import Field, model_validator

from eom_catalog_contracts.curated_document_assembly import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.models import FrozenModel, UtcDatetime


class CuratedDocumentDeliveryQueryV1(FrozenModel):
    operation: Literal["RESOLVE_CURATED_DOCUMENT_DELIVERY"] = "RESOLVE_CURATED_DOCUMENT_DELIVERY"
    purpose: Literal["AUTHORIZE_READ", "AUTHORIZE_BUILD", "PIN_INPUTS"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    authentication_time: UtcDatetime
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    handoff: ContentTeamHandoffSnapshot | None = None
    converter: CuratedHwpConverterSnapshot | None = None

    @model_validator(mode="after")
    def renderer_pins_only_at_admission(self) -> Self:
        if self.purpose == "PIN_INPUTS":
            if self.handoff is None or self.converter is None:
                raise ValueError("input admission requires trusted renderer release pins")
        elif self.handoff is not None or self.converter is not None:
            raise ValueError("reauthorization must not resolve a new renderer release")
        return self


class CuratedDocumentDeliveryResponseV1(FrozenModel):
    operation: Literal["RESOLVE_CURATED_DOCUMENT_DELIVERY"] = "RESOLVE_CURATED_DOCUMENT_DELIVERY"
    status: Literal["OK", "ERROR"]
    manifest: CuratedDocumentAssemblyManifestV1 | None = None
    inputs: CuratedHwpxBuildInput | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        if self.status == "ERROR":
            if not self.error_code or self.manifest is not None or self.inputs is not None:
                raise ValueError("delivery error must not contain authorized metadata")
        elif self.error_code is not None or self.manifest is None:
            raise ValueError("authorized delivery requires its exact assembly manifest")
        if (
            self.inputs is not None
            and self.manifest is not None
            and (
                self.inputs.assembly_id != self.manifest.assembly_id
                or self.inputs.assembly_revision_id != self.manifest.assembly_revision_id
                or self.inputs.assembly_manifest_sha256 != self.manifest.manifest_sha256
            )
        ):
            raise ValueError("delivery input pins differ from the authorized assembly")
        return self
