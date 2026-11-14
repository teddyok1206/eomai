"""Prepare exact per-question visual scope without redoing documents or native splits.

Only the existing Orchestrator extracts and commits source pictures. Native
fragment pixels are temporary comparison inputs, never a second canonical image.
"""

import tempfile
from collections.abc import Callable
from pathlib import Path

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_files import (
    MaterialNativeFileBinding,
    require_material_native_split_result,
)
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparedArtifact,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MATERIAL_NATIVE_VISUAL_PREPARED_REF,
    MaterialNativeQuestionVisualScope,
    MaterialNativeVisualCatalogSupplement,
    MaterialNativeVisualPreparationProfile,
    MaterialNativeVisualPreparedArtifact,
    require_native_visual_prepared_base,
)
from eom_catalog_contracts.material_native_visual_selection import (
    build_material_native_question_visual_scope,
)
from eom_catalog_contracts.material_native_visual_work import require_material_native_visual_bundle
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.office_picture_use_extraction import extract_office_picture_use_input
from eom_orchestrator.office_picture_use_publication import publish_office_picture_catalog

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import (
    find_material_publication,
    read_material_metadata,
)
from eom_catalog_service.material_learning_pages import MaterialPreparationOutcome
from eom_catalog_service.material_learning_source import MaterialLearningSourceService
from eom_catalog_service.material_native_resolution import read_material_native_bundle
from eom_catalog_service.material_page_source_read import read_material_source_pages
from eom_catalog_service.settings import CatalogSettings

_CATALOG_REF = "eom://schemas/image-provider/office-picture-use-catalog/1.0"
_PREPARED_TYPE = "control_material_native_visual_prepared"


def require_native_visual_catalog_equivalence(
    base: OfficePictureUseCatalog, current: OfficePictureUseCatalog
) -> None:
    """This successor resolves geometry, not source content, ordering or already-valid views."""
    if (
        base.embedded_images != current.embedded_images
        or base.native_objects != current.native_objects
        or len(base.picture_uses) != len(current.picture_uses)
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_SOURCE_CHANGED")
    for before, after in zip(base.picture_uses, current.picture_uses, strict=True):
        if before.model_dump(exclude={"geometry", "unresolved_reasons"}) != after.model_dump(
            exclude={"geometry", "unresolved_reasons"}
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_SOURCE_CHANGED")
        reasons = before.unresolved_reasons
        if before.geometry != after.geometry:
            if (
                before.geometry is not None
                or after.geometry is None
                or "GEOMETRY_UNRESOLVED" not in reasons
            ):
                raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_GEOMETRY_CHANGED")
            reasons = tuple(reason for reason in reasons if reason != "GEOMETRY_UNRESOLVED")
        if reasons != after.unresolved_reasons:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_REASONS_CHANGED")
    views = {view.use_id: view for view in current.rendered_uses}
    if any(views.get(view.use_id) != view for view in base.rendered_uses):
        raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_EXISTING_VIEW_CHANGED")


class MaterialNativeVisualPreparationService:
    def __init__(
        self,
        *,
        artifacts: CatalogArtifactService,
        publisher: ControlFileSetPublisher,
        settings: CatalogSettings,
        tool_root: Path,
        source_commit: str,
    ) -> None:
        self.artifacts, self.publisher, self.settings = artifacts, publisher, settings
        self.tool_root, self.source_commit = tool_root, source_commit
        self.sources = MaterialLearningSourceService(artifacts.engine, settings)
        body = {
            "source_commit": source_commit,
            "office_tool_source_commit": tool_root.parent.name,
            "parser_implementation_sha256": content_sha256(
                {
                    name: sha256_file(tool_root / "eom_image_provider" / (name + ".py"))
                    for name in (
                        "office_embedded_images",
                        "office_picture_records",
                        "office_picture_xml",
                        "office_picture_views",
                    )
                }
            ),
            "options_sha256": content_sha256(
                {"scope": "NATIVE_BODY_EXACT_PIXEL_AND_VIEW_V1", "catalog": _CATALOG_REF}
            ),
        }
        self.profile = MaterialNativeVisualPreparationProfile.model_validate(
            {**body, "profile_sha256": content_sha256(body)}
        )

    def _read_exact(self, pointer: MaterialArtifactMember) -> bytes:
        payload = self.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=pointer.bytes,
        )
        if len(payload) != pointer.bytes:
            raise ValueError("MATERIAL_NATIVE_VISUAL_SOURCE_SIZE_MISMATCH")
        return payload

    def _catalog(self, pointer: MaterialArtifactMember) -> OfficePictureUseCatalog:
        return read_material_metadata(
            self.artifacts,
            pointer,
            OfficePictureUseCatalog,
            schema_ref=_CATALOG_REF,
            member_path="picture-use-catalog.json",
            maximum_bytes=8 * 1024 * 1024,
        )

    def question_scope(
        self,
        file: MaterialNativeFileBinding,
        *,
        item_number: int,
        catalog: OfficePictureUseCatalog,
        catalog_pointer: MaterialArtifactMember,
        authorize: Callable[[], None],
    ) -> MaterialNativeQuestionVisualScope:
        """Recompute from the actual native body at preparation and registration boundaries."""
        authorize()
        evidence = NativeItemSplitResult.model_validate_json(self._read_exact(file.split_evidence))
        require_material_native_split_result(file, evidence, item_number=item_number)
        with tempfile.TemporaryDirectory(
            prefix="native-question-visual.", dir=self.settings.staging_root
        ) as temporary:
            native = extract_office_picture_use_input(
                self._read_exact(file.document),
                expected_sha256=file.document.sha256,
                tool_root=self.tool_root,
                workspace=Path(temporary) / "question",
            )
            scope = build_material_native_question_visual_scope(
                file,
                item_number=item_number,
                source_catalog=catalog,
                source_catalog_sha256=catalog_pointer.sha256,
                question_catalog=native.catalog,
            )
        authorize()
        return scope

    def enrich(
        self,
        base: MaterialNativePreparedArtifact,
        base_pointer: MaterialArtifactMember,
        *,
        intake: MaterialNativeLearningIntakeManifest,
        operator_id: str,
        authorize: Callable[[], None],
    ) -> MaterialPreparationOutcome:
        """One immutable checkpoint; no source/document re-registration or model invocation."""
        if (base.material_id, base.material_revision_id, base.native_bundle) != (
            intake.material_id,
            intake.material_revision_id,
            intake.native_bundle,
        ) or intake.requested_by != operator_id:
            raise ValueError("MATERIAL_NATIVE_VISUAL_SOURCE_MISMATCH")

        def reauthorize() -> None:
            authorize()
            for selection in intake.sources:
                self.sources.resolve(selection.source_upload, operator_id=operator_id)
            authorize()

        reauthorize()
        bundle = read_material_native_bundle(
            self.artifacts,
            intake.native_bundle,
            sources=intake.sources,
            operator_id=operator_id,
            authorize=reauthorize,
        )
        key = (
            "material-native-visual-prepared:"
            + content_sha256(
                {
                    "base": base_pointer.model_dump(mode="json"),
                    "profile": self.profile.profile_sha256,
                }
            )[7:]
        )
        existing = find_material_publication(
            self.publisher, idempotency_key=key, artifact_type=_PREPARED_TYPE
        )
        if existing is not None:
            # Reuse the public checkpoint resolver, including exact base validation.
            from eom_catalog_service.material_intake_read import read_material_prepared

            encoded = self.artifacts.read_member(
                artifact_id=existing.artifact_id,
                revision_id=existing.artifact_revision_id,
                member_path=existing.member_path,
                schema_ref=existing.schema_ref,
                media_type=existing.media_type,
                sha256=existing.sha256,
                max_bytes=4 * 1024 * 1024,
            )
            pointer = MaterialArtifactMember(**existing.model_dump(), bytes=len(encoded))
            prepared = read_material_prepared(self.artifacts, pointer, authorize=reauthorize)
            if not isinstance(prepared, MaterialNativeVisualPreparedArtifact):
                raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARED_SCHEMA_MISMATCH")
            require_native_visual_prepared_base(prepared, base=base, base_pointer=base_pointer)
            require_material_native_visual_bundle(prepared, bundle)
            if prepared.visual_profile != self.profile:
                raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARATION_PROFILE_STALE")
            return MaterialPreparationOutcome(prepared, pointer)

        source = base.sources[0]
        if source.source_role != "MAIN" or source.office_catalog is None:
            raise ValueError("MATERIAL_NATIVE_VISUAL_MAIN_SOURCE_REQUIRED")
        pages = read_material_source_pages(self.artifacts, source, ())
        base_catalog = self._catalog(source.office_catalog)
        if (
            pages.bundle.profile.source_commit == self.source_commit
            and pages.bundle.profile.office_tool_source_commit == self.tool_root.parent.name
        ):
            catalog_pointer = source.office_catalog
            catalog = base_catalog
        else:
            with tempfile.TemporaryDirectory(
                prefix="native-source-visual.", dir=self.settings.staging_root
            ) as temporary:
                extracted = extract_office_picture_use_input(
                    self._read_exact(source.original),
                    expected_sha256=source.original.sha256,
                    tool_root=self.tool_root,
                    workspace=Path(temporary) / "source",
                )
                require_native_visual_catalog_equivalence(base_catalog, extracted.catalog)
                committed = publish_office_picture_catalog(
                    self.publisher,
                    extracted,
                    source_commit=self.source_commit,
                    authorize_source=reauthorize,
                )
                catalog = extracted.catalog
                catalog_pointer = MaterialArtifactMember(
                    artifact_id=committed.artifact_id,
                    artifact_revision_id=committed.artifact_revision_id,
                    member_path=committed.member_path,
                    schema_ref=committed.schema_ref,
                    media_type="application/json",
                    sha256=committed.sha256,
                    bytes=len(canonical_json_bytes(catalog.model_dump(mode="json"))),
                )
        scopes = tuple(
            self.question_scope(
                item.question,
                item_number=item.item_number,
                catalog=catalog,
                catalog_pointer=catalog_pointer,
                authorize=reauthorize,
            )
            for item in bundle.items
        )
        body = {
            **base.model_dump(mode="json", exclude={"schema_version", "prepared_sha256"}),
            "schema_version": "material-learning-prepared/3.0",
            "base_prepared": base_pointer.model_dump(mode="json"),
            "visual_profile": self.profile.model_dump(mode="json"),
            "catalog_supplements": [
                MaterialNativeVisualCatalogSupplement(
                    source_role="MAIN", base_catalog=source.office_catalog, catalog=catalog_pointer
                ).model_dump(mode="json")
            ],
            "question_visual_scopes": [scope.model_dump(mode="json") for scope in scopes],
        }
        prepared = MaterialNativeVisualPreparedArtifact.model_validate(
            {**body, "prepared_sha256": content_sha256(body)}
        )
        require_native_visual_prepared_base(prepared, base=base, base_pointer=base_pointer)
        require_material_native_visual_bundle(prepared, bundle)
        reauthorize()
        pointer = self._publish(prepared, key=key)
        reauthorize()
        return MaterialPreparationOutcome(prepared, pointer)

    def _publish(
        self, prepared: MaterialNativeVisualPreparedArtifact, *, key: str
    ) -> MaterialArtifactMember:
        encoded = canonical_json_bytes(prepared.model_dump(mode="json"))
        digest = sha256_bytes(encoded)
        with tempfile.TemporaryDirectory(
            prefix="native-visual-checkpoint.", dir=self.settings.staging_root
        ) as temporary:
            path = Path(temporary) / "prepared.json"
            with path.open("xb") as stream:
                stream.write(encoded)
            published = self.publisher.publish_first_observation(
                members=(
                    ControlFileSetMember(
                        "material/prepared.json",
                        path,
                        digest,
                        len(encoded),
                        MATERIAL_NATIVE_VISUAL_PREPARED_REF,
                        "application/json",
                    ),
                ),
                primary_file="material/prepared.json",
                artifact_type=_PREPARED_TYPE,
                manifest_version="material-learning-prepared-artifact/3.0",
                idempotency_key=key,
                source_commit=self.source_commit,
            )
        if published.primary_sha256 != digest:
            raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARED_PUBLICATION_MISMATCH")
        return MaterialArtifactMember(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.artifact_revision_id,
            member_path="material/prepared.json",
            schema_ref=MATERIAL_NATIVE_VISUAL_PREPARED_REF,
            media_type="application/json",
            sha256=published.primary_sha256,
            bytes=len(encoded),
        )
