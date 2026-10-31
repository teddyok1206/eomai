"""Register archive Items with source lineage and an immutable solution/notes pointer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.assessment_item import (
    ASSESSMENT_ITEM_CONTENT_FILE_NAME,
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
)
from eom_catalog_contracts.creative_learning_cohort import CreativeCohortTarget
from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.creative_source_lineage import (
    CREATIVE_SOURCE_LINEAGE_SCHEMA_REF,
    CreativeSourceLineage,
    creative_registration_key,
)
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_contracts.external_item_preview import EXTERNAL_ITEM_PREVIEW_PDF_SCHEMA_REF
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_identity_service.repository import effective_permissions
from eom_item_registry import ComponentPointer, RegistrationRequest
from eom_operator_identity import PermissionKey
from eom_orchestrator.creative_source_visual_publication import publish_creative_source_visuals
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_workflow.creative_learning_profile import creative_learning_profile_for_protocol
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.creative_learning_proposal import (
    ResolvedCreativeLearningProposal,
    resolve_completed_creative_learning_proposal,
)
from eom_catalog_service.creative_registered_report import (
    RegisteredCreativeReport,
    load_registered_creative_report,
)
from eom_catalog_service.creative_source_content import (
    CREATIVE_CONTENT_UNAVAILABLE_CODE,
    CreativeSourceContent,
    materialize_creative_source_content,
    materialize_creative_source_content_v2,
)
from eom_catalog_service.external_creative_learning_source import (
    CatalogExternalItemLearningSourceAuthorizer,
)
from eom_catalog_service.external_item_models import ExternalItemSourceRecord
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
)
from eom_catalog_service.models import (
    ContentPackRecord,
    ContentPackReleaseRecord,
    ItemComponentRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.staging import stage_registry_item_content

CREATIVE_PACK_KEY = "external-creative-item"
CREATIVE_ITEM_TYPE = "external-creative-multiple-choice"
CREATIVE_METADATA_SCHEMA = "eom://metadata/external-creative-item@1.0"
CREATIVE_APPROVAL_BASIS = "SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION"


class CreativeItemRegistrationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CreativeItemContentUnavailable(CreativeItemRegistrationError):
    """Exact source/report pins for scheduling only, never registration authority."""

    def __init__(self, resolved: ResolvedCreativeLearningProposal) -> None:
        result = resolved.role.output.learning_result
        if result.proposal is not None or result.status != "NEEDS_DECISION":
            raise ValueError("CREATIVE_CONTENT_UNAVAILABLE_PROOF_INVALID")
        source = resolved.work.source
        self.target = CreativeCohortTarget.model_validate(
            dict(
                source_id=source.source_id,
                source_revision_id=source.source_revision_id,
                external_number=source.external_number,
                observation_sha256=source.observation_sha256,
                selected_edition=source.selected_edition,
            )
        )
        self.selection = resolved.selection
        self.report = resolved.pointer
        super().__init__(CREATIVE_CONTENT_UNAVAILABLE_CODE)


@dataclass(frozen=True, slots=True)
class RegisteredCreativeItem:
    item_id: str
    item_revision_id: str
    source_id: str
    source_revision_id: str
    content_sha256: str
    lineage: CreativeSourceLineage
    lineage_artifact: PublishedControlFileSet | None
    created: bool


def prepare_creative_registration_pack(
    engine: Engine,
    *,
    settings: CatalogSettings,
    pack_directory: Path,
    selection: ExternalItemLearningRoleSelection,
) -> str:
    """Release archive registration rules under the admitted task's current owner."""
    sessions = build_session_factory(engine)
    artifacts = CatalogArtifactService(engine, settings)
    authorizer = CatalogExternalItemLearningSourceAuthorizer(
        ExternalItemPreviewProjectionService(engine, settings=settings)
    )

    def authorize() -> str:
        with sessions() as session:
            resolved = resolve_completed_creative_learning_proposal(session, artifacts, selection)
            authorizer.reauthorize(
                session, operator_id=resolved.operator_id, source=resolved.work.source
            )
            if not {
                PermissionKey.CONTENT_PACK_RELEASE,
                PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT,
            }.issubset(effective_permissions(session, resolved.operator_id)):
                raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_PERMISSION_DENIED")
            return resolved.operator_id

    operator_id = authorize()
    packs = ContentPackService(engine, settings)
    release = packs.import_source(pack_directory)
    if authorize() != operator_id:
        raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_OWNER_MISMATCH")
    return packs.release(
        release.content_pack_release_id, actor_id=operator_id
    ).content_pack_release_id


def lock_creative_registration(session: Session, source_id: str) -> ItemRevisionRecord | None:
    """Hold the existing business-key fence through the caller's root transaction."""
    if not session.in_transaction():
        raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_TRANSACTION_REQUIRED")
    key = creative_registration_key(source_id)
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
    return session.scalar(
        select(ItemRevisionRecord)
        .where(ItemRevisionRecord.registration_key == key)
        .execution_options(populate_existing=True)
    )


class CreativeItemRegistrationService:
    """The source lock serializes materialization/registration, never a model run."""

    def __init__(
        self,
        engine: Engine,
        *,
        content_pack_release_id: str,
        publisher: ControlFileSetPublisher,
        source_commit: str,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings or CatalogSettings.from_environment()
        self.pack_release_id = content_pack_release_id
        self.publisher, self.source_commit = publisher, source_commit
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.registry = RegistryService(engine, self.settings)
        self.source = CatalogExternalItemLearningSourceAuthorizer(
            ExternalItemPreviewProjectionService(engine, settings=self.settings)
        )

    def find_registered_source(
        self, target: CreativeCohortTarget, *, requested_by_operator_id: str
    ) -> RegisteredCreativeItem | None:
        """Indexed exact source reuse; it neither changes a Workflow nor picks latest."""
        target = CreativeCohortTarget.model_validate(target.model_dump(mode="json"))
        with self.sessions() as session:
            revision = session.scalar(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.registration_key
                    == creative_registration_key(target.source_id)
                )
            )
            if revision is None:
                return None
            report = load_registered_creative_report(session, self.artifacts, revision)
            source = report.proposal.work.source
            if (
                source.source_id != target.source_id
                or source.source_revision_id != target.source_revision_id
                or source.observation_sha256 != target.observation_sha256
                or source.external_number != target.external_number
                or source.selected_edition != target.selected_edition
            ):
                raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_REPLAY_CONFLICT")
            self._authorize(session, report.proposal, requested_by_operator_id)
            self._verify_existing(session, revision, report.lineage, report=report)
            return RegisteredCreativeItem(
                revision.item_id,
                revision.item_revision_id,
                source.source_id,
                source.source_revision_id,
                report.lineage.registered_content_sha256,
                report.lineage,
                None,
                False,
            )

    def register_completed(
        self, selection: ExternalItemLearningRoleSelection, *, requested_by_operator_id: str
    ) -> RegisteredCreativeItem:
        # Source crop rendering is outside the registration transaction. The
        # final mutation re-resolves identical immutable work and current access.
        # An already registered source uses its stored derivation, not a new
        # runtime's source_commit or a newly generated image pointer.
        with self.sessions() as preflight:
            prepared = resolve_completed_creative_learning_proposal(
                preflight, self.artifacts, selection
            )
            self._authorize(preflight, prepared, requested_by_operator_id)
            present = preflight.scalar(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.registration_key
                    == creative_registration_key(prepared.work.source.source_id)
                )
            )
            already_registered = present is not None
        if not already_registered and prepared.role.output.learning_result.proposal is None:
            raise CreativeItemContentUnavailable(prepared)
        prepared_content = (
            self._prepare_successor_content(prepared)
            if isinstance(prepared.role.output.learning_result, ExternalItemLearningResultV2)
            and not already_registered
            else None
        )
        with self.sessions.begin() as guard:
            resolved = resolve_completed_creative_learning_proposal(
                guard, self.artifacts, selection
            )
            if (
                resolved.pointer != prepared.pointer
                or resolved.work != prepared.work
                or resolved.role.output.learning_result.result_sha256
                != prepared.role.output.learning_result.result_sha256
            ):
                raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_INPUT_CHANGED")
            source = resolved.work.source
            existing = lock_creative_registration(guard, source.source_id)
            current = guard.scalar(
                select(ExternalItemSourceRecord)
                .where(ExternalItemSourceRecord.source_id == source.source_id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            if current is None or current.current_revision_id != source.source_revision_id:
                raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_SOURCE_STALE")
            self._authorize(guard, resolved, requested_by_operator_id)
            key = creative_registration_key(source.source_id)
            if existing is not None:
                stored = load_registered_creative_report(guard, self.artifacts, existing)
                lineage = stored.lineage
                if (
                    lineage.selection != resolved.selection
                    or lineage.role_result != resolved.pointer
                    or lineage.result_sha256 != resolved.role.output.learning_result.result_sha256
                    or lineage.source_id != source.source_id
                    or lineage.source_revision_id != source.source_revision_id
                ):
                    raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_REPLAY_CONFLICT")
                self._verify_existing(guard, existing, lineage, report=stored)
                return RegisteredCreativeItem(
                    existing.item_id,
                    existing.item_revision_id,
                    source.source_id,
                    source.source_revision_id,
                    lineage.registered_content_sha256,
                    lineage,
                    None,
                    False,
                )

            result = resolved.role.output.learning_result
            if isinstance(result, ExternalItemLearningResultV2):
                if prepared_content is None:
                    raise CreativeItemRegistrationError(
                        "CREATIVE_REGISTRATION_PREPARATION_REQUIRED"
                    )
                content = prepared_content
            else:
                content = materialize_creative_source_content(result)
            lineage = self._lineage(resolved, content)

            staged, staged_hash = stage_registry_item_content(
                self.settings, content.content.model_dump(mode="json")
            )
            if staged_hash != content.registered_content_sha256:
                raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_CONTENT_MISMATCH")
            artifact = self.artifacts.commit_file_set(
                files={ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged},
                primary_file=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
                artifact_type="assessment-item-content",
                idempotency_key="creative-content:" + lineage.lineage_sha256[7:],
                request={"source_id": source.source_id, "lineage_sha256": lineage.lineage_sha256},
                result={"content_sha256": content.registered_content_sha256},
                file_metadata={
                    ASSESSMENT_ITEM_CONTENT_FILE_NAME: {
                        "schema_ref": ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
                        "media_type": "application/json",
                    }
                },
                expected_file_sha256={ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged_hash},
            )
            published = self._publish_lineage(lineage)
            self.source.reauthorize(guard, operator_id=resolved.operator_id, source=source)
            registered = self.registry.register(
                RegistrationRequest(
                    mode="CREATE_ITEM",
                    registration_key=key,
                    content_pack_release_id=self.pack_release_id,
                    workflow_id=selection.workflow_id,
                    workflow_definition_key="external-item-learning",
                    workflow_definition_version=creative_learning_profile_for_protocol(
                        resolved.role.protocol_version
                    ).definition_version,
                    source_workflow_step_run_id=selection.step_run_id,
                    # Unaccepted raw archive Intake rows are not fabricated approvals.
                    source_intake_batch_ids=(),
                    item_type_key=CREATIVE_ITEM_TYPE,
                    metadata_schema_ref=CREATIVE_METADATA_SCHEMA,
                    metadata={
                        "item_type_key": CREATIVE_ITEM_TYPE,
                        "source_kind": "CREATIVE",
                        "source_id": source.source_id,
                        "source_revision_id": source.source_revision_id,
                        "import_id": source.import_id,
                        "external_number": source.external_number,
                        "origin_kind": source.origin_kind,
                        "lineage_id": lineage.lineage_id,
                        "lineage_sha256": lineage.lineage_sha256,
                        "approval_basis": CREATIVE_APPROVAL_BASIS,
                    },
                    components=(
                        ComponentPointer(
                            component_type="ITEM_CONTENT",
                            ordinal=0,
                            schema_ref=ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
                            media_type="application/json",
                            artifact_id=artifact.artifact_id,
                            artifact_revision_id=artifact.revision_id,
                            sha256=artifact.content_hash,
                            logical_name=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
                        ),
                        ComponentPointer(
                            component_type="SOURCE_REFERENCE",
                            ordinal=0,
                            schema_ref=CREATIVE_SOURCE_LINEAGE_SCHEMA_REF,
                            media_type="application/json",
                            artifact_id=published.artifact_id,
                            artifact_revision_id=published.artifact_revision_id,
                            sha256=published.primary_sha256,
                            logical_name="lineage.json",
                        ),
                        ComponentPointer(
                            component_type="REVIEW_REPORT",
                            ordinal=0,
                            schema_ref=resolved.pointer.schema_ref,
                            media_type="application/json",
                            artifact_id=resolved.pointer.artifact_id,
                            artifact_revision_id=resolved.pointer.artifact_revision_id,
                            sha256=resolved.pointer.sha256,
                            logical_name="result.json",
                            metadata={
                                "report_kind": (
                                    "CREATIVE_SOURCE_SOLUTION_AND_WARNINGS_V2"
                                    if isinstance(result, ExternalItemLearningResultV2)
                                    else "CREATIVE_SOURCE_SOLUTION_AND_WARNINGS_V1"
                                )
                            },
                        ),
                    ),
                    created_by=resolved.operator_id,
                )
            )
            self._verify_existing(guard, registered, lineage)
            return RegisteredCreativeItem(
                registered.item_id,
                registered.item_revision_id,
                source.source_id,
                source.source_revision_id,
                content.registered_content_sha256,
                lineage,
                published,
                True,
            )

    def _authorize(
        self, session: Session, resolved: ResolvedCreativeLearningProposal, operator_id: str
    ) -> None:
        if resolved.operator_id != operator_id:
            raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_OWNER_MISMATCH")
        self.source.reauthorize(session, operator_id=operator_id, source=resolved.work.source)
        if PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT not in effective_permissions(
            session, operator_id
        ):
            raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_PERMISSION_DENIED")
        self._require_pack(session)

    def _prepare_successor_content(
        self, resolved: ResolvedCreativeLearningProposal
    ) -> CreativeSourceContent:
        result = resolved.role.output.learning_result
        assert isinstance(result, ExternalItemLearningResultV2)
        if result.proposal is None:
            raise CreativeItemRegistrationError(CREATIVE_CONTENT_UNAVAILABLE_CODE)
        if not any(isinstance(block, SourceImageBlock) for block in result.proposal.content.body):
            return materialize_creative_source_content_v2(result, resolved_images={})
        source = resolved.work.source

        def authorize_source() -> None:
            with self.sessions() as session:
                self._authorize(session, resolved, resolved.operator_id)

        pdf = self.artifacts.read_member(
            artifact_id=source.preview_artifact_id,
            revision_id=source.preview_artifact_revision_id,
            member_path=source.preview_manifest.pdf_member_path,
            sha256=source.preview_manifest.pdf_sha256,
            schema_ref=EXTERNAL_ITEM_PREVIEW_PDF_SCHEMA_REF,
            media_type="application/pdf",
            max_bytes=256 * 1024 * 1024,
        )
        with TemporaryDirectory(
            prefix="creative-source-visual-", dir=self.publisher.settings.staging_root
        ) as raw:
            visuals = publish_creative_source_visuals(
                self.publisher,
                work=resolved.work,
                result=result,
                role_result=resolved.pointer,
                pdf_bytes=pdf,
                workspace=Path(raw) / "crops",
                source_commit=self.source_commit,
                authorize_source=authorize_source,
            )
            if visuals is None:
                raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_VISUALS_MISSING")
            return materialize_creative_source_content_v2(result, resolved_images=visuals.images)

    def _require_pack(self, session: Session) -> None:
        release = session.get(ContentPackReleaseRecord, self.pack_release_id)
        logical = session.get(ContentPackRecord, release.content_pack_id) if release else None
        if (
            release is None
            or release.state != "RELEASED"
            or logical is None
            or logical.pack_key != CREATIVE_PACK_KEY
        ):
            raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_PACK_UNAVAILABLE")

    @staticmethod
    def _lineage(
        resolved: ResolvedCreativeLearningProposal, content: CreativeSourceContent
    ) -> CreativeSourceLineage:
        source, result = resolved.work.source, resolved.role.output.learning_result
        identity = content_sha256(
            {
                "source_revision_id": source.source_revision_id,
                "result_sha256": result.result_sha256,
                "registered_content_sha256": content.registered_content_sha256,
            }
        )[7:39]
        value = {
            "schema_version": "creative-source-lineage/1.0",
            "lineage_id": "extlineage_" + identity,
            "source_id": source.source_id,
            "source_revision_id": source.source_revision_id,
            "import_id": source.import_id,
            "external_number": source.external_number,
            "origin_kind": source.origin_kind,
            "source_input_sha256": source.input_sha256,
            "observation_sha256": source.observation_sha256,
            "selection": resolved.selection.model_dump(mode="json"),
            "role_result": resolved.pointer.model_dump(mode="json"),
            "result_id": result.result_id,
            "result_sha256": result.result_sha256,
            "proposed_content_sha256": content.proposed_content_sha256,
            "registered_content_sha256": content.registered_content_sha256,
            "source_answer_mode": content.source_answer_mode,
            "normalization_actions": content.normalization_actions,
            "warning_codes": content.warning_codes,
            "registration_policy": "PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1",
            "requested_by_operator_id": resolved.operator_id,
            "created_at": resolved.role.completed_at.isoformat().replace("+00:00", "Z"),
        }
        return CreativeSourceLineage.model_validate(
            {**value, "lineage_sha256": content_sha256(value)}
        )

    def _publish_lineage(self, lineage: CreativeSourceLineage) -> PublishedControlFileSet:
        payload = canonical_json_bytes(lineage.model_dump(mode="json"))
        with TemporaryDirectory(
            prefix="creative-lineage-", dir=self.publisher.settings.staging_root
        ) as raw:
            path = Path(raw) / "lineage.json"
            path.write_bytes(payload)
            path.chmod(0o400)
            return self.publisher.publish(
                members=(
                    ControlFileSetMember(
                        "lineage.json",
                        path,
                        sha256_bytes(payload),
                        len(payload),
                        CREATIVE_SOURCE_LINEAGE_SCHEMA_REF,
                        "application/json",
                    ),
                ),
                primary_file="lineage.json",
                artifact_type="control_creative_source_lineage",
                manifest_version=lineage.schema_version,
                idempotency_key="creative-lineage:" + lineage.lineage_sha256[7:],
                source_commit=self.source_commit,
                created_at=lineage.created_at,
            )

    def _verify_existing(
        self,
        session: Session,
        revision: ItemRevisionRecord,
        lineage: CreativeSourceLineage,
        *,
        report: RegisteredCreativeReport | None = None,
    ) -> None:
        metadata = revision.metadata_json
        components = tuple(
            session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == revision.item_revision_id
                )
            )
        )
        by_kind = {(row.component_type, row.ordinal): row for row in components}
        content = by_kind.get(("ITEM_CONTENT", 0))
        item = session.get(ItemRecord, revision.item_id, populate_existing=True)
        if (
            metadata.get("source_id") != lineage.source_id
            or item is None
            or item.lifecycle_state != "ACTIVE"
            or item.current_revision_id != revision.item_revision_id
            or metadata.get("source_revision_id") != lineage.source_revision_id
            or metadata.get("lineage_sha256") != lineage.lineage_sha256
            or revision.workflow_id != lineage.selection.workflow_id
            or revision.source_workflow_step_run_id != lineage.selection.step_run_id
            or revision.revision_state != "APPROVED"
            or content is None
            or content.sha256 != lineage.registered_content_sha256
            or len(by_kind) != len(components)
            or len(components) != 3
            or ("SOURCE_REFERENCE", 0) not in by_kind
            or ("REVIEW_REPORT", 0) not in by_kind
        ):
            raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_REPLAY_CONFLICT")
        stored = report or load_registered_creative_report(session, self.artifacts, revision)
        if stored.lineage != lineage:
            raise CreativeItemRegistrationError("CREATIVE_REGISTRATION_REPLAY_CONFLICT")
        self.artifacts.read_member(
            artifact_id=content.artifact_id,
            revision_id=content.artifact_revision_id,
            member_path=content.logical_name,
            sha256=content.sha256,
            schema_ref=content.schema_ref,
            media_type=content.media_type,
            max_bytes=256000,
        )
