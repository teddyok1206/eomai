"""Bounded categorical values use the canonical schema, not copied Notion types."""

from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_filter_options import (
    CATEGORICAL_ITEM_METADATA_FIELDS,
    ExternalItemDbFilterOptions,
)
from eom_catalog_contracts.validation import validate_contract
from jsonschema.exceptions import ValidationError as SchemaError

ROOT = Path(__file__).resolve().parents[2]


def options():
    return dict(
        schema_version="external-item-db-filter-options/1.0",
        fields=[
            dict(field=field, values=[], truncated=False)
            for field in CATEGORICAL_ITEM_METADATA_FIELDS
        ],
    )


def test_choices_are_schema_first_with_identical_installed_resource():
    path = Path("api/external-item-db-filter-options-v1.schema.json")
    assert (ROOT / "schemas/api/v1" / path.name).read_bytes() == (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / path
    ).read_bytes()
    value = options()
    validate_contract("external-item-db-filter-options-v1", value)
    assert len(ExternalItemDbFilterOptions.model_validate(value).fields) == 14


@pytest.mark.parametrize("change", ("field", "duplicate", "order", "budget", "long", "extra"))
def test_choices_reject_wrong_fields_unbounded_or_ambiguous_values(change):
    value = options()
    if change == "field":
        value["fields"][0]["field"] = "I"
    elif change == "duplicate":
        value["fields"][0]["values"] = ["unit", "unit"]
    elif change == "order":
        value["fields"].reverse()
    elif change == "budget":
        value["fields"][0]["values"] = [f"{i:03d}" for i in range(201)]
    elif change == "long":
        value["fields"][0]["values"] = ["x" * 256]
    else:
        value["permissions"] = ["ADMIN"]
    with pytest.raises((ValueError, SchemaError)):
        ExternalItemDbFilterOptions.model_validate(value)
