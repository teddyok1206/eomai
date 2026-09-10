from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import pytest
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactResolutionError,
    resolve_pinned_artifact_member,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord

T = TypeVar("T")


class _Session:
    def __init__(self, *records: object) -> None:
        self.records = {(type(record), _primary_key(record)): record for record in records}

    def get(self, model: type[T], identity: str) -> T | None:
        value = self.records.get((model, identity))
        return value if isinstance(value, model) else None


def _primary_key(record: object) -> str:
    if isinstance(record, ArtifactRecord):
        return record.logical_artifact_id
    if isinstance(record, ArtifactRevisionRecord):
        return record.revision_id
    if isinstance(record, JobRecord):
        return record.job_id
    raise TypeError("unsupported fixture record")


def _fixture(
    root: Path,
    *,
    artifact_type: str = "control_fixture",
    manifest_artifact_type: str | None = None,
    member_path: str = "evidence/value.json",
    schema_ref: str = "eom://schemas/fixture/value/1.0",
    metadata: bool = True,
    payload: bytes = b'{"value":1}',
) -> tuple[_Session, CatalogSettings, dict[str, object]]:
    artifact_id = "artifact_" + "1" * 32
    revision_id = "rev_" + "2" * 32
    job_id = "job_" + "3" * 32
    artifact_root = root / artifact_id / revision_id
    target = artifact_root / member_path
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    entry: dict[str, object] = {
        "file_name": member_path,
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    if metadata:
        entry.update({"schema_ref": schema_ref, "media_type": "application/json"})
    manifest = {
        "manifest_version": "1.0",
        "job_id": job_id,
        "logical_artifact_id": artifact_id,
        "revision_id": revision_id,
        "artifact_type": manifest_artifact_type or artifact_type,
        "primary_file": member_path,
        "content_hash": sha256_bytes(payload),
        "content_bytes": len(payload),
        "files": [entry],
    }
    job = JobRecord(
        job_id=job_id,
        protocol_version="fixture/1.0",
        idempotency_key="fixture-key",
        request_hash=sha256_bytes(b"request"),
        task_type=artifact_type,
        request={},
        status="SUCCEEDED",
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
    )
    logical = ArtifactRecord(
        logical_artifact_id=artifact_id,
        job_id=job_id,
        artifact_type=artifact_type,
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=revision_id,
        logical_artifact_id=artifact_id,
        job_id=job_id,
        content_hash=sha256_bytes(payload),
        manifest_hash=content_sha256(manifest),
        content_bytes=len(payload),
        nas_path=str(artifact_root),
        manifest=manifest,
        result={},
        approved=True,
    )
    return (
        _Session(job, logical, revision),
        CatalogSettings(nas_artifact_root=root),
        {
            "artifact_id": artifact_id,
            "artifact_revision_id": revision_id,
            "member_path": member_path,
            "sha256": sha256_bytes(payload),
            "schema_ref": schema_ref,
            "media_type": "application/json",
            "expected_artifact_types": {artifact_type},
            "expected_primary_file": member_path,
            "max_bytes": 1024,
        },
    )


def test_resolves_exact_member_and_full_provenance(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(tmp_path)

    resolved = resolve_pinned_artifact_member(session, settings, **arguments)  # type: ignore[arg-type]

    assert resolved.payload == b'{"value":1}'
    assert resolved.approved is True
    assert resolved.producing_job_state == "SUCCEEDED"


def test_empty_non_primary_member_requires_explicit_allowance(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(tmp_path)
    revision = session.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    member_path = "normalized/ambiguities.jsonl"
    target = Path(revision.nas_path) / member_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    files = revision.manifest["files"]
    assert isinstance(files, list)
    files.append(
        {
            "file_name": member_path,
            "sha256": sha256_bytes(b""),
            "bytes": 0,
            "schema_ref": "eom://schemas/knowledge/ambiguity/3.0",
            "media_type": "application/x-ndjson",
        }
    )
    revision.manifest_hash = content_sha256(revision.manifest)
    arguments.update(
        {
            "member_path": member_path,
            "sha256": sha256_bytes(b""),
            "schema_ref": "eom://schemas/knowledge/ambiguity/3.0",
            "media_type": "application/x-ndjson",
        }
    )

    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        resolve_pinned_artifact_member(
            session,
            settings,
            **arguments,  # type: ignore[arg-type]
        )

    resolved = resolve_pinned_artifact_member(
        session,
        settings,
        **arguments,  # type: ignore[arg-type]
        allow_empty=True,
    )

    assert resolved.payload == b""


def test_empty_primary_member_is_rejected_even_with_allowance(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(tmp_path, payload=b"")

    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        resolve_pinned_artifact_member(
            session,
            settings,
            **arguments,  # type: ignore[arg-type]
            allow_empty=True,
        )


def test_resolves_exact_logical_and_manifest_artifact_type_pair(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(
        tmp_path,
        artifact_type="workflow_support",
        manifest_artifact_type="legacy-item-extraction-result",
        member_path="result.json",
        schema_ref=("eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"),
    )
    arguments["expected_manifest_artifact_types"] = {"legacy-item-extraction-result"}

    resolved = resolve_pinned_artifact_member(
        session,
        settings,
        **arguments,  # type: ignore[arg-type]
    )

    assert resolved.artifact_type == "workflow_support"
    assert resolved.manifest_artifact_type == "legacy-item-extraction-result"
    arguments["expected_manifest_artifact_types"] = {"knowledge-analysis-proposal"}
    with pytest.raises(PinnedArtifactResolutionError, match="manifest does not resolve"):
        resolve_pinned_artifact_member(
            session,
            settings,
            **arguments,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("malformed_files", [1, True, {"file_name": "value.json"}])
def test_malformed_manifest_files_fail_stably(tmp_path: Path, malformed_files: object) -> None:
    session, settings, arguments = _fixture(tmp_path)
    revision = session.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    revision.manifest = {**revision.manifest, "files": malformed_files}

    with pytest.raises(PinnedArtifactResolutionError, match="manifest does not resolve"):
        resolve_pinned_artifact_member(session, settings, **arguments)  # type: ignore[arg-type]


def test_member_hash_drift_fails_stably(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(tmp_path)
    arguments["sha256"] = "sha256:" + "f" * 64

    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        resolve_pinned_artifact_member(session, settings, **arguments)  # type: ignore[arg-type]


def test_boolean_member_size_fails_stably(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(tmp_path)
    revision = session.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    files = revision.manifest["files"]
    assert isinstance(files, list)
    entry = files[0]
    assert isinstance(entry, dict)
    entry["bytes"] = True
    revision.manifest_hash = content_sha256(revision.manifest)

    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        resolve_pinned_artifact_member(session, settings, **arguments)  # type: ignore[arg-type]


def test_missing_materialization_fails_stably(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(tmp_path)
    revision = session.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    target = Path(revision.nas_path) / str(arguments["member_path"])
    target.unlink()

    with pytest.raises(PinnedArtifactResolutionError, match="materialization does not resolve"):
        resolve_pinned_artifact_member(session, settings, **arguments)  # type: ignore[arg-type]


def test_symlink_member_fails_stably(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(tmp_path)
    revision = session.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    target = Path(revision.nas_path) / str(arguments["member_path"])
    outside = tmp_path / "outside.json"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(PinnedArtifactResolutionError, match="materialization"):
        resolve_pinned_artifact_member(session, settings, **arguments)  # type: ignore[arg-type]


def test_historical_item_manifest_compatibility_is_narrow(tmp_path: Path) -> None:
    session, settings, arguments = _fixture(
        tmp_path,
        artifact_type="item-revision-manifest",
        member_path="item-revision-manifest.json",
        schema_ref="eom://schemas/item-registry/item-revision-manifest-v1",
        metadata=False,
    )

    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        resolve_pinned_artifact_member(session, settings, **arguments)  # type: ignore[arg-type]

    resolved = resolve_pinned_artifact_member(
        session,
        settings,
        **arguments,  # type: ignore[arg-type]
        historical_metadata_compatibility=True,
    )
    assert resolved.artifact_type == "item-revision-manifest"
