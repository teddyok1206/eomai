"""Commit and register one human-reviewed legacy extraction acceptance."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    LegacyItemExtractionAcceptance,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_origin_service import RightsPolicyResolver
from eom_catalog_service.legacy_assessment_registry import LegacyAssessmentRegistry
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True)
class LegacyItemAcceptanceRegistration:
    acceptance_id: str
    acceptance_sha256: str
    artifact_id: str
    artifact_revision_id: str
    created: bool


class LegacyItemAcceptanceService:
    """Own the Artifact-before-registry boundary for reviewed acceptance documents."""

    def __init__(
        self,
        engine: Engine,
        *,
        rights: RightsPolicyResolver,
        settings: CatalogSettings | None = None,
        artifacts: CatalogArtifactService | None = None,
        registry: LegacyAssessmentRegistry | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.artifacts = artifacts or CatalogArtifactService(engine, self.settings)
        self.registry = registry or LegacyAssessmentRegistry(
            engine,
            rights=rights,
            settings=self.settings,
            artifacts=self.artifacts,
        )

    def register(
        self,
        acceptance: LegacyItemExtractionAcceptance,
    ) -> LegacyItemAcceptanceRegistration:
        """Commit canonical bytes, then register the exact immutable pointer idempotently."""

        document = acceptance.model_dump(mode="json")
        validate_contract("legacy-item-extraction-acceptance", document)
        payload = canonical_json_bytes(document)
        artifact_payload_sha256 = sha256_bytes(payload)
        with tempfile.TemporaryDirectory(prefix="eom-legacy-item-acceptance-") as raw:
            source = Path(raw) / "acceptance.json"
            source.write_bytes(payload)
            artifact = self.artifacts.commit_file_set(
                files={"acceptance.json": source},
                primary_file="acceptance.json",
                artifact_type="legacy-item-extraction-acceptance",
                idempotency_key=f"legacy-item-acceptance:{acceptance.acceptance_id}",
                request={
                    "acceptance_id": acceptance.acceptance_id,
                    "acceptance_sha256": acceptance.acceptance_sha256,
                    "extraction_result_id": acceptance.extraction_result.extraction_result_id,
                    "result_sha256": acceptance.extraction_result.result_sha256,
                },
                result={
                    "acceptance_id": acceptance.acceptance_id,
                    "acceptance_sha256": acceptance.acceptance_sha256,
                    "state": acceptance.state,
                },
                file_metadata={
                    "acceptance.json": {
                        "schema_ref": (
                            "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"
                        ),
                        "media_type": "application/json",
                    }
                },
                expected_file_sha256={"acceptance.json": artifact_payload_sha256},
            )
        pointer = AssessmentArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path="acceptance.json",
            schema_ref=("eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"),
            media_type="application/json",
            sha256=artifact.content_hash,
        )
        registered = self.registry.register_acceptance(
            acceptance,
            acceptance_artifact=pointer,
        )
        return LegacyItemAcceptanceRegistration(
            acceptance_id=acceptance.acceptance_id,
            acceptance_sha256=acceptance.acceptance_sha256,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            created=registered.created,
        )
