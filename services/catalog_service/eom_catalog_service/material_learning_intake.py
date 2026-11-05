"""Accept a durable learning request; no conversion/model execution in HTTP threads."""

from __future__ import annotations

import tempfile
from pathlib import Path

from eom_catalog_contracts.material_learning import (
    PERMITTED_USES,
    MaterialArtifactMember,
    MaterialLearningRights,
)
from eom_catalog_contracts.material_learning_intake import (
    CreateMaterialLearningCommand,
    MaterialLearningAcceptance,
    MaterialLearningIntakeManifest,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.database import build_session_factory
from pydantic import BaseModel
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.material_learning_store import (
    MaterialSubmissionPins,
    create_material_learning,
    material_submission_identity,
)
from eom_catalog_service.settings import CatalogSettings


class MaterialLearningIntakeService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.sources = MaterialLearningSourceService(engine, self.settings)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def create(self, command: CreateMaterialLearningCommand) -> MaterialLearningAcceptance:
        command = CreateMaterialLearningCommand.model_validate(command.model_dump(mode="json"))
        # Resolver checks original uploader, immutable bytes, permissions and lifecycle.
        for selection in command.sources:
            self.sources.resolve(selection.source_upload, operator_id=command.actor_id)
        identity = material_submission_identity(command.actor_id, command.idempotency_key)
        request_sha = content_sha256(command.model_dump(mode="json"))
        attestation = {
            "schema_version": "material-learning-rights/1.0",
            "material_id": identity.material_id,
            "material_revision_id": identity.material_revision_id,
            "attested_by": command.actor_id,
            # Each raw upload includes explicit consent. Reuse its committed time,
            # not a fresh clock value that would break the same command's replay.
            "attested_at": max(selection.source_upload.created_at for selection in command.sources)
            .isoformat()
            .replace("+00:00", "Z"),
            "basis": "UPLOADER_ATTESTED_INTERNAL_PROCESSING",
            "source_hashes": [
                selection.source_upload.original.sha256 for selection in command.sources
            ],
            "permitted_uses": list(PERMITTED_USES),
            "public_redistribution_permitted": False,
            "withdrawal_policy": "DENY_NEW_RESOLUTION_PRESERVE_PINNED_AUDIT",
        }
        rights = MaterialLearningRights.model_validate(
            {**attestation, "attestation_sha256": content_sha256(attestation)}
        )
        rights_member = self._publish_metadata(
            rights,
            member_path="rights/attestation.json",
            schema_ref="eom://schemas/material-learning/rights/1.0",
            idempotency_key="material-rights:" + identity.material_revision_id,
        )
        intake = MaterialLearningIntakeManifest(
            material_id=identity.material_id,
            material_revision_id=identity.material_revision_id,
            requested_by=command.actor_id,
            request_sha256=request_sha,
            upload=command.upload,
            sources=command.sources,
            rights_attestation=rights_member,
        )
        with self.sessions() as session:
            authorize_material_learning(session, command.actor_id)
        manifest = self._publish_metadata(
            intake,
            member_path="material/intake.json",
            schema_ref="eom://schemas/material-learning/intake/1.0",
            idempotency_key="material-intake:" + identity.material_revision_id,
        )
        with self.sessions.begin() as session:
            authorize_material_learning(session, command.actor_id)
            run, created = create_material_learning(
                session,
                MaterialSubmissionPins(
                    command.actor_id,
                    command.idempotency_key,
                    command.upload.title,
                    command.upload.material_kind,
                    request_sha,
                    manifest,
                ),
            )
            acceptance = MaterialLearningAcceptance(
                material_id=identity.material_id,
                material_revision_id=identity.material_revision_id,
                run_id=run.run_id,
                request_sha256=request_sha,
                replayed=not created,
            )
            authorize_material_learning(session, command.actor_id)
        return acceptance

    def _publish_metadata(
        self, model: BaseModel, *, member_path: str, schema_ref: str, idempotency_key: str
    ) -> MaterialArtifactMember:
        encoded = canonical_json_bytes(model.model_dump(mode="json"))
        digest = sha256_bytes(encoded)
        with tempfile.TemporaryDirectory(
            prefix="material-intake.", dir=self.settings.staging_root
        ) as temporary:
            path = Path(temporary) / "metadata.json"
            with path.open("xb") as stream:
                stream.write(encoded)
            artifact = self.artifacts.commit_file_set(
                files={member_path: path},
                primary_file=member_path,
                artifact_type="material-learning-intake",
                idempotency_key=idempotency_key,
                request={"schema_ref": schema_ref, "sha256": digest},
                result={"sha256": digest},
                file_metadata={
                    member_path: {"schema_ref": schema_ref, "media_type": "application/json"}
                },
                expected_file_sha256={member_path: digest},
            )
        return MaterialArtifactMember(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=member_path,
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=digest,
            bytes=len(encoded),
        )
