"""HTTP presentation only; the native preparation contract remains authoritative."""

from __future__ import annotations

from typing import Annotated, Self

from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareRequest,
    ReferenceQueryPrepareRequestV2,
    ReferenceQueryPrepareRequestV3,
    ReferenceQueryPrepareRequestV11,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import Field, ModelWrapValidatorHandler, model_validator


def _http_validation_errors[T](value: object, handler: ModelWrapValidatorHandler[T]) -> T:
    try:
        return handler(value)
    except SchemaError:
        raise ValueError("invalid exact QUERY preparation request") from None


class ReferenceQueryPrepareInput(ReferenceQueryPrepareRequest):
    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        return _http_validation_errors(value, handler)


class ReferenceQueryPrepareInputV11(ReferenceQueryPrepareRequestV11):
    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        return _http_validation_errors(value, handler)


class ReferenceQueryPrepareInputV2(ReferenceQueryPrepareRequestV2):
    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        return _http_validation_errors(value, handler)


class ReferenceQueryPrepareInputV3(ReferenceQueryPrepareRequestV3):
    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        return _http_validation_errors(value, handler)


type SupportedReferenceQueryPrepareInput = Annotated[
    ReferenceQueryPrepareInput
    | ReferenceQueryPrepareInputV11
    | ReferenceQueryPrepareInputV2
    | ReferenceQueryPrepareInputV3,
    Field(discriminator="schema_version"),
]
