"""Review-gated import of immutable legacy Product/Form/Publication usage history."""

from __future__ import annotations

import re
import stat
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeVar, cast

from eom_catalog_contracts import (
    AssessmentAssemblyManifestV1,
    CommitLegacyUsageImportCommand,
    CreateLegacyUsageImportCommand,
    ItemPlacementV1,
    LegacyUsageFormValue,
    LegacyUsageImportManifest,
    LegacyUsageMappingContractRevision,
    LegacyUsagePlacementValue,
    LegacyUsageProposalState,
    LegacyUsagePublicationValue,
    LegacyUsageResolvedPointers,
    LegacyUsageReviewDecision,
    LegacyUsageRowProposal,
    LegacyUsageSourcePointer,
    ProductUsageGraphEdgeV1,
    ProductUsageGraphNodeV1,
    ProductUsageGraphProjectionV1,
    ReviewLegacyUsageRowCommand,
    validate_contract,
)
from eom_identifiers import content_sha256, sha256_file
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from pydantic import ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from eom_catalog_service.legacy_usage_models import (
    AssessmentAssemblyRecord,
    AssessmentAssemblyRevisionRecord,
    AssessmentFormRecord,
    AssessmentFormRevisionRecord,
    AssessmentItemPlacementRecord,
    LegacyUsageImportRecord,
    LegacyUsageMappingContractRecord,
    LegacyUsageMappingContractRevisionRecord,
    LegacyUsageRowProposalRecord,
    LegacyUsageRowReviewRecord,
    ProductUsageProjectionRecord,
    PublicationRecord,
    PublicationRevisionRecord,
    UsageRecordV1Record,
)
from eom_catalog_service.legacy_xlsx import DecodedLegacyUsageRow, read_legacy_usage_rows
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

_MAPPING_KEY = re.compile(r"^[a-z][a-z0-9._:-]{2,127}$")
_QUERY_CHUNK = 1000
_T = TypeVar("_T")
_ImportState = Literal["PROPOSED", "REVIEWED", "COMMITTED", "FAILED"]
_IMPORT_TRANSITIONS: dict[_ImportState, frozenset[_ImportState]] = {
    "PROPOSED": frozenset({"REVIEWED", "FAILED"}),
    "REVIEWED": frozenset({"COMMITTED", "FAILED"}),
    "COMMITTED": frozenset(),
    "FAILED": frozenset(),
}


class LegacyUsageError(RuntimeError):
    """Stable fail-closed error at the legacy usage application boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LegacyUsageProposalBatch:
    manifest: LegacyUsageImportManifest
    rows: tuple[LegacyUsageRowProposal, ...]


@dataclass(frozen=True)
class LegacyUsageCommitResult:
    legacy_usage_import_id: str
    commit_sha256: str
    form_revision_count: int
    placement_count: int
    publication_revision_count: int
    usage_record_count: int
    projection: ProductUsageGraphProjectionV1


@dataclass(frozen=True)
class _ResolvedSource:
    path: Path
    source: ContentIntakeSourceFileRecord
    revision: ArtifactRevisionRecord


class LegacyUsageService:
    """Own proposal, review, and atomic canonical commit boundaries."""

    def __init__(
        self,
        engine: Engine,
        *,
        settings: CatalogSettings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings or CatalogSettings.from_environment()
        self.clock = clock or (lambda: datetime.now(UTC))

    def release_mapping(
        self,
        mapping_key: str,
        mapping: LegacyUsageMappingContractRevision,
    ) -> LegacyUsageMappingContractRevisionRecord:
        """Register one immutable mapping revision and move only its logical current pointer."""

        if _MAPPING_KEY.fullmatch(mapping_key) is None:
            raise LegacyUsageError("LEGACY_USAGE_MAPPING_INVALID", "mapping key is invalid")
        document = mapping.model_dump(mode="json")
        self._validate_mapping_document(mapping, document)
        with transaction(self.sessions) as session:
            session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        _stable_lock_key("mapping", mapping.mapping_contract_id)
                    )
                )
            )
            logical = session.get(LegacyUsageMappingContractRecord, mapping.mapping_contract_id)
            if logical is None:
                logical = LegacyUsageMappingContractRecord(
                    mapping_contract_id=mapping.mapping_contract_id,
                    mapping_key=mapping_key,
                    current_revision_id=None,
                    created_by=mapping.released_by,
                )
                session.add(logical)
                session.flush()
            elif logical.mapping_key != mapping_key:
                raise LegacyUsageError(
                    "LEGACY_USAGE_MAPPING_CONFLICT", "mapping logical identity is inconsistent"
                )
            by_key = session.scalar(
                select(LegacyUsageMappingContractRecord).where(
                    LegacyUsageMappingContractRecord.mapping_key == mapping_key
                )
            )
            if by_key is not None and by_key.mapping_contract_id != mapping.mapping_contract_id:
                raise LegacyUsageError(
                    "LEGACY_USAGE_MAPPING_CONFLICT", "mapping key belongs to another identity"
                )
            existing = session.get(
                LegacyUsageMappingContractRevisionRecord,
                mapping.mapping_contract_revision_id,
            )
            if existing is not None:
                if (
                    existing.mapping_contract_id != mapping.mapping_contract_id
                    or existing.contract_sha256 != mapping.contract_sha256
                    or existing.canonical_document != document
                ):
                    raise LegacyUsageError(
                        "LEGACY_USAGE_MAPPING_CONFLICT",
                        "mapping revision identity has different immutable content",
                    )
                session.expunge(existing)
                return existing
            revision = LegacyUsageMappingContractRevisionRecord(
                mapping_contract_revision_id=mapping.mapping_contract_revision_id,
                mapping_contract_id=mapping.mapping_contract_id,
                revision_number=mapping.revision_number,
                state="RELEASED",
                contract_sha256=mapping.contract_sha256,
                canonical_document=document,
                released_at=mapping.released_at,
                released_by=mapping.released_by,
            )
            session.add(revision)
            session.flush()
            logical.current_revision_id = revision.mapping_contract_revision_id
            session.flush()
            session.expunge(revision)
            return revision

    def create_import(self, command: CreateLegacyUsageImportCommand) -> LegacyUsageProposalBatch:
        """Parse one exact workbook member and atomically persist bounded proposals."""

        with self.sessions() as session:
            replay = self._import_replay(session, command)
            if replay is not None:
                return replay
            mapping = self._resolve_mapping(session, command)
            resolved_source = self._resolve_source(session, command)
        rows = read_legacy_usage_rows(resolved_source.path, mapping)
        if sha256_file(resolved_source.path) != command.source.sha256:
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_HASH_MISMATCH", "workbook changed during bounded parsing"
            )
        import_id = _stable_id(
            "legacyimport",
            command.source.source_file_id,
            command.source.artifact_revision_id,
            command.mapping_contract_revision_id,
        )
        with transaction(self.sessions) as session:
            session.execute(
                select(func.pg_advisory_xact_lock(_stable_lock_key("import", import_id)))
            )
            replay = self._import_replay(session, command)
            if replay is not None:
                return replay
            # Re-resolve every database pointer after external parsing and before persistence.
            mapping = self._resolve_mapping(session, command)
            self._resolve_source(session, command)
            proposals = self._build_proposals(session, import_id, rows)
            counts: Counter[str] = Counter(str(row.proposal_state) for row in proposals)
            import_record = LegacyUsageImportRecord(
                legacy_usage_import_id=import_id,
                intake_batch_id=command.source.intake_batch_id,
                source_file_id=command.source.source_file_id,
                source_artifact_id=command.source.artifact_id,
                source_artifact_revision_id=command.source.artifact_revision_id,
                source_member_path=command.source.member_path,
                source_schema_ref=command.source.schema_ref,
                source_media_type=command.source.media_type,
                source_sha256=command.source.sha256,
                mapping_contract_revision_id=mapping.mapping_contract_revision_id,
                mapping_contract_sha256=mapping.contract_sha256,
                request_sha256=command.request_sha256,
                idempotency_key=command.idempotency_key,
                state="PROPOSED",
                row_count=len(proposals),
                resolved_count=counts["RESOLVED"],
                unresolved_count=counts["UNRESOLVED"],
                conflict_count=counts["CONFLICT"],
                rejected_count=counts["REJECTED"],
                commit_sha256=None,
                created_by=command.requested_by,
                committed_at=None,
                committed_by=None,
                lock_version=1,
            )
            session.add(import_record)
            session.add_all(
                LegacyUsageRowProposalRecord(
                    legacy_usage_row_id=proposal.legacy_usage_row_id,
                    legacy_usage_import_id=import_id,
                    source_row_key=proposal.source_row_key,
                    source_row_number=proposal.source_row_number,
                    normalized_row_sha256=proposal.normalized_row_sha256,
                    proposal_state=proposal.proposal_state,
                    canonical_document=proposal.model_dump(mode="json"),
                )
                for proposal in proposals
            )
            session.flush()
            manifest = self._manifest(import_record)
            validate_contract("legacy-usage-import-manifest", manifest.model_dump(mode="json"))
            return LegacyUsageProposalBatch(manifest=manifest, rows=proposals)

    def review_row(self, command: ReviewLegacyUsageRowCommand) -> LegacyUsageRowReviewRecord:
        """Append one immutable operator decision without modifying the proposal."""

        decision_sha256 = content_sha256(
            {
                "legacy_usage_row_id": command.legacy_usage_row_id,
                "decision": command.decision,
                "actor_id": command.actor_id,
            }
        )
        with transaction(self.sessions) as session:
            session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        _stable_lock_key(
                            "review-key",
                            command.idempotency_key,
                        )
                    )
                )
            )
            proposal = session.execute(
                select(LegacyUsageRowProposalRecord)
                .where(
                    LegacyUsageRowProposalRecord.legacy_usage_row_id == command.legacy_usage_row_id
                )
                .with_for_update()
            ).scalar_one_or_none()
            if proposal is None:
                raise LegacyUsageError(
                    "LEGACY_USAGE_ROW_NOT_FOUND", "legacy usage proposal does not exist"
                )
            by_key = session.scalar(
                select(LegacyUsageRowReviewRecord).where(
                    LegacyUsageRowReviewRecord.idempotency_key == command.idempotency_key
                )
            )
            existing = session.scalar(
                select(LegacyUsageRowReviewRecord).where(
                    LegacyUsageRowReviewRecord.legacy_usage_row_id == command.legacy_usage_row_id
                )
            )
            replay = by_key or existing
            if replay is not None:
                if (
                    replay.legacy_usage_row_id != command.legacy_usage_row_id
                    or replay.decision_sha256 != decision_sha256
                ):
                    raise LegacyUsageError(
                        "LEGACY_USAGE_REVIEW_IDEMPOTENCY_CONFLICT",
                        "review key or row already has a different decision",
                    )
                session.expunge(replay)
                return replay
            if command.decision == "APPROVE" and proposal.proposal_state != "RESOLVED":
                raise LegacyUsageError(
                    "LEGACY_USAGE_ROW_NOT_RESOLVED",
                    "only an exact resolved row can be approved",
                )
            now = self._utc_now()
            review = LegacyUsageRowReviewRecord(
                legacy_usage_review_id=_stable_id("legacyreview", command.legacy_usage_row_id),
                legacy_usage_row_id=command.legacy_usage_row_id,
                decision=command.decision,
                idempotency_key=command.idempotency_key,
                decision_sha256=decision_sha256,
                reviewed_at=now,
                reviewed_by=command.actor_id,
            )
            session.add(review)
            session.flush()
            import_record = session.execute(
                select(LegacyUsageImportRecord)
                .where(
                    LegacyUsageImportRecord.legacy_usage_import_id
                    == proposal.legacy_usage_import_id
                )
                .with_for_update()
            ).scalar_one()
            proposal_count = session.scalar(
                select(func.count(LegacyUsageRowProposalRecord.legacy_usage_row_id)).where(
                    LegacyUsageRowProposalRecord.legacy_usage_import_id
                    == import_record.legacy_usage_import_id
                )
            )
            review_count = session.scalar(
                select(func.count(LegacyUsageRowReviewRecord.legacy_usage_review_id))
                .join(LegacyUsageRowProposalRecord)
                .where(
                    LegacyUsageRowProposalRecord.legacy_usage_import_id
                    == import_record.legacy_usage_import_id
                )
            )
            if proposal_count == review_count and import_record.state == "PROPOSED":
                _transition_import(import_record, "REVIEWED")
            session.flush()
            session.expunge(review)
            return review

    def commit_import(self, command: CommitLegacyUsageImportCommand) -> LegacyUsageCommitResult:
        """Commit all reviewed rows as one immutable pointer chain and projection."""

        request_sha256 = content_sha256(
            command.model_dump(mode="json", exclude={"idempotency_key"})
        )
        with transaction(self.sessions) as session:
            import_record = session.execute(
                select(LegacyUsageImportRecord)
                .where(
                    LegacyUsageImportRecord.legacy_usage_import_id == command.legacy_usage_import_id
                )
                .with_for_update()
            ).scalar_one_or_none()
            if import_record is None:
                raise LegacyUsageError(
                    "LEGACY_USAGE_IMPORT_NOT_FOUND", "legacy usage import does not exist"
                )
            if import_record.state == "COMMITTED":
                if import_record.commit_sha256 != request_sha256:
                    raise LegacyUsageError(
                        "LEGACY_USAGE_COMMIT_IDEMPOTENCY_CONFLICT",
                        "committed import has a different immutable request",
                    )
                return self._committed_result(session, import_record)
            if import_record.state != "REVIEWED":
                raise LegacyUsageError(
                    "LEGACY_USAGE_IMPORT_NOT_REVIEWED",
                    "every row must have an immutable review before commit",
                )
            pairs = session.execute(
                select(LegacyUsageRowProposalRecord, LegacyUsageRowReviewRecord)
                .join(
                    LegacyUsageRowReviewRecord,
                    LegacyUsageRowReviewRecord.legacy_usage_row_id
                    == LegacyUsageRowProposalRecord.legacy_usage_row_id,
                )
                .where(
                    LegacyUsageRowProposalRecord.legacy_usage_import_id
                    == import_record.legacy_usage_import_id
                )
                .order_by(LegacyUsageRowProposalRecord.source_row_number)
            ).all()
            if len(pairs) != import_record.row_count:
                raise LegacyUsageError(
                    "LEGACY_USAGE_REVIEW_INCOMPLETE", "review cardinality is inconsistent"
                )
            approved = [
                LegacyUsageRowProposal.model_validate(proposal.canonical_document)
                for proposal, review in pairs
                if review.decision == "APPROVE"
            ]
            if any(row.proposal_state != "RESOLVED" for row in approved):
                raise LegacyUsageError(
                    "LEGACY_USAGE_REVIEW_INVALID", "an approved row is not resolved"
                )
            self._revalidate_approved_pointers(session, approved)
            now = self._utc_now()
            usage_rows = self._commit_groups(
                session, import_record, approved, command.actor_id, now
            )
            projection = self._projection(session, import_record, usage_rows)
            session.add(
                ProductUsageProjectionRecord(
                    legacy_usage_import_id=import_record.legacy_usage_import_id,
                    projection_sha256=projection.projection_sha256,
                    canonical_document=projection.model_dump(mode="json"),
                )
            )
            import_record.commit_sha256 = request_sha256
            import_record.committed_at = now
            import_record.committed_by = command.actor_id
            _transition_import(import_record, "COMMITTED")
            session.flush()
            return LegacyUsageCommitResult(
                legacy_usage_import_id=import_record.legacy_usage_import_id,
                commit_sha256=request_sha256,
                form_revision_count=len({row.assessment_form_revision_id for row in usage_rows}),
                placement_count=len(usage_rows),
                publication_revision_count=len({row.publication_revision_id for row in usage_rows}),
                usage_record_count=len(usage_rows),
                projection=projection,
            )

    @staticmethod
    def _validate_mapping_document(
        mapping: LegacyUsageMappingContractRevision, document: dict[str, Any]
    ) -> None:
        validate_contract("legacy-usage-mapping-contract", document)
        expected = content_sha256(
            {key: value for key, value in document.items() if key != "contract_sha256"}
        )
        if mapping.contract_sha256 != expected:
            raise LegacyUsageError(
                "LEGACY_USAGE_MAPPING_HASH_MISMATCH", "mapping contract hash is invalid"
            )

    def _resolve_mapping(
        self, session: Session, command: CreateLegacyUsageImportCommand
    ) -> LegacyUsageMappingContractRevision:
        record = session.get(
            LegacyUsageMappingContractRevisionRecord,
            command.mapping_contract_revision_id,
        )
        if (
            record is None
            or record.state != "RELEASED"
            or record.contract_sha256 != command.mapping_contract_sha256
        ):
            raise LegacyUsageError(
                "LEGACY_USAGE_MAPPING_STALE", "mapping contract revision is absent or stale"
            )
        try:
            validate_contract("legacy-usage-mapping-contract", record.canonical_document)
            mapping = LegacyUsageMappingContractRevision.model_validate(record.canonical_document)
        except (ValueError, ValidationError) as exc:
            raise LegacyUsageError(
                "LEGACY_USAGE_MAPPING_INVALID", "stored mapping contract is invalid"
            ) from exc
        self._validate_mapping_document(mapping, record.canonical_document)
        return mapping

    def _resolve_source(
        self, session: Session, command: CreateLegacyUsageImportCommand
    ) -> _ResolvedSource:
        pointer = command.source
        batch = session.get(ContentIntakeBatchRecord, pointer.intake_batch_id)
        source = session.get(ContentIntakeSourceFileRecord, pointer.source_file_id)
        logical = session.get(ArtifactRecord, pointer.artifact_id)
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        if batch is None or source is None or logical is None or revision is None:
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_NOT_FOUND", "source pointer does not resolve"
            )
        if batch.state not in {"ACCEPTED", "IMPORTED"}:
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_NOT_ACCEPTED", "source intake batch is not accepted"
            )
        if (
            source.intake_batch_id != batch.intake_batch_id
            or source.artifact_id != pointer.artifact_id
            or source.artifact_revision_id != pointer.artifact_revision_id
            or source.relative_path != pointer.member_path
            or source.media_type != pointer.media_type
            or source.sha256 != pointer.sha256
            or not logical.approved
            or not revision.approved
            or revision.logical_artifact_id != pointer.artifact_id
        ):
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_STALE", "source identity or lifecycle is inconsistent"
            )
        files = revision.manifest.get("files")
        matches = (
            [
                value
                for value in files
                if isinstance(value, dict) and value.get("file_name") == pointer.member_path
            ]
            if isinstance(files, list)
            else []
        )
        if len(matches) != 1 or (
            matches[0].get("sha256") != pointer.sha256
            or matches[0].get("schema_ref") != pointer.schema_ref
            or matches[0].get("media_type") != pointer.media_type
            or matches[0].get("bytes") != source.size_bytes
        ):
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_HASH_MISMATCH",
                "source Artifact member metadata is inconsistent",
            )
        path = self._artifact_member_path(revision, pointer.member_path)
        metadata = path.lstat()
        if metadata.st_size != source.size_bytes or sha256_file(path) != pointer.sha256:
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_HASH_MISMATCH", "source workbook bytes are stale"
            )
        return _ResolvedSource(path=path, source=source, revision=revision)

    def _artifact_member_path(self, revision: ArtifactRevisionRecord, member_path: str) -> Path:
        relative = PurePosixPath(member_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or "." in relative.parts
            or "\\" in member_path
        ):
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_PATH_INVALID", "source member path is unsafe"
            )
        try:
            allowed_root = self.settings.nas_artifact_root.resolve(strict=True)
            artifact_root = Path(revision.nas_path)
            root_metadata = artifact_root.lstat()
            if artifact_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
                raise OSError("artifact root is unsafe")
            resolved_root = artifact_root.resolve(strict=True)
            expected_root = allowed_root / revision.logical_artifact_id / revision.revision_id
            if resolved_root != expected_root:
                raise OSError("artifact root is not the canonical revision location")
            current = artifact_root
            for part in relative.parts:
                current = current / part
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise OSError("artifact member contains a symlink")
            metadata = current.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("artifact member is not regular")
            if not current.resolve(strict=True).is_relative_to(resolved_root):
                raise OSError("artifact member escapes its root")
        except OSError as exc:
            raise LegacyUsageError(
                "LEGACY_USAGE_SOURCE_PATH_INVALID", "source Artifact member is unsafe"
            ) from exc
        return current

    def _import_replay(
        self, session: Session, command: CreateLegacyUsageImportCommand
    ) -> LegacyUsageProposalBatch | None:
        by_key = session.scalar(
            select(LegacyUsageImportRecord).where(
                LegacyUsageImportRecord.idempotency_key == command.idempotency_key
            )
        )
        by_source = session.scalar(
            select(LegacyUsageImportRecord).where(
                LegacyUsageImportRecord.source_file_id == command.source.source_file_id,
                LegacyUsageImportRecord.source_artifact_revision_id
                == command.source.artifact_revision_id,
                LegacyUsageImportRecord.mapping_contract_revision_id
                == command.mapping_contract_revision_id,
            )
        )
        replay = by_key or by_source
        if replay is None:
            return None
        if (
            replay.source_file_id != command.source.source_file_id
            or replay.source_artifact_revision_id != command.source.artifact_revision_id
            or replay.mapping_contract_revision_id != command.mapping_contract_revision_id
            or replay.request_sha256 != command.request_sha256
        ):
            raise LegacyUsageError(
                "LEGACY_USAGE_IMPORT_IDEMPOTENCY_CONFLICT",
                "import key or source already has a different request",
            )
        rows = tuple(
            LegacyUsageRowProposal.model_validate(row.canonical_document)
            for row in session.scalars(
                select(LegacyUsageRowProposalRecord)
                .where(
                    LegacyUsageRowProposalRecord.legacy_usage_import_id
                    == replay.legacy_usage_import_id
                )
                .order_by(LegacyUsageRowProposalRecord.source_row_number)
            )
        )
        return LegacyUsageProposalBatch(manifest=self._manifest(replay), rows=rows)

    def _build_proposals(
        self,
        session: Session,
        import_id: str,
        rows: tuple[DecodedLegacyUsageRow, ...],
    ) -> tuple[LegacyUsageRowProposal, ...]:
        parsed = [self._parse_row(import_id, row) for row in rows]
        source_counts = Counter(row.source_row_key for row in parsed if row is not None)
        placement_counts = Counter(
            (
                row.resolved.assessment_form_revision_id,
                row.placement.section_key,
                row.placement.position,
            )
            for row in parsed
            if row is not None and row.resolved is not None and row.placement is not None
        )
        deliverables = self._records_by_id(
            session,
            DeliverableRecord,
            DeliverableRecord.deliverable_id,
            (row.resolved.deliverable_id for row in parsed if row and row.resolved),
        )
        deliverable_revisions = self._records_by_id(
            session,
            DeliverableRevisionRecord,
            DeliverableRevisionRecord.deliverable_revision_id,
            (row.resolved.deliverable_revision_id for row in parsed if row and row.resolved),
        )
        items = self._records_by_id(
            session,
            ItemRecord,
            ItemRecord.item_id,
            (row.resolved.item_id for row in parsed if row and row.resolved),
        )
        item_revisions = self._records_by_id(
            session,
            ItemRevisionRecord,
            ItemRevisionRecord.item_revision_id,
            (row.resolved.item_revision_id for row in parsed if row and row.resolved),
        )
        forms = self._records_by_id(
            session,
            AssessmentFormRecord,
            AssessmentFormRecord.assessment_form_id,
            (row.resolved.assessment_form_id for row in parsed if row and row.resolved),
        )
        form_revisions = self._records_by_id(
            session,
            AssessmentFormRevisionRecord,
            AssessmentFormRevisionRecord.assessment_form_revision_id,
            (row.resolved.assessment_form_revision_id for row in parsed if row and row.resolved),
        )
        publications = self._records_by_id(
            session,
            PublicationRecord,
            PublicationRecord.publication_id,
            (row.resolved.publication_id for row in parsed if row and row.resolved),
        )
        publication_revisions = self._records_by_id(
            session,
            PublicationRevisionRecord,
            PublicationRevisionRecord.publication_revision_id,
            (row.resolved.publication_revision_id for row in parsed if row and row.resolved),
        )
        output: list[LegacyUsageRowProposal] = []
        for decoded, candidate in zip(rows, parsed, strict=True):
            if candidate is None:
                output.append(self._quarantined(import_id, decoded, "REJECTED", "INVALID_VALUE"))
                continue
            if decoded.formula_fields:
                output.append(
                    self._quarantined(import_id, decoded, "REJECTED", "UNSUPPORTED_FORMULA")
                )
                continue
            assert candidate.resolved is not None
            assert candidate.form is not None
            assert candidate.placement is not None
            assert candidate.publication is not None
            resolved = candidate.resolved
            placement_key = (
                resolved.assessment_form_revision_id,
                candidate.placement.section_key,
                candidate.placement.position,
            )
            if source_counts[candidate.source_row_key] > 1:
                output.append(
                    self._quarantined(import_id, decoded, "CONFLICT", "DUPLICATE_SOURCE_ROW")
                )
                continue
            if placement_counts[placement_key] > 1:
                output.append(
                    self._quarantined(import_id, decoded, "CONFLICT", "DUPLICATE_PLACEMENT")
                )
                continue
            deliverable = deliverables.get(resolved.deliverable_id)
            deliverable_revision = deliverable_revisions.get(resolved.deliverable_revision_id)
            item = items.get(resolved.item_id)
            item_revision = item_revisions.get(resolved.item_revision_id)
            if (
                deliverable is None
                or deliverable_revision is None
                or item is None
                or item_revision is None
            ):
                output.append(
                    self._quarantined(import_id, decoded, "UNRESOLVED", "POINTER_NOT_FOUND")
                )
                continue
            if (
                deliverable_revision.deliverable_id != deliverable.deliverable_id
                or deliverable_revision.state != "RELEASED"
                or deliverable.lifecycle_state not in {"RELEASED", "ARCHIVED"}
                or item_revision.item_id != item.item_id
            ):
                output.append(
                    self._quarantined(
                        import_id,
                        decoded,
                        "CONFLICT",
                        "POINTER_OWNERSHIP_MISMATCH",
                    )
                )
                continue
            if item_revision.revision_state not in {"APPROVED", "SUPERSEDED"}:
                output.append(
                    self._quarantined(
                        import_id,
                        decoded,
                        "UNRESOLVED",
                        "ITEM_REVISION_NOT_APPROVED",
                    )
                )
                continue
            if item_revision.manifest_sha256 != resolved.item_manifest_sha256:
                output.append(
                    self._quarantined(import_id, decoded, "CONFLICT", "ITEM_HASH_MISMATCH")
                )
                continue
            form = forms.get(resolved.assessment_form_id)
            form_revision = form_revisions.get(resolved.assessment_form_revision_id)
            publication = publications.get(resolved.publication_id)
            publication_revision = publication_revisions.get(resolved.publication_revision_id)
            if (
                (form is not None and form.deliverable_id != resolved.deliverable_id)
                or (
                    form is not None
                    and form.current_revision_id not in {None, resolved.assessment_form_revision_id}
                )
                or (form_revision is None and candidate.form.revision_number != 1)
                or (
                    form_revision is not None
                    and (
                        form_revision.assessment_form_id != resolved.assessment_form_id
                        or form_revision.deliverable_revision_id != resolved.deliverable_revision_id
                        or form_revision.revision_number != candidate.form.revision_number
                    )
                )
                or (
                    publication is not None
                    and publication.assessment_form_id != resolved.assessment_form_id
                )
                or (
                    publication is not None
                    and publication.current_revision_id
                    not in {None, resolved.publication_revision_id}
                )
                or (publication_revision is None and candidate.publication.revision_number != 1)
                or (
                    publication_revision is not None
                    and (
                        publication_revision.publication_id != resolved.publication_id
                        or publication_revision.deliverable_revision_id
                        != resolved.deliverable_revision_id
                        or publication_revision.assessment_form_revision_id
                        != resolved.assessment_form_revision_id
                        or publication_revision.revision_number
                        != candidate.publication.revision_number
                    )
                )
            ):
                output.append(
                    self._quarantined(
                        import_id,
                        decoded,
                        "CONFLICT",
                        "POINTER_OWNERSHIP_MISMATCH",
                    )
                )
                continue
            if form_revision is not None or publication_revision is not None:
                output.append(
                    self._quarantined(
                        import_id,
                        decoded,
                        "CONFLICT",
                        "CANONICAL_TARGET_ALREADY_EXISTS",
                    )
                )
                continue
            output.append(candidate)
        return tuple(output)

    def _parse_row(
        self, import_id: str, row: DecodedLegacyUsageRow
    ) -> LegacyUsageRowProposal | None:
        values = row.values
        if any(not value for value in values.values()):
            return None
        normalized_sha = content_sha256(values)
        try:
            proposal = LegacyUsageRowProposal(
                schema_version="legacy-usage-row-proposal/1.0",
                legacy_usage_row_id=_stable_id(
                    "legacyrow", import_id, values["source_row_key"], row.row_number
                ),
                legacy_usage_import_id=import_id,
                source_row_key=values["source_row_key"],
                source_row_number=row.row_number,
                normalized_row_sha256=normalized_sha,
                proposal_state=LegacyUsageProposalState.RESOLVED,
                resolved=LegacyUsageResolvedPointers(
                    deliverable_id=values["deliverable_id"],
                    deliverable_revision_id=values["deliverable_revision_id"],
                    assessment_form_id=values["assessment_form_id"],
                    assessment_form_revision_id=values["assessment_form_revision_id"],
                    publication_id=values["publication_id"],
                    publication_revision_id=values["publication_revision_id"],
                    item_id=values["item_id"],
                    item_revision_id=values["item_revision_id"],
                    item_manifest_sha256=values["item_manifest_sha256"],
                ),
                form=LegacyUsageFormValue(
                    form_key=values["assessment_form_key"],
                    revision_number=int(values["assessment_form_revision_number"]),
                    ordinal=int(values["assessment_form_ordinal"]),
                    display_label=values["assessment_form_label"],
                ),
                placement=LegacyUsagePlacementValue(
                    section_key=values["section_key"],
                    section_ordinal=int(values["section_ordinal"]),
                    position=int(values["position"]),
                    display_number=values["display_number"],
                    points_milli=int(values["points_milli"]),
                    usage_role=cast(
                        Literal[
                            "PRIMARY",
                            "PRACTICE",
                            "REVIEW",
                            "EXAMPLE",
                            "OTHER_REVIEWED",
                        ],
                        values["usage_role"],
                    ),
                ),
                publication=LegacyUsagePublicationValue(
                    publication_key=values["publication_key"],
                    revision_number=int(values["publication_revision_number"]),
                    publication_date=date.fromisoformat(values["publication_date"]),
                ),
                candidate_revision_ids=(),
                reason_codes=(),
                review_decision=LegacyUsageReviewDecision.PENDING,
                reviewed_at=None,
                reviewed_by=None,
            )
        except (KeyError, ValueError, ValidationError):
            return None
        validate_contract("legacy-usage-row-proposal", proposal.model_dump(mode="json"))
        return proposal

    @staticmethod
    def _quarantined(
        import_id: str,
        row: DecodedLegacyUsageRow,
        state: str,
        reason: str,
    ) -> LegacyUsageRowProposal:
        source_key = row.values.get("source_row_key") or f"row-{row.row_number}"
        if re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", source_key) is None:
            source_key = f"row-{row.row_number}"
        return LegacyUsageRowProposal(
            schema_version="legacy-usage-row-proposal/1.0",
            legacy_usage_row_id=_stable_id("legacyrow", import_id, source_key, row.row_number),
            legacy_usage_import_id=import_id,
            source_row_key=source_key,
            source_row_number=row.row_number,
            normalized_row_sha256=content_sha256(row.values),
            proposal_state=LegacyUsageProposalState(state),
            resolved=None,
            form=None,
            placement=None,
            publication=None,
            candidate_revision_ids=(),
            reason_codes=(
                cast(
                    Literal[
                        "MISSING_REQUIRED_VALUE",
                        "INVALID_VALUE",
                        "POINTER_NOT_FOUND",
                        "POINTER_OWNERSHIP_MISMATCH",
                        "ITEM_REVISION_NOT_APPROVED",
                        "ITEM_HASH_MISMATCH",
                        "DUPLICATE_SOURCE_ROW",
                        "DUPLICATE_PLACEMENT",
                        "AMBIGUOUS_POINTER",
                        "CANONICAL_TARGET_ALREADY_EXISTS",
                        "UNSUPPORTED_FORMULA",
                    ],
                    reason,
                ),
            ),
            review_decision=LegacyUsageReviewDecision.PENDING,
            reviewed_at=None,
            reviewed_by=None,
        )

    @staticmethod
    def _records_by_id(
        session: Session,
        model: type[_T],
        column: Any,
        identifiers: Iterable[str],
    ) -> dict[str, _T]:
        values = sorted(set(identifiers))
        output: dict[str, _T] = {}
        for offset in range(0, len(values), _QUERY_CHUNK):
            for row in session.scalars(
                select(model).where(column.in_(values[offset : offset + _QUERY_CHUNK]))
            ):
                output[str(getattr(row, column.key))] = row
        return output

    def _revalidate_approved_pointers(
        self, session: Session, rows: list[LegacyUsageRowProposal]
    ) -> None:
        if not rows:
            return
        deliverables = self._records_by_id(
            session,
            DeliverableRevisionRecord,
            DeliverableRevisionRecord.deliverable_revision_id,
            (row.resolved.deliverable_revision_id for row in rows if row.resolved),
        )
        revisions = self._records_by_id(
            session,
            ItemRevisionRecord,
            ItemRevisionRecord.item_revision_id,
            (row.resolved.item_revision_id for row in rows if row.resolved),
        )
        products = self._records_by_id(
            session,
            DeliverableRecord,
            DeliverableRecord.deliverable_id,
            (row.resolved.deliverable_id for row in rows if row.resolved),
        )
        for row in rows:
            assert row.resolved is not None
            product = deliverables.get(row.resolved.deliverable_revision_id)
            logical_product = products.get(row.resolved.deliverable_id)
            item = revisions.get(row.resolved.item_revision_id)
            if (
                product is None
                or product.deliverable_id != row.resolved.deliverable_id
                or product.state != "RELEASED"
                or logical_product is None
                or logical_product.lifecycle_state not in {"RELEASED", "ARCHIVED"}
                or item is None
                or item.item_id != row.resolved.item_id
                or item.revision_state not in {"APPROVED", "SUPERSEDED"}
                or item.manifest_sha256 != row.resolved.item_manifest_sha256
            ):
                raise LegacyUsageError(
                    "LEGACY_USAGE_POINTER_STALE",
                    "an approved pointer changed before canonical commit",
                )

    def _commit_groups(
        self,
        session: Session,
        import_record: LegacyUsageImportRecord,
        approved: list[LegacyUsageRowProposal],
        actor_id: str,
        now: datetime,
    ) -> list[UsageRecordV1Record]:
        groups: dict[str, list[LegacyUsageRowProposal]] = defaultdict(list)
        for row in approved:
            assert row.resolved is not None
            groups[row.resolved.publication_revision_id].append(row)
        usage_rows: list[UsageRecordV1Record] = []
        for publication_revision_id in sorted(groups):
            rows = groups[publication_revision_id]
            first = rows[0]
            assert first.resolved and first.form and first.publication
            identity = (
                first.resolved.deliverable_id,
                first.resolved.deliverable_revision_id,
                first.resolved.assessment_form_id,
                first.resolved.assessment_form_revision_id,
                first.form,
                first.resolved.publication_id,
                first.resolved.publication_revision_id,
                first.publication,
            )
            if any(
                row.resolved is None
                or row.form is None
                or row.publication is None
                or (
                    row.resolved.deliverable_id,
                    row.resolved.deliverable_revision_id,
                    row.resolved.assessment_form_id,
                    row.resolved.assessment_form_revision_id,
                    row.form,
                    row.resolved.publication_id,
                    row.resolved.publication_revision_id,
                    row.publication,
                )
                != identity
                for row in rows
            ):
                raise LegacyUsageError(
                    "LEGACY_USAGE_GROUP_CONFLICT",
                    "publication rows do not share one exact form and product identity",
                )
            form = self._form(session, first, actor_id)
            assembly = self._assembly(session, form, first, actor_id)
            assembly_revision_id = _stable_id(
                "assemblyrev", first.resolved.assessment_form_revision_id
            )
            placements = self._placements(rows, assembly_revision_id)
            manifest = self._assembly_manifest(
                assembly,
                form,
                first,
                placements,
                import_record.created_at,
                actor_id,
            )
            self._persist_assembly_revision(session, assembly, manifest, actor_id, now)
            self._persist_placements(session, placements, manifest.assessment_assembly_revision_id)
            form_revision = self._persist_form_revision(
                session, form, first, manifest, actor_id, now
            )
            publication = self._publication(session, first, actor_id)
            publication_revision = self._persist_publication_revision(
                session,
                import_record,
                publication,
                form_revision,
                manifest,
                first,
                actor_id,
                now,
            )
            for row, placement in zip(sorted(rows, key=_proposal_order), placements, strict=True):
                assert row.resolved and row.placement
                detail = {
                    "contract_version": "usage-record/1.0",
                    "legacy_usage_import_id": import_record.legacy_usage_import_id,
                    "legacy_usage_row_id": row.legacy_usage_row_id,
                    "item_id": row.resolved.item_id,
                    "item_revision_id": row.resolved.item_revision_id,
                    "deliverable_id": row.resolved.deliverable_id,
                    "deliverable_revision_id": row.resolved.deliverable_revision_id,
                    "assessment_form_id": row.resolved.assessment_form_id,
                    "assessment_form_revision_id": row.resolved.assessment_form_revision_id,
                    "assessment_assembly_revision_id": manifest.assessment_assembly_revision_id,
                    "placement_id": placement.placement_id,
                    "publication_revision_id": publication_revision.publication_revision_id,
                    "section_key": row.placement.section_key,
                    "section_ordinal": row.placement.section_ordinal,
                    "position": row.placement.position,
                    "points_milli": row.placement.points_milli,
                    "usage_role": row.placement.usage_role,
                    "source_kind": "LEGACY_WORKBOOK",
                    "source_key": (f"{import_record.legacy_usage_import_id}:{row.source_row_key}"),
                    "source_hash": row.normalized_row_sha256,
                }
                usage = UsageRecordV1Record(
                    usage_record_id=_stable_id(
                        "usagerecord",
                        publication_revision.publication_revision_id,
                        placement.placement_id,
                    ),
                    detail_sha256=content_sha256(detail),
                    recorded_at=now,
                    recorded_by=actor_id,
                    **detail,
                )
                session.add(usage)
                usage_rows.append(usage)
        session.flush()
        return usage_rows

    @staticmethod
    def _form(session: Session, row: LegacyUsageRowProposal, actor_id: str) -> AssessmentFormRecord:
        assert row.resolved and row.form
        product = session.execute(
            select(DeliverableRecord)
            .where(DeliverableRecord.deliverable_id == row.resolved.deliverable_id)
            .with_for_update()
        ).scalar_one_or_none()
        if product is None:
            raise LegacyUsageError(
                "LEGACY_USAGE_POINTER_STALE", "product disappeared before form commit"
            )
        form = session.execute(
            select(AssessmentFormRecord)
            .where(AssessmentFormRecord.assessment_form_id == row.resolved.assessment_form_id)
            .with_for_update()
        ).scalar_one_or_none()
        if form is None:
            form = AssessmentFormRecord(
                assessment_form_id=row.resolved.assessment_form_id,
                deliverable_id=row.resolved.deliverable_id,
                form_key=row.form.form_key,
                current_revision_id=None,
                lifecycle_state="ACTIVE",
                created_by=actor_id,
            )
            session.add(form)
            session.flush()
        elif (
            form.deliverable_id != row.resolved.deliverable_id or form.form_key != row.form.form_key
        ):
            raise LegacyUsageError(
                "LEGACY_USAGE_FORM_CONFLICT", "form identity has different immutable ownership"
            )
        return form

    @staticmethod
    def _assembly(
        session: Session,
        form: AssessmentFormRecord,
        row: LegacyUsageRowProposal,
        actor_id: str,
    ) -> AssessmentAssemblyRecord:
        assembly_id = _stable_id("assembly", form.assessment_form_id)
        assembly = session.execute(
            select(AssessmentAssemblyRecord)
            .where(AssessmentAssemblyRecord.assessment_assembly_id == assembly_id)
            .with_for_update()
        ).scalar_one_or_none()
        if assembly is None:
            assembly = AssessmentAssemblyRecord(
                assessment_assembly_id=assembly_id,
                assessment_form_id=form.assessment_form_id,
                current_revision_id=None,
                created_by=actor_id,
            )
            session.add(assembly)
            session.flush()
        elif assembly.assessment_form_id != row.resolved.assessment_form_id:  # type: ignore[union-attr]
            raise LegacyUsageError(
                "LEGACY_USAGE_ASSEMBLY_CONFLICT", "assembly belongs to another form"
            )
        return assembly

    @staticmethod
    def _placements(
        rows: list[LegacyUsageRowProposal], assembly_revision_id: str
    ) -> tuple[ItemPlacementV1, ...]:
        values: list[ItemPlacementV1] = []
        for row in sorted(rows, key=_proposal_order):
            assert row.resolved and row.placement
            values.append(
                ItemPlacementV1(
                    placement_id=_stable_id("placement", assembly_revision_id, row.source_row_key),
                    section_key=row.placement.section_key,
                    section_ordinal=row.placement.section_ordinal,
                    position=row.placement.position,
                    display_number=row.placement.display_number,
                    item_id=row.resolved.item_id,
                    item_revision_id=row.resolved.item_revision_id,
                    item_manifest_sha256=row.resolved.item_manifest_sha256,
                    points_milli=row.placement.points_milli,
                    usage_role=row.placement.usage_role,
                    source_usage_plan_id=None,
                )
            )
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.section_ordinal,
                    item.position,
                    item.placement_id,
                ),
            )
        )

    @staticmethod
    def _assembly_manifest(
        assembly: AssessmentAssemblyRecord,
        form: AssessmentFormRecord,
        row: LegacyUsageRowProposal,
        placements: tuple[ItemPlacementV1, ...],
        created_at: datetime,
        actor_id: str,
    ) -> AssessmentAssemblyManifestV1:
        assert row.resolved and row.form
        revision_id = _stable_id("assemblyrev", row.resolved.assessment_form_revision_id)
        value: dict[str, Any] = {
            "schema_version": "assessment-assembly-manifest/1.0",
            "assessment_assembly_revision_id": revision_id,
            "assessment_assembly_id": assembly.assessment_assembly_id,
            "revision_number": row.form.revision_number,
            "previous_revision_id": None,
            "assessment_form_id": form.assessment_form_id,
            "placements": [item.model_dump(mode="json") for item in placements],
            "total_points_milli": sum(item.points_milli for item in placements),
            "revision_state": "RELEASED",
            "manifest_sha256": "sha256:" + "0" * 64,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "created_by": actor_id,
        }
        value["manifest_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "manifest_sha256"}
        )
        validate_contract("assessment-assembly-manifest", value)
        return AssessmentAssemblyManifestV1.model_validate(value)

    @staticmethod
    def _persist_assembly_revision(
        session: Session,
        assembly: AssessmentAssemblyRecord,
        manifest: AssessmentAssemblyManifestV1,
        actor_id: str,
        now: datetime,
    ) -> None:
        existing = session.get(
            AssessmentAssemblyRevisionRecord,
            manifest.assessment_assembly_revision_id,
        )
        document = manifest.model_dump(mode="json")
        if existing is not None:
            if (
                existing.assessment_assembly_id != assembly.assessment_assembly_id
                or existing.manifest_sha256 != manifest.manifest_sha256
                or existing.canonical_document != document
            ):
                raise LegacyUsageError(
                    "LEGACY_USAGE_ASSEMBLY_CONFLICT", "assembly revision content differs"
                )
            if assembly.current_revision_id not in {
                None,
                manifest.assessment_assembly_revision_id,
            }:
                raise LegacyUsageError(
                    "LEGACY_USAGE_ASSEMBLY_CONFLICT",
                    "assembly current revision points elsewhere",
                )
            assembly.current_revision_id = manifest.assessment_assembly_revision_id
            return
        session.add(
            AssessmentAssemblyRevisionRecord(
                assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
                assessment_assembly_id=manifest.assessment_assembly_id,
                assessment_form_id=manifest.assessment_form_id,
                revision_number=manifest.revision_number,
                previous_revision_id=manifest.previous_revision_id,
                revision_state="RELEASED",
                total_points_milli=manifest.total_points_milli,
                manifest_sha256=manifest.manifest_sha256,
                canonical_document=document,
                created_at=manifest.created_at,
                created_by=actor_id,
                released_at=now,
            )
        )
        session.flush()
        assembly.current_revision_id = manifest.assessment_assembly_revision_id

    @staticmethod
    def _persist_placements(
        session: Session,
        placements: tuple[ItemPlacementV1, ...],
        assessment_assembly_revision_id: str,
    ) -> None:
        for value in placements:
            existing = session.get(AssessmentItemPlacementRecord, value.placement_id)
            document = value.model_dump(mode="json")
            if existing is not None:
                actual = {key: getattr(existing, key) for key in document}
                if (
                    existing.assessment_assembly_revision_id != assessment_assembly_revision_id
                    or actual != document
                ):
                    raise LegacyUsageError(
                        "LEGACY_USAGE_PLACEMENT_CONFLICT", "placement content differs"
                    )
                continue
            session.add(
                AssessmentItemPlacementRecord(
                    assessment_assembly_revision_id=assessment_assembly_revision_id,
                    **document,
                )
            )
        session.flush()

    @staticmethod
    def _persist_form_revision(
        session: Session,
        form: AssessmentFormRecord,
        row: LegacyUsageRowProposal,
        manifest: AssessmentAssemblyManifestV1,
        actor_id: str,
        now: datetime,
    ) -> AssessmentFormRevisionRecord:
        assert row.resolved and row.form
        content = {
            "assessment_form_revision_id": row.resolved.assessment_form_revision_id,
            "assessment_form_id": row.resolved.assessment_form_id,
            "revision_number": row.form.revision_number,
            "previous_revision_id": None,
            "deliverable_revision_id": row.resolved.deliverable_revision_id,
            "ordinal": row.form.ordinal,
            "display_label": row.form.display_label,
            "assessment_assembly_revision_id": manifest.assessment_assembly_revision_id,
            "revision_state": "RELEASED",
            "assembly_manifest_sha256": manifest.manifest_sha256,
        }
        digest = content_sha256(content)
        existing = session.get(
            AssessmentFormRevisionRecord, row.resolved.assessment_form_revision_id
        )
        if existing is not None:
            if (
                existing.assessment_form_id != row.resolved.assessment_form_id
                or existing.deliverable_revision_id != row.resolved.deliverable_revision_id
                or existing.revision_number != row.form.revision_number
                or existing.ordinal != row.form.ordinal
                or existing.display_label != row.form.display_label
                or existing.assessment_assembly_revision_id
                != manifest.assessment_assembly_revision_id
                or existing.revision_sha256 != digest
            ):
                raise LegacyUsageError(
                    "LEGACY_USAGE_FORM_CONFLICT", "form revision content differs"
                )
            if form.current_revision_id not in {
                None,
                existing.assessment_form_revision_id,
            }:
                raise LegacyUsageError(
                    "LEGACY_USAGE_FORM_CONFLICT", "form current revision points elsewhere"
                )
            form.current_revision_id = existing.assessment_form_revision_id
        else:
            existing = AssessmentFormRevisionRecord(
                assessment_form_revision_id=row.resolved.assessment_form_revision_id,
                assessment_form_id=row.resolved.assessment_form_id,
                revision_number=row.form.revision_number,
                previous_revision_id=None,
                deliverable_revision_id=row.resolved.deliverable_revision_id,
                ordinal=row.form.ordinal,
                display_label=row.form.display_label,
                assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
                revision_state="RELEASED",
                revision_sha256=digest,
                created_by=actor_id,
                released_at=now,
            )
            session.add(existing)
            session.flush()
            form.current_revision_id = existing.assessment_form_revision_id
        return existing

    @staticmethod
    def _publication(
        session: Session, row: LegacyUsageRowProposal, actor_id: str
    ) -> PublicationRecord:
        assert row.resolved and row.publication
        locked_form = session.execute(
            select(AssessmentFormRecord)
            .where(AssessmentFormRecord.assessment_form_id == row.resolved.assessment_form_id)
            .with_for_update()
        ).scalar_one_or_none()
        if locked_form is None:
            raise LegacyUsageError(
                "LEGACY_USAGE_POINTER_STALE", "form disappeared before publication commit"
            )
        publication = session.execute(
            select(PublicationRecord)
            .where(PublicationRecord.publication_id == row.resolved.publication_id)
            .with_for_update()
        ).scalar_one_or_none()
        if publication is None:
            publication = PublicationRecord(
                publication_id=row.resolved.publication_id,
                assessment_form_id=row.resolved.assessment_form_id,
                publication_key=row.publication.publication_key,
                current_revision_id=None,
                lifecycle_state="ACTIVE",
                created_by=actor_id,
            )
            session.add(publication)
            session.flush()
        elif (
            publication.assessment_form_id != row.resolved.assessment_form_id
            or publication.publication_key != row.publication.publication_key
        ):
            raise LegacyUsageError(
                "LEGACY_USAGE_PUBLICATION_CONFLICT",
                "publication identity has different immutable ownership",
            )
        return publication

    @staticmethod
    def _persist_publication_revision(
        session: Session,
        import_record: LegacyUsageImportRecord,
        publication: PublicationRecord,
        form_revision: AssessmentFormRevisionRecord,
        manifest: AssessmentAssemblyManifestV1,
        row: LegacyUsageRowProposal,
        actor_id: str,
        now: datetime,
    ) -> PublicationRevisionRecord:
        assert row.resolved and row.publication
        content = {
            "publication_revision_id": row.resolved.publication_revision_id,
            "publication_id": row.resolved.publication_id,
            "revision_number": row.publication.revision_number,
            "deliverable_revision_id": row.resolved.deliverable_revision_id,
            "assessment_form_revision_id": form_revision.assessment_form_revision_id,
            "assessment_assembly_revision_id": manifest.assessment_assembly_revision_id,
            "assembly_manifest_sha256": manifest.manifest_sha256,
            "publication_date": row.publication.publication_date.isoformat(),
            "source_kind": "LEGACY_WORKBOOK",
            "source_artifact_id": import_record.source_artifact_id,
            "source_artifact_revision_id": import_record.source_artifact_revision_id,
            "source_sha256": import_record.source_sha256,
        }
        digest = content_sha256(content)
        existing = session.get(PublicationRevisionRecord, row.resolved.publication_revision_id)
        if existing is not None:
            if existing.publication_sha256 != digest:
                raise LegacyUsageError(
                    "LEGACY_USAGE_PUBLICATION_CONFLICT",
                    "publication revision content differs",
                )
            if publication.current_revision_id not in {
                None,
                existing.publication_revision_id,
            }:
                raise LegacyUsageError(
                    "LEGACY_USAGE_PUBLICATION_CONFLICT",
                    "publication current revision points elsewhere",
                )
            publication.current_revision_id = existing.publication_revision_id
            return existing
        existing = PublicationRevisionRecord(
            publication_revision_id=row.resolved.publication_revision_id,
            publication_id=row.resolved.publication_id,
            revision_number=row.publication.revision_number,
            deliverable_revision_id=row.resolved.deliverable_revision_id,
            assessment_form_revision_id=form_revision.assessment_form_revision_id,
            assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
            assembly_manifest_sha256=manifest.manifest_sha256,
            publication_date=row.publication.publication_date,
            revision_state="RELEASED",
            publication_sha256=digest,
            source_kind="LEGACY_WORKBOOK",
            source_artifact_id=import_record.source_artifact_id,
            source_artifact_revision_id=import_record.source_artifact_revision_id,
            source_sha256=import_record.source_sha256,
            created_by=actor_id,
            published_at=now,
        )
        session.add(existing)
        session.flush()
        publication.current_revision_id = existing.publication_revision_id
        return existing

    @staticmethod
    def _projection(
        session: Session,
        import_record: LegacyUsageImportRecord,
        usage_rows: list[UsageRecordV1Record],
    ) -> ProductUsageGraphProjectionV1:
        product_revisions = LegacyUsageService._records_by_id(
            session,
            DeliverableRevisionRecord,
            DeliverableRevisionRecord.deliverable_revision_id,
            (row.deliverable_revision_id for row in usage_rows),
        )
        form_revisions = LegacyUsageService._records_by_id(
            session,
            AssessmentFormRevisionRecord,
            AssessmentFormRevisionRecord.assessment_form_revision_id,
            (row.assessment_form_revision_id for row in usage_rows),
        )
        assembly_revisions = LegacyUsageService._records_by_id(
            session,
            AssessmentAssemblyRevisionRecord,
            AssessmentAssemblyRevisionRecord.assessment_assembly_revision_id,
            (row.assessment_assembly_revision_id for row in usage_rows),
        )
        publication_revisions = LegacyUsageService._records_by_id(
            session,
            PublicationRevisionRecord,
            PublicationRevisionRecord.publication_revision_id,
            (row.publication_revision_id for row in usage_rows),
        )
        item_revisions = LegacyUsageService._records_by_id(
            session,
            ItemRevisionRecord,
            ItemRevisionRecord.item_revision_id,
            (row.item_revision_id for row in usage_rows),
        )
        placements = LegacyUsageService._records_by_id(
            session,
            AssessmentItemPlacementRecord,
            AssessmentItemPlacementRecord.placement_id,
            (row.placement_id for row in usage_rows),
        )
        nodes: dict[str, ProductUsageGraphNodeV1] = {}
        edges: dict[str, ProductUsageGraphEdgeV1] = {}
        for usage in usage_rows:
            product_revision = product_revisions.get(usage.deliverable_revision_id)
            form_revision = form_revisions.get(usage.assessment_form_revision_id)
            assembly_revision = assembly_revisions.get(usage.assessment_assembly_revision_id)
            publication_revision = publication_revisions.get(usage.publication_revision_id)
            item_revision = item_revisions.get(usage.item_revision_id)
            placement = placements.get(usage.placement_id)
            if any(
                value is None
                for value in (
                    product_revision,
                    form_revision,
                    assembly_revision,
                    publication_revision,
                    item_revision,
                    placement,
                )
            ):
                raise LegacyUsageError(
                    "LEGACY_USAGE_PROJECTION_POINTER_MISSING",
                    "canonical projection source pointer is missing",
                )
            assert product_revision is not None
            assert form_revision is not None
            assert assembly_revision is not None
            assert publication_revision is not None
            assert item_revision is not None
            assert placement is not None
            placement_sha256 = content_sha256(
                {
                    "placement_id": placement.placement_id,
                    "assessment_assembly_revision_id": (placement.assessment_assembly_revision_id),
                    "section_key": placement.section_key,
                    "section_ordinal": placement.section_ordinal,
                    "position": placement.position,
                    "display_number": placement.display_number,
                    "item_id": placement.item_id,
                    "item_revision_id": placement.item_revision_id,
                    "item_manifest_sha256": placement.item_manifest_sha256,
                    "points_milli": placement.points_milli,
                    "usage_role": placement.usage_role,
                    "source_usage_plan_id": placement.source_usage_plan_id,
                }
            )
            identities = (
                (
                    "PRODUCT_REVISION",
                    usage.deliverable_id,
                    usage.deliverable_revision_id,
                    product_revision.metadata_sha256,
                ),
                (
                    "FORM_REVISION",
                    usage.assessment_form_id,
                    usage.assessment_form_revision_id,
                    form_revision.revision_sha256,
                ),
                (
                    "ASSEMBLY_REVISION",
                    usage.assessment_form_id,
                    usage.assessment_assembly_revision_id,
                    assembly_revision.manifest_sha256,
                ),
                (
                    "PUBLICATION_REVISION",
                    usage.publication_revision_id,
                    usage.publication_revision_id,
                    publication_revision.publication_sha256,
                ),
                (
                    "ITEM_REVISION",
                    usage.item_id,
                    usage.item_revision_id,
                    item_revision.manifest_sha256,
                ),
                (
                    "USAGE_RECORD",
                    usage.usage_record_id,
                    usage.usage_record_id,
                    usage.detail_sha256,
                ),
            )
            by_type: dict[str, ProductUsageGraphNodeV1] = {}
            for node_type, logical_id, revision_id, source_hash in identities:
                node_id = _stable_id("pnode", node_type, revision_id)
                node = ProductUsageGraphNodeV1(
                    node_id=node_id,
                    node_type=cast(
                        Literal[
                            "PRODUCT_REVISION",
                            "FORM_REVISION",
                            "ASSEMBLY_REVISION",
                            "PUBLICATION_REVISION",
                            "ITEM_REVISION",
                            "USAGE_RECORD",
                        ],
                        node_type,
                    ),
                    logical_id=logical_id,
                    revision_id=revision_id,
                    source_sha256=source_hash,
                )
                prior = nodes.get(node_id)
                if prior is not None and prior != node:
                    raise LegacyUsageError(
                        "LEGACY_USAGE_PROJECTION_CONFLICT", "graph node content differs"
                    )
                nodes[node_id] = node
                by_type[node_type] = node
            relationships = (
                (
                    "PRODUCT_HAS_FORM",
                    "PRODUCT_REVISION",
                    "FORM_REVISION",
                    form_revision.assessment_form_revision_id,
                    form_revision.revision_sha256,
                ),
                (
                    "FORM_HAS_ASSEMBLY",
                    "FORM_REVISION",
                    "ASSEMBLY_REVISION",
                    assembly_revision.assessment_assembly_revision_id,
                    assembly_revision.manifest_sha256,
                ),
                (
                    "ASSEMBLY_PLACES_ITEM",
                    "ASSEMBLY_REVISION",
                    "ITEM_REVISION",
                    usage.placement_id,
                    placement_sha256,
                ),
                (
                    "PUBLICATION_RELEASES_ASSEMBLY",
                    "PUBLICATION_REVISION",
                    "ASSEMBLY_REVISION",
                    usage.publication_revision_id,
                    publication_revision.publication_sha256,
                ),
                (
                    "USAGE_RECORDS_ITEM",
                    "USAGE_RECORD",
                    "ITEM_REVISION",
                    usage.usage_record_id,
                    usage.detail_sha256,
                ),
                (
                    "USAGE_IN_PUBLICATION",
                    "USAGE_RECORD",
                    "PUBLICATION_REVISION",
                    usage.usage_record_id,
                    usage.detail_sha256,
                ),
            )
            for edge_type, source_type, target_type, source_id, source_hash in relationships:
                edge_id = _stable_id(
                    "pedge", edge_type, by_type[source_type].node_id, by_type[target_type].node_id
                )
                edges[edge_id] = ProductUsageGraphEdgeV1(
                    edge_id=edge_id,
                    edge_type=cast(
                        Literal[
                            "PRODUCT_HAS_FORM",
                            "FORM_HAS_ASSEMBLY",
                            "ASSEMBLY_PLACES_ITEM",
                            "PUBLICATION_RELEASES_ASSEMBLY",
                            "USAGE_RECORDS_ITEM",
                            "USAGE_IN_PUBLICATION",
                        ],
                        edge_type,
                    ),
                    from_node_id=by_type[source_type].node_id,
                    to_node_id=by_type[target_type].node_id,
                    source_record_id=source_id,
                    source_sha256=source_hash,
                )
        value: dict[str, Any] = {
            "schema_version": "product-usage-graph-projection/1.0",
            "nodes": [nodes[key].model_dump(mode="json") for key in sorted(nodes)],
            "edges": [edges[key].model_dump(mode="json") for key in sorted(edges)],
            "projection_sha256": "sha256:" + "0" * 64,
            "created_at": import_record.created_at.isoformat().replace("+00:00", "Z"),
        }
        value["projection_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "projection_sha256"}
        )
        validate_contract("product-usage-graph-projection", value)
        return ProductUsageGraphProjectionV1.model_validate(value)

    def _committed_result(
        self, session: Session, import_record: LegacyUsageImportRecord
    ) -> LegacyUsageCommitResult:
        projection_row = session.scalar(
            select(ProductUsageProjectionRecord).where(
                ProductUsageProjectionRecord.legacy_usage_import_id
                == import_record.legacy_usage_import_id
            )
        )
        if projection_row is None:
            raise LegacyUsageError(
                "LEGACY_USAGE_COMMIT_CORRUPT", "committed import projection is missing"
            )
        projection = ProductUsageGraphProjectionV1.model_validate(projection_row.canonical_document)
        usages = list(
            session.scalars(
                select(UsageRecordV1Record).where(
                    UsageRecordV1Record.legacy_usage_import_id
                    == import_record.legacy_usage_import_id
                )
            )
        )
        return LegacyUsageCommitResult(
            legacy_usage_import_id=import_record.legacy_usage_import_id,
            commit_sha256=import_record.commit_sha256 or "",
            form_revision_count=len({row.assessment_form_revision_id for row in usages}),
            placement_count=len(usages),
            publication_revision_count=len({row.publication_revision_id for row in usages}),
            usage_record_count=len(usages),
            projection=projection,
        )

    @staticmethod
    def _manifest(record: LegacyUsageImportRecord) -> LegacyUsageImportManifest:
        return LegacyUsageImportManifest(
            schema_version="legacy-usage-import-manifest/1.0",
            legacy_usage_import_id=record.legacy_usage_import_id,
            source=LegacyUsageSourcePointer(
                intake_batch_id=record.intake_batch_id,
                source_file_id=record.source_file_id,
                artifact_id=record.source_artifact_id,
                artifact_revision_id=record.source_artifact_revision_id,
                member_path=record.source_member_path,
                schema_ref=cast(
                    Literal["eom://schemas/legacy-usage/workbook/1.0"],
                    record.source_schema_ref,
                ),
                media_type=cast(
                    Literal["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                    record.source_media_type,
                ),
                sha256=record.source_sha256,
            ),
            mapping_contract_revision_id=record.mapping_contract_revision_id,
            mapping_contract_sha256=record.mapping_contract_sha256,
            request_sha256=record.request_sha256,
            state=cast(
                Literal["PROPOSED", "REVIEWED", "COMMITTED", "FAILED"],
                record.state,
            ),
            row_count=record.row_count,
            resolved_count=record.resolved_count,
            unresolved_count=record.unresolved_count,
            conflict_count=record.conflict_count,
            rejected_count=record.rejected_count,
            created_at=record.created_at,
            created_by=record.created_by,
        )

    def _utc_now(self) -> datetime:
        value = self.clock()
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise LegacyUsageError("LEGACY_USAGE_CLOCK_INVALID", "clock must return UTC")
        return value.astimezone(UTC)


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{content_sha256(parts).removeprefix('sha256:')[:32]}"


def _stable_lock_key(*parts: object) -> int:
    value = int(content_sha256(parts).removeprefix("sha256:")[:16], 16)
    return value - 2**64 if value >= 2**63 else value


def _transition_import(record: LegacyUsageImportRecord, target: _ImportState) -> None:
    current = cast(_ImportState, record.state)
    if current not in _IMPORT_TRANSITIONS or target not in _IMPORT_TRANSITIONS[current]:
        raise LegacyUsageError(
            "LEGACY_USAGE_IMPORT_TRANSITION_INVALID",
            f"legacy usage import cannot transition from {current} to {target}",
        )
    record.state = target
    record.lock_version += 1


def _proposal_order(row: LegacyUsageRowProposal) -> tuple[int, int, str]:
    assert row.placement is not None
    return row.placement.section_ordinal, row.placement.position, row.legacy_usage_row_id
