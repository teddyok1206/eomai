"""HTTP presentation only; the native preparation contract remains authoritative."""

from __future__ import annotations

from typing import Self

from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequest
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ModelWrapValidatorHandler, model_validator


class ReferenceQueryPrepareInput(ReferenceQueryPrepareRequest):
    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except SchemaError:
            raise ValueError("invalid exact QUERY preparation request") from None
