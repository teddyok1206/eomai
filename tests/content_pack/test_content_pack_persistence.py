from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_service.content_pack_repository import append_pack_event, transition_pack
from eom_catalog_service.models import (
    ContentPackActivationRecord,
    ContentPackEventRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
)
from eom_content_pack import ContentPackState
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_orchestrator.models import JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _artifact(session: Session, key: str) -> JobRecord:
    ensure_protocol_version(session, "pack-test/1.0", "sha256:" + "f" * 64)
    job, _ = submit_structured_job(
        session,
        job_id=new_job_id(),
        protocol_version="pack-test/1.0",
        idempotency_key=key,
        task_type="pack-test",
        request={"placeholder": True},
        logical_artifact_id=new_logical_artifact_id(),
        revision_id=new_revision_id(),
    )
    for state in (
        JobState.VALIDATED,
        JobState.QUEUED,
        JobState.CLAIMED,
        JobState.RUNNING,
        JobState.VALIDATING_RESULT,
        JobState.COMMITTING,
    ):
        transition_job(session, job.job_id, state, f"TEST_{state.value}")
    create_artifact_records(
        session,
        job=job,
        content_hash="sha256:" + "a" * 64,
        manifest_hash="sha256:" + "b" * 64,
        content_bytes=10,
        nas_path=f"/tmp/{job.logical_artifact_id}/{job.revision_id}",
        manifest={"placeholder": True},
        result={"placeholder": True},
    )
    transition_job(session, job.job_id, JobState.SUCCEEDED, "TEST_COMMITTED")
    session.flush()
    return job


def _release(session: Session, suffix: str = "1") -> ContentPackReleaseRecord:
    artifact = _artifact(session, f"pack-record-{suffix}")
    pack = ContentPackRecord(
        content_pack_id="contentpack_" + suffix * 32,
        pack_key=f"generic-placeholder-{suffix}",
        display_name="Generic Placeholder Pack",
        description="PLACEHOLDER_CONTENT",
        locale="ko-KR",
        domain_key="PLACEHOLDER_DOMAIN",
    )
    session.add(pack)
    release = ContentPackReleaseRecord(
        content_pack_release_id="packrel_" + suffix * 32,
        content_pack_id=pack.content_pack_id,
        version="0.1.0",
        schema_version="1.0",
        state=ContentPackState.DRAFT.value,
        source_tree_sha256="sha256:" + suffix * 64,
        bundle_sha256="sha256:" + chr(ord("a") + int(suffix)) * 64,
        manifest_sha256="sha256:" + "c" * 64,
        bundle_artifact_id=artifact.logical_artifact_id,
        bundle_artifact_revision_id=artifact.revision_id,
        canonical_manifest_json={"placeholder": True},
        compatibility_json={"placeholder": True},
        lock_version=1,
    )
    session.add(release)
    session.flush()
    append_pack_event(
        session,
        release,
        event_type="TEST_DRAFT",
        prior_state=None,
        new_state="DRAFT",
        actor_id="operator_01",
    )
    return release


def test_pack_release_events_and_immutable_payload(db_session: Session) -> None:
    release = _release(db_session)
    transition_pack(
        db_session,
        release,
        ContentPackState.VALIDATED,
        event_type="TEST_VALIDATED",
        actor_id="operator_01",
    )
    transition_pack(
        db_session,
        release,
        ContentPackState.RELEASED,
        event_type="TEST_RELEASED",
        actor_id="admin_01",
    )
    db_session.flush()
    events = list(
        db_session.scalars(
            select(ContentPackEventRecord)
            .where(
                ContentPackEventRecord.content_pack_release_id == release.content_pack_release_id
            )
            .order_by(ContentPackEventRecord.sequence)
        )
    )
    assert [event.sequence for event in events] == [1, 2, 3]
    with pytest.raises(DBAPIError, match="payload is immutable"), db_session.begin_nested():
        release.bundle_sha256 = "sha256:" + "e" * 64
        db_session.flush()


def test_activation_unique_constraint(db_session: Session) -> None:
    first = _release(db_session, "2")
    second = _release(db_session, "3")
    for release in (first, second):
        transition_pack(
            db_session,
            release,
            ContentPackState.VALIDATED,
            event_type="TEST_VALIDATED",
            actor_id="operator_01",
        )
        transition_pack(
            db_session,
            release,
            ContentPackState.RELEASED,
            event_type="TEST_RELEASED",
            actor_id="admin_01",
        )
    first_activation = ContentPackActivationRecord(
        activation_id="activation_" + "4" * 32,
        environment="development",
        pack_key="shared-pack",
        content_pack_release_id=first.content_pack_release_id,
        active=True,
        activated_by="admin_01",
        activated_at=datetime.now(UTC),
        lock_version=1,
    )
    db_session.add(first_activation)
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            ContentPackActivationRecord(
                activation_id="activation_" + "5" * 32,
                environment="development",
                pack_key="shared-pack",
                content_pack_release_id=second.content_pack_release_id,
                active=True,
                activated_by="admin_01",
                activated_at=datetime.now(UTC),
                lock_version=1,
            )
        )
        db_session.flush()
