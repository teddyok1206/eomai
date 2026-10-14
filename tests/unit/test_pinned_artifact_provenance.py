"""Late current scalar reads with real temporary SQLite, not production metadata writes."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_service import pinned_artifact_resolution as module
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy import event

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_similarity_context_artifact import publish, publisher_for
from tests.unit.test_similarity_context_contracts import context_body


def publications(tmp_path, count=1):
    publisher = publisher_for(tmp_path)
    outputs = []
    for seed in "abcd"[:count]:
        raw = context_body(ready=False)
        raw["request"]["request_id"] = "similarityrequest_" + seed * 32
        raw["request"] = seal(raw["request"], "request_sha256")
        context = parse_similarity_context(seal(raw, "context_sha256"))
        outputs.append(publish(publisher, context, key="synthetic-provenance-" + seed * 32))
    return publisher, outputs


@pytest.mark.parametrize("count", (1, 4))
def test_late_provenance_is_three_indexed_scalar_batches_without_hash_or_file_io(
    tmp_path, monkeypatch, count
):
    publisher, outputs = publications(tmp_path, count)
    identities = tuple(
        (p.delivery.context_member.artifact_id, p.delivery.context_member.artifact_revision_id)
        for p in outputs
    )
    statements = []

    def observed(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch((*identities, *identities))
        event.listen(publisher.engine, "before_cursor_execute", observed)
        forbidden_hash = Mock(side_effect=AssertionError("late metadata check must not rehash"))
        monkeypatch.setattr(module, "sha256_file", forbidden_hash)
        monkeypatch.setattr(module, "content_sha256", forbidden_hash)
        try:
            reader.revalidate_provenance()
        finally:
            event.remove(publisher.engine, "before_cursor_execute", observed)
        assert len(statements) == 3
        assert all(
            statement.lstrip().upper().startswith("SELECT") and " IN (" in statement
            for statement in statements
        )
        assert not any(
            "artifact_revisions.manifest," in statement or "artifact_revisions.result," in statement
            for statement in statements
        )
        forbidden_hash.assert_not_called()


@pytest.mark.parametrize(
    "fault", ("logical", "revision", "producer", "manifest", "path", "missing")
)
def test_external_lifecycle_or_lineage_change_is_not_hidden_by_captured_orm_metadata(
    tmp_path, fault
):
    publisher, (output,) = publications(tmp_path)
    pin = output.delivery.context_member
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        with publisher.sessions.begin() as other:
            if fault == "logical":
                other.get(ArtifactRecord, pin.artifact_id).approved = False
            elif fault == "revision":
                other.get(ArtifactRevisionRecord, pin.artifact_revision_id).approved = False
            elif fault == "producer":
                other.get(JobRecord, output.owner_job_id).status = "RUNNING"
            elif fault == "manifest":
                other.get(ArtifactRevisionRecord, pin.artifact_revision_id).manifest_hash = (
                    "sha256:" + "0" * 64
                )
            elif fault == "path":
                other.get(
                    ArtifactRevisionRecord, pin.artifact_revision_id
                ).nas_path = "/tmp/synthetic-not-dereferenced"
            else:
                other.delete(other.get(ArtifactRevisionRecord, pin.artifact_revision_id))
        with pytest.raises(PinnedArtifactResolutionError, match="current provenance"):
            reader.revalidate_provenance()


def test_refreshed_orm_state_does_not_redefine_the_original_immutable_hash(tmp_path):
    publisher, (output,) = publications(tmp_path)
    pin = output.delivery.context_member
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        row = session.get(ArtifactRevisionRecord, pin.artifact_revision_id)
        with publisher.sessions.begin() as other:
            other.get(ArtifactRevisionRecord, pin.artifact_revision_id).content_hash = (
                "sha256:" + "0" * 64
            )
        session.refresh(row)
        with pytest.raises(PinnedArtifactResolutionError, match="current provenance"):
            reader.revalidate_provenance()


def test_expired_orm_metadata_cannot_add_lazy_reads_to_the_three_batch_check(tmp_path):
    publisher, outputs = publications(tmp_path, 4)
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(
            tuple(
                (
                    p.delivery.context_member.artifact_id,
                    p.delivery.context_member.artifact_revision_id,
                )
                for p in outputs
            )
        )
        session.expire_all()
        event.listen(publisher.engine, "before_cursor_execute", observe)
        try:
            reader.revalidate_provenance()
        finally:
            event.remove(publisher.engine, "before_cursor_execute", observe)
        assert len(statements) == 3


def test_late_check_refuses_pending_writes_without_flushing_them(tmp_path):
    publisher, (output,) = publications(tmp_path)
    pin = output.delivery.context_member
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        row = session.get(ArtifactRecord, pin.artifact_id)
        row.approved = False
        with pytest.raises(PinnedArtifactResolutionError, match="pending mutations"):
            reader.revalidate_provenance()
        assert row in session.dirty
        session.rollback()
    with publisher.sessions.begin() as session:
        assert session.get(ArtifactRecord, pin.artifact_id).approved is True


def test_empty_context_needs_no_sql_but_still_requires_its_original_root(tmp_path):
    publisher, _outputs = publications(tmp_path)
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.revalidate_provenance()
    with pytest.raises(PinnedArtifactResolutionError, match="transaction"):
        reader.revalidate_provenance()
