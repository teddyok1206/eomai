"""One authoritative schema/alias reader for Registry canonical Item content."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from eom_catalog_contracts import (
    AssessmentItemContent,
    AssessmentItemContentContract,
    AssessmentItemContentV2,
    AssessmentItemContentV3,
    validate_contract,
)

ITEM_CONTENT_SCHEMAS: MappingProxyType[
    str,
    tuple[
        str,
        type[AssessmentItemContent] | type[AssessmentItemContentV2] | type[AssessmentItemContentV3],
    ],
] = MappingProxyType(
    {
        "eom.assessment.item-content/1.0": ("assessment-item-content", AssessmentItemContent),
        "eom://schemas/item-registry/assessment-item-content-v1": (
            "assessment-item-content",
            AssessmentItemContent,
        ),
        "eom.assessment.item-content/2.0": ("assessment-item-content-v2", AssessmentItemContentV2),
        "eom://schemas/item-registry/assessment-item-content-v2": (
            "assessment-item-content-v2",
            AssessmentItemContentV2,
        ),
        "eom.assessment.item-content/3.0": ("assessment-item-content-v3", AssessmentItemContentV3),
        "eom://schemas/item-registry/assessment-item-content-v3": (
            "assessment-item-content-v3",
            AssessmentItemContentV3,
        ),
    }
)


def read_item_content(schema_ref: str, document: dict[str, Any]) -> AssessmentItemContentContract:
    if schema_ref not in ITEM_CONTENT_SCHEMAS:
        raise ValueError("unsupported canonical Item content schema")
    schema, model = ITEM_CONTENT_SCHEMAS[schema_ref]
    validate_contract(schema, document)
    return model.model_validate(document)
