"""Read-side validation of orchestrator-issued evidence-usage receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eom_catalog_contracts.item_review import MockExamTrustedEvidenceUsageReceiptPairV1
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
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
    ResolvedExecutionPlanV3,
    ReviewEvidenceUsageValidationReceipt,
    RoleWorkerInput,
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


@dataclass(frozen=True)
class EvidenceUsageProvenanceExpectation:
    """Small checkpoint-side pins needed to bind receipts to one knowledge resolution."""

    plan_id: str
    plan_sha256: str
    evidence_bundle_revision_id: str
    retrieval_request_id: str
    retrieval_request_sha256: str
    graph_snapshot_revision_id: str
    evidence_manifest_sha256: str


class EvidenceUsageReceiptResolver(Protocol):
    """Application port for resolving the two receipts required at registration."""

    def resolve_pair(
        self,
        *,
        authoring: ArtifactPointer,
        review: ArtifactPointer,
    ) -> EvidenceUsageReceiptPair: ...


class MockExamEvidenceUsageReceiptResolver(Protocol):
    """Trusted-RAG review boundary with exact Workflow occurrence context."""

    def resolve_mock_exam_pair(
        self,
        *,
        workflow_id: str,
        authoring_step_run_id: str,
        authoring: ArtifactPointer,
        review_step_run_id: str,
        review: ArtifactPointer,
        expected_provenance: EvidenceUsageProvenanceExpectation | None = None,
        expected_authoring_receipt_sha256: str | None = None,
        expected_review_receipt_sha256: str | None = None,
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
        pair, _jobs = self._resolve_pair_with_jobs(authoring=authoring, review=review)
        return pair

    def resolve_mock_exam_pair(
        self,
        *,
        workflow_id: str,
        authoring_step_run_id: str,
        authoring: ArtifactPointer,
        review_step_run_id: str,
        review: ArtifactPointer,
        expected_provenance: EvidenceUsageProvenanceExpectation | None = None,
        expected_authoring_receipt_sha256: str | None = None,
        expected_review_receipt_sha256: str | None = None,
    ) -> EvidenceUsageReceiptPair:
        """Resolve one pair and bind it to persisted worker inputs and knowledge plan."""

        pair, jobs = self._resolve_pair_with_jobs(authoring=authoring, review=review)
        contexts = (
            (authoring, authoring_step_run_id, pair.authoring, "authoring"),
            (review, review_step_run_id, pair.review, "review"),
        )
        for pointer, step_run_id, _receipt, role in contexts:
            job = jobs[pointer.job_id]
            try:
                worker_input = RoleWorkerInput.model_validate(job.request)
            except (PydanticValidationError, ValueError) as exc:
                raise EvidenceUsageReceiptResolutionError(
                    "evidence receipt job request is not a valid role-worker input"
                ) from exc
            expected_request_hash = content_sha256(
                {
                    "protocol_version": job.protocol_version,
                    "task_type": job.task_type,
                    "request": job.request,
                }
            )
            if (
                job.request_hash != expected_request_hash
                or worker_input.workflow_id != workflow_id
                or worker_input.step_run_id != step_run_id
                or worker_input.attempt != pointer.attempt
                or worker_input.job_id != pointer.job_id
                or worker_input.role != role
                or worker_input.protocol_version != "workflow-role/1.20.0"
                or worker_input.protocol_version != job.protocol_version
                or worker_input.artifact.logical_artifact_id != pointer.logical_artifact_id
                or worker_input.artifact.revision_id != pointer.revision_id
            ):
                raise EvidenceUsageReceiptResolutionError(
                    "evidence receipt job request differs from its Workflow occurrence"
                )

        if (
            expected_authoring_receipt_sha256 is not None
            and pair.authoring.receipt_sha256 != expected_authoring_receipt_sha256
        ) or (
            expected_review_receipt_sha256 is not None
            and pair.review.receipt_sha256 != expected_review_receipt_sha256
        ):
            raise EvidenceUsageReceiptResolutionError(
                "compact evidence receipt hash differs from the canonical terminal receipt"
            )

        with self.sessions() as session:
            plan_record = session.scalar(
                select(ResolvedExecutionPlanRecord).where(
                    ResolvedExecutionPlanRecord.workflow_id == workflow_id
                )
            )
        try:
            plan = (
                ResolvedExecutionPlanV3.model_validate(plan_record.canonical_document)
                if plan_record is not None
                else None
            )
        except (PydanticValidationError, ValueError) as exc:
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt knowledge plan is invalid"
            ) from exc
        if (
            plan_record is None
            or plan is None
            or not self._plan_record_is_exact(plan_record, plan, workflow_id)
        ):
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipt knowledge plan does not resolve exactly"
            )
        self._validate_plan_binding(pair, plan)
        if expected_provenance is not None:
            self._validate_expected_provenance(plan, expected_provenance)
        return pair

    def verify_mock_exam_pair(
        self,
        *,
        receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
        expected_provenance: EvidenceUsageProvenanceExpectation,
    ) -> EvidenceUsageReceiptPair:
        """Re-resolve a compact checkpoint pointer without trusting its claimed hashes."""

        return self.resolve_mock_exam_pair(
            workflow_id=receipts.authoring.workflow_id,
            authoring_step_run_id=receipts.authoring.step_run_id,
            authoring=self._artifact_pointer(receipts.authoring),
            review_step_run_id=receipts.review.step_run_id,
            review=self._artifact_pointer(receipts.review),
            expected_provenance=expected_provenance,
            expected_authoring_receipt_sha256=receipts.authoring.receipt_sha256,
            expected_review_receipt_sha256=receipts.review.receipt_sha256,
        )

    def _resolve_pair_with_jobs(
        self,
        *,
        authoring: ArtifactPointer,
        review: ArtifactPointer,
    ) -> tuple[EvidenceUsageReceiptPair, dict[str, JobRecord]]:
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
        return pair, jobs

    @staticmethod
    def _artifact_pointer(pointer: Any) -> ArtifactPointer:
        return ArtifactPointer(
            step_key=pointer.step_key,
            attempt=pointer.attempt,
            job_id=pointer.job_id,
            logical_artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            content_hash=pointer.sha256,
            result_schema=pointer.result_schema,
        )

    @staticmethod
    def _plan_record_is_exact(
        record: ResolvedExecutionPlanRecord,
        plan: ResolvedExecutionPlanV3,
        workflow_id: str,
    ) -> bool:
        return (
            record.plan_id == plan.plan_id
            and record.workflow_id == workflow_id
            and plan.workflow_id == workflow_id
            and record.preset_id == plan.preset_id
            and record.preset_revision_id == plan.preset_revision_id
            and record.capacity_policy_revision_id == plan.capacity_policy_revision_id
            and record.graph_snapshot_revision_id == plan.graph_snapshot.graph_snapshot_revision_id
            and record.evidence_bundle_revision_id == plan.evidence_bundle_revision_id
            and record.plan_sha256 == plan.plan_sha256
            and record.resolved_at == plan.resolved_at
            and plan.workflow_definition_key == "generic-item-development"
            and plan.workflow_definition_version == "1.10.0"
        )

    @staticmethod
    def _validate_plan_binding(
        pair: EvidenceUsageReceiptPair,
        plan: ResolvedExecutionPlanV3,
    ) -> None:
        receipt = pair.authoring
        if (
            receipt.plan_id != plan.plan_id
            or receipt.plan_sha256 != plan.plan_sha256
            or receipt.evidence_bundle_id != plan.evidence_bundle_id
            or receipt.evidence_bundle_revision_id != plan.evidence_bundle_revision_id
            or receipt.retrieval_request_id != plan.retrieval_request_id
            or receipt.retrieval_request_sha256 != plan.retrieval_request_sha256
            or receipt.graph_snapshot_revision_id != plan.graph_snapshot.graph_snapshot_revision_id
            or receipt.graph_snapshot_sha256 != plan.graph_snapshot.manifest_sha256
            or receipt.evidence_manifest_artifact != plan.evidence_manifest_artifact
            or receipt.evidence_manifest_sha256 != plan.evidence_manifest_sha256
            or receipt.evidence_context_artifact != plan.evidence_context_artifact
        ):
            raise EvidenceUsageReceiptResolutionError(
                "evidence receipts differ from the immutable knowledge plan"
            )

    @staticmethod
    def _validate_expected_provenance(
        plan: ResolvedExecutionPlanV3,
        expected: EvidenceUsageProvenanceExpectation,
    ) -> None:
        if (
            expected.plan_id != plan.plan_id
            or expected.plan_sha256 != plan.plan_sha256
            or expected.evidence_bundle_revision_id != plan.evidence_bundle_revision_id
            or expected.retrieval_request_id != plan.retrieval_request_id
            or expected.retrieval_request_sha256 != plan.retrieval_request_sha256
            or expected.graph_snapshot_revision_id != plan.graph_snapshot.graph_snapshot_revision_id
            or expected.evidence_manifest_sha256 != plan.evidence_manifest_sha256
        ):
            raise EvidenceUsageReceiptResolutionError(
                "Item-run knowledge provenance differs from the evidence receipt plan"
            )

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
