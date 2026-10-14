"""HTTP presentation of the canonical selector; do not duplicate its validation rules."""

from __future__ import annotations

from typing import Self

from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ModelWrapValidatorHandler, model_validator


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
