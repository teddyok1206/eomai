"""Source-bound uploaded questions registered by the existing Item Registry."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from eom_catalog_contracts.assessment_item import (
    ASSESSMENT_ITEM_CONTENT_FILE_NAME,
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
    ASSESSMENT_ITEM_CONTENT_V1_1_SCHEMA_REF,
    AssessmentItemContentV1_1,
)
from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.material_item_lineage import (
    MATERIAL_ITEM_LINEAGE_REF,
    MATERIAL_ITEM_LINEAGE_V2_REF,
    MATERIAL_ITEM_LINEAGE_V3_REF,
    MATERIAL_ITEM_LINEAGE_V4_REF,
    MATERIAL_ITEM_PACK,
    MATERIAL_ITEM_TYPE,
    MaterialItemLineage,
    MaterialItemLineageFamily,
    MaterialItemLineageV2,
    MaterialItemLineageV3,
    MaterialItemLineageV4,
    material_item_registration_key,
    parse_material_item_lineage,
)
from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialExtractionResult,
    MaterialExtractionResultV2,
    MaterialExtractionWork,
)
from eom_catalog_contracts.material_native_files import (
    MATERIAL_NATIVE_BINDING_REF,
    MaterialNativeItemBinding,
    material_native_registration_key,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeVisualPreparationProfile,
)
from eom_catalog_contracts.material_native_visual_selection import (
    validate_material_native_visual_bindings,
)
from eom_catalog_contracts.material_native_visual_work import material_native_question_visual_scope
from eom_identifiers import content_sha256
from eom_identity_service.repository import effective_permissions
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
from eom_item_registry import ComponentPointer, RegistrationRequest
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.material_source_visual_publication import publish_material_pdf_visuals
from eom_orchestrator.office_picture_use_publication import resolve_material_office_source_images
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.models import MaterialLearningRoleResultV2, MaterialLearningRoleResultV3
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import (
    CATALOG_ITEM_EXACT_SCORE_PROTOCOL_VERSION,
    CATALOG_ITEM_EXACT_SCORE_SCHEMA_HASH,
    CATALOG_PROTOCOL_VERSION,
    CATALOG_SCHEMA_HASH,
    CatalogArtifactService,
)
from eom_catalog_service.creative_source_content import (
    CreativeSourceContent,
    materialize_source_observation_content,
)
from eom_catalog_service.material_learning_artifacts import publish_material_metadata
from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningSourceAuthorizer,
)
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_native_item_registration import (
    NATIVE_BINDING_MEMBER,
    NATIVE_ITEM_PACK_METADATA_REF,
    native_material_components,
    native_material_metadata,
    resolve_native_material_registration_binding,
    verify_registered_native_material,
)
from eom_catalog_service.material_native_resolution import verify_material_native_item_files
from eom_catalog_service.material_native_score import (
    read_native_question_score,
    require_native_source_score,
)
from eom_catalog_service.material_native_score_reanalysis import (
    NativeMaterialScoreReanalysisService,
    ResolvedNativeScoreTarget,
)
from eom_catalog_service.material_native_visual_context import read_native_visual_prepared_for_run
from eom_catalog_service.material_native_visual_preparation import (
    MaterialNativeVisualPreparationService,
)
from eom_catalog_service.material_page_source_read import read_material_source_pages
from eom_catalog_service.material_task_results import (
    ResolvedMaterialTask,
    resolve_completed_material_task,
)
from eom_catalog_service.models import (
    ContentPackRecord,
    ContentPackReleaseRecord,
    ItemComponentRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.pack_resources import PackResourceResolver
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.staging import stage_registry_item_content


@dataclass(frozen=True, slots=True)
class RegisteredMaterialItem:
    item_id: str
    item_revision_id: str
    content_sha256: str
    lineage: MaterialItemLineageFamily
    created: bool


class MaterialItemRegistrationService:
    """A revision-local key fences publication/replay, never holds model capacity."""

    def __init__(
        self,
        engine: Engine,
        *,
        content_pack_release_id: str,
        native_content_pack_release_id: str | None = None,
        coverage_content_pack_release_id: str | None = None,
        native_coverage_content_pack_release_id: str | None = None,
        exact_score_content_pack_release_id: str | None = None,
        native_exact_score_content_pack_release_id: str | None = None,
        publisher: ControlFileSetPublisher,
        source_commit: str,
        settings: CatalogSettings | None = None,
        native_visuals: MaterialNativeVisualPreparationService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings or CatalogSettings.from_environment()
        self.pack_release_id = content_pack_release_id
        self.native_pack_release_id = native_content_pack_release_id
        self.coverage_pack_release_id = coverage_content_pack_release_id
        self.native_coverage_pack_release_id = native_coverage_content_pack_release_id
        self.exact_score_pack_release_id = exact_score_content_pack_release_id
        self.native_exact_score_pack_release_id = native_exact_score_content_pack_release_id
        self.publisher, self.source_commit = publisher, source_commit
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.registry = RegistryService(engine, self.settings)
        self.sources = CatalogMaterialLearningSourceAuthorizer(engine, self.settings)
        self.pack_resources = PackResourceResolver()
        self.native_visuals = native_visuals
        self.score_reanalysis = NativeMaterialScoreReanalysisService(
            engine, publisher=publisher, source_commit=source_commit, settings=self.settings
        )

    def _selected_pack_release_id(
        self, resolved: ResolvedMaterialTask, native: MaterialNativeItemBinding | None
    ) -> str | None:
        """Keep historical registrations replayable; a missing successor is not a fallback."""
        if isinstance(resolved.role, MaterialLearningRoleResultV3):
            return (
                self.native_exact_score_pack_release_id
                if native
                else self.exact_score_pack_release_id
            )
        if isinstance(resolved.role, MaterialLearningRoleResultV2):
            return self.native_coverage_pack_release_id if native else self.coverage_pack_release_id
        return self.native_pack_release_id if native else self.pack_release_id

    def _authorize(
        self,
        session: Session,
        resolved: ResolvedMaterialTask,
        native: MaterialNativeItemBinding | None = None,
    ) -> None:
        self.sources.reauthorize(session, operator_id=resolved.operator_id, work=resolved.work)
        pack_id = self._selected_pack_release_id(resolved, native)
        release = (
            session.get(ContentPackReleaseRecord, pack_id, populate_existing=True)
            if pack_id
            else None
        )
        logical = session.get(ContentPackRecord, release.content_pack_id) if release else None
        expected_version = (
            ("1.5.0" if native else "1.4.0")
            if isinstance(resolved.role, MaterialLearningRoleResultV3)
            else ("1.3.0" if native else "1.2.0")
            if isinstance(resolved.role, MaterialLearningRoleResultV2)
            else ("1.1.0" if native else "1.0.0")
        )
        if (
            PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT
            not in effective_permissions(session, resolved.operator_id)
            or release is None
            or release.state != "RELEASED"
            or logical is None
            or logical.pack_key != MATERIAL_ITEM_PACK
            or release.version != expected_version
        ):
            raise ValueError("MATERIAL_ITEM_REGISTRATION_NOT_AUTHORIZED")
        if native is not None:
            schema = json.loads(
                self.pack_resources.read(
                    session, release, "metadata-schemas/item-metadata.schema.json"
                )
            )
            item_type = yaml.safe_load(
                self.pack_resources.read(session, release, "item-types/uploaded-material-item.yaml")
            )
            declaration = item_type.get("item_type") if isinstance(item_type, dict) else None
            if (
                not isinstance(schema, dict)
                or schema.get("$id") != NATIVE_ITEM_PACK_METADATA_REF
                or not isinstance(declaration, dict)
                or declaration.get("key") != MATERIAL_ITEM_TYPE
                or declaration.get("required_components")
                != ["ITEM_CONTENT", "SOURCE_REFERENCE", "REVIEW_REPORT", "METADATA", "OTHER"]
            ):
                raise ValueError("MATERIAL_ITEM_NATIVE_PACK_INVALID")

    def _native_binding(
        self, session: Session, resolved: ResolvedMaterialTask
    ) -> MaterialNativeItemBinding | None:
        def authorize() -> None:
            self.sources.reauthorize(session, operator_id=resolved.operator_id, work=resolved.work)

        return resolve_native_material_registration_binding(
            session,
            self.artifacts,
            resolved,
            authorize=authorize,
        )

    def register_completed(self, *, task_id: str, operator_id: str) -> RegisteredMaterialItem:
        with self.sessions() as session:
            resolved = resolve_completed_material_task(
                session, self.artifacts, task_id=task_id, operator_id=operator_id
            )
            native = self._native_binding(session, resolved)
            self._authorize(session, resolved, native)
        if not isinstance(resolved.work, MaterialExtractionWork) or not isinstance(
            resolved.role.output.learning_result,
            (MaterialExtractionResult, MaterialExtractionResultV2),
        ):
            raise ValueError("MATERIAL_ITEM_QUESTION_TASK_REQUIRED")
        if native is not None:

            def authorize_native() -> None:
                with self.sessions() as session:
                    self._authorize(session, resolved, native)

            verify_material_native_item_files(self.artifacts, native, authorize=authorize_native)
            self._verify_native_visual_scope(resolved, native, authorize=authorize_native)
        key = (
            material_native_registration_key(operator_id, native)
            if native is not None
            else material_item_registration_key(
                resolved.work.material_revision_id, resolved.unit_key
            )
        )
        # The same lock spans the existing Registry transaction. A process dying
        # after Registry commit leaves a reusable exact revision, not a second Item.
        with self.sessions.begin() as guard:
            guard.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
            current = resolve_completed_material_task(
                guard, self.artifacts, task_id=task_id, operator_id=operator_id
            )
            if current != resolved:
                raise ValueError("MATERIAL_ITEM_INPUT_CHANGED")
            if not isinstance(current.work, MaterialExtractionWork):
                raise ValueError("MATERIAL_ITEM_QUESTION_TASK_REQUIRED")
            if self._native_binding(guard, current) != native:
                raise ValueError("MATERIAL_ITEM_INPUT_CHANGED")
            self._authorize(guard, current, native)
            reanalysis = (
                self.score_reanalysis.registration_target(
                    guard, task_id=current.task_id, operator_id=operator_id
                )
                if native is not None and isinstance(current.role, MaterialLearningRoleResultV3)
                else None
            )
            target = reanalysis.target if reanalysis else None
            if target is not None:
                if native is None or (
                    native.binding_sha256 != target.native_binding_sha256
                    or native.question.document != target.question
                    or current.work.material_revision_id != target.material_revision_id
                ):
                    raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_NATIVE_CHANGED")
                if target.prior_item is not None:
                    # Keep the source-key advisory lock, but a new exact revision
                    # has its own idempotent identity and the same logical Item.
                    key = (
                        "material-native-score:"
                        + content_sha256(
                            {
                                "source_key": key,
                                "target_sha256": target.target_sha256,
                                "task_id": current.task_id,
                                "result_sha256": current.result_pointer.sha256,
                            }
                        )[7:]
                    )
            if native is not None and isinstance(current.role, MaterialLearningRoleResultV3):
                result = current.role.output.learning_result
                if not isinstance(result, MaterialExtractionResultV2) or result.proposal is None:
                    raise ValueError("MATERIAL_ITEM_SOURCE_UNREADABLE")
                # The request/result pin is not independent source authority. Read the
                # exact question again at registration, including idempotent replay.
                observation = read_native_question_score(
                    self.artifacts,
                    native.question,
                    authorize=lambda: self._authorize(guard, current, native),
                )
                require_native_source_score(observation, result.proposal.content.score)
            existing = guard.scalar(
                select(ItemRevisionRecord).where(ItemRevisionRecord.registration_key == key)
            )
            if existing is not None:
                if native is not None and (
                    existing.metadata_json.get("material_revision_id")
                    != current.work.material_revision_id
                    or existing.metadata_json.get("unit_key") != current.unit_key
                ):
                    raise ValueError("MATERIAL_NATIVE_METADATA_UPDATE_REQUIRED")
                lineage = self._verify_registered(
                    guard, existing, current, native, reanalysis=reanalysis
                )
                return RegisteredMaterialItem(
                    existing.item_id,
                    existing.item_revision_id,
                    lineage.registered_content_sha256,
                    lineage,
                    False,
                )
            if (
                native is not None
                and not isinstance(current.role, MaterialLearningRoleResultV3)
                and self.native_exact_score_pack_release_id is not None
            ):
                # Explicit installed successor availability closes *new* legacy
                # writes, not historical replay or the immutable old ABI.
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_REQUIRED")
            if target is not None:
                self.score_reanalysis.validate_target(guard, target, require_current=True)
            content = self._prepare_content(current)
            lineage = material_item_lineage(current, content, reanalysis=reanalysis)
            lineage_ref = _lineage_ref(current, reanalysis=reanalysis)
            content_ref = (
                ASSESSMENT_ITEM_CONTENT_V1_1_SCHEMA_REF
                if isinstance(content.content, AssessmentItemContentV1_1)
                else ASSESSMENT_ITEM_CONTENT_SCHEMA_REF
            )
            staged, digest = stage_registry_item_content(
                self.settings, content.content.model_dump(mode="json")
            )
            if digest != lineage.registered_content_sha256:
                raise ValueError("MATERIAL_ITEM_CONTENT_HASH_MISMATCH")
            artifact = self.artifacts.commit_file_set(
                files={ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged},
                primary_file=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
                artifact_type="assessment-item-content",
                idempotency_key="material-content:" + lineage.lineage_sha256[7:],
                request={"lineage_sha256": lineage.lineage_sha256},
                result={"content_sha256": digest},
                file_metadata={
                    ASSESSMENT_ITEM_CONTENT_FILE_NAME: {
                        "schema_ref": content_ref,
                        "media_type": "application/json",
                    }
                },
                expected_file_sha256={ASSESSMENT_ITEM_CONTENT_FILE_NAME: digest},
                protocol_version=(
                    CATALOG_ITEM_EXACT_SCORE_PROTOCOL_VERSION
                    if isinstance(content.content, AssessmentItemContentV1_1)
                    else CATALOG_PROTOCOL_VERSION
                ),
                protocol_schema_hash=(
                    CATALOG_ITEM_EXACT_SCORE_SCHEMA_HASH
                    if isinstance(content.content, AssessmentItemContentV1_1)
                    else CATALOG_SCHEMA_HASH
                ),
            )
            source = publish_material_metadata(
                self.artifacts,
                self.settings,
                lineage,
                member_path="lineage.json",
                schema_ref=lineage_ref,
                artifact_type="material-item-lineage",
                idempotency_key="material-lineage:" + lineage.lineage_sha256[7:],
            )
            native_pointer = (
                publish_material_metadata(
                    self.artifacts,
                    self.settings,
                    native,
                    member_path=NATIVE_BINDING_MEMBER,
                    schema_ref=MATERIAL_NATIVE_BINDING_REF,
                    artifact_type="material-native-item-binding",
                    idempotency_key="material-native-binding:" + native.binding_sha256[7:],
                )
                if native
                else None
            )
            metadata = {
                "item_type_key": MATERIAL_ITEM_TYPE,
                "source_kind": "EXTERNAL",
                "material_id": lineage.material_id,
                "material_revision_id": lineage.material_revision_id,
                "unit_key": lineage.unit_key,
                "title": content.content.title,
                "source_filename": next(
                    source.original_filename
                    for source in current.work.sources
                    if source.source_role == current.work.question.anchors[0].source_role
                ),
                "printed_label": current.work.question.printed_label,
                "section_path": list(current.work.question.section_path),
                "physical_pages": sorted(
                    {anchor.physical_page for anchor in current.work.question.anchors}
                ),
                "lineage_sha256": lineage.lineage_sha256,
                "approval_basis": "SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION",
            }
            if native is not None:
                assert native_pointer is not None
                metadata = native_material_metadata(metadata, native, native_pointer).model_dump(
                    mode="json"
                )
            self._authorize(guard, current, native)
            selected_pack_id = self._selected_pack_release_id(current, native)
            assert selected_pack_id is not None
            registered = self.registry.register(
                RegistrationRequest(
                    mode="REVISE_ITEM"
                    if target is not None and target.prior_item
                    else "CREATE_ITEM",
                    item_id=target.prior_item.item_id
                    if target is not None and target.prior_item
                    else None,
                    base_revision_id=target.prior_item.item_revision_id
                    if target is not None and target.prior_item
                    else None,
                    registration_key=key,
                    content_pack_release_id=selected_pack_id,
                    workflow_id=current.selection.workflow_id,
                    workflow_definition_key="material-learning",
                    workflow_definition_version=(
                        "3.0.0"
                        if isinstance(current.role, MaterialLearningRoleResultV3)
                        else "2.0.0"
                        if isinstance(current.role, MaterialLearningRoleResultV2)
                        else "1.0.0"
                    ),
                    source_workflow_step_run_id=current.selection.step_run_id,
                    source_intake_batch_ids=(),
                    item_type_key=MATERIAL_ITEM_TYPE,
                    metadata_schema_ref=(
                        NATIVE_ITEM_PACK_METADATA_REF
                        if native
                        else "eom://metadata/uploaded-material-item@1.0"
                    ),
                    metadata=metadata,
                    components=(
                        ComponentPointer(
                            component_type="ITEM_CONTENT",
                            ordinal=0,
                            schema_ref=content_ref,
                            media_type="application/json",
                            artifact_id=artifact.artifact_id,
                            artifact_revision_id=artifact.revision_id,
                            sha256=digest,
                            logical_name=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
                        ),
                        ComponentPointer(
                            component_type="SOURCE_REFERENCE",
                            ordinal=0,
                            schema_ref=lineage_ref,
                            media_type="application/json",
                            artifact_id=source.artifact_id,
                            artifact_revision_id=source.artifact_revision_id,
                            sha256=source.sha256,
                            logical_name=source.member_path,
                        ),
                        ComponentPointer(
                            component_type="REVIEW_REPORT",
                            ordinal=0,
                            schema_ref=current.result_pointer.schema_ref,
                            media_type="application/json",
                            artifact_id=current.result_pointer.artifact_id,
                            artifact_revision_id=current.result_pointer.artifact_revision_id,
                            sha256=current.result_pointer.sha256,
                            logical_name="result.json",
                            metadata={"report_kind": "MATERIAL_SOURCE_SOLUTION_AND_WARNINGS_V1"},
                        ),
                    )
                    + (
                        native_material_components(native, native_pointer)
                        if native is not None and native_pointer is not None
                        else ()
                    ),
                    created_by=current.operator_id,
                )
            )
            stored = self._verify_registered(
                guard, registered, current, native, reanalysis=reanalysis
            )
            if stored != lineage:
                raise ValueError("MATERIAL_ITEM_REGISTRATION_REPLAY_CONFLICT")
            return RegisteredMaterialItem(
                registered.item_id, registered.item_revision_id, digest, lineage, True
            )

    def _read(self, pointer: MaterialArtifactMember) -> bytes:
        return self.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            max_bytes=pointer.bytes,
        )

    def _verify_native_visual_scope(
        self,
        resolved: ResolvedMaterialTask,
        native: MaterialNativeItemBinding,
        *,
        authorize: Callable[[], None],
    ) -> None:
        """Reject another question/header even if its global picture is otherwise readable."""
        with self.sessions() as session:
            task = session.get(MaterialLearningTaskRecord, resolved.task_id)
            run = session.get(MaterialLearningRunRecord, task.run_id) if task else None
            if run is None:
                raise ValueError("MATERIAL_NATIVE_VISUAL_SOURCE_MISMATCH")
            prepared = read_native_visual_prepared_for_run(
                session, self.artifacts, run, authorize=authorize
            )
        if prepared is None:
            return  # Historical V1/V2 inputs are not retrospectively reinterpreted.
        if self.native_visuals is None:
            raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARATION_PROFILE_STALE")
        recorded, current = (
            MaterialNativeVisualPreparationProfile.model_validate(profile.model_dump(mode="json"))
            for profile in (prepared.visual_profile, self.native_visuals.profile)
        )
        # A compatible SDK release does not replace the historical producer pin.
        # Tool/parser/options must still match; the native scope is independently
        # recomputed below, so differing runtime source is not a visual authority.
        if recorded.model_dump(exclude={"source_commit", "profile_sha256"}) != current.model_dump(
            exclude={"source_commit", "profile_sha256"}
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARATION_PROFILE_STALE")
        assert isinstance(resolved.work, MaterialExtractionWork)
        scope = material_native_question_visual_scope(
            prepared, printed_label=resolved.work.question.printed_label
        )
        assert scope is not None
        source = resolved.work.sources[0]
        if source.source_role != "MAIN" or source.office_catalog is None:
            raise ValueError("MATERIAL_NATIVE_VISUAL_MAIN_SOURCE_REQUIRED")
        catalog = OfficePictureUseCatalog.model_validate_json(self._read(source.office_catalog))
        actual = self.native_visuals.question_scope(
            native.question,
            item_number=native.item_number,
            catalog=catalog,
            catalog_pointer=source.office_catalog,
            authorize=authorize,
        )
        if actual != scope:
            raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_SCOPE_MISMATCH")
        result = resolved.role.output.learning_result
        assert isinstance(result, (MaterialExtractionResult, MaterialExtractionResultV2))
        if result.office_bindings is not None:
            validate_material_native_visual_bindings(result.office_bindings, scope=scope)

    def _prepare_content(self, resolved: ResolvedMaterialTask) -> CreativeSourceContent:
        work, result = resolved.work, resolved.role.output.learning_result
        assert isinstance(work, MaterialExtractionWork)
        assert isinstance(result, (MaterialExtractionResult, MaterialExtractionResultV2))
        if result.proposal is None:
            raise ValueError("MATERIAL_ITEM_SOURCE_UNREADABLE")
        if not any(isinstance(block, SourceImageBlock) for block in result.proposal.content.body):
            return materialize_source_observation_content(result, resolved_images={})
        target_role = work.question.anchors[0].source_role
        source = next(source for source in work.sources if source.source_role == target_role)
        if source.actual_format != "PDF":
            assert source.office_catalog is not None
            assert result.office_bindings is not None
            pointer = source.office_catalog
            catalog = OfficePictureUseCatalog.model_validate_json(self._read(pointer))
            images = resolve_material_office_source_images(
                result=result,
                selection=result.office_bindings,
                catalog=catalog,
                catalog_pointer=ArtifactMemberPointer.model_validate(
                    pointer.model_dump(include=set(ArtifactMemberPointer.model_fields))
                ),
                expected_source_sha256=source.original.sha256,
            )
        else:
            page_numbers = tuple(
                sorted(
                    {page.physical_page for page in work.pages if page.source_role == target_role}
                )
            )
            pages = read_material_source_pages(self.artifacts, source, page_numbers)

            def authorize() -> None:
                with self.sessions() as session:
                    self._authorize(session, resolved)

            with TemporaryDirectory(
                prefix="material-visuals-", dir=self.settings.staging_root
            ) as raw:
                images = publish_material_pdf_visuals(
                    self.publisher,
                    work=work,
                    result=result,
                    role_result=resolved.result_pointer,
                    pages={
                        (target_role, entry.page.physical_page): entry.page for entry in pages.pages
                    },
                    read_source=self._read,
                    authorize=authorize,
                    workspace=Path(raw) / "figures",
                    source_commit=self.source_commit,
                )
        return materialize_source_observation_content(result, resolved_images=images)

    def _verify_registered(
        self,
        session: Session,
        revision: ItemRevisionRecord,
        resolved: ResolvedMaterialTask,
        native: MaterialNativeItemBinding | None = None,
        *,
        reanalysis: ResolvedNativeScoreTarget | None = None,
    ) -> MaterialItemLineageFamily:
        rows = tuple(
            session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == revision.item_revision_id
                )
            )
        )
        components = {(row.component_type, row.ordinal): row for row in rows}
        item = session.get(ItemRecord, revision.item_id, populate_existing=True)
        source = components.get(("SOURCE_REFERENCE", 0))
        lineage_ref = _lineage_ref(resolved, reanalysis=reanalysis)
        if (
            len(rows) != (6 if native else 3)
            or set(components)
            != (
                {("ITEM_CONTENT", 0), ("SOURCE_REFERENCE", 0), ("REVIEW_REPORT", 0)}
                | ({("METADATA", 0), ("OTHER", 0), ("OTHER", 1)} if native else set())
            )
            or item is None
            or item.lifecycle_state != "ACTIVE"
            or item.current_revision_id != revision.item_revision_id
            or revision.revision_state != "APPROVED"
            or source is None
            or revision.workflow_id != resolved.selection.workflow_id
            or revision.source_workflow_step_run_id != resolved.selection.step_run_id
            or source.schema_ref != lineage_ref
            or revision.content_pack_release_id != self._selected_pack_release_id(resolved, native)
        ):
            raise ValueError("MATERIAL_ITEM_REGISTRATION_REPLAY_CONFLICT")
        lineage = parse_material_item_lineage(
            json.loads(
                self.artifacts.read_member(
                    artifact_id=source.artifact_id,
                    revision_id=source.artifact_revision_id,
                    member_path=source.logical_name,
                    sha256=source.sha256,
                    schema_ref=source.schema_ref,
                    media_type="application/json",
                    max_bytes=64 * 1024,
                )
            )
        )
        content, report = components[("ITEM_CONTENT", 0)], components[("REVIEW_REPORT", 0)]
        result = resolved.role.output.learning_result
        content_ref = (
            ASSESSMENT_ITEM_CONTENT_V1_1_SCHEMA_REF
            if isinstance(result, MaterialExtractionResultV2)
            and result.proposal is not None
            and isinstance(result.proposal.content.score.points, str)
            else ASSESSMENT_ITEM_CONTENT_SCHEMA_REF
        )
        if (
            lineage.work_input != resolved.work_pointer
            or lineage.selection != resolved.selection
            or lineage.role_result != resolved.result_pointer
            or lineage.result_sha256
            != content_sha256(resolved.role.output.learning_result.model_dump(mode="json"))
            or lineage.requested_by != resolved.operator_id
            or lineage.task_id != resolved.task_id
            or lineage.unit_key != resolved.unit_key
            or content.sha256 != lineage.registered_content_sha256
            or content.schema_ref != content_ref
            or revision.metadata_json.get("lineage_sha256") != lineage.lineage_sha256
            or revision.metadata_json.get("source_kind") != "EXTERNAL"
            or (report.artifact_id, report.artifact_revision_id, report.sha256)
            != (
                resolved.result_pointer.artifact_id,
                resolved.result_pointer.artifact_revision_id,
                resolved.result_pointer.sha256,
            )
        ):
            raise ValueError("MATERIAL_ITEM_REGISTRATION_REPLAY_CONFLICT")
        self.artifacts.verify_member(
            artifact_id=content.artifact_id,
            revision_id=content.artifact_revision_id,
            member_path=content.logical_name,
            sha256=content.sha256,
            schema_ref=content_ref,
            media_type="application/json",
            max_bytes=2 * 1024 * 1024,
        )
        if native is not None:
            verify_registered_native_material(session, self.artifacts, revision, components, native)
        if reanalysis is not None and (
            not isinstance(lineage, MaterialItemLineageV4)
            or lineage.native_score_reanalysis != reanalysis.evidence
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_LINEAGE_MISMATCH")
        target = reanalysis.target if reanalysis else None
        if target is not None and target.prior_item is not None:
            prior = session.get(
                ItemRevisionRecord, target.prior_item.item_revision_id, populate_existing=True
            )
            if (
                revision.item_id != target.prior_item.item_id
                or prior is None
                or prior.revision_state != "SUPERSEDED"
                or prior.superseded_by_revision_id != revision.item_revision_id
                or prior.manifest_sha256 != target.prior_item.manifest_sha256
            ):
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_ITEM_STALE")
        return lineage


def material_item_lineage(
    resolved: ResolvedMaterialTask,
    content: CreativeSourceContent,
    *,
    reanalysis: ResolvedNativeScoreTarget | None = None,
) -> MaterialItemLineageFamily:
    work = resolved.work
    if not isinstance(work, MaterialExtractionWork):
        raise ValueError("MATERIAL_ITEM_QUESTION_TASK_REQUIRED")
    model: (
        type[MaterialItemLineage]
        | type[MaterialItemLineageV2]
        | type[MaterialItemLineageV3]
        | type[MaterialItemLineageV4]
    )
    version: str
    if reanalysis is not None:
        if not isinstance(resolved.role, MaterialLearningRoleResultV3):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_RESULT_REQUIRED")
        model, version = MaterialItemLineageV4, "4.0"
    elif isinstance(resolved.role, MaterialLearningRoleResultV3):
        model, version = MaterialItemLineageV3, "3.0"
    elif isinstance(resolved.role, MaterialLearningRoleResultV2):
        model, version = MaterialItemLineageV2, "2.0"
    else:
        model, version = MaterialItemLineage, "1.0"
    value = dict(
        schema_version="material-learning-item-lineage/" + version,
        material_id=work.material_id,
        material_revision_id=work.material_revision_id,
        task_id=resolved.task_id,
        unit_key=resolved.unit_key,
        selection=resolved.selection.model_dump(mode="json"),
        work_input=resolved.work_pointer.model_dump(mode="json"),
        role_result=resolved.result_pointer.model_dump(mode="json"),
        input_sha256=work.input_sha256,
        result_sha256=content_sha256(resolved.role.output.learning_result.model_dump(mode="json")),
        proposed_content_sha256=content.proposed_content_sha256,
        registered_content_sha256=content.registered_content_sha256,
        source_answer_mode=content.source_answer_mode,
        warning_codes=list(content.warning_codes),
        registration_policy="PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1",
        requested_by=resolved.operator_id,
        created_at=resolved.role.completed_at.isoformat().replace("+00:00", "Z"),
    )
    if reanalysis is not None:
        value["native_score_reanalysis"] = reanalysis.evidence.model_dump(mode="json")
    return model.model_validate({**value, "lineage_sha256": content_sha256(value)})


def _lineage_ref(
    resolved: ResolvedMaterialTask, *, reanalysis: ResolvedNativeScoreTarget | None = None
) -> str:
    if reanalysis is not None:
        return MATERIAL_ITEM_LINEAGE_V4_REF
    if isinstance(resolved.role, MaterialLearningRoleResultV3):
        return MATERIAL_ITEM_LINEAGE_V3_REF
    if isinstance(resolved.role, MaterialLearningRoleResultV2):
        return MATERIAL_ITEM_LINEAGE_V2_REF
    return MATERIAL_ITEM_LINEAGE_REF
