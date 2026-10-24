"""Synthetic pure routing only; no CUDA allocation, installation or execution evidence."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.embedding_device_routing import (
    EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
    EMBEDDING_DEVICE_ROUTING_SCHEMA_SHA256,
    EmbeddingDeviceRoutingDecision,
    EmbeddingDeviceRoutingError,
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    embedding_device_routing_schema,
    plan_embedding_device_route,
    validate_embedding_device_route_replay,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal, view_recipe
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_native_embedding_backend_selection import backend_document

ROOT = Path(__file__).resolve().parents[2]
Purpose = Literal["INDEX", "REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"]


def policy_document(purpose: Purpose = "INDEX") -> dict[str, Any]:
    cpu = runtime_profile("CPU").model_dump(mode="json")
    cuda = runtime_profile("CUDA").model_dump(mode="json")
    # Independent fixtures reuse IDs; an actual pair must pin different immutable revisions.
    cuda["space"]["model_spec"]["model_revision_id"] = "embeddingmodelrev_" + "f" * 32
    cuda["space"]["model_spec"] = seal(cuda["space"]["model_spec"], "manifest_sha256")
    cuda["space"] = seal(cuda["space"], "space_sha256")
    cuda["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    cuda["runtime_bundle"]["manifest_member"]["artifact_revision_id"] = "rev_" + "f" * 32
    return seal(
        {
            "schema_version": "embedding-device-routing/1.0",
            "message_type": "POLICY",
            "policy_id": "embeddingroutingpolicy_" + "1" * 32,
            "policy_revision_id": "embeddingroutingpolicyrev_" + "2" * 32,
            "purpose": purpose,
            "preferred_device": "CUDA",
            "fallback_device": "CPU",
            "fallback_on": "PRE_EXECUTION_ALLOCATION_UNAVAILABLE",
            "view_recipe_sha256": view_recipe().recipe_sha256,
            "cpu": {"backend": backend_document("CPU", purpose), "profile": cpu},
            "cuda": {"backend": backend_document("CUDA", purpose), "profile": cuda},
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        },
        "policy_sha256",
    )


def allocation_document(
    policy: EmbeddingDeviceRoutingPolicy, status: str = "ACQUIRED"
) -> dict[str, Any]:
    return seal(
        {
            "schema_version": "embedding-device-routing/1.0",
            "message_type": "ALLOCATION_OBSERVATION",
            "allocation_attempt_id": "embeddingallocation_" + "a" * 32,
            "request_sha256": sha("b"),
            "policy_sha256": policy.policy_sha256,
            "phase": "PRE_EXECUTION",
            "cuda_launch_state": "NOT_STARTED",
            "status": status,
            "allocation_reference_sha256": sha("c"),
            "observed_at": NOW.isoformat().replace("+00:00", "Z"),
        },
        "observation_sha256",
    )


def test_packaged_schema_is_pinned_isolated_and_declares_202012() -> None:
    name = "embedding-device-routing-v1.schema.json"
    canonical = (ROOT / "schemas/workflow" / name).read_bytes()
    assert canonical == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(canonical) == EMBEDDING_DEVICE_ROUTING_SCHEMA_SHA256
    schema = embedding_device_routing_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == EMBEDDING_DEVICE_ROUTING_SCHEMA_REF
    Draft202012Validator.check_schema(schema)
    for name in ("policy", "observation", "decision", "binding"):
        branch = schema["$defs"][name]
        assert branch["additionalProperties"] is False
        assert set(branch["required"]) == set(branch["properties"])
    schema["$defs"].clear()
    assert embedding_device_routing_schema()["$defs"]


@pytest.mark.parametrize("purpose", ["INDEX", "REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"])
@pytest.mark.parametrize(
    "status,device,reason",
    [
        ("ACQUIRED", "CUDA", "GPU_ALLOCATION_ACQUIRED"),
        ("BUSY", "CPU", "GPU_BUSY_CPU_FALLBACK"),
        ("CAPACITY_UNAVAILABLE", "CPU", "GPU_CAPACITY_CPU_FALLBACK"),
    ],
)
def test_deterministic_allocation_only_route_preserves_exact_runtime(
    purpose: Purpose, status: str, device: str, reason: str
) -> None:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document(purpose))
    observation = EmbeddingGpuAllocationObservation.model_validate(
        allocation_document(policy, status)
    )
    decision = plan_embedding_device_route(policy, observation)
    assert decision.selected == (policy.cuda if device == "CUDA" else policy.cpu)
    assert decision.selected.backend.device == device
    assert decision.selected.backend.purpose == purpose
    assert decision.reason == reason
    assert decision.request_sha256 == observation.request_sha256
    assert decision.policy_sha256 == policy.policy_sha256
    assert decision.allocation_observation_sha256 == observation.observation_sha256
    assert decision.allocation_attempt_id == observation.allocation_attempt_id
    assert decision.decision_sha256 == content_sha256(
        decision.model_dump(mode="json", exclude={"decision_sha256"})
    )
    assert validate_embedding_device_route_replay(policy, observation, decision) == decision
    assert plan_embedding_device_route(policy, observation) == decision
    assert policy.cpu.profile.space.space_sha256 != policy.cuda.profile.space.space_sha256
    with pytest.raises(ValueError):
        decision.reason = "GPU_BUSY_CPU_FALLBACK"


@pytest.mark.parametrize(
    "status",
    [
        "INVALID",
        "UNKNOWN",
        "OOM",
        "HASH_MISMATCH",
        "UNAUTHORIZED",
        "STARTED",
        "ACKNOWLEDGED",
        "CLEANUP_UNCERTAIN",
        "CONFIGURATION_INVALID",
        "CUDA_UNAVAILABLE",
        True,
        None,
    ],
)
def test_errors_and_uncertain_execution_cannot_be_fallback_outcomes(status: Any) -> None:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document())
    body = allocation_document(policy)
    body["status"] = status
    with pytest.raises(ValueError):
        EmbeddingGpuAllocationObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("phase", "POST_EXECUTION"),
        ("phase", "PRE_ACK"),
        ("cuda_launch_state", "STARTED"),
        ("cuda_launch_state", "UNKNOWN"),
        ("allocation_attempt_id", "embeddingallocation_" + "f" * 31),
        ("observed_at", "2026-10-24T09:00:00+09:00"),
        ("observed_at", "2026-10-24T09:00:00"),
        ("request_sha256", "sha256:" + "z" * 64),
        ("allocation_reference_sha256", ""),
    ],
)
def test_pre_execution_provenance_is_closed(field: str, value: Any) -> None:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document())
    body = allocation_document(policy, "BUSY")
    body[field] = value
    with pytest.raises(ValueError):
        EmbeddingGpuAllocationObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize(
    "fault",
    [
        "swapped",
        "backend_device",
        "backend_purpose",
        "model_weights",
        "query_prefix",
        "model_origin",
        "microbatch",
        "threads",
        "runtime_hash",
        "bundle_revision",
        "artifact_revision",
        "model_revision_conflict",
        "policy_hash",
        "bool_threads",
    ],
)
def test_pair_rejects_semantic_or_identity_mismatch(fault: str) -> None:
    body = policy_document()
    cpu, cuda = body["cpu"]["profile"], body["cuda"]["profile"]
    if fault == "swapped":
        body["cpu"], body["cuda"] = body["cuda"], body["cpu"]
    elif fault == "backend_device":
        body["cuda"]["backend"] = backend_document("CPU")
    elif fault == "backend_purpose":
        body["cuda"]["backend"]["purpose"] = "REFERENCE_QUERY"
    elif fault in ("model_weights", "query_prefix", "model_origin"):
        spec = cuda["space"]["model_spec"]
        if fault == "model_weights":
            spec["files"][0]["sha256"] = sha("f")
        elif fault == "query_prefix":
            spec["query_prefix"] = "" if spec["query_prefix"] == "query: " else "query: "
        else:
            spec["upstream_revision"] = "f" * 40
        cuda["space"]["model_spec"] = seal(spec, "manifest_sha256")
        cuda["space"] = seal(cuda["space"], "space_sha256")
    elif fault in ("microbatch", "threads", "bool_threads"):
        field = "batch_size" if fault == "microbatch" else "threads"
        cuda["resource_profile"][field] = True if fault == "bool_threads" else 3
        cuda["resource_profile"] = seal(cuda["resource_profile"], "resource_profile_sha256")
    elif fault == "runtime_hash":
        cuda["space"]["runtime"]["execution_runtime_sha256"] = cpu["space"]["runtime"][
            "execution_runtime_sha256"
        ]
        cuda["space"] = seal(cuda["space"], "space_sha256")
    elif fault == "bundle_revision":
        cuda["runtime_bundle"]["bundle_revision_id"] = cpu["runtime_bundle"]["bundle_revision_id"]
    elif fault == "artifact_revision":
        cuda["runtime_bundle"]["manifest_member"]["artifact_revision_id"] = cpu["runtime_bundle"][
            "manifest_member"
        ]["artifact_revision_id"]
    elif fault == "model_revision_conflict":
        cuda["space"]["model_spec"]["model_revision_id"] = cpu["space"]["model_spec"][
            "model_revision_id"
        ]
        cuda["space"]["model_spec"] = seal(cuda["space"]["model_spec"], "manifest_sha256")
        cuda["space"] = seal(cuda["space"], "space_sha256")
    body = seal(body, "policy_sha256")
    if fault == "policy_hash":
        body["policy_sha256"] = sha("f")
    with pytest.raises(ValueError):
        EmbeddingDeviceRoutingPolicy.model_validate(body)


@pytest.mark.parametrize("kind", ["POLICY", "ALLOCATION_OBSERVATION", "DECISION"])
def test_required_fields_extra_values_and_hash_are_not_coerced(kind: str) -> None:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document())
    observation = EmbeddingGpuAllocationObservation.model_validate(allocation_document(policy))
    decision = plan_embedding_device_route(policy, observation)
    model = {
        "POLICY": policy,
        "ALLOCATION_OBSERVATION": observation,
        "DECISION": decision,
    }[kind]
    body = model.model_dump(mode="json")
    for name in body:
        missing = deepcopy(body)
        del missing[name]
        with pytest.raises(ValueError):
            type(model).model_validate(missing)
    extra = body | {"permission": "ADMIN"}
    with pytest.raises(ValueError):
        type(model).model_validate(extra)
    hash_name = {
        "POLICY": "policy_sha256",
        "ALLOCATION_OBSERVATION": "observation_sha256",
        "DECISION": "decision_sha256",
    }[kind]
    body[hash_name] = sha("f")
    with pytest.raises(ValueError):
        type(model).model_validate(body)


def test_replay_keeps_cpu_choice_and_rejects_new_availability_or_foreign_scope() -> None:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document())
    busy = EmbeddingGpuAllocationObservation.model_validate(allocation_document(policy, "BUSY"))
    original = plan_embedding_device_route(policy, busy)
    assert validate_embedding_device_route_replay(policy, busy, original) == original
    now_free = EmbeddingGpuAllocationObservation.model_validate(allocation_document(policy))
    with pytest.raises(EmbeddingDeviceRoutingError):
        validate_embedding_device_route_replay(policy, now_free, original)
    for field in ("request_sha256", "allocation_attempt_id", "policy_sha256"):
        body = busy.model_dump(mode="json")
        body[field] = "embeddingallocation_" + "f" * 32 if field.endswith("id") else sha("f")
        other = EmbeddingGpuAllocationObservation.model_validate(seal(body, "observation_sha256"))
        with pytest.raises(EmbeddingDeviceRoutingError):
            validate_embedding_device_route_replay(policy, other, original)
    body = policy.model_dump(mode="json")
    body["policy_revision_id"] = "embeddingroutingpolicyrev_" + "f" * 32
    other_policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(body, "policy_sha256"))
    with pytest.raises(EmbeddingDeviceRoutingError):
        plan_embedding_device_route(other_policy, busy)


def test_copied_or_constructed_models_cannot_smuggle_invalid_nested_values() -> None:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document())
    observation = EmbeddingGpuAllocationObservation.model_validate(allocation_document(policy))
    decision = plan_embedding_device_route(policy, observation)
    for forged_policy in (
        policy.model_copy(update={"fallback_on": "ANY_ERROR"}),
        policy.model_copy(update={"injected_authority": "ADMIN"}),
        policy.model_copy(
            update={
                "cpu": policy.cpu.model_copy(
                    update={
                        "profile": policy.cpu.profile.model_copy(
                            update={
                                "resource_profile": policy.cpu.profile.resource_profile.model_copy(
                                    update={"threads": True}
                                )
                            }
                        )
                    }
                )
            }
        ),
        EmbeddingDeviceRoutingPolicy.model_construct(**{"policy_sha256": policy.policy_sha256}),
    ):
        with pytest.raises(EmbeddingDeviceRoutingError):
            plan_embedding_device_route(forged_policy, observation)
    forged_observation = observation.model_copy(update={"status": "OOM"})
    with pytest.raises(EmbeddingDeviceRoutingError):
        plan_embedding_device_route(policy, forged_observation)
    forged_decision = decision.model_copy(update={"selected": policy.cpu})
    with pytest.raises(EmbeddingDeviceRoutingError):
        validate_embedding_device_route_replay(policy, observation, forged_decision)


@pytest.mark.parametrize("fault", ["backend_pin", "request", "allocation_evidence"])
def test_resealed_but_foreign_decision_is_rejected_by_original_replay(fault: str) -> None:
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_document())
    observation = EmbeddingGpuAllocationObservation.model_validate(
        allocation_document(policy, "BUSY")
    )
    decision = plan_embedding_device_route(policy, observation)
    body = decision.model_dump(mode="json")
    if fault == "backend_pin":
        body["selected"]["backend"]["backend"]["cpu_environment_raw_sha256"] = sha("f")
    elif fault == "request":
        body["request_sha256"] = sha("f")
    else:
        body["allocation_observation_sha256"] = sha("f")
    foreign = EmbeddingDeviceRoutingDecision.model_validate(seal(body, "decision_sha256"))
    with pytest.raises(EmbeddingDeviceRoutingError):
        validate_embedding_device_route_replay(policy, observation, foreign)


def test_pure_contract_has_no_runtime_infrastructure_dependencies() -> None:
    path = ROOT / "packages/workflow/eom_workflow/embedding_device_routing.py"
    tree = ast.parse(path.read_text())
    forbidden = (
        "torch",
        "transformers",
        "sqlalchemy",
        "subprocess",
        "socket",
        "eom_gpu_lease",
        "eom_orchestrator",
        "eom_catalog_service",
        "eom_workflow_runner",
    )
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(name.startswith(forbidden) for name in imports)
