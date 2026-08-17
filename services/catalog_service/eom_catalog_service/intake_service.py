"""Application service for immutable manual content intake."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_catalog_contracts import (
    HumanDecision,
    IntakeDecisionValue,
    IntakeManifest,
    MappingProposal,
    UncertaintiesDocument,
    validate_contract,
)
from eom_content_intake import (
    IntakeError,
    IntakeErrorCode,
    IntakeState,
    new_analysis_id,
    new_decision_id,
    new_intake_batch_id,
    new_source_file_id,
)
from eom_identifiers import canonical_json_bytes, sha256_file
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.intake_evidence import IntakeEvidenceResolver
from eom_catalog_service.intake_files import (
    discover_source_files,
    load_strict_json,
    load_strict_yaml,
    source_fingerprint,
    validate_analysis_markdown,
)
from eom_catalog_service.intake_pointer_store import IntakePointerStore
from eom_catalog_service.intake_repository import (
    append_intake_event,
    list_intake_events,
    transition_intake,
)
from eom_catalog_service.models import (
    ContentIntakeAnalysisRecord,
    ContentIntakeBatchRecord,
    ContentIntakeDecisionRecord,
    ContentIntakeEventRecord,
    ContentIntakeSourceFileRecord,
)
from eom_catalog_service.settings import CatalogSettings


class IntakeService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.evidence = IntakeEvidenceResolver()
        self.pointers = IntakePointerStore(self.settings.intake_root)

    def create(
        self,
        source_directory: Path,
        *,
        batch_name: str,
        received_by: str,
        purpose: str = "PLACEHOLDER_PURPOSE",
        source_owner_type: str = "internal_team_member",
        source_owner_reference: str = "team_lead_placeholder",
    ) -> ContentIntakeBatchRecord:
        sources = discover_source_files(source_directory)
        hashes = [source.sha256 for source in sources]
        if len(hashes) != len(set(hashes)):
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_INVALID,
                "intake batch contains duplicate file content",
            )
        fingerprint = source_fingerprint(sources)
        with self.sessions() as session:
            existing = session.scalar(
                select(ContentIntakeBatchRecord).where(
                    ContentIntakeBatchRecord.source_fingerprint == fingerprint
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing

        batch_id = new_intake_batch_id()
        received_at = datetime.now(UTC)
        manifest = IntakeManifest.model_validate(
            {
                "schema_version": "1.0",
                "batch_id": batch_id,
                "batch_name": batch_name,
                "received_at": received_at,
                "received_by": received_by,
                "source_owner": {
                    "type": source_owner_type,
                    "reference": source_owner_reference,
                },
                "purpose": purpose,
                "files": [
                    {
                        "source_file_id": new_source_file_id(),
                        "relative_path": f"source/{source.normalized_relative_path}",
                        "original_filename": source.original_filename,
                        "media_type": source.media_type,
                        "size_bytes": source.size_bytes,
                        "sha256": source.sha256,
                        "declared_role": "REFERENCE",
                        "declared_description": "PLACEHOLDER_SOURCE_FILE",
                    }
                    for source in sources
                ],
            }
        )
        manifest_data = manifest.model_dump(mode="json")
        validate_contract("intake-manifest", manifest_data)

        with transaction(self.sessions) as session:
            batch = ContentIntakeBatchRecord(
                intake_batch_id=batch_id,
                batch_name=batch_name,
                state=IntakeState.RECEIVED.value,
                purpose=purpose,
                received_by=received_by,
                source_owner_type=source_owner_type,
                source_owner_reference=source_owner_reference,
                source_fingerprint=fingerprint,
                lock_version=1,
            )
            session.add(batch)
            session.flush()
            append_intake_event(
                session,
                batch,
                event_type="CONTENT_INTAKE_RECEIVED",
                prior_state=None,
                new_state=IntakeState.RECEIVED.value,
                actor_id=received_by,
                payload={"file_count": len(sources), "source_fingerprint": fingerprint},
            )

        staging = self.settings.staging_root / batch_id / "source"
        staging.mkdir(parents=True, mode=0o750, exist_ok=False)
        manifest_path = staging / "intake-manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest_data))
        manifest_path.chmod(0o640)
        files: dict[str, Path] = {"intake-manifest.json": manifest_path}
        files.update(
            {f"source/{source.normalized_relative_path}": source.source for source in sources}
        )
        artifact = self.artifacts.commit_file_set(
            files=files,
            primary_file="intake-manifest.json",
            artifact_type="content-intake-source",
            idempotency_key=f"content-intake-source:{fingerprint}",
            request={"batch_id": batch_id, "source_fingerprint": fingerprint},
            result={"batch_id": batch_id, "file_count": len(sources)},
        )
        with transaction(self.sessions) as session:
            batch = session.execute(
                select(ContentIntakeBatchRecord)
                .where(ContentIntakeBatchRecord.intake_batch_id == batch_id)
                .with_for_update()
            ).scalar_one()
            batch.source_manifest_artifact_id = artifact.artifact_id
            batch.source_manifest_artifact_revision_id = artifact.revision_id
            batch.source_manifest_sha256 = sha256_file(manifest_path)
            by_path = {source.normalized_relative_path: source for source in sources}
            for source_model in manifest.files:
                relative = source_model.relative_path.removeprefix("source/")
                discovered = by_path[relative]
                session.add(
                    ContentIntakeSourceFileRecord(
                        source_file_id=source_model.source_file_id,
                        intake_batch_id=batch_id,
                        original_filename=source_model.original_filename,
                        normalized_filename=discovered.normalized_filename,
                        relative_path=source_model.relative_path,
                        media_type=source_model.media_type,
                        size_bytes=source_model.size_bytes,
                        sha256=source_model.sha256,
                        artifact_id=artifact.artifact_id,
                        artifact_revision_id=artifact.revision_id,
                        declared_role=source_model.declared_role,
                        declared_description=source_model.declared_description,
                    )
                )
            transition_intake(
                session,
                batch,
                IntakeState.HASHED,
                event_type="CONTENT_INTAKE_HASHED",
                actor_id="catalog_service",
                payload={"artifact_id": artifact.artifact_id, "revision_id": artifact.revision_id},
            )
            transition_intake(
                session,
                batch,
                IntakeState.ANALYSIS_PENDING,
                event_type="CONTENT_INTAKE_ANALYSIS_PENDING",
                actor_id="catalog_service",
            )
            session.flush()
            session.expunge(batch)
        self.pointers.write("inbox", batch_id, artifact.artifact_id, artifact.revision_id)
        return batch

    def attach_analysis(
        self,
        batch_id: str,
        *,
        analysis_report: Path,
        mapping_proposal: Path,
        uncertainties: Path,
    ) -> ContentIntakeAnalysisRecord:
        validate_analysis_markdown(analysis_report)
        proposal_raw = load_strict_yaml(mapping_proposal)
        uncertainties_raw = load_strict_json(uncertainties)
        validate_contract("mapping-proposal", proposal_raw)
        validate_contract("uncertainties", uncertainties_raw)
        proposal = MappingProposal.model_validate(proposal_raw)
        uncertainty_document = UncertaintiesDocument.model_validate(uncertainties_raw)
        if (
            proposal.proposal.source_batch_id != batch_id
            or uncertainty_document.batch_id != batch_id
        ):
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                "analysis references a different intake batch",
            )
        proposal_hash = sha256_file(mapping_proposal)
        with self.sessions() as session:
            existing = session.scalar(
                select(ContentIntakeAnalysisRecord).where(
                    ContentIntakeAnalysisRecord.intake_batch_id == batch_id,
                    ContentIntakeAnalysisRecord.mapping_proposal_sha256 == proposal_hash,
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            batch = session.get(ContentIntakeBatchRecord, batch_id)
            if batch is None:
                raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_NOT_FOUND, "intake not found")
            if batch.state != IntakeState.ANALYSIS_PENDING.value:
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_IMMUTABLE,
                    "analysis can only be attached to a pending intake",
                )

        artifact = self.artifacts.commit_file_set(
            files={
                "analysis-report.md": analysis_report,
                "mapping-proposal.yaml": mapping_proposal,
                "uncertainties.json": uncertainties,
            },
            primary_file="mapping-proposal.yaml",
            artifact_type="content-intake-analysis",
            idempotency_key=f"content-intake-analysis:{batch_id}:{proposal_hash}",
            request={"batch_id": batch_id, "proposal_hash": proposal_hash},
            result={"batch_id": batch_id, "proposal_key": proposal.proposal.key},
        )
        with transaction(self.sessions) as session:
            batch = session.execute(
                select(ContentIntakeBatchRecord)
                .where(ContentIntakeBatchRecord.intake_batch_id == batch_id)
                .with_for_update()
            ).scalar_one()
            record = ContentIntakeAnalysisRecord(
                analysis_id=new_analysis_id(),
                intake_batch_id=batch_id,
                proposal_key=proposal.proposal.key,
                analysis_source_type=proposal.proposal.analysis_source_type,
                analysis_report_artifact_id=artifact.artifact_id,
                analysis_report_artifact_revision_id=artifact.revision_id,
                analysis_report_sha256=sha256_file(analysis_report),
                mapping_proposal_artifact_id=artifact.artifact_id,
                mapping_proposal_artifact_revision_id=artifact.revision_id,
                mapping_proposal_sha256=proposal_hash,
                uncertainties_artifact_id=artifact.artifact_id,
                uncertainties_artifact_revision_id=artifact.revision_id,
                uncertainties_sha256=sha256_file(uncertainties),
                created_by=proposal.proposal.created_by,
                immutable=True,
            )
            session.add(record)
            transition_intake(
                session,
                batch,
                IntakeState.ANALYSIS_ATTACHED,
                event_type="CONTENT_INTAKE_ANALYSIS_ATTACHED",
                actor_id=proposal.proposal.created_by,
                payload={"analysis_id": record.analysis_id, "proposal_key": record.proposal_key},
            )
            session.flush()
            session.expunge(record)
            return record

    def validate(self, batch_id: str) -> ContentIntakeBatchRecord:
        with transaction(self.sessions) as session:
            batch = session.execute(
                select(ContentIntakeBatchRecord)
                .where(ContentIntakeBatchRecord.intake_batch_id == batch_id)
                .with_for_update()
            ).scalar_one_or_none()
            if batch is None:
                raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_NOT_FOUND, "intake not found")
            if batch.state == IntakeState.NEEDS_DECISION.value:
                session.expunge(batch)
                return batch
            if batch.state != IntakeState.ANALYSIS_ATTACHED.value:
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_MISSING,
                    "validated intake requires attached analysis",
                )
            transition_intake(
                session,
                batch,
                IntakeState.VALIDATING,
                event_type="CONTENT_INTAKE_VALIDATING",
                actor_id="catalog_service",
            )
            self._verify_evidence(session, batch)
            transition_intake(
                session,
                batch,
                IntakeState.NEEDS_DECISION,
                event_type="CONTENT_INTAKE_NEEDS_DECISION",
                actor_id="catalog_service",
            )
            session.flush()
            session.expunge(batch)
            return batch

    def decide(
        self, batch_id: str, decision_file: Path, *, actor_id: str
    ) -> ContentIntakeBatchRecord:
        decision_raw = load_strict_json(decision_file)
        validate_contract("human-decision", decision_raw)
        decision = HumanDecision.model_validate(decision_raw)
        if decision.batch_id != batch_id or decision.decided_by != actor_id:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_INVALID, "decision identity does not match command"
            )
        if decision.decision == IntakeDecisionValue.PENDING:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_DECISION_REQUIRED, "pending is not a final decision"
            )
        decision_hash = sha256_file(decision_file)
        with self.sessions() as session:
            batch = session.get(ContentIntakeBatchRecord, batch_id)
            if batch is None:
                raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_NOT_FOUND, "intake not found")
            existing = session.scalar(
                select(ContentIntakeDecisionRecord).where(
                    ContentIntakeDecisionRecord.intake_batch_id == batch_id
                )
            )
            if existing is not None:
                if existing.decision_sha256 != decision_hash:
                    raise IntakeError(
                        IntakeErrorCode.CONTENT_INTAKE_IMMUTABLE,
                        "intake already has a different immutable decision",
                    )
                session.expunge(batch)
                return batch
            analysis = session.scalar(
                select(ContentIntakeAnalysisRecord).where(
                    ContentIntakeAnalysisRecord.intake_batch_id == batch_id
                )
            )
            if analysis is None or analysis.proposal_key != decision.proposal_key:
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                    "decision does not match the attached proposal",
                )
            analysis_id = analysis.analysis_id
            if batch.state != IntakeState.NEEDS_DECISION.value:
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_DECISION_REQUIRED,
                    "intake is not awaiting a decision",
                )
            if decision.decision in {
                IntakeDecisionValue.ACCEPT,
                IntakeDecisionValue.ACCEPT_WITH_CHANGES,
            }:
                if self._has_blocking_uncertainty(session, analysis):
                    raise IntakeError(
                        IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                        "blocking uncertainty prevents acceptance",
                    )
                if (
                    decision.decision == IntakeDecisionValue.ACCEPT_WITH_CHANGES
                    and decision.required_corrections
                ):
                    raise IntakeError(
                        IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                        "required corrections must be applied before acceptance",
                    )

        artifact = self.artifacts.commit_file_set(
            files={"human-decision.json": decision_file},
            primary_file="human-decision.json",
            artifact_type="content-intake-decision",
            idempotency_key=f"content-intake-decision:{batch_id}:{decision_hash}",
            request={"batch_id": batch_id, "decision_hash": decision_hash},
            result={"batch_id": batch_id, "decision": decision.decision},
        )
        with transaction(self.sessions) as session:
            batch = session.execute(
                select(ContentIntakeBatchRecord)
                .where(ContentIntakeBatchRecord.intake_batch_id == batch_id)
                .with_for_update()
            ).scalar_one()
            session.add(
                ContentIntakeDecisionRecord(
                    decision_id=new_decision_id(),
                    intake_batch_id=batch_id,
                    analysis_id=analysis_id,
                    decision=decision.decision,
                    decision_artifact_id=artifact.artifact_id,
                    decision_artifact_revision_id=artifact.revision_id,
                    decision_sha256=decision_hash,
                    decided_by=actor_id,
                    decided_at=decision.decided_at,
                    notes=decision.notes,
                    immutable=True,
                )
            )
            target = {
                IntakeDecisionValue.ACCEPT: IntakeState.ACCEPTED,
                IntakeDecisionValue.ACCEPT_WITH_CHANGES: IntakeState.ACCEPTED,
                IntakeDecisionValue.REJECT: IntakeState.REJECTED,
                IntakeDecisionValue.SUPERSEDE: IntakeState.SUPERSEDED,
            }[IntakeDecisionValue(decision.decision)]
            transition_intake(
                session,
                batch,
                target,
                event_type=f"CONTENT_INTAKE_{target.value}",
                actor_id=actor_id,
                payload={
                    "decision": decision.decision,
                    "decision_artifact_id": artifact.artifact_id,
                },
            )
            session.flush()
            state = batch.state
            session.expunge(batch)
        self.pointers.write(
            "accepted" if state == IntakeState.ACCEPTED.value else "rejected",
            batch_id,
            artifact.artifact_id,
            artifact.revision_id,
        )
        return batch

    def reject(self, batch_id: str, *, reason: str, actor_id: str) -> ContentIntakeBatchRecord:
        with self.sessions() as session:
            analysis = session.scalar(
                select(ContentIntakeAnalysisRecord).where(
                    ContentIntakeAnalysisRecord.intake_batch_id == batch_id
                )
            )
            if analysis is None:
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_MISSING,
                    "rejection requires an attached analysis",
                )
            proposal_key = analysis.proposal_key
        path = self.settings.staging_root / batch_id / "decision-reject.json"
        path.parent.mkdir(parents=True, mode=0o750, exist_ok=True)
        decision = HumanDecision(
            batch_id=batch_id,
            proposal_key=proposal_key,
            decision=IntakeDecisionValue.REJECT,
            decided_by=actor_id,
            decided_at=datetime.now(UTC),
            accepted_change_keys=(),
            rejected_change_keys=("ALL",),
            required_corrections=(),
            notes=reason,
        )
        path.write_bytes(canonical_json_bytes(decision.model_dump(mode="json")))
        path.chmod(0o640)
        return self.decide(batch_id, path, actor_id=actor_id)

    def inspect(self, batch_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            batch = session.get(ContentIntakeBatchRecord, batch_id)
            if batch is None:
                raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_NOT_FOUND, "intake not found")
            sources = list(
                session.scalars(
                    select(ContentIntakeSourceFileRecord)
                    .where(ContentIntakeSourceFileRecord.intake_batch_id == batch_id)
                    .order_by(ContentIntakeSourceFileRecord.relative_path)
                )
            )
            analysis = session.scalar(
                select(ContentIntakeAnalysisRecord).where(
                    ContentIntakeAnalysisRecord.intake_batch_id == batch_id
                )
            )
            decision = session.scalar(
                select(ContentIntakeDecisionRecord).where(
                    ContentIntakeDecisionRecord.intake_batch_id == batch_id
                )
            )
            events = list_intake_events(session, batch_id)
            return {
                "batch": self.batch_dict(batch),
                "source_files": [self.source_dict(source) for source in sources],
                "analysis": self.analysis_dict(analysis) if analysis else None,
                "decision": self.decision_dict(decision) if decision else None,
                "events": [self.event_dict(event) for event in events],
            }

    def list_batches(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.sessions() as session:
            batches = list(
                session.scalars(
                    select(ContentIntakeBatchRecord)
                    .order_by(
                        ContentIntakeBatchRecord.created_at.desc(),
                        ContentIntakeBatchRecord.intake_batch_id.desc(),
                    )
                    .limit(limit)
                )
            )
            return [self.batch_dict(batch) for batch in batches]

    def events(self, batch_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            if session.get(ContentIntakeBatchRecord, batch_id) is None:
                raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_NOT_FOUND, "intake not found")
            return [self.event_dict(event) for event in list_intake_events(session, batch_id)]

    def _verify_evidence(self, session: Any, batch: ContentIntakeBatchRecord) -> None:
        if not batch.source_manifest_artifact_revision_id or not batch.source_manifest_sha256:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_HASH_MISMATCH,
                "source manifest pointer is incomplete",
            )
        self.evidence.verify_source_manifest(session, batch)
        analysis = session.scalar(
            select(ContentIntakeAnalysisRecord).where(
                ContentIntakeAnalysisRecord.intake_batch_id == batch.intake_batch_id
            )
        )
        if analysis is None or not analysis.immutable:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_MISSING,
                "immutable analysis evidence is required",
            )

    def _has_blocking_uncertainty(
        self, session: Any, analysis: ContentIntakeAnalysisRecord
    ) -> bool:
        document = self.evidence.load_uncertainties(session, analysis)
        return any(item.blocking for item in document.items)

    @staticmethod
    def batch_dict(batch: ContentIntakeBatchRecord) -> dict[str, Any]:
        return {
            "intake_batch_id": batch.intake_batch_id,
            "batch_name": batch.batch_name,
            "state": batch.state,
            "purpose": batch.purpose,
            "received_by": batch.received_by,
            "source_owner_type": batch.source_owner_type,
            "source_owner_reference": batch.source_owner_reference,
            "source_manifest_artifact_id": batch.source_manifest_artifact_id,
            "source_manifest_artifact_revision_id": batch.source_manifest_artifact_revision_id,
            "source_manifest_sha256": batch.source_manifest_sha256,
            "source_fingerprint": batch.source_fingerprint,
            "lock_version": batch.lock_version,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
            "accepted_at": batch.accepted_at,
            "rejected_at": batch.rejected_at,
        }

    @staticmethod
    def source_dict(source: ContentIntakeSourceFileRecord) -> dict[str, Any]:
        return {
            "source_file_id": source.source_file_id,
            "relative_path": source.relative_path,
            "original_filename": source.original_filename,
            "normalized_filename": source.normalized_filename,
            "media_type": source.media_type,
            "size_bytes": source.size_bytes,
            "sha256": source.sha256,
            "artifact_id": source.artifact_id,
            "artifact_revision_id": source.artifact_revision_id,
            "declared_role": source.declared_role,
        }

    @staticmethod
    def analysis_dict(analysis: ContentIntakeAnalysisRecord) -> dict[str, Any]:
        return {
            "analysis_id": analysis.analysis_id,
            "proposal_key": analysis.proposal_key,
            "analysis_source_type": analysis.analysis_source_type,
            "analysis_report_sha256": analysis.analysis_report_sha256,
            "mapping_proposal_sha256": analysis.mapping_proposal_sha256,
            "uncertainties_sha256": analysis.uncertainties_sha256,
            "created_by": analysis.created_by,
            "created_at": analysis.created_at,
            "immutable": analysis.immutable,
        }

    @staticmethod
    def decision_dict(decision: ContentIntakeDecisionRecord) -> dict[str, Any]:
        return {
            "decision_id": decision.decision_id,
            "decision": decision.decision,
            "decision_sha256": decision.decision_sha256,
            "decided_by": decision.decided_by,
            "decided_at": decision.decided_at,
            "immutable": decision.immutable,
        }

    @staticmethod
    def event_dict(event: ContentIntakeEventRecord) -> dict[str, Any]:
        return {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "prior_state": event.prior_state,
            "new_state": event.new_state,
            "actor_id": event.actor_id,
            "payload": event.payload,
            "created_at": event.created_at,
        }
