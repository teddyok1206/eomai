"""Exact immutable-ledger origins retain current admission and physical Artifact checks.

Only source/IAM/SQL are synthetic; the concrete verifier reads temporary committed
index/shard bytes and validates the actual finite unit vector, without a model or DB.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_registry_catalog_adapter as catalog
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_models import EmbeddingSourceBindingRecord
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingOrigin,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    ResolvedEmbeddingReferences,
)
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import content_sha256
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner

type OwnerFixture = tuple[Any, ...]
CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)
BINDING_SCALARS = tuple(
    column.name
    for column in EmbeddingSourceBindingRecord.__table__.columns
    if not column.name.startswith("binding_manifest_") and column.name != "registered_at"
)


def _verify(
    fixture: OwnerFixture, origins: tuple[EmbeddingBindingOrigin, ...] | None = None
) -> ResolvedEmbeddingReferences:
    verifier, session, command, _index, binding, _scope, _root = fixture
    return verifier.verify_registered_references(
        session,
        CALLER,
        command,
        (RegisteredEmbeddingRow(binding.encoding, binding.row_ref),),
        (EmbeddingBindingOrigin(binding.binding_sha256, command.index_manifest),)
        if origins is None
        else origins,
    )


@pytest.mark.parametrize("column", BINDING_SCALARS)
def test_every_canonical_ledger_scalar_must_equal_current_reconstruction(
    owner: OwnerFixture, column: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier, session, _command, _index, binding, _scope, _root = owner
    record = session.binding_records[binding.binding_sha256]
    setattr(record, column, getattr(record, column) + ":forged-ledger")
    materialize = Mock(side_effect=AssertionError("reject forged ledger before origin IO"))
    monkeypatch.setattr(verifier, "_read_index_member", materialize)
    with pytest.raises(EmbeddingRegistryError) as rejected:
        _verify(owner)
    assert rejected.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"
    materialize.assert_not_called()


@pytest.mark.parametrize("column", tuple(ArtifactMemberPointer.model_fields))
def test_every_first_origin_pointer_column_must_match_exactly(
    owner: OwnerFixture, column: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier, session, _command, _index, binding, _scope, _root = owner
    record = session.binding_records[binding.binding_sha256]
    field = "binding_manifest_" + column
    setattr(record, field, getattr(record, field) + ":forged-origin")
    materialize = Mock(side_effect=AssertionError("reject different first origin before IO"))
    monkeypatch.setattr(verifier, "_read_index_member", materialize)
    with pytest.raises(EmbeddingRegistryError) as rejected:
        _verify(owner)
    assert rejected.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"
    materialize.assert_not_called()


def test_missing_ledger_is_not_recovered_from_historical_index(owner: OwnerFixture) -> None:
    _verifier, session, _command, _index, _binding, _scope, _root = owner
    session.binding_records.clear()
    with pytest.raises(EmbeddingRegistryError) as rejected:
        _verify(owner)
    assert rejected.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"


@pytest.mark.parametrize("distinct_manifest", (False, True))
def test_duplicate_binding_sha_is_rejected_even_for_distinct_origin_pointers(
    owner: OwnerFixture, distinct_manifest: bool
) -> None:
    _verifier, _session, command, _index, binding, _scope, _root = owner
    first = EmbeddingBindingOrigin(binding.binding_sha256, command.index_manifest)
    second = (
        replace(first, manifest=first.manifest.model_copy(update={"sha256": sha("f")}))
        if distinct_manifest
        else first
    )
    with pytest.raises(EmbeddingRegistryError) as rejected:
        _verify(owner, (first, second))
    assert rejected.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"


def test_current_source_withdrawal_is_not_authorized_by_an_immutable_ledger(
    owner: OwnerFixture,
) -> None:
    verifier, _session, _command, _index, _binding, _scope, _root = owner
    capture = verifier.sources.capture_in_session.side_effect

    def withdrawn(*args, **kwargs):
        current = capture(*args, **kwargs)
        assert current.corpus is not None
        return replace(current, corpus=replace(current.corpus, profiles=(), sources=()), entries=())

    verifier.sources.capture_in_session.side_effect = withdrawn
    with pytest.raises(EmbeddingRegistryError) as rejected:
        _verify(owner)
    assert rejected.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"


def test_current_source_forbidden_keeps_authority_error_before_ledger_or_origin_io(
    owner: OwnerFixture,
) -> None:
    verifier, session, _command, _index, _binding, _scope, _root = owner
    verifier.sources.capture_in_session.side_effect = InferenceTransferServiceError(
        "INFERENCE_TRANSFER_FORBIDDEN"
    )
    with pytest.raises(EmbeddingRegistryError) as rejected:
        _verify(owner)
    assert rejected.value.code == "EMBEDDING_REGISTRY_FORBIDDEN"
    assert session.statements == []


@pytest.mark.parametrize(
    "failure",
    (
        "logical_missing",
        "revision_missing",
        "producer_missing",
        "file_deleted",
        "logical_approval",
        "revision_approval",
        "producer_state",
        "producer_identity",
        "raw_corruption",
        "stale_primary_hash",
        "descriptor_schema",
        "descriptor_media",
        "file_set_version",
        "extra_member",
        "declared_byte_bound",
    ),
)
def test_first_origin_still_requires_original_artifact_provenance_and_bounded_raw_bytes(
    owner: OwnerFixture, failure: str
) -> None:
    _verifier, session, command, _index, _binding, _scope, _root = owner
    pointer = command.index_manifest
    logical = session.get(ArtifactRecord, pointer.artifact_id)
    revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
    producer = session.get(JobRecord, revision.job_id)
    path = Path(revision.nas_path) / pointer.member_path
    descriptor = revision.manifest["files"][0]
    if failure == "logical_missing":
        session.records.pop((ArtifactRecord, pointer.artifact_id))
    elif failure == "revision_missing":
        session.records.pop((ArtifactRevisionRecord, pointer.artifact_revision_id))
    elif failure == "producer_missing":
        session.records.pop((JobRecord, producer.job_id))
    elif failure == "file_deleted":
        path.unlink()
    elif failure == "logical_approval":
        logical.approved = False
    elif failure == "revision_approval":
        revision.approved = False
    elif failure == "producer_state":
        producer.status = "RUNNING"
    elif failure == "producer_identity":
        producer.revision_id = "rev_" + "f" * 32
    elif failure == "raw_corruption":
        payload = path.read_bytes()
        path.write_bytes(b"!" + payload[1:])
    elif failure == "stale_primary_hash":
        revision.content_hash = sha("f")
    elif failure == "descriptor_schema":
        descriptor["schema_ref"] = "eom://schemas/knowledge/embedding-index-manifest/2.0"
    elif failure == "descriptor_media":
        descriptor["media_type"] = "application/octet-stream"
    elif failure == "file_set_version":
        revision.manifest["manifest_version"] = "control-file-set/2.0"
    elif failure == "extra_member":
        revision.manifest["files"].append(descriptor | {"file_name": "unexpected.json"})
    elif failure == "declared_byte_bound":
        descriptor["bytes"] = catalog.MAX_EMBEDDING_INPUT_BYTES + 1
        revision.content_bytes = descriptor["bytes"]
        revision.manifest["content_bytes"] = descriptor["bytes"]
    else:
        pytest.fail("unhandled origin failure")
    # Descriptor cases retain a consistent outer manifest hash, reaching the
    # specific schema/media/version/bound check rather than only its hash fence.
    revision.manifest_hash = content_sha256(revision.manifest)
    with pytest.raises(EmbeddingRegistryError) as rejected:
        _verify(owner)
    assert rejected.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"


def test_reference_origins_skip_historical_dto_parse_but_selected_index_still_parses(
    owner: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier, session, command, index, binding, _scope, _root = owner
    parse = Mock(wraps=catalog.parse_embedding_index)
    monkeypatch.setattr(catalog, "parse_embedding_index", parse)
    references = _verify(owner)
    assert references.origins[0].binding == binding
    assert references.shards[0][0] == binding.row_ref.shard_manifest
    parse.assert_not_called()
    reader = PinnedArtifactReadContext(cast(Session, session), verifier.settings)
    assert verifier._read_index(reader, command.index_manifest) == index
    parse.assert_called_once()
