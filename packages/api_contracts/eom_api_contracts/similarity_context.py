"""HTTP presentation of the canonical selector; do not duplicate its validation rules."""

from __future__ import annotations

from typing import Literal, Self

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import Field, ModelWrapValidatorHandler, model_validator


class SimilarityContextReadSelection(CompletedSimilarityQuerySelection):
    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except SchemaError:
            # FastAPI translates Pydantic input errors, not jsonschema exceptions.
            # Keep the canonical schema check and hide its attacker-controlled prose.
            raise ValueError("invalid exact similarity selector") from None


class SimilarityContextReadSelectionV2(FrozenModel):
    """Explicit mixed HTTP family; actual actor is still supplied only by authentication."""

    schema_version: Literal["system-rag-similarity-read-selection/2.0"]
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        try:
            return similarity_contract_document(value, "system-rag-similarity-read-v2", 4096)
        except SchemaError:
            raise ValueError("invalid exact mixed similarity selector") from None

    def exact_selection(self) -> CompletedSimilarityQuerySelection:
        return CompletedSimilarityQuerySelection.model_validate(
            self.model_dump(mode="json", exclude={"schema_version"})
        )


class SimilarityContextReadSelectionV3(FrozenModel):
    """Public-report read family; no actor or new source selection in the HTTP body."""

    schema_version: Literal["system-rag-similarity-read-selection/3.0"]
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        try:
            return similarity_contract_document(value, "system-rag-similarity-read-v3", 4096)
        except SchemaError:
            raise ValueError("invalid exact public solution similarity selector") from None

    def exact_selection(self) -> CompletedSimilarityQuerySelection:
        return CompletedSimilarityQuerySelection.model_validate(
            self.model_dump(mode="json", exclude={"schema_version"})
        )
