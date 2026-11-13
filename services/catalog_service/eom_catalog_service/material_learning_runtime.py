"""Installed composition of the existing document, Registry, Graph and Workflow owners."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from eom_catalog_contracts.material_learning_preparation import (
    MaterialExtractorIdentity,
    MaterialPreparationProfile,
)
from eom_identifiers import content_sha256, sha256_file
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.preset_model_selection import (
    resolve_released_capacity_policy,
    validated_preset,
)
from eom_orchestrator.settings import Settings
from eom_textbook_analysis.bundle import PopplerTesseractTextExtractor
from eom_workflow.control_plane import ExecutionPresetRevision, WorkerCapacityPolicyV7
from eom_workflow.shared_worker_capacity import SharedWorkerCapacityPolicy
from eom_workflow_runner.models import WorkflowDefinitionRecord
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from eom_catalog_service.material_graph_learning import (
    MaterialAnalysisControls,
    MaterialGraphLearningService,
)
from eom_catalog_service.material_item_registration import MaterialItemRegistrationService
from eom_catalog_service.material_learning_coordinator import MaterialLearningCoordinator
from eom_catalog_service.material_learning_pages import MaterialPagePreparationService
from eom_catalog_service.material_learning_processing import MaterialLearningProcessingService
from eom_catalog_service.material_learning_source_projection import MaterialSourceProjectionService
from eom_catalog_service.material_office_conversion import CatalogOwnerMaterialOfficeConverter
from eom_catalog_service.material_pdf_isolation import MaterialPdfSandboxRunner
from eom_catalog_service.settings import CatalogSettings


class MaterialLearningRuntimePins(BaseModel):
    """Small deployment settings, not an upload/model-supplied execution grant."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    learning_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    item_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    solution_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    document_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    content_pack_release_id: str = Field(min_length=1, max_length=128)
    native_content_pack_release_id: str | None = Field(default=None, min_length=1, max_length=128)
    definition_id: str = Field(min_length=1, max_length=128)

    @classmethod
    def from_environment(cls) -> "MaterialLearningRuntimePins":
        return cls.model_validate(
            {key: os.environ.get("EOM_MATERIAL_" + key.upper()) for key in cls.model_fields}
        )


@dataclass(frozen=True, slots=True)
class MaterialLearningRuntime:
    processing: MaterialLearningProcessingService


def build_material_learning_runtime(
    engine: Engine,
    pins: MaterialLearningRuntimePins,
    *,
    platform: Settings,
    catalog: CatalogSettings,
) -> MaterialLearningRuntime:
    """Resolve frozen installed controls once; no startup release or runtime Git reads."""
    if platform.runtime_source_commit is None:
        raise ValueError("MATERIAL_LEARNING_RUNTIME_SOURCE_REQUIRED")
    sessions = build_session_factory(engine)
    presets: list[ExecutionPresetRevision] = []
    with sessions() as session:
        for key, revision, protocol in (
            ("material-learning", pins.learning_preset_revision_id, "workflow-role/1.37.0"),
            ("material-item-analysis", pins.item_preset_revision_id, "workflow-role/1.4.0"),
            ("material-item-solution", pins.solution_preset_revision_id, "workflow-role/1.35.0"),
            (
                "material-knowledge-analysis",
                pins.document_preset_revision_id,
                "workflow-role/1.38.0",
            ),
        ):
            row = session.get(ExecutionPresetRevisionRecord, revision)
            value = validated_preset(row) if row else None
            logical = session.get(ExecutionPresetRecord, value.preset_id) if value else None
            if (
                not isinstance(value, ExecutionPresetRevision)
                or value.state != "RELEASED"
                or value.compatible_workflow_protocols != (protocol,)
                or logical is None
                or logical.state != "ACTIVE"
                or logical.preset_key != key
            ):
                raise ValueError("MATERIAL_LEARNING_RUNTIME_PRESET_INVALID")
            presets.append(value)
        if len({value.capacity_policy_revision_id for value in presets}) != 1:
            raise ValueError("MATERIAL_LEARNING_RUNTIME_CAPACITY_INVALID")
        capacity = resolve_released_capacity_policy(session, presets[0].capacity_policy_revision_id)
        if not isinstance(capacity, (WorkerCapacityPolicyV7, SharedWorkerCapacityPolicy)):
            raise ValueError("MATERIAL_LEARNING_RUNTIME_CAPACITY_INVALID")
        definition = session.get(WorkflowDefinitionRecord, pins.definition_id)
        if definition is None or (definition.definition_key, definition.definition_version) != (
            "material-learning",
            "1.0.0",
        ):
            raise ValueError("MATERIAL_LEARNING_RUNTIME_DEFINITION_INVALID")
    extractor = PopplerTesseractTextExtractor(
        pdftotext=Path("/usr/bin/pdftotext"),
        pdfinfo=Path("/usr/bin/pdfinfo"),
        pdftoppm=Path("/usr/bin/pdftoppm"),
        tesseract=Path("/usr/bin/tesseract"),
        tessdata_directory=Path("/usr/share/tesseract-ocr/5/tessdata"),
        ocr_mode="fallback",
        run=MaterialPdfSandboxRunner(output_root=catalog.staging_root),
        temporary_root=catalog.staging_root,
    )
    converter = CatalogOwnerMaterialOfficeConverter()
    if platform.office_image_tool_root is None:
        raise ValueError("MATERIAL_LEARNING_OFFICE_TOOLS_UNAVAILABLE")
    body = dict(
        schema_version="material-learning-preparation-profile/1.0",
        source_commit=platform.runtime_source_commit,
        extractor=MaterialExtractorIdentity(
            implementation=extractor.implementation,
            version=extractor.version,
            implementation_sha256=extractor.implementation_sha256,
            options_sha256=extractor.options_sha256,
        ).model_dump(mode="json"),
        office_tool_source_commit=platform.office_image_tool_root.parent.name,
        libreoffice_sha256=sha256_file(converter.libreoffice),
        h2orestart_sha256=sha256_file(converter.h2orestart_bundle),
        maximum_pages=2000,
        maximum_rendered_bytes=4 * 1024**3,
        chunk_page_limit=128,
        chunk_soft_bytes=256 * 1024**2,
    )
    profile = MaterialPreparationProfile.model_validate(
        {**body, "profile_sha256": content_sha256(body)}
    )
    publisher = ControlFileSetPublisher(engine, platform)
    preparation = MaterialPagePreparationService(
        engine,
        settings=catalog,
        publisher=publisher,
        source_commit=platform.runtime_source_commit,
        extractor=extractor,
        projections=MaterialSourceProjectionService(
            engine,
            settings=catalog,
            platform_settings=platform,
            publisher=publisher,
            converter=converter,
        ),
    )
    coordinator = MaterialLearningCoordinator(
        engine,
        settings=catalog,
        preparation=preparation,
        profile=profile,
        preset=presets[0],
        definition_id=pins.definition_id,
        owner_id="material-owner-" + uuid4().hex,
    )
    processing = MaterialLearningProcessingService(
        coordinator,
        registration=MaterialItemRegistrationService(
            engine,
            content_pack_release_id=pins.content_pack_release_id,
            native_content_pack_release_id=pins.native_content_pack_release_id,
            publisher=publisher,
            source_commit=platform.runtime_source_commit,
            settings=catalog,
        ),
        graph=MaterialGraphLearningService(
            engine,
            settings=catalog,
            controls=MaterialAnalysisControls(
                presets[1],
                presets[3],
                presets[2],
                pins.risk_policy_revision_id,
                pins.access_policy_revision_id,
            ),
        ),
    )
    return MaterialLearningRuntime(processing)
