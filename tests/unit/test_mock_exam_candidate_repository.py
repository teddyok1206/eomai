from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_service.mock_exam_candidate_repository import (
    MockExamCandidateRepository,
    MockExamCandidateResolutionError,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord


def _artifact_fixture(
    root: Path,
    *,
    payload: bytes = b"{}",
) -> tuple[MockExamCandidateRepository, ArtifactRecord, ArtifactRevisionRecord, Path]:
    artifact_id = "artifact_" + "1" * 32
    revision_id = "rev_" + "2" * 32
    job_id = "job_" + "3" * 32
    digest = sha256_bytes(payload)
    storage = root / artifact_id / revision_id
    storage.mkdir(parents=True)
    member = storage / "member.json"
    member.write_bytes(payload)
    manifest = {
        "logical_artifact_id": artifact_id,
        "revision_id": revision_id,
        "primary_file": "member.json",
        "files": [
            {
                "file_name": "member.json",
                "bytes": len(payload),
                "sha256": digest,
                "media_type": "application/json",
                "schema_ref": "eom://schemas/test/1.0",
            }
        ],
    }
    artifact = ArtifactRecord(
        logical_artifact_id=artifact_id,
        job_id=job_id,
        artifact_type="test-evidence",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=revision_id,
        logical_artifact_id=artifact_id,
        job_id=job_id,
        content_hash=digest,
        manifest_hash=content_sha256(manifest),
        content_bytes=len(payload),
        nas_path=str(storage),
        manifest=manifest,
        result={},
        approved=True,
    )
    return (
        MockExamCandidateRepository(CatalogSettings(nas_artifact_root=root)),
        artifact,
        revision,
        member,
    )


def _read(
    repository: MockExamCandidateRepository,
    artifact: ArtifactRecord,
    revision: ArtifactRevisionRecord,
) -> bytes:
    return repository._read_member(
        artifact,
        revision,
        artifact_id=artifact.logical_artifact_id,
        revision_id=revision.revision_id,
        artifact_type="test-evidence",
        member_path="member.json",
        expected_sha256=revision.content_hash,
        max_bytes=1024,
        expected_media_type="application/json",
        expected_schema_ref="eom://schemas/test/1.0",
    )


def test_candidate_member_resolution_is_hash_pinned_and_same_file_descriptor(
    tmp_path: Path,
) -> None:
    repository, artifact, revision, _member = _artifact_fixture(tmp_path)

    assert _read(repository, artifact, revision) == b"{}"


@pytest.mark.parametrize("failure", ["missing", "stale", "hash", "duplicate", "symlink"])
def test_candidate_member_resolution_rejects_invalid_or_ambiguous_pointers(
    tmp_path: Path,
    failure: str,
) -> None:
    repository, artifact, revision, member = _artifact_fixture(tmp_path)
    if failure == "missing":
        artifact.approved = False
    elif failure == "stale":
        revision.logical_artifact_id = "artifact_" + "4" * 32
    elif failure == "hash":
        member.write_bytes(b"[]")
    elif failure == "duplicate":
        revision.manifest = {
            **revision.manifest,
            "files": [*revision.manifest["files"], *revision.manifest["files"]],
        }
        revision.manifest_hash = content_sha256(revision.manifest)
    else:
        target = tmp_path / "untrusted.json"
        target.write_bytes(b"{}")
        member.unlink()
        member.symlink_to(target)

    with pytest.raises(MockExamCandidateResolutionError):
        _read(repository, artifact, revision)
