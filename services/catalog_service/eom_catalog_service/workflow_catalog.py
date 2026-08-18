"""Content Pack binding, prompt provenance, and deterministic workflow registration."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Literal, cast

from eom_catalog_contracts import validate_contract
from eom_content_pack import ContentPackError, ContentPackErrorCode, render_prompt
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_item_registry import ComponentPointer, RegistrationRequest
from eom_orchestrator.database import build_session_factory
from eom_workflow import ArtifactPointer, WorkflowRequest
from eom_workflow_runner.catalog_port import PreparedPrompt, RegistrationOutcome
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
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
ComponentType = Literal["UPPER_STEM", "IMAGE_SPEC", "REVIEW_REPORT", "METADATA"]


def _prepare_prompt_staging(
    prompt_root: Path,
    workflow_id: str,
    step_key: str,
    attempt: int,
) -> Path:
    """Create job-local prompt staging beneath the operator-managed root."""
    _require_runtime_directory(prompt_root, "prompt staging root is not prepared")
    workflow_root = _create_runtime_directory(prompt_root, workflow_id)
    return _create_runtime_directory(workflow_root, f"{step_key}-{attempt}")


def _create_runtime_directory(parent: Path, name: str) -> Path:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise OSError("prompt staging path component is invalid")
    path = parent / name
    created = False
    try:
        path.mkdir(mode=0o750, parents=False)
        created = True
    except FileExistsError:
        pass
    if created:
        path.chmod(0o750)
    _require_runtime_directory(path, "prompt staging directory is unsafe")
    return path


def _require_runtime_directory(path: Path, message: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OSError(message) from exc
    valid = (
        not path.is_symlink()
        and stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and metadata.st_gid == os.getegid()
        and stat.S_IMODE(metadata.st_mode) == 0o750
        and os.access(path, os.W_OK | os.X_OK)
    )
    if not valid:
        raise OSError(message)


class WorkflowCatalogService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.resources = PackResourceResolver()
        self.registry = RegistryService(engine, self.settings)

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
            or request.source_intake is None
            or request.registry_intent is None
        ):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID,
                "workflow 1.1 requires complete Content Pack and registry input",
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
            profile_keys = request.profiles.model_dump(mode="json")
            profiles = self._profile_snapshots(session, release, profile_keys)
            batches = list(
                session.scalars(
                    select(ContentIntakeBatchRecord).where(
                        ContentIntakeBatchRecord.intake_batch_id.in_(
                            request.source_intake.batch_ids
                        )
                    )
                )
            )
            if len(batches) != len(set(request.source_intake.batch_ids)) or any(
                batch.state not in {"ACCEPTED", "IMPORTED"} for batch in batches
            ):
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID,
                    "source Intake snapshot does not resolve to accepted evidence",
                )
            return {
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
                "source_intake": {"batch_ids": sorted(request.source_intake.batch_ids)},
                "registry_intent": request.registry_intent.model_dump(
                    mode="json", exclude_none=True
                ),
                "prompt_artifacts": [],
            }

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
        components = tuple(
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
                item_type_key="generic-multiple-choice",
                primary_taxonomy_ref="PLACEHOLDER_TAXONOMY",
                difficulty_band="PLACEHOLDER_DIFFICULTY",
                tag_keys=("PLACEHOLDER_TAG",),
                metadata_schema_ref="eom://metadata/generic-placeholder@1.0",
                metadata={
                    "item_type_key": "generic-multiple-choice",
                    "primary_taxonomy_ref": "PLACEHOLDER_TAXONOMY",
                    "difficulty_band": "PLACEHOLDER_DIFFICULTY",
                    "tags": ["PLACEHOLDER_TAG"],
                },
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

    @staticmethod
    def _prompt_context(
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        upstream: tuple[ArtifactPointer, ...],
        release_id: str,
    ) -> dict[str, Any]:
        upstream_context = {
            pointer.step_key: {"artifact_id": pointer.logical_artifact_id} for pointer in upstream
        }
        return {
            "workflow": {"id": workflow.workflow_id, "step_key": step.step_key},
            "request": {
                "request_name": request.request_name,
                "image_mode": request.image_mode,
            },
            "upstream": upstream_context,
            "pack": {"release_id": release_id},
        }

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
