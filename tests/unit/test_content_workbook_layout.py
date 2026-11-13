"""Workbook admission and Edition layout share the same bounded section traversal."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts.content_planning import CONTENT_MAX_SECTIONS
from eom_catalog_contracts.content_planning_commands import CreatePlannedContent
from eom_catalog_contracts.content_workbook_import import (
    ContentWorkbookDocument,
    ContentWorkbookMetadata,
    ContentWorkbookProposal,
    ContentWorkbookResolution,
    ContentWorkbookRow,
    PrepareContentWorkbookRequest,
)
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_workbook_import_service import ContentWorkbookImportService
from eom_catalog_service.content_workbook_layout import require_workbook_layout, workbook_layout

from tests.api.test_content_workbook_routes import proposal as proposal_pointer
from tests.unit.content_planning_fixtures import SHA, identifier, source_target


def document(keys: tuple[tuple[str, str], ...]) -> ContentWorkbookDocument:
    return ContentWorkbookDocument(
        metadata=ContentWorkbookMetadata(
            content_title="합성 경계 검사",
            content_type="OTHER",
            edition_label="합성 초판",
            academic_year=2027,
            print_status="NOT_PRINTED",
            printed_on=None,
        ),
        rows=tuple(
            ContentWorkbookRow(
                row_number=index + 2,
                group_label=group,
                section_label=section,
                display_number=None,
                external_number="10321",
                points_milli=None,
                note="",
            )
            for index, (group, section) in enumerate(keys)
        ),
    )


def proposal(value: ContentWorkbookDocument, *, resolved: bool = True) -> ContentWorkbookProposal:
    return ContentWorkbookProposal(
        uploaded_by=identifier("operator"),
        original_filename="synthetic.xlsx",
        workbook_sha256=SHA,
        workbook_bytes=8,
        document=value,
        resolutions=tuple(
            ContentWorkbookResolution(
                row_number=row.row_number,
                status="MATCHED" if resolved else "MISSING",
                title="합성 문항" if resolved else None,
                target=source_target() if resolved else None,
            )
            for row in value.rows
        ),
    )


def grouped_document(*, extra_blank: bool = False, extra_group: bool = False):
    keys = tuple((f"group-{index}", "form") for index in range(CONTENT_MAX_SECTIONS // 2))
    if extra_blank:
        keys += (("", "form"),)
    if extra_group:
        keys += (("extra", "form"),)
    return document(keys)


def test_existing_domain_section_bound_is_not_broadened():
    assert CONTENT_MAX_SECTIONS == 10000
    assert CreatePlannedContent.model_json_schema()["properties"]["sections"]["maxItems"] == 10000


@pytest.mark.parametrize("extra_blank,extra_group", [(True, False), (False, True)])
def test_valid_rows_cannot_prepare_or_generate_10001_or_10002_sections(extra_blank, extra_group):
    value = grouped_document(extra_blank=extra_blank, extra_group=extra_group)
    assert len(value.rows) == 5001  # The workbook row contract is valid.
    pinned = proposal(value)
    for operation in (lambda: require_workbook_layout(value), lambda: workbook_layout(pinned)):
        with pytest.raises(ContentPlanningError, match="CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE"):
            operation()


@pytest.mark.parametrize("grouped", [False, True])
def test_exactly_10000_sections_remain_valid_for_admission_and_layout(grouped):
    value = (
        grouped_document()
        if grouped
        else document(tuple(("", f"form-{index}") for index in range(CONTENT_MAX_SECTIONS)))
    )
    require_workbook_layout(value)
    command, slots = workbook_layout(proposal(value))
    assert len(command.sections) == CONTENT_MAX_SECTIONS
    assert sum(len(rows) for rows in slots.values()) == len(value.rows)


def test_blank_and_repeated_groups_preserve_authored_order_and_occurrences():
    value = document((("", ""), ("", ""), ("G", "one"), ("G", "one"), ("G", "two")))
    require_workbook_layout(value)
    command, slots = workbook_layout(proposal(value))
    assert [(row.kind, row.label) for row in command.sections] == [
        ("FORM", "본문"),
        ("GROUP", "G"),
        ("FORM", "one"),
        ("FORM", "two"),
    ]
    assert [len(slots[row.section_id]) for row in command.sections if row.kind == "FORM"] == [
        2,
        2,
        1,
    ]


def test_feasibility_does_not_allocate_item_slots_or_random_identities(monkeypatch):
    create = Mock(side_effect=AssertionError("preview must not materialize the full layout"))
    monkeypatch.setattr("eom_catalog_service.content_workbook_layout.new_content_id", create)
    monkeypatch.setattr("eom_catalog_service.content_workbook_layout.CuratedSlot", create)
    require_workbook_layout(grouped_document())
    create.assert_not_called()


def test_unresolved_rows_remain_a_separate_existing_rejection():
    value = document((("", ""),))
    require_workbook_layout(value)
    with pytest.raises(ContentPlanningError, match="CONTENT_WORKBOOK_UNRESOLVED"):
        workbook_layout(proposal(value, resolved=False))


def service_stub(value: ContentWorkbookProposal):
    service = object.__new__(ContentWorkbookImportService)
    service.sessions = MagicMock()
    service.authorize = Mock()
    service._receipt = Mock(return_value=None)
    service._proposal = Mock(return_value=value)
    service.artifacts = Mock()
    return service


def test_prepare_rejects_structure_before_source_resolution_or_artifact_commit(
    tmp_path, monkeypatch
):
    value = grouped_document(extra_blank=True)
    service = service_stub(proposal(value))
    actor = SimpleNamespace(actor_id=identifier("operator"))
    content = b"synthetic-xlsx"
    path = tmp_path / "synthetic.xlsx"
    path.write_bytes(content)
    request = PrepareContentWorkbookRequest(
        actor_id=actor.actor_id,
        session_id=identifier("apisession"),
        request_id="req_synthetic_workbook",
        authentication_time=datetime.now(UTC),
        original_filename=path.name,
        content_length=len(content),
        sha256="sha256:" + hashlib.sha256(content).hexdigest(),
        idempotency_key="synthetic-workbook-key",
    )
    monkeypatch.setattr(
        "eom_catalog_service.content_workbook_import_service.read_content_workbook",
        Mock(return_value=value),
    )
    resolve = Mock(side_effect=AssertionError("structural rejection precedes source resolution"))
    monkeypatch.setattr(
        "eom_catalog_service.content_workbook_import_service.resolve_workbook_rows", resolve
    )
    with pytest.raises(ContentPlanningError, match="CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE"):
        service.prepare(path, request, actor)
    resolve.assert_not_called()
    service.artifacts.commit_file_set.assert_not_called()


@pytest.mark.parametrize("operation", ["read", "commit"])
def test_old_oversized_proposal_is_preserved_but_never_advertised_ready_or_committed(operation):
    pinned = proposal(grouped_document(extra_blank=True))
    before = pinned.model_dump(mode="json")
    service = service_stub(pinned)
    actor = SimpleNamespace(actor_id=identifier("operator"))
    pointer = proposal_pointer()
    with pytest.raises(ContentPlanningError, match="CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE"):
        if operation == "read":
            service.read(pointer, actor=actor)
        else:
            service.commit(pointer, actor=actor, idempotency_key="synthetic-workbook-commit")
    assert pinned.model_dump(mode="json") == before
    service.artifacts.commit_file_set.assert_not_called()
    service.sessions.begin.assert_not_called()


def test_readiness_still_matches_original_v1_resolution_semantics():
    pinned = proposal(document((("", ""),)))
    service = service_stub(pinned)
    actor = SimpleNamespace(actor_id=identifier("operator"))
    ready = service.read(proposal_pointer(), actor=actor)
    assert ready.can_commit is True and ready.unresolved_rows == 0
    service._proposal.return_value = proposal(pinned.document, resolved=False)
    unresolved = service.read(proposal_pointer(), actor=actor)
    assert unresolved.can_commit is False and unresolved.unresolved_rows == 1
