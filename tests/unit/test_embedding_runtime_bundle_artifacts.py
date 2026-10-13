"""Bundle publication adapter and existing local owner; no installed runtime admission."""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import eom_orchestrator.embedding_runtime_bundle_artifacts as module
import pytest
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    RUNTIME_BUNDLE_SCHEMA_REF,
    EmbeddingRuntimeBundle,
    embedding_runtime_bundle_bytes,
    validate_embedding_runtime_bundle_pointer,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator.control_artifacts import ControlArtifactPublisher, PublishedControlArtifact
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.embedding_runtime_bundle_artifacts import (
    EmbeddingBundlePublicationError,
    EmbeddingRuntimeBundleArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import ControlArtifactPointer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_artifact_publication import _publisher

NOW = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def bundle() -> EmbeddingRuntimeBundle:
    return native_config_metadata()[1]


class RecordingOwner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.change: tuple[str, object] | None = None
        self.error: Exception | None = None

    def publish_bytes(self, **values: Any) -> PublishedControlArtifact:
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        receipt = PublishedControlArtifact(
            job_id="job_" + "a" * 32,
            pointer=ControlArtifactPointer(
                artifact_id="artifact_" + "b" * 32,
                artifact_revision_id="rev_" + "c" * 32,
                sha256=sha256_bytes(values["payload"]),
                schema_ref=values["schema_ref"],
                media_type=values["media_type"],
                logical_name=values["logical_name"],
            ),
            manifest_sha256="sha256:" + "d" * 64,
        )
        if self.change is not None:
            field, value = self.change
            if field == "job_id":
                assert isinstance(value, str)
                receipt = replace(receipt, job_id=value)
            elif field == "manifest_sha256":
                assert isinstance(value, str)
                receipt = replace(receipt, manifest_sha256=value)
            else:
                receipt = replace(
                    receipt, pointer=receipt.pointer.model_copy(update={field: value})
                )
        return receipt

    def adapter(self) -> EmbeddingRuntimeBundleArtifactPublisher:
        return EmbeddingRuntimeBundleArtifactPublisher(
            cast(ControlArtifactPublisher, self), source_commit="a" * 40
        )


def test_one_bounded_canonical_member_and_distinct_owner_identity(
    bundle: EmbeddingRuntimeBundle,
) -> None:
    owner = RecordingOwner()
    receipt = owner.adapter().publish(bundle, created_at=NOW)
    (call,) = owner.calls
    raw = embedding_runtime_bundle_bytes(bundle)
    assert call["payload"] == raw and len(raw) <= MAX_RUNTIME_BUNDLE_BYTES
    assert call["logical_name"] == "bundle.json"
    assert call["schema_ref"] == RUNTIME_BUNDLE_SCHEMA_REF
    assert call["artifact_type"] == "control_embedding_runtime_bundle"
    assert call["media_type"] == "application/json"
    assert call["source_commit"] == "a" * 40 and call["created_at"] == NOW
    assert receipt.owner_job_id == "job_" + "a" * 32
    assert receipt.bundle.bundle_id == bundle.bundle_id
    assert receipt.bundle.bundle_revision_id == bundle.bundle_revision_id
    assert receipt.bundle.manifest_member.artifact_id == "artifact_" + "b" * 32
    assert receipt.bundle.manifest_member.artifact_revision_id == "rev_" + "c" * 32
    assert receipt.bundle.bundle_raw_sha256 == sha256_bytes(raw)
    validate_embedding_runtime_bundle_pointer(bundle, receipt.bundle, raw)


def test_identity_key_does_not_change_when_content_or_source_release_changes(
    bundle: EmbeddingRuntimeBundle,
) -> None:
    owner = RecordingOwner()
    body = bundle.model_dump(mode="json")
    body["execution_model_spec"]["model_revision_id"] = "embeddingmodelrev_" + "e" * 32
    body["execution_model_spec"] = seal(body["execution_model_spec"], "manifest_sha256")
    changed = EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
    owner.adapter().publish(bundle, created_at=NOW)
    other = EmbeddingRuntimeBundleArtifactPublisher(
        cast(ControlArtifactPublisher, owner), source_commit="b" * 40
    )
    other.publish(changed, created_at=NOW + timedelta(seconds=1))
    assert owner.calls[0]["payload"] != owner.calls[1]["payload"]
    assert owner.calls[0]["idempotency_key"] == owner.calls[1]["idempotency_key"]


@pytest.mark.parametrize("source", ["", "a" * 39, "A" * 40, "a" * 41, None, 12, True])
def test_invalid_installed_source_rejected(source: Any) -> None:
    with pytest.raises(EmbeddingBundlePublicationError, match="EMBEDDING_BUNDLE_SOURCE_INVALID"):
        EmbeddingRuntimeBundleArtifactPublisher(
            cast(ControlArtifactPublisher, RecordingOwner()), source_commit=source
        )


@pytest.mark.parametrize(
    "timestamp", [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=9)))]
)
def test_timestamp_is_utc_before_any_write(
    bundle: EmbeddingRuntimeBundle, timestamp: datetime
) -> None:
    owner = RecordingOwner()
    with pytest.raises(EmbeddingBundlePublicationError, match="EMBEDDING_BUNDLE_CONTEXT_INVALID"):
        owner.adapter().publish(bundle, created_at=timestamp)
    assert not owner.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("bundle_id", "../escape"),
        ("bundle_revision_id", "embeddingbundlerev_" + "f" * 32),
        ("bundle_sha256", "sha256:" + "0" * 64),
        ("numerical_runtime", None),
    ],
)
def test_copied_invalid_contract_rejected_before_owner(
    bundle: EmbeddingRuntimeBundle,
    field: str,
    value: object,
) -> None:
    owner = RecordingOwner()
    with pytest.raises(EmbeddingBundlePublicationError, match="EMBEDDING_BUNDLE_CONTEXT_INVALID"):
        owner.adapter().publish(bundle.model_copy(update={field: value}), created_at=NOW)
    assert not owner.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "unknown"),
        ("manifest_sha256", "bad"),
        ("artifact_id", "bad"),
        ("artifact_revision_id", "bad"),
        ("logical_name", "not-bundle.json"),
        ("schema_ref", "eom://schemas/other/1.0"),
        ("media_type", "text/plain"),
        ("sha256", "sha256:" + "0" * 64),
    ],
)
def test_bad_actual_owner_receipt_is_not_an_admitted_pointer(
    bundle: EmbeddingRuntimeBundle,
    field: str,
    value: object,
) -> None:
    owner = RecordingOwner()
    owner.change = field, value
    with pytest.raises(EmbeddingBundlePublicationError, match="EMBEDDING_BUNDLE_RECEIPT_INVALID"):
        owner.adapter().publish(bundle, created_at=NOW)
    assert len(owner.calls) == 1


def test_uncertain_commit_exception_is_preserved_without_retry(
    bundle: EmbeddingRuntimeBundle,
) -> None:
    owner = RecordingOwner()
    error = RuntimeError("synthetic commit uncertainty")
    owner.error = error
    with pytest.raises(RuntimeError) as raised:
        owner.adapter().publish(bundle, created_at=NOW)
    assert raised.value is error and len(owner.calls) == 1


def test_existing_local_owner_replay_conflict_and_no_payload_in_database(
    tmp_path: Path,
    bundle: EmbeddingRuntimeBundle,
) -> None:
    publisher, engine = _publisher(tmp_path)
    adapter = EmbeddingRuntimeBundleArtifactPublisher(publisher, source_commit="a" * 40)
    try:
        first = adapter.publish(bundle, created_at=NOW)
        pointer = first.bundle.manifest_member
        path = (
            publisher.settings.nas_artifact_root
            / pointer.artifact_id
            / pointer.artifact_revision_id
            / pointer.member_path
        )
        before = path.stat()
        assert path.read_bytes() == embedding_runtime_bundle_bytes(bundle)
        assert adapter.publish(bundle, created_at=NOW + timedelta(seconds=1)) == first
        assert (path.stat().st_ino, path.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
        body = bundle.model_dump(mode="json")
        body["execution_model_spec"]["model_revision_id"] = "embeddingmodelrev_" + "e" * 32
        body["execution_model_spec"] = seal(body["execution_model_spec"], "manifest_sha256")
        changed = EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
        with pytest.raises(ControlPlaneError):
            adapter.publish(changed, created_at=NOW)
        assert path.read_bytes() == embedding_runtime_bundle_bytes(bundle)
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
            assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 1
            assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
            job = session.scalars(select(JobRecord)).one()
            assert job.status == "SUCCEEDED"
            raw = json.dumps(job.request)
            assert "payload_model_spec" not in raw and "numerical_runtime" not in raw
            assert len(raw) < 2048
    finally:
        engine.dispose()


def test_adapter_is_small_metadata_only_and_has_no_parallel_persistence_or_runtime() -> None:
    tree = ast.parse(inspect.getsource(module))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
    }
    assert not any(
        name
        and name.startswith(
            (
                "sqlalchemy",
                "subprocess",
                "torch",
                "transformers",
                "eom_catalog_service",
                "eom_identity",
                "http",
            )
        )
        for name in imports
    )
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert not {"open", "new_job_id", "new_revision_id", "new_logical_artifact_id"}.intersection(
        calls
    )
