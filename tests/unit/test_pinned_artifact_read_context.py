"""Synthetic root-Session metadata/temporary-file checks, no DB or actual NAS access."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service import pinned_artifact_resolution as module
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy.orm import Session

from tests.unit.test_pinned_artifact_resolution import _fixture, _primary_key


def member_stream_counts(monkeypatch: pytest.MonkeyPatch, paths: set[Path]) -> SimpleNamespace:
    """Count actual member FDs/returned bytes, ignoring unrelated Python/fixture IO."""
    opened: Counter[Path] = Counter()
    read_calls: Counter[Path] = Counter()
    payload_chunks: Counter[Path] = Counter()
    payload_bytes: Counter[Path] = Counter()
    closed: Counter[Path] = Counter()
    active: dict[int, Path] = {}
    actual_open, actual_read, actual_close = module.os.open, module.os.read, module.os.close
    actual_path_open = Path.open

    def open_stream(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        # A preliminary Path.open hash would bypass the counted bounded FD stream.
        # Fixture writes remain allowed; production member bytes have one reader.
        if path in paths and "r" in mode:
            raise AssertionError("member read bypassed the bounded descriptor")
        return actual_path_open(path, mode, *args, **kwargs)

    def open_member(path: Any, *args: Any, **kwargs: Any) -> int:
        descriptor = actual_open(path, *args, **kwargs)
        if isinstance(path, (str, Path)) and Path(path) in paths:
            member = Path(path)
            opened[member] += 1
            active[descriptor] = member
        return descriptor

    def read_member(descriptor: int, maximum: int) -> bytes:
        payload = actual_read(descriptor, maximum)
        if (member := active.get(descriptor)) is not None:
            read_calls[member] += 1
            payload_bytes[member] += len(payload)
            if payload:
                payload_chunks[member] += 1
        return payload

    def close_member(descriptor: int) -> None:
        actual_close(descriptor)
        if (member := active.pop(descriptor, None)) is not None:
            closed[member] += 1

    monkeypatch.setattr(module.os, "open", open_member)
    monkeypatch.setattr(module.os, "read", read_member)
    monkeypatch.setattr(module.os, "close", close_member)
    monkeypatch.setattr(Path, "open", open_stream)
    return SimpleNamespace(
        opened=opened,
        read_calls=read_calls,
        payload_chunks=payload_chunks,
        payload_bytes=payload_bytes,
        closed=closed,
        active=active,
    )


class MetadataSession:
    def __init__(self, *records: object) -> None:
        self.info: dict[object, object] = {}
        self.records = {(type(record), _primary_key(record)): record for record in records}
        self.root = SimpleNamespace(is_active=True)
        self.statements: list[Any] = []
        self.get_calls = 0

    def get_transaction(self) -> object:
        return self.root

    def get(self, model: type[Any], identity: str) -> Any:
        self.get_calls += 1
        return self.records.get((model, identity))

    def scalars(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        model = statement.column_descriptions[0]["entity"]
        return [value for (kind, _key), value in self.records.items() if kind is model]


def test_root_reader_reuses_only_same_session_root_settings_and_thread(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace

    original, settings, _arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    first = PinnedArtifactReadContext.for_session(cast(Session, session), settings)
    assert PinnedArtifactReadContext.for_session(cast(Session, session), settings) is first
    other_settings = replace(settings, nas_artifact_root=tmp_path / "other")
    with pytest.raises(PinnedArtifactResolutionError, match="settings"):
        PinnedArtifactReadContext.for_session(cast(Session, session), other_settings)
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(PinnedArtifactResolutionError, match="transaction"),
    ):
        pool.submit(PinnedArtifactReadContext.for_session, session, settings).result()
    session.root.is_active = False
    with pytest.raises(PinnedArtifactResolutionError, match="transaction"):
        PinnedArtifactReadContext.for_session(cast(Session, session), settings)
    session.root = SimpleNamespace(is_active=True)
    second = PinnedArtifactReadContext.for_session(cast(Session, session), settings)
    assert second is not first
    other_session = MetadataSession(*original.records.values())
    assert (
        PinnedArtifactReadContext.for_session(cast(Session, other_session), settings) is not second
    )


def test_root_reader_retains_current_provenance_checks(tmp_path: Path) -> None:
    original, settings, arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext.for_session(cast(Session, session), settings)
    context.prefetch(((str(arguments["artifact_id"]), str(arguments["artifact_revision_id"])),))
    context.read_pinned(**arguments)
    revision = original.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    revision.approved = False
    same = PinnedArtifactReadContext.for_session(cast(Session, session), settings)
    assert same is context
    with pytest.raises(PinnedArtifactResolutionError, match="provenance"):
        same.read_pinned(**arguments)


def test_prefetch_exact_three_queries_and_no_lazy_sql_on_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original, settings, arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    with pytest.raises(PinnedArtifactResolutionError, match="not captured"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]
    context.prefetch(((str(arguments["artifact_id"]), str(arguments["artifact_revision_id"])),))
    revision = original.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    member = Path(revision.nas_path) / str(arguments["member_path"])
    streams = member_stream_counts(monkeypatch, {member})
    first = context.read_pinned(**arguments)  # type: ignore[arg-type]
    second = context.read_pinned(**arguments)  # type: ignore[arg-type]
    assert first == second and first.payload == b'{"value":1}'
    assert streams.opened == streams.closed == streams.payload_chunks == {member: 1}
    assert streams.read_calls == {member: 2}
    assert streams.payload_bytes == {member: len(first.payload)} and not streams.active
    assert len(session.statements) == 3 and session.get_calls == 0
    assert all(
        statement.get_execution_options()["populate_existing"] for statement in session.statements
    )
    context.prefetch(((first.artifact_id, first.artifact_revision_id),))
    assert len(session.statements) == 3


def test_historical_item_manifest_opt_in_does_not_leak_through_cached_bytes(
    tmp_path: Path,
) -> None:
    original, settings, arguments = _fixture(
        tmp_path,
        artifact_type="item-revision-manifest",
        member_path="item-revision-manifest.json",
        schema_ref="eom://schemas/item-registry/item-revision-manifest-v1",
        metadata=False,
    )
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    context.prefetch(((str(arguments["artifact_id"]), str(arguments["artifact_revision_id"])),))
    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]
    member = context.read_pinned(
        **arguments,
        historical_metadata_compatibility=True,  # type: ignore[arg-type]
    )
    assert member.payload == b'{"value":1}'
    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]
    assert len(session.statements) == 3 and session.get_calls == 0


def test_cached_bytes_never_cache_approval_or_terminal_producer_state(tmp_path: Path) -> None:
    original, settings, arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    context.prefetch(((str(arguments["artifact_id"]), str(arguments["artifact_revision_id"])),))
    context.read_pinned(**arguments)  # type: ignore[arg-type]
    logical = original.get(ArtifactRecord, str(arguments["artifact_id"]))
    job = original.get(JobRecord, "job_" + "3" * 32)
    assert logical is not None and job is not None
    logical.approved = False
    with pytest.raises(PinnedArtifactResolutionError, match="provenance"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]
    logical.approved = True
    job.status = "RUNNING"
    with pytest.raises(PinnedArtifactResolutionError, match="provenance"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]


def test_missing_prefetch_retains_exact_identity_without_skipping(tmp_path: Path) -> None:
    _original, settings, _arguments = _fixture(tmp_path)
    session = MetadataSession()
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    identity = ("artifact_" + "f" * 32, "rev_" + "e" * 32)
    with pytest.raises(PinnedArtifactResolutionError, match="does not resolve") as failure:
        context.prefetch((identity,))
    assert failure.value.artifact_id == identity[0]
    assert failure.value.artifact_revision_id == identity[1]
    with pytest.raises(PinnedArtifactResolutionError, match="not captured"):
        context.read_member(
            artifact_id=identity[0],
            revision_id=identity[1],
            member_path="missing.json",
            sha256="sha256:" + "0" * 64,
            schema_ref="eom://schemas/fixture/1.0",
            media_type="application/json",
            max_bytes=1024,
        )


def test_context_denies_other_session_root_end_and_wrong_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original, settings, _arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    with pytest.raises(PinnedArtifactResolutionError, match="transaction"):
        context.require_session(cast(Session, MetadataSession()))
    monkeypatch.setattr(module, "get_ident", lambda: -1)
    with pytest.raises(PinnedArtifactResolutionError, match="transaction"):
        context.require_session(cast(Session, session))
    monkeypatch.undo()
    session.root.is_active = False
    with pytest.raises(PinnedArtifactResolutionError, match="transaction"):
        context.prefetch(())


def test_exact_descriptor_pointer_member_closure_and_byte_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original, settings, arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    artifact, revision = str(arguments["artifact_id"]), str(arguments["artifact_revision_id"])
    context.prefetch(((artifact, revision),))
    pointer = context.member_pointer(
        artifact,
        revision,
        "evidence/value.json",
        schema_ref=str(arguments["schema_ref"]),
        media_type="application/json",
    )
    assert pointer.sha256 == arguments["sha256"]
    context.require_file_set(artifact, revision, ("evidence/value.json",))
    with pytest.raises(PinnedArtifactResolutionError, match="set differs"):
        context.require_file_set(artifact, revision, ("index.json",))
    with pytest.raises(PinnedArtifactResolutionError, match="descriptor"):
        context.member_pointer(
            artifact,
            revision,
            "evidence/value.json",
            schema_ref="eom://schemas/fixture/foreign/1.0",
            media_type="application/json",
        )
    context.MAX_RETAINED_BYTES = 1
    revision_record = original.get(ArtifactRevisionRecord, revision)
    member = Path(revision_record.nas_path) / "evidence/value.json"
    streams = member_stream_counts(monkeypatch, {member})
    with pytest.raises(PinnedArtifactResolutionError, match="byte budget"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]
    assert not streams.opened and not streams.read_calls and not streams.payload_bytes
    context.MAX_REVISIONS = 1
    with pytest.raises(PinnedArtifactResolutionError, match="metadata budget"):
        context.prefetch((("artifact_" + "f" * 32, "rev_" + "f" * 32),))


def test_1024_members_share_one_manifest_hash_map_and_three_sql_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, settings, arguments = _fixture(tmp_path)
    revision = original.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    files = revision.manifest["files"]
    for number in range(1, 1024):
        path = f"evidence/value-{number}.json"
        payload = f'{{"value":{number}}}'.encode()
        (Path(revision.nas_path) / path).write_bytes(payload)
        files.append(
            {
                "file_name": path,
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "schema_ref": arguments["schema_ref"],
                "media_type": "application/json",
            }
        )
    revision.manifest_hash = content_sha256(revision.manifest)
    session = MetadataSession(*original.records.values())
    calls = 0

    def count_manifest(value: Any) -> str:
        nonlocal calls
        calls += 1
        return content_sha256(value)

    monkeypatch.setattr(module, "content_sha256", count_manifest)
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    context.MAX_RETAINED_BYTES = 512
    context.prefetch(((str(arguments["artifact_id"]), revision.revision_id),))
    for descriptor in files:
        context.read_member(
            artifact_id=str(arguments["artifact_id"]),
            revision_id=revision.revision_id,
            member_path=descriptor["file_name"],
            sha256=descriptor["sha256"],
            schema_ref=descriptor["schema_ref"],
            media_type=descriptor["media_type"],
            max_bytes=1024,
        )
        assert context._retained_bytes <= 512
    assert calls == 1 and len(session.statements) == 3 and session.get_calls == 0
    assert len(context._seen_members) == 1024 and len(context._members) < 1024


def _eviction_fixture(tmp_path: Path):
    original, settings, arguments = _fixture(tmp_path)
    revision = original.get(ArtifactRevisionRecord, str(arguments["artifact_revision_id"]))
    assert revision is not None
    requests = [arguments]
    for number in range(1, 4):
        name = f"evidence/value-{number}.json"
        payload = f'{{"value":{number}}}'.encode()
        (Path(revision.nas_path) / name).write_bytes(payload)
        revision.manifest["files"].append(
            {
                "file_name": name,
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "schema_ref": arguments["schema_ref"],
                "media_type": "application/json",
            }
        )
        requests.append(arguments | {"member_path": name, "sha256": sha256_bytes(payload)})
    revision.manifest_hash = content_sha256(revision.manifest)
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    context.MAX_RETAINED_BYTES = 2 * len(b'{"value":1}')
    context.prefetch(((str(arguments["artifact_id"]), revision.revision_id),))
    return context, requests, revision


def test_lru_eviction_rereads_bytes_and_rejects_tampering(tmp_path: Path, monkeypatch):
    context, requests, revision = _eviction_fixture(tmp_path)
    paths = [Path(revision.nas_path) / str(request["member_path"]) for request in requests]
    streams = member_stream_counts(monkeypatch, set(paths))
    for number in (0, 1, 0, 2):
        context.read_pinned(**requests[number])
    assert streams.opened == streams.closed == streams.payload_chunks == dict.fromkeys(paths[:3], 1)
    assert sum(streams.payload_bytes.values()) == 3 * len(b'{"value":1}')
    assert [key[2] for key in context._members] == [requests[n]["member_path"] for n in (0, 2)]
    context.read_pinned(**requests[1])
    assert (
        streams.opened
        == streams.closed
        == streams.payload_chunks
        == {
            paths[0]: 1,
            paths[1]: 2,
            paths[2]: 1,
        }
    )
    assert sum(streams.read_calls.values()) == 8
    assert sum(streams.payload_bytes.values()) == 4 * len(b'{"value":1}')
    assert not streams.active
    assert context._retained_bytes <= context.MAX_RETAINED_BYTES
    # Reading 1 evicted 0. Reopening 0 must not use an old validation flag.
    (Path(revision.nas_path) / str(requests[0]["member_path"])).write_bytes(b"tampered")
    with pytest.raises(PinnedArtifactResolutionError, match="materialization"):
        context.read_pinned(**requests[0])


def test_eviction_does_not_reset_distinct_member_budget(tmp_path: Path):
    context, requests, _revision = _eviction_fixture(tmp_path)
    context.MAX_RETAINED_BYTES //= 2
    context.MAX_MEMBERS = 3
    for number in (0, 1, 0, 2, 1):
        context.read_pinned(**requests[number])
    assert len(context._members) == 1 and len(context._seen_members) == 3
    with pytest.raises(PinnedArtifactResolutionError, match="member budget"):
        context.read_pinned(**requests[3])
