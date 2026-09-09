"""Serialized first-observation authority for exact PDF learning completion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn

from eom_catalog_contracts import SourceRelease
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from eom_catalog_service.pdf_learning_completion_models import (
    PdfLearningCompletionObservationRecord,
)
from eom_catalog_service.pdf_learning_completion_service import (
    PdfLearningCompletionObservation,
    PdfLearningCompletionRequest,
)


class PdfLearningCompletionObservationError(RuntimeError):
    """Stable conflict at the persisted first-observation boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PostgresPdfLearningCompletionObservationRegistry:
    """Persist/reload the first observation under one semantic advisory lock."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def claim(
        self,
        request: PdfLearningCompletionRequest,
        *,
        source_release: SourceRelease,
        completion_identity_sha256: str,
        mutable_fingerprint_sha256: str,
        observed_at_utc: datetime,
    ) -> PdfLearningCompletionObservation:
        if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() != UTC.utcoffset(
            observed_at_utc
        ):
            self._fail("PDF_LEARNING_COMPLETION_OBSERVATION_INVALID", "observation is not UTC")
        with self.sessions() as session, session.begin():
            self._lock(session, completion_identity_sha256)
            existing = session.get(
                PdfLearningCompletionObservationRecord, completion_identity_sha256
            )
            if existing is not None:
                self._require_exact(
                    existing,
                    request=request,
                    source_release=source_release,
                    mutable_fingerprint_sha256=mutable_fingerprint_sha256,
                )
                return self._value(existing)
            completion = request.corpus_completion
            row = PdfLearningCompletionObservationRecord(
                completion_identity_sha256=completion_identity_sha256,
                mutable_fingerprint_sha256=mutable_fingerprint_sha256,
                source_commit=source_release.git_commit,
                source_tree=source_release.git_tree,
                source_archive_sha256=source_release.git_archive_sha256,
                inventory_id=completion.inventory_id,
                inventory_sha256=completion.inventory_sha256,
                original_batch_id=completion.original_batch.extraction_batch_id,
                successor_batch_id=completion.successor_batch.extraction_batch_id,
                recovery_sha256=completion.recovery_sha256,
                coverage_id=completion.coverage_id,
                graph_snapshot_revision_id=request.graph_snapshot_revision_id,
                graph_snapshot_sha256=request.graph_snapshot_sha256,
                requested_by_operator_id=completion.requested_by,
                first_observed_at=observed_at_utc,
            )
            session.add(row)
            session.flush()
            return self._value(row)

    @staticmethod
    def _require_exact(
        row: PdfLearningCompletionObservationRecord,
        *,
        request: PdfLearningCompletionRequest,
        source_release: SourceRelease,
        mutable_fingerprint_sha256: str,
    ) -> None:
        completion = request.corpus_completion
        observed = (
            row.mutable_fingerprint_sha256,
            row.source_commit,
            row.source_tree,
            row.source_archive_sha256,
            row.inventory_id,
            row.inventory_sha256,
            row.original_batch_id,
            row.successor_batch_id,
            row.recovery_sha256,
            row.coverage_id,
            row.graph_snapshot_revision_id,
            row.graph_snapshot_sha256,
            row.requested_by_operator_id,
        )
        expected = (
            mutable_fingerprint_sha256,
            source_release.git_commit,
            source_release.git_tree,
            source_release.git_archive_sha256,
            completion.inventory_id,
            completion.inventory_sha256,
            completion.original_batch.extraction_batch_id,
            completion.successor_batch.extraction_batch_id,
            completion.recovery_sha256,
            completion.coverage_id,
            request.graph_snapshot_revision_id,
            request.graph_snapshot_sha256,
            completion.requested_by,
        )
        if observed != expected:
            raise PdfLearningCompletionObservationError(
                "PDF_LEARNING_COMPLETION_OBSERVATION_CONFLICT",
                "completion identity was previously observed with different authority",
            )

    @staticmethod
    def _value(
        row: PdfLearningCompletionObservationRecord,
    ) -> PdfLearningCompletionObservation:
        return PdfLearningCompletionObservation(
            completion_identity_sha256=row.completion_identity_sha256,
            mutable_fingerprint_sha256=row.mutable_fingerprint_sha256,
            first_observed_at_utc=row.first_observed_at.astimezone(UTC),
        )

    @staticmethod
    def _lock(session: Session, key: str) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "pdf-learning-completion-observation:" + key},
            )

    @staticmethod
    def _fail(code: str, message: str) -> NoReturn:
        raise PdfLearningCompletionObservationError(code, message)


__all__ = [
    "PdfLearningCompletionObservationError",
    "PostgresPdfLearningCompletionObservationRegistry",
]
