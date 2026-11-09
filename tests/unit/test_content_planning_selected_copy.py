"""Partial copy preserves exact origins and canonical source order."""

import pytest
from eom_catalog_contracts.curated_document_slots import CuratedDocumentAssemblyManifestV2
from eom_catalog_service.content_planning_layout import (
    ContentPlanningConflict,
    copy_assembly_slots,
)
from eom_identifiers import content_sha256

from tests.unit.content_planning_fixtures import SHA, TIME, identifier, slot


def source():
    value = {
        "schema_version": "curated-document-assembly-manifest/2.0",
        "assembly_id": identifier("assembly"),
        "assembly_revision_id": identifier("assemblyrev"),
        "revision_number": 1,
        "previous_revision_id": None,
        "selection_sha256": SHA,
        "placements": [slot(i) for i in range(1, 5)],
        "created_by": identifier("operator"),
        "created_at": TIME,
    }
    return CuratedDocumentAssemblyManifestV2.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )


def test_subset_order_is_source_order_and_positions_are_contiguous():
    original = source()
    copied = copy_assembly_slots(
        original,
        (identifier("placement", 10), identifier("placement", 11)),
        selected_placement_ids=(identifier("placement", 4), identifier("placement", 2)),
    )
    assert [row.position for row in copied] == [1, 2]
    assert [row.copied_from.placement_id for row in copied] == [
        identifier("placement", 2),
        identifier("placement", 4),
    ]
    assert all(row.copied_from.manifest_sha256 == original.manifest_sha256 for row in copied)
    assert copied[0].target == original.placements[1].target
    assert len(original.placements) == 4


@pytest.mark.parametrize(
    "selection",
    [(), (identifier("placement", 99),), (identifier("placement", 2),) * 2],
)
def test_empty_unknown_or_duplicate_subset_is_rejected(selection):
    with pytest.raises(ContentPlanningConflict, match="CONTENT_COPY_SELECTION_INVALID"):
        copy_assembly_slots(
            source(), (identifier("placement", 10),), selected_placement_ids=selection
        )


def test_subset_cannot_reuse_an_unselected_source_identity():
    with pytest.raises(ContentPlanningConflict, match="CONTENT_COPY_PLACEMENT_ID_INVALID"):
        copy_assembly_slots(
            source(),
            (identifier("placement", 3),),
            selected_placement_ids=(identifier("placement", 2),),
        )
