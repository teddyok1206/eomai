"""Catalog-owned scalar embedding persistence; eligibility is never decided here."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from eom_catalog_contracts.embedding_registry import RegisterEmbeddingIndexCommand
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
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
