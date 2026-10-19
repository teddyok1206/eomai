"""Synthetic canonical registration parity; no Artifact writes or model execution."""

from __future__ import annotations

import pytest
from eom_catalog_contracts import AssessmentItemContentV2, AssessmentItemContentV3
from eom_catalog_service.item_content_contract import (
    canonical_content_team_item_materialization,
)
from eom_hwpx_contracts import (
    derive_content_team_equation_sources,
    normalize_content_team_stem,
)
from eom_identifiers import content_sha256
from pydantic import ValidationError

from tests.unit.test_inference_transfer_item_projection import _item_content_team


@pytest.mark.parametrize("version", (2, 3))
def test_shared_projection_preserves_existing_registration_bytes(version: int) -> None:
    original = _item_content_team(version)
    original_bytes_hash = content_sha256(original.model_dump(mode="json"))
    document = original.model_dump(mode="json")
    model = AssessmentItemContentV2 if version == 2 else AssessmentItemContentV3
    document["stem"] = normalize_content_team_stem(original.item_number, original.stem)
    document["equation_sources"] = []
    expected = model.model_validate(document)
    document["equation_sources"] = list(derive_content_team_equation_sources(expected))
    expected = model.model_validate(document)

    actual = canonical_content_team_item_materialization(original)

    assert actual == expected
    assert type(actual) is model
    assert content_sha256(actual.model_dump(mode="json")) == content_sha256(
        expected.model_dump(mode="json")
    )
    assert content_sha256(original.model_dump(mode="json")) == original_bytes_hash
    assert actual.equation_sources != original.equation_sources
    assert canonical_content_team_item_materialization(actual) == actual


@pytest.mark.parametrize("version", (2, 3))
def test_registered_materialization_revalidates_forged_frozen_values(version: int) -> None:
    forged = _item_content_team(version).model_copy(update={"choices": ()})
    with pytest.raises(ValidationError):
        canonical_content_team_item_materialization(forged)
