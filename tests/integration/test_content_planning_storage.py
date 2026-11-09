"""Disposable PostgreSQL gates; synthetic metadata only, no live items or files.

These exercise storage primitives. Application authorization/GUI/output coverage
is separate and cannot be inferred from these persistence results.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from threading import Barrier
from uuid import uuid4

import eom_catalog_service.external_item_models
import eom_catalog_service.knowledge_graph_models
import eom_catalog_service.legacy_usage_models  # noqa: F401
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.content_planning import ContentEditionCompositionV1
from eom_catalog_service.content_planning_models import (
    CONTENT_PRODUCT_REVISION_SEQUENCE,
    ContentEditionRecord,
    ContentEditionRevisionRecord,
    ContentPlanningCommandReceiptRecord,
)
from eom_catalog_service.content_print_models import ContentPrintRecord
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRecord,
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_slot_models import CuratedDocumentAssemblySlotRecord
from eom_catalog_service.models import DeliverableRecord, DeliverableRevisionRecord
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from tests.unit.content_planning_fixtures import SHA, composition, identifier, slot

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _id(prefix: str) -> str:
    return prefix + "_" + uuid4().hex


@dataclass(frozen=True)
class Pins:
    actor: str
    product: str
    edition: str


@pytest.fixture
def pins(creative_engine: Engine):
    actor, product, edition = _id("operator"), _id("deliverable"), _id("edition")
    with Session(creative_engine) as session, session.begin():
        session.add(
            OperatorRecord(
                operator_id=actor,
                username=actor,
                normalized_username=actor,
                display_name="Synthetic planning owner",
                status="ACTIVE",
                must_change_password=False,
                created_by="content-planning-disposable-test",
            )
        )
        session.add(
            DeliverableRecord(
                deliverable_id=product,
                deliverable_key=product,
                deliverable_type="OTHER",
                title="Synthetic content",
                edition="CONTENT_PLANNING",
                lifecycle_state="IN_PRODUCTION",
                created_by=actor,
            )
        )
        session.flush()
        session.add(
            ContentEditionRecord(
                edition_id=edition,
                deliverable_id=product,
                edition_key=edition,
                lifecycle_state="ACTIVE",
                created_by=actor,
            )
        )
    return Pins(actor, product, edition)


def _revision(session: Session, pins: Pins, number: int = 1, previous: str | None = None):
    body = composition(
        [],
        deliverable_id=pins.product,
        edition_id=pins.edition,
        deliverable_revision_id=_id("delivrev"),
        revision_number=number,
        previous_revision_id=previous,
        created_by=pins.actor,
    )
    value = ContentEditionCompositionV1.model_validate(body)
    session.add(
        DeliverableRevisionRecord(
            deliverable_revision_id=value.deliverable_revision_id,
            deliverable_id=pins.product,
            revision_number=session.scalar(select(CONTENT_PRODUCT_REVISION_SEQUENCE.next_value())),
            state="DRAFT",
            metadata_json=body,
            metadata_sha256=content_sha256(body),
        )
    )
    session.flush()
    session.add(
        ContentEditionRevisionRecord(
            deliverable_revision_id=value.deliverable_revision_id,
            deliverable_id=pins.product,
            edition_id=pins.edition,
            revision_number=number,
            previous_revision_id=previous,
            academic_year=value.academic_year,
            composition_sha256=value.composition_sha256,
        )
    )
    session.flush()
    return value


def _advance(session: Session, pins: Pins, value) -> None:
    row = session.scalar(
        select(ContentEditionRecord)
        .where(ContentEditionRecord.edition_id == pins.edition)
        .with_for_update()
    )
    assert row is not None
    row.current_revision_id = value.deliverable_revision_id
    row.lock_version += 1
    session.flush()


def test_exact_edition_head_and_parent_history_are_enforced(creative_engine, pins):
    with Session(creative_engine) as session, session.begin():
        first = _revision(session, pins)
        _advance(session, pins, first)
        second = _revision(session, pins, 2, first.deliverable_revision_id)
        _advance(session, pins, second)
    with creative_engine.begin() as connection:
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE content_editions SET current_revision_id=:old, "
                    "lock_version=lock_version+1 "
                    "WHERE edition_id=:edition"
                ),
                {"old": first.deliverable_revision_id, "edition": pins.edition},
            )
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE deliverable_revisions SET metadata_sha256=:hash "
                    "WHERE deliverable_revision_id=:revision"
                ),
                {"hash": SHA, "revision": first.deliverable_revision_id},
            )
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text("DELETE FROM content_edition_revisions WHERE edition_id=:edition"),
                {"edition": pins.edition},
            )
        assert (
            connection.scalar(
                select(ContentEditionRecord.current_revision_id).where(
                    ContentEditionRecord.edition_id == pins.edition
                )
            )
            == second.deliverable_revision_id
        )


def test_wrong_revision_metadata_cannot_enter_typed_index(creative_engine, pins):
    with Session(creative_engine) as session, session.begin():
        revision = _id("delivrev")
        session.add(
            DeliverableRevisionRecord(
                deliverable_revision_id=revision,
                deliverable_id=pins.product,
                revision_number=1,
                state="DRAFT",
                metadata_json={"edition_id": pins.edition},
                metadata_sha256=SHA,
            )
        )
        session.flush()
        with pytest.raises(DBAPIError), session.begin_nested():
            session.add(
                ContentEditionRevisionRecord(
                    deliverable_revision_id=revision,
                    deliverable_id=pins.product,
                    edition_id=pins.edition,
                    revision_number=1,
                    previous_revision_id=None,
                    academic_year=2027,
                    composition_sha256=SHA,
                )
            )
            session.flush()


def test_two_concurrent_editors_only_one_can_advance_expected_head(creative_engine, pins):
    with Session(creative_engine) as session, session.begin():
        original = _revision(session, pins)
        _advance(session, pins, original)
    barrier = Barrier(2)

    def save():
        barrier.wait(timeout=10)
        with Session(creative_engine) as session, session.begin():
            row = session.scalar(
                select(ContentEditionRecord)
                .where(ContentEditionRecord.edition_id == pins.edition)
                .with_for_update()
            )
            if row.current_revision_id != original.deliverable_revision_id:
                return "STALE"
            value = _revision(session, pins, 2, original.deliverable_revision_id)
            _advance(session, pins, value)
            return "SAVED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save), pool.submit(save)]
        assert sorted(value.result(timeout=20) for value in futures) == ["SAVED", "STALE"]
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentEditionRevisionRecord)
                .where(ContentEditionRevisionRecord.edition_id == pins.edition)
            )
            == 2
        )


def test_different_editions_of_same_content_do_not_share_a_write_lock(creative_engine, pins):
    other = Pins(pins.actor, pins.product, _id("edition"))
    with Session(creative_engine) as session, session.begin():
        session.add(
            ContentEditionRecord(
                edition_id=other.edition,
                deliverable_id=other.product,
                edition_key=other.edition,
                lifecycle_state="ACTIVE",
                created_by=other.actor,
            )
        )
    barrier = Barrier(2)

    def save(value):
        with Session(creative_engine) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout='5s'"))
            session.scalar(
                select(ContentEditionRecord)
                .where(ContentEditionRecord.edition_id == value.edition)
                .with_for_update()
            )
            revision = _revision(session, value)
            barrier.wait(timeout=10)  # both can write before either transaction commits
            _advance(session, value, revision)
            return revision.deliverable_revision_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, value) for value in (pins, other)]
        assert len({value.result(timeout=20) for value in futures}) == 2


def test_rollback_and_replay_keep_one_result_pointer(creative_engine, pins):
    key = "planning-replay-" + uuid4().hex
    result = {"deliverable_id": pins.product, "edition_id": pins.edition}
    with (
        pytest.raises(RuntimeError, match="before commit"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        session.add(
            ContentPlanningCommandReceiptRecord(
                actor_id=pins.actor,
                command_kind="CREATE_EDITION",
                idempotency_key=key,
                request_sha256=SHA,
                result_pointer=result,
            )
        )
        session.flush()
        raise RuntimeError("before commit")
    barrier = Barrier(2)

    def save():
        barrier.wait(timeout=10)
        try:
            with Session(creative_engine) as session, session.begin():
                session.add(
                    ContentPlanningCommandReceiptRecord(
                        actor_id=pins.actor,
                        command_kind="CREATE_EDITION",
                        idempotency_key=key,
                        request_sha256=SHA,
                        result_pointer=result,
                    )
                )
                session.flush()
            return "NEW"
        except IntegrityError:
            with Session(creative_engine) as session:
                existing = session.get(
                    ContentPlanningCommandReceiptRecord, (pins.actor, "CREATE_EDITION", key)
                )
                assert existing.request_sha256 == SHA
                assert existing.result_pointer == result
            return "REPLAY"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save), pool.submit(save)]
        assert sorted(value.result(timeout=20) for value in futures) == ["NEW", "REPLAY"]


def _assembly(session, pins, *, profile="curated-document-assembly-manifest/2.0"):
    assembly, revision = _id("assembly"), _id("assemblyrev")
    session.add(CuratedDocumentAssemblyRecord(assembly_id=assembly, created_by=pins.actor))
    session.flush()
    session.add(
        CuratedDocumentAssemblyRevisionRecord(
            assembly_id=assembly,
            assembly_revision_id=revision,
            revision_number=1,
            revision_state="INPUT_PINNED",
            manifest_schema_version=profile,
            selection_sha256=SHA,
            request_sha256=SHA,
            manifest_sha256=SHA,
            canonical_document={"schema_version": profile, "placements": []},
            idempotency_key="assembly-" + uuid4().hex,
            created_by=pins.actor,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    return revision


def test_1200_occurrences_empty_targets_and_profile_separation(creative_engine, pins):
    with Session(creative_engine) as session, session.begin():
        revision = _assembly(session, pins)
        legacy = _assembly(session, pins, profile="curated-document-assembly-manifest/1.0")
        for position in range(1, 1201):
            body = slot(position, target={"placement_kind": "EMPTY"})
            session.add(
                CuratedDocumentAssemblySlotRecord(
                    assembly_revision_id=revision,
                    placement_id=body["placement_id"],
                    position=position,
                    placement_kind="EMPTY",
                    canonical_slot=body,
                )
            )
        session.flush()
        assert (
            session.scalar(
                select(func.count())
                .select_from(CuratedDocumentAssemblySlotRecord)
                .where(CuratedDocumentAssemblySlotRecord.assembly_revision_id == revision)
            )
            == 1200
        )
        with pytest.raises(DBAPIError), session.begin_nested():
            session.add(
                CuratedDocumentAssemblySlotRecord(
                    assembly_revision_id=legacy,
                    placement_id=identifier("placement"),
                    position=1,
                    placement_kind="EMPTY",
                    canonical_slot=slot(1, target={"placement_kind": "EMPTY"}),
                )
            )
            session.flush()
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                update(CuratedDocumentAssemblySlotRecord)
                .where(CuratedDocumentAssemblySlotRecord.assembly_revision_id == revision)
                .values(position=2)
            )


def test_concurrent_initial_print_record_is_unique(creative_engine, pins):
    with Session(creative_engine) as session, session.begin():
        value = _revision(session, pins)
        _advance(session, pins, value)
    barrier = Barrier(2)

    def record():
        barrier.wait(timeout=10)
        try:
            with Session(creative_engine) as session, session.begin():
                session.add(
                    ContentPrintRecord(
                        print_record_id=_id("print"),
                        edition_id=pins.edition,
                        deliverable_revision_id=value.deliverable_revision_id,
                        scope_sha256=SHA,
                        intent="INITIAL",
                        canonical_record={},
                        record_sha256=SHA,
                        recorded_by=pins.actor,
                    )
                )
                session.flush()
            return "NEW"
        except IntegrityError:
            return "EXISTS"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(record), pool.submit(record)]
        assert sorted(value.result(timeout=20) for value in futures) == ["EXISTS", "NEW"]


def test_downgrade_does_not_discard_created_edition_history(creative_engine, pins):
    migration = import_module("migrations.versions.20261109_0075_content_planning")
    with creative_engine.begin() as connection:
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="CONTENT_PLANNING_HISTORY_EXISTS"),
        ):
            migration.downgrade()
        assert (
            connection.scalar(
                select(ContentEditionRecord.edition_id).where(
                    ContentEditionRecord.edition_id == pins.edition
                )
            )
            == pins.edition
        )
