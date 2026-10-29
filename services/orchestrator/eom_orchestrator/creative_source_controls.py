"""Release a separate source-visual purpose; never repoint the historical preset."""

from collections.abc import Callable
from datetime import UTC, datetime

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.control_plane import (
    BundleRevisionPointer,
    ControlArtifactPointer,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
)
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow.schemas import load_role_input_schema, role_schema_bundle_hash
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    resolve_released_instruction_bundle,
)
from eom_orchestrator.external_item_learning_controls import (
    CREATIVE_SOURCE_INSTRUCTION_BUNDLE_KEY,
    publish_external_item_learning_instruction_bundle,
)
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.preset_model_selection import (
    non_live_invocation_cases,
    resolve_released_capacity_policy,
    validated_preset,
)
from eom_orchestrator.preset_policy import execution_preset_policy_sha256
from eom_orchestrator.repository import ensure_protocol_version


def _instruction(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    platform: bytes,
    role: bytes,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
) -> BundleRevisionPointer:
    """Replay a published exact two-layer bundle, not its mutable current meaning."""
    with sessions() as session:
        logical = session.scalar(
            select(ExecutionBundleRecord).where(
                ExecutionBundleRecord.bundle_key == CREATIVE_SOURCE_INSTRUCTION_BUNDLE_KEY,
                ExecutionBundleRecord.bundle_kind == "INSTRUCTION",
            )
        )
        if logical is not None:
            row = session.get(ExecutionBundleRevisionRecord, logical.current_revision_id)
            if row is None or logical.state != "ACTIVE" or row.state != "RELEASED":
                raise ControlPlaneError(
                    "CONTROL_CREATIVE_SOURCE_BUNDLE_INVALID", "bundle state differs"
                )
            pointer = BundleRevisionPointer(
                bundle_id=row.bundle_id,
                bundle_revision_id=row.bundle_revision_id,
                manifest_artifact=ControlArtifactPointer(
                    artifact_id=row.manifest_artifact_id,
                    artifact_revision_id=row.manifest_artifact_revision_id,
                    sha256=row.manifest_sha256,
                    schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
                    media_type="application/json",
                    logical_name="instruction-bundle.json",
                ),
                manifest_sha256=row.manifest_sha256,
            )
            manifest = resolve_released_instruction_bundle(session, pointer)
            expected = (
                ("PLATFORM", "instructions/platform.md", sha256_bytes(platform)),
                ("ROLE", "instructions/external-item-learning.md", sha256_bytes(role)),
            )
            if (
                tuple(
                    (part.layer, part.relative_path, part.artifact.sha256)
                    for part in manifest.components
                )
                != expected
            ):
                raise ControlPlaneError(
                    "CONTROL_CREATIVE_SOURCE_BUNDLE_INVALID", "bundle content differs"
                )
            return pointer
    return publish_external_item_learning_instruction_bundle(
        sessions,
        publisher,
        platform_payload=platform,
        role_payload=role,
        operator_id=operator_id,
        source_commit=source_commit,
        created_at=datetime.now(UTC),
        authorize_control_change=authorize,
        bundle_key=CREATIVE_SOURCE_INSTRUCTION_BUNDLE_KEY,
    )


def release_creative_source_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    baseline_revision_id: str,
    capacity_revision_id: str,
    platform_payload: bytes,
    role_payload: bytes,
    operator_id: str,
    source_commit: str,
    authorize: Callable[[str], None],
) -> ExecutionPresetRevision:
    """Clone the exact old model/isolation, change only the separate instructions/family.

    Existing lifecycle owns draft/evaluation/release and serializes publication.
    NON_LIVE is contract validation, never educational quality or fresh quota proof.
    """
    authorize(operator_id)
    with sessions() as session:
        row = session.get(ExecutionPresetRevisionRecord, baseline_revision_id)
        baseline = validated_preset(row) if row else None
        logical_baseline = (
            session.get(ExecutionPresetRecord, baseline.preset_id) if baseline else None
        )
        capacity = resolve_released_capacity_policy(session, capacity_revision_id)
        pools = {pool.pool_key: pool for pool in capacity.pools}
        pool = pools.get("support")
        if (
            not isinstance(baseline, ExecutionPresetRevision)
            or logical_baseline is None
            or logical_baseline.state != "ACTIVE"
            or logical_baseline.preset_key != "external-item-learning"
            or baseline.state != "RELEASED"
            or baseline.compatible_workflow_protocols != ("workflow-role/1.33.0",)
            or baseline.capacity_policy_revision_id != capacity_revision_id
            or baseline.general_knowledge_policy != "DENY"
            or len(baseline.role_policies) != 1
            or baseline.role_policies[0].role != "support"
            or baseline.role_policies[0].worker_pool_key != "support"
            or baseline.role_policies[0].network != "disabled"
            or baseline.role_policies[0].sandbox != "read-only"
            or baseline.role_policies[0].reference_bundle is not None
            or pool is None
            or pool.slot_keys != ("slot05",)
            or pool.max_active != 1
        ):
            raise ControlPlaneError(
                "CONTROL_CREATIVE_SOURCE_BASE_INVALID", "source baseline differs"
            )
    profile = creative_learning_profile("2.0.0")
    load_role_input_schema("support", profile.role_protocol)
    instruction = _instruction(
        sessions,
        publisher,
        platform=platform_payload,
        role=role_payload,
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
    )
    policies = [
        baseline.role_policies[0]
        .model_copy(update={"instruction_bundle": instruction})
        .model_dump(mode="json")
    ]
    with sessions.begin() as session:
        authorize(operator_id)
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        ensure_protocol_version(
            session, profile.role_protocol, role_schema_bundle_hash(profile.role_protocol)
        )
        logical = session.scalar(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key == profile.preset_key)
            .with_for_update()
        )
        if logical is not None and logical.state != "ACTIVE":
            raise ControlPlaneError(
                "CONTROL_CREATIVE_SOURCE_PRESET_INVALID", "source purpose is retired"
            )
        if logical is not None and logical.current_revision_id:
            row = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            existing = validated_preset(row) if row else None
            if (
                not isinstance(existing, ExecutionPresetRevision)
                or existing.state != "RELEASED"
                or existing.capacity_policy_revision_id != capacity_revision_id
                or existing.general_knowledge_policy != "DENY"
                or existing.compatible_workflow_protocols != (profile.role_protocol,)
                or [part.model_dump(mode="json") for part in existing.role_policies] != policies
            ):
                raise ControlPlaneError(
                    "CONTROL_CREATIVE_SOURCE_PRESET_INVALID", "source replay differs"
                )
            return existing
        drafts = (
            tuple(
                session.scalars(
                    select(ExecutionPresetRevisionRecord).where(
                        ExecutionPresetRevisionRecord.preset_id == logical.preset_id,
                        ExecutionPresetRevisionRecord.state == "DRAFT",
                    )
                )
            )
            if logical
            else ()
        )
        if len(drafts) > 1:
            raise ControlPlaneError(
                "CONTROL_CREATIVE_SOURCE_PRESET_INVALID", "source drafts repeat"
            )
        draft_row = (
            drafts[0]
            if drafts
            else create_execution_preset_draft(
                session,
                preset_key=profile.preset_key,
                display_name="창작 원문 그림·풀이 분석",
                description="원문 영역 추출과 독립 풀이, support05 동시1",
                role_policies=policies,
                capacity_policy_revision_id=capacity_revision_id,
                general_knowledge_policy="DENY",
                compatible_workflow_protocols=[profile.role_protocol],
                created_by=operator_id,
                created_at=datetime.now(UTC),
            )
        )
        draft = validated_preset(draft_row)
        if (
            not isinstance(draft, ExecutionPresetRevision)
            or draft.capacity_policy_revision_id != capacity_revision_id
            or draft.compatible_workflow_protocols != (profile.role_protocol,)
            or draft.general_knowledge_policy != "DENY"
            or [part.model_dump(mode="json") for part in draft.role_policies] != policies
        ):
            raise ControlPlaneError(
                "CONTROL_CREATIVE_SOURCE_PRESET_INVALID", "source draft differs"
            )
    cases = (
        "SOURCE_VISUAL_ROLE_SCHEMA",
        "EXACT_BASELINE_MODEL_AND_ISOLATION",
        "SLOT05_ONLY",
        *non_live_invocation_cases(draft),
    )
    now = datetime.now(UTC)
    body = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": draft.preset_revision_id,
        "evaluated_policy_sha256": execution_preset_policy_sha256(draft),
        "scope": "NON_LIVE",
        "outcome": "PASS",
        "summary_code": "CONTRACT_VALIDATION",
        "cases_total": len(cases),
        "cases_passed": len(cases),
        "quality_score_permille": None,
        "completed_at": now.isoformat().replace("+00:00", "Z"),
    }
    report = ExecutionPresetEvaluationReport.model_validate(
        {**body, "report_sha256": content_sha256(body)}
    )
    authorize(operator_id)
    artifact = publisher.publish_bytes(
        payload=canonical_json_bytes(report.model_dump(mode="json")) + b"\n",
        logical_name="creative-source-preset-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key="creative-source-eval:" + report.report_sha256[7:],
        created_at=now,
        source_commit=source_commit,
    )
    with sessions.begin() as session:
        authorize(operator_id)
        record_execution_preset_evaluation(
            session,
            document=report.model_dump(mode="json"),
            report_artifact=artifact.pointer,
            created_by=operator_id,
        )
        released = validated_preset(
            release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=operator_id,
                released_at=now,
            )
        )
        if not isinstance(released, ExecutionPresetRevision):
            raise ControlPlaneError(
                "CONTROL_CREATIVE_SOURCE_PRESET_INVALID", "released schema differs"
            )
        return released
