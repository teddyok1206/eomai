from __future__ import annotations

import errno
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TypeVar

import pytest
from eom_catalog_service import pinned_artifact_resolution as artifact_module
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
    assert resolved.producer_job_id == "job_" + "3" * 32


@pytest.mark.parametrize(
    "reason",
    [
        "HASH",
        "BYTES_TYPE",
        "NEGATIVE_BYTES",
        "EMPTY",
        "SIZE_LIMIT",
        "SCHEMA_MEDIA",
        "PRIMARY_HASH",
        "PRIMARY_BYTES",
    ],
)
def test_descriptor_failures_keep_closed_checks_and_report_safe_reason(tmp_path, reason):
    session, settings, arguments = _fixture(tmp_path)
    revision = session.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    entry = revision.manifest["files"][0]
    if reason == "HASH":
        arguments["sha256"] = "sha256:" + "f" * 64
    elif reason in {"BYTES_TYPE", "NEGATIVE_BYTES", "EMPTY"}:
        entry["bytes"] = {"BYTES_TYPE": "10", "NEGATIVE_BYTES": -1, "EMPTY": 0}[reason]
    elif reason == "SIZE_LIMIT":
        arguments["max_bytes"] = 1
    elif reason == "SCHEMA_MEDIA":
        arguments["schema_ref"] = "eom://schemas/fixture/different/1.0"
    elif reason == "PRIMARY_HASH":
        revision.content_hash = "sha256:" + "f" * 64
    else:
        revision.content_bytes += 1
    revision.manifest_hash = content_sha256(revision.manifest)
    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs") as caught:
        resolve_pinned_artifact_member(session, settings, **arguments)
    assert caught.value.code == "PINNED_ARTIFACT_DESCRIPTOR_" + reason
    assert caught.value.artifact_id == arguments["artifact_id"]
    assert caught.value.artifact_revision_id == arguments["artifact_revision_id"]


def test_descriptor_reason_is_a_closed_code_not_free_text():
    error = PinnedArtifactResolutionError("safe", descriptor_reason="SECRET_VALUE")
    assert error.code is None


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


def _member_target(session: _Session, arguments: dict[str, object]) -> Path:
    revision = session.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    return Path(revision.nas_path) / str(arguments["member_path"])


def _observe_member_io(monkeypatch: pytest.MonkeyPatch, target: Path):
    opened: list[int] = []
    chunks: list[bytes] = []
    closed: list[int] = []
    original_open, original_read = os.open, os.read
    original_close, original_fstat = os.close, os.fstat

    def open_member(path, flags, *args, **kwargs):
        if Path(path) == target:
            assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
        descriptor = original_open(path, flags, *args, **kwargs)
        if Path(path) == target:
            opened.append(descriptor)
        return descriptor

    def read_member(descriptor, size):
        value = original_read(descriptor, size)
        if descriptor in opened:
            chunks.append(value)
        return value

    def close_member(descriptor):
        original_close(descriptor)
        if descriptor in opened:
            closed.append(descriptor)

    monkeypatch.setattr(artifact_module.os, "open", open_member)
    monkeypatch.setattr(artifact_module.os, "read", read_member)
    monkeypatch.setattr(artifact_module.os, "close", close_member)
    return opened, chunks, closed, original_fstat


def _assert_member_descriptors_closed(opened, closed, original_fstat) -> None:
    assert closed == opened
    for descriptor in opened:
        with pytest.raises(OSError) as caught:
            original_fstat(descriptor)
        assert caught.value.errno == errno.EBADF


def _changed_stat(value: os.stat_result, field: str) -> SimpleNamespace:
    fields = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
    fields[field] += 1
    return SimpleNamespace(**fields)


def test_cold_member_consumes_one_bounded_descriptor_stream(tmp_path, monkeypatch):
    payload = b"x" * (2 * 64 * 1024 + 19)
    session, settings, arguments = _fixture(tmp_path, payload=payload)
    arguments["max_bytes"] = len(payload)
    target = _member_target(session, arguments)
    opened, chunks, closed, original_fstat = _observe_member_io(monkeypatch, target)
    original_path_open = Path.open

    def no_second_path_stream(path, *args, **kwargs):
        assert path != target, "the member must not have a separate preliminary hash stream"
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_second_path_stream)
    resolved = resolve_pinned_artifact_member(session, settings, **arguments)

    assert resolved.payload == payload
    assert len(opened) == 1
    assert b"".join(chunks) == payload
    assert sum(map(len, chunks)) == len(payload)
    assert all(len(chunk) <= 64 * 1024 for chunk in chunks)
    _assert_member_descriptors_closed(opened, closed, original_fstat)


def test_same_size_physical_tamper_is_rejected_by_payload_hash(tmp_path, monkeypatch):
    session, settings, arguments = _fixture(tmp_path)
    target = _member_target(session, arguments)
    original = target.read_bytes()
    tampered = original.replace(b"1", b"2")
    assert len(tampered) == len(original) and tampered != original
    target.write_bytes(tampered)
    opened, chunks, closed, original_fstat = _observe_member_io(monkeypatch, target)

    with pytest.raises(PinnedArtifactResolutionError, match="changed while reading"):
        resolve_pinned_artifact_member(session, settings, **arguments)

    assert len(opened) == 1 and b"".join(chunks) == tampered
    _assert_member_descriptors_closed(opened, closed, original_fstat)


@pytest.mark.parametrize("replacement", ("inode", "symlink", "fifo"))
def test_member_replacement_at_open_is_rejected_before_read(tmp_path, monkeypatch, replacement):
    session, settings, arguments = _fixture(tmp_path)
    target = _member_target(session, arguments)
    substitute = target.with_name("replacement.json")
    substitute.write_bytes(target.read_bytes())
    opened, chunks, closed, original_fstat = _observe_member_io(monkeypatch, target)
    observed_open = artifact_module.os.open
    raced = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal raced
        if Path(path) == target:
            assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
            assert not raced
            raced = True
            if replacement == "inode":
                os.replace(substitute, target)
            else:
                target.unlink()
                if replacement == "symlink":
                    target.symlink_to(substitute)
                else:
                    os.mkfifo(target)
        return observed_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(artifact_module.os, "open", replace_before_open)
    with pytest.raises(PinnedArtifactResolutionError, match=r"materialization|changed"):
        resolve_pinned_artifact_member(session, settings, **arguments)

    assert raced and not chunks
    assert len(opened) == (0 if replacement == "symlink" else 1)
    _assert_member_descriptors_closed(opened, closed, original_fstat)


@pytest.mark.parametrize(
    "field",
    (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_uid",
        "st_gid",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    ),
)
def test_member_full_epoch_drift_during_read_is_rejected(tmp_path, monkeypatch, field):
    session, settings, arguments = _fixture(tmp_path)
    target = _member_target(session, arguments)
    opened, chunks, closed, original_fstat = _observe_member_io(monkeypatch, target)
    member_stats = 0

    def drift_after_read(descriptor):
        nonlocal member_stats
        value = original_fstat(descriptor)
        if descriptor in opened:
            member_stats += 1
            if member_stats == 2:
                return _changed_stat(value, field)
        return value

    monkeypatch.setattr(artifact_module.os, "fstat", drift_after_read)
    with pytest.raises(PinnedArtifactResolutionError, match="changed while reading"):
        resolve_pinned_artifact_member(session, settings, **arguments)

    assert member_stats == 2 and b"".join(chunks) == b'{"value":1}'
    _assert_member_descriptors_closed(opened, closed, original_fstat)


@pytest.mark.parametrize("change", ("removed", "replaced", "hardlink"))
def test_member_final_path_change_is_rejected_and_descriptor_closed(tmp_path, monkeypatch, change):
    session, settings, arguments = _fixture(tmp_path)
    target = _member_target(session, arguments)
    substitute = target.with_name("replacement.json")
    substitute.write_bytes(target.read_bytes())
    opened, chunks, closed, original_fstat = _observe_member_io(monkeypatch, target)
    original_lstat = Path.lstat
    changed = False

    def change_final_path(path, *args, **kwargs):
        nonlocal changed
        if path == target and chunks and not changed:
            changed = True
            if change == "removed":
                target.unlink()
            elif change == "replaced":
                os.replace(substitute, target)
            else:
                os.link(target, target.with_name("new-link.json"))
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", change_final_path)
    with pytest.raises(PinnedArtifactResolutionError, match=r"materialization|changed"):
        resolve_pinned_artifact_member(session, settings, **arguments)

    assert changed and len(opened) == 1 and b"".join(chunks) == b'{"value":1}'
    _assert_member_descriptors_closed(opened, closed, original_fstat)


def test_member_atime_only_change_is_not_identity_drift(tmp_path, monkeypatch):
    session, settings, arguments = _fixture(tmp_path)
    target = _member_target(session, arguments)
    opened, chunks, closed, original_fstat = _observe_member_io(monkeypatch, target)
    changed = False

    def access_time_only(descriptor):
        nonlocal changed
        value = original_fstat(descriptor)
        if descriptor in opened and chunks:
            changed = True
            return _changed_stat(value, "st_atime_ns")
        return value

    monkeypatch.setattr(artifact_module.os, "fstat", access_time_only)
    resolved = resolve_pinned_artifact_member(session, settings, **arguments)

    assert changed and resolved.payload == b'{"value":1}' and len(opened) == 1
    _assert_member_descriptors_closed(opened, closed, original_fstat)


def test_member_read_error_closes_open_descriptor(tmp_path, monkeypatch):
    session, settings, arguments = _fixture(tmp_path)
    target = _member_target(session, arguments)
    opened, chunks, closed, original_fstat = _observe_member_io(monkeypatch, target)
    observed_read = artifact_module.os.read

    def fail_member_read(descriptor, size):
        if descriptor in opened:
            raise OSError(errno.EIO, "synthetic local member read failure")
        return observed_read(descriptor, size)

    monkeypatch.setattr(artifact_module.os, "read", fail_member_read)
    with pytest.raises(PinnedArtifactResolutionError, match="materialization does not resolve"):
        resolve_pinned_artifact_member(session, settings, **arguments)

    assert len(opened) == 1 and not chunks
    _assert_member_descriptors_closed(opened, closed, original_fstat)
