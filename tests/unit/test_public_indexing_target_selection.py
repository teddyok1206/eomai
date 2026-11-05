"""Deterministic public discovery fairness; no DB, model, authority or new queue."""

from itertools import permutations

import pytest
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_workflow_runner.local_embedding_service_reconciliation import _public_target_revisions
from pydantic import TypeAdapter

from tests.unit.test_public_solution_encoding import public_entry


def sources(past: int, registered: int) -> tuple[PopulationSource, ...]:
    # Registered revisions deliberately sort before every original past exam.
    seed = public_entry().source.model_dump(mode="json")
    return tuple(
        TypeAdapter(PopulationSource).validate_python(
            seed
            | dict(
                source_class=kind,
                item_id="item_" + f"{offset + number:032x}",
                item_revision_id="itemrev_" + f"{offset + number:032x}",
            )
        )
        for kind, count, offset in (("PAST_EXAM", past, 0xF000), ("APPROVED_ITEM", registered, 1))
        for number in range(count)
    )


@pytest.mark.parametrize(
    ("past", "registered", "limit", "expected_past", "expected_registered"),
    (
        (3, 8, 4, 2, 2),
        (1, 8, 4, 1, 3),
        (8, 1, 4, 3, 1),
        (0, 8, 4, 0, 4),
        (8, 0, 4, 4, 0),
        (1, 1, 8, 1, 1),
        (3, 8, 1, 1, 0),
        (3, 8, 3, 2, 1),
        (0, 0, 4, 0, 0),
    ),
)
def test_bounded_classes_cannot_be_hidden_by_registered_id_prefix(
    past, registered, limit, expected_past, expected_registered
):
    values = sources(past, registered)
    classes = {s.item_revision_id: s.source_class for s in values}
    targets = _public_target_revisions(set(classes), values, limit)
    assert targets == tuple(sorted(set(targets)))
    assert len(targets) <= limit
    assert sum(classes[revision] == "PAST_EXAM" for revision in targets) == expected_past
    assert sum(classes[revision] == "APPROVED_ITEM" for revision in targets) == expected_registered


def test_selection_is_canonical_and_does_not_reintroduce_cached_or_unavailable_sources():
    values = sources(2, 2)
    eligible = {values[1].item_revision_id, values[3].item_revision_id}
    for reordered in permutations(values):
        assert _public_target_revisions(eligible, reordered, 4) == tuple(sorted(eligible))


def test_continuing_registered_arrivals_cannot_starve_the_existing_past_exam_set():
    original = sources(9, 2)
    remaining = {s.item_revision_id for s in original if s.source_class == "PAST_EXAM"}
    for cycle in range(5):
        values = sources(9, 20 + cycle * 10)
        candidates = remaining | {
            s.item_revision_id for s in values if s.source_class == "APPROVED_ITEM"
        }
        chosen = _public_target_revisions(candidates, values, 4)
        remaining.difference_update(chosen)
    assert not remaining
