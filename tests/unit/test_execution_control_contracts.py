from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from eom_identifiers import content_sha256
from eom_workflow import (
    CodexAssessmentImageInputManifest,
    CodexAuthBrokerRequest,
    CodexAuthBrokerRequestV2,
    CodexAuthBrokerResponse,
    CodexAuthBrokerResponseV2,
    CodexAuthEnrollmentRequest,
    CodexAuthEnrollmentRequestV2,
    CodexAuthEnrollmentStatus,
    CodexAuthEnrollmentStatusV2,
    CodexAuthHealthView,
    CodexCapabilitySnapshot,
    CodexControlCommand,
    CodexControlCommandResult,
    CodexDeviceChallenge,
    CodexDeviceChallengeV2,
    CodexDeviceLoginStatus,
    CodexDeviceLoginStatusV2,
    CodexImageInputManifest,
    CodexInvocation,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
    InstructionBundleManifest,
    ReferenceBundleManifest,
    ResolvedExecutionPlan,
    ResolvedExecutionPlanV2,
    WorkerCapacityPolicy,
    WorkerCapacityPolicyV2,
    WorkerCapacityPolicyV3,
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


def _resolved_analysis_plan() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "resolved-execution-plan/2.0",
        "plan_id": "execplan_" + "a" * 32,
        "workflow_id": "workflow_" + "a" * 32,
        "workload_class": "KNOWLEDGE_ANALYSIS",
        "preset_id": "execpreset_" + "a" * 32,
        "preset_revision_id": "execpresetrev_" + "a" * 32,
        "preset_sha256": "sha256:" + "a" * 64,
        "workflow_definition_key": "knowledge-analysis",
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": "sha256:" + "b" * 64,
        "analysis_request_id": "knowledgeanalysis_" + "a" * 32,
        "analysis_request_sha256": "sha256:" + "c" * 64,
        "source_artifact_id": "artifact_" + "d" * 32,
        "source_artifact_revision_id": "rev_" + "d" * 32,
        "source_member_path": "source/chapter-1.pdf",
        "source_materialized_path": "source/chapter-1.pdf",
        "source_sha256": "sha256:" + "d" * 64,
        "source_bytes": 1024,
        "source_media_type": "application/pdf",
        "source_schema_ref": None,
        "capacity_policy_revision_id": "capacityrev_" + "e" * 32,
        "steps": [
            {
                "step_key": "analyze",
                "role": "support",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "instruction_bundle": _instruction_pointer(),
                "reference_bundle": None,
                "worker_pool_key": "support",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "DENIED",
            }
        ],
        "resolver_version": "2.0.0",
        "resolved_at": NOW.isoformat().replace("+00:00", "Z"),
        "plan_sha256": ZERO_SHA,
    }
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


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


def _capacity_policy_v2() -> dict[str, object]:
    value = _capacity_policy()
    value.update(
        {
            "schema_version": "worker-capacity-policy/1.1",
            "revision_number": 2,
            "max_configured_slots": 6,
            "max_active_knowledge_analysis": 2,
            "pools": [
                {
                    "pool_key": "authoring",
                    "roles": ["authoring"],
                    "slot_keys": ["slot01"],
                    "max_active": 1,
                },
                {
                    "pool_key": "review",
                    "roles": ["review"],
                    "slot_keys": ["slot02"],
                    "max_active": 1,
                },
                {
                    "pool_key": "image",
                    "roles": ["image"],
                    "slot_keys": ["slot03"],
                    "max_active": 1,
                },
                {
                    "pool_key": "item-management",
                    "roles": ["item_management"],
                    "slot_keys": ["slot04"],
                    "max_active": 1,
                },
                {
                    "pool_key": "support",
                    "roles": ["support"],
                    "slot_keys": ["slot05", "slot06"],
                    "max_active": 2,
                },
            ],
        }
    )
    return value


def _capacity_policy_v3() -> dict[str, object]:
    value = _capacity_policy_v2()
    pools = value["pools"]
    assert isinstance(pools, list)
    value.update(
        {
            "schema_version": "worker-capacity-policy/1.2",
            "revision_number": 3,
            "pools": [
                *pools[:-1],
                {
                    "pool_key": "support",
                    "roles": ["support"],
                    "slot_keys": ["slot05"],
                    "max_active": 1,
                },
                {
                    "pool_key": "legacy-extraction",
                    "roles": ["support"],
                    "slot_keys": ["slot06"],
                    "max_active": 1,
                },
            ],
        }
    )
    return value


def _slot_inventory_v2() -> dict[str, object]:
    value = yaml.safe_load(
        (REPOSITORY_ROOT / "config" / "worker-slots.example.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def _codex_invocation() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "codex-invocation/1.0",
        "plan_id": "execplan_" + "4" * 32,
        "step_key": "authoring",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "invocation_sha256": ZERO_SHA,
    }
    value["invocation_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "invocation_sha256"}
    )
    return value


def test_control_schema_resources_are_immutable_and_packaged() -> None:
    entries = control_schema_inventory()
    assert len(entries) == 45
    assert len({name for name, _ in entries}) == len(entries)
    assert {
        "execution-preset-revision-v2",
        "knowledge-item-control-bootstrap",
        "standard-control-bootstrap-v3",
        "standard-control-bootstrap-v4",
        "standard-control-bootstrap-v5",
        "standard-control-bootstrap-v6",
        "resolved-execution-plan-v3",
        "resolved-execution-plan-v4",
        "resolved-execution-plan-v5",
        "resolved-execution-plan-v6",
        "resolved-execution-plan-v7",
        "worker-capacity-policy-v3",
        "codex-auth-enrollment-request",
        "codex-auth-enrollment-status",
        "codex-device-challenge",
        "codex-device-login-status",
        "codex-auth-broker-request",
        "codex-auth-broker-response",
    }.issubset({name for name, _ in entries})
    for name, entry in entries:
        canonical = REPOSITORY_ROOT / entry.canonical_path
        packaged = RESOURCE_ROOT.joinpath(entry.resource_path.removeprefix("resources/"))
        raw = packaged.read_bytes()
        assert raw == canonical.read_bytes(), name
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == entry.sha256, name
        assert isinstance(load_control_schema(name), dict)


def test_codex_auth_v2_adds_only_slot06_and_preserves_v1() -> None:
    enrollment = {
        "schema_version": "codex-auth-enrollment-request/1.1",
        "enrollment_id": "authflow_" + "1" * 32,
        "binding_id": "authbinding_" + "2" * 32,
        "expected_binding_resource_version": 7,
        "slot_key": "slot06",
        "requested_account_label": "teacher-account-06",
        "requested_by_operator_id": "operator_" + "3" * 32,
        "requested_by_api_session_id": "apisession_" + "4" * 32,
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        "request_sha256": "sha256:" + "5" * 64,
    }
    validate_control_contract("codex-auth-enrollment-request-v2", enrollment)
    CodexAuthEnrollmentRequestV2.model_validate(enrollment)
    with pytest.raises((ValidationError, PydanticValidationError)):
        validate_control_contract(
            "codex-auth-enrollment-request",
            enrollment | {"schema_version": "codex-auth-enrollment-request/1.0"},
        )

    status = CodexDeviceLoginStatusV2(
        enrollment_id=enrollment["enrollment_id"],
        slot_key="slot06",
        state="WAITING_FOR_USER",
        reason_code=None,
        updated_at=NOW,
    )
    challenge = CodexDeviceChallengeV2(
        enrollment_id=enrollment["enrollment_id"],
        slot_key="slot06",
        verification_uri="https://auth.openai.com/codex/device",
        user_code="ABC1-DEF2",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    broker_request = CodexAuthBrokerRequestV2(
        action="REVEAL",
        enrollment_id=enrollment["enrollment_id"],
        slot_key="slot06",
    )
    response = CodexAuthBrokerResponseV2(
        outcome="OK", status=status, challenge=challenge, error_code=None
    )
    projected = CodexAuthEnrollmentStatusV2(
        enrollment_id=enrollment["enrollment_id"],
        binding_id=enrollment["binding_id"],
        slot_key="slot06",
        requested_account_label="teacher-account-06",
        state="WAITING_FOR_USER",
        challenge_available=True,
        challenge_revealed_at=None,
        assignment_revision_id=None,
        error_code=None,
        requested_at=NOW,
        started_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        completed_at=None,
        resource_version=1,
    )
    for schema_name, model in (
        ("codex-device-login-status-v2", status),
        ("codex-device-challenge-v2", challenge),
        ("codex-auth-broker-request-v2", broker_request),
        ("codex-auth-broker-response-v2", response),
        ("codex-auth-enrollment-status-v2", projected),
    ):
        validate_control_contract(schema_name, model.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("name", "value", "model"),
    [
        ("execution-preset-revision", _preset(), ExecutionPresetRevision),
        ("instruction-bundle-manifest", _instruction_manifest(), InstructionBundleManifest),
        ("reference-bundle-manifest", _reference_manifest(), ReferenceBundleManifest),
        ("resolved-execution-plan", _resolved_plan(), ResolvedExecutionPlan),
        (
            "resolved-execution-plan-v2",
            _resolved_analysis_plan(),
            ResolvedExecutionPlanV2,
        ),
        ("codex-invocation", _codex_invocation(), CodexInvocation),
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
        (
            "codex-control-command",
            {
                "schema_version": "codex-control-command/1.0",
                "command_id": "codexcmd_" + "8" * 32,
                "command_type": "DRAIN",
                "binding_id": "authbinding_" + "7" * 32,
                "expected_resource_version": 1,
                "requested_by_operator_id": "operator_" + "9" * 32,
                "requested_at": NOW.isoformat().replace("+00:00", "Z"),
                "reason_code": "ADMIN_REQUESTED_DRAIN",
                "request_sha256": "sha256:" + "8" * 64,
            },
            CodexControlCommand,
        ),
        (
            "codex-control-command-result",
            {
                "schema_version": "codex-control-command-result/1.0",
                "command_id": "codexcmd_" + "8" * 32,
                "command_type": "OBSERVE",
                "binding_id": "authbinding_" + "7" * 32,
                "outcome": "SUCCEEDED",
                "result_resource_version": 2,
                "binding_state": "READY",
                "reason_code": None,
                "processed_at": NOW.isoformat().replace("+00:00", "Z"),
                "result_sha256": "sha256:" + "6" * 64,
            },
            CodexControlCommandResult,
        ),
        (
            "codex-auth-enrollment-request",
            {
                "schema_version": "codex-auth-enrollment-request/1.0",
                "enrollment_id": "authflow_" + "1" * 32,
                "binding_id": "authbinding_" + "2" * 32,
                "expected_binding_resource_version": 7,
                "slot_key": "slot05",
                "requested_account_label": "teacher-account-01",
                "requested_by_operator_id": "operator_" + "3" * 32,
                "requested_by_api_session_id": "apisession_" + "4" * 32,
                "requested_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
                "request_sha256": "sha256:" + "5" * 64,
            },
            CodexAuthEnrollmentRequest,
        ),
        (
            "codex-auth-enrollment-status",
            {
                "schema_version": "codex-auth-enrollment-status/1.0",
                "enrollment_id": "authflow_" + "1" * 32,
                "binding_id": "authbinding_" + "2" * 32,
                "slot_key": "slot05",
                "requested_account_label": "teacher-account-01",
                "state": "WAITING_FOR_USER",
                "challenge_available": True,
                "challenge_revealed_at": None,
                "assignment_revision_id": None,
                "error_code": None,
                "requested_at": NOW.isoformat().replace("+00:00", "Z"),
                "started_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
                "completed_at": None,
                "resource_version": 4,
            },
            CodexAuthEnrollmentStatus,
        ),
        (
            "codex-device-challenge",
            {
                "schema_version": "codex-device-challenge/1.0",
                "enrollment_id": "authflow_" + "1" * 32,
                "slot_key": "slot05",
                "verification_uri": "https://auth.openai.com/codex/device",
                "user_code": "ABC1-DEF2",
                "issued_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            },
            CodexDeviceChallenge,
        ),
        (
            "codex-device-login-status",
            {
                "schema_version": "codex-device-login-status/1.0",
                "enrollment_id": "authflow_" + "1" * 32,
                "slot_key": "slot05",
                "state": "WAITING_FOR_USER",
                "reason_code": None,
                "updated_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            CodexDeviceLoginStatus,
        ),
        (
            "codex-auth-broker-request",
            {
                "schema_version": "codex-auth-broker-request/1.0",
                "action": "STATUS",
                "enrollment_id": "authflow_" + "1" * 32,
                "slot_key": "slot05",
            },
            CodexAuthBrokerRequest,
        ),
        (
            "codex-auth-broker-response",
            {
                "schema_version": "codex-auth-broker-response/1.0",
                "outcome": "OK",
                "status": {
                    "schema_version": "codex-device-login-status/1.0",
                    "enrollment_id": "authflow_" + "1" * 32,
                    "slot_key": "slot05",
                    "state": "WAITING_FOR_USER",
                    "reason_code": None,
                    "updated_at": NOW.isoformat().replace("+00:00", "Z"),
                },
                "challenge": None,
                "error_code": None,
            },
            CodexAuthBrokerResponse,
        ),
        (
            "execution-preset-evaluation-report",
            {
                "schema_version": "execution-preset-evaluation-report/1.0",
                "evaluated_preset_revision_id": "execpresetrev_" + "1" * 32,
                "evaluated_policy_sha256": "sha256:" + "1" * 64,
                "scope": "NON_LIVE",
                "outcome": "PASS",
                "summary_code": "FAKE_ADAPTER_ACCEPTANCE",
                "cases_total": 8,
                "cases_passed": 8,
                "quality_score_permille": 900,
                "completed_at": NOW.isoformat().replace("+00:00", "Z"),
                "report_sha256": "sha256:" + "9" * 64,
            },
            ExecutionPresetEvaluationReport,
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


def test_codex_invocation_rejects_hash_drift_at_typed_boundary() -> None:
    value = _codex_invocation()
    value["model"] = "gpt-5.6-luna"
    with pytest.raises(PydanticValidationError, match="hash does not match"):
        CodexInvocation.model_validate(value)


def test_codex_image_manifest_requires_complete_ordered_page_set_and_exact_hash() -> None:
    value: dict[str, object] = {
        "schema_version": "codex-image-input-manifest/1.0",
        "plan_id": "execplan_" + "8" * 32,
        "images": [
            {
                "physical_page": page,
                "relative_path": f"source/document/images/page-{page:06d}.png",
                "media_type": "image/png",
                "sha256": "sha256:" + str(page % 10) * 64,
                "bytes": 1024,
                "width_pixels": 1200,
                "height_pixels": 1800,
            }
            for page in (5, 6)
        ],
        "manifest_sha256": ZERO_SHA,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    validate_control_contract("codex-image-input-manifest", value)
    parsed = CodexImageInputManifest.model_validate(value)
    assert tuple(image.physical_page for image in parsed.images) == (5, 6)

    missing = deepcopy(value)
    images = missing["images"]
    assert isinstance(images, list)
    images[1]["physical_page"] = 7
    images[1]["relative_path"] = "source/document/images/page-000007.png"
    missing["manifest_sha256"] = content_sha256(
        {key: item for key, item in missing.items() if key != "manifest_sha256"}
    )
    with pytest.raises(PydanticValidationError, match="contiguous"):
        CodexImageInputManifest.model_validate(missing)


def test_assessment_image_manifest_bounds_decoded_pixels() -> None:
    value: dict[str, object] = {
        "schema_version": "codex-image-input-manifest/2.0",
        "plan_id": "execplan_" + "8" * 32,
        "images": [
            {
                "page_input_id": "assessmentpage_" + "1" * 32,
                "source_role": "PROBLEM_DOCUMENT",
                "physical_page": 1,
                "relative_path": "source/pages/assessmentpage_" + "1" * 32 + ".png",
                "media_type": "image/png",
                "sha256": "sha256:" + "1" * 64,
                "bytes": 1024,
                "width_pixels": 20000,
                "height_pixels": 4000,
            }
        ],
        "manifest_sha256": ZERO_SHA,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    validate_control_contract("codex-image-input-manifest-v2", value)
    with pytest.raises(PydanticValidationError, match="decoded-pixel"):
        CodexAssessmentImageInputManifest.model_validate(value)


def test_analysis_plan_is_support_only_and_hash_pinned() -> None:
    wrong_role = _resolved_analysis_plan()
    steps = wrong_role["steps"]
    assert isinstance(steps, list)
    steps[0]["role"] = "authoring"
    with pytest.raises(ValidationError):
        validate_control_contract("resolved-execution-plan-v2", wrong_role)
    with pytest.raises(PydanticValidationError, match="analyze support step"):
        ResolvedExecutionPlanV2.model_validate(wrong_role)

    stale_source = _resolved_analysis_plan()
    stale_source["source_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(PydanticValidationError, match="plan hash does not match"):
        ResolvedExecutionPlanV2.model_validate(stale_source)


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


def test_capacity_v2_schema_pins_the_two_slot_analysis_pool() -> None:
    value = _capacity_policy_v2()
    validate_control_contract("worker-capacity-policy-v2", value)
    parsed = WorkerCapacityPolicyV2.model_validate(value)
    assert parsed.max_active_knowledge_analysis == 2
    assert parsed.pools[-1].slot_keys == ("slot05", "slot06")

    wrong_support_pool = deepcopy(value)
    pools = wrong_support_pool["pools"]
    assert isinstance(pools, list)
    pools[-1]["slot_keys"] = ["slot05"]
    pools[-1]["max_active"] = 1
    with pytest.raises(ValidationError):
        validate_control_contract("worker-capacity-policy-v2", wrong_support_pool)
    with pytest.raises(PydanticValidationError, match="reviewed fixed-host pools"):
        WorkerCapacityPolicyV2.model_validate(wrong_support_pool)

    wrong_authoring_pool = deepcopy(value)
    pools = wrong_authoring_pool["pools"]
    assert isinstance(pools, list)
    pools[0]["slot_keys"] = ["slot02"]
    with pytest.raises(ValidationError):
        validate_control_contract("worker-capacity-policy-v2", wrong_authoring_pool)
    with pytest.raises(PydanticValidationError, match="reviewed fixed-host pools"):
        WorkerCapacityPolicyV2.model_validate(wrong_authoring_pool)


def test_capacity_v3_isolates_slot05_analysis_from_slot06_extraction() -> None:
    value = _capacity_policy_v3()
    validate_control_contract("worker-capacity-policy-v3", value)
    parsed = WorkerCapacityPolicyV3.model_validate(value)
    pools = {pool.pool_key: pool for pool in parsed.pools}
    assert pools["support"].slot_keys == ("slot05",)
    assert pools["legacy-extraction"].slot_keys == ("slot06",)

    shared = deepcopy(value)
    shared_pools = shared["pools"]
    assert isinstance(shared_pools, list)
    shared_pools[-2]["slot_keys"] = ["slot05", "slot06"]
    with pytest.raises(ValidationError):
        validate_control_contract("worker-capacity-policy-v3", shared)
    with pytest.raises(PydanticValidationError, match="reviewed isolated pools"):
        WorkerCapacityPolicyV3.model_validate(shared)


def test_worker_inventory_v2_schema_pins_all_fixed_slot_identities() -> None:
    value = _slot_inventory_v2()
    validate_control_contract("worker-slot-inventory-v2", value)

    wrong_role = deepcopy(value)
    slots = wrong_role["slots"]
    assert isinstance(slots, list)
    slots[-1]["role"] = "review"
    with pytest.raises(ValidationError):
        validate_control_contract("worker-slot-inventory-v2", wrong_role)

    wrong_identity = deepcopy(value)
    slots = wrong_identity["slots"]
    assert isinstance(slots, list)
    slots[-1]["linux_user"] = "eom-cdx-05"
    with pytest.raises(ValidationError):
        validate_control_contract("worker-slot-inventory-v2", wrong_identity)

    missing_slot = deepcopy(value)
    slots = missing_slot["slots"]
    assert isinstance(slots, list)
    slots.pop()
    with pytest.raises(ValidationError):
        validate_control_contract("worker-slot-inventory-v2", missing_slot)


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


def test_control_command_requires_only_operational_reason_codes() -> None:
    base = {
        "schema_version": "codex-control-command/1.0",
        "command_id": "codexcmd_" + "8" * 32,
        "command_type": "ENABLE",
        "binding_id": "authbinding_" + "7" * 32,
        "expected_resource_version": 1,
        "requested_by_operator_id": "operator_" + "9" * 32,
        "requested_at": NOW,
        "reason_code": "UNSAFE_REASON",
        "request_sha256": "sha256:" + "8" * 64,
    }
    with pytest.raises(PydanticValidationError, match="forbid one"):
        CodexControlCommand.model_validate(base)

    base["command_type"] = "DISABLE"
    base["reason_code"] = None
    with pytest.raises(PydanticValidationError, match="require a reason"):
        CodexControlCommand.model_validate(base)


def test_evaluation_report_fails_closed_on_incoherent_claims() -> None:
    report = {
        "schema_version": "execution-preset-evaluation-report/1.0",
        "evaluated_preset_revision_id": "execpresetrev_" + "1" * 32,
        "evaluated_policy_sha256": "sha256:" + "1" * 64,
        "scope": "LIVE_ONE_SHOT",
        "outcome": "PASS",
        "summary_code": "FAKE_ADAPTER_ACCEPTANCE",
        "cases_total": 2,
        "cases_passed": 1,
        "quality_score_permille": 900,
        "completed_at": NOW,
        "report_sha256": "sha256:" + "9" * 64,
    }
    with pytest.raises(PydanticValidationError, match="every evaluation case"):
        ExecutionPresetEvaluationReport.model_validate(report)

    report["cases_passed"] = 2
    with pytest.raises(PydanticValidationError, match="live acceptance summary"):
        ExecutionPresetEvaluationReport.model_validate(report)


def test_historical_role_protocol_hashes_remain_unchanged() -> None:
    assert role_schema_bundle_hash("workflow-role/1.2.0") == (
        "sha256:09c325824484d1bbcb46e14fa3007aa2b51f9750235a1969dee67b2b795d60f4"
    )
    assert role_schema_bundle_hash("workflow-role/1.3.0") == (
        "sha256:dce3e0921cf2d0d236f813101406286cb86cabaef07c95030f05028fad664ab8"
    )
