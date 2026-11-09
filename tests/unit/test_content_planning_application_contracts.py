"""Application commands and V2 batching preserve old resolver invariants."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts.content_planning_commands import (
    CreatePlannedContent,
    parse_content_planning_command,
)
from eom_catalog_contracts.curated_document_slots import CuratedSlot
from eom_catalog_service import curated_document_slot_resolution as resolution
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.curated_document_assembly_source import (
    CuratedDocumentAssemblySourceError,
    resolve_curated_external_document,
    resolve_pinned_curated_external_documents,
)
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.content_planning_fixtures import identifier, item_target, slot, source_target
from tests.unit.test_curated_document_assembly_item import _selection as item_selection
from tests.unit.test_curated_document_assembly_item import _Session as ItemSession
from tests.unit.test_curated_document_assembly_resolution import _actor, _resolved_source
from tests.unit.test_curated_document_assembly_source import _Media, _rows, _selection
from tests.unit.test_curated_document_assembly_source import _Session as SourceSession


def test_creation_requires_one_explicit_typed_shape_and_rejects_client_authority():
    body = {
        "command_kind": "CREATE_CONTENT",
        "content_title": "학교별 시험지",
        "content_type": "OTHER",
        "edition_label": "2027",
        "academic_year": 2027,
        "sections": [],
    }
    assert isinstance(parse_content_planning_command(body), CreatePlannedContent)
    for change in (
        {"actor_id": identifier("operator")},
        {"academic_year": True},
        {"content_title": "bad\tlabel"},
        {"edition_label": " 앞공백"},
        {"content_type": "SCHOOL_AND_PERMANENTLY_UNUSED"},
    ):
        invalid = deepcopy(body)
        invalid.update(change)
        with pytest.raises((ValidationError, SchemaError)):
            parse_content_planning_command(invalid)


def test_v2_keeps_published_old_graph_and_deduplicates_item_targets():
    selection = item_selection()
    session = ItemSession(selection)
    session.corpus.current_graph_snapshot_revision_id = identifier("graphrev", 99)
    target = selection.model_dump(mode="json", exclude={"position"})
    occurrences = tuple(CuratedSlot.model_validate(slot(i, target=target)) for i in range(1, 501))
    resolved = resolution.resolve_curated_slots(
        session, occurrences, _actor(PermissionKey.ITEM_READ)
    )
    assert len(resolved) == 500 and session.execute_calls == 2
    assert len({entry.placement_id for entry in resolved}) == 500
    assert all(
        entry.target.graph_snapshot_revision_id == selection.graph_snapshot_revision_id
        for entry in resolved
    )


def test_v2_batches_distinct_graphs_and_preserves_arbitrary_display_order(monkeypatch):
    calls = []

    def authorize(_session, values):
        calls.append(values)
        assert len(values) <= 200
        assert len({row.graph_snapshot_revision_id for row in values}) == 1
        assert len({row.item_revision_id for row in values}) == len(values)
        return values

    monkeypatch.setattr(resolution, "reauthorize_curated_registered_items", authorize)
    occurrences = []
    for i in range(1, 452):
        target = {
            **item_target(i),
            "graph_snapshot_revision_id": identifier("graphrev", 1 if i <= 450 else 2),
        }
        occurrences.append(CuratedSlot.model_validate(slot(i, target=target)))
    resolved = resolution.resolve_curated_slots(
        None, tuple(reversed(occurrences)), _actor(PermissionKey.ITEM_READ)
    )
    assert [len(call) for call in calls] == [200, 200, 50, 1]
    assert [row.placement_id for row in resolved] == [
        row.placement_id for row in reversed(occurrences)
    ]


def test_v2_deduplicates_source_bytes_without_losing_two_picture_occurrences(monkeypatch):
    calls = []

    def resolve(_session, selected):
        calls.append(selected)
        return tuple(_resolved_source(value) for value in selected)

    monkeypatch.setattr(resolution, "resolve_pinned_curated_external_documents", resolve)
    occurrences = tuple(CuratedSlot.model_validate(slot(i, target=source_target())) for i in (1, 2))
    result = resolution.resolve_curated_slots(
        None, occurrences, _actor(PermissionKey.ITEM_READ, PermissionKey.CONTENT_INTAKE_READ)
    )
    assert len(calls) == 1 and len(calls[0]) == 1
    assert result[0].target == result[1].target
    assert result[0].placement_id != result[1].placement_id
    with pytest.raises(ContentPlanningError, match="CURATED_SOURCE_PERMISSION_DENIED"):
        resolution.resolve_curated_slots(None, occurrences, _actor(PermissionKey.ITEM_READ))


def test_pinned_source_copy_can_use_exact_earlier_revision_but_not_a_changed_hash():
    rows = _rows()
    rows[0].current_revision_id = identifier("extitemrev", 99)
    saved = resolve_pinned_curated_external_documents(SourceSession(rows), (_selection(),))
    assert saved[0].source_revision_id == _selection().source_revision_id
    # Released V1 still requires current source; the successor does not relax it.
    with pytest.raises(CuratedDocumentAssemblySourceError, match="CURATED_SOURCE_STALE"):
        resolve_curated_external_document(SourceSession(rows), _Media(rows), _selection())
    rows[1].observation_sha256 = "sha256:" + "f" * 64
    with pytest.raises(CuratedDocumentAssemblySourceError, match="CURATED_SOURCE_POINTER_INVALID"):
        resolve_pinned_curated_external_documents(SourceSession(rows), (_selection(),))
