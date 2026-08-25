"""Register source-bound educational documents through immutable Artifact revisions."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from eom_catalog_contracts import (
    EducationalDocumentRegistrationReceipt,
    EducationalDocumentRegistrationRequest,
    EducationalDocumentRevisionManifest,
    EducationalDocumentRightsAttestation,
    LegacyArtifactMemberPointer,
    TextbookAnalysisBundleManifest,
    validate_contract,
)
from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    educational_document_id,
    educational_document_registration_id,
    educational_document_revision_id,
    new_educational_document_rights_attestation_id,
    sha256_bytes,
    sha256_file,
)
from eom_orchestrator.database import build_session_factory, transaction
from pydantic import ValidationError
from sqlalchemy import Engine, or_, select

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.models import (
    EducationalDocumentRecord,
    EducationalDocumentRegistrationRecord,
    EducationalDocumentRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_TEXT_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ANALYSIS_BUNDLE_BYTES = 256 * 1024 * 1024
PDF_SOURCE_SCHEMA_REF = "eom://schemas/educational-document/pdf-source/1.0"
RIGHTS_SCHEMA_REF = "eom://schemas/educational-document/rights-attestation/1.0"
REVISION_SCHEMA_REF = "eom://schemas/educational-document/revision-manifest/1.0"
TEXTBOOK_BUNDLE_SCHEMA_REF = "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0"
MARKDOWN_SCHEMA_REF = "eom://schemas/educational-document/extracted-markdown/1.0"
EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL = "educational-document/1.0"
EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL_HASH = content_sha256(
    {
        "protocol": EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL,
        "contracts": ("analysis", "revision", "rights", "source"),
    }
)


class EducationalDocumentError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PreparedTextbookBundle:
    manifest: TextbookAnalysisBundleManifest
    member_files: dict[str, Path]
    member_hashes: dict[str, str]


@dataclass(frozen=True)
class ReservedRegistration:
    document_registration_id: str
    document_id: str
    document_revision_id: str
    revision_number: int
    previous_revision_id: str | None
    state: str


def load_educational_document_registration_request(
    path: Path,
) -> EducationalDocumentRegistrationRequest:
    try:
        raw = _read_regular_bytes(path.absolute(), max_bytes=MAX_JSON_BYTES, exact_mode=0o600)
        value: object = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        validate_contract("educational-document-registration-request", value)
        return EducationalDocumentRegistrationRequest.model_validate(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_REQUEST_INVALID") from exc


def prepare_textbook_registration_request(
    *,
    source_path: Path,
    analysis_bundle_root: Path,
    document_key: str,
    edition_label: str,
    registered_by: str,
    registration_key: str,
    confirmation_reference: str,
    registered_at: datetime | None = None,
) -> EducationalDocumentRegistrationRequest:
    """Build a source-hashed request without committing DB, NAS, workflow, or worker state."""

    actual_registered_at = registered_at or datetime.now(UTC)
    try:
        source_path = source_path.absolute()
        source_metadata = _require_regular_file(source_path, max_bytes=1024 * 1024 * 1024)
        source_sha256 = sha256_file(source_path)
        manifest_raw = _read_regular_bytes(
            analysis_bundle_root.absolute() / "manifest.json",
            max_bytes=MAX_JSON_BYTES,
            exact_mode=0o400,
        )
        manifest_value: object = json.loads(manifest_raw)
        if not isinstance(manifest_value, dict):
            raise ValueError
        validate_contract("textbook-analysis-bundle-manifest", manifest_value)
        bundle = TextbookAnalysisBundleManifest.model_validate(manifest_value)
        rights_value: dict[str, Any] = {
            "schema_version": "educational-document-rights-attestation/1.0",
            "rights_attestation_id": new_educational_document_rights_attestation_id(),
            "source_sha256": source_sha256,
            "source_media_type": "application/pdf",
            "rights_state": "CLEARED_LICENSED",
            "basis": "PURCHASED_AND_NEGOTIATED",
            "permitted_uses": [
                "GRAPH_INDEXING",
                "INTERNAL_ARCHIVAL",
                "INTERNAL_REVIEW",
                "ITEM_AUTHORING_GROUNDING",
                "KNOWLEDGE_ANALYSIS",
                "TEXT_EXTRACTION",
            ],
            "allowed_roles": [
                "ADMIN",
                "DATA_ANALYST_WORKER",
                "HUMAN_EDITOR",
                "ITEM_AUTHORING_WORKER",
                "RIGHTS_REVIEWER",
            ],
            "answer_bearing": True,
            "attribution_required": True,
            "retention_policy_key": "licensed-source.default",
            "withdrawal_behavior": "RETIRE_FROM_NEW_RETRIEVAL",
            "confirmation_reference": confirmation_reference,
            "reviewed_at": actual_registered_at.isoformat().replace("+00:00", "Z"),
            "reviewed_by": registered_by,
        }
        rights_value["rights_attestation_sha256"] = content_sha256(rights_value)
        request_value: dict[str, Any] = {
            "schema_version": "educational-document-registration-request/1.0",
            "identity": {
                "document_key": document_key,
                "document_kind": "TEXTBOOK",
                "publisher_key": bundle.document.publisher_key,
                "publisher_label": bundle.document.publisher_label,
                "title": bundle.document.title,
                "curriculum_volume": bundle.document.curriculum_volume,
                "edition_label": edition_label,
                "language": bundle.document.language,
            },
            "expected_source_sha256": source_sha256,
            "expected_source_size_bytes": source_metadata.st_size,
            "expected_source_page_count": bundle.source.page_count,
            "expected_analysis_manifest_sha256": sha256_bytes(manifest_raw),
            "rights": rights_value,
            "registration_key": registration_key,
            "registered_at": actual_registered_at.isoformat().replace("+00:00", "Z"),
            "registered_by": registered_by,
        }
        request_value["request_sha256"] = content_sha256(request_value)
        validate_contract("educational-document-registration-request", request_value)
        request = EducationalDocumentRegistrationRequest.model_validate(request_value)
        EducationalDocumentService._validate_source(source_path, request)
        EducationalDocumentService._validate_bundle(analysis_bundle_root.absolute(), request)
        return request
    except EducationalDocumentError:
        raise
    except Exception as exc:
        raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_REQUEST_PREPARATION_FAILED") from exc


def write_educational_document_registration_request(
    path: Path, request: EducationalDocumentRegistrationRequest
) -> None:
    """Create one protected request file without replacing an existing operator decision."""

    path = path.absolute()
    try:
        parent = path.parent
        parent_metadata = parent.lstat()
        if (
            parent.is_symlink()
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise ValueError
        _write_exclusive(path, canonical_json_bytes(request))
    except (OSError, ValueError) as exc:
        raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_REQUEST_OUTPUT_INVALID") from exc


class EducationalDocumentService:
    """Application service for idempotent document registration and pointer inspection."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def register_textbook(
        self,
        request: EducationalDocumentRegistrationRequest,
        *,
        source_path: Path,
        analysis_bundle_root: Path,
    ) -> EducationalDocumentRegistrationReceipt:
        self._validate_request(request)
        source_path = source_path.absolute()
        analysis_bundle_root = analysis_bundle_root.absolute()
        self._validate_source(source_path, request)
        prepared = self._validate_bundle(analysis_bundle_root, request)
        reservation = self._reserve(request)
        if reservation.state == "COMMITTED":
            return self._receipt(reservation.document_revision_id, verify=True)

        try:
            source_artifact = self._publish_source(request, source_path)
            source_pointer = self._pointer(
                source_artifact,
                member_path="source/original.pdf",
                schema_ref=PDF_SOURCE_SCHEMA_REF,
                media_type="application/pdf",
            )
            rights_artifact = self._publish_rights(request)
            rights_pointer = self._pointer(
                rights_artifact,
                member_path="rights/attestation.json",
                schema_ref=RIGHTS_SCHEMA_REF,
                media_type="application/json",
            )
            analysis_artifact, canonical_analysis = self._publish_analysis(
                request,
                prepared,
                source_pointer,
            )
            analysis_pointer = self._pointer(
                analysis_artifact,
                member_path="analysis/manifest.json",
                schema_ref=TEXTBOOK_BUNDLE_SCHEMA_REF,
                media_type="application/json",
            )
            revision_manifest = self._revision_manifest(
                request=request,
                reservation=reservation,
                source=source_pointer,
                analysis=analysis_pointer,
                rights=rights_pointer,
            )
            revision_artifact = self._publish_revision_manifest(request, revision_manifest)
            revision_pointer = self._pointer(
                revision_artifact,
                member_path="document/document-revision.json",
                schema_ref=REVISION_SCHEMA_REF,
                media_type="application/json",
            )
            receipt = EducationalDocumentRegistrationReceipt(
                document_id=reservation.document_id,
                document_revision_id=reservation.document_revision_id,
                revision_number=reservation.revision_number,
                registration_request_sha256=request.request_sha256,
                revision_manifest=revision_pointer,
                source=source_pointer,
                analysis_bundle_manifest=analysis_pointer,
                rights_attestation=rights_pointer,
            )
            validate_contract(
                "educational-document-registration-receipt",
                receipt.model_dump(mode="json"),
            )
            self._commit_registration(
                request=request,
                reservation=reservation,
                revision_manifest=revision_manifest,
                receipt=receipt,
                canonical_analysis=canonical_analysis,
            )
            return receipt
        except Exception as exc:
            failure_code = (
                exc.code
                if isinstance(exc, EducationalDocumentError)
                else "EDUCATIONAL_DOCUMENT_REGISTRATION_FAILED"
            )
            self._record_failure(reservation.document_registration_id, failure_code)
            raise

    def inspect(self, document_id_or_key: str) -> EducationalDocumentRegistrationReceipt:
        with self.sessions() as session:
            document = session.scalar(
                select(EducationalDocumentRecord).where(
                    or_(
                        EducationalDocumentRecord.document_id == document_id_or_key,
                        EducationalDocumentRecord.document_key == document_id_or_key,
                    )
                )
            )
            if document is None or document.current_revision_id is None:
                raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_NOT_FOUND")
            revision_id = document.current_revision_id
        return self._receipt(revision_id, verify=True)

    def list_current(self) -> tuple[EducationalDocumentRegistrationReceipt, ...]:
        with self.sessions() as session:
            revision_ids = tuple(
                session.scalars(
                    select(EducationalDocumentRecord.current_revision_id)
                    .where(EducationalDocumentRecord.current_revision_id.is_not(None))
                    .order_by(EducationalDocumentRecord.document_key)
                )
            )
        return tuple(self._receipt(str(revision_id), verify=False) for revision_id in revision_ids)

    @staticmethod
    def _validate_request(request: EducationalDocumentRegistrationRequest) -> None:
        try:
            validate_contract(
                "educational-document-registration-request", request.model_dump(mode="json")
            )
        except Exception as exc:
            raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_REQUEST_INVALID") from exc
        if request.identity.document_kind != "TEXTBOOK":
            raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_KIND_UNSUPPORTED")

    @staticmethod
    def _validate_source(
        source_path: Path, request: EducationalDocumentRegistrationRequest
    ) -> None:
        try:
            metadata = _require_regular_file(source_path, max_bytes=1024 * 1024 * 1024)
            if (
                source_path.suffix.casefold() != ".pdf"
                or stat.S_IMODE(metadata.st_mode) != 0o400
                or metadata.st_size != request.expected_source_size_bytes
                or sha256_file(source_path) != request.expected_source_sha256
            ):
                raise ValueError
            with source_path.open("rb") as stream:
                if not stream.read(8).startswith(b"%PDF-"):
                    raise ValueError
        except (OSError, ValueError) as exc:
            raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_SOURCE_INVALID") from exc

    @staticmethod
    def _validate_bundle(
        bundle_root: Path,
        request: EducationalDocumentRegistrationRequest,
    ) -> PreparedTextbookBundle:
        try:
            root_metadata = bundle_root.lstat()
            pages_root = bundle_root / "pages"
            pages_metadata = pages_root.lstat()
            if (
                bundle_root.is_symlink()
                or not stat.S_ISDIR(root_metadata.st_mode)
                or stat.S_IMODE(root_metadata.st_mode) != 0o500
                or root_metadata.st_uid != os.geteuid()
                or pages_root.is_symlink()
                or not stat.S_ISDIR(pages_metadata.st_mode)
                or stat.S_IMODE(pages_metadata.st_mode) != 0o500
                or pages_metadata.st_uid != os.geteuid()
            ):
                raise ValueError
            manifest_path = bundle_root / "manifest.json"
            raw_manifest = _read_regular_bytes(
                manifest_path,
                max_bytes=MAX_JSON_BYTES,
                exact_mode=0o400,
            )
            if sha256_bytes(raw_manifest) != request.expected_analysis_manifest_sha256:
                raise ValueError
            value: object = json.loads(raw_manifest)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract("textbook-analysis-bundle-manifest", value)
            manifest = TextbookAnalysisBundleManifest.model_validate(value)
            if (
                manifest.bundle_state != "PRE_CANONICAL_REVIEW_ONLY"
                or manifest.canonical_source is not None
                or manifest.source.sha256 != request.expected_source_sha256
                or manifest.source.size_bytes != request.expected_source_size_bytes
                or manifest.source.page_count != request.expected_source_page_count
                or manifest.document.publisher_key != request.identity.publisher_key
                or manifest.document.publisher_label != request.identity.publisher_label
                or manifest.document.title.replace(" ", "")
                != request.identity.title.replace(" ", "")
                or manifest.document.curriculum_volume != request.identity.curriculum_volume
                or manifest.document.language != request.identity.language
            ):
                raise ValueError
            member_files: dict[str, Path] = {
                manifest.index_member.member_path: bundle_root / manifest.index_member.member_path
            }
            member_hashes: dict[str, str] = {
                manifest.index_member.member_path: manifest.index_member.member_sha256
            }
            for page in manifest.pages:
                if page.member_path in member_files:
                    raise ValueError
                member_files[page.member_path] = bundle_root / page.member_path
                member_hashes[page.member_path] = page.member_sha256
            expected_paths = {"manifest.json", *member_files}
            actual_paths = {
                child.relative_to(bundle_root).as_posix()
                for child in bundle_root.rglob("*")
                if child.is_file() or child.is_symlink()
            }
            if actual_paths != expected_paths:
                raise ValueError
            total_bytes = len(raw_manifest)
            for relative_path, path in member_files.items():
                if PurePosixPath(relative_path).as_posix() != relative_path:
                    raise ValueError
                metadata = _require_regular_file(path, max_bytes=MAX_TEXT_MEMBER_BYTES)
                if (
                    stat.S_IMODE(metadata.st_mode) != 0o400
                    or sha256_file(path) != member_hashes[relative_path]
                ):
                    raise ValueError
                total_bytes += metadata.st_size
            if total_bytes > MAX_ANALYSIS_BUNDLE_BYTES:
                raise ValueError
            anchor_ids = {page.anchor_id for page in manifest.pages}
            for mapping in manifest.curriculum_mappings:
                if not set(mapping.evidence_anchor_ids).issubset(anchor_ids):
                    raise ValueError
            return PreparedTextbookBundle(
                manifest=manifest,
                member_files=member_files,
                member_hashes=member_hashes,
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_ANALYSIS_INVALID") from exc

    def _reserve(self, request: EducationalDocumentRegistrationRequest) -> ReservedRegistration:
        document_id = educational_document_id(request.identity.document_key)
        revision_id = educational_document_revision_id(request.request_sha256)
        registration_id = educational_document_registration_id(request.request_sha256)
        with transaction(self.sessions) as session:
            existing = session.scalar(
                select(EducationalDocumentRegistrationRecord).where(
                    or_(
                        EducationalDocumentRegistrationRecord.registration_key
                        == request.registration_key,
                        EducationalDocumentRegistrationRecord.registration_request_sha256
                        == request.request_sha256,
                    )
                )
            )
            if existing is not None:
                if (
                    existing.registration_key != request.registration_key
                    or existing.registration_request_sha256 != request.request_sha256
                    or existing.document_id != document_id
                    or existing.document_revision_id != revision_id
                ):
                    raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_IDEMPOTENCY_CONFLICT")
                if existing.state == "FAILED":
                    existing.state = "PREPARED"
                    existing.completed_at = None
                existing.failure_code = None
                existing.updated_at = datetime.now(UTC)
                existing.lock_version += 1
                return _reserved(existing)

            document = session.execute(
                select(EducationalDocumentRecord)
                .where(EducationalDocumentRecord.document_id == document_id)
                .with_for_update()
            ).scalar_one_or_none()
            if document is None:
                document = EducationalDocumentRecord(
                    document_id=document_id,
                    document_key=request.identity.document_key,
                    document_kind=request.identity.document_kind,
                    lifecycle_state="ACTIVE",
                    current_revision_id=None,
                    created_at=request.registered_at,
                    created_by=request.registered_by,
                    lock_version=1,
                )
                session.add(document)
                session.flush()
            elif (
                document.document_key != request.identity.document_key
                or document.document_kind != request.identity.document_kind
                or document.lifecycle_state != "ACTIVE"
            ):
                raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_IDENTITY_CONFLICT")

            highest_registration = session.scalar(
                select(EducationalDocumentRegistrationRecord)
                .where(EducationalDocumentRegistrationRecord.document_id == document_id)
                .order_by(EducationalDocumentRegistrationRecord.revision_number.desc())
                .limit(1)
            )
            if highest_registration is not None:
                if highest_registration.state != "COMMITTED":
                    raise EducationalDocumentError(
                        "EDUCATIONAL_DOCUMENT_PREVIOUS_REGISTRATION_INCOMPLETE"
                    )
                if document.current_revision_id != highest_registration.document_revision_id:
                    raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_CURRENT_POINTER_STALE")
                revision_number = highest_registration.revision_number + 1
                previous_revision_id = highest_registration.document_revision_id
            elif document.current_revision_id is not None:
                current = session.get(
                    EducationalDocumentRevisionRecord, document.current_revision_id
                )
                if current is None:
                    raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_CURRENT_POINTER_STALE")
                revision_number = current.revision_number + 1
                previous_revision_id = current.document_revision_id
            else:
                revision_number = 1
                previous_revision_id = None
            registration = EducationalDocumentRegistrationRecord(
                document_registration_id=registration_id,
                registration_key=request.registration_key,
                registration_request_sha256=request.request_sha256,
                document_id=document_id,
                document_revision_id=revision_id,
                revision_number=revision_number,
                previous_revision_id=previous_revision_id,
                state="PREPARED",
                failure_code=None,
                created_at=request.registered_at,
                updated_at=request.registered_at,
                completed_at=None,
                lock_version=1,
            )
            session.add(registration)
            session.flush()
            return _reserved(registration)

    def _publish_source(
        self, request: EducationalDocumentRegistrationRequest, source_path: Path
    ) -> CatalogArtifact:
        member = "source/original.pdf"
        return self.artifacts.commit_file_set(
            files={member: source_path},
            primary_file=member,
            artifact_type="educational-document-source",
            idempotency_key=f"educational-document-source:{request.expected_source_sha256}",
            request={
                "schema_version": "educational-document-source-commit-request/1.0",
                "source_sha256": request.expected_source_sha256,
                "source_size_bytes": request.expected_source_size_bytes,
            },
            result={
                "schema_version": "educational-document-source-commit-result/1.0",
                "source_sha256": request.expected_source_sha256,
                "source_size_bytes": request.expected_source_size_bytes,
            },
            file_metadata={
                member: {"media_type": "application/pdf", "schema_ref": PDF_SOURCE_SCHEMA_REF}
            },
            manifest_version="educational-document-source-artifact/1.0",
            protocol_version=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL,
            protocol_schema_hash=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL_HASH,
            expected_file_sha256={member: request.expected_source_sha256},
        )

    def _publish_rights(self, request: EducationalDocumentRegistrationRequest) -> CatalogArtifact:
        payload = canonical_json_bytes(request.rights)
        expected = sha256_bytes(payload)
        with tempfile.TemporaryDirectory(
            prefix="educational-rights-", dir=self.settings.staging_root
        ) as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "attestation.json"
            _write_exclusive(path, payload)
            return self.artifacts.commit_file_set(
                files={"rights/attestation.json": path},
                primary_file="rights/attestation.json",
                artifact_type="educational-document-rights",
                idempotency_key=(
                    f"educational-document-rights:{request.rights.rights_attestation_sha256}"
                ),
                request={
                    "schema_version": "educational-document-rights-commit-request/1.0",
                    "rights_attestation_sha256": (request.rights.rights_attestation_sha256),
                    "source_sha256": request.expected_source_sha256,
                },
                result={
                    "schema_version": "educational-document-rights-commit-result/1.0",
                    "rights_state": request.rights.rights_state,
                    "source_sha256": request.expected_source_sha256,
                },
                file_metadata={
                    "rights/attestation.json": {
                        "media_type": "application/json",
                        "schema_ref": RIGHTS_SCHEMA_REF,
                    }
                },
                manifest_version="educational-document-rights-artifact/1.0",
                protocol_version=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL,
                protocol_schema_hash=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL_HASH,
                expected_file_sha256={"rights/attestation.json": expected},
            )

    def _publish_analysis(
        self,
        request: EducationalDocumentRegistrationRequest,
        prepared: PreparedTextbookBundle,
        source: LegacyArtifactMemberPointer,
    ) -> tuple[CatalogArtifact, TextbookAnalysisBundleManifest]:
        value = prepared.manifest.model_dump(mode="json")
        value["bundle_state"] = "CANONICAL"
        value["canonical_source"] = source.model_dump(mode="json")
        value["manifest_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "manifest_sha256"}
        )
        validate_contract("textbook-analysis-bundle-manifest", value)
        canonical = TextbookAnalysisBundleManifest.model_validate(value)
        manifest_payload = canonical_json_bytes(canonical)
        manifest_hash = sha256_bytes(manifest_payload)
        with tempfile.TemporaryDirectory(
            prefix="educational-analysis-", dir=self.settings.staging_root
        ) as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            manifest_path = root / "manifest.json"
            _write_exclusive(manifest_path, manifest_payload)
            files: dict[str, Path] = {"analysis/manifest.json": manifest_path}
            expected: dict[str, str] = {"analysis/manifest.json": manifest_hash}
            metadata: dict[str, dict[str, str]] = {
                "analysis/manifest.json": {
                    "media_type": "application/json",
                    "schema_ref": TEXTBOOK_BUNDLE_SCHEMA_REF,
                }
            }
            for relative_path, source_path in prepared.member_files.items():
                target = f"analysis/{relative_path}"
                files[target] = source_path
                expected[target] = prepared.member_hashes[relative_path]
                metadata[target] = {
                    "media_type": "text/markdown; charset=utf-8",
                    "schema_ref": MARKDOWN_SCHEMA_REF,
                }
            artifact = self.artifacts.commit_file_set(
                files=files,
                primary_file="analysis/manifest.json",
                artifact_type="educational-document-analysis",
                idempotency_key=(
                    f"educational-document-analysis:{request.identity.document_key}:{manifest_hash}"
                ),
                request={
                    "schema_version": "educational-document-analysis-commit-request/1.0",
                    "document_key": request.identity.document_key,
                    "source_sha256": request.expected_source_sha256,
                    "canonical_manifest_sha256": manifest_hash,
                },
                result={
                    "schema_version": "educational-document-analysis-commit-result/1.0",
                    "page_count": len(canonical.pages),
                    "curriculum_mapping_count": len(canonical.curriculum_mappings),
                    "canonical_manifest_sha256": manifest_hash,
                },
                file_metadata=metadata,
                manifest_version="educational-document-analysis-artifact/1.0",
                protocol_version=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL,
                protocol_schema_hash=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL_HASH,
                expected_file_sha256=expected,
            )
        return artifact, canonical

    @staticmethod
    def _revision_manifest(
        *,
        request: EducationalDocumentRegistrationRequest,
        reservation: ReservedRegistration,
        source: LegacyArtifactMemberPointer,
        analysis: LegacyArtifactMemberPointer,
        rights: LegacyArtifactMemberPointer,
    ) -> EducationalDocumentRevisionManifest:
        value: dict[str, Any] = {
            "schema_version": "educational-document-revision-manifest/1.0",
            "document_id": reservation.document_id,
            "document_revision_id": reservation.document_revision_id,
            "revision_number": reservation.revision_number,
            "previous_revision_id": reservation.previous_revision_id,
            "identity": request.identity.model_dump(mode="json"),
            "source": source.model_dump(mode="json"),
            "source_size_bytes": request.expected_source_size_bytes,
            "source_page_count": request.expected_source_page_count,
            "analysis_bundle_manifest": analysis.model_dump(mode="json"),
            "analysis_bundle_root": "analysis",
            "rights_attestation": rights.model_dump(mode="json"),
            # Hash the wire representation used by the JSON Schema/Pydantic boundary.
            # Hashing the datetime object directly would force fixed microseconds in
            # canonical_json_bytes, while Pydantic omits zero microseconds.
            "registered_at": request.registered_at.isoformat().replace("+00:00", "Z"),
            "registered_by": request.registered_by,
            "registration_request_sha256": request.request_sha256,
        }
        value["document_revision_sha256"] = content_sha256(value)
        manifest = EducationalDocumentRevisionManifest.model_validate(value)
        validate_contract(
            "educational-document-revision-manifest", manifest.model_dump(mode="json")
        )
        return manifest

    def _publish_revision_manifest(
        self,
        request: EducationalDocumentRegistrationRequest,
        manifest: EducationalDocumentRevisionManifest,
    ) -> CatalogArtifact:
        payload = canonical_json_bytes(manifest)
        expected = sha256_bytes(payload)
        with tempfile.TemporaryDirectory(
            prefix="educational-revision-", dir=self.settings.staging_root
        ) as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "document-revision.json"
            _write_exclusive(path, payload)
            return self.artifacts.commit_file_set(
                files={"document/document-revision.json": path},
                primary_file="document/document-revision.json",
                artifact_type="educational-document-revision-manifest",
                idempotency_key=(
                    f"educational-document-revision:{manifest.document_revision_id}:"
                    f"{manifest.document_revision_sha256}"
                ),
                request={
                    "schema_version": "educational-document-revision-commit-request/1.0",
                    "document_id": manifest.document_id,
                    "document_revision_id": manifest.document_revision_id,
                    "registration_request_sha256": request.request_sha256,
                    "document_revision_sha256": manifest.document_revision_sha256,
                },
                result={
                    "schema_version": "educational-document-revision-commit-result/1.0",
                    "document_id": manifest.document_id,
                    "document_revision_id": manifest.document_revision_id,
                    "revision_number": manifest.revision_number,
                },
                file_metadata={
                    "document/document-revision.json": {
                        "media_type": "application/json",
                        "schema_ref": REVISION_SCHEMA_REF,
                    }
                },
                manifest_version="educational-document-revision-artifact/1.0",
                protocol_version=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL,
                protocol_schema_hash=EDUCATIONAL_DOCUMENT_ARTIFACT_PROTOCOL_HASH,
                expected_file_sha256={"document/document-revision.json": expected},
            )

    def _commit_registration(
        self,
        *,
        request: EducationalDocumentRegistrationRequest,
        reservation: ReservedRegistration,
        revision_manifest: EducationalDocumentRevisionManifest,
        receipt: EducationalDocumentRegistrationReceipt,
        canonical_analysis: TextbookAnalysisBundleManifest,
    ) -> None:
        with transaction(self.sessions) as session:
            registration = session.execute(
                select(EducationalDocumentRegistrationRecord)
                .where(
                    EducationalDocumentRegistrationRecord.document_registration_id
                    == reservation.document_registration_id
                )
                .with_for_update()
            ).scalar_one()
            document = session.execute(
                select(EducationalDocumentRecord)
                .where(EducationalDocumentRecord.document_id == reservation.document_id)
                .with_for_update()
            ).scalar_one()
            existing = session.get(
                EducationalDocumentRevisionRecord, reservation.document_revision_id
            )
            if registration.state == "COMMITTED":
                if (
                    existing is None
                    or document.current_revision_id != existing.document_revision_id
                ):
                    raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_COMMIT_STALE")
                return
            if (
                registration.registration_request_sha256 != request.request_sha256
                or registration.document_revision_id != reservation.document_revision_id
                or document.current_revision_id != reservation.previous_revision_id
            ):
                raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_CONCURRENCY_CONFLICT")
            if existing is not None:
                raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_REVISION_CONFLICT")
            revision = EducationalDocumentRevisionRecord(
                document_revision_id=reservation.document_revision_id,
                document_id=reservation.document_id,
                revision_number=reservation.revision_number,
                previous_revision_id=reservation.previous_revision_id,
                revision_state="APPROVED",
                registration_key=request.registration_key,
                registration_request_sha256=request.request_sha256,
                publisher_key=request.identity.publisher_key,
                publisher_label=request.identity.publisher_label,
                title=request.identity.title,
                curriculum_volume=request.identity.curriculum_volume,
                edition_label=request.identity.edition_label,
                language=request.identity.language,
                source_artifact_id=receipt.source.artifact_id,
                source_artifact_revision_id=receipt.source.artifact_revision_id,
                source_sha256=receipt.source.sha256,
                source_size_bytes=request.expected_source_size_bytes,
                source_page_count=request.expected_source_page_count,
                analysis_artifact_id=receipt.analysis_bundle_manifest.artifact_id,
                analysis_artifact_revision_id=(
                    receipt.analysis_bundle_manifest.artifact_revision_id
                ),
                analysis_manifest_sha256=receipt.analysis_bundle_manifest.sha256,
                rights_artifact_id=receipt.rights_attestation.artifact_id,
                rights_artifact_revision_id=(receipt.rights_attestation.artifact_revision_id),
                rights_attestation_sha256=receipt.rights_attestation.sha256,
                revision_manifest_artifact_id=receipt.revision_manifest.artifact_id,
                revision_manifest_artifact_revision_id=(
                    receipt.revision_manifest.artifact_revision_id
                ),
                revision_manifest_sha256=receipt.revision_manifest.sha256,
                created_at=request.registered_at,
                created_by=request.registered_by,
            )
            session.add(revision)
            # The current-revision pointer has a real FK to this immutable row.
            # There is no ORM relationship whose dependency sorter could infer
            # the order, so make the INSERT visible before updating the pointer.
            session.flush([revision])
            document.current_revision_id = reservation.document_revision_id
            document.lock_version += 1
            registration.state = "COMMITTED"
            registration.failure_code = None
            registration.updated_at = datetime.now(UTC)
            registration.completed_at = datetime.now(UTC)
            registration.lock_version += 1
            if (
                canonical_analysis.canonical_source is None
                or canonical_analysis.canonical_source.sha256 != receipt.source.sha256
                or revision_manifest.document_revision_sha256
                != content_sha256(
                    revision_manifest.model_dump(mode="json", exclude={"document_revision_sha256"})
                )
            ):
                raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_POINTER_MISMATCH")

    def _record_failure(self, registration_id: str, failure_code: str) -> None:
        try:
            with transaction(self.sessions) as session:
                registration = session.execute(
                    select(EducationalDocumentRegistrationRecord)
                    .where(
                        EducationalDocumentRegistrationRecord.document_registration_id
                        == registration_id
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if registration is not None and registration.state == "PREPARED":
                    failed_at = datetime.now(UTC)
                    registration.state = "FAILED"
                    registration.failure_code = failure_code[:64]
                    registration.updated_at = failed_at
                    registration.completed_at = failed_at
                    registration.lock_version += 1
        except Exception:
            return

    def _receipt(
        self, document_revision_id: str, *, verify: bool
    ) -> EducationalDocumentRegistrationReceipt:
        with self.sessions() as session:
            revision = session.get(EducationalDocumentRevisionRecord, document_revision_id)
            if revision is None or revision.revision_state != "APPROVED":
                raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_REVISION_NOT_FOUND")
            receipt = EducationalDocumentRegistrationReceipt(
                document_id=revision.document_id,
                document_revision_id=revision.document_revision_id,
                revision_number=revision.revision_number,
                registration_request_sha256=revision.registration_request_sha256,
                revision_manifest=LegacyArtifactMemberPointer(
                    artifact_id=revision.revision_manifest_artifact_id,
                    artifact_revision_id=revision.revision_manifest_artifact_revision_id,
                    member_path="document/document-revision.json",
                    schema_ref=REVISION_SCHEMA_REF,
                    media_type="application/json",
                    sha256=revision.revision_manifest_sha256,
                ),
                source=LegacyArtifactMemberPointer(
                    artifact_id=revision.source_artifact_id,
                    artifact_revision_id=revision.source_artifact_revision_id,
                    member_path="source/original.pdf",
                    schema_ref=PDF_SOURCE_SCHEMA_REF,
                    media_type="application/pdf",
                    sha256=revision.source_sha256,
                ),
                analysis_bundle_manifest=LegacyArtifactMemberPointer(
                    artifact_id=revision.analysis_artifact_id,
                    artifact_revision_id=revision.analysis_artifact_revision_id,
                    member_path="analysis/manifest.json",
                    schema_ref=TEXTBOOK_BUNDLE_SCHEMA_REF,
                    media_type="application/json",
                    sha256=revision.analysis_manifest_sha256,
                ),
                rights_attestation=LegacyArtifactMemberPointer(
                    artifact_id=revision.rights_artifact_id,
                    artifact_revision_id=revision.rights_artifact_revision_id,
                    member_path="rights/attestation.json",
                    schema_ref=RIGHTS_SCHEMA_REF,
                    media_type="application/json",
                    sha256=revision.rights_attestation_sha256,
                ),
            )
        validate_contract(
            "educational-document-registration-receipt", receipt.model_dump(mode="json")
        )
        if verify:
            self._verify_receipt(receipt)
        return receipt

    def _verify_receipt(self, receipt: EducationalDocumentRegistrationReceipt) -> None:
        for pointer, max_bytes in (
            (receipt.source, 1024 * 1024 * 1024),
            (receipt.analysis_bundle_manifest, MAX_JSON_BYTES),
            (receipt.rights_attestation, MAX_JSON_BYTES),
            (receipt.revision_manifest, MAX_JSON_BYTES),
        ):
            self.artifacts.verify_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=max_bytes,
            )
        try:
            rights_value = json.loads(
                self.artifacts.read_member(
                    artifact_id=receipt.rights_attestation.artifact_id,
                    revision_id=receipt.rights_attestation.artifact_revision_id,
                    member_path=receipt.rights_attestation.member_path,
                    sha256=receipt.rights_attestation.sha256,
                    media_type=receipt.rights_attestation.media_type,
                    schema_ref=receipt.rights_attestation.schema_ref,
                    max_bytes=MAX_JSON_BYTES,
                )
            )
            analysis_value = json.loads(
                self.artifacts.read_member(
                    artifact_id=receipt.analysis_bundle_manifest.artifact_id,
                    revision_id=receipt.analysis_bundle_manifest.artifact_revision_id,
                    member_path=receipt.analysis_bundle_manifest.member_path,
                    sha256=receipt.analysis_bundle_manifest.sha256,
                    media_type=receipt.analysis_bundle_manifest.media_type,
                    schema_ref=receipt.analysis_bundle_manifest.schema_ref,
                    max_bytes=MAX_JSON_BYTES,
                )
            )
            revision_value = json.loads(
                self.artifacts.read_member(
                    artifact_id=receipt.revision_manifest.artifact_id,
                    revision_id=receipt.revision_manifest.artifact_revision_id,
                    member_path=receipt.revision_manifest.member_path,
                    sha256=receipt.revision_manifest.sha256,
                    media_type=receipt.revision_manifest.media_type,
                    schema_ref=receipt.revision_manifest.schema_ref,
                    max_bytes=MAX_JSON_BYTES,
                )
            )
            if not all(
                isinstance(value, dict) for value in (rights_value, analysis_value, revision_value)
            ):
                raise ValueError
            validate_contract("educational-document-rights-attestation", rights_value)
            validate_contract("textbook-analysis-bundle-manifest", analysis_value)
            validate_contract("educational-document-revision-manifest", revision_value)
            parsed_rights = EducationalDocumentRightsAttestation.model_validate(rights_value)
            parsed_analysis = TextbookAnalysisBundleManifest.model_validate(analysis_value)
            parsed_revision = EducationalDocumentRevisionManifest.model_validate(revision_value)
            if (
                parsed_rights.source_sha256 != receipt.source.sha256
                or parsed_analysis.canonical_source != receipt.source
                or parsed_revision.document_id != receipt.document_id
                or parsed_revision.document_revision_id != receipt.document_revision_id
                or parsed_revision.source != receipt.source
                or parsed_revision.analysis_bundle_manifest != receipt.analysis_bundle_manifest
                or parsed_revision.rights_attestation != receipt.rights_attestation
            ):
                raise ValueError
        except Exception as exc:
            raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_POINTER_MISMATCH") from exc

    @staticmethod
    def _pointer(
        artifact: CatalogArtifact,
        *,
        member_path: str,
        schema_ref: str,
        media_type: str,
    ) -> LegacyArtifactMemberPointer:
        matching = [
            member
            for member in artifact.manifest.get("files", [])
            if isinstance(member, dict) and member.get("file_name") == member_path
        ]
        if (
            len(matching) != 1
            or matching[0].get("sha256") != artifact.content_hash
            or matching[0].get("schema_ref") != schema_ref
            or matching[0].get("media_type") != media_type
        ):
            raise EducationalDocumentError("EDUCATIONAL_DOCUMENT_ARTIFACT_INVALID")
        return LegacyArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=member_path,
            schema_ref=schema_ref,
            media_type=media_type,
            sha256=artifact.content_hash,
        )


def _reserved(record: EducationalDocumentRegistrationRecord) -> ReservedRegistration:
    return ReservedRegistration(
        document_registration_id=record.document_registration_id,
        document_id=record.document_id,
        document_revision_id=record.document_revision_id,
        revision_number=record.revision_number,
        previous_revision_id=record.previous_revision_id,
        state=record.state,
    )


def _require_regular_file(path: Path, *, max_bytes: int) -> os.stat_result:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        or metadata.st_size < 1
        or metadata.st_size > max_bytes
        or stat.S_IMODE(metadata.st_mode) & 0o037
    ):
        raise ValueError("untrusted file metadata")
    return metadata


def _read_regular_bytes(path: Path, *, max_bytes: int, exact_mode: int) -> bytes:
    metadata = _require_regular_file(path, max_bytes=max_bytes)
    if stat.S_IMODE(metadata.st_mode) != exact_mode:
        raise ValueError("untrusted file mode")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
        ):
            raise ValueError("file changed during open")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if not payload or len(payload) > max_bytes or len(payload) != metadata.st_size:
            raise ValueError("file size changed during read")
        return payload
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short educational-document write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
