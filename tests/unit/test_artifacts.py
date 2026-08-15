from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_orchestrator.artifacts import commit_artifact, stage_artifact
from eom_orchestrator.errors import PlatformError
from eom_protocol import ArtifactSpec, ResultContent, WorkerResult

JOB_ID = "job_0123456789abcdef0123456789abcdef"
ARTIFACT_ID = "artifact_0123456789abcdef0123456789abcdef"
REVISION_ID = "rev_0123456789abcdef0123456789abcdef"


def _result() -> WorkerResult:
    return WorkerResult(
        job_id=JOB_ID,
        message="EOM_PLATFORM_SMOKE_TEST_OK",
        artifact=ArtifactSpec(logical_artifact_id=ARTIFACT_ID, revision_id=REVISION_ID),
        content=ResultContent(message="EOM_PLATFORM_SMOKE_TEST_OK"),
        completed_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def test_stage_and_immutable_commit(tmp_path: Path) -> None:
    staged = stage_artifact(result=_result(), staging=tmp_path / "staging", worker_slot="01")
    nas_root = tmp_path / "nas"
    nas_root.mkdir()
    final = commit_artifact(staged, nas_root)
    assert final == nas_root / ARTIFACT_ID / REVISION_ID
    assert (final / "result.json").is_file()
    assert (final / "manifest.json").is_file()
    assert commit_artifact(staged, nas_root) == final


def test_existing_revision_with_different_hash_is_rejected(tmp_path: Path) -> None:
    staged = stage_artifact(result=_result(), staging=tmp_path / "staging", worker_slot="01")
    nas_root = tmp_path / "nas"
    nas_root.mkdir()
    final = commit_artifact(staged, nas_root)
    (final / "result.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(PlatformError, match="checksum"):
        commit_artifact(staged, nas_root)


def test_logical_artifact_symlink_is_rejected(tmp_path: Path) -> None:
    staged = stage_artifact(result=_result(), staging=tmp_path / "staging", worker_slot="01")
    nas_root = tmp_path / "nas"
    nas_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (nas_root / ARTIFACT_ID).symlink_to(outside, target_is_directory=True)
    with pytest.raises(PlatformError, match="invalid logical artifact path"):
        commit_artifact(staged, nas_root)
