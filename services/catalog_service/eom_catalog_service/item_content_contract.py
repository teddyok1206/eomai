"""One authoritative schema/alias reader for Registry canonical Item content."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, overload

from eom_catalog_contracts import (
    AssessmentItemContent,
    AssessmentItemContentContract,
    AssessmentItemContentV2,
    AssessmentItemContentV3,
    validate_contract,
)
from eom_hwpx_contracts import (
    derive_content_team_equation_sources,
    normalize_content_team_stem,
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


@overload
def canonical_content_team_item_materialization(
    content: AssessmentItemContentV2,
) -> AssessmentItemContentV2: ...


@overload
def canonical_content_team_item_materialization(
    content: AssessmentItemContentV3,
) -> AssessmentItemContentV3: ...


def canonical_content_team_item_materialization(
    content: AssessmentItemContentV2 | AssessmentItemContentV3,
) -> AssessmentItemContentV2 | AssessmentItemContentV3:
    """Pure registered-content projection, shared by registration and provenance reads.

    Review paths belong to the original authoring draft. Registration normalizes
    its stem and derives equation sources; readers must reproduce exactly that
    boundary, not require equality of raw draft and registered-content hashes.
    No files are staged and neither input nor immutable history is modified.
    """
    model = type(content)
    checked = model.model_validate(content.model_dump(mode="json"))
    document = checked.model_dump(mode="json")
    document["stem"] = normalize_content_team_stem(checked.item_number, checked.stem)
    document["equation_sources"] = []
    projected = model.model_validate(document)
    document["equation_sources"] = list(derive_content_team_equation_sources(projected))
    return model.model_validate(document)
