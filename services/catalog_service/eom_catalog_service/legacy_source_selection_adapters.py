"""Catalog infrastructure adapters for reviewed legacy-source selection."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from eom_catalog_contracts import (
    LegacyKnowledgeContractErrorCode,
    LegacyRightsReviewPointerV2,
    LegacySourceRightsReviewV2,
    LegacySourceSelectionV2,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.intake_service import IntakeService, IntakeSourceDeclaration
from eom_catalog_service.legacy_source_selection_boundary import (
    LegacyContentIntakeReceipt,
    LegacySelectionArtifactReceipt,
    LegacySourceSelectionError,
)
from eom_catalog_service.settings import CatalogSettings

MAX_RIGHTS_REVIEW_BYTES = 2 * 1024 * 1024
_OPEN_WRITE_EXCLUSIVE = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)

LEGACY_SELECTION_PROTOCOL_VERSION = "legacy-source-selection/2.0"
LEGACY_SELECTION_PROTOCOL_SCHEMA_HASH = content_sha256(
    {
        "protocol": LEGACY_SELECTION_PROTOCOL_VERSION,
        "contracts": {
            "legacy-source-inventory/2.0": (
                "sha256:ecb02a261d523e640cda1d11118b988c1d5038e020429e959856eb08c65979e7"
            ),
            "legacy-source-rights-review/2.0": (
                "sha256:de8a98565ffb8b6d326cd716ff8245778a0ea11702838bf6dd5475b7fecef3f5"
            ),
            "legacy-source-selection/2.0": (
                "sha256:0c25bfa3c8732f85306b7077199e0f222aab65203c468a8ecb813f6092407775"
            ),
        },
    }
)


class CatalogLegacyRightsReviewResolver:
    def __init__(self, artifacts: CatalogArtifactService) -> None:
        self.artifacts = artifacts

    def resolve(self, pointer: LegacyRightsReviewPointerV2) -> LegacySourceRightsReviewV2:
        try:
            payload = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=MAX_RIGHTS_REVIEW_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_POINTER_STALE
            ) from exc
        try:
            value = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite JSON")),
            )
            if not isinstance(value, dict):
                raise ValueError("rights review must be an object")
            validate_contract("legacy-source-rights-review-v2", value)
            return LegacySourceRightsReviewV2.model_validate(value)
        except (UnicodeError, ValueError, json.JSONDecodeError, JsonSchemaValidationError) as exc:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_RIGHTS_INVALID
            ) from exc


class CatalogLegacyContentIntakeBoundary:
    def __init__(self, service: IntakeService) -> None:
        self.service = service

    def create(
        self,
        source_directory: Path,
        *,
        batch_name: str,
        received_by: str,
        purpose: str,
        source_owner_type: str,
        source_owner_reference: str,
        source_declarations: tuple[IntakeSourceDeclaration, ...],
    ) -> LegacyContentIntakeReceipt:
        batch = self.service.create(
            source_directory,
            batch_name=batch_name,
            received_by=received_by,
            purpose=purpose,
            source_owner_type=source_owner_type,
            source_owner_reference=source_owner_reference,
            source_declarations=source_declarations,
        )
        if (
            batch.state != "ANALYSIS_PENDING"
            or batch.source_manifest_artifact_id is None
            or batch.source_manifest_artifact_revision_id is None
            or batch.source_manifest_sha256 is None
        ):
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_OUTPUT_INVALID
            )
        return LegacyContentIntakeReceipt(
            intake_batch_id=batch.intake_batch_id,
            state=batch.state,
            source_fingerprint=batch.source_fingerprint,
            source_manifest_artifact_id=batch.source_manifest_artifact_id,
            source_manifest_artifact_revision_id=batch.source_manifest_artifact_revision_id,
            source_manifest_sha256=batch.source_manifest_sha256,
        )


class CatalogLegacySelectionArtifactBoundary:
    def __init__(self, artifacts: CatalogArtifactService, settings: CatalogSettings) -> None:
        self.artifacts = artifacts
        self.settings = settings

    def commit(
        self,
        selection: LegacySourceSelectionV2,
        intake: LegacyContentIntakeReceipt,
    ) -> LegacySelectionArtifactReceipt:
        payload = (
            json.dumps(
                selection.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        try:
            with tempfile.TemporaryDirectory(
                prefix="legacy-source-selection-", dir=self.settings.staging_root
            ) as directory:
                staging = Path(directory)
                os.chmod(staging, 0o700)
                target = staging / "legacy-source-selection.json"
                _write_exclusive_file(target, payload)
                artifact = self.artifacts.commit_file_set(
                    files={"legacy-source-selection.json": target},
                    primary_file="legacy-source-selection.json",
                    artifact_type="legacy-source-selection",
                    idempotency_key=f"legacy-source-selection:{selection.selection_sha256}",
                    request={
                        "schema_version": "legacy-source-selection-commit-request/1.0",
                        "selection_id": selection.selection_id,
                        "selection_sha256": selection.selection_sha256,
                        "inventory_id": selection.inventory_id,
                        "inventory_sha256": selection.inventory_sha256,
                    },
                    result={
                        "schema_version": "legacy-source-selection-commit-result/1.0",
                        "selection_id": selection.selection_id,
                        "selection_sha256": selection.selection_sha256,
                        "intake_batch_id": intake.intake_batch_id,
                        "source_manifest_artifact_id": intake.source_manifest_artifact_id,
                        "source_manifest_artifact_revision_id": (
                            intake.source_manifest_artifact_revision_id
                        ),
                    },
                    file_metadata={
                        "legacy-source-selection.json": {
                            "media_type": "application/json",
                            "schema_ref": (
                                "eom://schemas/legacy-knowledge/legacy-source-selection/2.0"
                            ),
                        }
                    },
                    manifest_version="legacy-source-selection-artifact/1.0",
                    protocol_version=LEGACY_SELECTION_PROTOCOL_VERSION,
                    protocol_schema_hash=LEGACY_SELECTION_PROTOCOL_SCHEMA_HASH,
                )
        except LegacySourceSelectionError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_OUTPUT_INVALID
            ) from exc
        return LegacySelectionArtifactReceipt(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            content_sha256=artifact.content_hash,
            manifest_sha256=artifact.manifest_hash,
        )


def _write_exclusive_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, _OPEN_WRITE_EXCLUSIVE, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short protected document write")
            view = view[written:]
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != len(payload)
        ):
            raise OSError("protected document metadata mismatch")
    finally:
        os.close(descriptor)


def _unique_json_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
