"""Catalog owns material/source permissions and exact page-to-source membership."""

from bisect import bisect_left

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialInputPage,
    MaterialLearningRights,
    MaterialLearningWork,
    material_work_schema_ref,
)
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationReply,
    MaterialLearningAuthorizationRequest,
)
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_learning_preparation import (
    MaterialDocumentRevision,
    MaterialPageBundle,
    MaterialPageChunk,
    material_chunk_member,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.material_learning_execution import validate_material_learning_execution_plan
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_workflow.compiler import compile_definition_data
from eom_workflow.material_learning_request import MaterialLearningWorkflowRequest
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import load_persisted_workflow_request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.educational_document_service import EducationalDocumentService
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.settings import CatalogSettings


class CatalogMaterialLearningSourceAuthorizer:
    def __init__(self, engine: Engine, settings: CatalogSettings) -> None:
        self.artifacts = CatalogArtifactService(engine, settings)
        self.documents = EducationalDocumentService(engine, settings)
        self.sources = MaterialLearningSourceService(engine, settings)

    def reauthorize(
        self, session: Session, *, operator_id: str, work: MaterialLearningWork
    ) -> MaterialLearningWork:
        authorize_material_learning(session, operator_id)
        task = session.get(MaterialLearningTaskRecord, work.task_id, populate_existing=True)
        run = (
            session.get(MaterialLearningRunRecord, task.run_id, populate_existing=True)
            if task
            else None
        )
        revision = session.get(LearningMaterialRevisionRecord, work.material_revision_id)
        material = session.get(LearningMaterialRecord, work.material_id, populate_existing=True)
        if (
            run is None
            or task is None
            or revision is None
            or material is None
            or material.lifecycle_state != "ACTIVE"
            or material.created_by != operator_id
            or revision.material_id != material.material_id
            or revision.created_by != operator_id
            or run.material_revision_id != revision.material_revision_id
            or run.created_by != operator_id
            or run.state == "CANCELLED"
            or task.state == "CANCELLED"
            or task.task_kind != ("DISCOVER" if work.task_kind == "DISCOVER" else "QUESTION")
            or task.input_artifact_revision_id is None
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_AUTHORIZATION_FAILED")
        artifact = session.get(ArtifactRevisionRecord, revision.manifest_artifact_revision_id)
        if artifact is None:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_INTAKE_MISSING")
        intake_pointer = MaterialArtifactMember(
            artifact_id=revision.manifest_artifact_id,
            artifact_revision_id=revision.manifest_artifact_revision_id,
            member_path=revision.manifest_member_path,
            schema_ref="eom://schemas/material-learning/intake/1.0",
            media_type="application/json",
            sha256=revision.manifest_sha256,
            bytes=artifact.content_bytes,
        )
        intake = read_material_metadata(
            self.artifacts,
            intake_pointer,
            MaterialLearningIntakeManifest,
            schema_ref=intake_pointer.schema_ref,
            member_path=intake_pointer.member_path,
        )
        if (
            intake.requested_by != operator_id
            or intake.material_id != work.material_id
            or intake.material_revision_id != work.material_revision_id
            or intake.rights_attestation != work.rights_attestation
            or intake.upload.additional_instructions != work.additional_instructions
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_INPUT_MISMATCH")
        rights = read_material_metadata(
            self.artifacts,
            work.rights_attestation,
            MaterialLearningRights,
            schema_ref="eom://schemas/material-learning/rights/1.0",
            member_path="rights/attestation.json",
        )
        if (rights.material_id, rights.material_revision_id, rights.attested_by) != (
            work.material_id,
            work.material_revision_id,
            operator_id,
        ) or rights.source_hashes != tuple(
            entry.source_upload.original.sha256 for entry in intake.sources
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RIGHTS_MISMATCH")
        input_artifact = session.get(ArtifactRevisionRecord, task.input_artifact_revision_id)
        if input_artifact is None or task.input_artifact_id is None or task.input_sha256 is None:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_INPUT_MISSING")
        input_pointer = MaterialArtifactMember(
            artifact_id=task.input_artifact_id,
            artifact_revision_id=task.input_artifact_revision_id,
            member_path="material/work.json",
            schema_ref=material_work_schema_ref(work),
            media_type="application/json",
            sha256=task.input_sha256,
            bytes=input_artifact.content_bytes,
        )
        actual = read_material_metadata(
            self.artifacts,
            input_pointer,
            type(work),
            schema_ref=input_pointer.schema_ref,
            member_path=input_pointer.member_path,
        )
        if actual != work:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_INPUT_CHANGED")
        selected = {entry.source_role: entry.source_upload for entry in intake.sources}
        if set(selected) != {source.source_role for source in work.sources}:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_ROLE_MISMATCH")
        for source in work.sources:
            receipt = selected[source.source_role]
            self.sources.resolve(receipt, operator_id=operator_id)
            registered = self.documents.inspect_material_revision(source.document_revision_id)
            document = read_material_metadata(
                self.artifacts,
                registered.revision_manifest,
                MaterialDocumentRevision,
                schema_ref=registered.revision_manifest.schema_ref,
                member_path=registered.revision_manifest.member_path,
            )
            if (
                document.material_id != work.material_id
                or document.material_revision_id != work.material_revision_id
                or document.source_role != source.source_role
                or document.document_id != source.document_id
                or registered.revision_manifest.sha256 != source.document_manifest_sha256
                or document.original != source.original
                or source.original != receipt.original
                or source.original_filename != receipt.original_filename
                or source.actual_format != receipt.source_format
                or document.source != source.pdf
                or document.analysis_bundle_manifest != source.page_bundle
                or document.rights_attestation != work.rights_attestation
                or document.source_page_count != source.page_count
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_INPUT_MISMATCH")
            bundle = read_material_metadata(
                self.artifacts,
                source.page_bundle,
                MaterialPageBundle,
                schema_ref=source.page_bundle.schema_ref,
                member_path=source.page_bundle.member_path,
            )
            if (
                bundle.document_revision_id != source.document_revision_id
                or bundle.original != source.original
                or bundle.pdf != source.pdf
                or bundle.office_catalog != source.office_catalog
                or bundle.page_count != source.page_count
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_PAGE_BUNDLE_MISMATCH")
            ends = tuple(chunk.last_physical_page for chunk in bundle.chunks)
            chunks: dict[int, MaterialPageChunk] = {}
            for page in work.pages:
                if page.source_role != source.source_role:
                    continue
                index = bisect_left(ends, page.physical_page)
                reference = bundle.chunks[index]
                if index not in chunks:
                    chunk = read_material_metadata(
                        self.artifacts,
                        reference.manifest,
                        MaterialPageChunk,
                        schema_ref=reference.manifest.schema_ref,
                        member_path=reference.manifest.member_path,
                    )
                    if (
                        chunk.document_id != source.document_id
                        or chunk.document_revision_id != source.document_revision_id
                        or chunk.source_role != source.source_role
                        or chunk.pdf_sha256 != source.pdf.sha256
                        or chunk.profile_sha256 != bundle.profile.profile_sha256
                        or (chunk.first_physical_page, chunk.last_physical_page)
                        != (
                            reference.first_physical_page,
                            reference.last_physical_page,
                        )
                    ):
                        raise MaterialLearningSourceError("MATERIAL_LEARNING_PAGE_CHUNK_MISMATCH")
                    chunks[index] = chunk
                chunk = chunks[index]
                observed = chunk.pages[page.physical_page - chunk.first_physical_page]

                expected = MaterialInputPage(
                    input_index=page.input_index,
                    source_role=source.source_role,
                    physical_page=observed.physical_page,
                    image=material_chunk_member(reference.manifest, observed.image),
                    text=material_chunk_member(reference.manifest, observed.text),
                    width_pixels=observed.width_pixels,
                    height_pixels=observed.height_pixels,
                )
                if page != expected:
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_PAGE_NOT_IN_SOURCE")
        authorize_material_learning(session, operator_id)
        return work


class CatalogMaterialLearningAuthorizationService:
    def __init__(self, engine: Engine, settings: CatalogSettings) -> None:
        self.sessions = build_session_factory(engine)
        self.source = CatalogMaterialLearningSourceAuthorizer(engine, settings)

    def authorize(
        self, request: MaterialLearningAuthorizationRequest
    ) -> MaterialLearningAuthorizationReply:
        with self.sessions() as session:
            workflow = session.get(
                WorkflowInstanceRecord, request.workflow_id, populate_existing=True
            )
            step = session.get(WorkflowStepRunRecord, request.step_run_id, populate_existing=True)
            if (
                workflow is None
                or step is None
                or workflow.definition_key != "material-learning"
                or workflow.created_actor_type != "human"
                or workflow.role_schema_version != "workflow-role/1.37.0"
                or step.workflow_id != workflow.workflow_id
                or step.step_key != "learn"
                or step.worker_role != "support"
                or step.step_type != "agent"
                or step.attempt != 1
                or step.result_schema != "material-learning-result@1.0"
            ):
                raise ValueError("material stored role differs")
            definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
            if definition is None:
                raise ValueError("material definition missing")
            compiled = compile_definition_data(
                definition.canonical_definition, definition.source_path, {"support"}
            )
            if (
                definition.definition_key != workflow.definition_key
                or definition.definition_version != workflow.definition_version
                or compiled.sha256 != workflow.definition_hash
                or definition.definition_hash != workflow.definition_hash
            ):
                raise ValueError("material pinned definition differs")
            original = load_persisted_workflow_request(workflow.initial_request)
            if not isinstance(
                original, MaterialLearningWorkflowRequest
            ) or original != load_persisted_workflow_request(workflow.request_payload):
                raise ValueError("material original input differs")
            plan = validate_material_learning_execution_plan(
                session.get(ResolvedExecutionPlanRecord, request.plan_id),
                workflow_id=workflow.workflow_id,
                step_key=step.step_key,
                request=original.worker_request(),
            )
            if (
                plan.plan_sha256 != request.plan_sha256
                or plan.work_input.input_sha256 != request.input_sha256
                or plan.workflow_definition_sha256 != workflow.definition_hash
                or plan.workflow_definition_version != workflow.definition_version
            ):
                raise ValueError("material requested plan differs")
            self.source.reauthorize(
                session, operator_id=workflow.created_actor_id, work=plan.work_input
            )
            task = session.get(
                MaterialLearningTaskRecord, plan.work_input.task_id, populate_existing=True
            )
            if task is None or task.workflow_id != workflow.workflow_id:
                raise ValueError("material task child binding differs")
            return MaterialLearningAuthorizationReply(
                status="SUCCESS",
                request_sha256=content_sha256(request.model_dump(mode="json")),
                input_sha256=request.input_sha256,
                error_code=None,
            )
