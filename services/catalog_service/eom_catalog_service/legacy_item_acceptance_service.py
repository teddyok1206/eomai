"""Commit and register one policy-decided legacy extraction acceptance."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    LegacyExtractionResultPointer,
    LegacyItemDecision,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionResult,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
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
    """Own the Artifact-before-registry boundary for acceptance documents."""

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


AUTOMATIC_ACCEPTANCE_ACTOR = "system.legacy-item-auto-acceptance"
MAX_EXTRACTION_RESULT_BYTES = 16 * 1024 * 1024


class AutomaticLegacyItemAcceptanceService:
    """Accept a fully canonical extraction without claiming that a human reviewed it."""

    def __init__(
        self,
        engine: Engine,
        *,
        acceptance: LegacyItemAcceptanceService,
        artifacts: CatalogArtifactService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = artifacts or CatalogArtifactService(engine)
        self.acceptance = acceptance

    def register_validated_result(
        self,
        pointer: LegacyExtractionResultPointer,
    ) -> LegacyItemAcceptanceRegistration:
        """Create one replay-stable ACCEPT decision covering every anchored content path."""

        try:
            raw = self.artifacts.read_member(
                artifact_id=pointer.artifact.artifact_id,
                revision_id=pointer.artifact.artifact_revision_id,
                member_path=pointer.artifact.member_path,
                sha256=pointer.artifact.sha256,
                media_type=pointer.artifact.media_type,
                schema_ref=pointer.artifact.schema_ref,
                max_bytes=MAX_EXTRACTION_RESULT_BYTES,
            )
            document = json.loads(raw, object_pairs_hook=self._unique_object)
            if not isinstance(document, dict):
                raise ValueError("extraction result is not an object")
            validate_contract("legacy-item-extraction-result", document)
            result = LegacyItemExtractionResult.model_validate(document)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            raise ValueError("automatic acceptance source is invalid") from exc
        if (
            result.extraction_result_id != pointer.extraction_result_id
            or result.result_sha256 != pointer.result_sha256
        ):
            raise ValueError("automatic acceptance source differs from its pinned result")
        with self.sessions() as session:
            revision = session.get(
                ArtifactRevisionRecord,
                pointer.artifact.artifact_revision_id,
            )
            if (
                revision is None
                or not revision.approved
                or revision.logical_artifact_id != pointer.artifact.artifact_id
                or revision.content_hash != pointer.artifact.sha256
            ):
                raise ValueError("automatic acceptance Artifact Revision is stale")
            reviewed_at = revision.created_at

        identity = content_sha256(
            {
                "protocol": "legacy-item-automatic-acceptance/1.0",
                "extraction_result": pointer.model_dump(mode="json"),
            }
        ).removeprefix("sha256:")
        values: dict[str, object] = {
            "schema_version": "legacy-item-extraction-acceptance/1.0",
            "acceptance_id": f"itemacceptance_{identity[:32]}",
            "extraction_result": pointer.model_dump(mode="json"),
            "state": "ACCEPTED",
            "item_decisions": tuple(
                LegacyItemDecision(
                    item_proposal_id=item.item_proposal_id,
                    item_number=item.item_number,
                    decision="ACCEPT",
                    accepted_content_paths=tuple(
                        mapping.content_path for mapping in item.content_anchor_map
                    ),
                    rejected_content_paths=(),
                    required_corrections=(),
                ).model_dump(mode="json")
                for item in result.items
            ),
            "coverage_state": "COMPLETE",
            "reviewed_at": reviewed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "reviewed_by": AUTOMATIC_ACCEPTANCE_ACTOR,
        }
        values["acceptance_sha256"] = content_sha256(values)
        automatic = LegacyItemExtractionAcceptance.model_validate(values)
        return self.acceptance.register(automatic)

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
