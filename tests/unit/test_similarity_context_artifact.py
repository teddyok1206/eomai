"""Actual publisher/local SQLite and temporary Artifacts; source/QUERY authority is synthetic."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_delivery import validate_similarity_context_delivery
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.similarity_context_artifact import (
    SIMILARITY_CONTEXT_ARTIFACT_TYPE,
    publish_similarity_context,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import func, select

from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_similarity_context_contracts import context_body

SOURCE = "a" * 40
KEY = "synthetic-similarity-context:" + "a" * 32


def publisher_for(tmp_path):
    publisher, _ = _publisher(tmp_path)
    workspace = tmp_path / "context-workspace"
    workspace.mkdir()
    publisher.settings = replace(publisher.settings, workspace_root=workspace)
    return publisher


def publish(publisher, context, *, key=KEY, source=SOURCE):
    return publish_similarity_context(
        publisher,
        context=context,
        expected_request=context.request,
        idempotency_key=key,
        source_commit=source,
    )


def test_one_canonical_context_replays_without_timestamp_or_bytes_changes(tmp_path: Path) -> None:
    publisher = publisher_for(tmp_path)
    context = parse_similarity_context(context_body())
    first = publish(publisher, context)
    (primary,) = tuple(publisher.settings.nas_artifact_root.rglob("context.json"))
    before = primary.stat()
    raw = primary.read_bytes()
    assert publish(publisher, context) == first
    after = primary.stat()
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    assert primary.read_bytes() == raw == canonical_json_bytes(context.model_dump(mode="json"))
    assert sha256_bytes(raw) == first.delivery.context_member.sha256
    assert first.delivery.context_sha256 == context.context_sha256
    assert first.delivery.context_member.sha256 != first.delivery.context_sha256
    assert not tuple(publisher.settings.workspace_root.iterdir())
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
        job = session.get(JobRecord, first.owner_job_id)
        assert job is not None and job.status == "SUCCEEDED"
        assert b'"candidates"' not in canonical_json_bytes(job.request)
        assert b'"query_execution"' not in canonical_json_bytes(job.request)
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        pin = first.delivery.context_member
        reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
        reader.require_file_set(
            pin.artifact_id,
            pin.artifact_revision_id,
            ("context.json",),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        read = reader.read_pinned(
            **pin.model_dump(mode="python"),
            expected_artifact_types=(SIMILARITY_CONTEXT_ARTIFACT_TYPE,),
            expected_primary_file="context.json",
            max_bytes=512 * 1024,
        )
        assert read.payload == raw
        assert (
            validate_similarity_context_delivery(
                first.delivery, context, expected_request=context.request
            )
            == context
        )


def test_existing_key_cannot_switch_request_or_context(tmp_path: Path) -> None:
    publisher = publisher_for(tmp_path)
    original = parse_similarity_context(context_body())
    first = publish(publisher, original)
    successor = parse_similarity_context(context_body(required=True))
    with pytest.raises(ControlPlaneError):
        publish(publisher, successor)
    assert publish(publisher, original) == first
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1


@pytest.mark.parametrize("fault", ("bad_source", "copied_extra", "bad_hash", "required_absent"))
def test_invalid_context_or_provenance_never_reaches_publication(
    tmp_path: Path, fault: str
) -> None:
    publisher = publisher_for(tmp_path)
    context = parse_similarity_context(context_body())
    source = "invalid" if fault == "bad_source" else SOURCE
    if fault == "copied_extra":
        context = context.model_copy(update={"role": "ADMIN"})
    elif fault == "bad_hash":
        context = context.model_copy(update={"context_sha256": "sha256:" + "0" * 64})
    elif fault == "required_absent":
        context = parse_similarity_context(context_body(ready=False, required=True))
    with pytest.raises((ValueError, SchemaError)):
        publish(publisher, context, source=source)
    assert not tuple(publisher.settings.workspace_root.iterdir())
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 0


@pytest.mark.parametrize(
    "field",
    (
        "primary_file",
        "primary_sha256",
        "job_id",
        "artifact_id",
        "artifact_revision_id",
        "manifest_sha256",
        "missing_receipt",
    ),
)
def test_bad_post_commit_receipt_preserves_original_artifact_without_automatic_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    publisher = publisher_for(tmp_path)
    context = parse_similarity_context(context_body())
    original = publisher.publish_first_observation
    calls = []

    def wrong(**kwargs):
        actual = original(**kwargs)
        calls.append(actual)
        if field == "missing_receipt":
            return None
        return replace(actual, **{field: "wrong"})

    with monkeypatch.context() as patch:
        patch.setattr(publisher, "publish_first_observation", wrong)
        with pytest.raises(ValueError, match="PUBLICATION_RECEIPT_INVALID"):
            publish(publisher, context)
    assert len(calls) == 1
    recovered = publish(publisher, context)
    assert recovered.delivery.context_member.artifact_revision_id == calls[0].artifact_revision_id
    assert recovered.owner_job_id == calls[0].job_id
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
