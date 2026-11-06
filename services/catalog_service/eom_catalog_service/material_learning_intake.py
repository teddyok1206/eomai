"""Accept a durable learning request; no conversion/model execution in HTTP threads."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts.material_learning import (
    PERMITTED_USES,
    MaterialArtifactMember,
    MaterialLearningRights,
)
from eom_catalog_contracts.material_learning_intake import (
    ControlMaterialLearningRunCommand,
    CreateMaterialLearningCommand,
    MaterialLearningAcceptance,
    MaterialLearningControlResult,
    MaterialLearningIntakeManifest,
    MaterialLearningRetryResult,
    RetryMaterialLearningRunCommand,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_workflow.material_learning_state import MaterialLearningState
from pydantic import BaseModel
from sqlalchemy import Engine, select

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import publish_material_metadata
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
)
from eom_catalog_service.material_learning_recovery import retry_material_learning_run
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.material_learning_store import (
    MaterialSubmissionPins,
    create_material_learning,
    material_submission_identity,
    transition_material_run,
)
from eom_catalog_service.settings import CatalogSettings


class MaterialLearningIntakeService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.sources = MaterialLearningSourceService(engine, self.settings)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def retry(self, command: RetryMaterialLearningRunCommand) -> MaterialLearningRetryResult:
        return retry_material_learning_run(self.sessions, command)

    def control(self, command: ControlMaterialLearningRunCommand) -> MaterialLearningControlResult:
        command = ControlMaterialLearningRunCommand.model_validate(command.model_dump(mode="json"))
        with self.sessions.begin() as session:
            authorize_material_learning(session, command.actor_id)
            run = session.scalar(
                select(MaterialLearningRunRecord)
                .where(
                    MaterialLearningRunRecord.run_id == command.run_id,
                    MaterialLearningRunRecord.created_by == command.actor_id,
                )
                .with_for_update()
            )
            revision = (
                session.get(LearningMaterialRevisionRecord, run.material_revision_id)
                if run
                else None
            )
            material = (
                session.get(LearningMaterialRecord, revision.material_id) if revision else None
            )
            if (
                run is None
                or revision is None
                or material is None
                or material.lifecycle_state != "ACTIVE"
                or material.current_revision_id != revision.material_revision_id
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
            already = (
                run.state == "PAUSED"
                if command.action == "PAUSE"
                else run.state in {"DISCOVERING", "PROCESSING"}
            )
            if not already:
                if run.updated_at != command.expected_updated_at:
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_STATE_STALE")
                if command.action == "PAUSE":
                    if run.state not in {"DISCOVERING", "PROCESSING", "WAITING_FOR_CAPACITY"}:
                        raise MaterialLearningSourceError("MATERIAL_LEARNING_CONTROL_PHASE_INVALID")
                    target = MaterialLearningState.PAUSED
                else:
                    if run.state != "PAUSED" or run.phase_before_wait not in {
                        "DISCOVERING",
                        "PROCESSING",
                    }:
                        raise MaterialLearningSourceError("MATERIAL_LEARNING_CONTROL_PHASE_INVALID")
                    target = MaterialLearningState(run.phase_before_wait)
                transition_material_run(session, run, target, now=datetime.now(UTC))
            result = MaterialLearningControlResult.model_validate(
                dict(
                    run_id=run.run_id,
                    state=run.state,
                    updated_at=run.updated_at,
                    replayed=already,
                )
            )
            authorize_material_learning(session, command.actor_id)
            return result

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
        return publish_material_metadata(
            self.artifacts,
            self.settings,
            model,
            member_path=member_path,
            schema_ref=schema_ref,
            idempotency_key=idempotency_key,
            artifact_type="material-learning-intake",
        )
