"""Exact observed score values; no inferred scale, float rounding or execution authority."""

import re
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import validate_contract

SOURCE_SCORE_V2_SCHEMA = "source-score-v2"
SOURCE_SCORE_V2_REF = "eom://schemas/external-item/source-score/2.0"
type IntegerSourcePoints = Annotated[int, Field(strict=True, ge=0, le=100)]
type HalfSourcePoints = Annotated[
    # Unlike $, the end assertion also rejects a final newline. The explicit
    # Python regex enables this JSON-Schema/ECMAScript-compatible lookahead.
    str, Field(strict=True, pattern=re.compile(r"^[1-9][0-9]?\.5(?![\s\S])"), max_length=4)
]


class PrintedSourceScoreV2(FrozenModel):
    state: Literal["PRINTED"]
    points: IntegerSourcePoints | HalfSourcePoints

    @model_validator(mode="after")
    def exact_score(self) -> Self:
        validate_contract(SOURCE_SCORE_V2_SCHEMA, self.model_dump(mode="json"))
        return self


class UnprintedSourceScoreV2(FrozenModel):
    state: Literal["UNPRINTED"]
    points: None

    @model_validator(mode="after")
    def no_invented_value(self) -> Self:
        validate_contract(SOURCE_SCORE_V2_SCHEMA, self.model_dump(mode="json"))
        return self


type SourceScoreV2 = Annotated[
    PrintedSourceScoreV2 | UnprintedSourceScoreV2, Field(discriminator="state")
]
_SCORE_ADAPTER: TypeAdapter[SourceScoreV2] = TypeAdapter(SourceScoreV2)


def parse_source_score_v2(value: object) -> PrintedSourceScoreV2 | UnprintedSourceScoreV2:
    return _SCORE_ADAPTER.validate_python(value)


def source_score_decimal(score: PrintedSourceScoreV2 | UnprintedSourceScoreV2) -> Decimal | None:
    """None means not printed, never zero; a printed value is never rescaled."""
    return Decimal(str(score.points)) if isinstance(score, PrintedSourceScoreV2) else None
