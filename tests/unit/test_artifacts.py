from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_orchestrator.artifacts import (
    commit_artifact,
    commit_file_set_artifact,
    stage_artifact,
    stage_file_set_artifact,
)
from eom_orchestrator.errors import PlatformError
from eom_protocol import ArtifactSpec, ErrorCode, ResultContent, WorkerResult

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


def test_file_set_artifact_commits_and_verifies_every_file(tmp_path: Path) -> None:
    primary = tmp_path / "document.hwpx"
    report = tmp_path / "structural.json"
    primary.write_bytes(b"synthetic-hwpx")
    report.write_text('{"status":"PASS"}', encoding="utf-8")
    staged = stage_file_set_artifact(
        files={"placeholder_item_combined.hwpx": primary, "reports/structural.json": report},
        primary_file="placeholder_item_combined.hwpx",
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        artifact_type="hwpx-build",
        staging=tmp_path / "staged",
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    nas_root = tmp_path / "nas"
    nas_root.mkdir()
    final = commit_file_set_artifact(staged, nas_root)
    assert (final / "placeholder_item_combined.hwpx").read_bytes() == b"synthetic-hwpx"
    assert (final / "reports/structural.json").is_file()
    assert commit_file_set_artifact(staged, nas_root) == final
    (final / "reports/structural.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(PlatformError, match="checksum"):
        commit_file_set_artifact(staged, nas_root)


def test_file_set_artifact_rejects_existing_revision_symlink(tmp_path: Path) -> None:
    source = tmp_path / "document.md"
    source.write_text("# Proposal\n", encoding="utf-8")
    staged = stage_file_set_artifact(
        files={"document.md": source},
        primary_file="document.md",
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        artifact_type="knowledge-analysis-proposal",
        staging=tmp_path / "staged-symlink-revision",
    )
    nas_root = tmp_path / "nas-symlink-revision"
    nas_root.mkdir()
    final = commit_file_set_artifact(staged, nas_root)
    outside = tmp_path / "outside-revision"
    final.rename(outside)
    final.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PlatformError, match="invalid artifact revision path"):
        commit_file_set_artifact(staged, nas_root)


def test_file_set_artifact_maps_logical_directory_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "document.md"
    source.write_text("# Proposal\n", encoding="utf-8")
    staged = stage_file_set_artifact(
        files={"document.md": source},
        primary_file="document.md",
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        artifact_type="knowledge-analysis-proposal",
        staging=tmp_path / "staged-permission-error",
    )
    nas_root = tmp_path / "nas-permission-error"
    nas_root.mkdir()
    blocked = nas_root / ARTIFACT_ID
    original_mkdir = Path.mkdir

    def deny_logical_directory(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == blocked:
            raise PermissionError("synthetic permission denial")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", deny_logical_directory)

    with pytest.raises(PlatformError) as failure:
        commit_file_set_artifact(staged, nas_root)
    assert failure.value.code is ErrorCode.ARTIFACT_COMMIT_FAILED
    assert str(failure.value) == "NAS artifact commit failed"


def test_structured_artifact_maps_logical_directory_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = stage_artifact(
        result=_result(), staging=tmp_path / "structured-permission-staging", worker_slot="01"
    )
    nas_root = tmp_path / "structured-permission-nas"
    nas_root.mkdir()
    blocked = nas_root / ARTIFACT_ID
    original_mkdir = Path.mkdir

    def deny_logical_directory(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == blocked:
            raise PermissionError("synthetic permission denial")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", deny_logical_directory)

    with pytest.raises(PlatformError) as failure:
        commit_artifact(staged, nas_root)
    assert failure.value.code is ErrorCode.ARTIFACT_COMMIT_FAILED
    assert str(failure.value) == "NAS artifact commit failed"


def test_file_set_artifact_records_exact_typed_member_metadata(tmp_path: Path) -> None:
    source = tmp_path / "guidance.md"
    source.write_text("# Reviewed guidance\n", encoding="utf-8")
    staged = stage_file_set_artifact(
        files={"guidance.md": source},
        primary_file="guidance.md",
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        artifact_type="control_markdown",
        staging=tmp_path / "typed-staged",
        file_metadata={
            "guidance.md": {
                "schema_ref": "eom://schemas/workflow/instruction-member/1.0",
                "media_type": "text/markdown",
            }
        },
    )
    assert staged.manifest["files"] == [
        {
            "file_name": "guidance.md",
            "sha256": staged.primary_hash,
            "bytes": staged.primary_bytes,
            "schema_ref": "eom://schemas/workflow/instruction-member/1.0",
            "media_type": "text/markdown",
        }
    ]
    with pytest.raises(PlatformError, match="metadata"):
        stage_file_set_artifact(
            files={"guidance.md": source},
            primary_file="guidance.md",
            job_id=JOB_ID,
            logical_artifact_id=ARTIFACT_ID,
            revision_id=REVISION_ID,
            artifact_type="control_markdown",
            staging=tmp_path / "mismatched-metadata",
            file_metadata={},
        )


def test_file_set_artifact_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"content")
    with pytest.raises(PlatformError, match="unsafe"):
        stage_file_set_artifact(
            files={"../escape": source},
            primary_file="../escape",
            job_id=JOB_ID,
            logical_artifact_id=ARTIFACT_ID,
            revision_id=REVISION_ID,
            artifact_type="hwpx-build",
            staging=tmp_path / "traversal",
        )
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(PlatformError, match="regular"):
        stage_file_set_artifact(
            files={"document.hwpx": link},
            primary_file="document.hwpx",
            job_id=JOB_ID,
            logical_artifact_id=ARTIFACT_ID,
            revision_id=REVISION_ID,
            artifact_type="hwpx-build",
            staging=tmp_path / "symlink",
        )
