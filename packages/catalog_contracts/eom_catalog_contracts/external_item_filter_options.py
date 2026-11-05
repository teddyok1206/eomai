"""Current categorical filter values; never an authorization or original Notion type claim."""

from typing import Annotated, Final, Literal, Self, get_args

from pydantic import Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel

type CategoricalItemMetadataField = Literal[
    "Q", "R", "Z", "Y", "V", "O", "G", "H", "T", "W", "X", "AB", "AD", "AE"
]
CATEGORICAL_ITEM_METADATA_FIELDS: Final[tuple[CategoricalItemMetadataField, ...]] = get_args(
    CategoricalItemMetadataField.__value__
)
ITEM_METADATA_OPTION_LIMIT: Final = 200


class ItemDbCategoricalFieldOptions(FrozenModel):
    field: CategoricalItemMetadataField
    values: tuple[Annotated[str, Field(min_length=1, max_length=255)], ...] = Field(max_length=200)
    truncated: bool

    @model_validator(mode="after")
    def stable_options(self) -> Self:
        if self.values != tuple(sorted(set(self.values))):
            raise ValueError("metadata choices must be unique and canonically ordered")
        return self


class ExternalItemDbFilterOptions(FrozenModel):
    schema_version: Literal["external-item-db-filter-options/1.0"]
    fields: tuple[ItemDbCategoricalFieldOptions, ...] = Field(min_length=14, max_length=14)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "external-item-db-filter-options-v1", 3 * 1024 * 1024
        )

    @model_validator(mode="after")
    def exact_field_order(self) -> Self:
        if tuple(value.field for value in self.fields) != CATEGORICAL_ITEM_METADATA_FIELDS:
            raise ValueError("metadata choice fields differ")
        return self
