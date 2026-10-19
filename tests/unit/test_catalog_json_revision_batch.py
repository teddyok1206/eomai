"""Disposable SQLite metadata and local files; no runtime NAS or live source authority."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_service import artifacts as artifact_module
from eom_catalog_service.artifacts import (
    MAX_JSON_REVISION_BATCH,
    MAX_JSON_REVISION_BATCH_BYTES,
    CatalogArtifactService,
    CatalogJsonRevisionRequest,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, Base
from eom_protocol.models import ArtifactManifest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session


@compiles(JSONB, "sqlite")
def _sqlite_json(_type: JSONB, _compiler: object, **_kwargs: object) -> str:
    return "JSON"


@pytest.fixture
def case(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[ArtifactRecord.__table__, ArtifactRevisionRecord.__table__]
    )
    root = tmp_path / "nas"
    root.mkdir()
    service = CatalogArtifactService(engine, CatalogSettings(nas_artifact_root=root))
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    def add(
        index: int = 1,
        *,
        kind: str = "legacy",
        payload: bytes | None = None,
        microsecond: int = 0,
        metadata: bool = True,
    ) -> tuple[CatalogJsonRevisionRequest, Path]:
        artifact_id = f"artifact_{index:032x}"
        revision_id = f"rev_{index:032x}"
        job_id = f"job_{index:032x}"
        raw = payload if payload is not None else canonical_json_bytes({"sequence": index})
        digest = sha256_bytes(raw)
        directory = root / artifact_id / revision_id
        directory.mkdir(parents=True)
        target = directory / "result.json"
        target.write_bytes(raw)
        if kind == "legacy":
            typed = ArtifactManifest(
                job_id=job_id,
                logical_artifact_id=artifact_id,
                revision_id=revision_id,
                content_hash=digest,
                content_bytes=len(raw),
                worker_slot="01",
                created_at=datetime(2026, 10, 19, microsecond=microsecond, tzinfo=UTC),
            )
            manifest = typed.model_dump(mode="json")
            manifest_hash = content_sha256(typed)
        else:
            member: dict[str, object] = {
                "file_name": "result.json",
                "sha256": digest,
                "bytes": len(raw),
            }
            if metadata:
                member.update(media_type="application/json", schema_ref="fixture-result@1.0")
            manifest = {
                "manifest_version": "catalog-file-set/1.0",
                "job_id": job_id,
                "logical_artifact_id": artifact_id,
                "revision_id": revision_id,
                "artifact_type": "fixture",
                "primary_file": "result.json",
                "content_hash": digest,
                "content_bytes": len(raw),
                "files": [member],
                "created_at": "2026-10-19T00:00:00Z",
            }
            manifest_hash = content_sha256(manifest)
        with Session(engine) as session:
            session.add(
                ArtifactRecord(
                    logical_artifact_id=artifact_id,
                    job_id=job_id,
                    artifact_type="fixture",
                    approved=True,
                )
            )
            session.flush()
            session.add(
                ArtifactRevisionRecord(
                    revision_id=revision_id,
                    logical_artifact_id=artifact_id,
                    job_id=job_id,
                    content_hash=digest,
                    manifest_hash=manifest_hash,
                    content_bytes=len(raw),
                    nas_path=str(directory),
                    manifest=manifest,
                    result={},
                    approved=True,
                )
            )
            session.commit()
        return CatalogJsonRevisionRequest(artifact_id, revision_id, digest), target

    yield service, add, engine, statements
    engine.dispose()


def _change(case, request, *, revision=None, logical=None):
    engine = case[2]
    with Session(engine) as session:
        if revision is not None:
            record = session.get(ArtifactRevisionRecord, request.revision_id)
            for name, value in revision.items():
                setattr(record, name, value)
        if logical is not None:
            record = session.get(ArtifactRecord, request.artifact_id)
            for name, value in logical.items():
                setattr(record, name, value)
        session.commit()


@pytest.mark.parametrize("kind,metadata", (("legacy", True), ("fileset", True), ("fileset", False)))
@pytest.mark.parametrize("microsecond", (0, 123456))
def test_legacy_and_file_set_exact_primary_round_trip(case, kind, metadata, microsecond):
    service, add, _, statements = case
    request, _ = add(kind=kind, metadata=metadata, microsecond=microsecond)
    statements.clear()
    assert service.load_json_revisions((request,)) == {request.revision_id: {"sequence": 1}}
    assert len(statements) == 1
    assert "JOIN artifacts" in statements[0]
    assert "artifact_revisions.revision_id IN" in statements[0]
    assert service.load_json_revision(
        artifact_id=request.artifact_id,
        revision_id=request.revision_id,
        content_hash=request.content_hash,
    ) == {"sequence": 1}


def test_batch_545_uses_one_current_metadata_query_and_no_lazy_relationship_loads(case):
    service, add, _, statements = case
    requests = tuple(add(index)[0] for index in range(1, 546))
    statements.clear()
    result = service.load_json_revisions(tuple(reversed(requests)))
    assert tuple(result) == tuple(request.revision_id for request in reversed(requests))
    assert len(result) == 545
    assert result[requests[0].revision_id] == {"sequence": 1}
    assert len(statements) == 1
    assert "artifact_revisions.revision_id IN" in statements[0]


def test_single_entry_delegates_the_exact_same_bulk_boundary(case, monkeypatch):
    service, add, _, _ = case
    request, _ = add()
    calls = []
    original = service.load_json_revisions

    def bulk(requests):
        calls.append(requests)
        return original(requests)

    monkeypatch.setattr(service, "load_json_revisions", bulk)
    service.load_json_revision(
        artifact_id=request.artifact_id,
        revision_id=request.revision_id,
        content_hash=request.content_hash,
        max_bytes=123,
    )
    assert calls == [(replace(request, max_bytes=123),)]


def test_empty_batch_has_no_query_or_filesystem_read(case):
    service, _, _, statements = case
    assert service.load_json_revisions(()) == {}
    assert statements == []


@pytest.mark.parametrize("fault", ("list", "duplicate", "conflicting", "oversized", "forged"))
def test_bad_batch_fails_before_query_or_materialization(case, fault):
    service, add, _, statements = case
    request, _ = add()
    if fault == "list":
        requests = [request]
    elif fault == "duplicate":
        requests = (request, request)
    elif fault == "conflicting":
        requests = (request, replace(request, content_hash="sha256:" + "f" * 64))
    elif fault == "oversized":
        requests = (request,) * (MAX_JSON_REVISION_BATCH + 1)
    else:
        forged = replace(request)
        object.__setattr__(forged, "max_bytes", True)
        requests = (forged,)
    statements.clear()
    with pytest.raises(ValueError):
        service.load_json_revisions(requests)
    assert statements == []


@pytest.mark.parametrize(
    "field,value",
    (
        ("artifact_id", "bad"),
        ("revision_id", "bad"),
        ("content_hash", "bad"),
        ("max_bytes", 0),
        ("max_bytes", True),
        ("max_bytes", 1.0),
    ),
)
def test_request_preserves_exact_ids_hash_and_integer_budget(field, value):
    body = {
        "artifact_id": "artifact_" + "1" * 32,
        "revision_id": "rev_" + "2" * 32,
        "content_hash": "sha256:" + "3" * 64,
        "max_bytes": 1024,
    }
    body[field] = value
    with pytest.raises(ValueError):
        CatalogJsonRevisionRequest(**body)


@pytest.mark.parametrize(
    "fault", ("missing", "artifact", "hash", "revision_approval", "logical_approval")
)
def test_current_missing_stale_hash_and_revoked_metadata_never_falls_back(case, fault):
    service, add, _, _ = case
    request, _ = add()
    assert service.load_json_revisions((request,))
    if fault == "missing":
        request = replace(request, revision_id="rev_" + "f" * 32)
    elif fault == "artifact":
        request = replace(request, artifact_id="artifact_" + "f" * 32)
    elif fault == "hash":
        request = replace(request, content_hash="sha256:" + "f" * 64)
    elif fault == "revision_approval":
        _change(case, request, revision={"approved": False})
    else:
        _change(case, request, logical={"approved": False})
    with pytest.raises(ValueError):
        service.load_json_revisions((request,))


@pytest.mark.parametrize(
    "fault",
    (
        "manifest_hash",
        "header_artifact",
        "header_revision",
        "header_job",
        "header_hash",
        "header_size",
        "primary",
        "duplicate",
        "entry_hash",
        "entry_size",
        "entry_media",
        "boolean_size",
    ),
)
def test_fileset_header_and_exact_primary_are_revalidated_before_reads(case, fault, monkeypatch):
    service, add, engine, _ = case
    request, _ = add(kind="fileset")
    with Session(engine) as session:
        row = session.get(ArtifactRevisionRecord, request.revision_id)
        body = dict(row.manifest)
        body["files"] = [dict(entry) for entry in body["files"]]
        if fault == "header_artifact":
            body["logical_artifact_id"] = "artifact_" + "f" * 32
        elif fault == "header_revision":
            body["revision_id"] = "rev_" + "f" * 32
        elif fault == "header_job":
            body["job_id"] = "job_" + "f" * 32
        elif fault == "header_hash":
            body["content_hash"] = "sha256:" + "f" * 64
        elif fault == "header_size":
            body["content_bytes"] += 1
        elif fault == "primary":
            body["primary_file"] = "other.json"
        elif fault == "duplicate":
            body["files"] *= 2
        elif fault == "entry_hash":
            body["files"][0]["sha256"] = "sha256:" + "f" * 64
        elif fault == "entry_size":
            body["files"][0]["bytes"] += 1
        elif fault == "entry_media":
            body["files"][0]["media_type"] = "image/png"
        elif fault == "boolean_size":
            body["files"][0]["bytes"] = True
        row.manifest = body
        row.manifest_hash = (
            "sha256:" + "f" * 64 if fault == "manifest_hash" else content_sha256(body)
        )
        session.commit()
    calls = []
    monkeypatch.setattr(
        artifact_module, "_read_json_revision_payload", lambda *_: calls.append(True)
    )
    with pytest.raises(ValueError):
        service.load_json_revisions((request,))
    assert calls == []


def test_legacy_manifest_uses_the_original_typed_timestamp_hash(case):
    service, add, engine, _ = case
    request, _ = add()
    with Session(engine) as session:
        row = session.get(ArtifactRevisionRecord, request.revision_id)
        assert content_sha256(row.manifest) != row.manifest_hash
        row.manifest_hash = content_sha256(row.manifest)
        session.commit()
    with pytest.raises(ValueError, match="manifest"):
        service.load_json_revisions((request,))


def test_aggregate_budget_is_static_and_checked_before_any_member_read(case, monkeypatch):
    service, add, engine, _ = case
    requests = tuple(add(index, kind="fileset")[0] for index in (1, 2))
    declared = MAX_JSON_REVISION_BATCH_BYTES // 2 + 1
    with Session(engine) as session:
        for row in session.scalars(select(ArtifactRevisionRecord)):
            body = dict(row.manifest)
            body["files"] = [dict(entry) for entry in body["files"]]
            body["content_bytes"] = declared
            body["files"][0]["bytes"] = declared
            row.content_bytes = declared
            row.manifest = body
            row.manifest_hash = content_sha256(body)
        session.commit()
    calls = []
    monkeypatch.setattr(
        artifact_module, "_read_json_revision_payload", lambda *_: calls.append(True)
    )
    with pytest.raises(ValueError, match=r"^CATALOG_JSON_BATCH_BUDGET_EXCEEDED$"):
        service.load_json_revisions(tuple(replace(value, max_bytes=declared) for value in requests))
    assert calls == []


@pytest.mark.parametrize(
    "fault", ("missing", "hash", "oversized", "directory", "hardlink", "symlink")
)
def test_bad_physical_member_cannot_be_used_as_json(case, tmp_path, fault):
    service, add, _, _ = case
    request, target = add()
    if fault == "missing":
        target.unlink()
    elif fault == "hash":
        target.write_bytes(b'{"sequence":2}')
    elif fault == "oversized":
        request = replace(request, max_bytes=1)
    elif fault == "directory":
        target.unlink()
        target.mkdir()
    elif fault == "hardlink":
        os.link(target, target.with_name("second.json"))
    else:
        original = target.read_bytes()
        target.unlink()
        outside = tmp_path / "outside.json"
        outside.write_bytes(original)
        target.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        service.load_json_revisions((request,))


@pytest.mark.parametrize("ancestor", ("revision", "artifact"))
def test_internal_directory_symlinks_are_rejected_even_for_the_same_bytes(case, ancestor):
    service, add, _, _ = case
    request, target = add()
    source = target.parent if ancestor == "revision" else target.parent.parent
    moved = source.with_name(source.name + "-moved")
    source.rename(moved)
    source.symlink_to(moved, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        service.load_json_revisions((request,))


@pytest.mark.parametrize("outside", (True, False))
def test_nas_path_escape_and_traversal_are_rejected(case, outside):
    service, add, _, _ = case
    request, target = add()
    path = (
        str(target.parents[3] / "other")
        if outside
        else str(target.parent / ".." / target.parent.name)
    )
    _change(case, request, revision={"nas_path": path})
    with pytest.raises((ValueError, OSError)):
        service.load_json_revisions((request,))


def test_same_bytes_replacement_between_stat_and_open_is_rejected(case, monkeypatch):
    service, add, _, _ = case
    request, target = add()
    original_open = artifact_module.os.open

    def racing_open(path, flags, *args, **kwargs):
        if path == "result.json":
            replacement = target.with_name("replacement.json")
            replacement.write_bytes(target.read_bytes())
            replacement.replace(target)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(artifact_module.os, "open", racing_open)
    with pytest.raises(ValueError, match="materialization"):
        service.load_json_revisions((request,))


@pytest.mark.parametrize("fault", ("rewrite", "same_bytes", "path_replace", "parent_replace"))
def test_same_fd_payload_and_path_epochs_survive_the_complete_read_or_fail(
    case, monkeypatch, fault
):
    service, add, _, _ = case
    request, target = add()
    original_read = artifact_module.os.read
    old_stat = target.stat()
    changed = False

    def racing_read(descriptor, size):
        nonlocal changed
        raw = original_read(descriptor, size)
        if raw and not changed:
            changed = True
            if fault == "rewrite":
                target.write_bytes(b'{"sequence":2}')
            elif fault == "same_bytes":
                target.write_bytes(raw)
                os.utime(target, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            elif fault == "path_replace":
                replacement = target.with_name("replacement.json")
                replacement.write_bytes(raw)
                replacement.replace(target)
            else:
                old_root = target.parent.with_name(target.parent.name + "-old")
                target.parent.rename(old_root)
                target.parent.mkdir()
                target.write_bytes(raw)
        return raw

    monkeypatch.setattr(artifact_module.os, "read", racing_read)
    with pytest.raises((ValueError, OSError)):
        service.load_json_revisions((request,))
    assert changed


@pytest.mark.parametrize("raw", (b"[]", b"null", b"not json", b"\xff", b'\xff{"sequence":1}'))
def test_only_utf8_json_objects_are_returned(case, raw):
    service, add, _, _ = case
    request, _ = add(payload=raw)
    with pytest.raises((ValueError, UnicodeError)):
        service.load_json_revisions((request,))


def test_payload_is_read_once_not_prehashed_then_reopened(case, monkeypatch):
    service, add, _, _ = case
    request, target = add()
    original_open, original_read = artifact_module.os.open, artifact_module.os.read
    opened = []
    payloads = []
    descriptors = set()

    def record_open(path, flags, *args, **kwargs):
        descriptor = original_open(path, flags, *args, **kwargs)
        if path == "result.json":
            opened.append((flags, kwargs.get("dir_fd")))
            descriptors.add(descriptor)
        return descriptor

    def record_read(descriptor, size):
        raw = original_read(descriptor, size)
        if descriptor in descriptors:
            payloads.append(raw)
        return raw

    monkeypatch.setattr(artifact_module.os, "open", record_open)
    monkeypatch.setattr(artifact_module.os, "read", record_read)
    assert service.load_json_revisions((request,)) == {request.revision_id: {"sequence": 1}}
    assert len(opened) == 1
    assert opened[0][0] & os.O_NOFOLLOW and opened[0][0] & os.O_NONBLOCK
    assert opened[0][1] is not None
    assert b"".join(payloads) == target.read_bytes()
