"""Synthetic root-Session metadata/temporary-file checks, no DB or actual NAS access."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

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


class MetadataSession:
    def __init__(self, *records: object) -> None:
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


def test_prefetch_exact_three_queries_and_no_lazy_sql_on_read(tmp_path: Path) -> None:
    original, settings, arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    context = PinnedArtifactReadContext(cast(Session, session), settings)
    with pytest.raises(PinnedArtifactResolutionError, match="not captured"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]
    context.prefetch(((str(arguments["artifact_id"]), str(arguments["artifact_revision_id"])),))
    first = context.read_pinned(**arguments)  # type: ignore[arg-type]
    second = context.read_pinned(**arguments)  # type: ignore[arg-type]
    assert first == second and first.payload == b'{"value":1}'
    assert len(session.statements) == 3 and session.get_calls == 0
    assert all(
        statement.get_execution_options()["populate_existing"] for statement in session.statements
    )
    context.prefetch(((first.artifact_id, first.artifact_revision_id),))
    assert len(session.statements) == 3


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
    hash_file = Mock()
    monkeypatch.setattr(module, "sha256_file", hash_file)
    with pytest.raises(PinnedArtifactResolutionError, match="byte budget"):
        context.read_pinned(**arguments)  # type: ignore[arg-type]
    hash_file.assert_not_called()
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
    assert calls == 1 and len(session.statements) == 3 and session.get_calls == 0
