"""Closed local owner commands; no arbitrary path, actor or persistence authority."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract


class MaterialOfficeCommand(FrozenModel):
    schema_version: Literal["material-learning-office-command/1.0"] = (
        "material-learning-office-command/1.0"
    )
    operation: Literal["CREATE", "CONVERT", "READ"]
    instance_id: str = Field(pattern=r"^officeconv_[0-9a-f]{32}$")
    source_format: Literal["HWP", "HWPX"]
    source_sha256: Sha256 | None

    @model_validator(mode="after")
    def closed_operation(self) -> Self:
        validate_contract("material-learning-office-command-v1", self.model_dump(mode="json"))
        if (self.operation == "CREATE") != (self.source_sha256 is None):
            raise ValueError("MATERIAL_OFFICE_COMMAND_INVALID")
        return self


class MaterialOfficeReply(FrozenModel):
    schema_version: Literal["material-learning-office-reply/1.0"] = (
        "material-learning-office-reply/1.0"
    )
    operation: Literal["CREATE", "CONVERT", "READ"]
    instance_id: str = Field(pattern=r"^officeconv_[0-9a-f]{32}$")
    source_sha256: Sha256 | None
    conversion: OfficeDocumentReviewConversionIdentity | None

    @model_validator(mode="after")
    def closed_operation(self) -> Self:
        validate_contract("material-learning-office-reply-v1", self.model_dump(mode="json"))
        empty = self.source_sha256 is None and self.conversion is None
        if (self.operation == "CREATE") != empty or (
            self.operation != "CREATE" and (self.conversion is None or self.source_sha256 is None)
        ):
            raise ValueError("MATERIAL_OFFICE_REPLY_INVALID")
        return self
