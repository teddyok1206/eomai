"""Catalog-owned scalar embedding persistence; eligibility is never decided here."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSourceBinding,
    EmbeddingVectorRowRef,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import String, column, exists, select, tuple_, update, values
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

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
    EmbeddingRegistryError,
    RegisteredEmbeddingIndexRead,
)

ASSOCIATION_COLUMNS = (
    "item_revision_id",
    "graph_snapshot_revision_id",
    "policy_revision_id",
    "recipe_sha256",
    "view",
    "projection_version",
    "base_analysis_run_id",
    "profile_revision_id",
    "solution_analysis_run_id",
    "encoding_sha256",
)


def artifact_member(record: object, prefix: str) -> ArtifactMemberPointer:
    return ArtifactMemberPointer.model_validate(
        {
            name: getattr(record, prefix + name)
            for name in (
                "artifact_id",
                "artifact_revision_id",
                "member_path",
                "schema_ref",
                "media_type",
                "sha256",
            )
        }
    )


def registered_row(record: EmbeddingEncodingRecord) -> RegisteredEmbeddingRow:
    return RegisteredEmbeddingRow(
        EmbeddingEncodingIdentity(
            storage_partition=record.storage_partition,
            space_sha256=record.space_sha256,
            input_text_sha256=record.input_text_sha256,
            encoding_sha256=record.encoding_sha256,
        ),
        EmbeddingVectorRowRef(
            shard_manifest=artifact_member(record, "shard_"),
            row_index=record.row_index,
            encoding_sha256=record.encoding_sha256,
        ),
    )


def binding_origin(record: EmbeddingSourceBindingRecord) -> EmbeddingBindingOrigin:
    return EmbeddingBindingOrigin(
        record.binding_sha256, artifact_member(record, "binding_manifest_")
    )


def binding_columns(binding: EmbeddingSourceBinding) -> dict[str, Any]:
    """The one scalar projection stored by registration, not an eligibility decision."""
    return {
        "binding_sha256": binding.binding_sha256,
        "encoding_sha256": binding.encoding.encoding_sha256,
        "item_id": binding.source.item_id,
        "item_revision_id": binding.source.item_revision_id,
        "source_class": binding.source.source_class,
        "source_sha256": binding.source.artifact_member.sha256,
        "base_analysis_run_id": binding.solution_evidence.base_analysis_run_id,
        "solution_analysis_run_id": binding.solution_evidence.solution_analysis_run_id,
        "solution_pointer_sha256": binding.solution_evidence.pointer_sha256,
        "profile_id": binding.profile.profile_id,
        "profile_revision_id": binding.profile.profile_revision_id,
        "profile_sha256": binding.profile.profile_sha256,
        "graph_snapshot_revision_id": binding.graph_snapshot.graph_snapshot_revision_id,
        "policy_revision_id": binding.policy_revision_id,
        "policy_sha256": binding.policy_sha256,
        "view": binding.view,
        "recipe_sha256": binding.recipe.recipe_sha256,
        "projection_version": binding.projection_version,
    }


class EmbeddingRegistryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def operation(self, key: str) -> EmbeddingIndexRevisionRecord | None:
        return self.session.scalar(
            select(EmbeddingIndexRevisionRecord).where(
                EmbeddingIndexRevisionRecord.operation_key == key
            )
        )

    def head(self, index_id: str) -> EmbeddingIndexRecord | None:
        return self.session.scalar(
            select(EmbeddingIndexRecord)
            .where(EmbeddingIndexRecord.index_id == index_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def revision(self, revision_id: str) -> EmbeddingIndexRevisionRecord | None:
        return self.session.get(EmbeddingIndexRevisionRecord, revision_id)

    def current_namespace_revision(
        self, corpus_id: str, namespace: EmbeddingIndexNamespace
    ) -> tuple[RegisteredEmbeddingIndexRead, int] | None:
        """One unique-namespace lookup and pinned PK read, no write/current-head lock.

        Select mutable head once, then keep that exact predecessor/version. A later
        contender is handled by registration CAS, not another latest substitution.
        Current source permission must be fenced by the Catalog application first.
        """
        record = EmbeddingIndexRecord
        head = self.session.scalar(
            select(record)
            .where(
                record.corpus_id == corpus_id,
                *(
                    getattr(record, name) == value
                    for name, value in namespace.model_dump(mode="python").items()
                ),
            )
            .execution_options(populate_existing=True)
        )
        if head is None:
            return None
        revision_id, version = head.current_index_revision_id, head.lock_version
        if revision_id is None or type(version) is not int or version < 2:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
        pinned = self.read_pinned_revision(head.index_id, revision_id)
        revision = self.revision(revision_id)
        if pinned is None or revision is None or revision.revision_number + 1 != version:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
        return pinned, version

    def read_pinned_revision(
        self, index_id: str, revision_id: str
    ) -> RegisteredEmbeddingIndexRead | None:
        """One exact PK/FK join; never select the mutable current pointer or acquire its lock."""
        revision, index = EmbeddingIndexRevisionRecord, EmbeddingIndexRecord
        row = self.session.execute(
            select(
                revision.index_id,
                revision.index_revision_id,
                revision.manifest_artifact_id,
                revision.manifest_artifact_revision_id,
                revision.manifest_member_path,
                revision.manifest_schema_ref,
                revision.manifest_media_type,
                revision.manifest_sha256,
                revision.index_sha256,
                revision.graph_snapshot_revision_id,
                revision.policy_revision_id,
                revision.policy_sha256,
                revision.binding_count,
                revision.binding_set_sha256,
                index.corpus_id,
                index.storage_partition,
                index.space_sha256,
                index.view,
                index.recipe_sha256,
                index.projection_version,
                index.population_scope,
            )
            .join(index, index.index_id == revision.index_id)
            .where(revision.index_id == index_id, revision.index_revision_id == revision_id)
        ).one_or_none()
        if row is None:
            return None
        return RegisteredEmbeddingIndexRead(
            row.corpus_id,
            EmbeddingIndexNamespace.model_validate(
                {name: getattr(row, name) for name in EmbeddingIndexNamespace.model_fields}
            ),
            row.index_id,
            row.index_revision_id,
            artifact_member(row, "manifest_"),
            row.index_sha256,
            row.graph_snapshot_revision_id,
            row.policy_revision_id,
            row.policy_sha256,
            row.binding_count,
            row.binding_set_sha256,
        )

    def create_head(
        self, command: RegisterEmbeddingIndexCommand, now: datetime
    ) -> EmbeddingIndexRecord:
        namespace = command.namespace.model_dump(mode="python")
        row = EmbeddingIndexRecord(
            index_id=command.index_id,
            corpus_id=command.corpus_id,
            **namespace,
            current_index_revision_id=None,
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def encodings(self, keys: tuple[str, ...]) -> dict[str, EmbeddingEncodingRecord]:
        if not keys:
            return {}
        return {
            row.encoding_sha256: row
            for row in self.session.scalars(
                select(EmbeddingEncodingRecord).where(
                    EmbeddingEncodingRecord.encoding_sha256.in_(keys)
                )
            )
        }

    def bindings(
        self, keys: tuple[EmbeddingBindingLookupKey, ...]
    ) -> dict[str, EmbeddingSourceBindingRecord]:
        if not keys:
            return {}
        columns = tuple(getattr(EmbeddingSourceBindingRecord, name) for name in ASSOCIATION_COLUMNS)
        return {
            row.binding_sha256: row
            for row in self.session.scalars(
                select(EmbeddingSourceBindingRecord).where(
                    tuple_(*columns).in_(tuple(key.columns() for key in keys))
                )
            )
        }

    def bindings_by_sha256(self, keys: tuple[str, ...]) -> dict[str, EmbeddingSourceBindingRecord]:
        """Fresh exact immutable ledger rows in one PK batch, never per-origin SQL."""
        if not keys:
            return {}
        return {
            row.binding_sha256: row
            for row in self.session.scalars(
                select(EmbeddingSourceBindingRecord)
                .where(EmbeddingSourceBindingRecord.binding_sha256.in_(tuple(sorted(set(keys)))))
                .execution_options(populate_existing=True)
            )
        }

    def missing_bindings(
        self, keys: tuple[EmbeddingBindingLookupKey, ...]
    ) -> tuple[EmbeddingBindingLookupKey, ...]:
        if not keys:
            return ()
        candidates = (
            values(
                *(column(name, String()) for name in ASSOCIATION_COLUMNS),
                name="embedding_demands",
            )
            .data(tuple(key.columns() for key in keys))
            .alias("embedding_demands")
        )
        predicate = exists(
            select(1).where(
                *(
                    getattr(EmbeddingSourceBindingRecord, name) == candidates.c[name]
                    for name in ASSOCIATION_COLUMNS
                )
            )
        )
        found = self.session.execute(select(*candidates.c).where(~predicate)).all()
        missing = {tuple(str(value) for value in row) for row in found}
        return tuple(key for key in keys if key.columns() in missing)

    def insert_components(
        self,
        encodings: Sequence[dict[str, Any]],
        bindings: Sequence[dict[str, Any]],
    ) -> None:
        # Ignore only identical primary identities. Other uniqueness/FK errors remain errors.
        for model, rows, key in (
            (EmbeddingEncodingRecord, encodings, "encoding_sha256"),
            (EmbeddingSourceBindingRecord, bindings, "binding_sha256"),
        ):
            if rows:
                self.session.execute(
                    insert(model).values(list(rows)).on_conflict_do_nothing(index_elements=[key])
                )
        self.session.flush()

    def add_revision(self, row: EmbeddingIndexRevisionRecord) -> None:
        self.session.add(row)
        self.session.flush()

    def advance(self, command: RegisterEmbeddingIndexCommand, now: datetime) -> bool:
        result = self.session.execute(
            update(EmbeddingIndexRecord)
            .where(
                EmbeddingIndexRecord.index_id == command.index_id,
                EmbeddingIndexRecord.lock_version == command.expected_lock_version,
                EmbeddingIndexRecord.current_index_revision_id.is_not_distinct_from(
                    command.expected_current_index_revision_id
                ),
            )
            .values(
                current_index_revision_id=command.index_revision_id,
                lock_version=command.expected_lock_version + 1,
                updated_at=now,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1
