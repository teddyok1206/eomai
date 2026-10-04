from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import ImageEvaluationArtifactMember
from eom_orchestrator import control_artifact_resolution as resolver


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Engine:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters=None):
        self.calls.append((str(statement), parameters))
        return _Rows([] if str(statement).startswith("SET TRANSACTION") else self.rows)


def _fixture(tmp_path: Path, count=6):
    reads, files, payloads = [], [], []
    for index in range(count):
        payload = f"bounded-fixture-{index}".encode()
        member = f"case-{index}.png"
        (tmp_path / member).write_bytes(payload)
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + "1" * 32,
            artifact_revision_id="rev_" + "2" * 32,
            member_path=member,
            schema_ref="eom://schemas/image-provider/test-png/1.0",
            media_type="image/png",
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        )
        reads.append(resolver.BoundedControlArtifactRead(pointer, len(payload)))
        files.append(
            {
                "file_name": member,
                "sha256": pointer.sha256,
                "bytes": len(payload),
                "schema_ref": pointer.schema_ref,
                "media_type": pointer.media_type,
            }
        )
        payloads.append(payload)
    row = {
        "artifact_id": reads[0].pointer.artifact_id,
        "revision_id": reads[0].pointer.artifact_revision_id,
        "nas_path": str(tmp_path),
        "manifest": {"files": files},
        "artifact_approved": True,
        "revision_approved": True,
    }
    return _Engine([row]), tuple(reads), tuple(payloads)


def test_six_members_use_one_indexed_snapshot_lookup_preserve_order_and_exact_bytes(tmp_path):
    engine, reads, expected = _fixture(tmp_path)
    assert resolver.resolve_control_artifact_members(engine, reads[::-1]) == expected[::-1]
    assert len(engine.calls) == 2
    assert "REPEATABLE READ READ ONLY" in engine.calls[0][0]
    query, parameters = engine.calls[1]
    assert "WHERE (ar.logical_artifact_id, ar.revision_id) IN" in query
    assert parameters == {
        "artifact_id_0": reads[0].pointer.artifact_id,
        "revision_id_0": reads[0].pointer.artifact_revision_id,
    }


@pytest.mark.parametrize(
    "fault",
    [
        "missing-row",
        "artifact-unapproved",
        "revision-unapproved",
        "stale",
        "member-missing",
        "duplicate-member",
        "hash-metadata",
        "media",
        "schema",
        "bytes",
        "too-large",
    ],
)
def test_all_metadata_is_admitted_before_any_binary_read(tmp_path, monkeypatch, fault):
    engine, reads, _ = _fixture(tmp_path)
    row = engine.rows[0]
    last = row["manifest"]["files"][-1]
    if fault == "missing-row":
        engine.rows = []
    elif fault == "artifact-unapproved":
        row["artifact_approved"] = False
    elif fault == "revision-unapproved":
        row["revision_approved"] = False
    elif fault == "stale":
        row["revision_id"] = "rev_" + "f" * 32
    elif fault == "member-missing":
        row["manifest"]["files"].pop()
    elif fault == "duplicate-member":
        row["manifest"]["files"].append(dict(last))
    elif fault == "hash-metadata":
        last["sha256"] = "sha256:" + "f" * 64
    elif fault == "media":
        last["media_type"] = "application/json"
    elif fault == "schema":
        last["schema_ref"] = "eom://schemas/wrong/1.0"
    elif fault == "bytes":
        last["bytes"] = True
    else:
        last["bytes"] += 1
    monkeypatch.setattr(
        resolver,
        "_safe_read_beneath",
        lambda *_a, **_k: pytest.fail("metadata failure materialized bytes"),
    )
    with pytest.raises(resolver.ControlArtifactResolutionError):
        resolver.resolve_control_artifact_members(engine, reads)


@pytest.mark.parametrize("fault", ["duplicate", "bad-bound", "too-many", "traversal"])
def test_invalid_batch_fails_before_database_lookup(tmp_path, fault):
    engine, reads, _ = _fixture(tmp_path, count=1)
    if fault == "duplicate":
        reads = reads + reads
    elif fault == "bad-bound":
        reads = (resolver.BoundedControlArtifactRead(reads[0].pointer, 0),)
    elif fault == "too-many":
        reads = reads * 129
    else:
        reads = (
            resolver.BoundedControlArtifactRead(
                reads[0].pointer.model_copy(update={"member_path": "../escape"}), 10
            ),
        )
    with pytest.raises(resolver.ControlArtifactResolutionError, match="BATCH_INVALID"):
        resolver.resolve_control_artifact_members(engine, reads)
    assert engine.calls == []


@pytest.mark.parametrize("fault", ["hash", "missing", "symlink", "hardlink", "size"])
def test_batch_reads_keep_file_identity_and_bytes_fail_closed(tmp_path, fault):
    engine, reads, _ = _fixture(tmp_path, count=1)
    path = tmp_path / reads[0].pointer.member_path
    if fault == "hash":
        path.write_bytes(b"x" * path.stat().st_size)
    elif fault == "missing":
        path.unlink()
    elif fault in {"symlink", "hardlink"}:
        import os

        origin = tmp_path / "origin"
        path.rename(origin)
        if fault == "symlink":
            path.symlink_to(origin)
        else:
            os.link(origin, path)
    else:
        engine.rows[0]["manifest"]["files"][0]["bytes"] -= 1
    with pytest.raises(resolver.ControlArtifactResolutionError):
        resolver.resolve_control_artifact_members(engine, reads)


def test_large_manifest_is_indexed_once_not_scanned_for_each_requested_member(tmp_path):
    engine, reads, expected = _fixture(tmp_path)

    class CountedMembers(list):
        iterations = 0
        yielded = 0

        def __iter__(self):
            self.iterations += 1
            for member in super().__iter__():
                self.yielded += 1
                yield member

    entries = engine.rows[0]["manifest"]["files"]
    entries.extend({"file_name": f"unrequested-{index}"} for index in range(10_000))
    members = CountedMembers(entries)
    engine.rows[0]["manifest"]["files"] = members
    assert resolver.resolve_control_artifact_members(engine, reads) == expected
    assert members.iterations == 1 and members.yielded == 10_006
    assert len(engine.calls) == 2


@pytest.mark.parametrize("fault", ["member-over-64mib", "aggregate-over-128mib"])
def test_batch_ceiling_is_checked_before_any_database_or_filesystem_access(tmp_path, fault):
    engine, reads, _ = _fixture(tmp_path, count=3)
    bound = 64 * 1024**2 + 1 if fault == "member-over-64mib" else 64 * 1024**2
    reads = tuple(resolver.BoundedControlArtifactRead(read.pointer, bound) for read in reads)
    with pytest.raises(resolver.ControlArtifactResolutionError, match="BATCH_INVALID"):
        resolver.resolve_control_artifact_members(engine, reads)
    assert not engine.calls


def test_lora_size_bound_reuses_existing_reader_without_allocating_a_64mib_fixture(tmp_path):
    engine, reads, expected = _fixture(tmp_path, count=1)
    bound = (resolver.BoundedControlArtifactRead(reads[0].pointer, 64 * 1024**2),)
    assert resolver.resolve_control_artifact_members(engine, bound) == expected
    assert len(engine.calls) == 2
