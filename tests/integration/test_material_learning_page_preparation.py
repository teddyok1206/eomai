"""Actual intake/Artifact/document owners with a synthetic local extractor, no models."""

from __future__ import annotations

import struct
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning_intake import CreateMaterialLearningCommand
from eom_catalog_contracts.material_learning_preparation import (
    MaterialDocumentReceipt,
    MaterialPreparationInput,
)
from eom_catalog_service.educational_document_service import EducationalDocumentService
from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_models import LearningMaterialRevisionRecord
from eom_catalog_service.material_learning_pages import MaterialPagePreparationService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.material_learning_source_projection import MaterialSourceProjectionService
from eom_catalog_service.models import EducationalDocumentRevisionRecord
from eom_identifiers import content_sha256
from eom_orchestrator.codex_compatibility_probe import synthetic_probe_png
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings
from eom_textbook_analysis.bundle import ExtractedMultimodalPage, PdfInspection
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.unit.test_material_learning_preparation import profile

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


class InterruptibleExtractor:
    implementation = "synthetic"
    version = "1.0"
    implementation_sha256 = "sha256:" + "a" * 64
    options_sha256 = "sha256:" + "a" * 64

    def __init__(self):
        self.calls = []
        self.interrupt = True

    def inspect(self, _path):
        return PdfInspection(page_count=3, encrypted=False)

    def extract_multimodal(self, path, first, last):
        assert path.is_file() and first == last
        self.calls.append(first)
        if first == 2 and self.interrupt:
            self.interrupt = False
            raise RuntimeError("synthetic process interruption after committed first chunk")
        png = synthetic_probe_png()
        width, height = struct.unpack(">II", png[16:24])
        return (ExtractedMultimodalPage(f"Synthetic page {first}", png, width, height, 180),)


def test_prepare_resume_reuses_chunk_and_registers_in_existing_document_owner(
    creative_engine, material_intake
):
    actor, settings, path, source_command = material_intake
    receipt = MaterialLearningSourceService(creative_engine, settings).ingest(path, source_command)
    command = CreateMaterialLearningCommand.model_validate(
        {
            "actor_id": actor,
            "idempotency_key": "material-pages-" + uuid4().hex,
            "upload": {
                "title": "Synthetic mixed workbook",
                "material_kind": "WORKBOOK",
                "source_description": "internal disposable fixture",
                "additional_instructions": "",
                "curriculum_unit_hints": [],
                "rights_confirmed": True,
            },
            "sources": [{"source_role": "MAIN", "source_upload": receipt.model_dump(mode="json")}],
        }
    )
    accepted = MaterialLearningIntakeService(creative_engine, settings).create(command)
    with Session(creative_engine) as session:
        revision = session.get(LearningMaterialRevisionRecord, accepted.material_revision_id)
        assert revision is not None
        # The manifest is one small primary; all original PDF bytes remain separate.
        from eom_orchestrator.models import ArtifactRevisionRecord

        artifact = session.get(ArtifactRevisionRecord, revision.manifest_artifact_revision_id)
        assert artifact is not None
        intake_pointer = {
            "artifact_id": revision.manifest_artifact_id,
            "artifact_revision_id": revision.manifest_artifact_revision_id,
            "member_path": revision.manifest_member_path,
            "schema_ref": "eom://schemas/material-learning/intake/1.0",
            "media_type": "application/json",
            "sha256": revision.manifest_sha256,
            "bytes": artifact.content_bytes,
        }
    raw_profile = profile()
    raw_profile["chunk_page_limit"] = 1
    raw_profile["profile_sha256"] = content_sha256(
        {key: value for key, value in raw_profile.items() if key != "profile_sha256"}
    )
    body = {
        "schema_version": "material-learning-preparation-input/1.0",
        "task_id": "materialtask_" + uuid4().hex,
        "material_id": accepted.material_id,
        "material_revision_id": accepted.material_revision_id,
        "intake_manifest": intake_pointer,
        "profile": raw_profile,
    }
    work = MaterialPreparationInput.model_validate({**body, "input_sha256": content_sha256(body)})
    platform = Settings(
        staging_root=settings.staging_root, nas_artifact_root=settings.nas_artifact_root
    )
    publisher = ControlFileSetPublisher(creative_engine, platform)
    extractor = InterruptibleExtractor()
    projections = MaterialSourceProjectionService(
        creative_engine,
        settings=settings,
        platform_settings=platform,
        publisher=publisher,
    )
    service = MaterialPagePreparationService(
        creative_engine,
        settings=settings,
        publisher=publisher,
        source_commit="1" * 40,
        extractor=extractor,
        projections=projections,
    )

    def authorize():
        with Session(creative_engine) as session:
            authorize_material_learning(session, actor)

    with pytest.raises(RuntimeError, match="synthetic process interruption"):
        service.prepare(work, operator_id=actor, authorize=authorize)
    result = service.prepare(work, operator_id=actor, authorize=authorize)
    assert extractor.calls == [1, 2, 2, 3], "already committed first page was extracted again"
    assert result.prepared.sources[0].page_count == 3
    assert result.prepared.sources[0].original == receipt.original
    replay = service.prepare(work, operator_id=actor, authorize=authorize)
    assert replay == result
    assert extractor.calls == [1, 2, 2, 3], "ready result replay repeated PDF work"
    documents = EducationalDocumentService(creative_engine, settings)
    registered = documents.inspect(result.prepared.sources[0].document_id)
    assert isinstance(registered, MaterialDocumentReceipt)
    assert registered.original == receipt.original
    assert registered.source == receipt.original
    with Session(creative_engine) as session:
        count = session.scalar(
            select(func.count())
            .select_from(EducationalDocumentRevisionRecord)
            .where(EducationalDocumentRevisionRecord.document_id == registered.document_id)
        )
        assert count == 1
    assert len(tuple(settings.nas_artifact_root.rglob("original.pdf"))) == 1
