"""Application service for reviewed legacy-source selection and Content Intake."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts import (
    LegacyKnowledgeContractErrorCode,
    LegacyRootAlias,
    LegacySelectedOriginalSourceV2,
    LegacySourceInventoryEntry,
    LegacySourceInventoryV2,
    LegacySourceSelectionV2,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.intake_files import MAX_BATCH_BYTES, MAX_FILE_BYTES
from eom_catalog_service.intake_service import IntakeService
from eom_catalog_service.legacy_source_inventory import (
    LegacySourceInventoryError,
    LegacySourceRootConfiguration,
    load_protected_legacy_control_document,
)
from eom_catalog_service.legacy_source_materialization import LegacySourceMaterializer
from eom_catalog_service.legacy_source_selection_boundary import (
    LegacyContentIntakeBoundary,
    LegacyRightsReviewResolver,
    LegacySelectionArtifactBoundary,
    LegacySelectionIntakeResult,
    LegacySelectionValidation,
    LegacySourceSelectionError,
    SelectedInventoryEntry,
)
from eom_catalog_service.settings import CatalogSettings


def load_source_selection(path: Path) -> LegacySourceSelectionV2:
    """Load one protected V2 selection and reject unbound-rights V1 files."""

    try:
        value = load_protected_legacy_control_document(path)
        validate_contract("legacy-source-selection-v2", value)
        return LegacySourceSelectionV2.model_validate(value)
    except LegacySourceInventoryError as exc:
        raise LegacySourceSelectionError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONFIGURATION_INVALID
        ) from exc
    except (ValueError, JsonSchemaValidationError) as exc:
        raise LegacySourceSelectionError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONTRACT_INVALID
        ) from exc


class LegacySourceSelectionService:
    """Validate one reviewed selection and route its originals through Content Intake."""

    def __init__(
        self,
        *,
        settings: CatalogSettings,
        rights: LegacyRightsReviewResolver,
        intake: LegacyContentIntakeBoundary | None = None,
        selection_artifacts: LegacySelectionArtifactBoundary | None = None,
        materializer: LegacySourceMaterializer | None = None,
    ) -> None:
        self.settings = settings
        self.rights = rights
        self.intake = intake
        self.selection_artifacts = selection_artifacts
        self.materializer = materializer or LegacySourceMaterializer(settings)

    @classmethod
    def from_engine(
        cls, engine: Engine, settings: CatalogSettings | None = None
    ) -> LegacySourceSelectionService:
        from eom_catalog_service.legacy_source_selection_adapters import (
            CatalogLegacyContentIntakeBoundary,
            CatalogLegacyRightsReviewResolver,
            CatalogLegacySelectionArtifactBoundary,
        )

        resolved_settings = settings or CatalogSettings.from_environment()
        artifacts = CatalogArtifactService(engine, resolved_settings)
        return cls(
            settings=resolved_settings,
            rights=CatalogLegacyRightsReviewResolver(artifacts),
            intake=CatalogLegacyContentIntakeBoundary(IntakeService(engine, resolved_settings)),
            selection_artifacts=CatalogLegacySelectionArtifactBoundary(
                artifacts, resolved_settings
            ),
        )

    def validate(
        self,
        *,
        selection: LegacySourceSelectionV2,
        inventory: LegacySourceInventoryV2,
        roots: LegacySourceRootConfiguration,
    ) -> LegacySelectionValidation:
        prepared = self._prepare(selection=selection, inventory=inventory, roots=roots)
        with self.materializer.materialize(
            prepared.entries,
            roots=roots,
            root_alias=prepared.root_alias,
        ):
            pass
        return prepared.validation

    def create_intake(
        self,
        *,
        selection: LegacySourceSelectionV2,
        inventory: LegacySourceInventoryV2,
        roots: LegacySourceRootConfiguration,
    ) -> LegacySelectionIntakeResult:
        if self.intake is None or self.selection_artifacts is None:
            raise RuntimeError("legacy selection mutation boundaries are not configured")
        prepared = self._prepare(selection=selection, inventory=inventory, roots=roots)
        with self.materializer.materialize(
            prepared.entries,
            roots=roots,
            root_alias=prepared.root_alias,
        ) as materialized:
            intake = self.intake.create(
                materialized.directory,
                batch_name=f"legacy-{selection.selection_id}",
                received_by=selection.reviewed_by,
                purpose=(
                    f"legacy-selection:{selection.selection_id};"
                    f"corpus:{prepared.validation.intended_corpus_key}"
                ),
                source_owner_type="legacy_system",
                source_owner_reference=prepared.validation.source_owner_reference,
                source_declarations=materialized.declarations,
            )
        artifact = self.selection_artifacts.commit(selection, intake)
        return LegacySelectionIntakeResult(
            validation=prepared.validation,
            intake=intake,
            selection_artifact=artifact,
        )

    def _prepare(
        self,
        *,
        selection: LegacySourceSelectionV2,
        inventory: LegacySourceInventoryV2,
        roots: LegacySourceRootConfiguration,
    ) -> _PreparedSelection:
        try:
            validate_contract("legacy-source-selection-v2", selection.model_dump(mode="json"))
            validate_contract("legacy-source-inventory-v2", inventory.model_dump(mode="json"))
        except (ValueError, JsonSchemaValidationError) as exc:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONTRACT_INVALID
            ) from exc
        if (
            selection.inventory_id != inventory.inventory_id
            or selection.inventory_sha256 != inventory.inventory_sha256
        ):
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_INVENTORY_STALE
            )
        root_alias = LegacyRootAlias(inventory.root_alias)
        if roots.identity_sha256(root_alias) != inventory.root_configuration_sha256:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_ROOT_CHANGED
            )
        by_key = {entry.entry_key: entry for entry in inventory.entries}
        owners = {source.source_owner_reference for source in selection.selected_sources}
        corpora = {source.intended_corpus_key for source in selection.selected_sources}
        if len(owners) != 1 or len(corpora) != 1:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONTRACT_INVALID
            )
        entries: list[SelectedInventoryEntry] = []
        total_bytes = 0
        for selected in selection.selected_sources:
            entry = by_key.get(selected.entry_key)
            if entry is None:
                raise LegacySourceSelectionError(
                    LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_INVENTORY_STALE
                )
            self._validate_original(selection, selected, entry)
            total_bytes += entry.size_bytes
            if entry.size_bytes > MAX_FILE_BYTES or total_bytes > MAX_BATCH_BYTES:
                raise LegacySourceSelectionError(
                    LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CAPACITY_EXCEEDED
                )
            entries.append(SelectedInventoryEntry(selected=selected, entry=entry))
        for evidence in selection.comparison_evidence:
            entry = by_key.get(evidence.entry_key)
            if (
                entry is None
                or entry.preliminary_class != "DERIVED_MIGRATION_EVIDENCE"
                or entry.canonicality != "DERIVED"
                or entry.content_sha256 != evidence.content_sha256
            ):
                raise LegacySourceSelectionError(
                    LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CLASS_INVALID
                )
        validation = LegacySelectionValidation(
            selection_id=selection.selection_id,
            selection_sha256=selection.selection_sha256,
            inventory_id=selection.inventory_id,
            inventory_sha256=selection.inventory_sha256,
            intended_corpus_key=next(iter(corpora)),
            source_owner_reference=next(iter(owners)),
            selected_source_count=len(entries),
            comparison_evidence_count=len(selection.comparison_evidence),
            selected_byte_count=total_bytes,
        )
        return _PreparedSelection(
            validation=validation,
            root_alias=root_alias,
            entries=tuple(entries),
        )

    def _validate_original(
        self,
        selection: LegacySourceSelectionV2,
        selected: LegacySelectedOriginalSourceV2,
        entry: LegacySourceInventoryEntry,
    ) -> None:
        if (
            entry.preliminary_class != "ORIGINAL_SOURCE_CANDIDATE"
            or entry.file_observation != "REGULAR"
            or entry.canonicality != "ORIGINAL"
            or entry.source_family != selected.reviewed_source_family
            or entry.content_sha256 != selected.content_sha256
            or entry.media_type is None
            or entry.exclusion_reasons
        ):
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CLASS_INVALID
            )
        try:
            rights = self.rights.resolve(selected.rights_review)
        except LegacySourceSelectionError:
            raise
        except Exception as exc:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_POINTER_STALE
            ) from exc
        expected_document_type = (
            "ASSESSMENT_ITEM"
            if selected.reviewed_source_family == "ITEM"
            else selected.reviewed_source_family
        )
        source = rights.source
        if (
            source.inventory_id != selection.inventory_id
            or source.inventory_sha256 != selection.inventory_sha256
            or source.entry_key != selected.entry_key
            or source.content_sha256 != selected.content_sha256
            or rights.source_owner_reference != selected.source_owner_reference
            or rights.document_type != expected_document_type
            or rights.rights_state != selected.rights_state
            or not rights.allowed_internal_processing
            or rights.reviewed_at > selection.reviewed_at
        ):
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_RIGHTS_INVALID
            )


@dataclass(frozen=True)
class _PreparedSelection:
    validation: LegacySelectionValidation
    root_alias: LegacyRootAlias
    entries: tuple[SelectedInventoryEntry, ...]
