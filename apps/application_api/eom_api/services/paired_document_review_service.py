"""Application service for one immutable question/solution review set."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from eom_api_contracts import (
    CreateDocumentReviewSetRequest,
    DocumentReviewSetMemberView,
    DocumentReviewSetView,
)
from eom_catalog_contracts import (
    OfficeDocumentReviewMemberPointerV2,
    OfficeDocumentReviewSourcePointer,
    OfficeDocumentReviewSourcePointerV2,
    PdfReviewDocumentPointer,
)
from eom_identifiers import content_sha256, new_document_review_set_id
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory, transaction
from eom_workflow import (
    PdfReviewPresetKey,
    build_paired_document_review_request,
    normalize_pdf_review_guidance,
)
from eom_workflow_runner.errors import WorkflowError
from pydantic import ValidationError
from sqlalchemy import Engine, select

from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import (
    DocumentReviewSetMemberRecord,
    DocumentReviewSetRecord,
)
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_api.services.command_adapter import CommandAdapter
from eom_api.services.pdf_document_review_service import _RETRYABLE_CATALOG_CODES
from eom_api.services.pdf_upload_stager import StagedPdfUpload


@dataclass(frozen=True)
class PairedReviewMemberClaim:
    review_set_id: str
    document_role: str
    lease_owner: str | None
    original_filename: str
    source_format: str
    source_media_type: str
    already_committed: bool = False


@dataclass(frozen=True)
class PairedReviewStartClaim:
    review_set_id: str
    lease_owner: str
    preset_key: str
    additional_guidance: str | None
    question_document: PdfReviewDocumentPointer
    solution_document: PdfReviewDocumentPointer


class PairedDocumentReviewApplicationService:
    """Coordinate two Catalog intakes and at most one paired review Workflow."""

    def __init__(
        self,
        engine: Engine,
        *,
        catalog: CatalogApplicationClient,
        commands: CommandAdapter,
        intent_ttl_seconds: int,
        processing_lease_seconds: int,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.catalog = catalog
        self.commands = commands
        self.intent_ttl_seconds = intent_ttl_seconds
        self.processing_lease_seconds = processing_lease_seconds

    def create_set(
        self,
        request: CreateDocumentReviewSetRequest,
        *,
        actor_id: str,
        observed_at: datetime | None = None,
    ) -> DocumentReviewSetView:
        now = observed_at or datetime.now(UTC)
        normalized_guidance = (
            None
            if request.additional_guidance is None
            else normalize_pdf_review_guidance(request.additional_guidance)
        )
        review_set_id = new_document_review_set_id()
        record = DocumentReviewSetRecord(
            review_set_id=review_set_id,
            operator_id=actor_id,
            state="AWAITING_UPLOADS",
            preset_key=request.preset_key,
            additional_guidance=normalized_guidance,
            additional_guidance_sha256=(
                None if normalized_guidance is None else content_sha256(normalized_guidance)
            ),
            attempts=0,
            lock_version=1,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self.intent_ttl_seconds),
        )
        members = tuple(
            DocumentReviewSetMemberRecord(
                review_set_id=review_set_id,
                document_role=document.role,
                state="AWAITING_UPLOAD",
                original_filename=document.original_filename,
                source_format=document.source_format,
                source_media_type=document.media_type,
                content_length=document.content_length,
                attempts=0,
                lock_version=1,
                created_at=now,
                updated_at=now,
            )
            for document in request.documents
        )
        with transaction(self.sessions) as session:
            session.add(record)
            # The set/member models intentionally do not expose an ORM relationship: the
            # application service owns their aggregate and all reads are keyed lookups.  Flush
            # the parent explicitly so SQLAlchemy cannot batch the member INSERTs ahead of the
            # foreign-key target on PostgreSQL.
            session.flush()
            session.add_all(members)
            session.flush()
        return self._view(record, members)

    def review_set(self, review_set_id: str, *, actor_id: str) -> DocumentReviewSetView:
        with self.sessions() as session:
            record = session.scalar(
                select(DocumentReviewSetRecord).where(
                    DocumentReviewSetRecord.review_set_id == review_set_id,
                    DocumentReviewSetRecord.operator_id == actor_id,
                )
            )
            if record is None:
                raise self._not_found()
            members = tuple(
                session.scalars(
                    select(DocumentReviewSetMemberRecord).where(
                        DocumentReviewSetMemberRecord.review_set_id == review_set_id
                    )
                )
            )
            session.expunge(record)
            for member in members:
                session.expunge(member)
        return self._view(record, members)

    def accept_member_upload(
        self,
        review_set_id: str,
        document_role: str,
        upload: StagedPdfUpload,
        *,
        actor: ActorContext,
        observed_at: datetime | None = None,
    ) -> tuple[str | None, DocumentReviewSetView]:
        now = observed_at or datetime.now(UTC)
        claim = self._claim_member(
            review_set_id,
            document_role,
            upload,
            actor_id=actor.actor_id,
            observed_at=now,
        )
        if not claim.already_committed:
            try:
                document = self.catalog.ingest_office_document_review_source(
                    upload.path,
                    actor_id=actor.actor_id,
                    original_filename=claim.original_filename,
                    source_format=claim.source_format,  # type: ignore[arg-type]
                    media_type=claim.source_media_type,  # type: ignore[arg-type]
                    idempotency_key=(
                        f"paired-document-review-intake:{claim.review_set_id}:{claim.document_role}"
                    ),
                )
                if (
                    document.original_filename != claim.original_filename
                    or document.source_format != claim.source_format
                    or document.original_source.sha256 != upload.sha256
                    or document.original_source.content_length != upload.content_length
                ):
                    raise ApiError(
                        503,
                        "PAIRED_DOCUMENT_REVIEW_INTAKE_POINTER_MISMATCH",
                        "Document intake pointer differs",
                        "Catalog did not return the exact immutable source that was uploaded.",
                    )
                self._complete_member(claim, document=document)
            except CatalogApplicationClientError as exc:
                retryable = exc.code in _RETRYABLE_CATALOG_CODES
                self._fail_member(
                    claim,
                    error_code=exc.code,
                    retryable=retryable,
                    retained_source=exc.retained_source,
                )
                raise ApiError(
                    503 if retryable else 422,
                    exc.code,
                    "Paired document intake failed",
                    "The document could not be registered for paired review.",
                ) from exc
            except ApiError as exc:
                self._fail_member(
                    claim,
                    error_code=str(exc.error_code),
                    retryable=exc.status >= 500,
                )
                raise
            except Exception as exc:
                self._fail_member(
                    claim,
                    error_code="PAIRED_DOCUMENT_REVIEW_PROCESSING_FAILED",
                    retryable=True,
                )
                raise ApiError(
                    500,
                    "PAIRED_DOCUMENT_REVIEW_PROCESSING_FAILED",
                    "Paired document processing failed",
                    "Retry the exact member upload after the dependency recovers.",
                ) from exc

        start_claim = self._claim_start(
            review_set_id,
            actor_id=actor.actor_id,
            observed_at=datetime.now(UTC),
        )
        if start_claim is None:
            view = self.review_set(review_set_id, actor_id=actor.actor_id)
            return view.workflow_id and self._workflow_command_id(review_set_id), view
        try:
            review_request = build_paired_document_review_request(
                question_document=start_claim.question_document,
                solution_document=start_claim.solution_document,
                preset_key=cast(PdfReviewPresetKey, start_claim.preset_key),
                additional_guidance=start_claim.additional_guidance,
            )
            command_id, workflow_id, _ = self.commands.start_paired_document_review(
                review_request,
                actor,
                idempotency_key=f"paired-pdf-review-workflow:{start_claim.review_set_id}",
            )
        except ApiError as exc:
            self._fail_start(
                start_claim,
                error_code=str(exc.error_code),
                retryable=exc.status >= 500,
            )
            raise
        except WorkflowError as exc:
            code = getattr(exc.code, "value", str(exc.code))
            self._fail_start(start_claim, error_code=code, retryable=False)
            raise ApiError(
                409,
                code,
                "Paired document-review Workflow could not start",
                "The immutable paired review request conflicts with an existing Workflow.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            self._fail_start(
                start_claim,
                error_code="PAIRED_DOCUMENT_REVIEW_REQUEST_UNSUPPORTED",
                retryable=False,
            )
            raise ApiError(
                422,
                "PAIRED_DOCUMENT_REVIEW_REQUEST_UNSUPPORTED",
                "Paired review request is outside the supported boundary",
                "The two immutable documents cannot be reviewed by the paired workflow.",
            ) from exc
        except Exception as exc:
            self._fail_start(
                start_claim,
                error_code="PAIRED_DOCUMENT_REVIEW_START_FAILED",
                retryable=True,
            )
            raise ApiError(
                500,
                "PAIRED_DOCUMENT_REVIEW_START_FAILED",
                "Paired document review could not start",
                "Replay either exact committed member after the dependency recovers.",
            ) from exc
        return command_id, self._complete_start(
            start_claim,
            command_id=command_id,
            workflow_id=workflow_id,
        )

    def _claim_member(
        self,
        review_set_id: str,
        document_role: str,
        upload: StagedPdfUpload,
        *,
        actor_id: str,
        observed_at: datetime,
    ) -> PairedReviewMemberClaim:
        lease_owner = "pairedreviewmemberlease_" + secrets.token_hex(16)
        with transaction(self.sessions) as session:
            review_set = session.scalar(
                select(DocumentReviewSetRecord)
                .where(
                    DocumentReviewSetRecord.review_set_id == review_set_id,
                    DocumentReviewSetRecord.operator_id == actor_id,
                )
                .with_for_update()
            )
            if review_set is None:
                raise self._not_found()
            if self._as_utc(review_set.expires_at) <= observed_at:
                raise ApiError(
                    409,
                    "PAIRED_DOCUMENT_REVIEW_SET_EXPIRED",
                    "Paired review set expired",
                    "Create a new review set before uploading documents again.",
                )
            if review_set.state == "FAILED_FINAL":
                raise ApiError(
                    409,
                    review_set.failure_code or "PAIRED_DOCUMENT_REVIEW_SET_FAILED",
                    "Paired review set cannot continue",
                    "Create a new set after correcting the non-retryable input error.",
                )
            member = session.get(
                DocumentReviewSetMemberRecord,
                (review_set_id, document_role),
                with_for_update=True,
            )
            if member is None:
                raise ApiError(
                    404,
                    "PAIRED_DOCUMENT_REVIEW_MEMBER_NOT_FOUND",
                    "Paired review member not found",
                    "The requested document role is not part of this review set.",
                )
            if member.content_length != upload.content_length:
                raise ApiError(
                    422,
                    "PAIRED_DOCUMENT_REVIEW_UPLOAD_LENGTH_MISMATCH",
                    "Document upload length differs",
                    "The uploaded bytes do not match the declared set member.",
                )
            if (
                member.source_format != upload.source_format
                or member.source_media_type != upload.media_type
            ):
                raise ApiError(
                    422,
                    "PAIRED_DOCUMENT_REVIEW_UPLOAD_FORMAT_MISMATCH",
                    "Document upload format differs",
                    "The uploaded bytes must use the declared format and media type.",
                )
            if member.upload_sha256 is not None and not hmac.compare_digest(
                member.upload_sha256, upload.sha256
            ):
                raise ApiError(
                    409,
                    "PAIRED_DOCUMENT_REVIEW_UPLOAD_HASH_MISMATCH",
                    "Document upload differs from the pinned member",
                    "Replay only the exact same bytes for this document role.",
                )
            if member.state == "COMMITTED":
                return PairedReviewMemberClaim(
                    review_set_id=review_set_id,
                    document_role=document_role,
                    lease_owner=None,
                    original_filename=member.original_filename,
                    source_format=member.source_format,
                    source_media_type=member.source_media_type,
                    already_committed=True,
                )
            if member.state == "FAILED_FINAL":
                raise ApiError(
                    409,
                    member.failure_code or "PAIRED_DOCUMENT_REVIEW_MEMBER_FAILED",
                    "Paired review member cannot be retried",
                    "Create a new review set after correcting the document.",
                )
            if member.state == "PROCESSING" and (
                member.lease_expires_at is None
                or self._as_utc(member.lease_expires_at) > observed_at
            ):
                raise ApiError(
                    409,
                    "PAIRED_DOCUMENT_REVIEW_UPLOAD_IN_PROGRESS",
                    "Document upload is already being processed",
                    "Retry the exact bytes after the current processing lease ends.",
                )
            member.state = "PROCESSING"
            member.upload_sha256 = upload.sha256
            member.failure_code = None
            member.lease_owner = lease_owner
            member.lease_expires_at = observed_at + timedelta(seconds=self.processing_lease_seconds)
            member.attempts += 1
            member.lock_version += 1
            member.updated_at = observed_at
            return PairedReviewMemberClaim(
                review_set_id=review_set_id,
                document_role=document_role,
                lease_owner=lease_owner,
                original_filename=member.original_filename,
                source_format=member.source_format,
                source_media_type=member.source_media_type,
            )

    def _complete_member(
        self,
        claim: PairedReviewMemberClaim,
        *,
        document: OfficeDocumentReviewSourcePointer | OfficeDocumentReviewSourcePointerV2,
    ) -> None:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            member = session.get(
                DocumentReviewSetMemberRecord,
                (claim.review_set_id, claim.document_role),
                with_for_update=True,
            )
            if member is None or not self._owns_member(member, claim):
                raise ApiError(
                    409,
                    "PAIRED_DOCUMENT_REVIEW_UPLOAD_CLAIM_LOST",
                    "Document upload claim was superseded",
                    "Replay the exact bytes to receive the committed set state.",
                )
            review = document.review_document
            member.state = "COMMITTED"
            member.document_id = review.document_id
            member.document_revision_id = review.document_revision_id
            member.source_artifact_id = document.original_source.artifact_id
            member.source_artifact_revision_id = document.original_source.artifact_revision_id
            member.source_pdf_sha256 = review.source_pdf.sha256
            member.page_count = review.page_count
            member.review_document_pointer = review.model_dump(mode="json")
            member.failure_code = None
            member.lease_owner = None
            member.lease_expires_at = None
            member.lock_version += 1
            member.updated_at = now

    def _fail_member(
        self,
        claim: PairedReviewMemberClaim,
        *,
        error_code: str,
        retryable: bool,
        retained_source: OfficeDocumentReviewMemberPointerV2 | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            member = session.get(
                DocumentReviewSetMemberRecord,
                (claim.review_set_id, claim.document_role),
                with_for_update=True,
            )
            if member is None or not self._owns_member(member, claim):
                return
            member.state = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
            member.failure_code = error_code[:64]
            if retained_source is not None:
                member.source_artifact_id = retained_source.artifact_id
                member.source_artifact_revision_id = retained_source.artifact_revision_id
            member.lease_owner = None
            member.lease_expires_at = None
            member.lock_version += 1
            member.updated_at = now
            if not retryable:
                review_set = session.get(
                    DocumentReviewSetRecord,
                    claim.review_set_id,
                    with_for_update=True,
                )
                if review_set is not None and review_set.state != "STARTED":
                    review_set.state = "FAILED_FINAL"
                    review_set.failure_code = error_code[:64]
                    review_set.lease_owner = None
                    review_set.lease_expires_at = None
                    review_set.attempts += 1
                    review_set.lock_version += 1
                    review_set.updated_at = now

    def _claim_start(
        self,
        review_set_id: str,
        *,
        actor_id: str,
        observed_at: datetime,
    ) -> PairedReviewStartClaim | None:
        lease_owner = "pairedreviewstartlease_" + secrets.token_hex(16)
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(DocumentReviewSetRecord)
                .where(
                    DocumentReviewSetRecord.review_set_id == review_set_id,
                    DocumentReviewSetRecord.operator_id == actor_id,
                )
                .with_for_update()
            )
            if record is None:
                raise self._not_found()
            if record.state == "STARTED":
                return None
            if record.state == "FAILED_FINAL":
                raise ApiError(
                    409,
                    record.failure_code or "PAIRED_DOCUMENT_REVIEW_SET_FAILED",
                    "Paired review set cannot start",
                    "Create a new review set after correcting the invalid input.",
                )
            members = tuple(
                session.scalars(
                    select(DocumentReviewSetMemberRecord).where(
                        DocumentReviewSetMemberRecord.review_set_id == review_set_id
                    )
                )
            )
            by_role = {member.document_role: member for member in members}
            if set(by_role) != {"QUESTION", "SOLUTION"} or any(
                member.state != "COMMITTED" for member in members
            ):
                return None
            if record.state == "STARTING" and (
                record.lease_expires_at is None
                or self._as_utc(record.lease_expires_at) > observed_at
            ):
                return None
            documents: dict[str, PdfReviewDocumentPointer] = {}
            for role in ("QUESTION", "SOLUTION"):
                pointer = by_role[role].review_document_pointer
                if pointer is None:
                    raise RuntimeError("committed paired review member lost its document pointer")
                documents[role] = PdfReviewDocumentPointer.model_validate(pointer)
            record.state = "STARTING"
            record.failure_code = None
            record.lease_owner = lease_owner
            record.lease_expires_at = observed_at + timedelta(seconds=self.processing_lease_seconds)
            record.attempts += 1
            record.lock_version += 1
            record.updated_at = observed_at
            return PairedReviewStartClaim(
                review_set_id=review_set_id,
                lease_owner=lease_owner,
                preset_key=record.preset_key,
                additional_guidance=record.additional_guidance,
                question_document=documents["QUESTION"],
                solution_document=documents["SOLUTION"],
            )

    def _complete_start(
        self,
        claim: PairedReviewStartClaim,
        *,
        command_id: str,
        workflow_id: str,
    ) -> DocumentReviewSetView:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            record = session.get(DocumentReviewSetRecord, claim.review_set_id, with_for_update=True)
            if record is None or not self._owns_start(record, claim):
                raise ApiError(
                    409,
                    "PAIRED_DOCUMENT_REVIEW_START_CLAIM_LOST",
                    "Paired review start claim was superseded",
                    "Reload the review set to receive the committed Workflow pointer.",
                )
            record.state = "STARTED"
            record.workflow_id = workflow_id
            record.workflow_command_id = command_id
            record.failure_code = None
            record.lease_owner = None
            record.lease_expires_at = None
            record.lock_version += 1
            record.updated_at = now
            members = tuple(
                session.scalars(
                    select(DocumentReviewSetMemberRecord).where(
                        DocumentReviewSetMemberRecord.review_set_id == claim.review_set_id
                    )
                )
            )
            session.flush()
            return self._view(record, members)

    def _fail_start(
        self,
        claim: PairedReviewStartClaim,
        *,
        error_code: str,
        retryable: bool,
    ) -> None:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            record = session.get(DocumentReviewSetRecord, claim.review_set_id, with_for_update=True)
            if record is None or not self._owns_start(record, claim):
                return
            record.state = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
            record.failure_code = error_code[:64]
            record.lease_owner = None
            record.lease_expires_at = None
            record.lock_version += 1
            record.updated_at = now

    def _workflow_command_id(self, review_set_id: str) -> str | None:
        with self.sessions() as session:
            value = session.get(DocumentReviewSetRecord, review_set_id)
            return None if value is None else value.workflow_command_id

    @staticmethod
    def _owns_member(
        record: DocumentReviewSetMemberRecord,
        claim: PairedReviewMemberClaim,
    ) -> bool:
        return (
            record.state == "PROCESSING"
            and record.lease_owner is not None
            and claim.lease_owner is not None
            and hmac.compare_digest(record.lease_owner, claim.lease_owner)
        )

    @staticmethod
    def _owns_start(record: DocumentReviewSetRecord, claim: PairedReviewStartClaim) -> bool:
        return (
            record.state == "STARTING"
            and record.lease_owner is not None
            and hmac.compare_digest(record.lease_owner, claim.lease_owner)
        )

    @staticmethod
    def _view(
        record: DocumentReviewSetRecord,
        members: tuple[DocumentReviewSetMemberRecord, ...],
    ) -> DocumentReviewSetView:
        ordered = tuple(sorted(members, key=lambda value: value.document_role))
        if tuple(value.document_role for value in ordered) != ("QUESTION", "SOLUTION"):
            raise RuntimeError("paired review set lost its exact role members")
        return DocumentReviewSetView(
            review_set_id=record.review_set_id,
            state=record.state,  # type: ignore[arg-type]
            documents=tuple(
                DocumentReviewSetMemberView(
                    role=member.document_role,  # type: ignore[arg-type]
                    original_filename=member.original_filename,
                    source_format=member.source_format,  # type: ignore[arg-type]
                    media_type=member.source_media_type,  # type: ignore[arg-type]
                    content_length=member.content_length,
                    state=member.state,  # type: ignore[arg-type]
                    upload_sha256=member.upload_sha256,
                    document_id=member.document_id,
                    document_revision_id=member.document_revision_id,
                    source_pdf_sha256=member.source_pdf_sha256,
                    page_count=member.page_count,
                    failure_code=member.failure_code,
                    upload_url=(
                        f"/api/v1/pdf-document-reviews/sets/{record.review_set_id}/"
                        f"documents/{member.document_role}/content"
                    ),
                )
                for member in ordered
            ),
            preset_key=record.preset_key,  # type: ignore[arg-type]
            additional_guidance_sha256=record.additional_guidance_sha256,
            workflow_id=record.workflow_id,
            failure_code=record.failure_code,
            review_url=(
                f"/api/v1/pdf-document-reviews/{record.workflow_id}"
                if record.workflow_id is not None
                else None
            ),
            created_at=PairedDocumentReviewApplicationService._as_utc(record.created_at),
            updated_at=PairedDocumentReviewApplicationService._as_utc(record.updated_at),
            expires_at=PairedDocumentReviewApplicationService._as_utc(record.expires_at),
            resource_version=record.lock_version,
        )

    @staticmethod
    def _not_found() -> ApiError:
        return ApiError(
            404,
            "PAIRED_DOCUMENT_REVIEW_SET_NOT_FOUND",
            "Paired document review set not found",
            "The review set does not exist or is not visible to this Operator.",
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
