"""Current placement and effective print union matches the workbook's year semantics."""

import pytest
from eom_catalog_contracts.content_planning_commands import CopyContentEdition
from eom_catalog_contracts.content_print_commands import VoidContentPrint
from eom_catalog_contracts.content_usage import (
    ReadContentUsage,
    ReadContentUsageSummary,
    ReadPriorContentUsage,
)
from eom_catalog_contracts.content_usage_filter import ContentUsageFilter
from eom_catalog_service.external_item_models import ExternalItemSourceRecord
from eom_catalog_service.external_item_read_service import (
    ExternalItemListFilter,
    list_external_item_sources,
)
from eom_catalog_service.models import DeliverableRecord
from sqlalchemy import event
from sqlalchemy.orm import Session

from tests.integration.content_planning_sources import add_source
from tests.integration.test_content_planning_application import change, key, section
from tests.integration.test_content_planning_application import planning as planning
from tests.integration.test_content_print_application import command, filled

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_prior_usage_keeps_exact_revision_and_has_bounded_pagination(creative_engine, monkeypatch):
    from eom_catalog_contracts.validation import validate_contract
    from eom_catalog_service import content_prior_usage_read as reader
    from eom_catalog_service.models import DeliverableRevisionRecord, UsageRecord
    from eom_operator_identity import PermissionKey

    from tests.item_registry.test_registry_persistence import _approved_revision
    from tests.unit.content_planning_fixtures import SHA, item_target
    from tests.unit.test_curated_document_assembly_resolution import _actor

    # Graph admission is separately covered by the shared resolver suite. This
    # transaction exercises real old-ledger/FK/query behavior, not a second importer.
    admissions = []
    monkeypatch.setattr(
        reader, "resolve_curated_slots", lambda s, slots, a: admissions.append(slots)
    )
    actor = _actor(PermissionKey.ITEM_READ, PermissionKey.USAGE_READ)
    with creative_engine.connect() as connection, connection.begin() as transaction:
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            item, revision, _ = _approved_revision(session)
            product = DeliverableRecord(
                deliverable_id="deliverable_" + "a" * 32,
                deliverable_key="prior-usage-test",
                deliverable_type="OTHER",
                title="옛" * 256,
                edition="old",
                lifecycle_state="RELEASED",
                created_by="test",
            )
            session.add(product)
            session.flush()
            prior = DeliverableRevisionRecord(
                deliverable_revision_id="delivrev_" + "b" * 32,
                deliverable_id=product.deliverable_id,
                revision_number=1,
                state="RELEASED",
                metadata_json={},
                metadata_sha256=SHA,
            )
            session.add(prior)
            session.flush()
            for number in (1, 2):
                session.add(
                    UsageRecord(
                        usage_record_id=f"usagerecord_{number:032x}",
                        item_id=item.item_id,
                        item_revision_id=revision.item_revision_id,
                        deliverable_id=product.deliverable_id,
                        deliverable_revision_id=prior.deliverable_revision_id,
                        section="1회",
                        sequence=number,
                        usage_role="PRIMARY",
                        recorded_by="test",
                        metadata_json={},
                    )
                )
            session.flush()
            query = ReadPriorContentUsage(
                query_kind="PRIOR_USAGE",
                targets=(
                    {
                        **item_target(),
                        "item_id": item.item_id,
                        "item_revision_id": revision.item_revision_id,
                        "item_manifest_sha256": revision.manifest_sha256,
                    },
                ),
                academic_year="ALL",
                after=None,
                limit=1,
            )
            first = reader.read_prior_content_usage(session, query, actor)
            second = reader.read_prior_content_usage(
                session, query.model_copy(update={"after": first.next_after}), actor
            )
            assert first.next_after is not None and second.next_after is None
            assert [row.position for row in first.rows + second.rows] == [1, 2]
            assert all(
                row.target.item_revision_id == revision.item_revision_id
                for row in first.rows + second.rows
            )
            assert first.rows[0].publication_revision_id is None and len(admissions) == 2
            validate_contract("content-planning-query-result-v1", first.model_dump(mode="json"))
            with pytest.raises(ValueError, match="PERMISSION_DENIED"):
                reader.read_prior_content_usage(session, query, _actor(PermissionKey.ITEM_READ))
        transaction.rollback()


def test_annual_unused_filter_is_before_pagination_and_follows_print_void(
    creative_engine, planning
):
    saved = filled(planning, creative_engine, count=1200)
    target = section(planning, saved).placements[0].target
    with Session(creative_engine) as session:
        namespace = session.get(ExternalItemSourceRecord, target.source_id).source_namespace
    second = add_source(creative_engine, "10311", namespace=namespace)
    third = add_source(creative_engine, "10312", namespace=namespace)

    def find(state, year, after=None):
        with Session(creative_engine) as session:
            return list_external_item_sources(
                session,
                ExternalItemListFilter(
                    source_namespace=namespace,
                    limit=1,
                    after_number=after,
                    usage_filter=ContentUsageFilter(state=state, academic_year=year),
                ),
            )

    year = saved.academic_year
    page = find("UNUSED", year)
    assert page.entries[0].source_id == second["source_id"]
    assert find("UNUSED", year, page.next_after_number).entries[0].source_id == third["source_id"]
    assert find("USED", year).entries[0].source_id == target.source_id
    assert find("USED", year + 1).entries == ()
    printed = planning.service.prints.execute(
        command(saved), actor=planning.editor, idempotency_key=key()
    )
    updated = planning.service.execute(
        change(saved, {0: ()}), actor=planning.editor, idempotency_key=key()
    ).composition
    assert find("USED", year).entries[0].source_id == target.source_id
    planning.service.prints.execute(
        VoidContentPrint(
            command_kind="VOID_PRINT",
            edition_id=updated.edition_id,
            print_record_id=printed.record.print_record_id,
            record_sha256=printed.record.record_sha256,
            reason="합성 인쇄 취소",
        ),
        actor=planning.editor,
        idempotency_key=key(),
    )
    assert find("USED", year).entries == ()
    assert find("UNUSED", year).entries[0].source_id == target.source_id


def query_for(planning, saved, *, limit=200, year="ALL"):
    target = section(planning, saved).placements[0].selection().target
    return ReadContentUsage(
        query_kind="USAGE", targets=(target,), academic_year=year, after=None, limit=limit
    )


def test_two_placements_two_printings_are_two_locations_not_six(creative_engine, planning):
    saved = filled(planning, creative_engine)
    first = planning.service.prints.execute(
        command(saved), actor=planning.editor, idempotency_key=key()
    )
    planning.service.prints.execute(
        command(saved, intent="REPRINT", predecessor=first.record.print_record_id),
        actor=planning.editor,
        idempotency_key=key(),
    )
    query = query_for(planning, saved, limit=1)
    page1 = planning.service.query(query, actor=planning.viewer)
    page2 = planning.service.query(
        query.model_copy(update={"after": page1.next_after}), actor=planning.viewer
    )
    assert page1.total_locations == page2.total_locations == 2
    assert page1.next_after is not None and page2.next_after is None
    assert {row.position for row in page1.rows + page2.rows} == {1, 2}
    assert all(
        row.currently_placed and row.print_count == 2 and row.matched_target_indices == (0,)
        for row in page1.rows + page2.rows
    )


def test_removed_unprinted_usage_disappears_but_printed_usage_stays(creative_engine, planning):
    saved = filled(planning, creative_engine)
    query = query_for(planning, saved)
    printed = planning.service.prints.execute(
        command(saved), actor=planning.editor, idempotency_key=key()
    )
    updated = planning.service.execute(
        change(saved, {0: ()}), actor=planning.editor, idempotency_key=key()
    ).composition
    page = planning.service.query(query, actor=planning.viewer)
    assert len(page.rows) == 2 and all(
        not row.currently_placed and row.print_count == 1 for row in page.rows
    )
    assert page.rows[0].revision_id == saved.deliverable_revision_id
    planning.service.prints.execute(
        VoidContentPrint(
            command_kind="VOID_PRINT",
            edition_id=updated.edition_id,
            print_record_id=printed.record.print_record_id,
            record_sha256=printed.record.record_sha256,
            reason="합성 테스트 오입력",
        ),
        actor=planning.editor,
        idempotency_key=key(),
    )
    assert planning.service.query(query, actor=planning.viewer).rows == ()


def test_copy_year_then_remove_is_not_permanently_used_and_archive_keeps_history(
    creative_engine, planning
):
    saved = filled(planning, creative_engine)
    query = query_for(planning, saved, year=2028)
    assert planning.service.query(query, actor=planning.viewer).total_locations == 0
    copied = planning.service.execute(
        CopyContentEdition(
            command_kind="COPY_EDITION",
            source_edition_id=saved.edition_id,
            source_revision_id=saved.deliverable_revision_id,
            source_sha256=saved.composition_sha256,
            edition_label="2028",
            academic_year=2028,
        ),
        actor=planning.editor,
        idempotency_key=key(),
    ).composition
    assert planning.service.query(query, actor=planning.viewer).total_locations == 2
    planning.service.execute(change(copied, {0: ()}), actor=planning.peer, idempotency_key=key())
    assert planning.service.query(query, actor=planning.viewer).total_locations == 0
    planning.service.prints.execute(command(saved), actor=planning.editor, idempotency_key=key())
    with Session(creative_engine) as session, session.begin():
        session.get(DeliverableRecord, saved.deliverable_id).lifecycle_state = "ARCHIVED"
    old = query.model_copy(update={"academic_year": 2027})
    assert planning.service.query(old, actor=planning.viewer).total_locations == 2


def test_page_query_count_is_bounded_not_per_placement(creative_engine, planning):
    saved = filled(planning, creative_engine, 1200)
    query = query_for(planning, saved)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(creative_engine, "before_cursor_execute", capture)
    try:
        page = planning.service.query(query, actor=planning.viewer)
    finally:
        event.remove(creative_engine, "before_cursor_execute", capture)
    assert page.total_locations == 1200 and len(page.rows) == 200
    assert len(statements) <= 12
    assert any(
        "content_edition_revision_forms" in sql and "content_print_scopes" in sql
        for sql in statements
    )


def test_summary_same_scope_print_union_other_editions_and_year(creative_engine, planning):
    saved = filled(planning, creative_engine)
    target = query_for(planning, saved).targets[0]
    query = ReadContentUsageSummary(
        query_kind="USAGE_SUMMARY",
        targets=(target,),
        academic_year=2027,
        edition_id=saved.edition_id,
    )
    planning.service.prints.execute(command(saved), actor=planning.editor, idempotency_key=key())
    planning.service.execute(
        CopyContentEdition(
            command_kind="COPY_EDITION",
            source_edition_id=saved.edition_id,
            source_revision_id=saved.deliverable_revision_id,
            source_sha256=saved.composition_sha256,
            edition_label="다른 판",
            academic_year=2027,
        ),
        actor=planning.editor,
        idempotency_key=key(),
    )
    result = planning.service.query(query, actor=planning.viewer)
    row = result.rows[0]
    assert row.total_locations == 4 and row.edition_locations == row.other_locations == 2
    assert (
        planning.service.query(
            query.model_copy(update={"academic_year": 2028}), actor=planning.viewer
        )
        .rows[0]
        .total_locations
        == 0
    )
