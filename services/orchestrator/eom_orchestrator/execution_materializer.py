"""Fail-closed immutable-bundle materialization into one worker workspace."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from eom_catalog_contracts import (
    EvidenceBundleManifestV2,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    KnowledgeArtifactMemberPointer,
)
from eom_catalog_contracts import validate_contract as validate_catalog_contract
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import (
    CodexImageInputManifest,
    CodexInvocation,
    InstructionBundleManifest,
    ReferenceBundleManifest,
    ResolvedExecutionPlan,
    ResolvedExecutionPlanV2,
    ResolvedExecutionPlanV3,
    ResolvedExecutionPlanV4,
    ResolvedExecutionPlanV5,
    ResolvedStepExecutionV3,
    validate_control_contract,
)
from eom_workflow.control_plane import (
    BundleRevisionPointer,
    ControlArtifactPointer,
    ResolvedStepExecution,
)
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    resolve_control_artifact_pointer,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord

MAX_MARKDOWN_MEMBER_BYTES = 2 * 1024 * 1024
MAX_MATERIALIZED_BYTES = 32 * 1024 * 1024
MAX_ANALYSIS_MATERIALIZED_BYTES = 132 * 1024 * 1024
COPY_BUFFER_BYTES = 1024 * 1024
WORKSPACE_MODE = 0o2770
MATERIALIZED_DIRECTORY_MODE = 0o750
MATERIALIZED_FILE_MODE = 0o640


@dataclass(frozen=True)
class MaterializedExecution:
    """Sanitized evidence and local paths for one prepared fixed-worker invocation."""

    plan_id: str
    plan_sha256: str
    step_key: str
    model: str
    reasoning_effort: str
    instruction_bundle_revision_id: str
    instruction_manifest_sha256: str
    reference_bundle_revision_id: str | None
    reference_manifest_sha256: str | None
    agents_sha256: str
    invocation_sha256: str
    image_input_manifest_sha256: str | None
    materialized_member_count: int
    materialized_bytes: int
    invocation_path: Path
    source_artifact_revision_id: str | None = None
    source_sha256: str | None = None
    evidence_bundle_revision_id: str | None = None
    evidence_manifest_sha256: str | None = None
    evidence_context_sha256: str | None = None

    def event_data(self) -> dict[str, str | int | None]:
        """Return the bounded path-free projection safe for an append-only job event."""

        return {
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "step_key": self.step_key,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "instruction_bundle_revision_id": self.instruction_bundle_revision_id,
            "instruction_manifest_sha256": self.instruction_manifest_sha256,
            "reference_bundle_revision_id": self.reference_bundle_revision_id,
            "reference_manifest_sha256": self.reference_manifest_sha256,
            "agents_sha256": self.agents_sha256,
            "invocation_sha256": self.invocation_sha256,
            "image_input_manifest_sha256": self.image_input_manifest_sha256,
            "materialized_member_count": self.materialized_member_count,
            "materialized_bytes": self.materialized_bytes,
            "source_artifact_revision_id": self.source_artifact_revision_id,
            "source_sha256": self.source_sha256,
            "evidence_bundle_revision_id": self.evidence_bundle_revision_id,
            "evidence_manifest_sha256": self.evidence_manifest_sha256,
            "evidence_context_sha256": self.evidence_context_sha256,
        }


def materialize_execution_step(
    session: Session,
    *,
    plan_id: str,
    step_key: str,
    workspace: Path,
    canonical_artifact_root: Path,
    worker_group_id: int,
    authorized_artifact_revision_ids: frozenset[str],
) -> MaterializedExecution:
    """Materialize one exact plan step without resolving any mutable current pointer."""

    _require_directory(workspace, group_id=worker_group_id, mode=WORKSPACE_MODE)
    artifact_root = _canonical_root(canonical_artifact_root)
    plan_record = session.get(ResolvedExecutionPlanRecord, plan_id)
    if plan_record is None:
        raise ControlPlaneError("CONTROL_PLAN_MISSING", "resolved execution plan is missing")
    plan_schema_version = plan_record.canonical_document.get("schema_version")
    is_analysis = plan_schema_version in {
        "resolved-execution-plan/2.0",
        "resolved-execution-plan/4.0",
        "resolved-execution-plan/5.0",
    }
    plan: (
        ResolvedExecutionPlan
        | ResolvedExecutionPlanV2
        | ResolvedExecutionPlanV3
        | ResolvedExecutionPlanV4
        | ResolvedExecutionPlanV5
    )
    if plan_schema_version == "resolved-execution-plan/2.0":
        plan = ResolvedExecutionPlanV2.model_validate(plan_record.canonical_document)
    elif plan_schema_version == "resolved-execution-plan/3.0":
        plan = ResolvedExecutionPlanV3.model_validate(plan_record.canonical_document)
    elif plan_schema_version == "resolved-execution-plan/4.0":
        plan = ResolvedExecutionPlanV4.model_validate(plan_record.canonical_document)
    elif plan_schema_version == "resolved-execution-plan/5.0":
        plan = ResolvedExecutionPlanV5.model_validate(plan_record.canonical_document)
    else:
        plan = ResolvedExecutionPlan.model_validate(plan_record.canonical_document)
    if plan.plan_sha256 != plan_record.plan_sha256:
        raise ControlPlaneError("CONTROL_PLAN_HASH_MISMATCH", "resolved plan record is stale")
    matching = [step for step in plan.steps if step.step_key == step_key]
    if len(matching) != 1:
        raise ControlPlaneError("CONTROL_PLAN_STEP_MISSING", "resolved execution step is missing")
    step = matching[0]

    instruction = _instruction_manifest(
        session,
        step,
        authorized_artifact_revision_ids=authorized_artifact_revision_ids,
    )
    reference = _reference_manifest(
        session,
        step,
        authorized_artifact_revision_ids=authorized_artifact_revision_ids,
    )
    instruction_docs: list[tuple[str, str, bytes]] = []
    total_bytes = 0
    member_count = 0
    for component in sorted(
        instruction.components,
        key=lambda item: (0 if item.layer == "PLATFORM" else 1, item.relative_path),
    ):
        payload = _materialize_member(
            session,
            pointer=component.artifact,
            relative_path=component.relative_path,
            workspace=workspace,
            artifact_root=artifact_root,
            worker_group_id=worker_group_id,
            authorized_artifact_revision_ids=authorized_artifact_revision_ids,
        )
        total_bytes += len(payload)
        member_count += 1
        _require_total_size(total_bytes, analysis=is_analysis)
        instruction_docs.append((component.layer, component.relative_path, payload))
    layers = {layer for layer, _, _ in instruction_docs}
    if layers != {"PLATFORM", "ROLE"}:
        raise ControlPlaneError(
            "CONTROL_INSTRUCTION_LAYERS_INVALID",
            "instruction bundle requires platform and role components",
        )

    if reference is not None:
        for entry in sorted(reference.entries, key=lambda item: item.relative_path):
            payload = _materialize_member(
                session,
                pointer=entry.artifact,
                relative_path=entry.relative_path,
                workspace=workspace,
                artifact_root=artifact_root,
                worker_group_id=worker_group_id,
                authorized_artifact_revision_ids=authorized_artifact_revision_ids,
            )
            total_bytes += len(payload)
            member_count += 1
            _require_total_size(total_bytes, analysis=is_analysis)

    source_artifact_revision_id: str | None = None
    source_sha256: str | None = None
    evidence_bundle_revision_id: str | None = None
    evidence_manifest_sha256: str | None = None
    evidence_context_sha256: str | None = None
    if isinstance(plan, ResolvedExecutionPlanV2):
        payload = _materialize_analysis_source(
            session,
            plan=plan,
            workspace=workspace,
            artifact_root=artifact_root,
            worker_group_id=worker_group_id,
            authorized_artifact_revision_ids=authorized_artifact_revision_ids,
        )
        total_bytes += len(payload)
        member_count += 1
        _require_total_size(total_bytes, analysis=True)
        source_artifact_revision_id = plan.source_artifact_revision_id
        source_sha256 = plan.source_sha256
    elif isinstance(plan, (ResolvedExecutionPlanV4, ResolvedExecutionPlanV5)):
        document_bytes, document_members = _materialize_analysis_document_source(
            session,
            plan=plan,
            workspace=workspace,
            artifact_root=artifact_root,
            worker_group_id=worker_group_id,
            authorized_artifact_revision_ids=authorized_artifact_revision_ids,
        )
        total_bytes += document_bytes
        member_count += document_members
        _require_total_size(total_bytes, analysis=True)
        source_artifact_revision_id = plan.document_source.artifact_member.artifact_revision_id
        source_sha256 = plan.document_source.artifact_member.sha256
    elif isinstance(plan, ResolvedExecutionPlanV3):
        assert isinstance(step, ResolvedStepExecutionV3)
        if step.evidence_access == "EVIDENCE_CONTEXT":
            payload = _materialize_evidence_context(
                session,
                plan=plan,
                workspace=workspace,
                artifact_root=artifact_root,
                worker_group_id=worker_group_id,
                authorized_artifact_revision_ids=authorized_artifact_revision_ids,
            )
            total_bytes += len(payload)
            member_count += 1
            _require_total_size(total_bytes, analysis=False)
            evidence_bundle_revision_id = plan.evidence_bundle_revision_id
            evidence_manifest_sha256 = plan.evidence_manifest_sha256
            evidence_context_sha256 = plan.evidence_context_artifact.sha256

    agents_bytes = _agents_document(instruction_docs)
    total_bytes += len(agents_bytes)
    _require_total_size(total_bytes, analysis=is_analysis)
    agents_path = workspace / "AGENTS.md"
    _write_exclusive(agents_path, agents_bytes, group_id=worker_group_id)

    image_input_manifest_sha256: str | None = None
    if isinstance(plan, ResolvedExecutionPlanV5):
        image_manifest_document: dict[str, object] = {
            "schema_version": "codex-image-input-manifest/1.0",
            "plan_id": plan.plan_id,
            "images": [
                {
                    "physical_page": member.physical_page,
                    "relative_path": member.materialized_path,
                    "media_type": "image/png",
                    "sha256": member.sha256,
                    "bytes": member.bytes,
                    "width_pixels": member.width_pixels,
                    "height_pixels": member.height_pixels,
                }
                for member in plan.document_source.materialization_members
                if member.member_kind == "PAGE_IMAGE"
            ],
            "manifest_sha256": "sha256:" + "0" * 64,
        }
        image_manifest_document["manifest_sha256"] = content_sha256(
            {
                key: value
                for key, value in image_manifest_document.items()
                if key != "manifest_sha256"
            }
        )
        validate_control_contract("codex-image-input-manifest", image_manifest_document)
        image_manifest = CodexImageInputManifest.model_validate(image_manifest_document)
        image_manifest_bytes = canonical_json_bytes(image_manifest) + b"\n"
        total_bytes += len(image_manifest_bytes)
        member_count += 1
        _require_total_size(total_bytes, analysis=True)
        _write_exclusive(
            workspace / "codex-image-inputs.json",
            image_manifest_bytes,
            group_id=worker_group_id,
        )
        image_input_manifest_sha256 = image_manifest.manifest_sha256

    invocation_document: dict[str, object] = {
        "schema_version": "codex-invocation/1.0",
        "plan_id": plan.plan_id,
        "step_key": step.step_key,
        "model": step.model,
        "reasoning_effort": step.reasoning_effort,
        "invocation_sha256": "sha256:" + "0" * 64,
    }
    invocation_document["invocation_sha256"] = content_sha256(
        {key: value for key, value in invocation_document.items() if key != "invocation_sha256"}
    )
    validate_control_contract("codex-invocation", invocation_document)
    invocation = CodexInvocation.model_validate(invocation_document)
    invocation_path = workspace / "codex-invocation.json"
    invocation_bytes = canonical_json_bytes(invocation) + b"\n"
    total_bytes += len(invocation_bytes)
    _require_total_size(total_bytes, analysis=is_analysis)
    _write_exclusive(
        invocation_path,
        invocation_bytes,
        group_id=worker_group_id,
    )
    return MaterializedExecution(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        step_key=step.step_key,
        model=step.model,
        reasoning_effort=str(step.reasoning_effort),
        instruction_bundle_revision_id=step.instruction_bundle.bundle_revision_id,
        instruction_manifest_sha256=step.instruction_bundle.manifest_sha256,
        reference_bundle_revision_id=(
            step.reference_bundle.bundle_revision_id if step.reference_bundle is not None else None
        ),
        reference_manifest_sha256=(
            step.reference_bundle.manifest_sha256 if step.reference_bundle is not None else None
        ),
        agents_sha256=sha256_bytes(agents_bytes),
        invocation_sha256=invocation.invocation_sha256,
        image_input_manifest_sha256=image_input_manifest_sha256,
        materialized_member_count=member_count,
        materialized_bytes=total_bytes,
        invocation_path=invocation_path,
        source_artifact_revision_id=source_artifact_revision_id,
        source_sha256=source_sha256,
        evidence_bundle_revision_id=evidence_bundle_revision_id,
        evidence_manifest_sha256=evidence_manifest_sha256,
        evidence_context_sha256=evidence_context_sha256,
    )


def authorized_execution_artifact_revisions(
    session: Session, *, plan_id: str, step_key: str
) -> frozenset[str]:
    """Derive the exact materialization allowlist from one immutable plan and its manifests."""

    plan_record = session.get(ResolvedExecutionPlanRecord, plan_id)
    if plan_record is None:
        raise ControlPlaneError("CONTROL_PLAN_MISSING", "resolved execution plan is missing")
    if plan_record.canonical_document.get("schema_version") == "resolved-execution-plan/2.0":
        plan: (
            ResolvedExecutionPlan
            | ResolvedExecutionPlanV2
            | ResolvedExecutionPlanV3
            | ResolvedExecutionPlanV4
            | ResolvedExecutionPlanV5
        ) = ResolvedExecutionPlanV2.model_validate(plan_record.canonical_document)
    elif plan_record.canonical_document.get("schema_version") == "resolved-execution-plan/3.0":
        plan = ResolvedExecutionPlanV3.model_validate(plan_record.canonical_document)
    elif plan_record.canonical_document.get("schema_version") == "resolved-execution-plan/4.0":
        plan = ResolvedExecutionPlanV4.model_validate(plan_record.canonical_document)
    elif plan_record.canonical_document.get("schema_version") == "resolved-execution-plan/5.0":
        plan = ResolvedExecutionPlanV5.model_validate(plan_record.canonical_document)
    else:
        plan = ResolvedExecutionPlan.model_validate(plan_record.canonical_document)
    if (
        plan.plan_sha256 != plan_record.plan_sha256
        or compute_control_document_hash(plan_record.canonical_document, "plan_sha256")
        != plan.plan_sha256
    ):
        raise ControlPlaneError("CONTROL_PLAN_HASH_MISMATCH", "resolved plan record is stale")
    matches = [step for step in plan.steps if step.step_key == step_key]
    if len(matches) != 1:
        raise ControlPlaneError("CONTROL_PLAN_STEP_MISSING", "resolved execution step is missing")
    step = matches[0]
    revision_ids: set[str] = set()
    if isinstance(plan, ResolvedExecutionPlanV2):
        revision_ids.add(plan.source_artifact_revision_id)
    elif isinstance(plan, (ResolvedExecutionPlanV4, ResolvedExecutionPlanV5)):
        # The original PDF, bundle manifest, and rights attestation are pinned
        # provenance. Only the selected Markdown members cross the explicit
        # materialization boundary into the worker workspace. V5 also carries
        # every selected immutable page PNG through this same allowlist.
        revision_ids.update(
            member.artifact_revision_id for member in plan.document_source.materialization_members
        )
    elif isinstance(plan, ResolvedExecutionPlanV3):
        assert isinstance(step, ResolvedStepExecutionV3)
        if step.evidence_access == "EVIDENCE_CONTEXT":
            revision_ids.update(
                {
                    plan.evidence_manifest_artifact.artifact_revision_id,
                    plan.evidence_context_artifact.artifact_revision_id,
                }
            )
    bundles: list[tuple[BundleRevisionPointer, str]] = [(step.instruction_bundle, "INSTRUCTION")]
    if step.reference_bundle is not None:
        bundles.append((step.reference_bundle, "REFERENCE"))
    for pointer, expected_kind in bundles:
        record = session.get(ExecutionBundleRevisionRecord, pointer.bundle_revision_id)
        if (
            record is None
            or record.bundle_id != pointer.bundle_id
            or record.bundle_kind != expected_kind
            or record.state != "RELEASED"
            or record.manifest_sha256 != pointer.manifest_sha256
            or record.manifest_artifact_revision_id
            != pointer.manifest_artifact.artifact_revision_id
        ):
            raise ControlPlaneError(
                "CONTROL_BUNDLE_POINTER_INVALID", "resolved bundle pointer is stale"
            )
        revision_ids.add(pointer.manifest_artifact.artifact_revision_id)
        if expected_kind == "INSTRUCTION":
            instruction_manifest = InstructionBundleManifest.model_validate(
                record.canonical_document
            )
            revision_ids.update(
                component.artifact.artifact_revision_id
                for component in instruction_manifest.components
            )
        else:
            reference_manifest = ReferenceBundleManifest.model_validate(record.canonical_document)
            revision_ids.update(
                entry.artifact.artifact_revision_id for entry in reference_manifest.entries
            )
    return frozenset(revision_ids)


def _instruction_manifest(
    session: Session,
    step: ResolvedStepExecution,
    *,
    authorized_artifact_revision_ids: frozenset[str],
) -> InstructionBundleManifest:
    record = session.get(ExecutionBundleRevisionRecord, step.instruction_bundle.bundle_revision_id)
    if (
        record is None
        or record.bundle_id != step.instruction_bundle.bundle_id
        or record.bundle_kind != "INSTRUCTION"
        or record.state != "RELEASED"
        or record.manifest_sha256 != step.instruction_bundle.manifest_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_INSTRUCTION_POINTER_INVALID", "instruction bundle revision is stale"
        )
    if (
        step.instruction_bundle.manifest_artifact.artifact_revision_id
        not in authorized_artifact_revision_ids
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_PERMISSION_DENIED", "instruction manifest is not authorized"
        )
    resolve_control_artifact_pointer(session, step.instruction_bundle.manifest_artifact)
    manifest = InstructionBundleManifest.model_validate(record.canonical_document)
    if (
        record.content_sha256 != manifest.content_sha256
        or compute_control_document_hash(record.canonical_document, "content_sha256")
        != manifest.content_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_INSTRUCTION_HASH_MISMATCH", "instruction bundle document hash differs"
        )
    return manifest


def _reference_manifest(
    session: Session,
    step: ResolvedStepExecution,
    *,
    authorized_artifact_revision_ids: frozenset[str],
) -> ReferenceBundleManifest | None:
    if step.reference_bundle is None:
        return None
    record = session.get(ExecutionBundleRevisionRecord, step.reference_bundle.bundle_revision_id)
    if (
        record is None
        or record.bundle_id != step.reference_bundle.bundle_id
        or record.bundle_kind != "REFERENCE"
        or record.state != "RELEASED"
        or record.manifest_sha256 != step.reference_bundle.manifest_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_REFERENCE_POINTER_INVALID", "reference bundle revision is stale"
        )
    if (
        step.reference_bundle.manifest_artifact.artifact_revision_id
        not in authorized_artifact_revision_ids
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_PERMISSION_DENIED", "reference manifest is not authorized"
        )
    resolve_control_artifact_pointer(session, step.reference_bundle.manifest_artifact)
    manifest = ReferenceBundleManifest.model_validate(record.canonical_document)
    if (
        record.content_sha256 != manifest.content_sha256
        or compute_control_document_hash(record.canonical_document, "content_sha256")
        != manifest.content_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_REFERENCE_HASH_MISMATCH", "reference bundle document hash differs"
        )
    return manifest


def _materialize_member(
    session: Session,
    *,
    pointer: ControlArtifactPointer,
    relative_path: str,
    workspace: Path,
    artifact_root: Path,
    worker_group_id: int,
    authorized_artifact_revision_ids: frozenset[str],
) -> bytes:
    if pointer.artifact_revision_id not in authorized_artifact_revision_ids:
        raise ControlPlaneError(
            "CONTROL_POINTER_PERMISSION_DENIED", "artifact revision is not authorized"
        )
    if pointer.media_type != "text/markdown" or not relative_path.endswith(".md"):
        raise ControlPlaneError(
            "CONTROL_POINTER_MEDIA_MISMATCH", "materialized member is not Markdown"
        )
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ControlPlaneError("CONTROL_POINTER_UNSAFE", "materialized path is unsafe")
    revision = resolve_control_artifact_pointer(
        session, pointer, expected_media_type="text/markdown"
    )
    expected_revision_root = artifact_root / pointer.artifact_id / pointer.artifact_revision_id
    stored_root = Path(revision.nas_path)
    if stored_root != expected_revision_root:
        raise ControlPlaneError(
            "CONTROL_POINTER_STORAGE_MISMATCH", "artifact storage location is not canonical"
        )
    source = stored_root / PurePosixPath(pointer.logical_name)
    entry = _manifest_entry(revision.manifest, pointer.logical_name)
    expected_bytes = entry.get("bytes")
    if not isinstance(expected_bytes, int) or not 0 < expected_bytes <= MAX_MARKDOWN_MEMBER_BYTES:
        raise ControlPlaneError("CONTROL_POINTER_SIZE_INVALID", "Markdown member size is invalid")
    payload = _read_verified_source(
        source,
        canonical_root=artifact_root,
        expected_sha256=pointer.sha256,
        expected_bytes=expected_bytes,
    )
    try:
        payload.decode("utf-8")
    except UnicodeError as exc:
        raise ControlPlaneError(
            "CONTROL_POINTER_ENCODING_INVALID", "Markdown member is not UTF-8"
        ) from exc
    destination = workspace.joinpath(*relative.parts)
    _ensure_parent(destination.parent, workspace=workspace, group_id=worker_group_id)
    _write_exclusive(destination, payload, group_id=worker_group_id)
    return payload


def _manifest_entry(manifest: dict[str, object], logical_name: str) -> dict[str, object]:
    files = manifest.get("files")
    matches = (
        [item for item in files if isinstance(item, dict) and item.get("file_name") == logical_name]
        if isinstance(files, list)
        else []
    )
    if len(matches) != 1:
        raise ControlPlaneError("CONTROL_POINTER_MANIFEST_MISMATCH", "artifact member is missing")
    return matches[0]


def _materialize_analysis_source(
    session: Session,
    *,
    plan: ResolvedExecutionPlanV2,
    workspace: Path,
    artifact_root: Path,
    worker_group_id: int,
    authorized_artifact_revision_ids: frozenset[str],
) -> bytes:
    if plan.source_artifact_revision_id not in authorized_artifact_revision_ids:
        raise ControlPlaneError(
            "CONTROL_POINTER_PERMISSION_DENIED", "analysis source revision is not authorized"
        )
    logical = session.get(ArtifactRecord, plan.source_artifact_id)
    revision = session.get(ArtifactRevisionRecord, plan.source_artifact_revision_id)
    if (
        logical is None
        or revision is None
        or not logical.approved
        or not revision.approved
        or revision.logical_artifact_id != plan.source_artifact_id
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_REVISION_INVALID", "analysis source Artifact pointer is stale"
        )
    expected_root = artifact_root / plan.source_artifact_id / plan.source_artifact_revision_id
    stored_root = Path(revision.nas_path)
    if stored_root != expected_root:
        raise ControlPlaneError(
            "CONTROL_POINTER_STORAGE_MISMATCH", "analysis source storage is not canonical"
        )
    entry = _manifest_entry(revision.manifest, plan.source_member_path)
    if (
        entry.get("sha256") != plan.source_sha256
        or entry.get("bytes") != plan.source_bytes
        or entry.get("media_type") != plan.source_media_type
        or entry.get("schema_ref") != plan.source_schema_ref
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_MANIFEST_MISMATCH", "analysis source manifest differs from plan"
        )
    payload = _read_verified_source(
        stored_root / PurePosixPath(plan.source_member_path),
        canonical_root=artifact_root,
        expected_sha256=plan.source_sha256,
        expected_bytes=plan.source_bytes,
    )
    relative = PurePosixPath(plan.source_materialized_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or relative.parts[0] != "source"
        or ".." in relative.parts
        or "." in relative.parts
    ):
        raise ControlPlaneError("CONTROL_POINTER_UNSAFE", "analysis source path is unsafe")
    destination = workspace.joinpath(*relative.parts)
    _ensure_parent(destination.parent, workspace=workspace, group_id=worker_group_id)
    _write_exclusive(destination, payload, group_id=worker_group_id)
    return payload


def _materialize_analysis_document_source(
    session: Session,
    *,
    plan: ResolvedExecutionPlanV4 | ResolvedExecutionPlanV5,
    workspace: Path,
    artifact_root: Path,
    worker_group_id: int,
    authorized_artifact_revision_ids: frozenset[str],
) -> tuple[int, int]:
    """Materialize only the exact analysis index/pages; the original PDF stays canonical."""

    source = plan.document_source
    total_bytes = 0
    for member in source.materialization_members:
        if member.artifact_revision_id not in authorized_artifact_revision_ids:
            raise ControlPlaneError(
                "CONTROL_POINTER_PERMISSION_DENIED",
                "document analysis member revision is not authorized",
            )
        logical = session.get(ArtifactRecord, member.artifact_id)
        revision = session.get(ArtifactRevisionRecord, member.artifact_revision_id)
        if (
            logical is None
            or revision is None
            or not logical.approved
            or not revision.approved
            or revision.logical_artifact_id != member.artifact_id
        ):
            raise ControlPlaneError(
                "CONTROL_POINTER_REVISION_INVALID",
                "document analysis member Artifact pointer is stale",
            )
        expected_root = artifact_root / member.artifact_id / member.artifact_revision_id
        stored_root = Path(revision.nas_path)
        if stored_root != expected_root:
            raise ControlPlaneError(
                "CONTROL_POINTER_STORAGE_MISMATCH",
                "document analysis member storage is not canonical",
            )
        entry = _manifest_entry(revision.manifest, member.member_path)
        if (
            entry.get("sha256") != member.sha256
            or entry.get("bytes") != member.bytes
            or entry.get("media_type") != member.media_type
            or entry.get("schema_ref") != member.schema_ref
        ):
            raise ControlPlaneError(
                "CONTROL_POINTER_MANIFEST_MISMATCH",
                "document analysis member manifest differs from the plan",
            )
        payload = _read_verified_source(
            stored_root / PurePosixPath(member.member_path),
            canonical_root=artifact_root,
            expected_sha256=member.sha256,
            expected_bytes=member.bytes,
        )
        if member.media_type == "image/png":
            _validate_png_payload(
                payload,
                expected_width=member.width_pixels,
                expected_height=member.height_pixels,
            )
        else:
            try:
                payload.decode("utf-8")
            except UnicodeError as exc:
                raise ControlPlaneError(
                    "CONTROL_POINTER_ENCODING_INVALID",
                    "document analysis member is not UTF-8 Markdown",
                ) from exc
        relative = PurePosixPath(member.materialized_path)
        if (
            relative.is_absolute()
            or relative.parts[:2] != ("source", "document")
            or ".." in relative.parts
            or "." in relative.parts
        ):
            raise ControlPlaneError(
                "CONTROL_POINTER_UNSAFE", "document analysis materialized path is unsafe"
            )
        destination = workspace.joinpath(*relative.parts)
        _ensure_parent(destination.parent, workspace=workspace, group_id=worker_group_id)
        _write_exclusive(destination, payload, group_id=worker_group_id)
        total_bytes += len(payload)
    if total_bytes != source.materialization_bytes:
        raise ControlPlaneError(
            "CONTROL_POINTER_SIZE_INVALID",
            "document analysis materialized byte count differs from the plan",
        )
    return total_bytes, len(source.materialization_members)


def _validate_png_payload(
    payload: bytes,
    *,
    expected_width: int | None,
    expected_height: int | None,
) -> None:
    if (
        len(payload) < 24
        or payload[:8] != b"\x89PNG\r\n\x1a\n"
        or payload[12:16] != b"IHDR"
        or expected_width is None
        or expected_height is None
        or int.from_bytes(payload[16:20], "big") != expected_width
        or int.from_bytes(payload[20:24], "big") != expected_height
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_MEDIA_MISMATCH",
            "document analysis page image is not the pinned PNG",
        )


def _materialize_evidence_context(
    session: Session,
    *,
    plan: ResolvedExecutionPlanV3,
    workspace: Path,
    artifact_root: Path,
    worker_group_id: int,
    authorized_artifact_revision_ids: frozenset[str],
) -> bytes:
    """Validate the immutable manifest, then stage only its bounded context Markdown."""

    for pointer in (plan.evidence_manifest_artifact, plan.evidence_context_artifact):
        if pointer.artifact_revision_id not in authorized_artifact_revision_ids:
            raise ControlPlaneError(
                "CONTROL_POINTER_PERMISSION_DENIED", "Evidence Bundle material is not authorized"
            )
    manifest_payload = _knowledge_member_payload(
        session,
        pointer=plan.evidence_manifest_artifact,
        artifact_root=artifact_root,
        maximum_bytes=2 * 1024 * 1024,
    )
    try:
        manifest_value = json.loads(manifest_payload.decode("utf-8"))
        if not isinstance(manifest_value, dict):
            raise ValueError("manifest root is not an object")
        manifest_schema_ref = plan.evidence_manifest_artifact.schema_ref
        manifest: EvidenceBundleManifestV2 | EvidenceBundleManifestV3 | EvidenceBundleManifestV4
        if manifest_schema_ref == "eom://schemas/knowledge/evidence-bundle-manifest/4.0":
            validate_catalog_contract("evidence-bundle-manifest-v4", manifest_value)
            manifest = EvidenceBundleManifestV4.model_validate(manifest_value)
        elif manifest_schema_ref == "eom://schemas/knowledge/evidence-bundle-manifest/3.0":
            validate_catalog_contract("evidence-bundle-manifest-v3", manifest_value)
            manifest = EvidenceBundleManifestV3.model_validate(manifest_value)
        else:
            validate_catalog_contract("evidence-bundle-manifest-v2", manifest_value)
            manifest = EvidenceBundleManifestV2.model_validate(manifest_value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_EVIDENCE_MANIFEST_INVALID", "Evidence Bundle manifest is invalid"
        ) from exc
    if (
        manifest.evidence_bundle_id != plan.evidence_bundle_id
        or manifest.evidence_bundle_revision_id != plan.evidence_bundle_revision_id
        or manifest.retrieval_request_id != plan.retrieval_request_id
        or manifest.retrieval_request_sha256 != plan.retrieval_request_sha256
        or manifest.graph_snapshot != plan.graph_snapshot
        or manifest.access_policy_revision_id != plan.access_policy_revision_id
        or manifest.access_policy_sha256 != plan.access_policy_sha256
        or manifest.requester_permissions_sha256 != plan.requester_permissions_sha256
        or manifest.materials.context_markdown != plan.evidence_context_artifact
        or manifest.manifest_sha256 != plan.evidence_manifest_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_EVIDENCE_POINTER_MISMATCH", "Evidence Bundle manifest differs from plan"
        )
    payload = _knowledge_member_payload(
        session,
        pointer=plan.evidence_context_artifact,
        artifact_root=artifact_root,
        maximum_bytes=MAX_MARKDOWN_MEMBER_BYTES,
    )
    try:
        payload.decode("utf-8")
    except UnicodeError as exc:
        raise ControlPlaneError(
            "CONTROL_POINTER_ENCODING_INVALID", "Evidence context is not UTF-8"
        ) from exc
    destination = workspace / "references" / "evidence" / "context.md"
    _ensure_parent(destination.parent, workspace=workspace, group_id=worker_group_id)
    _write_exclusive(destination, payload, group_id=worker_group_id)
    return payload


def _knowledge_member_payload(
    session: Session,
    *,
    pointer: KnowledgeArtifactMemberPointer,
    artifact_root: Path,
    maximum_bytes: int,
) -> bytes:
    logical = session.get(ArtifactRecord, pointer.artifact_id)
    revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
    if (
        logical is None
        or revision is None
        or not logical.approved
        or not revision.approved
        or revision.logical_artifact_id != pointer.artifact_id
        or revision.content_hash != pointer.sha256
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_REVISION_INVALID", "Evidence Artifact pointer is stale"
        )
    stored_root = Path(revision.nas_path)
    expected_root = artifact_root / pointer.artifact_id / pointer.artifact_revision_id
    if stored_root != expected_root:
        raise ControlPlaneError(
            "CONTROL_POINTER_STORAGE_MISMATCH", "Evidence Artifact storage is not canonical"
        )
    entry = _manifest_entry(revision.manifest, pointer.member_path)
    expected_bytes = entry.get("bytes")
    if (
        entry.get("sha256") != pointer.sha256
        or entry.get("media_type") != pointer.media_type
        or entry.get("schema_ref") != pointer.schema_ref
        or not isinstance(expected_bytes, int)
        or not 0 < expected_bytes <= maximum_bytes
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_MANIFEST_MISMATCH", "Evidence member manifest differs"
        )
    return _read_verified_source(
        stored_root / PurePosixPath(pointer.member_path),
        canonical_root=artifact_root,
        expected_sha256=pointer.sha256,
        expected_bytes=expected_bytes,
    )


def _canonical_root(path: Path) -> Path:
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or not path.is_absolute()
            or path.resolve(strict=True) != path
        ):
            raise ValueError("artifact root is unsafe")
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_ARTIFACT_ROOT_UNAVAILABLE", "canonical artifact root is unavailable"
        ) from exc
    return path


def _read_verified_source(
    path: Path,
    *,
    canonical_root: Path,
    expected_sha256: str,
    expected_bytes: int,
) -> bytes:
    try:
        relative = path.relative_to(canonical_root)
        current = canonical_root
        for component in relative.parts[:-1]:
            current = current / component
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("artifact parent is unsafe")
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size != expected_bytes
            ):
                raise ValueError("artifact member metadata differs")
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, COPY_BUFFER_BYTES):
                digest.update(chunk)
                chunks.append(chunk)
            payload = b"".join(chunks)
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_POINTER_FILE_INVALID", "artifact member is unsafe or unreadable"
        ) from exc
    if "sha256:" + digest.hexdigest() != expected_sha256:
        raise ControlPlaneError("CONTROL_POINTER_HASH_MISMATCH", "artifact member hash differs")
    return payload


def _ensure_parent(path: Path, *, workspace: Path, group_id: int) -> None:
    try:
        relative = path.relative_to(workspace)
    except ValueError as exc:
        raise ControlPlaneError("CONTROL_POINTER_UNSAFE", "materialized parent escaped") from exc
    current = workspace
    for component in relative.parts:
        current = current / component
        if current.exists() or current.is_symlink():
            _require_directory(current, group_id=group_id, mode=MATERIALIZED_DIRECTORY_MODE)
            continue
        current.mkdir(mode=MATERIALIZED_DIRECTORY_MODE)
        os.chown(current, -1, group_id)
        current.chmod(MATERIALIZED_DIRECTORY_MODE)
        _require_directory(current, group_id=group_id, mode=MATERIALIZED_DIRECTORY_MODE)


def _require_directory(path: Path, *, group_id: int, mode: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ControlPlaneError(
            "CONTROL_WORKSPACE_INVALID", "workspace directory is unavailable"
        ) from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_gid != group_id
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise ControlPlaneError("CONTROL_WORKSPACE_INVALID", "workspace directory is unsafe")


def _write_exclusive(path: Path, payload: bytes, *, group_id: int) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, MATERIALIZED_FILE_MODE)
        try:
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fchown(descriptor, -1, group_id)
            os.fchmod(descriptor, MATERIALIZED_FILE_MODE)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_gid != group_id
                or stat.S_IMODE(metadata.st_mode) != MATERIALIZED_FILE_MODE
                or metadata.st_size != len(payload)
            ):
                raise ValueError("materialized file metadata differs")
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_MATERIALIZATION_FAILED", "job-local materialization failed"
        ) from exc


def _agents_document(instruction_docs: list[tuple[str, str, bytes]]) -> bytes:
    sections = [
        b"# EOM Job Instructions\n\n",
        b"This file is a deterministic job-local view of pinned instruction revisions.\n",
    ]
    for layer, relative_path, payload in instruction_docs:
        sections.extend(
            (
                f"\n## {layer}: {relative_path}\n\n".encode(),
                payload.rstrip(b"\n"),
                b"\n",
            )
        )
    return b"".join(sections)


def _require_total_size(value: int, *, analysis: bool) -> None:
    limit = MAX_ANALYSIS_MATERIALIZED_BYTES if analysis else MAX_MATERIALIZED_BYTES
    if value > limit:
        raise ControlPlaneError(
            "CONTROL_MATERIALIZATION_TOO_LARGE", "job-local materialization exceeds size limit"
        )
