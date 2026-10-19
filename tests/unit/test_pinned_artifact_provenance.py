"""Late current scalar reads with real temporary SQLite, not production metadata writes."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_service import pinned_artifact_resolution as module
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.similarity_context_artifact import SIMILARITY_CONTEXT_ARTIFACT_TYPE
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


def _metadata_operation(reader, pin, operation):
    if operation == "file_set":
        return reader.require_file_set(pin.artifact_id, pin.artifact_revision_id, ("context.json",))
    if operation == "pointer":
        return reader.member_pointer(
            pin.artifact_id,
            pin.artifact_revision_id,
            pin.member_path,
            schema_ref=pin.schema_ref,
            media_type=pin.media_type,
        )
    if operation == "member":
        return reader.read_member(
            artifact_id=pin.artifact_id,
            revision_id=pin.artifact_revision_id,
            member_path=pin.member_path,
            sha256=pin.sha256,
            schema_ref=pin.schema_ref,
            media_type=pin.media_type,
            max_bytes=512 * 1024,
        )
    assert operation == "pinned"
    return reader.read_pinned(
        **pin.model_dump(mode="python"),
        expected_artifact_types=(SIMILARITY_CONTEXT_ARTIFACT_TYPE,),
        expected_primary_file="context.json",
        max_bytes=512 * 1024,
    )


@pytest.mark.parametrize("first_operation", ("file_set", "pointer", "member", "pinned"))
def test_equal_manifest_refresh_from_second_context_is_hashed_once_per_capture(
    tmp_path, monkeypatch, first_operation
):
    publisher, (output,) = publications(tmp_path)
    pin = output.delivery.context_member
    settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, settings)
        reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        original = _metadata_operation(reader, pin, "pinned")
        row = session.get(ArtifactRevisionRecord, pin.artifact_revision_id)
        manifest = row.manifest
        other = PinnedArtifactReadContext(session, settings)
        other.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        assert session.get(ArtifactRevisionRecord, pin.artifact_revision_id) is row
        assert row.manifest is not manifest and row.manifest == manifest
        assert not (session.new or session.dirty or session.deleted)
        assert _metadata_operation(other, pin, "pinned") == original
        hashed = Mock(wraps=module.content_sha256)
        monkeypatch.setattr(module, "content_sha256", hashed)
        statements = []

        def observe(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(publisher.engine, "before_cursor_execute", observe)
        try:
            _metadata_operation(reader, pin, first_operation)
            for _ in range(4):
                _metadata_operation(reader, pin, "file_set")
                assert _metadata_operation(reader, pin, "pointer") == pin
                assert _metadata_operation(reader, pin, "member") == original.payload
                assert _metadata_operation(reader, pin, "pinned") == original
            assert statements == []
            reader.revalidate_provenance()
            assert len(statements) == 3
        finally:
            event.remove(publisher.engine, "before_cursor_execute", observe)
        assert hashed.call_count == 1


@pytest.mark.parametrize("operation", ("file_set", "pointer", "member", "pinned"))
@pytest.mark.parametrize(
    "fault",
    (
        "manifest_old_hash",
        "manifest_new_hash",
        "header",
        "primary",
        "member_bytes",
        "schema_media",
        "member_missing",
        "logical_approval",
        "revision_approval",
        "producer",
        "content_hash",
        "content_bytes",
        "nas_path",
        "producer_pointer",
    ),
)
def test_refreshed_manifest_never_redefines_immutable_provenance(tmp_path, operation, fault):
    publisher, (output,) = publications(tmp_path)
    pin = output.delivery.context_member
    settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, settings)
        reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        _metadata_operation(reader, pin, "pinned")
        with publisher.sessions.begin() as other:
            revision = other.get(ArtifactRevisionRecord, pin.artifact_revision_id)
            if fault in {"manifest_old_hash", "manifest_new_hash"}:
                manifest = deepcopy(revision.manifest)
                manifest["files"][0]["sha256"] = "sha256:" + "f" * 64
                revision.manifest = manifest
                if fault == "manifest_new_hash":
                    revision.manifest_hash = content_sha256(manifest)
            elif fault in {"header", "primary", "member_bytes", "schema_media", "member_missing"}:
                manifest = deepcopy(revision.manifest)
                if fault == "header":
                    manifest["revision_id"] = "rev_" + "f" * 32
                elif fault == "primary":
                    manifest["primary_file"] = "other.json"
                elif fault == "member_bytes":
                    manifest["files"][0]["bytes"] += 1
                elif fault == "schema_media":
                    manifest["files"][0]["media_type"] = "text/plain"
                else:
                    manifest["files"] = []
                revision.manifest = manifest
                revision.manifest_hash = content_sha256(manifest)
            elif fault == "logical_approval":
                other.get(ArtifactRecord, pin.artifact_id).approved = False
            elif fault == "revision_approval":
                revision.approved = False
            elif fault == "producer":
                other.get(JobRecord, output.owner_job_id).status = "RUNNING"
            elif fault == "producer_pointer":
                other.get(JobRecord, output.owner_job_id).revision_id = "rev_" + "f" * 32
            elif fault == "content_hash":
                revision.content_hash = "sha256:" + "f" * 64
            elif fault == "content_bytes":
                revision.content_bytes += 1
            else:
                assert fault == "nas_path"
                revision.nas_path = "/tmp/synthetic-not-dereferenced"
        refreshed = PinnedArtifactReadContext(session, settings)
        refreshed.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        with pytest.raises(PinnedArtifactResolutionError):
            _metadata_operation(reader, pin, operation)
        if fault == "manifest_old_hash":
            # Advertised scalars alone are unchanged; the refresh's recomputed
            # canonical JSON hash, not the late scalar fence, rejects this forgery.
            reader.revalidate_provenance()
        else:
            with pytest.raises(PinnedArtifactResolutionError):
                reader.revalidate_provenance()


def test_second_context_missing_revision_cannot_replace_captured_metadata(tmp_path):
    publisher, (output,) = publications(tmp_path)
    pin = output.delivery.context_member
    settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, settings)
        reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        _metadata_operation(reader, pin, "pinned")
        with publisher.sessions.begin() as other:
            other.delete(other.get(ArtifactRevisionRecord, pin.artifact_revision_id))
        with pytest.raises(PinnedArtifactResolutionError, match="provenance does not resolve"):
            PinnedArtifactReadContext(session, settings).prefetch(
                ((pin.artifact_id, pin.artifact_revision_id),)
            )
        with pytest.raises(PinnedArtifactResolutionError, match="provenance is missing"):
            reader.revalidate_provenance()


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
        monkeypatch.setattr(module.os, "open", forbidden_hash)
        monkeypatch.setattr(module.os, "read", forbidden_hash)
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
