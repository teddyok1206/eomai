"""Preset-bound model availability and non-live invocation acceptance rules."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from eom_workflow import (
    CodexCapabilitySnapshot,
    CodexControlCommandResultV3,
    ExecutionPresetRevision,
    ExecutionPresetRevisionV2,
    ModelCandidate,
    ReasoningEffort,
    WorkerCapacityPolicy,
    WorkerCapacityPolicyV2,
    WorkerCapacityPolicyV3,
    WorkerCapacityPolicyV4,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexCapabilitySnapshotRecord,
    CodexControlCommandRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
    WorkerCapacityPoolRoleRecord,
    WorkerCapacityPoolSlotRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    _validate_bundle_pointer,
    compute_control_document_hash,
)
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.worker_exec import codex_command

Preset = ExecutionPresetRevision | ExecutionPresetRevisionV2
Capacity = (
    WorkerCapacityPolicy | WorkerCapacityPolicyV2 | WorkerCapacityPolicyV3 | WorkerCapacityPolicyV4
)
_CAPACITY_MODELS: dict[str, tuple[str, type[Capacity]]] = {
    "worker-capacity-policy/1.0": ("worker-capacity-policy", WorkerCapacityPolicy),
    "worker-capacity-policy/1.1": ("worker-capacity-policy-v2", WorkerCapacityPolicyV2),
    "worker-capacity-policy/1.2": ("worker-capacity-policy-v3", WorkerCapacityPolicyV3),
    "worker-capacity-policy/1.3": ("worker-capacity-policy-v4", WorkerCapacityPolicyV4),
}
_EXECUTION_EFFORTS = frozenset(str(effort) for effort in ReasoningEffort)


def validated_preset(row: ExecutionPresetRevisionRecord) -> Preset:
    if not isinstance(row.canonical_document, dict):
        raise ControlPlaneError("CONTROL_PRESET_DOCUMENT_INVALID", "preset document is invalid")
    schema = row.canonical_document.get("schema_version")
    kind = (
        ExecutionPresetRevisionV2
        if schema == "execution-preset-revision/2.0"
        else ExecutionPresetRevision
    )
    try:
        validate_control_contract(
            "execution-preset-revision-v2"
            if kind is ExecutionPresetRevisionV2
            else "execution-preset-revision",
            row.canonical_document,
        )
        model = kind.model_validate(row.canonical_document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_PRESET_DOCUMENT_INVALID", "preset document is invalid"
        ) from exc
    if (
        model.preset_revision_id != row.preset_revision_id
        or model.preset_id != row.preset_id
        or model.state != row.state
        or model.revision_number != row.revision_number
        or model.content_sha256 != row.content_sha256
        or model.content_sha256
        != compute_control_document_hash(row.canonical_document, "content_sha256")
    ):
        raise ControlPlaneError("CONTROL_PRESET_HASH_MISMATCH", "preset identity or hash differs")
    return model


def require_model_only_successor(base: Preset, draft: Preset) -> None:
    """Administrator model selection cannot replace authority or isolation policies."""

    def fixed_policy(value: Preset) -> dict[str, Any]:
        body = value.model_dump(mode="json")
        for field in (
            "preset_revision_id",
            "revision_number",
            "state",
            "content_sha256",
            "created_at",
            "display_name",
            "description",
        ):
            body.pop(field)
        for policy in body["role_policies"]:
            if policy["role"] in {"authoring", "review"}:
                # Count/order have execution meaning (ordinary vs enhanced review).
                policy["model_candidates"] = [None] * len(policy["model_candidates"])
        return body

    if (
        base.state != "RELEASED"
        or draft.state != "DRAFT"
        or fixed_policy(base) != fixed_policy(draft)
    ):
        raise ControlPlaneError(
            "CONTROL_PRESET_FIXED_POLICY_CHANGED", "model selection changed a fixed policy"
        )


def preset_model_options(
    session: Session, preset: Preset, *, observed_at: datetime
) -> dict[str, tuple[ModelCandidate, ...]]:
    """Return native-catalog ∩ reviewed-policy ∩ role/pool options, never guessed models."""

    options, _unknown_roles = _available_role_models(session, preset, observed_at=observed_at)
    return options


def capacity_pool_model_options(
    session: Session,
    *,
    capacity_policy_revision_id: str,
    role: str,
    worker_pool_key: str,
    observed_at: datetime,
) -> tuple[ModelCandidate, ...]:
    """Read fresh native ∩ reviewed options without inventing a preset or bundle.

    This exposes availability only. It neither grants operator authority nor
    reserves capacity, refreshes observations or changes a released policy.
    """

    capacity = _load_capacity(session, capacity_policy_revision_id)
    scope = (worker_pool_key, role)
    if scope not in {
        (pool.pool_key, str(value)) for pool in capacity.pools for value in pool.roles
    }:
        raise ControlPlaneError("CONTROL_PRESET_POOL_INVALID", "role is not admitted by its pool")
    options, _observed = _available_capacity_models(session, capacity, observed_at=observed_at)
    return options.get(scope, ())


def _load_capacity(session: Session, revision_id: str) -> Capacity:
    row = session.get(WorkerCapacityPolicyRevisionRecord, revision_id)
    if row is None:
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "capacity policy is unavailable"
        )
    return _validated_capacity(row, revision_id)


def resolve_released_capacity_policy(session: Session, revision_id: str) -> Capacity:
    """Resolve an exact native pin, without refreshing observations or granting access.

    The protected owner must separately authorize the current operator. The same
    canonical schema/hash/lifecycle rule used by execution remains authoritative.
    """
    return _load_capacity(session, revision_id)


def _validated_capacity(row: WorkerCapacityPolicyRevisionRecord, revision_id: str) -> Capacity:
    if not isinstance(row.canonical_document, dict):
        raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "capacity policy is invalid")
    try:
        schema, kind = _CAPACITY_MODELS[str(row.canonical_document.get("schema_version"))]
        validate_control_contract(schema, row.canonical_document)
        capacity = kind.model_validate(row.canonical_document)
    except (KeyError, JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "capacity policy is invalid"
        ) from exc
    if (
        capacity.capacity_policy_revision_id != revision_id
        or capacity.capacity_policy_revision_id != row.capacity_policy_revision_id
        or capacity.capacity_policy_id != row.capacity_policy_id
        or capacity.revision_number != row.revision_number
        or capacity.schema_version != row.schema_version
        or capacity.state != "RELEASED"
        or row.state != "RELEASED"
        or capacity.content_sha256 != row.content_sha256
        or capacity.content_sha256
        != compute_control_document_hash(row.canonical_document, "content_sha256")
    ):
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "capacity policy identity differs"
        )
    return capacity


def _validated_capability(
    row: CodexCapabilitySnapshotRecord, binding: CodexAuthBindingRecord
) -> CodexCapabilitySnapshot:
    try:
        validate_control_contract("codex-capability-snapshot", row.canonical_document)
        snapshot = CodexCapabilitySnapshot.model_validate(row.canonical_document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_INVALID", "reviewed capability is invalid"
        ) from exc
    if (
        snapshot.binding_id != binding.binding_id
        or snapshot.binding_id != row.binding_id
        or snapshot.capability_snapshot_id != row.capability_snapshot_id
        or snapshot.codex_cli_version != row.codex_cli_version
        or snapshot.source != row.source
        or snapshot.observed_at != row.observed_at
        or snapshot.valid_until != row.valid_until
        or snapshot.snapshot_sha256 != row.snapshot_sha256
        or snapshot.snapshot_sha256
        != compute_control_document_hash(row.canonical_document, "snapshot_sha256")
    ):
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_HASH_MISMATCH", "capability identity or hash differs"
        )
    return snapshot


def _native_model_pairs(
    row: CodexControlCommandRecord | None,
    *,
    binding: CodexAuthBindingRecord,
    slot: WorkerSlotRecord,
    observed_at: datetime,
) -> set[tuple[str, str]] | None:
    if (
        row is not None
        and row.result_document is not None
        and not isinstance(row.result_document, dict)
    ):
        raise ControlPlaneError(
            "CONTROL_NATIVE_CATALOG_INVALID", "native catalog result is invalid"
        )
    # Historical OBSERVE results deliberately have no native catalog. Never fabricate one.
    if (
        row is None
        or row.result_document is None
        or row.result_document.get("schema_version") != "codex-control-command-result/1.2"
    ):
        return None
    try:
        validate_control_contract("codex-control-command-result-v3", row.result_document)
        result = CodexControlCommandResultV3.model_validate(row.result_document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_NATIVE_CATALOG_INVALID", "native catalog result is invalid"
        ) from exc
    observation = result.usage_observation
    catalog = observation.model_catalog
    if (
        result.command_id != row.command_id
        or result.binding_id != row.binding_id
        or result.binding_id != binding.binding_id
        or row.command_type != "OBSERVE"
        or row.state != "SUCCEEDED"
        or result.processed_at != row.processed_at
        or result.result_resource_version != row.result_resource_version
        or observation.slot_key != f"slot{slot.slot_id}"
        or result.result_sha256
        != compute_control_document_hash(row.result_document, "result_sha256")
        or observation.observation_sha256
        != compute_control_document_hash(observation.model_dump(mode="json"), "observation_sha256")
    ):
        raise ControlPlaneError(
            "CONTROL_NATIVE_CATALOG_HASH_MISMATCH", "native catalog identity or hash differs"
        )
    if (
        catalog.state != "OBSERVED"
        or not catalog.models
        or catalog.observed_at > observed_at
        or observation.observed_at > observed_at
        or result.processed_at > observed_at
        or catalog.valid_until <= observed_at
        or catalog.codex_cli_version != binding.codex_cli_version
        or result.result_resource_version != binding.resource_version
    ):
        return None
    return {
        (model.model, effort)
        for model in catalog.models
        if not model.hidden
        for effort in model.supported_reasoning_efforts
        if effort in _EXECUTION_EFFORTS
    }


def _available_role_models(
    session: Session, preset: Preset, *, observed_at: datetime
) -> tuple[dict[str, tuple[ModelCandidate, ...]], frozenset[str]]:
    """Batch six slots and immutable snapshots; sets give O(metadata) intersections."""

    capacity = _load_capacity(session, preset.capacity_policy_revision_id)
    eligible, observed_pools = _available_capacity_models(
        session, capacity, observed_at=observed_at
    )
    options = {
        str(policy.role): eligible.get((policy.worker_pool_key, str(policy.role)), ())
        for policy in preset.role_policies
    }
    return options, frozenset(
        str(policy.role)
        for policy in preset.role_policies
        if (policy.worker_pool_key, str(policy.role)) not in observed_pools
    )


def _available_capacity_models(
    session: Session, capacity_model: Capacity, *, observed_at: datetime
) -> tuple[dict[tuple[str, str], tuple[ModelCandidate, ...]], frozenset[tuple[str, str]]]:
    """One authoritative engine for existing presets and prepublication admission."""

    revision_id = capacity_model.capacity_policy_revision_id
    pool_roles = {
        (row.pool_key, row.role)
        for row in session.scalars(
            select(WorkerCapacityPoolRoleRecord).where(
                WorkerCapacityPoolRoleRecord.capacity_policy_revision_id == revision_id
            )
        )
    }
    memberships: dict[str, set[str]] = {}
    for row in session.scalars(
        select(WorkerCapacityPoolSlotRecord).where(
            WorkerCapacityPoolSlotRecord.capacity_policy_revision_id == revision_id
        )
    ):
        memberships.setdefault(row.pool_key, set()).add(row.slot_id)
    expected_roles = {
        (pool.pool_key, str(role)) for pool in capacity_model.pools for role in pool.roles
    }
    expected_memberships = {
        pool.pool_key: {key.removeprefix("slot") for key in pool.slot_keys}
        for pool in capacity_model.pools
    }
    if pool_roles != expected_roles or memberships != expected_memberships:
        raise ControlPlaneError(
            "CONTROL_CAPACITY_POINTER_INVALID", "capacity pool projection differs"
        )
    bindings = tuple(
        session.execute(
            select(CodexAuthBindingRecord, WorkerSlotRecord).join(
                WorkerSlotRecord, WorkerSlotRecord.slot_id == CodexAuthBindingRecord.worker_slot_id
            )
        ).all()
    )
    binding_ids = tuple(binding.binding_id for binding, _slot in bindings)
    latest: dict[str, CodexCapabilitySnapshotRecord] = {}
    latest_observations: dict[str, CodexControlCommandRecord] = {}
    if binding_ids:
        # DISTINCT ON is an indexed, bounded latest-per-binding lookup in production PostgreSQL.
        statement = (
            select(CodexCapabilitySnapshotRecord)
            .where(CodexCapabilitySnapshotRecord.binding_id.in_(binding_ids))
            .distinct(CodexCapabilitySnapshotRecord.binding_id)
            .order_by(
                CodexCapabilitySnapshotRecord.binding_id,
                CodexCapabilitySnapshotRecord.observed_at.desc(),
                CodexCapabilitySnapshotRecord.capability_snapshot_id.desc(),
            )
        )
        latest = {row.binding_id: row for row in session.scalars(statement)}
        # Do not fall back to an older successful catalog when a newer observation is unavailable.
        observations = (
            select(CodexControlCommandRecord)
            .where(
                CodexControlCommandRecord.binding_id.in_(binding_ids),
                CodexControlCommandRecord.command_type == "OBSERVE",
                CodexControlCommandRecord.state == "SUCCEEDED",
            )
            .distinct(CodexControlCommandRecord.binding_id)
            .order_by(
                CodexControlCommandRecord.binding_id,
                CodexControlCommandRecord.processed_at.desc(),
                CodexControlCommandRecord.command_id.desc(),
            )
        )
        latest_observations = {row.binding_id: row for row in session.scalars(observations)}
    eligible: dict[tuple[str, str], set[tuple[str, str]]] = {}
    observed_pools: set[tuple[str, str]] = set()
    for binding, slot in bindings:
        snapshot = latest.get(binding.binding_id)
        if (
            not slot.enabled
            or binding.state != "READY"
            or binding.observed_at is None
            or binding.observed_at > observed_at
            or binding.worker_slot_id != slot.slot_id
            or binding.valid_until is None
            or binding.valid_until <= observed_at
            or snapshot is None
            or snapshot.observed_at > observed_at
            or snapshot.valid_until <= observed_at
            or snapshot.codex_cli_version != binding.codex_cli_version
        ):
            continue
        validated = _validated_capability(snapshot, binding)
        native_pairs = _native_model_pairs(
            latest_observations.get(binding.binding_id),
            binding=binding,
            slot=slot,
            observed_at=observed_at,
        )
        if native_pairs is None:
            continue
        pairs = {
            (capability.model, str(effort))
            for capability in validated.capabilities
            if capability.state == "AVAILABLE"
            for effort in capability.reasoning_efforts
        }
        pairs.intersection_update(native_pairs)
        for pool_key, members in memberships.items():
            if slot.slot_id in members and (pool_key, slot.role) in pool_roles:
                eligible.setdefault((pool_key, slot.role), set()).update(pairs)
                observed_pools.add((pool_key, str(slot.role)))
    options = {
        scope: tuple(
            ModelCandidate.model_validate({"model": model, "reasoning_effort": effort})
            for model, effort in sorted(pairs)
        )
        for scope, pairs in eligible.items()
    }
    return options, frozenset(observed_pools)


def non_live_invocation_cases(preset: Preset) -> tuple[str, ...]:
    """Execute the real worker CLI adapter against deterministic positive/negative fixtures.

    This is adapter acceptance, not inference, content quality or entitlement verification.
    Nothing is launched; a synthetic local workspace is only an argument value.
    """

    cases: list[str] = []
    workspace = Path("/srv/eom/workspaces/non-live-preset-validation")
    for policy in preset.role_policies:
        for index, candidate in enumerate(policy.model_candidates):
            transported = ModelCandidate.model_validate(json.loads(candidate.model_dump_json()))
            command = codex_command(workspace, transported.model_dump(mode="json"))
            checks = {
                "MODEL_PIN": command[command.index("--model") + 1] == candidate.model,
                "EFFORT_PIN": command[command.index("--config") + 1]
                == f'model_reasoning_effort="{candidate.reasoning_effort}"',
                "ISOLATION_PIN": command[command.index("--sandbox") + 1] == "read-only"
                and "--strict-config" in command,
                "SCHEMA_OUTPUT_PIN": command[command.index("--output-schema") + 1]
                == str(workspace / "worker-result.schema.json"),
                "INDEPENDENT_SESSION": "--ephemeral" in command
                and "--ignore-user-config" in command
                and "resume" not in command,
                "TRANSPORT_ROUNDTRIP": transported == candidate,
            }
            for key, passed in checks.items():
                if not passed:
                    raise ControlPlaneError(
                        "CONTROL_PRESET_INVOCATION_CASE_FAILED", "non-live invocation case failed"
                    )
                cases.append(f"{policy.role}:{index}:{key}")
    for effort in ("max", "ultra"):
        try:
            ModelCandidate.model_validate({"model": "gpt-fixture", "reasoning_effort": effort})
        except ValueError:
            cases.append(f"REJECT_UNSUPPORTED_{effort.upper()}")
        else:
            raise ControlPlaneError(
                "CONTROL_PRESET_INVOCATION_CASE_FAILED", "unsupported effort was accepted"
            )
    return tuple(cases)


def validate_model_selection(
    session: Session, base: Preset, draft: Preset, *, observed_at: datetime
) -> tuple[str, ...]:
    require_model_only_successor(base, draft)
    options, unknown_roles = _available_role_models(session, draft, observed_at=observed_at)
    for policy in draft.role_policies:
        if policy.role in unknown_roles:
            raise ControlPlaneError(
                "CONTROL_PRESET_MODEL_CATALOG_REQUIRED",
                "candidate needs a fresh native catalog observation",
            )
        allowed = {(item.model, str(item.reasoning_effort)) for item in options[policy.role]}
        if any(
            (item.model, str(item.reasoning_effort)) not in allowed
            for item in policy.model_candidates
        ):
            raise ControlPlaneError(
                "CONTROL_PRESET_MODEL_UNAVAILABLE", "candidate has no fresh admitted slot"
            )
        _validate_bundle_pointer(session, policy.instruction_bundle, expected_kind="INSTRUCTION")
        if policy.reference_bundle is not None:
            _validate_bundle_pointer(session, policy.reference_bundle, expected_kind="REFERENCE")
    return (
        "FIXED_POLICY_PRESERVED",
        "FRESH_ROLE_CAPABILITY",
        "RELEASED_BUNDLE_POINTERS",
        *non_live_invocation_cases(draft),
    )
