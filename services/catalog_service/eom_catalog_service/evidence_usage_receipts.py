"""Read-side validation of orchestrator-issued evidence-usage receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eom_identifiers import content_sha256
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_protocol import ArtifactManifest
from eom_workflow import (
    ArtifactPointer,
    AuthoringEvidenceUsageValidationReceipt,
    EvidenceResultArtifactPointer,
    ReviewEvidenceUsageValidationReceipt,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class EvidenceUsageReceiptResolutionError(RuntimeError):
    """Stable failure for a missing, stale, or mismatched trusted receipt."""


@dataclass(frozen=True)
class EvidenceUsageReceiptPair:
    """Exact authoring/review receipts for one Graph-grounded workflow."""

    authoring: AuthoringEvidenceUsageValidationReceipt
    review: ReviewEvidenceUsageValidationReceipt


class EvidenceUsageReceiptResolver(Protocol):
    """Application port for resolving the two receipts required at registration."""

    def resolve_pair(
        self,
        *,
        authoring: ArtifactPointer,
        review: ArtifactPointer,
    ) -> EvidenceUsageReceiptPair: ...


EvidenceUsageValidationReceipt = (
    AuthoringEvidenceUsageValidationReceipt | ReviewEvidenceUsageValidationReceipt
)
_RECEIPT_ADAPTER: TypeAdapter[EvidenceUsageValidationReceipt] = TypeAdapter(
    EvidenceUsageValidationReceipt
)
_EVENT_DATA_KEYS = frozenset(
    {
        "logical_artifact_id",
        "revision_id",
        "content_hash",
        "evidence_usage_validation_receipt",
    }
)


class OrchestratorEvidenceUsageReceiptResolver:
    """Resolve trusted receipts from exact terminal orchestrator job events.

    Two job IDs are fetched in bounded set-based queries. Maps provide O(1) identity lookup and
    event lists make duplicate terminal receipts an explicit error rather than selecting one.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.sessions = session_factory

    def resolve_pair(
        self,
        *,
        authoring: ArtifactPointer,
        review: ArtifactPointer,
    ) -> EvidenceUsageReceiptPair:
        pointers = (authoring, review)
        if (
            authoring.step_key != "authoring"
            or authoring.result_schema != "authoring-result@10.0"
            or review.step_key != "review"
            or review.result_schema != "review-result@10.0"
            or authoring.job_id == review.job_id
        ):
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt pointers are not one exact @10 authoring/review pair"
            )
        job_ids = tuple(pointer.job_id for pointer in pointers)
        artifact_ids = tuple(pointer.logical_artifact_id for pointer in pointers)
        revision_ids = tuple(pointer.revision_id for pointer in pointers)
        with self.sessions() as session:
            jobs = {
                row.job_id: row
                for row in session.scalars(select(JobRecord).where(JobRecord.job_id.in_(job_ids)))
            }
            artifacts = {
                row.logical_artifact_id: row
                for row in session.scalars(
                    select(ArtifactRecord).where(
                        ArtifactRecord.logical_artifact_id.in_(artifact_ids)
                    )
                )
            }
            revisions = {
                row.revision_id: row
                for row in session.scalars(
                    select(ArtifactRevisionRecord).where(
                        ArtifactRevisionRecord.revision_id.in_(revision_ids)
                    )
                )
            }
            events_by_job: dict[str, list[JobEventRecord]] = {job_id: [] for job_id in job_ids}
            for event in session.scalars(
                select(JobEventRecord).where(
                    JobEventRecord.job_id.in_(job_ids),
                    JobEventRecord.event == "ARTIFACT_COMMITTED",
                )
            ):
                events_by_job.setdefault(event.job_id, []).append(event)

        resolved = tuple(
            self._validate_receipt_record(
                pointer=pointer,
                job=jobs.get(pointer.job_id),
                artifact=artifacts.get(pointer.logical_artifact_id),
                revision=revisions.get(pointer.revision_id),
                events=tuple(events_by_job.get(pointer.job_id, ())),
            )
            for pointer in pointers
        )
        authoring_receipt, review_receipt = resolved
        if not isinstance(
            authoring_receipt, AuthoringEvidenceUsageValidationReceipt
        ) or not isinstance(review_receipt, ReviewEvidenceUsageValidationReceipt):
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipts do not match their authoring/review roles"
            )
        pair = EvidenceUsageReceiptPair(authoring=authoring_receipt, review=review_receipt)
        self._validate_pair(pair)
        return pair

    @staticmethod
    def _validate_receipt_record(
        *,
        pointer: ArtifactPointer,
        job: JobRecord | None,
        artifact: ArtifactRecord | None,
        revision: ArtifactRevisionRecord | None,
        events: tuple[JobEventRecord, ...],
    ) -> AuthoringEvidenceUsageValidationReceipt | ReviewEvidenceUsageValidationReceipt:
        if job is None or artifact is None or revision is None or len(events) != 1:
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt job, artifact, revision, or terminal event does not resolve"
            )
        event = events[0]
        data: Any = event.data
        try:
            artifact_manifest = ArtifactManifest.model_validate(revision.manifest)
        except PydanticValidationError as exc:
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt Artifact manifest is invalid"
            ) from exc
        if (
            job.job_id != pointer.job_id
            or job.status != "SUCCEEDED"
            or job.completed_at is None
            or job.protocol_version != "workflow-role/1.20.0"
            or job.task_type != f"workflow_{pointer.step_key}"
            or job.logical_artifact_id != pointer.logical_artifact_id
            or job.revision_id != pointer.revision_id
            or artifact.logical_artifact_id != pointer.logical_artifact_id
            or artifact.job_id != pointer.job_id
            or artifact.artifact_type != f"workflow_{pointer.step_key}"
            or not artifact.approved
            or revision.revision_id != pointer.revision_id
            or revision.logical_artifact_id != pointer.logical_artifact_id
            or revision.job_id != pointer.job_id
            or revision.content_hash != pointer.content_hash
            or revision.manifest_hash != content_sha256(revision.manifest)
            or revision.content_bytes != artifact_manifest.content_bytes
            or not revision.approved
            or artifact_manifest.job_id != pointer.job_id
            or artifact_manifest.logical_artifact_id != pointer.logical_artifact_id
            or artifact_manifest.revision_id != pointer.revision_id
            or artifact_manifest.content_hash != pointer.content_hash
            or artifact_manifest.file_name != "result.json"
            or artifact_manifest.media_type != "application/json"
            or event.job_id != pointer.job_id
            or event.from_state != "COMMITTING"
            or event.to_state != "SUCCEEDED"
            or event.event != "ARTIFACT_COMMITTED"
            or not isinstance(data, dict)
            or frozenset(data) != _EVENT_DATA_KEYS
            or data.get("logical_artifact_id") != pointer.logical_artifact_id
            or data.get("revision_id") != pointer.revision_id
            or data.get("content_hash") != pointer.content_hash
        ):
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt event differs from its immutable result pointer"
            )
        raw_receipt = data.get("evidence_usage_validation_receipt")
        try:
            validate_control_contract("evidence-usage-validation-receipt", raw_receipt)
            receipt = _RECEIPT_ADAPTER.validate_python(raw_receipt)
        except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt failed its JSON Schema or typed contract"
            ) from exc
        expected_result = EvidenceResultArtifactPointer(
            logical_artifact_id=pointer.logical_artifact_id,
            revision_id=pointer.revision_id,
            content_hash=pointer.content_hash,
            result_schema=pointer.result_schema,  # type: ignore[arg-type]
        )
        if receipt.step_key != pointer.step_key or receipt.result_artifact != expected_result:
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt does not bind the exact workflow result"
            )
        return receipt

    @staticmethod
    def _validate_pair(pair: EvidenceUsageReceiptPair) -> None:
        authoring = pair.authoring
        review = pair.review
        shared_authoring = (
            authoring.plan_id,
            authoring.plan_sha256,
            authoring.evidence_bundle_id,
            authoring.evidence_bundle_revision_id,
            authoring.retrieval_request_id,
            authoring.retrieval_request_sha256,
            authoring.graph_snapshot_revision_id,
            authoring.graph_snapshot_sha256,
            authoring.evidence_manifest_artifact,
            authoring.evidence_manifest_sha256,
            authoring.evidence_context_artifact,
        )
        shared_review = (
            review.plan_id,
            review.plan_sha256,
            review.evidence_bundle_id,
            review.evidence_bundle_revision_id,
            review.retrieval_request_id,
            review.retrieval_request_sha256,
            review.graph_snapshot_revision_id,
            review.graph_snapshot_sha256,
            review.evidence_manifest_artifact,
            review.evidence_manifest_sha256,
            review.evidence_context_artifact,
        )
        if (
            shared_authoring != shared_review
            or review.authoring_artifact != authoring.result_artifact
            or review.authoring_citation_set_sha256 != authoring.authoring_citation_set_sha256
            or review.review_citation_set_sha256 != authoring.authoring_citation_set_sha256
        ):
            raise EvidenceUsageReceiptResolutionError(
                "authoring and review evidence receipts do not form one immutable chain"
            )
