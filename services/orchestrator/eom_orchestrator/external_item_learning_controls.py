"""Prepare creative instruction/preset values through existing control owners.

No new capacity policy, model observation, evaluation, release or worker start.
The authenticated calling application supplies the current control-authority port.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.control_plane import (
    BundleRevisionPointer,
    ExecutionPresetRevision,
    InstructionBundleManifest,
    ModelCandidate,
    RoleExecutionPolicy,
    UtcDatetime,
    WorkerCapacityPolicyV4,
    WorkerRole,
)
from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionBundleRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    publish_bundle_revision,
    record_bundle_revision,
    resolve_released_instruction_bundle,
)
from eom_orchestrator.preset_lifecycle import create_execution_preset_draft
from eom_orchestrator.preset_model_selection import (
    resolve_released_capacity_policy,
    validated_preset,
)

CREATIVE_INSTRUCTION_BUNDLE_KEY = "external-item-learning-instructions"
CREATIVE_SOURCE_INSTRUCTION_BUNDLE_KEY = "creative-source-learning-instructions"


def resolve_external_item_learning_control_policy(
    session: Session,
    *,
    instruction: BundleRevisionPointer,
    capacity_revision_id: str,
    candidate: ModelCandidate,
) -> RoleExecutionPolicy:
    """Resolve exact control purpose, without granting source or model authority."""

    capacity = resolve_released_capacity_policy(session, capacity_revision_id)
    logical = session.get(WorkerCapacityPolicyRecord, capacity.capacity_policy_id)
    if (
        not isinstance(capacity, WorkerCapacityPolicyV4)
        or logical is None
        or logical.policy_key != "fixed-host"
        or logical.state != "ACTIVE"
        or logical.current_revision_id != capacity_revision_id
    ):
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "creative preparation requires fixed-host V4"
        )
    manifest = resolve_released_instruction_bundle(session, instruction)
    bundle = session.get(
        ExecutionBundleRecord, instruction.bundle_id, with_for_update=True, populate_existing=True
    )
    if (
        bundle is None
        or bundle.bundle_key != CREATIVE_INSTRUCTION_BUNDLE_KEY
        or bundle.bundle_kind != "INSTRUCTION"
        or bundle.state != "ACTIVE"
        or bundle.current_revision_id != instruction.bundle_revision_id
        or tuple((part.layer, part.relative_path) for part in manifest.components)
        != (
            ("PLATFORM", "instructions/platform.md"),
            ("ROLE", "instructions/external-item-learning.md"),
        )
    ):
        raise ControlPlaneError(
            "CONTROL_INSTRUCTION_POINTER_INVALID", "creative instruction purpose differs"
        )
    return RoleExecutionPolicy(
        role=WorkerRole.SUPPORT,
        model_candidates=(candidate,),
        instruction_bundle=instruction,
        reference_bundle=None,
        worker_pool_key="support",
        timeout_seconds=7200,
        sandbox="read-only",
        network="disabled",
    )


def publish_external_item_learning_instruction_bundle(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    platform_payload: bytes,
    role_payload: bytes,
    source_commit: str,
    operator_id: str,
    created_at: datetime,
    authorize_control_change: Callable[[str], None],
    bundle_key: str = CREATIVE_INSTRUCTION_BUNDLE_KEY,
) -> BundleRevisionPointer:
    """Publish the reviewed initial two-layer bundle; never a model or preset.

    Individual Artifact commits are resumable independent transactions. Retain
    them on a later permission/control failure and replay with the same pins.
    """

    if bundle_key not in {CREATIVE_INSTRUCTION_BUNDLE_KEY, CREATIVE_SOURCE_INSTRUCTION_BUNDLE_KEY}:
        raise ValueError("creative instruction purpose is unsupported")
    authorize_control_change(operator_id)
    TypeAdapter(UtcDatetime).validate_python(created_at)
    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("creative instruction source commit is invalid")
    for payload in (platform_payload, role_payload):
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= 64 * 1024:
            raise ValueError("creative instruction payload exceeds its bound")
        if "\x00" in payload.decode("utf-8"):
            raise ValueError("creative instruction payload is not plain UTF-8")
    components = []
    for layer, name, payload in (
        ("PLATFORM", "platform.md", platform_payload),
        ("ROLE", "external-item-learning.md", role_payload),
    ):
        authorize_control_change(operator_id)
        artifact = publisher.publish_bytes(
            payload=payload,
            logical_name=name,
            schema_ref="eom://schemas/workflow/instruction-member/1.0",
            media_type="text/markdown",
            artifact_type="control_markdown",
            idempotency_key=f"creative-instruction:{layer.lower()}:{sha256_bytes(payload)[7:]}",
            source_commit=source_commit,
            created_at=created_at,
        )
        components.append(
            {
                "layer": layer,
                "relative_path": "instructions/" + name,
                "artifact": artifact.pointer.model_dump(mode="json"),
            }
        )
    bundle_id = "instrbundle_" + uuid5(NAMESPACE_URL, bundle_key).hex
    revision_id = "instrrev_" + uuid5(NAMESPACE_URL, bundle_key + "/v1").hex
    body = {
        "schema_version": "instruction-bundle-manifest/1.0",
        "bundle_id": bundle_id,
        "bundle_revision_id": revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "components": components,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    manifest = InstructionBundleManifest.model_validate(
        {**body, "content_sha256": content_sha256(body)}
    )
    payload = canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"
    authorize_control_change(operator_id)
    artifact = publisher.publish_bytes(
        payload=payload,
        logical_name="instruction-bundle.json",
        schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
        media_type="application/json",
        artifact_type="control_instruction_bundle",
        idempotency_key="creative-instruction:manifest:" + sha256_bytes(payload)[7:],
        source_commit=source_commit,
        created_at=created_at,
    )
    with sessions.begin() as session:
        authorize_control_change(operator_id)
        record = record_bundle_revision(
            session,
            bundle_key=bundle_key,
            manifest_artifact=artifact.pointer,
            document=manifest.model_dump(mode="json"),
            created_by=operator_id,
        )
        publish_bundle_revision(
            session, bundle_id=record.bundle_id, bundle_revision_id=record.bundle_revision_id
        )
        authorize_control_change(operator_id)
    return BundleRevisionPointer(
        bundle_id=bundle_id,
        bundle_revision_id=revision_id,
        manifest_artifact=artifact.pointer,
        manifest_sha256=artifact.pointer.sha256,
    )


def prepare_external_item_learning_control_draft(
    session: Session,
    *,
    instruction: BundleRevisionPointer,
    capacity_revision_id: str,
    candidate: ModelCandidate,
    operator_id: str,
    created_at: datetime,
    authorize_control_change: Callable[[str], None],
) -> ExecutionPresetRevision:
    """Reuse a published instruction and fixed-host policy; save at most one DRAFT.

    The caller owns the root transaction, actual operator authentication and
    immutable instruction publication. A candidate is a desired model, not a
    fresh capability/quota claim. Execution keeps the normal current checks.
    """

    if not session.in_transaction():
        raise ValueError("creative control preparation requires a caller root transaction")
    try:
        authorize_control_change(operator_id)
        TypeAdapter(UtcDatetime).validate_python(created_at)
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        policy = resolve_external_item_learning_control_policy(
            session,
            instruction=instruction,
            capacity_revision_id=capacity_revision_id,
            candidate=candidate,
        )
        role_policies = [policy.model_dump(mode="json")]
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key == "external-item-learning")
            .with_for_update()
        )
        latest = (
            session.scalar(
                select(ExecutionPresetRevisionRecord)
                .where(ExecutionPresetRevisionRecord.preset_id == logical.preset_id)
                .order_by(ExecutionPresetRevisionRecord.revision_number.desc())
                .limit(1)
            )
            if logical is not None
            else None
        )
        if logical is not None and (
            logical.state != "ACTIVE" or latest is None or logical.current_revision_id is not None
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_HISTORY_INVALID", "creative preset history is unavailable"
            )
        if latest is not None:
            existing = validated_preset(latest)
            if (
                not isinstance(existing, ExecutionPresetRevision)
                or existing.state != "DRAFT"
                or existing.capacity_policy_revision_id != capacity_revision_id
                or existing.compatible_workflow_protocols != ("workflow-role/1.33.0",)
                or existing.general_knowledge_policy != "DENY"
                or [role.model_dump(mode="json") for role in existing.role_policies]
                != role_policies
            ):
                raise ControlPlaneError(
                    "CONTROL_BOOTSTRAP_CONFLICT", "creative preset already has a different history"
                )
            authorize_control_change(operator_id)
            return existing
        draft = create_execution_preset_draft(
            session,
            preset_key="external-item-learning",
            display_name="창작 문항 풀이 준비",
            description="고정된 원본/페이지를 기존 support 슬롯 1개로 읽는 창작 문항 분석 정책",
            role_policies=role_policies,
            capacity_policy_revision_id=capacity_revision_id,
            general_knowledge_policy="DENY",
            compatible_workflow_protocols=["workflow-role/1.33.0"],
            created_by=operator_id,
            created_at=created_at,
        )
        authorize_control_change(operator_id)
        return ExecutionPresetRevision.model_validate(draft.canonical_document)
    except Exception:
        session.rollback()
        raise
