from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import pytest
from eom_workflow import (
    CodexAuthHealthView,
    CodexCapabilitySnapshot,
    ExecutionPresetRevision,
    InstructionBundleManifest,
    ReferenceBundleManifest,
    ResolvedExecutionPlan,
    WorkerCapacityPolicy,
    WorkerLeaseView,
    control_schema_inventory,
    load_control_schema,
    validate_control_contract,
)
from eom_workflow.schemas import role_schema_bundle_hash
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = files("eom_workflow").joinpath("resources")
NOW = datetime(2026, 8, 23, 1, 2, 3, tzinfo=UTC)
ZERO_SHA = "sha256:" + "0" * 64


def _artifact(seed: str = "1", *, logical_name: str = "manifest.json") -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
        "media_type": "application/json",
        "logical_name": logical_name,
    }


def _instruction_pointer() -> dict[str, object]:
    return {
        "bundle_id": "instrbundle_" + "1" * 32,
        "bundle_revision_id": "instrrev_" + "1" * 32,
        "manifest_artifact": _artifact("1"),
        "manifest_sha256": "sha256:" + "1" * 64,
    }


def _reference_pointer() -> dict[str, object]:
    return {
        "bundle_id": "refbundle_" + "2" * 32,
        "bundle_revision_id": "refrev_" + "2" * 32,
        "manifest_artifact": _artifact("2"),
        "manifest_sha256": "sha256:" + "2" * 64,
    }


def _preset() -> dict[str, object]:
    return {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "1" * 32,
        "preset_revision_id": "execpresetrev_" + "1" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "Standard item",
        "description": "Pinned standard item execution policy.",
        "role_policies": [
            {
                "role": "authoring",
                "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
                "instruction_bundle": _instruction_pointer(),
                "reference_bundle": _reference_pointer(),
                "worker_pool_key": "authoring",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
            }
        ],
        "capacity_policy_revision_id": "capacityrev_" + "1" * 32,
        "general_knowledge_policy": "ALLOW_WITH_PROVENANCE",
        "compatible_workflow_protocols": ["workflow-role/1.3.0"],
        "content_sha256": ZERO_SHA,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _instruction_manifest() -> dict[str, object]:
    return {
        "schema_version": "instruction-bundle-manifest/1.0",
        "bundle_id": "instrbundle_" + "1" * 32,
        "bundle_revision_id": "instrrev_" + "1" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "components": [
            {
                "layer": "PLATFORM",
                "relative_path": "instructions/AGENTS.md",
                "artifact": {
                    **_artifact("3", logical_name="AGENTS.md"),
                    "media_type": "text/markdown",
                },
            }
        ],
        "content_sha256": ZERO_SHA,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _reference_manifest() -> dict[str, object]:
    return {
        "schema_version": "reference-bundle-manifest/1.0",
        "bundle_id": "refbundle_" + "2" * 32,
        "bundle_revision_id": "refrev_" + "2" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "entries": [
            {
                "reference_key": "curriculum-earth",
                "source_class": "CURRICULUM",
                "relative_path": "references/curriculum/earth.md",
                "source_logical_id": "document_" + "3" * 32,
                "source_revision_id": "documentrev_" + "3" * 32,
                "rights_policy_revision_id": "rightsrev_" + "3" * 32,
                "artifact": {
                    **_artifact("3", logical_name="earth.md"),
                    "media_type": "text/markdown",
                },
            }
        ],
        "content_sha256": ZERO_SHA,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _resolved_plan() -> dict[str, object]:
    return {
        "schema_version": "resolved-execution-plan/1.0",
        "plan_id": "execplan_" + "4" * 32,
        "workflow_id": "workflow_" + "4" * 32,
        "preset_id": "execpreset_" + "1" * 32,
        "preset_revision_id": "execpresetrev_" + "1" * 32,
        "preset_sha256": "sha256:" + "1" * 64,
        "workflow_definition_key": "generic-item-development",
        "workflow_definition_version": "1.4.0",
        "workflow_definition_sha256": "sha256:" + "2" * 64,
        "content_pack_release_id": "packrel_" + "3" * 32,
        "content_pack_sha256": "sha256:" + "3" * 64,
        "capacity_policy_revision_id": "capacityrev_" + "4" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "5" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "5" * 32,
        "steps": [
            {
                "step_key": "authoring",
                "role": "authoring",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "instruction_bundle": _instruction_pointer(),
                "reference_bundle": _reference_pointer(),
                "worker_pool_key": "authoring",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "ALLOWED_WITH_PROVENANCE",
            }
        ],
        "resolver_version": "1.0.0",
        "resolved_at": NOW.isoformat().replace("+00:00", "Z"),
        "plan_sha256": "sha256:" + "4" * 64,
    }


def _capacity_policy() -> dict[str, object]:
    return {
        "schema_version": "worker-capacity-policy/1.0",
        "capacity_policy_id": "capacity_" + "6" * 32,
        "capacity_policy_revision_id": "capacityrev_" + "6" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "max_configured_slots": 5,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 1,
        "pools": [
            {
                "pool_key": "authoring",
                "roles": ["authoring"],
                "slot_keys": ["slot01"],
                "max_active": 1,
            },
            {
                "pool_key": "support",
                "roles": ["support"],
                "slot_keys": ["slot05"],
                "max_active": 1,
            },
        ],
        "content_sha256": "sha256:" + "6" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def test_control_schema_resources_are_immutable_and_packaged() -> None:
    entries = control_schema_inventory()
    assert len(entries) == 9
    assert len({name for name, _ in entries}) == len(entries)
    for name, entry in entries:
        canonical = REPOSITORY_ROOT / entry.canonical_path
        packaged = RESOURCE_ROOT.joinpath(entry.resource_path.removeprefix("resources/"))
        raw = packaged.read_bytes()
        assert raw == canonical.read_bytes(), name
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == entry.sha256, name
        assert isinstance(load_control_schema(name), dict)


@pytest.mark.parametrize(
    ("name", "value", "model"),
    [
        ("execution-preset-revision", _preset(), ExecutionPresetRevision),
        ("instruction-bundle-manifest", _instruction_manifest(), InstructionBundleManifest),
        ("reference-bundle-manifest", _reference_manifest(), ReferenceBundleManifest),
        ("resolved-execution-plan", _resolved_plan(), ResolvedExecutionPlan),
        (
            "codex-auth-health-view",
            {
                "schema_version": "codex-auth-health-view/1.0",
                "binding_id": "authbinding_" + "7" * 32,
                "slot_key": "slot01",
                "account_label": "worker-account-01",
                "state": "READY",
                "reason_code": None,
                "codex_cli_version": "0.147.0",
                "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                "valid_until": (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            },
            CodexAuthHealthView,
        ),
        (
            "codex-capability-snapshot",
            {
                "schema_version": "codex-capability-snapshot/1.0",
                "capability_snapshot_id": "capsnap_" + "7" * 32,
                "binding_id": "authbinding_" + "7" * 32,
                "codex_cli_version": "0.147.0",
                "source": "LOCAL_OBSERVATION",
                "capabilities": [
                    {
                        "model": "gpt-5.6-terra",
                        "reasoning_efforts": ["low", "medium", "high"],
                        "state": "AVAILABLE",
                    }
                ],
                "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                "valid_until": (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
                "snapshot_sha256": "sha256:" + "7" * 64,
            },
            CodexCapabilitySnapshot,
        ),
        ("worker-capacity-policy", _capacity_policy(), WorkerCapacityPolicy),
        (
            "worker-lease-view",
            {
                "schema_version": "worker-lease-view/1.0",
                "lease_id": "workerlease_" + "8" * 32,
                "capacity_policy_revision_id": "capacityrev_" + "6" * 32,
                "pool_key": "authoring",
                "slot_key": "slot01",
                "binding_id": "authbinding_" + "7" * 32,
                "workflow_id": "workflow_" + "8" * 32,
                "job_id": "job_" + "8" * 32,
                "attempt": 1,
                "state": "ACTIVE",
                "acquired_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
                "released_at": None,
                "release_reason": None,
            },
            WorkerLeaseView,
        ),
    ],
)
def test_control_contracts_validate_at_schema_and_typed_boundaries(
    name: str, value: dict[str, object], model: type[object]
) -> None:
    validate_control_contract(name, value)
    validator = model.model_validate
    assert validator(value)


def test_control_contracts_reject_secrets_and_unknown_fields() -> None:
    for forbidden in ("credential", "access_token", "session_id", "raw_prompt", "nas_path"):
        value = {**_preset(), forbidden: "<redacted>"}
        with pytest.raises(ValidationError):
            validate_control_contract("execution-preset-revision", value)
        with pytest.raises(PydanticValidationError):
            ExecutionPresetRevision.model_validate(value)


def test_materialization_paths_are_relative_markdown_and_contained() -> None:
    for unsafe in (
        "/etc/eom/AGENTS.md",
        "instructions/../secrets.md",
        "references/evidence.txt",
    ):
        value = _instruction_manifest()
        components = value["components"]
        assert isinstance(components, list)
        components[0]["relative_path"] = unsafe
        with pytest.raises(ValidationError):
            validate_control_contract("instruction-bundle-manifest", value)
        with pytest.raises(PydanticValidationError):
            InstructionBundleManifest.model_validate(value)


def test_ordered_model_policy_is_bounded_and_deduplicated() -> None:
    value = _preset()
    role_policies = value["role_policies"]
    assert isinstance(role_policies, list)
    candidate = {"model": "gpt-5.6-terra", "reasoning_effort": "high"}
    role_policies[0]["model_candidates"] = [candidate, candidate]
    with pytest.raises(PydanticValidationError, match="model candidates must be unique"):
        ExecutionPresetRevision.model_validate(value)

    invalid_effort = deepcopy(_preset())
    invalid_policies = invalid_effort["role_policies"]
    assert isinstance(invalid_policies, list)
    invalid_policies[0]["model_candidates"] = [
        {"model": "gpt-5.6-terra", "reasoning_effort": "ultra"}
    ]
    with pytest.raises(ValidationError):
        validate_control_contract("execution-preset-revision", invalid_effort)


def test_plan_requires_snapshot_for_evidence_and_unique_steps() -> None:
    missing_snapshot = _resolved_plan()
    missing_snapshot["graph_snapshot_revision_id"] = None
    with pytest.raises(PydanticValidationError, match="requires its pinned Graph Snapshot"):
        ResolvedExecutionPlan.model_validate(missing_snapshot)

    duplicate = _resolved_plan()
    steps = duplicate["steps"]
    assert isinstance(steps, list)
    steps.append(deepcopy(steps[0]))
    with pytest.raises(PydanticValidationError, match="step keys must be unique"):
        ResolvedExecutionPlan.model_validate(duplicate)


def test_capacity_contract_pins_host_limits_and_rejects_overcommit() -> None:
    value = _capacity_policy()
    validate_control_contract("worker-capacity-policy", value)
    parsed = WorkerCapacityPolicy.model_validate(value)
    assert (parsed.max_configured_slots, parsed.max_active_codex) == (5, 3)
    assert parsed.max_active_per_slot == parsed.max_active_gpu == 1

    overcommitted = deepcopy(value)
    overcommitted["max_configured_slots"] = 2
    with pytest.raises(PydanticValidationError, match="global active limit"):
        WorkerCapacityPolicy.model_validate(overcommitted)


def test_health_and_lease_windows_fail_closed() -> None:
    health = {
        "schema_version": "codex-auth-health-view/1.0",
        "binding_id": "authbinding_" + "7" * 32,
        "slot_key": "slot01",
        "account_label": "worker-account-01",
        "state": "AUTH_REQUIRED",
        "reason_code": None,
        "codex_cli_version": "0.147.0",
        "observed_at": NOW,
        "valid_until": NOW + timedelta(minutes=1),
    }
    with pytest.raises(PydanticValidationError, match="requires a reason code"):
        CodexAuthHealthView.model_validate(health)

    active = {
        "schema_version": "worker-lease-view/1.0",
        "lease_id": "workerlease_" + "8" * 32,
        "capacity_policy_revision_id": "capacityrev_" + "6" * 32,
        "pool_key": "authoring",
        "slot_key": "slot01",
        "binding_id": "authbinding_" + "7" * 32,
        "workflow_id": "workflow_" + "8" * 32,
        "job_id": "job_" + "8" * 32,
        "attempt": 1,
        "state": "ACTIVE",
        "acquired_at": NOW,
        "expires_at": NOW + timedelta(minutes=30),
        "released_at": NOW + timedelta(minutes=1),
        "release_reason": "JOB_SUCCEEDED",
    }
    with pytest.raises(PydanticValidationError, match="terminal lease state"):
        WorkerLeaseView.model_validate(active)


def test_historical_role_protocol_hashes_remain_unchanged() -> None:
    assert role_schema_bundle_hash("workflow-role/1.2.0") == (
        "sha256:09c325824484d1bbcb46e14fa3007aa2b51f9750235a1969dee67b2b795d60f4"
    )
    assert role_schema_bundle_hash("workflow-role/1.3.0") == (
        "sha256:dce3e0921cf2d0d236f813101406286cb86cabaef07c95030f05028fad664ab8"
    )
