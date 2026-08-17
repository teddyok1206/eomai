"""Resolve immutable intake evidence through validated artifact pointers."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_contracts import UncertaintiesDocument, validate_contract
from eom_content_intake import IntakeError, IntakeErrorCode
from eom_identifiers import sha256_file
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy.orm import Session

from eom_catalog_service.intake_files import load_strict_json
from eom_catalog_service.models import (
    ContentIntakeAnalysisRecord,
    ContentIntakeBatchRecord,
)


class IntakeEvidenceResolver:
    """Resolve pinned revisions; never substitute the current/latest revision."""

    def verify_source_manifest(
        self, session: Session, batch: ContentIntakeBatchRecord
    ) -> ArtifactRevisionRecord:
        revision_id = batch.source_manifest_artifact_revision_id
        expected_hash = batch.source_manifest_sha256
        if not revision_id or not expected_hash:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_HASH_MISMATCH,
                "source manifest pointer is incomplete",
            )
        revision = session.get(ArtifactRevisionRecord, revision_id)
        if (
            revision is None
            or revision.logical_artifact_id != batch.source_manifest_artifact_id
            or revision.content_hash != expected_hash
            or not revision.approved
            or revision.manifest.get("manifest_version") != "catalog-file-set/1.0"
            or revision.manifest.get("artifact_type") != "content-intake-source"
        ):
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_HASH_MISMATCH,
                "source manifest artifact pointer does not resolve",
            )
        return revision

    def load_uncertainties(
        self, session: Session, analysis: ContentIntakeAnalysisRecord
    ) -> UncertaintiesDocument:
        revision = session.get(ArtifactRevisionRecord, analysis.uncertainties_artifact_revision_id)
        if (
            revision is None
            or revision.logical_artifact_id != analysis.uncertainties_artifact_id
            or not revision.approved
            or revision.manifest.get("manifest_version") != "catalog-file-set/1.0"
            or revision.manifest.get("artifact_type") != "content-intake-analysis"
        ):
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_MISSING,
                "uncertainty artifact pointer does not resolve",
            )
        path = Path(revision.nas_path) / "uncertainties.json"
        if not path.is_file() or sha256_file(path) != analysis.uncertainties_sha256:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_HASH_MISMATCH,
                "uncertainty artifact hash mismatch",
            )
        raw = load_strict_json(path)
        validate_contract("uncertainties", raw)
        return UncertaintiesDocument.model_validate(raw)
