"""Content Pack binding, prompt provenance, and deterministic workflow registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from eom_catalog_contracts import (
    ASSESSMENT_ITEM_CONTENT_FILE_NAME,
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
    AssessmentItemContent,
    ImageBlock,
    MediaArtifactPointer,
    validate_contract,
    validate_eom_question_template_content,
)
from eom_content_pack import ContentPackError, ContentPackErrorCode, render_prompt
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_image_contracts import LocalImageProviderBinding, content_json_bytes
from eom_item_registry import ComponentPointer, RegistrationRequest
from eom_orchestrator.database import build_session_factory
from eom_workflow import ArtifactPointer, ItemBriefV2, WorkflowRequest
from eom_workflow.models import (
    GeneratedAuthoringRoleResult,
    GeneratedAuthoringRoleResultV4,
    GeneratedAuthoringRoleResultV5,
    GeneratedAuthoringRoleResultV6,
    GeneratedImageRoleResult,
    GeneratedImageRoleResultV4,
    GeneratedImageRoleResultV5,
    GeneratedImageRoleResultV6,
    GeneratedLineGraphDrawing,
    GeneratedLineGraphDrawingV5,
    GeneratedLineGraphDrawingV6,
    GeneratedVectorDrawingV5,
    GeneratedVectorDrawingV6,
    KnowledgeAuthoringRoleResult,
    RoleResult,
)
from eom_workflow.schemas import validate_role_result
from eom_workflow_runner.catalog_port import (
    GeneratedStimulusPointer,
    PreparedPrompt,
    RegistrationOutcome,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.generated_stimulus import (
    BACKGROUND_MEMBER,
    LOCAL_IMAGE_RECEIPT_MEMBER,
    PNG_HEIGHT,
    PNG_MEMBER,
    PNG_WIDTH,
    RASTER_MEMBER,
    render_generated_local_vector_stimulus,
    render_generated_stimulus,
    render_generated_vector_stimulus,
)
from eom_catalog_service.knowledge_stimulus import KnowledgeStimulusService
from eom_catalog_service.local_image_adapter import (
    FixedLocalImageProviderAdapter,
    load_local_image_provider_binding,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentPackActivationRecord,
    ContentPackProfileRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
)
from eom_catalog_service.pack_resources import PackResourceResolver
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.staging import (
    create_catalog_operation_directory,
    require_catalog_runtime_directory,
    stage_registry_item_content,
)
from eom_catalog_service.vector_stimulus import (
    SVG_ALLOWED_FONT_FAMILIES,
    SVG_FONT_FAMILY,
    SVG_FONT_PROFILE,
    SVG_MEDIA_TYPE,
    SVG_MEMBER,
    SVG_RENDERER_CONTRACT,
)

ROLE_PROFILE_KEYS = {
    "authoring": "authoring",
    "image": "image",
    "review": "review",
    "item_management": "registration",
}
COMPONENT_TYPES = {
    "authoring": "UPPER_STEM",
    "image": "IMAGE_SPEC",
    "review": "REVIEW_REPORT",
    "registration": "METADATA",
}
ComponentType = Literal["UPPER_STEM", "IMAGE_SPEC", "REVIEW_REPORT", "METADATA", "ITEM_CONTENT"]
ROLE_BY_RESULT_SCHEMA = {
    "authoring-result@1.0": "authoring",
    "authoring-result@2.0": "authoring",
    "authoring-result@3.0": "authoring",
    "image-result@1.0": "image",
    "image-result@2.0": "image",
    "image-result@3.0": "image",
    "review-result@1.0": "review",
    "review-result@2.0": "review",
    "review-result@3.0": "review",
    "registration-result@1.0": "item_management",
    "registration-result@2.0": "item_management",
    "registration-result@3.0": "item_management",
    "authoring-result@4.0": "authoring",
    "image-result@4.0": "image",
    "review-result@4.0": "review",
    "registration-result@4.0": "item_management",
    "authoring-result@5.0": "authoring",
    "image-result@5.0": "image",
    "review-result@5.0": "review",
    "registration-result@5.0": "item_management",
    "authoring-result@6.0": "authoring",
    "image-result@6.0": "image",
    "review-result@6.0": "review",
    "registration-result@6.0": "item_management",
    "knowledge-analysis-proposal-result@1.0": "support",
    "knowledge-analysis-proposal-result@2.0": "support",
    "knowledge-analysis-proposal-result@3.0": "support",
    "knowledge-analysis-proposal-result@4.0": "support",
    "knowledge-analysis-proposal-result@5.0": "support",
    "knowledge-analysis-proposal-result@6.0": "support",
    "knowledge-analysis-proposal-result@7.0": "support",
    "knowledge-analysis-proposal-result@8.0": "support",
    "legacy-item-extraction-result@1.0": "support",
}
GENERATED_RESULT_SCHEMA_PAIRS = frozenset(
    {
        ("authoring-result@3.0", "image-result@3.0"),
        ("authoring-result@4.0", "image-result@4.0"),
        ("authoring-result@5.0", "image-result@5.0"),
        ("authoring-result@6.0", "image-result@6.0"),
    }
)
GENERATED_AUTHORING_SCHEMAS = frozenset(pair[0] for pair in GENERATED_RESULT_SCHEMA_PAIRS)
GENERATED_IMAGE_SCHEMAS = frozenset(pair[1] for pair in GENERATED_RESULT_SCHEMA_PAIRS)


def _validate_generated_vector_artifact_manifest(
    manifest: dict[str, Any],
    *,
    expected_file_sha256: dict[str, str],
    file_metadata: dict[str, dict[str, str]],
    content_hash: str,
    manifest_version: str = "generated-item-stimulus-file-set/2.0",
) -> None:
    files = manifest.get("files")
    entries = (
        {entry.get("file_name"): entry for entry in files if isinstance(entry, dict)}
        if isinstance(files, list)
        else {}
    )
    if (
        manifest.get("manifest_version") != manifest_version
        or manifest.get("primary_file") != PNG_MEMBER
        or not isinstance(files, list)
        or len(files) != len(expected_file_sha256)
        or len(entries) != len(expected_file_sha256)
        or set(entries) != set(expected_file_sha256)
        or content_hash != expected_file_sha256[PNG_MEMBER]
    ):
        raise ValueError("generated vector stimulus manifest identity is invalid")
    for member, expected_hash in expected_file_sha256.items():
        entry = entries[member]
        if (
            entry.get("sha256") != expected_hash
            or entry.get("schema_ref") != file_metadata[member]["schema_ref"]
            or entry.get("media_type") != file_metadata[member]["media_type"]
        ):
            raise ValueError("generated vector stimulus manifest member is invalid")


GENERAL_KNOWLEDGE_SOURCE_MODE: Literal["general_model_knowledge"] = "general_model_knowledge"
GRAPH_GROUNDED_KNOWLEDGE_SOURCE_MODE: Literal["graph_grounded"] = "graph_grounded"


def _generated_result_pointers(
    artifacts: tuple[ArtifactPointer, ...],
) -> tuple[ArtifactPointer, ArtifactPointer]:
    authoring = next(
        (
            pointer
            for pointer in artifacts
            if pointer.step_key == "authoring"
            and pointer.result_schema in GENERATED_AUTHORING_SCHEMAS
        ),
        None,
    )
    image = next(
        (
            pointer
            for pointer in artifacts
            if pointer.step_key == "image" and pointer.result_schema in GENERATED_IMAGE_SCHEMAS
        ),
        None,
    )
    if authoring is None or image is None:
        raise ValueError("generated workflow result pointers are incomplete")
    if (authoring.result_schema, image.result_schema) not in GENERATED_RESULT_SCHEMA_PAIRS:
        raise ValueError("generated workflow result schema versions are mixed")
    return authoring, image


def _prepare_prompt_staging(
    prompt_root: Path,
    workflow_id: str,
    step_key: str,
    attempt: int,
) -> Path:
    """Create job-local prompt staging beneath the operator-managed root."""
    require_catalog_runtime_directory(prompt_root, "prompt staging root is not prepared")
    workflow_root = _create_runtime_directory(prompt_root, workflow_id)
    return _create_runtime_directory(workflow_root, f"{step_key}-{attempt}")


def _create_runtime_directory(parent: Path, name: str) -> Path:
    return create_catalog_operation_directory(
        parent,
        name,
        message="prompt staging directory is unsafe",
    )


class WorkflowCatalogService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.resources = PackResourceResolver()
        self.registry = RegistryService(engine, self.settings)
        self.stimulus = KnowledgeStimulusService(engine, self.settings)
        self.local_image = FixedLocalImageProviderAdapter(self.settings)

    def bind_request(
        self,
        request: WorkflowRequest,
        *,
        definition_key: str,
        definition_version: str,
    ) -> dict[str, Any]:
        if (
            request.content_pack is None
            or request.profiles is None
            or request.registry_intent is None
        ):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID,
                "Content Pack workflow requires complete pack, profile, and registry input",
            )
        with self.sessions() as session:
            activation = session.scalar(
                select(ContentPackActivationRecord).where(
                    ContentPackActivationRecord.pack_key == request.content_pack.pack_key,
                    ContentPackActivationRecord.environment == request.content_pack.environment,
                    ContentPackActivationRecord.active.is_(True),
                )
            )
            release = (
                session.get(ContentPackReleaseRecord, activation.content_pack_release_id)
                if activation is not None
                else None
            )
            pack = (
                session.get(ContentPackRecord, release.content_pack_id)
                if release is not None
                else None
            )
            if (
                activation is None
                or release is None
                or release.state != "RELEASED"
                or pack is None
                or pack.pack_key != request.content_pack.pack_key
            ):
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_NOT_RELEASED,
                    "active released Content Pack does not resolve",
                )
            self._require_compatibility(release, definition_key, definition_version)
            self._require_item_brief_release(pack.pack_key, release.version, request)
            profile_keys = request.profiles.model_dump(mode="json")
            profiles = self._profile_snapshots(session, release, profile_keys)
            intake_ids = request.source_intake.batch_ids if request.source_intake else ()
            batches = (
                list(
                    session.scalars(
                        select(ContentIntakeBatchRecord).where(
                            ContentIntakeBatchRecord.intake_batch_id.in_(intake_ids)
                        )
                    )
                )
                if intake_ids
                else []
            )
            if len(batches) != len(set(intake_ids)) or any(
                batch.state not in {"ACCEPTED", "IMPORTED"} for batch in batches
            ):
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID,
                    "source Intake snapshot does not resolve to accepted evidence",
                )
            context = {
                "content_pack": {
                    "release_id": release.content_pack_release_id,
                    "pack_key": pack.pack_key,
                    "version": release.version,
                    "release_sha256": release.bundle_sha256,
                    "manifest_sha256": release.manifest_sha256,
                    "activation_id": activation.activation_id,
                    "environment": activation.environment,
                },
                "profiles": profiles,
                "source_intake": {"batch_ids": sorted(intake_ids)},
                "registry_intent": request.registry_intent.model_dump(
                    mode="json", exclude_none=True
                ),
                "prompt_artifacts": [],
            }
            if pack.pack_key == "generated-knowledge-item" and release.version in {
                "1.4.0",
                "1.5.0",
            }:
                binding = load_local_image_provider_binding(
                    self.settings.local_image_provider_binding
                )
                context["local_image_provider"] = binding.model_dump(mode="json")
            if request.request_name in {
                "KNOWLEDGE_ITEM_REQUEST",
                "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            }:
                assert request.item_brief is not None
                context["item_brief"] = request.item_brief.model_dump(mode="json")
                if request.stimulus_asset is not None:
                    context["stimulus_asset"] = self.stimulus.resolve(
                        request.stimulus_asset.asset_key
                    ).as_dict()
            return context

    def prepare_prompt(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        upstream: tuple[ArtifactPointer, ...],
    ) -> PreparedPrompt:
        pack_snapshot, profile_snapshot = self._snapshots(workflow, step)
        with self.sessions() as session:
            release = self._pinned_release(session, pack_snapshot)
            profile_type = ROLE_PROFILE_KEYS[step.worker_role or ""]
            profile = session.scalar(
                select(ContentPackProfileRecord).where(
                    ContentPackProfileRecord.content_pack_release_id
                    == release.content_pack_release_id,
                    ContentPackProfileRecord.profile_type == profile_type,
                    ContentPackProfileRecord.profile_key == profile_snapshot["profile_key"],
                )
            )
            if (
                profile is None
                or profile.profile_version != profile_snapshot["profile_version"]
                or profile.profile_sha256 != profile_snapshot["profile_sha256"]
                or profile.template_relative_path != profile_snapshot["template_relative_path"]
                or profile.output_schema_ref != step.result_schema
            ):
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_PROFILE_INVALID,
                    "pinned Content Pack profile is stale or incompatible",
                )
            template_path = str(profile_snapshot["template_relative_path"])
            template_bytes = self.resources.read(session, release, template_path)
        template = template_bytes.decode("utf-8")
        context = self._prompt_context(
            workflow, step, request, upstream, str(pack_snapshot["release_id"])
        )
        required = tuple(cast(list[str], profile_snapshot["required_context"]))
        rendered = render_prompt(template, context, required)
        envelope = {
            "schema_version": "1.0",
            "pack_release_id": pack_snapshot["release_id"],
            "pack_release_sha256": pack_snapshot["release_sha256"],
            "profile_key": profile_snapshot["profile_key"],
            "profile_version": profile_snapshot["profile_version"],
            "profile_sha256": profile_snapshot["profile_sha256"],
            "template_path": template_path,
            "template_sha256": sha256_bytes(template_bytes),
            "render_context_sha256": rendered.context_hash,
            "rendered_prompt_sha256": rendered.prompt_hash,
            "workflow_id": workflow.workflow_id,
            "step_run_id": step.step_run_id,
            "source_intake_batch_ids": workflow.runtime_context["source_intake"]["batch_ids"],
        }
        validate_contract("prompt-envelope", envelope)
        staging = _prepare_prompt_staging(
            self.settings.prompt_staging_root,
            workflow.workflow_id,
            step.step_key,
            step.attempt,
        )
        prompt_path = staging / "prompt.txt"
        envelope_path = staging / "prompt-envelope.json"
        prompt_path.write_text(rendered.text, encoding="utf-8")
        envelope_path.write_bytes(canonical_json_bytes(envelope))
        prompt_path.chmod(0o640)
        envelope_path.chmod(0o640)
        artifact = self.artifacts.commit_file_set(
            files={"prompt.txt": prompt_path, "prompt-envelope.json": envelope_path},
            primary_file="prompt.txt",
            artifact_type="rendered-workflow-prompt",
            idempotency_key=(
                f"prompt:{workflow.workflow_id}:{step.step_key}:{step.attempt}:"
                f"{pack_snapshot['release_sha256']}:{profile_snapshot['profile_sha256']}"
            ),
            request={
                "workflow_id": workflow.workflow_id,
                "step_run_id": step.step_run_id,
                "pack_release_id": pack_snapshot["release_id"],
            },
            result={"rendered_prompt_sha256": rendered.prompt_hash},
        )
        pointer = {
            "artifact_id": artifact.artifact_id,
            "artifact_revision_id": artifact.revision_id,
            "sha256": artifact.content_hash,
            "manifest_sha256": artifact.manifest_hash,
            "schema_ref": "eom://schemas/content-pack/prompt-envelope-v1",
        }
        return PreparedPrompt(rendered.text, pointer, envelope)

    def materialize_generated_stimulus(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> GeneratedStimulusPointer:
        authoring, image = _generated_result_pointers(artifacts)
        _, authoring_result = self._load_upstream_result(workflow, authoring)
        _, image_result = self._load_upstream_result(workflow, image)
        if not isinstance(
            authoring_result,
            GeneratedAuthoringRoleResult
            | GeneratedAuthoringRoleResultV4
            | GeneratedAuthoringRoleResultV5
            | GeneratedAuthoringRoleResultV6,
        ) or not isinstance(
            image_result,
            GeneratedImageRoleResult
            | GeneratedImageRoleResultV4
            | GeneratedImageRoleResultV5
            | GeneratedImageRoleResultV6,
        ):
            raise ValueError("generated stimulus result types are invalid")
        brief = authoring_result.output.draft.image_brief
        drawing = image_result.output.drawing
        drawing_data = drawing.model_dump(mode="json")
        for output_only in (
            "width_px",
            "height_px",
            "stroke_color",
            "point_style",
            "svg_overlay",
        ):
            drawing_data.pop(output_only, None)
        if brief.model_dump(mode="json") != drawing_data:
            raise ValueError("image worker changed the authoring image brief")
        drawing_hash = content_sha256(drawing.model_dump(mode="json"))
        if isinstance(image_result, GeneratedImageRoleResultV5 | GeneratedImageRoleResultV6):
            if not isinstance(
                drawing,
                GeneratedLineGraphDrawingV5
                | GeneratedVectorDrawingV5
                | GeneratedLineGraphDrawingV6
                | GeneratedVectorDrawingV6,
            ):
                raise ValueError("generated vector drawing type is invalid")
            if isinstance(
                drawing, GeneratedVectorDrawingV5 | GeneratedVectorDrawingV6
            ) and drawing.production_route in {
                "LOCAL_GENERATIVE_BACKGROUND",
                "HYBRID_LOCAL_GENERATIVE",
            }:
                binding_value = workflow.runtime_context.get("local_image_provider")
                if not isinstance(binding_value, dict):
                    raise ValueError("pinned local image provider binding is missing")
                binding = LocalImageProviderBinding.model_validate(binding_value)
                local_rendered = render_generated_local_vector_stimulus(
                    self.settings,
                    workflow_id=workflow.workflow_id,
                    result_revision_id=image.revision_id,
                    drawing_hash=drawing_hash,
                    drawing=drawing,
                    binding=binding,
                    adapter=self.local_image,
                )
                raster_member = (
                    RASTER_MEMBER
                    if isinstance(image_result, GeneratedImageRoleResultV6)
                    else BACKGROUND_MEMBER
                )
                files = {
                    PNG_MEMBER: local_rendered.png_path,
                    SVG_MEMBER: local_rendered.svg_path,
                    raster_member: local_rendered.background_path,
                    LOCAL_IMAGE_RECEIPT_MEMBER: local_rendered.receipt_path,
                }
                receipt = local_rendered.receipt
                result = {
                    "drawing_sha256": drawing_hash,
                    "renderer_contract": local_rendered.renderer_contract,
                    "renderer_version": local_rendered.renderer_version,
                    "renderer_sha256": local_rendered.renderer_sha256,
                    "font_family": SVG_FONT_FAMILY,
                    "font_sha256": local_rendered.font_sha256,
                    "font_families": sorted(SVG_ALLOWED_FONT_FAMILIES),
                    "font_profile": SVG_FONT_PROFILE,
                    "font_manifest_sha256": local_rendered.font_manifest_sha256,
                    "production_route": drawing.production_route,
                    **(
                        {
                            "route_reason": cast(
                                GeneratedLineGraphDrawingV6 | GeneratedVectorDrawingV6,
                                drawing,
                            ).route_reason
                        }
                        if isinstance(image_result, GeneratedImageRoleResultV6)
                        else {}
                    ),
                    "local_image_binding_sha256": binding.binding_sha256,
                    "local_image_request_sha256": local_rendered.request_sha256,
                    "local_image_receipt_sha256": receipt.receipt_sha256,
                    "local_image_unit": local_rendered.unit_name,
                    (
                        "local_image_raster_sha256"
                        if isinstance(image_result, GeneratedImageRoleResultV6)
                        else "local_image_background_sha256"
                    ): receipt.generation.output.sha256,
                    "local_image_model": receipt.generation.model.model_dump(mode="json"),
                    "local_image_runtime": receipt.generation.runtime.model_dump(mode="json"),
                    "compositor": receipt.compositor.model_dump(mode="json"),
                }
                drawing_schema = (
                    "eom.generated-vector-stimulus/4.0"
                    if isinstance(image_result, GeneratedImageRoleResultV6)
                    else "eom.generated-vector-stimulus/3.0"
                )
                file_metadata = {
                    PNG_MEMBER: {
                        "schema_ref": "eom://schemas/generated-item/stimulus-png/3.0",
                        "media_type": "image/png",
                    },
                    SVG_MEMBER: {
                        "schema_ref": "eom://schemas/generated-item/stimulus-svg-overlay/1.0",
                        "media_type": SVG_MEDIA_TYPE,
                    },
                    raster_member: {
                        "schema_ref": (
                            "eom://schemas/generated-item/semantic-raster-png/1.0"
                            if isinstance(image_result, GeneratedImageRoleResultV6)
                            else "eom://schemas/generated-item/background-png/1.0"
                        ),
                        "media_type": "image/png",
                    },
                    LOCAL_IMAGE_RECEIPT_MEMBER: {
                        "schema_ref": (
                            "eom://schemas/image-provider/local-image-composite-receipt/1.0"
                        ),
                        "media_type": "application/json",
                    },
                }
                manifest_version = (
                    "generated-item-stimulus-file-set/4.0"
                    if isinstance(image_result, GeneratedImageRoleResultV6)
                    else "generated-item-stimulus-file-set/3.0"
                )
                artifact_idempotency_key = (
                    f"generated-stimulus:{workflow.workflow_id}:{image.revision_id}:"
                    f"{drawing_hash}:{binding.binding_sha256}:{local_rendered.request_sha256}"
                )
            else:
                vector_rendered = render_generated_vector_stimulus(
                    self.settings,
                    workflow_id=workflow.workflow_id,
                    result_revision_id=image.revision_id,
                    drawing=drawing,
                )
                files = {
                    PNG_MEMBER: vector_rendered.png_path,
                    SVG_MEMBER: vector_rendered.svg_path,
                }
                result = {
                    "drawing_sha256": drawing_hash,
                    "renderer_contract": vector_rendered.renderer_contract,
                    "renderer_version": vector_rendered.renderer_version,
                    "renderer_sha256": vector_rendered.renderer_sha256,
                    "font_family": SVG_FONT_FAMILY,
                    "font_sha256": vector_rendered.font_sha256,
                    "font_families": sorted(SVG_ALLOWED_FONT_FAMILIES),
                    "font_profile": SVG_FONT_PROFILE,
                    "font_manifest_sha256": vector_rendered.font_manifest_sha256,
                    "production_route": drawing.production_route,
                    **(
                        {
                            "route_reason": cast(
                                GeneratedLineGraphDrawingV6 | GeneratedVectorDrawingV6,
                                drawing,
                            ).route_reason
                        }
                        if isinstance(image_result, GeneratedImageRoleResultV6)
                        else {}
                    ),
                }
                drawing_schema = (
                    "eom.generated-vector-stimulus/3.0"
                    if isinstance(image_result, GeneratedImageRoleResultV6)
                    else "eom.generated-vector-stimulus/2.0"
                )
                file_metadata = {
                    PNG_MEMBER: {
                        "schema_ref": "eom://schemas/generated-item/stimulus-png/2.0",
                        "media_type": "image/png",
                    },
                    SVG_MEMBER: {
                        "schema_ref": "eom://schemas/generated-item/stimulus-svg/2.0",
                        "media_type": SVG_MEDIA_TYPE,
                    },
                }
                manifest_version = "generated-item-stimulus-file-set/2.0"
                artifact_idempotency_key = (
                    f"generated-stimulus:{workflow.workflow_id}:{image.revision_id}:"
                    f"{SVG_RENDERER_CONTRACT}:{drawing_hash}"
                )
            expected_file_sha256 = {name: sha256_file(source) for name, source in files.items()}
        else:
            if not isinstance(drawing, GeneratedLineGraphDrawing):
                raise ValueError("generated legacy drawing type is invalid")
            source = render_generated_stimulus(
                self.settings,
                workflow_id=workflow.workflow_id,
                result_revision_id=image.revision_id,
                drawing=drawing,
            )
            files = {PNG_MEMBER: source}
            result = {"drawing_sha256": drawing_hash}
            file_metadata = None
            expected_file_sha256 = None
            manifest_version = "catalog-file-set/1.0"
            artifact_idempotency_key = (
                f"generated-stimulus:{workflow.workflow_id}:{image.revision_id}"
            )
            drawing_schema = "eom.generated-line-graph/1.0"
        artifact = self.artifacts.commit_file_set(
            files=files,
            primary_file=PNG_MEMBER,
            artifact_type="generated-item-stimulus",
            idempotency_key=artifact_idempotency_key,
            request={
                "workflow_id": workflow.workflow_id,
                "source_result_revision_id": image.revision_id,
                "drawing_schema": drawing_schema,
            },
            result=result,
            file_metadata=file_metadata,
            manifest_version=manifest_version,
            expected_file_sha256=expected_file_sha256,
        )
        if expected_file_sha256 is not None:
            if file_metadata is None:
                raise ValueError("generated vector stimulus metadata is missing")
            _validate_generated_vector_artifact_manifest(
                artifact.manifest,
                expected_file_sha256=expected_file_sha256,
                file_metadata=file_metadata,
                content_hash=artifact.content_hash,
                manifest_version=manifest_version,
            )
        return GeneratedStimulusPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            artifact_member=PNG_MEMBER,
            sha256=artifact.content_hash,
            media_type="image/png",
            width_px=PNG_WIDTH,
            height_px=PNG_HEIGHT,
            source_result_revision_id=image.revision_id,
        )

    def register_workflow(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> RegistrationOutcome:
        pack_snapshot = cast(dict[str, Any], workflow.runtime_context["content_pack"])
        intent = cast(dict[str, Any], workflow.runtime_context["registry_intent"])
        source_intake = cast(dict[str, Any], workflow.runtime_context["source_intake"])
        registration_key = "registry-" + content_sha256(
            {
                "workflow_id": workflow.workflow_id,
                "step_key": step.step_key,
                "attempt": step.attempt,
                "intent": intent,
                "pack_release_sha256": pack_snapshot["release_sha256"],
            }
        ).removeprefix("sha256:")
        components: tuple[ComponentPointer, ...] = tuple(
            ComponentPointer(
                component_type=cast(ComponentType, COMPONENT_TYPES[pointer.step_key]),
                ordinal=0,
                schema_ref=pointer.result_schema,
                media_type="application/json",
                artifact_id=pointer.logical_artifact_id,
                artifact_revision_id=pointer.revision_id,
                sha256=pointer.content_hash,
                logical_name=f"{pointer.step_key}-result",
            )
            for pointer in artifacts
            if pointer.step_key in COMPONENT_TYPES
        )
        tags: tuple[str, ...]
        if request.request_name in {
            "KNOWLEDGE_ITEM_REQUEST",
            "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        }:
            components = (*components, self._knowledge_item_content(workflow, request, artifacts))
            assert request.item_brief is not None
            brief = request.item_brief
            item_type_key = "eom-template-multiple-choice"
            taxonomy = "GENERAL_SCIENCE"
            tags = ("EOM_QUESTION_TEMPLATE", "GENERAL_KNOWLEDGE_GENERATED")
            source_mode = self._knowledge_source_mode(request)
            metadata_schema = "eom://metadata/general-knowledge-item@1.0"
            metadata: dict[str, Any] = {
                "item_type_key": item_type_key,
                "primary_taxonomy_ref": taxonomy,
                "difficulty_band": brief.difficulty,
                "tags": list(tags),
                "subject": brief.subject,
                "topic": brief.topic,
                "task_type": brief.task_type,
                "knowledge_source_mode": source_mode,
                "request_sha256": brief.original_request_sha256,
            }
            if isinstance(brief, ItemBriefV2):
                metadata_schema = "eom://metadata/general-knowledge-item@2.0"
                metadata.update(
                    {
                        "authoring_guidance_sha256": brief.authoring_guidance_sha256,
                        "curriculum_scope": (
                            brief.curriculum_scope.model_dump(mode="json")
                            if brief.curriculum_scope is not None
                            else None
                        ),
                    }
                )
        else:
            item_type_key = "generic-multiple-choice"
            taxonomy = "PLACEHOLDER_TAXONOMY"
            tags = ("PLACEHOLDER_TAG",)
            metadata_schema = "eom://metadata/generic-placeholder@1.0"
            metadata = {
                "item_type_key": item_type_key,
                "primary_taxonomy_ref": taxonomy,
                "difficulty_band": "PLACEHOLDER_DIFFICULTY",
                "tags": list(tags),
            }
        revision = self.registry.register(
            RegistrationRequest(
                mode=intent["mode"],
                registration_key=registration_key,
                item_id=intent.get("item_id"),
                base_revision_id=intent.get("base_revision_id"),
                content_pack_release_id=pack_snapshot["release_id"],
                workflow_id=workflow.workflow_id,
                workflow_definition_key=workflow.definition_key,
                workflow_definition_version=workflow.definition_version,
                source_workflow_step_run_id=step.step_run_id,
                source_intake_batch_ids=tuple(source_intake["batch_ids"]),
                item_type_key=item_type_key,
                primary_taxonomy_ref=taxonomy,
                difficulty_band=(
                    request.item_brief.difficulty
                    if request.item_brief is not None
                    else "PLACEHOLDER_DIFFICULTY"
                ),
                tag_keys=tags,
                metadata_schema_ref=metadata_schema,
                metadata=metadata,
                components=components,
                created_by=workflow.created_actor_id,
            )
        )
        return RegistrationOutcome(
            item_id=revision.item_id,
            item_revision_id=revision.item_revision_id,
            revision_number=revision.revision_number,
            manifest_artifact_id=revision.manifest_artifact_id,
            manifest_artifact_revision_id=revision.manifest_artifact_revision_id,
            manifest_sha256=revision.manifest_sha256,
        )

    @staticmethod
    def _require_compatibility(
        release: ContentPackReleaseRecord, definition_key: str, definition_version: str
    ) -> None:
        compatible = any(
            item.get("key") == definition_key and definition_version in item.get("versions", [])
            for item in release.compatibility_json.get("workflow_definitions", [])
            if isinstance(item, dict)
        )
        if not compatible:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_COMPATIBILITY_FAILED,
                "Content Pack does not allow the workflow definition snapshot",
            )

    @staticmethod
    def _require_item_brief_release(
        pack_key: str, release_version: str, request: WorkflowRequest
    ) -> None:
        if request.item_brief is None:
            return
        is_v2 = isinstance(request.item_brief, ItemBriefV2)
        expects_v2 = pack_key == "generated-knowledge-item" and release_version in {
            "1.2.0",
            "1.3.0",
            "1.4.0",
            "1.5.0",
        }
        if expects_v2 != is_v2:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_COMPATIBILITY_FAILED,
                "item brief version does not match the immutable Content Pack release",
            )

    @staticmethod
    def _profile_snapshots(
        session: Session,
        release: ContentPackReleaseRecord,
        requested: dict[str, str],
    ) -> dict[str, Any]:
        rows = list(
            session.scalars(
                select(ContentPackProfileRecord).where(
                    ContentPackProfileRecord.content_pack_release_id
                    == release.content_pack_release_id
                )
            )
        )
        lookup = {(row.profile_type, row.profile_key): row for row in rows}
        snapshots: dict[str, Any] = {}
        for profile_type, profile_key in requested.items():
            row = lookup.get((profile_type, profile_key))
            if row is None:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_PROFILE_INVALID,
                    "requested Content Pack profile does not resolve",
                )
            snapshots[profile_type] = {
                "profile_key": row.profile_key,
                "profile_version": row.profile_version,
                "profile_sha256": row.profile_sha256,
                "template_relative_path": row.template_relative_path,
                "input_schema_ref": row.input_schema_ref,
                "output_schema_ref": row.output_schema_ref,
                "required_context": row.compiled_profile_json["required_context"],
            }
        return snapshots

    @staticmethod
    def _snapshots(
        workflow: WorkflowInstanceRecord, step: WorkflowStepRunRecord
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        pack = workflow.runtime_context.get("content_pack")
        profiles = workflow.runtime_context.get("profiles")
        profile_type = ROLE_PROFILE_KEYS.get(step.worker_role or "")
        if not isinstance(pack, dict) or not isinstance(profiles, dict) or profile_type is None:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_PROFILE_INVALID,
                "workflow Content Pack snapshot is missing",
            )
        profile = profiles.get(profile_type)
        if not isinstance(profile, dict):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_PROFILE_INVALID,
                "workflow profile snapshot is missing",
            )
        return cast(dict[str, Any], pack), cast(dict[str, Any], profile)

    def _prompt_context(
        self,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        upstream: tuple[ArtifactPointer, ...],
        release_id: str,
    ) -> dict[str, Any]:
        upstream_context: dict[str, dict[str, str]] = {}
        for pointer in upstream:
            if pointer.step_key in upstream_context:
                raise ValueError("duplicate upstream step pointer")
            result, _ = self._load_upstream_result(workflow, pointer)
            upstream_context[pointer.step_key] = {
                "artifact_id": pointer.logical_artifact_id,
                "artifact_revision_id": pointer.revision_id,
                "sha256": pointer.content_hash,
                "result_json": canonical_json_bytes(result).decode("utf-8"),
            }
        context: dict[str, Any] = {
            "workflow": {"id": workflow.workflow_id, "step_key": step.step_key},
            "request": {
                "request_name": request.request_name,
                "image_mode": request.image_mode,
            },
            "upstream": upstream_context,
            "pack": {"release_id": release_id},
        }
        if request.item_brief is not None:
            brief = request.item_brief.model_dump(mode="json")
            if isinstance(request.item_brief, ItemBriefV2):
                reviewed_brief = request.item_brief.model_dump(mode="json")
                reviewed_brief["knowledge_source_mode"] = self._knowledge_source_mode(request)
                brief["reviewed_item_brief_json"] = canonical_json_bytes(reviewed_brief).decode(
                    "utf-8"
                )
            context["brief"] = brief
        stimulus = workflow.runtime_context.get("stimulus_asset")
        if isinstance(stimulus, dict):
            context["stimulus"] = stimulus
        generated = workflow.runtime_context.get("generated_stimulus")
        if isinstance(generated, dict):
            context["generated_stimulus"] = generated
        provider = workflow.runtime_context.get("local_image_provider")
        if isinstance(provider, dict):
            validated_provider = LocalImageProviderBinding.model_validate(provider)
            provider_context = validated_provider.model_dump(mode="json")
            # The provider contract legitimately contains a floating-point sampler value. EOM
            # message hashing rejects floats, so expose only its already validated canonical JSON
            # data boundary to prompts; execution continues to use the pinned typed runtime value.
            context["local_image_provider"] = {
                "reviewed_binding_json": content_json_bytes(provider_context).decode("utf-8")
            }
        return context

    def _knowledge_item_content(
        self,
        workflow: WorkflowInstanceRecord,
        request: WorkflowRequest,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> ComponentPointer:
        if request.request_name == "GENERATED_KNOWLEDGE_ITEM_REQUEST":
            return self._generated_knowledge_item_content(workflow, request, artifacts)
        authoring = next(
            (
                pointer
                for pointer in artifacts
                if pointer.step_key == "authoring"
                and pointer.result_schema == "authoring-result@2.0"
            ),
            None,
        )
        if authoring is None:
            raise ValueError("knowledge workflow has no structured authoring result")
        _, parsed = self._load_upstream_result(workflow, authoring)
        if not isinstance(parsed, KnowledgeAuthoringRoleResult):
            raise ValueError("knowledge authoring result type is invalid")
        content: AssessmentItemContent = parsed.output.content
        validate_eom_question_template_content(content)
        expected_stimulus = workflow.runtime_context.get("stimulus_asset")
        image = next((block for block in content.body if isinstance(block, ImageBlock)), None)
        if not isinstance(expected_stimulus, dict) or image is None:
            raise ValueError("knowledge workflow stimulus snapshot is missing")
        actual_pointer = image.artifact.model_dump(mode="json")
        expected_pointer = {
            key: expected_stimulus[key]
            for key in (
                "artifact_id",
                "artifact_revision_id",
                "artifact_member",
                "sha256",
                "media_type",
            )
        }
        if actual_pointer != expected_pointer:
            raise ValueError("authoring result changed the pinned stimulus pointer")
        content_data = content.model_dump(mode="json")
        staged, staged_hash = stage_registry_item_content(self.settings, content_data)
        expected_hash = content_sha256(content_data)
        if staged_hash != expected_hash:
            raise ValueError("knowledge item content changed during staging")
        artifact = self.artifacts.commit_file_set(
            files={ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged},
            primary_file=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            artifact_type="assessment-item-content",
            idempotency_key=f"workflow-item-content:{workflow.workflow_id}:{expected_hash}",
            request={"workflow_id": workflow.workflow_id, "schema_version": "1.0"},
            result={"content_sha256": expected_hash},
            file_metadata={
                ASSESSMENT_ITEM_CONTENT_FILE_NAME: {
                    "schema_ref": ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
                    "media_type": ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
                }
            },
        )
        return ComponentPointer(
            component_type="ITEM_CONTENT",
            ordinal=0,
            schema_ref=ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
            media_type=ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            sha256=artifact.content_hash,
            logical_name=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            metadata={
                "authoring_artifact_revision_id": authoring.revision_id,
                **self._brief_provenance_metadata(request),
            },
        )

    def _generated_knowledge_item_content(
        self,
        workflow: WorkflowInstanceRecord,
        request: WorkflowRequest,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> ComponentPointer:
        authoring, image_result = _generated_result_pointers(artifacts)
        _, parsed = self._load_upstream_result(workflow, authoring)
        if not isinstance(
            parsed,
            GeneratedAuthoringRoleResult
            | GeneratedAuthoringRoleResultV4
            | GeneratedAuthoringRoleResultV5
            | GeneratedAuthoringRoleResultV6,
        ):
            raise ValueError("generated authoring result type is invalid")
        stimulus = workflow.runtime_context.get("generated_stimulus")
        if (
            not isinstance(stimulus, dict)
            or stimulus.get("source_result_revision_id") != image_result.revision_id
            or stimulus.get("media_type") != "image/png"
            or stimulus.get("width_px") != PNG_WIDTH
            or stimulus.get("height_px") != PNG_HEIGHT
        ):
            raise ValueError("generated stimulus pointer is missing or stale")
        pointer = MediaArtifactPointer.model_validate(
            {
                key: stimulus[key]
                for key in (
                    "artifact_id",
                    "artifact_revision_id",
                    "artifact_member",
                    "sha256",
                    "media_type",
                )
            }
        )
        self.artifacts.verify_file_pointer(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            content_hash=pointer.sha256,
            member=pointer.artifact_member,
        )
        draft = parsed.output.draft
        content = AssessmentItemContent(
            schema_version="1.0",
            locale=draft.locale,
            title=draft.title,
            body=(
                draft.stem,
                draft.data_table,
                ImageBlock(
                    block_id=draft.image_brief.block_id,
                    purpose="stimulus",
                    artifact=pointer,
                    alt_text=draft.image_brief.alt_text,
                    width_px=PNG_WIDTH,
                    height_px=PNG_HEIGHT,
                ),
                draft.equation,
                draft.prompt,
                draft.statements,
            ),
            interaction=draft.interaction,
            solution=draft.solution,
            score=draft.score,
        )
        validate_eom_question_template_content(content)
        content_data = content.model_dump(mode="json")
        staged, staged_hash = stage_registry_item_content(self.settings, content_data)
        expected_hash = content_sha256(content_data)
        if staged_hash != expected_hash:
            raise ValueError("generated item content changed during staging")
        artifact = self.artifacts.commit_file_set(
            files={ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged},
            primary_file=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            artifact_type="assessment-item-content",
            idempotency_key=f"workflow-item-content:{workflow.workflow_id}:{expected_hash}",
            request={"workflow_id": workflow.workflow_id, "schema_version": "1.0"},
            result={"content_sha256": expected_hash},
            file_metadata={
                ASSESSMENT_ITEM_CONTENT_FILE_NAME: {
                    "schema_ref": ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
                    "media_type": ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
                }
            },
        )
        return ComponentPointer(
            component_type="ITEM_CONTENT",
            ordinal=0,
            schema_ref=ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
            media_type=ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            sha256=artifact.content_hash,
            logical_name=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            metadata={
                "authoring_artifact_revision_id": authoring.revision_id,
                "image_artifact_revision_id": pointer.artifact_revision_id,
                "image_result_revision_id": image_result.revision_id,
                **self._brief_provenance_metadata(request),
            },
        )

    def _brief_provenance_metadata(self, request: WorkflowRequest) -> dict[str, Any]:
        brief = request.item_brief
        metadata: dict[str, Any] = {
            "knowledge_source_mode": self._knowledge_source_mode(request),
            "delivery_profile": "eom-question-template-v1",
            "request_sha256": brief.original_request_sha256 if brief is not None else "",
        }
        if isinstance(brief, ItemBriefV2):
            metadata.update(
                {
                    "authoring_guidance_sha256": brief.authoring_guidance_sha256,
                    "curriculum_scope": (
                        brief.curriculum_scope.model_dump(mode="json")
                        if brief.curriculum_scope is not None
                        else None
                    ),
                }
            )
        return metadata

    @staticmethod
    def _knowledge_source_mode(
        request: WorkflowRequest,
    ) -> Literal["general_model_knowledge", "graph_grounded"]:
        if (
            isinstance(request.item_brief, ItemBriefV2)
            and request.educational_retrieval is not None
        ):
            return GRAPH_GROUNDED_KNOWLEDGE_SOURCE_MODE
        return GENERAL_KNOWLEDGE_SOURCE_MODE

    def _load_upstream_result(
        self,
        workflow: WorkflowInstanceRecord,
        pointer: ArtifactPointer,
    ) -> tuple[dict[str, Any], RoleResult]:
        """Resolve and bind one schema-valid result to its exact workflow/job/artifact pointer."""

        result = self.artifacts.load_json_revision(
            artifact_id=pointer.logical_artifact_id,
            revision_id=pointer.revision_id,
            content_hash=pointer.content_hash,
        )
        role = ROLE_BY_RESULT_SCHEMA.get(pointer.result_schema)
        if role is None:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_PROFILE_INVALID,
                "upstream result schema is unsupported",
            )
        parsed = validate_role_result(result, role, pointer.result_schema)
        if (
            parsed.workflow_id != workflow.workflow_id
            or parsed.job_id != pointer.job_id
            or parsed.artifact.logical_artifact_id != pointer.logical_artifact_id
            or parsed.artifact.revision_id != pointer.revision_id
        ):
            raise ValueError("upstream result identity does not match its immutable pointer")
        return result, parsed

    @staticmethod
    def _pinned_release(session: Session, snapshot: dict[str, Any]) -> ContentPackReleaseRecord:
        release = session.get(ContentPackReleaseRecord, snapshot.get("release_id"))
        if (
            release is None
            or release.state not in {"RELEASED", "DEPRECATED"}
            or release.version != snapshot.get("version")
            or release.bundle_sha256 != snapshot.get("release_sha256")
            or release.manifest_sha256 != snapshot.get("manifest_sha256")
        ):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID,
                "pinned Content Pack release is stale or mismatched",
            )
        return release
