"""Catalog application service for immutable redline HWPX correction Artifacts."""

from __future__ import annotations

import io
import json
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from eom_catalog_contracts import (
    ApplyDocumentReviewHwpxCorrections,
    DocumentReviewHwpxCorrectionMediaQuery,
    DocumentReviewHwpxCorrectionResponse,
    OfficeDocumentReviewMemberPointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_workflow import PdfDocumentReviewRoleResult
from eom_workflow.schemas import validate_role_result
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.document_review_hwpx import (
    DocumentReviewHwpxError,
    DocumentReviewReplacement,
    apply_document_review_hwpx_correction,
    build_document_review_hwpx_correction_plan,
)
from eom_catalog_service.settings import CatalogSettings

DOCUMENT_REVIEW_HWPX_CORRECTION_PROTOCOL_VERSION = "catalog/1.18"
DOCUMENT_REVIEW_HWPX_CORRECTION_SCHEMA_HASH = content_sha256(
    {
        "protocol": DOCUMENT_REVIEW_HWPX_CORRECTION_PROTOCOL_VERSION,
        "contracts": [
            "document-review-hwpx-correction-request/1.0",
            "document-review-hwpx-correction-plan/1.0",
            "document-review-hwpx-correction-result/1.0",
            "document-review-hwpx-correction-response/1.0",
        ],
    }
)
MAX_REVIEW_RESULT_BYTES = 16 * 1024 * 1024


class DocumentReviewHwpxCorrectionServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DocumentReviewCorrectionArtifacts(Protocol):
    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> bytes: ...

    def commit_file_set(
        self,
        *,
        files: dict[str, Path],
        primary_file: str,
        artifact_type: str,
        idempotency_key: str,
        request: dict[str, object],
        result: dict[str, object],
        file_metadata: dict[str, dict[str, str]] | None = None,
        manifest_version: str = "catalog-file-set/1.0",
        protocol_version: str,
        protocol_schema_hash: str,
        expected_file_sha256: dict[str, str] | None = None,
    ) -> CatalogArtifact: ...


@dataclass(frozen=True)
class ResolvedDocumentReviewHwpx:
    stream: BinaryIO
    media_type: str
    content_length: int
    sha256: str

    def iter_chunks(self) -> Generator[bytes, None, None]:
        try:
            while chunk := self.stream.read(1024 * 1024):
                yield chunk
        finally:
            self.stream.close()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


class DocumentReviewHwpxCorrectionService:
    """Resolve findings, create one redline successor, and commit it atomically."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.artifacts: DocumentReviewCorrectionArtifacts = CatalogArtifactService(
            engine,
            self.settings,
        )

    def apply(
        self,
        command: ApplyDocumentReviewHwpxCorrections,
    ) -> DocumentReviewHwpxCorrectionResponse:
        review_bytes = self._read_pointer(command.review_result, MAX_REVIEW_RESULT_BYTES)
        base_bytes = self._read_pointer(command.base_hwpx, 256 * 1024 * 1024)
        try:
            raw_result: object = json.loads(
                review_bytes.decode("utf-8", errors="strict"),
                object_pairs_hook=_unique_json_object,
            )
            parsed = validate_role_result(
                raw_result,
                "support",
                "pdf-document-review-result@1.0",
            )
        except (UnicodeError, ValueError) as exc:
            raise DocumentReviewHwpxCorrectionServiceError(
                "DOCUMENT_REVIEW_CORRECTION_RESULT_INVALID",
                "Document review result is invalid",
            ) from exc
        if (
            not isinstance(parsed, PdfDocumentReviewRoleResult)
            or parsed.workflow_id != command.workflow_id
        ):
            raise DocumentReviewHwpxCorrectionServiceError(
                "DOCUMENT_REVIEW_CORRECTION_RESULT_MISMATCH",
                "Document review result differs from the selected workflow",
            )
        findings = {finding.finding_id: finding for finding in parsed.output.findings}
        if set(command.finding_ids) - findings.keys():
            raise DocumentReviewHwpxCorrectionServiceError(
                "DOCUMENT_REVIEW_CORRECTION_FINDING_NOT_FOUND",
                "A selected document review finding does not exist",
            )
        replacements: list[DocumentReviewReplacement] = []
        for finding_id in command.finding_ids:
            finding = findings[finding_id]
            recommendation = finding.recommendation
            if (
                recommendation.operation != "REPLACE"
                or recommendation.before_text is None
                or recommendation.after_text is None
            ):
                raise DocumentReviewHwpxCorrectionServiceError(
                    "DOCUMENT_REVIEW_CORRECTION_FINDING_UNSUPPORTED",
                    "Only confirmed exact text replacements can be applied to HWPX",
                )
            replacements.append(
                DocumentReviewReplacement(
                    finding_id=finding.finding_id,
                    finding_code=finding.finding_code,
                    before_text=recommendation.before_text,
                    after_text=recommendation.after_text,
                )
            )
        correction_digest = content_sha256(
            {
                "workflow_id": command.workflow_id,
                "review_result": command.review_result.model_dump(mode="json"),
                "base_hwpx": command.base_hwpx.model_dump(mode="json"),
                "finding_ids": list(command.finding_ids),
            }
        ).removeprefix("sha256:")
        correction_id = f"doccorrection_{correction_digest[:32]}"
        try:
            with tempfile.TemporaryDirectory(
                prefix="document-review-correction.",
                dir=self.settings.staging_root,
            ) as raw_workspace:
                workspace = Path(raw_workspace)
                source = workspace / "source.hwpx"
                source.write_bytes(base_bytes)
                source.chmod(0o600)
                plan = build_document_review_hwpx_correction_plan(
                    source,
                    correction_id=correction_id,
                    workflow_id=command.workflow_id,
                    review_result=command.review_result,
                    base_hwpx=command.base_hwpx,
                    replacements=tuple(replacements),
                )
                output = workspace / "corrected/document-review-redline.hwpx"
                result = apply_document_review_hwpx_correction(source, output, plan)
                if (
                    result.correction_id != correction_id
                    or result.workflow_id != command.workflow_id
                    or result.plan_sha256 != plan.plan_sha256
                    or result.base_hwpx_sha256 != command.base_hwpx.sha256
                    or set(result.applied_finding_ids) != set(command.finding_ids)
                ):
                    raise DocumentReviewHwpxCorrectionServiceError(
                        "DOCUMENT_REVIEW_CORRECTION_RESULT_MISMATCH",
                        "HWPX correction result differs from its immutable request",
                    )
                plan_path = workspace / "plan.json"
                result_path = workspace / "result.json"
                plan_path.write_bytes(canonical_json_bytes(plan.model_dump(mode="json")))
                result_path.write_bytes(canonical_json_bytes(result.model_dump(mode="json")))
                plan_path.chmod(0o600)
                result_path.chmod(0o600)
                files = {
                    "result.json": result_path,
                    "plan.json": plan_path,
                    "corrected/document-review-redline.hwpx": output,
                }
                expected = {name: sha256_file(path) for name, path in files.items()}
                artifact = self.artifacts.commit_file_set(
                    files=files,
                    primary_file="result.json",
                    artifact_type="document-review-hwpx-correction",
                    idempotency_key=(f"document-review-hwpx-correction:{command.idempotency_key}"),
                    request={
                        "actor_id": command.actor_id,
                        "workflow_id": command.workflow_id,
                        "review_result": command.review_result.model_dump(mode="json"),
                        "base_hwpx": command.base_hwpx.model_dump(mode="json"),
                        "finding_ids": list(command.finding_ids),
                    },
                    result=result.model_dump(mode="json"),
                    file_metadata={
                        "result.json": {
                            "media_type": "application/json",
                            "schema_ref": (
                                "eom://schemas/document-review/"
                                "document-review-hwpx-correction-result/1.0"
                            ),
                        },
                        "plan.json": {
                            "media_type": "application/json",
                            "schema_ref": (
                                "eom://schemas/document-review/"
                                "document-review-hwpx-correction-plan/1.0"
                            ),
                        },
                        "corrected/document-review-redline.hwpx": {
                            "media_type": "application/vnd.hancom.hwpx",
                            "schema_ref": "eom://schemas/document-review/corrected-hwpx/1.0",
                        },
                    },
                    manifest_version="document-review-hwpx-correction-file-set/1.0",
                    protocol_version=DOCUMENT_REVIEW_HWPX_CORRECTION_PROTOCOL_VERSION,
                    protocol_schema_hash=DOCUMENT_REVIEW_HWPX_CORRECTION_SCHEMA_HASH,
                    expected_file_sha256=expected,
                )
        except DocumentReviewHwpxError as exc:
            raise DocumentReviewHwpxCorrectionServiceError(exc.code, str(exc)) from exc
        output_pointer = OfficeDocumentReviewMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=result.output_member.member_path,
            sha256=result.output_member.sha256,
            content_length=result.output_member.content_length,
            media_type=result.output_member.media_type,
            schema_ref="eom://schemas/document-review/corrected-hwpx/1.0",
        )
        response = DocumentReviewHwpxCorrectionResponse(
            status="OK",
            output=output_pointer,
            result=result,
        )
        validate_contract(
            "document-review-hwpx-correction-response",
            response.model_dump(mode="json", exclude_none=True),
        )
        return response

    def load_output(
        self,
        query: DocumentReviewHwpxCorrectionMediaQuery,
    ) -> ResolvedDocumentReviewHwpx:
        payload = self._read_pointer(query.output, 256 * 1024 * 1024)
        return ResolvedDocumentReviewHwpx(
            stream=io.BytesIO(payload),
            media_type=query.output.media_type,
            content_length=len(payload),
            sha256=query.output.sha256,
        )

    def _read_pointer(
        self,
        pointer: object,
        max_bytes: int,
    ) -> bytes:
        value = cast(OfficeDocumentReviewMemberPointer, pointer)
        try:
            return self.artifacts.read_member(
                artifact_id=value.artifact_id,
                revision_id=value.artifact_revision_id,
                member_path=value.member_path,
                sha256=value.sha256,
                media_type=value.media_type,
                schema_ref=value.schema_ref,
                max_bytes=max_bytes,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise DocumentReviewHwpxCorrectionServiceError(
                "DOCUMENT_REVIEW_CORRECTION_POINTER_INVALID",
                "Document review correction pointer could not be resolved",
            ) from exc
