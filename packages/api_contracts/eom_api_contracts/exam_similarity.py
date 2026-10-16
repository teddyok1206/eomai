"""HTTP validation wrapper over the one authoritative Assembly observation selector."""

from __future__ import annotations

from typing import Self

from eom_catalog_contracts.exam_similarity_read import ExamObservationReadSelection
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ModelWrapValidatorHandler, model_validator


class ExamSimilarityReadSelection(ExamObservationReadSelection):
    @model_validator(mode="wrap")
    @classmethod
    def http_validation_errors(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except SchemaError:
            raise ValueError("invalid exact Assembly observation selector") from None
