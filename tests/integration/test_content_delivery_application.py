"""Content scope pinning and existing HWPX queue in disposable PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.content_delivery import PrepareContentDelivery, ReadContentDeliveries
from eom_catalog_contracts.curated_document_slots import CuratedSlot
from eom_catalog_service.content_delivery_models import ContentDeliveryScopeRecord
from eom_catalog_service.content_delivery_service import ContentDeliveryService
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_layout import ContentPlanningConflict
from eom_catalog_service.content_print_models import ContentPrintRecord
from eom_catalog_service.curated_document_assembly_service import CuratedDocumentAssemblyService
from eom_hwpx_contracts.curated_occurrences import CuratedHwpxBuildInputV2
from eom_hwpx_manager.curated_application_service import CuratedHwpxApplicationService
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.content_planning_sources import add_source
from tests.integration.test_content_planning_application import change, create, ident, key
from tests.integration.test_content_planning_application import planning as planning
from tests.unit.content_planning_fixtures import slot

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def filled(planning, engine, count=3):
    original = create(planning)
    target = add_source(engine)
    contents = {
        section: tuple(
            CuratedSlot.model_validate(
                {
                    **slot(i, target=target),
                    "placement_id": ident("placement"),
                }
            )
            for i in range(1, count + 1)
        )
        for section in (0, 1)
    }
    return planning.service.execute(
        change(original, contents), actor=planning.editor, idempotency_key=key()
    ).composition


def command(saved, *, sections=None):
    return PrepareContentDelivery(
        edition_id=saved.edition_id,
        revision_id=saved.deliverable_revision_id,
        composition_sha256=saved.composition_sha256,
        section_ids=sections or tuple(row.section_id for row in saved.sections),
    )


def manifest(engine, prepared, actor):
    return CuratedDocumentAssemblyService(engine, media=Mock()).authorize_delivery_build(
        prepared.assembly_id,
        assembly_revision_id=prepared.assembly_revision_id,
        manifest_sha256=prepared.manifest_sha256,
        actor=actor,
    )


def test_scope_1200_positions_same_source_is_one_input_not_a_private_assembly(
    creative_engine, planning
):
    saved = filled(planning, creative_engine, 600)
    service = ContentDeliveryService(creative_engine)
    prepared = service.prepare(command(saved), actor=planning.editor, idempotency_key=key())
    pinned = manifest(creative_engine, prepared, planning.peer)
    assert prepared.placement_count == 1200
    assert len({slot.target.source_id for slot in pinned.placements}) == 1
    assert len({slot.placement_id for slot in pinned.placements}) == 1200
    assert tuple(slot.position for slot in pinned.placements) == tuple(range(1, 1201))
    assemblies = CuratedDocumentAssemblyService(creative_engine, media=Mock())
    rows, _ = assemblies.list_recent_titled(actor=planning.editor)
    assert prepared.assembly_id not in {row.assembly_id for row in rows}
    pins = Mock()
    pins.pin_inputs.return_value = CuratedHwpxBuildInputV2(
        assembly_id=pinned.assembly_id,
        assembly_revision_id=pinned.assembly_revision_id,
        assembly_manifest_sha256=pinned.manifest_sha256,
        handoff=None,
        converter=None,
        placements=tuple(
            dict(
                kind="NATIVE_DOCUMENT",
                position=slot.position,
                placement_id=slot.placement_id,
                source_format=slot.target.source_format,
                document=slot.target.document_artifact.model_dump(),
                size_bytes=slot.target.document_size_bytes,
            )
            for slot in pinned.placements
        ),
    )
    queue = CuratedHwpxApplicationService(creative_engine, assemblies=assemblies, input_pins=pins)
    request_key = key()
    record, created = queue.request_build(
        pinned.assembly_id,
        assembly_revision_id=pinned.assembly_revision_id,
        manifest_sha256=pinned.manifest_sha256,
        actor=planning.editor,
        idempotency_key=request_key,
    )
    same, repeated = queue.request_build(
        pinned.assembly_id,
        assembly_revision_id=pinned.assembly_revision_id,
        manifest_sha256=pinned.manifest_sha256,
        actor=planning.editor,
        idempotency_key=request_key,
    )
    assert created and not repeated and record.build_id == same.build_id
    pins.pin_inputs.assert_called_once()
    assert queue.get_build(record.build_id, actor=planning.peer).placement_count == 1200
    assert (
        queue.latest_build(
            pinned.assembly_id,
            assembly_revision_id=pinned.assembly_revision_id,
            manifest_sha256=pinned.manifest_sha256,
            actor=planning.peer,
        ).build_id
        == record.build_id
    )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentPrintRecord)
                .where(ContentPrintRecord.edition_id == saved.edition_id)
            )
            == 0
        )


def test_concurrent_scope_preparation_and_replay_share_one_pinned_input(creative_engine, planning):
    saved = filled(planning, creative_engine)
    service, barrier = ContentDeliveryService(creative_engine), Barrier(2)

    def submit(actor):
        barrier.wait(timeout=10)
        return service.prepare(command(saved), actor=actor, idempotency_key=key())

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = tuple(pool.map(submit, (planning.editor, planning.peer)))
    assert a.assembly_revision_id == b.assembly_revision_id
    request_key = key()
    first = service.prepare(command(saved), actor=planning.editor, idempotency_key=request_key)
    repeated = service.prepare(command(saved), actor=planning.editor, idempotency_key=request_key)
    assert repeated.replayed and first.assembly_revision_id == repeated.assembly_revision_id
    with pytest.raises(ContentPlanningError, match="CONTENT_IDEMPOTENCY_CONFLICT"):
        service.prepare(
            command(saved, sections=(saved.sections[0].section_id,)),
            actor=planning.editor,
            idempotency_key=request_key,
        )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentDeliveryScopeRecord)
                .where(ContentDeliveryScopeRecord.edition_id == saved.edition_id)
            )
            == 1
        )


def test_interrupted_prepare_rolls_back_then_same_request_can_complete(
    creative_engine, planning, monkeypatch
):
    import eom_catalog_service.content_delivery_service as module

    saved = filled(planning, creative_engine)
    service, request_key = ContentDeliveryService(creative_engine), key()
    append = module.append_curated_slot_revisions

    def interrupted(*args, **kwargs):
        append(*args, **kwargs)
        raise RuntimeError("synthetic interruption before scope commit")

    with monkeypatch.context() as patch:
        patch.setattr(module, "append_curated_slot_revisions", interrupted)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            service.prepare(command(saved), actor=planning.editor, idempotency_key=request_key)
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentDeliveryScopeRecord)
                .where(ContentDeliveryScopeRecord.edition_id == saved.edition_id)
            )
            == 0
        )
    prepared = service.prepare(command(saved), actor=planning.editor, idempotency_key=request_key)
    assert (
        manifest(creative_engine, prepared, planning.editor).assembly_revision_id
        == prepared.assembly_revision_id
    )


def test_empty_scope_and_wrong_hash_fail_before_scope_commit(creative_engine, planning):
    service = ContentDeliveryService(creative_engine)
    saved = create(planning)
    with pytest.raises(ContentPlanningConflict, match="CONTENT_PRINT_EMPTY_SECTION"):
        service.prepare(command(saved), actor=planning.editor, idempotency_key=key())
    with pytest.raises(ContentPlanningError, match="CONTENT_EDITION_REVISION_STALE"):
        service.prepare(
            command(saved).model_copy(update={"composition_sha256": "sha256:" + "0" * 64}),
            actor=planning.editor,
            idempotency_key=key(),
        )


def test_editing_head_does_not_retarget_prepared_output(creative_engine, planning):
    saved = filled(planning, creative_engine)
    service = ContentDeliveryService(creative_engine)
    prepared = service.prepare(command(saved), actor=planning.editor, idempotency_key=key())
    before = manifest(creative_engine, prepared, planning.peer)
    planning.service.execute(change(saved, {0: ()}), actor=planning.peer, idempotency_key=key())
    assert manifest(creative_engine, prepared, planning.peer) == before
    query = ReadContentDeliveries(
        query_kind="DELIVERIES", edition_id=saved.edition_id, before_id=None, limit=1
    )
    listed = planning.service.query(query, actor=planning.viewer)
    assert len(listed.rows) == 1 and listed.next_id is None
    assert listed.rows[0].prepared == prepared
    assert listed.rows[0].section_count == 2
    assert not listed.rows[0].matches_current_revision


def test_delivery_history_is_bounded_and_permissions_are_rechecked(creative_engine, planning):
    saved = filled(planning, creative_engine)
    service = ContentDeliveryService(creative_engine)
    with pytest.raises(ContentPlanningError, match="PERMISSION_DENIED"):
        service.prepare(command(saved), actor=planning.viewer, idempotency_key=key())
    prepared = tuple(
        service.prepare(
            command(saved, sections=(section.section_id,)),
            actor=planning.editor,
            idempotency_key=key(),
        )
        for section in saved.sections
    )
    query = ReadContentDeliveries(
        query_kind="DELIVERIES", edition_id=saved.edition_id, before_id=None, limit=1
    )
    first = planning.service.query(query, actor=planning.viewer)
    second = planning.service.query(
        query.model_copy(update={"before_id": first.next_id}), actor=planning.viewer
    )
    assert first.next_id and second.next_id is None
    assert {row.prepared.assembly_revision_id for row in (*first.rows, *second.rows)} == {
        row.assembly_revision_id for row in prepared
    }
    with pytest.raises(ContentPlanningError, match="CURSOR_INVALID"):
        planning.service.query(
            query.model_copy(update={"before_id": ident("assemblyrev")}), actor=planning.viewer
        )
    with pytest.raises(ContentPlanningError):
        manifest(
            creative_engine,
            prepared[0].model_copy(update={"manifest_sha256": "sha256:" + "0" * 64}),
            planning.peer,
        )
