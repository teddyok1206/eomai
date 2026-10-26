"""Publish an exact, textbook-only Graph bundle for a scientific review."""

from __future__ import annotations

import json
import re

from eom_catalog_contracts import CreateItemProductionEvidenceCommand, ReviewTextbookEvidence
from eom_catalog_contracts.knowledge import (
    EducationalRetrievalRequirement,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
)


class ReviewTextbookEvidenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReviewTextbookEvidenceService:
    """One Catalog-owned publication boundary reused by Item and material review."""

    def __init__(
        self,
        *,
        retrieval: KnowledgeRetrievalApplicationService,
        artifacts: CatalogArtifactService,
    ) -> None:
        self.retrieval = retrieval
        self.artifacts = artifacts

    def create(
        self,
        *,
        review_input_sha256: str,
        command: CreateItemProductionEvidenceCommand,
    ) -> ReviewTextbookEvidence:
        if (
            re.fullmatch(r"sha256:[0-9a-f]{64}", review_input_sha256) is None
            or not isinstance(command.requirement, EducationalRetrievalRequirement)
            or command.requirement.query_kind != "ITEM_PREPARATION"
            or command.requirement.source_classes != ("TEXTBOOK",)
            or command.solution_evidence_requirement != "NONE"
        ):
            raise ReviewTextbookEvidenceError(
                "REVIEW_TEXTBOOK_SCOPE_INVALID",
                "review evidence must use an explicit textbook-only educational query",
            )
        publication = self.retrieval.create_item_production(command)
        if not isinstance(
            publication,
            EvidenceBundlePublicationResultV3 | EvidenceBundlePublicationResultV4,
        ) or publication.schema_version not in {
            "evidence-bundle-publication-result/3.0",
            "evidence-bundle-publication-result/4.0",
        }:
            raise ReviewTextbookEvidenceError(
                "REVIEW_TEXTBOOK_SOURCE_MISSING",
                "published review evidence has no approved textbook document source",
            )
        if (
            publication.access_policy_revision_id != command.access_policy_revision_id
            or publication.access_policy_sha256 != command.access_policy_sha256
            or publication.requester_permissions_sha256
            != content_sha256({"permission_keys": list(command.requester_permission_keys)})
        ):
            raise ReviewTextbookEvidenceError(
                "REVIEW_TEXTBOOK_PUBLICATION_MISMATCH",
                "textbook publication differs from the reviewer's released authority",
            )
        pointer = publication.manifest_artifact
        try:
            payload = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=8 * 1024 * 1024,
            )
        except (ValueError, OSError) as exc:
            raise ReviewTextbookEvidenceError(
                "REVIEW_TEXTBOOK_MATERIAL_INVALID",
                "pinned textbook manifest is missing, stale or hash-invalid",
            ) from exc
        try:
            value = json.loads(payload)
            schema_key = (
                "evidence-bundle-manifest-v4"
                if isinstance(publication, EvidenceBundlePublicationResultV4)
                else "evidence-bundle-manifest-v3"
            )
            validate_contract(schema_key, value)
            manifest = (
                EvidenceBundleManifestV4.model_validate(value)
                if schema_key.endswith("v4")
                else EvidenceBundleManifestV3.model_validate(value)
            )
        except (ValueError, TypeError, ValidationError, JsonSchemaValidationError) as exc:
            raise ReviewTextbookEvidenceError(
                "REVIEW_TEXTBOOK_MANIFEST_INVALID",
                "published textbook evidence manifest is invalid",
            ) from exc
        textbook_ids = tuple(
            sorted(
                entry.evidence_id
                for entry in manifest.entries
                if entry.source.source_class == "TEXTBOOK"
            )
        )
        if not textbook_ids:
            raise ReviewTextbookEvidenceError(
                "REVIEW_TEXTBOOK_SOURCE_MISSING",
                "published review bundle has no approved textbook entry",
            )
        document: dict[str, object] = {
            "schema_version": "review-textbook-evidence/1.0",
            "review_input_sha256": review_input_sha256,
            "requirement": command.requirement.model_dump(mode="json"),
            "publication": publication.model_dump(mode="json"),
            "textbook_evidence_ids": list(textbook_ids),
        }
        document["binding_sha256"] = content_sha256(document)
        try:
            validate_contract("review-textbook-evidence", document)
            binding = ReviewTextbookEvidence.model_validate(document)
            binding.verify_manifest(manifest)
        except (ValueError, ValidationError, JsonSchemaValidationError) as exc:
            raise ReviewTextbookEvidenceError(
                "REVIEW_TEXTBOOK_MANIFEST_INVALID",
                "textbook evidence differs from its pinned publication",
            ) from exc
        return binding
