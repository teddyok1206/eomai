"""Real business-key fencing and interruption in a guarded disposable database.

Synthetic Registry prerequisites avoid NAS/model work. Source fidelity and
authorization are separate unit/live gates, not implied by this storage test.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_service.creative_item_registration import (
    creative_registration_key,
    lock_creative_registration,
)
from eom_catalog_service.models import ItemRevisionRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.item_registry.test_registry_persistence import _approved_revision

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _copy_revision(base, *, source_id, revision_number):
    values = {
        column.name: getattr(base, column.name)
        for column in ItemRevisionRecord.__table__.columns
        if column.name not in {"created_at", "updated_at"}
    }
    values.update(
        item_revision_id="itemrev_" + uuid4().hex,
        registration_key=creative_registration_key(source_id),
        revision_number=revision_number,
    )
    return ItemRevisionRecord(**values)


def test_concurrent_creative_registration_key_creates_one_revision(creative_engine):
    with Session(creative_engine, expire_on_commit=False) as session, session.begin():
        _, base, _ = _approved_revision(session)
        session.expunge(base)
    source_id = "extitem_" + uuid4().hex
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=10)
        with Session(creative_engine) as session, session.begin():
            existing = lock_creative_registration(session, source_id)
            if existing is not None:
                return existing.item_revision_id, False
            revision = _copy_revision(base, source_id=source_id, revision_number=2)
            session.add(revision)
            session.flush()
            return revision.item_revision_id, True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: submit(), range(2)))
    assert len({entry[0] for entry in results}) == 1
    assert sum(entry[1] for entry in results) == 1
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemRevisionRecord)
                .where(ItemRevisionRecord.registration_key == creative_registration_key(source_id))
            )
            == 1
        )


def test_interrupted_creative_registration_rolls_back_and_same_key_can_resume(creative_engine):
    source_id = "extitem_" + uuid4().hex
    with Session(creative_engine) as session:
        base = session.scalar(
            select(ItemRevisionRecord).where(
                ItemRevisionRecord.registration_key == "registry-test-registration"
            )
        )
        assert base is not None
        session.expunge(base)
    with (
        pytest.raises(RuntimeError, match="synthetic interruption"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        assert lock_creative_registration(session, source_id) is None
        session.add(_copy_revision(base, source_id=source_id, revision_number=3))
        session.flush()
        raise RuntimeError("synthetic interruption")
    with Session(creative_engine) as session, session.begin():
        assert lock_creative_registration(session, source_id) is None
        revision = _copy_revision(base, source_id=source_id, revision_number=3)
        session.add(revision)
        session.flush()
        assert (
            lock_creative_registration(session, source_id).item_revision_id
            == revision.item_revision_id
        )
