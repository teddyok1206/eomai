"""Bounded pure index interpretation never replaces current file/source authority."""

from collections.abc import Iterator
from datetime import datetime
from types import SimpleNamespace, UnionType
from typing import Annotated, Any, Literal, TypeAliasType, Union, cast, get_args, get_origin
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingIndexManifest
from eom_catalog_contracts.mixed_embedding_index import MixedEmbeddingIndexManifest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionEmbeddingIndex
from eom_catalog_contracts.registered_public_solution_index import PublicSolutionEmbeddingIndexV4
from eom_catalog_service import embedding_registry_catalog_adapter as module
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import index_manifest, seal
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_pinned_artifact_read_context import member_stream_counts
from tests.unit.test_registered_public_solution_index import successor


@pytest.fixture(autouse=True)
def isolated_decode_cache() -> Iterator[None]:
    module._decode_cached_index_manifest.cache_clear()
    yield
    module._decode_cached_index_manifest.cache_clear()


def index_bytes(seed: str = "1") -> tuple[str, bytes]:
    body = index_manifest().model_dump(mode="json")
    body["index_revision_id"] = "embeddingindexrev_" + seed * 32
    index = EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    return "eom://schemas/knowledge/" + index.schema_version, canonical_json_bytes(index)


def test_exact_bytes_and_schema_reuse_one_successful_interpretation(monkeypatch):
    schema, raw = index_bytes()
    decode = Mock(wraps=module._decode_index_manifest_uncached)
    monkeypatch.setattr(module, "_decode_index_manifest_uncached", decode)
    first = module._decode_index_manifest(schema, raw)
    copied = bytes(bytearray(raw))
    assert copied == raw and copied is not raw
    assert module._decode_index_manifest(schema, copied) is first
    assert decode.call_count == 1
    assert module._decode_cached_index_manifest.cache_info().currsize == 1


def test_changed_bytes_are_not_a_hit_and_changed_schema_is_not_accepted(monkeypatch):
    schema, first_raw = index_bytes("1")
    _, second_raw = index_bytes("2")
    decode = Mock(wraps=module._decode_index_manifest_uncached)
    monkeypatch.setattr(module, "_decode_index_manifest_uncached", decode)
    first = module._decode_index_manifest(schema, first_raw)
    second = module._decode_index_manifest(schema, second_raw)
    assert first != second and first is not second
    with pytest.raises(ValueError, match="schema"):
        module._decode_index_manifest(module.MIXED_EMBEDDING_INDEX_SCHEMA_REF, first_raw)
    assert decode.call_count == 3
    assert module._decode_index_manifest(schema, first_raw) is first
    assert decode.call_count == 3


@pytest.mark.parametrize("fault", ("json", "noncanonical", "hash", "schema"))
def test_invalid_interpretations_are_never_cached(monkeypatch, fault):
    schema, raw = index_bytes()
    if fault == "json":
        raw = b"not JSON"
    elif fault == "noncanonical":
        raw += b"\n"
    elif fault == "hash":
        value = index_manifest().model_dump(mode="json")
        value["index_sha256"] = "sha256:" + "f" * 64
        raw = canonical_json_bytes(value)
    else:
        schema = "eom://schemas/knowledge/foreign/1.0"
    decode = Mock(wraps=module._decode_index_manifest_uncached)
    monkeypatch.setattr(module, "_decode_index_manifest_uncached", decode)
    for _ in range(2):
        with pytest.raises(ValueError):
            module._decode_index_manifest(schema, raw)
    assert decode.call_count == 2
    assert module._decode_cached_index_manifest.cache_info().currsize == 0


@pytest.mark.parametrize("at_limit", (False, True))
def test_size_bound_is_inclusive_and_oversized_input_keeps_strict_decoder(monkeypatch, at_limit):
    assert module.MAX_CACHED_INDEX_MANIFEST_BYTES == 16 * 1024**2
    schema, raw = index_bytes()
    monkeypatch.setattr(module, "MAX_CACHED_INDEX_MANIFEST_BYTES", len(raw) - (not at_limit))
    decode = Mock(wraps=module._decode_index_manifest_uncached)
    monkeypatch.setattr(module, "_decode_index_manifest_uncached", decode)
    first = module._decode_index_manifest(schema, raw)
    second = module._decode_index_manifest(schema, raw)
    assert first == second
    assert (first is second) is at_limit
    assert decode.call_count == (1 if at_limit else 2)
    assert module._decode_cached_index_manifest.cache_info().currsize == int(at_limit)


def test_two_entry_lru_evicts_least_recent_exact_input(monkeypatch):
    first, second, third = (index_bytes(seed) for seed in ("1", "2", "3"))
    decode = Mock(wraps=module._decode_index_manifest_uncached)
    monkeypatch.setattr(module, "_decode_index_manifest_uncached", decode)
    one = module._decode_index_manifest(*first)
    two = module._decode_index_manifest(*second)
    assert module._decode_index_manifest(*first) is one
    module._decode_index_manifest(*third)
    assert module._decode_index_manifest(*first) is one
    replay = module._decode_index_manifest(*second)
    assert replay == two and replay is not two
    assert decode.call_count == 4
    info = module._decode_cached_index_manifest.cache_info()
    assert info.maxsize == info.currsize == 2


def test_new_roots_read_current_physical_bytes_and_provenance_before_decode_hit(owner, monkeypatch):
    verifier, session, command, index, _, _, root = owner
    pointer = command.index_manifest
    path = root / pointer.artifact_id / pointer.artifact_revision_id / pointer.member_path
    size = path.stat().st_size
    streams = member_stream_counts(monkeypatch, {path})
    decode = Mock(wraps=module._decode_index_manifest_uncached)
    monkeypatch.setattr(module, "_decode_index_manifest_uncached", decode)
    values = []
    for _ in range(2):
        session.root.is_active = False
        session.root = SimpleNamespace(is_active=True)
        before = len(session.statements)
        reader = PinnedArtifactReadContext.for_session(cast(Session, session), verifier.settings)
        values.append(verifier._read_index(reader, pointer))
        reader.revalidate_provenance()
        assert len(session.statements) > before
    assert values[0] == index and values[1] is values[0]
    assert decode.call_count == 1
    assert streams.opened[path] == streams.closed[path] == 2
    assert streams.payload_bytes[path] == 2 * size
    assert not streams.active


@pytest.mark.parametrize("fault", ("approval", "producer", "missing", "tamper", "hash"))
def test_warm_process_cache_does_not_admit_revoked_or_changed_input_in_a_new_root(owner, fault):
    verifier, session, command, _, _, _, root = owner
    pointer = command.index_manifest
    reader = PinnedArtifactReadContext.for_session(cast(Session, session), verifier.settings)
    verifier._read_index(reader, pointer)
    revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
    path = root / pointer.artifact_id / pointer.artifact_revision_id / pointer.member_path
    if fault == "approval":
        session.get(ArtifactRecord, pointer.artifact_id).approved = False
    elif fault == "producer":
        session.get(JobRecord, revision.job_id).status = "RUNNING"
    elif fault == "missing":
        path.unlink()
    elif fault == "tamper":
        path.write_bytes(b"x" * path.stat().st_size)
    else:
        pointer = pointer.model_copy(update={"sha256": "sha256:" + "f" * 64})
    session.root.is_active = False
    session.root = SimpleNamespace(is_active=True)
    fresh = PinnedArtifactReadContext.for_session(cast(Session, session), verifier.settings)
    with pytest.raises((ValueError, PinnedArtifactResolutionError)):
        verifier._read_index(fresh, pointer)


@pytest.mark.parametrize(
    "index_type",
    (
        EmbeddingIndexManifest,
        MixedEmbeddingIndexManifest,
        PublicSolutionEmbeddingIndex,
        PublicSolutionEmbeddingIndexV4,
    ),
)
def test_all_cached_index_families_have_deeply_immutable_field_types(index_type):
    seen: set[type[BaseModel]] = set()

    def inspect(annotation):
        if isinstance(annotation, TypeAliasType):
            inspect(annotation.__value__)
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation in seen:
                return
            seen.add(annotation)
            assert annotation.model_config.get("frozen") is True
            assert annotation.model_config.get("extra") == "forbid"
            for field in annotation.model_fields.values():
                inspect(field.annotation)
        elif get_origin(annotation) is Annotated:
            inspect(get_args(annotation)[0])
        elif get_origin(annotation) is Literal:
            assert all(isinstance(value, str | int | bool) for value in get_args(annotation))
        elif get_origin(annotation):
            assert get_origin(annotation) in (tuple, Union, UnionType)
            for argument in get_args(annotation):
                inspect(argument)
        else:
            assert annotation in (str, int, datetime, type(None), Ellipsis)

    inspect(index_type)
    assert len(seen) >= 20


@pytest.mark.parametrize("version", ("4.0", "5.0"))
def test_cached_public_index_and_nested_values_reject_mutation(version):
    _, index, _, _ = successor()
    body = index.model_dump(mode="json")
    body["schema_version"] = "embedding-index-manifest/" + version
    index = PublicSolutionEmbeddingIndexV4.model_validate(seal(body, "index_sha256"))
    schema = "eom://schemas/knowledge/" + index.schema_version
    raw = canonical_json_bytes(index)
    cached = module._decode_index_manifest(schema, raw)
    pending: list[Any] = [cached]
    models = 0
    while pending:
        value = pending.pop()
        if isinstance(value, BaseModel):
            models += 1
            for name in type(value).model_fields:
                original = getattr(value, name)
                with pytest.raises(ValidationError, match="frozen"):
                    setattr(value, name, original)
                pending.append(original)
        elif isinstance(value, tuple):
            pending.extend(value)
        else:
            assert value is None or isinstance(value, str | int | datetime)
    assert models > 20
    exported = cached.model_dump(mode="json")
    exported["bindings"][0]["source"]["item_id"] = "item_" + "f" * 32
    assert module._decode_index_manifest(schema, raw) is cached
    assert canonical_json_bytes(cached) == raw
