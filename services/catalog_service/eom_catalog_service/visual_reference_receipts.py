"""Resolve one Orchestrator-published morphology reference for local image generation."""

from __future__ import annotations

from dataclasses import dataclass

from eom_identifiers import content_sha256
from eom_image_contracts import (
    LocalImageVisualReferencePointer,
    LocalImageVisualReferencePublicationReceipt,
    SvgLabelLayoutValidationReceipt,
    VisualReferenceImageResultArtifactPointer,
    sanitize_svg_overlay,
    text_sha256,
    validate_contract,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_protocol import ArtifactManifest
from eom_workflow import ArtifactPointer, RoleWorkerInput
from eom_workflow.models import ContentTeamImageRoleResultV12, GeneratedVectorDrawingV6
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactResolutionError,
    resolve_pinned_artifact_member,
)
from eom_catalog_service.settings import CatalogSettings

_EVENT_DATA_KEYS = frozenset(
    {
        "logical_artifact_id",
        "revision_id",
        "content_hash",
        "visual_reference_publication_receipt",
    }
)
_SVG_LABEL_RECEIPT_KEY = "svg_label_layout_validation_receipts"


class VisualReferenceReceiptResolutionError(RuntimeError):
    """Stable failure for a missing, stale, or mismatched visual-reference receipt."""


@dataclass(frozen=True, slots=True)
class ResolvedVisualReference:
    """One exact normalized PNG and its immutable publication identities."""

    pointer: LocalImageVisualReferencePointer
    payload: bytes
    publication_receipt_sha256: str


class OrchestratorVisualReferenceReceiptResolver:
    """Resolve exact image-result and visual-reference records in one DB snapshot.

    All persistent lookups are indexed primary-key or ``job_id`` queries.  The only iteration is
    over one bounded terminal-event set and the receipt's at-most-two entries, so resolution is
    ``O(E)`` with ``E <= 2`` and constant auxiliary space.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: CatalogSettings,
    ) -> None:
        self.sessions = session_factory
        self.settings = settings

    def resolve(
        self,
        *,
        image_result: ArtifactPointer,
        workflow_id: str,
        visual_ordinal: int,
        drawing_sha256: str,
    ) -> ResolvedVisualReference:
        if image_result.step_key != "image" or image_result.result_schema != "image-result@12.0":
            raise VisualReferenceReceiptResolutionError(
                "visual-reference image result pointer is incompatible"
            )
        with self.sessions() as session:
            job = session.get(JobRecord, image_result.job_id)
            artifact = session.get(ArtifactRecord, image_result.logical_artifact_id)
            revision = session.get(ArtifactRevisionRecord, image_result.revision_id)
            events = tuple(
                session.scalars(
                    select(JobEventRecord).where(
                        JobEventRecord.job_id == image_result.job_id,
                        JobEventRecord.event == "ARTIFACT_COMMITTED",
                    )
                )
            )
            receipt = self._validate_image_result(
                image_result=image_result,
                workflow_id=workflow_id,
                job=job,
                artifact=artifact,
                revision=revision,
                events=events,
            )
            matches = tuple(
                entry
                for entry in receipt.entries
                if entry.visual_ordinal == visual_ordinal and entry.drawing_sha256 == drawing_sha256
            )
            if len(matches) != 1:
                raise VisualReferenceReceiptResolutionError(
                    "visual-reference publication does not bind the requested drawing"
                )
            pointer = matches[0].visual_reference
            try:
                member = resolve_pinned_artifact_member(
                    session,
                    self.settings,
                    artifact_id=pointer.reference_member.artifact_id,
                    artifact_revision_id=pointer.reference_member.artifact_revision_id,
                    member_path=pointer.reference_member.member_path,
                    sha256=pointer.reference_member.sha256,
                    schema_ref=pointer.reference_member.schema_ref,
                    media_type=pointer.reference_member.media_type,
                    expected_artifact_types={"control_local_image_visual_reference_bundle"},
                    expected_primary_file="manifests/visual-reference-bundle.json",
                    max_bytes=8 * 1024 * 1024,
                )
            except PinnedArtifactResolutionError as exc:
                raise VisualReferenceReceiptResolutionError(
                    "visual-reference Artifact member does not resolve"
                ) from exc
        return ResolvedVisualReference(
            pointer=pointer,
            payload=member.payload,
            publication_receipt_sha256=receipt.receipt_sha256,
        )

    @staticmethod
    def _validate_image_result(
        *,
        image_result: ArtifactPointer,
        workflow_id: str,
        job: JobRecord | None,
        artifact: ArtifactRecord | None,
        revision: ArtifactRevisionRecord | None,
        events: tuple[JobEventRecord, ...],
    ) -> LocalImageVisualReferencePublicationReceipt:
        if job is None or artifact is None or revision is None or len(events) != 1:
            raise VisualReferenceReceiptResolutionError(
                "visual-reference result records do not resolve"
            )
        event = events[0]
        data = event.data
        try:
            worker_input = RoleWorkerInput.model_validate(job.request)
            result = ContentTeamImageRoleResultV12.model_validate(revision.result)
            manifest = ArtifactManifest.model_validate(revision.manifest)
        except (PydanticValidationError, ValueError) as exc:
            raise VisualReferenceReceiptResolutionError(
                "visual-reference image result contracts are invalid"
            ) from exc
        expected_request_hash = content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
        if (
            job.status != "SUCCEEDED"
            or job.completed_at is None
            or job.protocol_version != "workflow-role/1.24.0"
            or job.task_type != "workflow_image"
            or job.request_hash != expected_request_hash
            or job.logical_artifact_id != image_result.logical_artifact_id
            or job.revision_id != image_result.revision_id
            or worker_input.workflow_id != workflow_id
            or worker_input.attempt != image_result.attempt
            or worker_input.job_id != image_result.job_id
            or worker_input.role != "image"
            or worker_input.protocol_version != "workflow-role/1.24.0"
            or worker_input.artifact.logical_artifact_id != image_result.logical_artifact_id
            or worker_input.artifact.revision_id != image_result.revision_id
            or result.workflow_id != workflow_id
            or result.step_run_id != worker_input.step_run_id
            or result.job_id != image_result.job_id
            or result.artifact.logical_artifact_id != image_result.logical_artifact_id
            or result.artifact.revision_id != image_result.revision_id
            or artifact.job_id != image_result.job_id
            or artifact.logical_artifact_id != image_result.logical_artifact_id
            or artifact.artifact_type != "workflow_image"
            or not artifact.approved
            or revision.logical_artifact_id != image_result.logical_artifact_id
            or revision.job_id != image_result.job_id
            or revision.content_hash != image_result.content_hash
            or revision.content_hash != content_sha256(revision.result)
            or revision.manifest_hash != content_sha256(revision.manifest)
            or revision.content_bytes != manifest.content_bytes
            or not revision.approved
            or manifest.job_id != image_result.job_id
            or manifest.logical_artifact_id != image_result.logical_artifact_id
            or manifest.revision_id != image_result.revision_id
            or manifest.content_hash != image_result.content_hash
            or manifest.file_name != "result.json"
            or manifest.media_type != "application/json"
            or event.job_id != image_result.job_id
            or event.from_state != "COMMITTING"
            or event.to_state != "SUCCEEDED"
            or event.event != "ARTIFACT_COMMITTED"
            or not isinstance(data, dict)
            or frozenset(data)
            not in {_EVENT_DATA_KEYS, _EVENT_DATA_KEYS | {_SVG_LABEL_RECEIPT_KEY}}
            or data.get("logical_artifact_id") != image_result.logical_artifact_id
            or data.get("revision_id") != image_result.revision_id
            or data.get("content_hash") != image_result.content_hash
        ):
            raise VisualReferenceReceiptResolutionError(
                "visual-reference result differs from its immutable pointer"
            )
        if _SVG_LABEL_RECEIPT_KEY in data:
            _validate_svg_label_receipts(data[_SVG_LABEL_RECEIPT_KEY], result)
        raw_receipt = data.get("visual_reference_publication_receipt")
        if not isinstance(raw_receipt, dict):
            raise VisualReferenceReceiptResolutionError(
                "visual-reference publication receipt is invalid"
            )
        try:
            validate_contract("visual-reference-publication-receipt", raw_receipt)
            receipt = LocalImageVisualReferencePublicationReceipt.model_validate(raw_receipt)
        except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
            raise VisualReferenceReceiptResolutionError(
                "visual-reference publication receipt is invalid"
            ) from exc
        expected_result = VisualReferenceImageResultArtifactPointer(
            logical_artifact_id=image_result.logical_artifact_id,
            revision_id=image_result.revision_id,
            content_hash=image_result.content_hash,
        )
        if receipt.image_result_artifact != expected_result:
            raise VisualReferenceReceiptResolutionError(
                "visual-reference receipt does not bind the exact image result"
            )
        return receipt


def _validate_svg_label_receipts(
    value: object,
    result: ContentTeamImageRoleResultV12,
) -> None:
    expected = {
        item.visual_ordinal: (
            content_sha256(item.drawing.model_dump(mode="json")),
            text_sha256(
                sanitize_svg_overlay(item.drawing.svg_overlay, item.drawing.required_labels)
            ),
            tuple(sorted(item.drawing.required_labels)),
        )
        for item in result.output.drawings
        if isinstance(item.drawing, GeneratedVectorDrawingV6)
    }
    if not isinstance(value, list) or len(value) != len(expected):
        raise VisualReferenceReceiptResolutionError("SVG label receipt set is invalid")
    observed: dict[int, tuple[str, str, tuple[str, ...]]] = {}
    for entry in value:
        if not isinstance(entry, dict) or frozenset(entry) != {
            "visual_ordinal",
            "drawing_sha256",
            "receipt",
        }:
            raise VisualReferenceReceiptResolutionError("SVG label receipt entry is invalid")
        ordinal = entry.get("visual_ordinal")
        drawing_sha256 = entry.get("drawing_sha256")
        receipt_document = entry.get("receipt")
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or not isinstance(drawing_sha256, str)
            or not isinstance(receipt_document, dict)
            or ordinal in observed
        ):
            raise VisualReferenceReceiptResolutionError("SVG label receipt entry is invalid")
        try:
            validate_contract("svg-label-layout-validation-receipt", receipt_document)
            receipt = SvgLabelLayoutValidationReceipt.model_validate(receipt_document)
        except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
            raise VisualReferenceReceiptResolutionError("SVG label receipt is invalid") from exc
        observed[ordinal] = (
            drawing_sha256,
            receipt.overlay_sha256,
            receipt.required_labels,
        )
    if observed != expected:
        raise VisualReferenceReceiptResolutionError(
            "SVG label receipts do not bind the exact image drawings"
        )


__all__ = [
    "OrchestratorVisualReferenceReceiptResolver",
    "ResolvedVisualReference",
    "VisualReferenceReceiptResolutionError",
]
