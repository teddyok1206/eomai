"""Partial-copy writes through existing guarded SAVE_SECTIONS, not a parallel API."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from eom_catalog_contracts.curated_document_slots import CuratedSlot
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_layout import copy_assembly_slots

from tests.integration.test_content_planning_application import (
    change,
    create,
    ident,
    key,
    section,
    slots,
)
from tests.integration.test_content_planning_application import (
    planning as planning,
)
from tests.unit.content_planning_fixtures import item_target

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def setup_copy(planning):
    original = create(planning)
    original = planning.service.execute(
        change(original, {0: slots(4)}), actor=planning.editor, idempotency_key=key()
    ).composition
    target = create(planning)
    manifest = section(planning, original)
    copied = copy_assembly_slots(
        manifest,
        (ident("placement"), ident("placement")),
        selected_placement_ids=(
            manifest.placements[3].placement_id,
            manifest.placements[1].placement_id,
        ),
    )
    return original, target, manifest, copied


def test_partial_copy_keeps_old_source_revision_and_replays_exact_result(planning):
    original, target, manifest, copied = setup_copy(planning)
    planning.service.execute(
        change(original, {0: slots(1)}), actor=planning.peer, idempotency_key=key()
    )
    command, request_key = change(target, {0: copied}), key()
    saved = planning.service.execute(command, actor=planning.editor, idempotency_key=request_key)
    replay = planning.service.execute(command, actor=planning.editor, idempotency_key=request_key)
    assert replay.replayed and replay.composition == saved.composition
    placed = section(planning, saved.composition).placements
    assert len(placed) == 2
    assert [row.copied_from.placement_id for row in placed] == [
        manifest.placements[1].placement_id,
        manifest.placements[3].placement_id,
    ]
    assert all(
        row.copied_from.assembly_revision_id == manifest.assembly_revision_id for row in placed
    )
    assert section(planning, original) == manifest


@pytest.mark.parametrize("mutation", ["hash", "revision", "target", "new_id"])
def test_forged_origin_or_target_rolls_back_entire_partial_copy(planning, mutation):
    _, target, _, copied = setup_copy(planning)
    data = copied[1].model_dump(mode="json")
    if mutation == "hash":
        data["copied_from"]["manifest_sha256"] = "sha256:" + "e" * 64
    elif mutation == "revision":
        data["copied_from"]["assembly_revision_id"] = ident("assemblyrev")
    elif mutation == "target":
        data["target"] = item_target()
    else:
        data["placement_id"] = data["copied_from"]["placement_id"]
    forged = (copied[0], CuratedSlot.model_validate(data))
    with pytest.raises(ContentPlanningError, match="CONTENT_COPY_"):
        planning.service.execute(
            change(target, {0: forged}), actor=planning.editor, idempotency_key=key()
        )
    assert planning.service.read(target.edition_id, actor=planning.viewer) == target
    assert section(planning, target).placements == ()


def test_retained_copy_provenance_cannot_be_rewritten(planning):
    _, target, manifest, copied = setup_copy(planning)
    saved = planning.service.execute(
        change(target, {0: copied}), actor=planning.editor, idempotency_key=key()
    ).composition
    data = copied[0].model_dump(mode="json")
    data["copied_from"]["placement_id"] = manifest.placements[0].placement_id
    with pytest.raises(ContentPlanningError, match="CONTENT_COPY_ORIGIN_IMMUTABLE"):
        planning.service.execute(
            change(saved, {0: (CuratedSlot.model_validate(data), copied[1])}),
            actor=planning.editor,
            idempotency_key=key(),
        )
    assert planning.service.read(saved.edition_id, actor=planning.viewer) == saved


def test_two_copies_cannot_overwrite_same_target_snapshot(planning):
    _, target, manifest, copied = setup_copy(planning)
    other = copy_assembly_slots(
        manifest,
        (ident("placement"),),
        selected_placement_ids=(manifest.placements[0].placement_id,),
    )
    barrier = Barrier(2)

    def save(rows):
        barrier.wait(timeout=10)
        try:
            return planning.service.execute(
                change(target, {0: rows}), actor=planning.editor, idempotency_key=key()
            ).disposition
        except ContentPlanningError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, (copied, other)))
    assert sorted(outcomes) == ["CONTENT_EDITION_REVISION_STALE", "SAVED"]


def test_replacement_preserves_old_snapshot_and_source(planning):
    original, target, manifest, copied = setup_copy(planning)
    old_rows = slots(3)
    target = planning.service.execute(
        change(target, {0: old_rows}), actor=planning.editor, idempotency_key=key()
    ).composition
    final = tuple(
        row.model_copy(update={"position": i})
        for i, row in enumerate((old_rows[0], *copied, old_rows[2]), 1)
    )
    saved = planning.service.execute(
        change(target, {0: final}), actor=planning.editor, idempotency_key=key()
    ).composition
    assert len(section(planning, saved).placements) == 4
    assert [row.placement_id for row in section(planning, target).placements] == [
        row.placement_id for row in old_rows
    ]
    assert section(planning, original) == manifest
