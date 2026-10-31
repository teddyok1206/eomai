"""Catalog-owned scalar embedding persistence; eligibility is never decided here."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast, overload

from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingBinding,
    SupportedEmbeddingNamespace,
    parse_supported_embedding_namespace,
)
from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingVectorRowRef,
)
from eom_catalog_contracts.mixed_embedding_index import RegisteredReviewEmbeddingSourceBinding
from eom_catalog_contracts.public_solution_embedding import AcceptedPublicSolutionEvidence
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionEmbeddingSourceBinding,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEvidence,
)
from eom_catalog_contracts.registered_public_solution_index import (
    RegisteredPublicSolutionSourceBinding,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Select, String, column, exists, select, tuple_, update, values
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
    PublicSolutionEmbeddingBindingLookupKey,
    RegisteredEmbeddingIndexRead,
    RegisteredReviewEmbeddingBindingLookupKey,
    SupportedEmbeddingBindingLookupKey,
    SupportedEmbeddingRegistrationCommand,
    embedding_binding_lookup_sort_key,
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
REGISTERED_REVIEW_ASSOCIATION_COLUMNS = (
    "item_revision_id",
    "graph_snapshot_revision_id",
    "policy_revision_id",
    "recipe_sha256",
    "view",
    "projection_version",
    "base_analysis_run_id",
    "profile_revision_id",
    "encoding_sha256",
    "review_job_id",
    "review_evidence_sha256",
)
PUBLIC_SOLUTION_ASSOCIATION_COLUMNS = (
    "item_revision_id",
    "graph_snapshot_revision_id",
    "policy_revision_id",
    "recipe_sha256",
    "view",
    "projection_version",
    "base_analysis_run_id",
    "profile_revision_id",
    "encoding_sha256",
    "solution_pointer_sha256",
)


def _binding_key_groups(
    keys: tuple[SupportedEmbeddingBindingLookupKey, ...],
) -> tuple[tuple[str, tuple[str, ...], tuple[SupportedEmbeddingBindingLookupKey, ...]], ...]:
    if not isinstance(keys, tuple) or len(keys) > (
        MAX_PUBLIC_SOLUTION_SOURCES
        if all(isinstance(value, PublicSolutionEmbeddingBindingLookupKey) for value in keys)
        else 1024
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")
    legacy: list[SupportedEmbeddingBindingLookupKey] = []
    registered: list[SupportedEmbeddingBindingLookupKey] = []
    public: list[SupportedEmbeddingBindingLookupKey] = []
    for key in keys:
        embedding_binding_lookup_sort_key(key)
        if type(key) is EmbeddingBindingLookupKey:
            selected = legacy
        elif type(key) is RegisteredReviewEmbeddingBindingLookupKey:
            selected = registered
        elif type(key) is PublicSolutionEmbeddingBindingLookupKey:
            selected = public
        else:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")
        selected.append(key)
    return tuple(
        (kind, columns, tuple(selected[offset : offset + 1024]))
        for kind, columns, selected in (
            ("ACCEPTED_SOLUTION_ANALYSIS", ASSOCIATION_COLUMNS, legacy),
            ("REGISTERED_ITEM_REVIEW_SOLUTION", REGISTERED_REVIEW_ASSOCIATION_COLUMNS, registered),
            ("PUBLIC_SOLUTION_REPORT", PUBLIC_SOLUTION_ASSOCIATION_COLUMNS, public),
        )
        if selected
        for offset in range(0, len(selected), 1024)
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


def binding_columns(
    binding: SupportedEmbeddingBinding,
) -> dict[str, Any]:
    """The one scalar projection stored by registration, not an eligibility decision."""
    result: dict[str, Any] = {
        "binding_sha256": binding.binding_sha256,
        "encoding_sha256": binding.encoding.encoding_sha256,
        "item_id": binding.source.item_id,
        "item_revision_id": binding.source.item_revision_id,
        "source_class": binding.source.source_class,
        "source_sha256": binding.source.artifact_member.sha256,
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
    if isinstance(
        binding, PublicSolutionEmbeddingSourceBinding | RegisteredPublicSolutionSourceBinding
    ):
        result.update(
            evidence_kind="PUBLIC_SOLUTION_REPORT",
            base_analysis_run_id=binding.base_analysis_run_id,
            solution_analysis_run_id=binding.evidence.solution.solution_analysis_run_id
            if isinstance(
                binding.evidence, AcceptedPublicSolutionEvidence | RegisteredPublicSolutionEvidence
            )
            else None,
            # This branch hashes its explicit public-evidence union, never
            # masquerading as a legacy KnowledgeSolutionEvidencePointer.
            solution_pointer_sha256=content_sha256(binding.evidence),
            review_job_id=None,
            review_evidence_sha256=None,
        )
    elif isinstance(binding, RegisteredReviewEmbeddingSourceBinding):
        result.update(
            evidence_kind="REGISTERED_ITEM_REVIEW_SOLUTION",
            base_analysis_run_id=binding.base_analysis_run_id,
            solution_analysis_run_id=None,
            solution_pointer_sha256=None,
            review_job_id=binding.review_evidence.review.job_id,
            review_evidence_sha256=binding.review_evidence.evidence_sha256,
        )
    else:
        result.update(
            evidence_kind="ACCEPTED_SOLUTION_ANALYSIS",
            base_analysis_run_id=binding.solution_evidence.base_analysis_run_id,
            solution_analysis_run_id=binding.solution_evidence.solution_analysis_run_id,
            solution_pointer_sha256=binding.solution_evidence.pointer_sha256,
            review_job_id=None,
            review_evidence_sha256=None,
        )
    return result


def _pinned_revision_select() -> Select[Any]:
    revision, index = EmbeddingIndexRevisionRecord, EmbeddingIndexRecord
    return select(
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
    ).join(index, index.index_id == revision.index_id)


def _registered_index_read(row: Any) -> RegisteredEmbeddingIndexRead:
    return RegisteredEmbeddingIndexRead(
        row.corpus_id,
        parse_supported_embedding_namespace(
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
        self, corpus_id: str, namespace: SupportedEmbeddingNamespace
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
        revision = EmbeddingIndexRevisionRecord
        row = self.session.execute(
            _pinned_revision_select().where(
                revision.index_id == index_id, revision.index_revision_id == revision_id
            )
        ).one_or_none()
        return None if row is None else _registered_index_read(row)

    def read_pinned_revisions(
        self, identities: tuple[tuple[str, str], ...]
    ) -> dict[tuple[str, str], RegisteredEmbeddingIndexRead]:
        """At most three immutable view pins in one exact indexed join, never latest."""
        if not 1 <= len(identities) <= 3 or len(set(identities)) != len(identities):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
        revision = EmbeddingIndexRevisionRecord
        rows = self.session.execute(
            _pinned_revision_select().where(
                tuple_(revision.index_id, revision.index_revision_id).in_(identities)
            )
        ).all()
        result = {
            (row.index_id, row.index_revision_id): _registered_index_read(row) for row in rows
        }
        if len(result) != len(rows):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
        return result

    def create_head(
        self,
        command: SupportedEmbeddingRegistrationCommand,
        now: datetime,
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
        self, keys: tuple[SupportedEmbeddingBindingLookupKey, ...]
    ) -> dict[str, EmbeddingSourceBindingRecord]:
        if not keys:
            return {}
        result: dict[str, EmbeddingSourceBindingRecord] = {}
        for family, names, selected in _binding_key_groups(keys):
            columns = tuple(getattr(EmbeddingSourceBindingRecord, name) for name in names)
            result.update(
                {
                    row.binding_sha256: row
                    for row in self.session.scalars(
                        select(EmbeddingSourceBindingRecord)
                        .where(
                            EmbeddingSourceBindingRecord.evidence_kind == family,
                            tuple_(*columns).in_(tuple(key.columns() for key in selected)),
                        )
                        .execution_options(populate_existing=True)
                    )
                }
            )
        return result

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

    @overload
    def missing_bindings(
        self, keys: tuple[EmbeddingBindingLookupKey, ...]
    ) -> tuple[EmbeddingBindingLookupKey, ...]: ...

    @overload
    def missing_bindings(
        self, keys: tuple[SupportedEmbeddingBindingLookupKey, ...]
    ) -> tuple[SupportedEmbeddingBindingLookupKey, ...]: ...

    def missing_bindings(
        self, keys: tuple[SupportedEmbeddingBindingLookupKey, ...]
    ) -> tuple[SupportedEmbeddingBindingLookupKey, ...]:
        if not keys:
            return ()
        missing: set[SupportedEmbeddingBindingLookupKey] = set()
        for family, names, selected in _binding_key_groups(keys):
            candidates = (
                values(*(column(name, String()) for name in names), name="embedding_demands")
                .data(tuple(key.columns() for key in selected))
                .alias("embedding_demands")
            )
            predicate = exists(
                select(1).where(
                    EmbeddingSourceBindingRecord.evidence_kind == family,
                    *(
                        getattr(EmbeddingSourceBindingRecord, name) == candidates.c[name]
                        for name in names
                    ),
                )
            )
            found = self.session.execute(select(*candidates.c).where(~predicate)).all()
            absent = {tuple(str(value) for value in row) for row in found}
            missing.update(key for key in selected if key.columns() in absent)
        return tuple(key for key in keys if key in missing)

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
            for offset in range(0, len(rows), 1024):
                self.session.execute(
                    insert(model)
                    .values(list(rows[offset : offset + 1024]))
                    .on_conflict_do_nothing(index_elements=[key])
                )
        self.session.flush()

    def add_revision(self, row: EmbeddingIndexRevisionRecord) -> None:
        self.session.add(row)
        self.session.flush()

    def advance(
        self,
        command: SupportedEmbeddingRegistrationCommand,
        now: datetime,
    ) -> bool:
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
