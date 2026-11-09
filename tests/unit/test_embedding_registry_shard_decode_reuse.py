"""Retain immutable shard interpretation, not numeric/source/Artifact admission."""

from time import perf_counter
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_registry_catalog_adapter as module
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy.orm import Session

from tests.unit.test_embedding_registry_catalog_adapter import owner as owner


def test_same_root_reuses_shard_and_result_but_rechecks_numeric_values(owner, monkeypatch):
    verifier, session, _command, index, *_ = owner
    shard_parser = Mock(wraps=module.parse_embedding_shard)
    result_parser = Mock(wraps=module.parse_incremental_embedding_result)
    numerical = Mock(wraps=module.read_unit_vectors)
    monkeypatch.setattr(module, "parse_embedding_shard", shard_parser)
    monkeypatch.setattr(module, "parse_incremental_embedding_result", result_parser)
    monkeypatch.setattr(module, "read_unit_vectors", numerical)
    reader = PinnedArtifactReadContext(cast(Session, session), verifier.settings)
    values = tuple(tuple(verifier._iter_numerical_shards(reader, index.shards)) for _ in range(10))
    assert all(value == values[0] for value in values)
    assert all(value[0][1] is values[0][0][1] for value in values)
    assert (shard_parser.call_count, result_parser.call_count, numerical.call_count) == (1, 1, 10)
    fresh = PinnedArtifactReadContext(cast(Session, session), verifier.settings)
    assert tuple(verifier._iter_numerical_shards(fresh, index.shards)) == values[0]
    assert (shard_parser.call_count, result_parser.call_count, numerical.call_count) == (2, 2, 11)


@pytest.mark.parametrize(
    "fault", ("hash", "schema", "media", "revision", "approval", "producer", "root")
)
def test_warm_shard_models_never_admit_changed_pointer_or_provenance(owner, fault):
    verifier, session, _command, index, *_ = owner
    reader = PinnedArtifactReadContext(cast(Session, session), verifier.settings)
    assert tuple(verifier._iter_numerical_shards(reader, index.shards))
    pointer = index.shards[0]
    revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
    if fault == "hash":
        pointer = pointer.model_copy(update={"sha256": "sha256:" + "f" * 64})
    elif fault == "schema":
        pointer = pointer.model_copy(update={"schema_ref": module.RESULT_SCHEMA_REF})
    elif fault == "media":
        pointer = pointer.model_copy(update={"media_type": "text/plain"})
    elif fault == "revision":
        pointer = pointer.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32})
    elif fault == "approval":
        session.get(ArtifactRecord, pointer.artifact_id).approved = False
    elif fault == "producer":
        session.get(JobRecord, revision.job_id).status = "RUNNING"
    else:
        session.root.is_active = False
    with pytest.raises((ValueError, PinnedArtifactResolutionError)):
        tuple(verifier._iter_numerical_shards(reader, (pointer,)))


@pytest.mark.parametrize("member", ("shard.json", "result.json", "vectors.f32"))
@pytest.mark.parametrize("fault", (None, "missing", "tamper"))
def test_decoded_shard_models_still_require_physical_bytes_after_eviction(owner, member, fault):
    verifier, session, _command, index, _binding, _scope, root = owner
    pointer = index.shards[0]
    directory = root / pointer.artifact_id / pointer.artifact_revision_id
    files = tuple(directory / name for name in ("shard.json", "result.json", "vectors.f32"))
    index_pointer = _command.index_manifest
    index_path = (
        root / index_pointer.artifact_id / index_pointer.artifact_revision_id / "index.json"
    )
    reader = PinnedArtifactReadContext(cast(Session, session), verifier.settings)
    reader.MAX_RETAINED_BYTES = index_path.stat().st_size
    assert max(path.stat().st_size for path in files) <= reader.MAX_RETAINED_BYTES
    original = tuple(verifier._iter_numerical_shards(reader, index.shards))
    # Exercise the ordinary raw-byte LRU, leaving the typed immutable models warm.
    verifier._read_index(reader, _command.index_manifest)
    assert all(
        key[2] not in {"shard.json", "result.json", "vectors.f32"} for key in reader._members
    )
    selected = directory / member
    if fault == "missing":
        selected.unlink()
    elif fault == "tamper":
        selected.write_bytes(b"x" * selected.stat().st_size)
    if fault is None:
        assert tuple(verifier._iter_numerical_shards(reader, index.shards)) == original
    else:
        with pytest.raises((ValueError, PinnedArtifactResolutionError)):
            tuple(verifier._iter_numerical_shards(reader, index.shards))


def test_synthetic_repeated_shard_decode_cost_preserves_exact_rows(owner, monkeypatch, request):
    verifier, session, _command, index, *_ = owner
    shard_parser = Mock(wraps=module.parse_embedding_shard)
    result_parser = Mock(wraps=module.parse_incremental_embedding_result)
    numerical = Mock(wraps=module.read_unit_vectors)
    monkeypatch.setattr(module, "parse_embedding_shard", shard_parser)
    monkeypatch.setattr(module, "parse_incremental_embedding_result", result_parser)
    monkeypatch.setattr(module, "read_unit_vectors", numerical)
    observed = []
    for retained in (False, True):
        reader = PinnedArtifactReadContext(cast(Session, session), verifier.settings)
        if not retained:
            reader.MAX_DECODED_MEMBERS = 0
        for parser in (shard_parser, result_parser, numerical):
            parser.reset_mock()
        started = perf_counter()
        rows = tuple(
            tuple(verifier._iter_numerical_shards(reader, index.shards)) for _ in range(25)
        )
        elapsed = perf_counter() - started
        assert all(row == rows[0] for row in rows)
        assert shard_parser.call_count == result_parser.call_count == (1 if retained else 25)
        assert numerical.call_count == 25
        observed.append((rows[0], elapsed))
    assert observed[0][0] == observed[1][0]
    request.node.user_properties.extend(
        (
            ("synthetic_uncached_shard_result_parses", 50),
            ("synthetic_retained_shard_result_parses", 2),
            ("synthetic_numeric_checks_each", 25),
            ("synthetic_uncached_seconds", observed[0][1]),
            ("synthetic_retained_seconds", observed[1][1]),
        )
    )
