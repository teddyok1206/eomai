"""Explicit initial comparison-control preparation and technical release.

This dormant leaf does not bootstrap on a failed comparison request. The caller
must supply an actual authenticated owner's current-permission authorizer; a
reviewed timestamp, actor string or this module is not a release grant. Only the
explicitly selected initial V1 or three-axis V1.1 policies and exact replay are
supported. A V1 request is never automatically upgraded.

Artifact publication commits independently through the existing publisher.
Later control-transaction failure therefore retains immutable publication
history for exact recovery; it is not a distributed rollback. No model runs,
observation refresh, slot mutation, Workflow creation or Content Pack occurs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import AgentStep, compile_definition_data
from eom_workflow.control_plane import (
    BundleRevisionPointer,
    ControlArtifactPointer,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
    InstructionBundleManifest,
    RoleExecutionPolicy,
    UtcDatetime,
    WorkerRole,
)
from eom_workflow.inference_transfer_bootstrap_contract import (
    InferenceTransferBootstrapManifest,
    InferenceTransferBootstrapManifestV11,
    validate_inference_transfer_bootstrap_manifest,
    validate_inference_transfer_bootstrap_manifest_v11,
    validate_inference_transfer_reviewed_instruction,
)
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.repository import admitted_workflow_definition
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    publish_bundle_revision,
    record_bundle_revision,
    resolve_control_artifact_pointer,
    resolve_released_instruction_bundle,
)
from eom_orchestrator.database import transaction
from eom_orchestrator.models import ProtocolVersionRecord
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.preset_model_selection import (
    capacity_pool_model_options,
    non_live_invocation_cases,
    validated_preset,
)
from eom_orchestrator.preset_policy import execution_preset_policy_sha256
from eom_orchestrator.repository import ensure_protocol_version

PRESET_KEY = "item-inference-transfer-comparison"
INSTRUCTION_BUNDLE_KEY = "item-inference-transfer-comparison-instructions"
AXES_PRESET_KEY = "item-inference-transfer-comparison-axes"
AXES_INSTRUCTION_BUNDLE_KEY = "item-inference-transfer-comparison-axes-instructions"
_BUNDLE_ID = "instrbundle_" + uuid5(NAMESPACE_URL, f"eom://controls/{INSTRUCTION_BUNDLE_KEY}").hex
_BUNDLE_REVISION_ID = (
    "instrrev_" + uuid5(NAMESPACE_URL, f"eom://controls/{INSTRUCTION_BUNDLE_KEY}/initial-v1").hex
)
_BOOTSTRAP_SCHEMA = "eom://schemas/workflow/inference-transfer-control-bootstrap/1.0"
_INSTRUCTION_SCHEMA = "eom://schemas/workflow/instruction-bundle-manifest/1.0"
_EVALUATION_SCHEMA = "eom://schemas/workflow/execution-preset-evaluation-report/1.0"
ControlChangeAuthorizer = Callable[[str, Literal["PREPARE", "RELEASE"]], None]


@dataclass(frozen=True, slots=True)
class _BootstrapPurpose:
    preset_key: str
    instruction_bundle_key: str
    bootstrap_schema: str
    initial_revision: str

    @property
    def bundle_id(self) -> str:
        return (
            "instrbundle_"
            + uuid5(NAMESPACE_URL, f"eom://controls/{self.instruction_bundle_key}").hex
        )

    @property
    def bundle_revision_id(self) -> str:
        return (
            "instrrev_"
            + uuid5(
                NAMESPACE_URL,
                f"eom://controls/{self.instruction_bundle_key}/{self.initial_revision}",
            ).hex
        )


_V1_PURPOSE = _BootstrapPurpose(PRESET_KEY, INSTRUCTION_BUNDLE_KEY, _BOOTSTRAP_SCHEMA, "initial-v1")
_V11_PURPOSE = _BootstrapPurpose(
    AXES_PRESET_KEY,
    AXES_INSTRUCTION_BUNDLE_KEY,
    "eom://schemas/workflow/inference-transfer-control-bootstrap/1.1",
    "initial-v1.1",
)


def _purpose(manifest: InferenceTransferBootstrapManifest) -> _BootstrapPurpose:
    return (
        _V11_PURPOSE if isinstance(manifest, InferenceTransferBootstrapManifestV11) else _V1_PURPOSE
    )


@dataclass(frozen=True, slots=True)
class PreparedInferenceTransferControls:
    """Small exact control values, not approval or source-access tokens."""

    manifest: InferenceTransferBootstrapManifest
    bootstrap_artifact: ControlArtifactPointer
    instruction_bundle: BundleRevisionPointer
    draft: ExecutionPresetRevision


@dataclass(frozen=True, slots=True)
class ReleasedInferenceTransferControls:
    preset: ExecutionPresetRevision
    evaluation_id: str
    evaluation_artifact: ControlArtifactPointer
    executed_cases: tuple[str, ...]
    scientific_evaluation: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    human_transfer_evaluation: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


def prepare_inference_transfer_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    manifest: InferenceTransferBootstrapManifest,
    platform_payload: bytes,
    rubric_payload: bytes,
    operator_id: str,
    observed_at: datetime,
    authorize_control_change: ControlChangeAuthorizer,
) -> PreparedInferenceTransferControls:
    """Publish reviewed immutable inputs and an exact DRAFT, never release it."""

    if isinstance(manifest, InferenceTransferBootstrapManifestV11):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "explicit V1 bootstrap required")
    return _prepare_controls(
        sessions,
        publisher,
        manifest=manifest,
        platform_payload=platform_payload,
        rubric_payload=rubric_payload,
        operator_id=operator_id,
        observed_at=observed_at,
        authorize_control_change=authorize_control_change,
    )


def prepare_inference_transfer_controls_v11(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    manifest: InferenceTransferBootstrapManifestV11,
    platform_payload: bytes,
    rubric_payload: bytes,
    operator_id: str,
    observed_at: datetime,
    authorize_control_change: ControlChangeAuthorizer,
) -> PreparedInferenceTransferControls:
    """Explicit separate initial three-axis control history, with the same owners."""
    if not isinstance(manifest, InferenceTransferBootstrapManifestV11):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "explicit V1.1 bootstrap required")
    return _prepare_controls(
        sessions,
        publisher,
        manifest=manifest,
        platform_payload=platform_payload,
        rubric_payload=rubric_payload,
        operator_id=operator_id,
        observed_at=observed_at,
        authorize_control_change=authorize_control_change,
    )


def _prepare_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    manifest: InferenceTransferBootstrapManifest,
    platform_payload: bytes,
    rubric_payload: bytes,
    operator_id: str,
    observed_at: datetime,
    authorize_control_change: ControlChangeAuthorizer,
) -> PreparedInferenceTransferControls:

    checked = _checked_inputs(manifest, observed_at)
    purpose = _purpose(checked)
    try:
        validate_inference_transfer_reviewed_instruction(
            checked, layer="PLATFORM", payload=platform_payload
        )
        validate_inference_transfer_reviewed_instruction(
            checked, layer="ROLE", payload=rubric_payload
        )
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "reviewed instruction bytes differ"
        ) from exc
    _authorize(operator_id, "PREPARE", authorize_control_change)
    with transaction(sessions) as session:
        _authorize(operator_id, "PREPARE", authorize_control_change)
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        # Admission and existing history must pass before initial protocol
        # registration. RELEASE and ordinary comparison requests never repair it.
        _preflight_admission(session, checked, observed_at)
        _require_initial_history(session, checked)
        try:
            ensure_protocol_version(
                session,
                checked.workflow_role_schema_version,
                role_schema_bundle_hash(checked.workflow_role_schema_version),
            )
        except RuntimeError as exc:
            raise ControlPlaneError(
                "CONTROL_PROTOCOL_POINTER_MISSING", "exact comparison protocol is unavailable"
            ) from exc
        session.flush()
        _preflight(session, checked, observed_at)

    bootstrap = _publish(
        sessions,
        publisher,
        manifest=checked,
        payload=_json_bytes(checked),
        logical_name="inference-transfer-bootstrap.json",
        schema_ref=purpose.bootstrap_schema,
        artifact_type="control_inference_transfer_bootstrap",
        component_key="bootstrap",
        operator_id=operator_id,
        action="PREPARE",
        authorize=authorize_control_change,
    )
    members: list[dict[str, Any]] = []
    for member, payload in (
        (checked.platform_instruction, platform_payload),
        (checked.rubric_instruction, rubric_payload),
    ):
        pointer = _publish(
            sessions,
            publisher,
            manifest=checked,
            payload=payload,
            logical_name=member.logical_name,
            schema_ref=member.schema_ref,
            artifact_type="control_instruction_member",
            component_key=member.layer.lower(),
            operator_id=operator_id,
            action="PREPARE",
            authorize=authorize_control_change,
        )
        members.append(
            {
                "layer": member.layer,
                "relative_path": member.relative_path,
                "artifact": pointer.model_dump(mode="json"),
            }
        )
    instruction_body = {
        "schema_version": "instruction-bundle-manifest/1.0",
        "bundle_id": purpose.bundle_id,
        "bundle_revision_id": purpose.bundle_revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "components": members,
        "created_at": _utc_text(checked.source.reviewed_at),
    }
    instruction = InstructionBundleManifest.model_validate(
        instruction_body | {"content_sha256": content_sha256(instruction_body)}
    )
    instruction_artifact = _publish(
        sessions,
        publisher,
        manifest=checked,
        payload=_json_bytes(instruction),
        logical_name="instruction-bundle.json",
        schema_ref=_INSTRUCTION_SCHEMA,
        artifact_type="control_instruction_bundle",
        component_key="instruction-bundle",
        operator_id=operator_id,
        action="PREPARE",
        authorize=authorize_control_change,
    )
    bundle = BundleRevisionPointer(
        bundle_id=instruction.bundle_id,
        bundle_revision_id=instruction.bundle_revision_id,
        manifest_artifact=instruction_artifact,
        manifest_sha256=instruction_artifact.sha256,
    )
    with transaction(sessions) as session:
        _authorize(operator_id, "PREPARE", authorize_control_change)
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        _preflight(session, checked, observed_at)
        _require_initial_history(session, checked)
        record_bundle_revision(
            session,
            bundle_key=purpose.instruction_bundle_key,
            manifest_artifact=instruction_artifact,
            document=instruction.model_dump(mode="json"),
            created_by=operator_id,
        )
        publish_bundle_revision(
            session,
            bundle_id=instruction.bundle_id,
            bundle_revision_id=instruction.bundle_revision_id,
        )
        draft = _find_or_create_draft(session, checked, bundle, operator_id)
        _check_exact_preparation(session, checked, bootstrap, bundle, draft)
    return PreparedInferenceTransferControls(checked, bootstrap, bundle, draft)


def release_inference_transfer_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    prepared: PreparedInferenceTransferControls,
    operator_id: str,
    released_at: datetime,
    authorize_control_change: ControlChangeAuthorizer,
) -> ReleasedInferenceTransferControls:
    """Execute NON_LIVE adapter checks and explicitly release the exact policy.

    Returned case keys are actual executed checks. The existing immutable report
    stores their count, not a model-quality score. A retry reevaluates current
    admission and may record a new technical report; it never rewrites history.
    """

    if isinstance(prepared.manifest, InferenceTransferBootstrapManifestV11):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "explicit V1 bootstrap required")
    return _release_controls(
        sessions,
        publisher,
        prepared=prepared,
        operator_id=operator_id,
        released_at=released_at,
        authorize_control_change=authorize_control_change,
    )


def release_inference_transfer_controls_v11(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    prepared: PreparedInferenceTransferControls,
    operator_id: str,
    released_at: datetime,
    authorize_control_change: ControlChangeAuthorizer,
) -> ReleasedInferenceTransferControls:
    if not isinstance(prepared.manifest, InferenceTransferBootstrapManifestV11):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "explicit V1.1 bootstrap required")
    return _release_controls(
        sessions,
        publisher,
        prepared=prepared,
        operator_id=operator_id,
        released_at=released_at,
        authorize_control_change=authorize_control_change,
    )


def _release_controls(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    prepared: PreparedInferenceTransferControls,
    operator_id: str,
    released_at: datetime,
    authorize_control_change: ControlChangeAuthorizer,
) -> ReleasedInferenceTransferControls:
    checked = _checked_inputs(prepared.manifest, released_at)
    _authorize(operator_id, "RELEASE", authorize_control_change)
    with transaction(sessions) as session:
        _preflight(session, checked, released_at)
        _check_exact_preparation(
            session,
            checked,
            prepared.bootstrap_artifact,
            prepared.instruction_bundle,
            prepared.draft,
        )
        cases = (
            "REVIEWED_BOOTSTRAP_SCHEMA",
            "PUBLISHED_WORKFLOW_PROTOCOL_PINS",
            "FRESH_CAPACITY_POOL_MODEL",
            "EXACT_RELEASED_INSTRUCTION_METADATA",
            "EXACT_INITIAL_DRAFT",
            *non_live_invocation_cases(prepared.draft),
        )
    report_body = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": prepared.draft.preset_revision_id,
        "evaluated_policy_sha256": execution_preset_policy_sha256(prepared.draft),
        "scope": "NON_LIVE",
        "outcome": "PASS",
        "summary_code": "CONTRACT_VALIDATION",
        "cases_total": len(cases),
        "cases_passed": len(cases),
        "quality_score_permille": None,
        "completed_at": _utc_text(released_at),
    }
    report = ExecutionPresetEvaluationReport.model_validate(
        report_body | {"report_sha256": content_sha256(report_body)}
    )
    report_artifact = _publish(
        sessions,
        publisher,
        manifest=checked,
        payload=_json_bytes(report),
        logical_name="inference-transfer-preset-evaluation.json",
        schema_ref=_EVALUATION_SCHEMA,
        artifact_type="control_preset_evaluation",
        component_key=f"evaluation:{report.report_sha256[7:]}",
        operator_id=operator_id,
        action="RELEASE",
        authorize=authorize_control_change,
        created_at=released_at,
    )
    with transaction(sessions) as session:
        _authorize(operator_id, "RELEASE", authorize_control_change)
        session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
        _preflight(session, checked, released_at)
        _check_exact_preparation(
            session,
            checked,
            prepared.bootstrap_artifact,
            prepared.instruction_bundle,
            prepared.draft,
        )
        evaluation = record_execution_preset_evaluation(
            session,
            document=report.model_dump(mode="json"),
            report_artifact=report_artifact,
            created_by=operator_id,
        )
        released = release_execution_preset(
            session,
            draft_revision_id=prepared.draft.preset_revision_id,
            released_by=operator_id,
            released_at=released_at,
        )
        actual = validated_preset(released)
        if not isinstance(actual, ExecutionPresetRevision) or actual.state != "RELEASED":
            raise ControlPlaneError("CONTROL_BOOTSTRAP_HISTORY_INVALID", "release result differs")
        if execution_preset_policy_sha256(actual) != report.evaluated_policy_sha256:
            raise ControlPlaneError("CONTROL_BOOTSTRAP_HISTORY_INVALID", "released policy differs")
    return ReleasedInferenceTransferControls(
        actual, evaluation.evaluation_id, report_artifact, cases
    )


def _checked_inputs(
    manifest: InferenceTransferBootstrapManifest,
    observed_at: datetime,
) -> InferenceTransferBootstrapManifest:
    try:
        checked = (
            validate_inference_transfer_bootstrap_manifest_v11(manifest.model_dump(mode="json"))
            if isinstance(manifest, InferenceTransferBootstrapManifestV11)
            else validate_inference_transfer_bootstrap_manifest(manifest.model_dump(mode="json"))
        )
        now = TypeAdapter(UtcDatetime).validate_python(observed_at)
        if checked.source.reviewed_at > now:
            raise ValueError("reviewed source is in the future")
        return checked
    except (ValueError, JsonSchemaValidationError) as exc:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_INVALID", "comparison bootstrap input is invalid"
        ) from exc


def _authorize(
    operator_id: str, action: Literal["PREPARE", "RELEASE"], authorize: ControlChangeAuthorizer
) -> None:
    if re.fullmatch(r"operator_[0-9a-f]{32}", operator_id) is None or not callable(authorize):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_AUTHORIZATION_REQUIRED", "current operator authorization is required"
        )
    # The authenticated owner raises its stable permission error. Never catch
    # arbitrary bugs or turn this callback's presence into an authority grant.
    authorize(operator_id, action)


def _preflight(
    session: Session, manifest: InferenceTransferBootstrapManifest, observed_at: datetime
) -> None:
    protocol = session.get(ProtocolVersionRecord, manifest.workflow_role_schema_version)
    if protocol is None or protocol.schema_sha256 != role_schema_bundle_hash(
        manifest.workflow_role_schema_version
    ):
        raise ControlPlaneError(
            "CONTROL_PROTOCOL_POINTER_MISSING", "exact comparison protocol is unavailable"
        )
    _preflight_admission(session, manifest, observed_at)


def _preflight_admission(
    session: Session, manifest: InferenceTransferBootstrapManifest, observed_at: datetime
) -> None:
    """One authoritative read-only definition/capacity/model admission boundary."""

    try:
        definition = admitted_workflow_definition(
            session,
            definition_key=manifest.workflow_definition_key,
            definition_version=manifest.workflow_definition_version,
        )
        if definition is None:
            raise ValueError("comparison definition is not published")
        compiled = compile_definition_data(
            definition.canonical_definition, definition.source_path, {"support"}
        )
        agent_steps = tuple(
            step for step in compiled.definition.steps if isinstance(step, AgentStep)
        )
        if (
            compiled.sha256 != manifest.workflow_definition_sha256
            or compiled.sha256 != definition.definition_hash
            or len(agent_steps) != 1
            or agent_steps[0].key != "compare_pair"
            or agent_steps[0].worker_role != "support"
            or agent_steps[0].result_schema != manifest.result_schema
        ):
            raise ValueError("published comparison definition differs")
    except (ValueError, WorkflowError) as exc:
        raise ControlPlaneError(
            "CONTROL_WORKFLOW_NOT_PUBLISHED", "exact comparison definition is unavailable"
        ) from exc
    capacity = session.get(
        WorkerCapacityPolicyRevisionRecord, manifest.capacity.capacity_policy_revision_id
    )
    logical = session.get(WorkerCapacityPolicyRecord, manifest.capacity.capacity_policy_id)
    if (
        capacity is None
        or logical is None
        or logical.state != "ACTIVE"
        or logical.current_revision_id != manifest.capacity.capacity_policy_revision_id
        or capacity.capacity_policy_id != manifest.capacity.capacity_policy_id
        or capacity.schema_version != manifest.capacity.schema_version
        or capacity.state != "RELEASED"
        or capacity.content_sha256 != manifest.capacity.content_sha256
    ):
        raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "reviewed capacity pin differs")
    options = capacity_pool_model_options(
        session,
        capacity_policy_revision_id=manifest.capacity.capacity_policy_revision_id,
        role=WorkerRole.SUPPORT,
        worker_pool_key="customer-support",
        observed_at=observed_at,
    )
    if manifest.model_candidate not in options:
        raise ControlPlaneError(
            "CONTROL_PRESET_MODEL_UNAVAILABLE", "comparison candidate has no fresh admitted slot"
        )


def _description(manifest: InferenceTransferBootstrapManifest) -> str:
    return "초기 풀이 전이 비교 정책. 교육 품질 미평가. 검토 manifest " + manifest.manifest_sha256


def _require_initial_history(
    session: Session, manifest: InferenceTransferBootstrapManifest
) -> tuple[ExecutionPresetRevision, ...]:
    purpose = _purpose(manifest)
    logical = session.scalar(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_key == purpose.preset_key)
        .with_for_update()
    )
    if logical is None:
        return ()
    if logical.state != "ACTIVE":
        raise ControlPlaneError("CONTROL_PRESET_RETIRED", "comparison preset is retired")
    rows = tuple(
        session.scalars(
            select(ExecutionPresetRevisionRecord)
            .where(
                ExecutionPresetRevisionRecord.preset_id == logical.preset_id,
            )
            .order_by(ExecutionPresetRevisionRecord.revision_number)
            .limit(3)
        )
    )
    values = tuple(validated_preset(row) for row in rows)
    if len(values) > 2 or any(
        not isinstance(value, ExecutionPresetRevision)
        or value.description != _description(manifest)
        or value.state not in {"DRAFT", "RELEASED"}
        for value in values
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT", "initial comparison control history differs"
        )
    for value in values:
        policy = value.role_policies[0]
        if (
            len(value.role_policies) != 1
            or policy.instruction_bundle.bundle_id != purpose.bundle_id
            or policy.instruction_bundle.bundle_revision_id != purpose.bundle_revision_id
            or value.role_policies != (_role_policy(manifest, policy.instruction_bundle),)
            or value.capacity_policy_revision_id != manifest.capacity.capacity_policy_revision_id
            or value.compatible_workflow_protocols != (manifest.workflow_role_schema_version,)
            or value.general_knowledge_policy != "DENY"
        ):
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "initial comparison policy differs"
            )
    drafts = tuple(
        value
        for value in values
        if isinstance(value, ExecutionPresetRevision) and value.state == "DRAFT"
    )
    released = tuple(
        value
        for value in values
        if isinstance(value, ExecutionPresetRevision) and value.state == "RELEASED"
    )
    if (
        len(drafts) != 1
        or len(released) > 1
        or drafts[0].revision_number != 1
        or drafts[0].created_at != manifest.source.reviewed_at
        or (
            released
            and (
                released[0].revision_number != 2
                or logical.current_revision_id != released[0].preset_revision_id
            )
        )
        or (not released and logical.current_revision_id is not None)
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_HISTORY_INVALID", "initial comparison history is incomplete"
        )
    return drafts + released


def _role_policy(
    manifest: InferenceTransferBootstrapManifest, bundle: BundleRevisionPointer
) -> RoleExecutionPolicy:
    return RoleExecutionPolicy(
        role=WorkerRole.SUPPORT,
        model_candidates=(manifest.model_candidate,),
        instruction_bundle=bundle,
        reference_bundle=None,
        worker_pool_key="customer-support",
        timeout_seconds=manifest.timeout_seconds,
    )


def _find_or_create_draft(
    session: Session,
    manifest: InferenceTransferBootstrapManifest,
    bundle: BundleRevisionPointer,
    operator_id: str,
) -> ExecutionPresetRevision:
    history = _require_initial_history(session, manifest)
    if history:
        draft = history[0]
    else:
        created = validated_preset(
            create_execution_preset_draft(
                session,
                preset_key=_purpose(manifest).preset_key,
                display_name="문항 풀이 전이 비교",
                description=_description(manifest),
                role_policies=[_role_policy(manifest, bundle).model_dump(mode="json")],
                capacity_policy_revision_id=manifest.capacity.capacity_policy_revision_id,
                general_knowledge_policy="DENY",
                compatible_workflow_protocols=[manifest.workflow_role_schema_version],
                created_by=operator_id,
                created_at=manifest.source.reviewed_at,
            )
        )
        if not isinstance(created, ExecutionPresetRevision):
            raise ControlPlaneError("CONTROL_BOOTSTRAP_CONFLICT", "comparison requires V1")
        draft = created
    if not isinstance(draft, ExecutionPresetRevision):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT", "comparison requires the exact V1 preset"
        )
    return draft


def _check_exact_preparation(
    session: Session,
    manifest: InferenceTransferBootstrapManifest,
    bootstrap: ControlArtifactPointer,
    bundle: BundleRevisionPointer,
    draft: ExecutionPresetRevision,
) -> None:
    _resolve_publication(
        session,
        bootstrap,
        payload=_json_bytes(manifest),
        logical_name="inference-transfer-bootstrap.json",
        schema_ref=_purpose(manifest).bootstrap_schema,
        manifest=manifest,
        created_at=manifest.source.reviewed_at,
    )
    checked_bundle = BundleRevisionPointer.model_validate(bundle.model_dump(mode="json"))
    instruction = resolve_released_instruction_bundle(session, checked_bundle)
    if (
        instruction.bundle_id != _purpose(manifest).bundle_id
        or instruction.bundle_revision_id != _purpose(manifest).bundle_revision_id
        or instruction.revision_number != 1
        or instruction.created_at != manifest.source.reviewed_at
        or len(instruction.components) != 2
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT", "initial comparison instruction differs"
        )
    for component, member in zip(
        instruction.components,
        (manifest.platform_instruction, manifest.rubric_instruction),
        strict=True,
    ):
        if component.layer != member.layer or component.relative_path != member.relative_path:
            raise ControlPlaneError(
                "CONTROL_BOOTSTRAP_CONFLICT", "reviewed instruction member differs"
            )
        _resolve_publication(
            session,
            component.artifact,
            expected_sha256=member.sha256,
            logical_name=member.logical_name,
            schema_ref=member.schema_ref,
            manifest=manifest,
            created_at=manifest.source.reviewed_at,
        )
    _resolve_publication(
        session,
        checked_bundle.manifest_artifact,
        payload=_json_bytes(instruction),
        logical_name="instruction-bundle.json",
        schema_ref=_INSTRUCTION_SCHEMA,
        manifest=manifest,
        created_at=manifest.source.reviewed_at,
    )
    actual_row = session.get(ExecutionPresetRevisionRecord, draft.preset_revision_id)
    if actual_row is None:
        raise ControlPlaneError(
            "CONTROL_PRESET_DRAFT_REQUIRED", "prepared comparison draft is missing"
        )
    actual = validated_preset(actual_row)
    history = _require_initial_history(session, manifest)
    expected_policy = _role_policy(manifest, checked_bundle)
    if (
        actual != ExecutionPresetRevision.model_validate(draft.model_dump(mode="json"))
        or actual.state != "DRAFT"
        or not history
        or actual != history[0]
        or actual.role_policies != (expected_policy,)
        or actual.general_knowledge_policy != "DENY"
        or actual.capacity_policy_revision_id != manifest.capacity.capacity_policy_revision_id
        or actual.compatible_workflow_protocols != (manifest.workflow_role_schema_version,)
        or any(
            execution_preset_policy_sha256(value) != execution_preset_policy_sha256(actual)
            for value in history
        )
    ):
        raise ControlPlaneError("CONTROL_BOOTSTRAP_CONFLICT", "prepared comparison policy differs")


def _publish(
    sessions: sessionmaker[Session],
    publisher: ControlArtifactPublisher,
    *,
    manifest: InferenceTransferBootstrapManifest,
    payload: bytes,
    logical_name: str,
    schema_ref: str,
    artifact_type: str,
    component_key: str,
    operator_id: str,
    action: Literal["PREPARE", "RELEASE"],
    authorize: ControlChangeAuthorizer,
    created_at: datetime | None = None,
) -> ControlArtifactPointer:
    _authorize(operator_id, action, authorize)
    timestamp = created_at or manifest.source.reviewed_at
    # Full reviewed identity is in the publication key, so the existing
    # publisher's byte-level replay cannot silently reuse a different source.
    key_digest = content_sha256({"manifest": manifest.manifest_sha256, "component": component_key})[
        7:
    ]
    result = publisher.publish_bytes(
        payload=payload,
        logical_name=logical_name,
        schema_ref=schema_ref,
        media_type="text/markdown" if logical_name.endswith(".md") else "application/json",
        artifact_type=artifact_type,
        idempotency_key=f"inference-transfer-bootstrap:{key_digest}",
        created_at=timestamp,
        source_commit=manifest.source.source_commit,
    )
    with transaction(sessions) as session:
        _resolve_publication(
            session,
            result.pointer,
            payload=payload,
            logical_name=logical_name,
            schema_ref=schema_ref,
            manifest=manifest,
            created_at=timestamp,
        )
    return result.pointer


def _resolve_publication(
    session: Session,
    pointer: ControlArtifactPointer,
    *,
    logical_name: str,
    schema_ref: str,
    manifest: InferenceTransferBootstrapManifest,
    created_at: datetime,
    payload: bytes | None = None,
    expected_sha256: str | None = None,
) -> None:
    checked = ControlArtifactPointer.model_validate(pointer.model_dump(mode="json"))
    expected_hash = sha256_bytes(payload) if payload is not None else expected_sha256
    media = "text/markdown" if logical_name.endswith(".md") else "application/json"
    if checked.logical_name != logical_name or checked.sha256 != expected_hash:
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_CONFLICT", "published comparison member identity differs"
        )
    revision = resolve_control_artifact_pointer(
        session, checked, expected_schema_ref=schema_ref, expected_media_type=media
    )
    if (
        not isinstance(revision.result, dict)
        or revision.result.get("source_commit") != manifest.source.source_commit
        or revision.result.get("created_at_utc") != _utc_text(created_at)
    ):
        raise ControlPlaneError(
            "CONTROL_BOOTSTRAP_SOURCE_COMMIT_MISMATCH", "publication source or timestamp differs"
        )


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _json_bytes(
    value: InferenceTransferBootstrapManifest
    | InstructionBundleManifest
    | ExecutionPresetEvaluationReport,
) -> bytes:
    return canonical_json_bytes(value.model_dump(mode="json")) + b"\n"
