"""Synthetic captures and memory metadata adapter; no DB, source authority or encoder."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingBindingOrigin,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    RegisteredEmbeddingIndexRead,
    ResolvedEmbeddingBindingOrigin,
    ResolvedEmbeddingLookup,
    ResolvedEmbeddingReferences,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.embedding_registry_repository import ASSOCIATION_COLUMNS, artifact_member
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    index_manifest,
    index_pointer,
    seal,
    source_binding,
    vector_shard,
)
from tests.unit.test_embedding_registry_contracts import registration_command


def capture_pair(
    previous: ResolvedEmbeddingRegistration | None = None,
) -> tuple[RegisterEmbeddingIndexCommand, ResolvedEmbeddingRegistration]:
    entry = embedding_entry()
    binding = source_binding(entry)
    shard = vector_shard((binding.encoding,))
    previous_value = (
        None if previous is None else (index_pointer(previous.index, "b"), previous.index)
    )
    index = index_manifest(
        binding,
        previous_manifest=None if previous_value is None else previous_value[0],
        revision_seed="2" if previous is None else "3",
    )
    command = registration_command().model_dump(mode="json")
    command.update(
        index_revision_id=index.index_revision_id,
        index_manifest=index_pointer(index, "b" if previous is None else "c").model_dump(
            mode="json"
        ),
        index_sha256=index.index_sha256,
        expected_current_index_revision_id=None
        if previous is None
        else previous.index.index_revision_id,
        expected_lock_version=1 if previous is None else 2,
        operation_key="synthetic-register:first"
        if previous is None
        else "synthetic-register:second",
        source_set_sha256=population_sha256((binding.source,)),
    )
    request = RegisterEmbeddingIndexCommand.model_validate(seal(command, "request_sha256"))
    resolved = ResolvedEmbeddingRegistration(
        request.corpus_id,
        index,
        ((binding.row_ref.shard_manifest, shard),),
        previous_value,
        (binding.source,),
        (entry,),
    )
    return request, resolved


class MemorySession:
    def __init__(self) -> None:
        self.state: dict[str, dict[str, Any]] = {
            name: {} for name in ("heads", "revisions", "encodings", "bindings")
        }
        self.transaction_active = True
        self.cas_succeeds = True

    def in_transaction(self) -> bool:
        return self.transaction_active

    @contextmanager
    def begin_nested(self) -> Iterator[None]:
        before = deepcopy(self.state)
        try:
            yield
        except Exception:
            self.state = before
            raise

    def refresh(self, _row: object) -> None:
        pass


class MemoryRepository:
    def __init__(self, session: MemorySession) -> None:
        self.session = session

    def operation(self, key: str) -> EmbeddingIndexRevisionRecord | None:
        return cast(
            EmbeddingIndexRevisionRecord | None,
            next(
                (
                    row
                    for row in self.session.state["revisions"].values()
                    if row.operation_key == key
                ),
                None,
            ),
        )

    def head(self, index_id: str) -> EmbeddingIndexRecord | None:
        return cast(EmbeddingIndexRecord | None, self.session.state["heads"].get(index_id))

    def revision(self, revision_id: str) -> EmbeddingIndexRevisionRecord | None:
        return cast(
            EmbeddingIndexRevisionRecord | None, self.session.state["revisions"].get(revision_id)
        )

    def read_pinned_revision(
        self, index_id: str, revision_id: str
    ) -> RegisteredEmbeddingIndexRead | None:
        revision = self.revision(revision_id)
        head = self.session.state["heads"].get(index_id)
        if revision is None or head is None or revision.index_id != index_id:
            return None
        return RegisteredEmbeddingIndexRead(
            head.corpus_id,
            EmbeddingIndexNamespace.model_validate(
                {name: getattr(head, name) for name in EmbeddingIndexNamespace.model_fields}
            ),
            revision.index_id,
            revision.index_revision_id,
            artifact_member(revision, "manifest_"),
            revision.index_sha256,
            revision.graph_snapshot_revision_id,
            revision.policy_revision_id,
            revision.policy_sha256,
            revision.binding_count,
            revision.binding_set_sha256,
        )

    def create_head(
        self, command: RegisterEmbeddingIndexCommand, now: datetime
    ) -> EmbeddingIndexRecord:
        row = EmbeddingIndexRecord(
            index_id=command.index_id,
            corpus_id=command.corpus_id,
            **command.namespace.model_dump(mode="python"),
            current_index_revision_id=None,
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.state["heads"][row.index_id] = row
        return row

    def encodings(self, keys: tuple[str, ...]) -> dict[str, EmbeddingEncodingRecord]:
        return {
            key: self.session.state["encodings"][key]
            for key in keys
            if key in self.session.state["encodings"]
        }

    def bindings(
        self, keys: tuple[EmbeddingBindingLookupKey, ...]
    ) -> dict[str, EmbeddingSourceBindingRecord]:
        wanted = {key.columns() for key in keys}
        return {
            key: row
            for key, row in self.session.state["bindings"].items()
            if tuple(getattr(row, name) for name in ASSOCIATION_COLUMNS) in wanted
        }

    def missing_bindings(
        self, keys: tuple[EmbeddingBindingLookupKey, ...]
    ) -> tuple[EmbeddingBindingLookupKey, ...]:
        existing = {
            tuple(getattr(row, name) for name in ASSOCIATION_COLUMNS)
            for row in self.bindings(keys).values()
        }
        return tuple(key for key in keys if key.columns() not in existing)

    def insert_components(
        self, encodings: Sequence[dict[str, Any]], bindings: Sequence[dict[str, Any]]
    ) -> None:
        for name, model, rows, key in (
            ("encodings", EmbeddingEncodingRecord, encodings, "encoding_sha256"),
            ("bindings", EmbeddingSourceBindingRecord, bindings, "binding_sha256"),
        ):
            for values in rows:
                self.session.state[name].setdefault(values[key], model(**values))

    def add_revision(self, row: EmbeddingIndexRevisionRecord) -> None:
        self.session.state["revisions"][row.index_revision_id] = row

    def advance(self, command: RegisterEmbeddingIndexCommand, now: datetime) -> bool:
        if not self.session.cas_succeeds:
            return False
        row = self.head(command.index_id)
        assert row is not None
        row.current_index_revision_id = command.index_revision_id
        row.lock_version = command.expected_lock_version + 1
        row.updated_at = now
        return True


class SyntheticVerifier:
    """A test-only owner; local fixture states are not wire approval/role grants."""

    def __init__(self, *captures: ResolvedEmbeddingRegistration) -> None:
        self.captures = {capture.index.index_revision_id: capture for capture in captures}
        self.capture = captures[0]
        self.item_state = "APPROVED"
        self.analysis_state = "ACCEPTED"
        self.member_state = "COMMITTED"
        self.calls: list[str] = []

    def authorize_scope(
        self,
        _session: Session,
        caller: EmbeddingRegistryCaller,
        _intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
    ) -> None:
        self.calls.append("authorize")
        if caller.operator_id != "operator_" + "1" * 32:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")

    def _check_source_and_commit(self) -> None:
        if self.item_state != "APPROVED" or self.analysis_state != "ACCEPTED":
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        if self.member_state != "COMMITTED":
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")

    def resolve_registration(
        self,
        _session: Session,
        _caller: EmbeddingRegistryCaller,
        command: RegisterEmbeddingIndexCommand,
    ) -> ResolvedEmbeddingRegistration:
        self.calls.append("resolve")
        self._check_source_and_commit()
        return self.captures[command.index_revision_id]

    def resolve_lookup(
        self, _session: Session, _caller: EmbeddingRegistryCaller, _query: EmbeddingRegistryLookup
    ) -> ResolvedEmbeddingLookup:
        self.calls.append("lookup")
        self._check_source_and_commit()
        capture = self.capture
        return ResolvedEmbeddingLookup(
            capture.corpus_id,
            capture.index.space,
            capture.index.recipe,
            capture.sources,
            capture.entries,
            capture.truncated,
        )

    def verify_registered_references(
        self,
        _session: Session,
        _caller: EmbeddingRegistryCaller,
        _intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        rows: tuple[RegisteredEmbeddingRow, ...],
        origins: tuple[EmbeddingBindingOrigin, ...],
    ) -> ResolvedEmbeddingReferences:
        self.calls.append("references")
        self._check_source_and_commit()
        by_shard = {
            pointer: shard
            for capture in self.captures.values()
            for pointer, shard in capture.shards
        }
        by_binding = {
            binding.binding_sha256: binding
            for capture in self.captures.values()
            for binding in capture.index.bindings
        }
        for row in rows:
            shard = by_shard.get(row.row_ref.shard_manifest)
            if shard is None or shard.rows[row.row_ref.row_index] != row.encoding:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
        selected = tuple(
            ResolvedEmbeddingBindingOrigin(origin, by_binding[origin.binding_sha256])
            for origin in origins
        )
        pointers = {value.binding.row_ref.shard_manifest for value in selected}
        return ResolvedEmbeddingReferences(
            selected,
            tuple(
                (pointer, by_shard[pointer])
                for pointer in sorted(
                    pointers,
                    key=lambda pointer: (
                        pointer.artifact_id,
                        pointer.artifact_revision_id,
                        pointer.member_path,
                        pointer.sha256,
                    ),
                )
            ),
        )


def truncated_capture(capture: ResolvedEmbeddingRegistration) -> ResolvedEmbeddingRegistration:
    return replace(capture, truncated=True)
