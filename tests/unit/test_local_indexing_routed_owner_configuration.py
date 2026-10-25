"""Pure config5 and source pairing; no actual grant, runtime, model or allocation."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_device_routing import (
    EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
    EmbeddingDeviceRoutingPolicy,
)
from eom_workflow.local_indexing_owner_configuration import (
    parse_cpu_local_indexing_owner_configuration,
    parse_local_indexing_owner_configuration,
    parse_supported_local_indexing_owner_configuration,
)
from eom_workflow.local_indexing_routed_owner_configuration import (
    LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_REF,
    LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_SHA256,
    RoutedLocalIndexingOwnerConfiguration,
    local_indexing_routed_owner_configuration_bytes,
    local_indexing_routed_owner_configuration_schema,
    parse_local_indexing_routed_owner_configuration,
    require_routed_indexing_policy,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member
from tests.unit.test_embedding_device_routing import policy_document
from tests.unit.test_local_indexing_dual_projection_owner import dual_document
from tests.unit.test_local_indexing_owner_configuration import document

ROOT = Path(__file__).resolve().parents[2]


def routed_document(*, dual=False):
    cpu = dual_document() if dual else document()
    cpu["runtime_profile"]["resource_profile"] = seal(
        cpu["runtime_profile"]["resource_profile"] | {"timeout_seconds": 180},
        "resource_profile_sha256",
    )
    groups = [cpu]
    if dual:
        cpu["legacy_configuration"]["runtime_profile"] = deepcopy(cpu["runtime_profile"])
        groups.append(cpu["legacy_configuration"])
    policy = policy_document("INDEX")
    policy["cpu"]["profile"] = deepcopy(cpu["runtime_profile"])
    policy["cpu"]["backend"]["backend"].update(
        runtime_verifier=cpu["runtime_verifier"],
        cpu_environment_raw_sha256=cpu["cpu_environment_raw_sha256"],
    )
    policy["cuda"]["profile"]["resource_profile"] = seal(
        policy["cuda"]["profile"]["resource_profile"] | {"timeout_seconds": 180},
        "resource_profile_sha256",
    )
    policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(policy, "policy_sha256"))
    grants = []
    for index, selected in enumerate(groups):
        seed = str(index + 8)
        grants.append(
            dict(
                cpu_service_policy_revision_id=selected["service_policy_revision_id"],
                service_policy_revision_id="accessrev_" + seed * 32,
                service_policy_sha256="sha256:" + seed * 64,
                native_execution_policy=selected["native_execution_policy"]
                | {
                    "artifact_revision_id": "rev_" + seed * 32,
                    "sha256": "sha256:" + seed * 64,
                },
                native_execution_policy_sha256="sha256:" + seed * 64,
            )
        )
    return dict(
        schema_version="local-indexing-owner-configuration/5.0",
        cpu_configuration=cpu,
        cuda_runtime_profile=policy.cuda.profile.model_dump(mode="json"),
        cuda_backend=policy.cuda.backend.model_dump(mode="json"),
        cuda_grants=grants,
        routing_policy=member(
            "policy.json", EMBEDDING_DEVICE_ROUTING_SCHEMA_REF, policy, "7"
        ).model_dump(mode="json"),
        routing_policy_sha256=policy.policy_sha256,
        controller_release="a" * 40,
    ), policy


@pytest.mark.parametrize("dual", (False, True))
def test_config5_schema_and_roundtrip_preserve_explicit_cpu_and_cuda_group_pins(dual):
    raw = (ROOT / "schemas/workflow/local-indexing-owner-configuration-v5.schema.json").read_bytes()
    assert (
        raw
        == (
            ROOT
            / "packages/workflow/eom_workflow/resources"
            / "local-indexing-owner-configuration-v5.schema.json"
        ).read_bytes()
    )
    assert sha256_bytes(raw) == LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_SHA256
    schema = local_indexing_routed_owner_configuration_schema()
    assert schema["$id"] == LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_REF
    Draft202012Validator.check_schema(schema)
    body, policy = routed_document(dual=dual)
    selected = RoutedLocalIndexingOwnerConfiguration.model_validate(body)
    wire = local_indexing_routed_owner_configuration_bytes(selected)
    assert wire == canonical_json_bytes(body)
    assert parse_local_indexing_routed_owner_configuration(wire) == selected
    require_routed_indexing_policy(selected, policy)
    assert len(selected.groups) == (2 if dual else 1)
    for group in selected.groups:
        gpu_namespaces = group.cuda_namespaces(selected.cuda_runtime_profile)
        for cpu_ns, gpu_ns in zip(group.cpu.namespaces, gpu_namespaces, strict=True):
            assert type(cpu_ns) is type(gpu_ns)
            assert cpu_ns.space_sha256 != gpu_ns.space_sha256
            assert gpu_ns.model_dump(mode="json") == cpu_ns.model_dump(mode="json") | {
                "space_sha256": selected.cuda_runtime_profile.space.space_sha256
            }
    for old_parser in (
        parse_cpu_local_indexing_owner_configuration,
        parse_local_indexing_owner_configuration,
        parse_supported_local_indexing_owner_configuration,
    ):
        with pytest.raises(ValueError):
            old_parser(wire)


@pytest.mark.parametrize(
    "fault",
    (
        "device",
        "cpu_timeout",
        "cuda_timeout",
        "same_space",
        "wrong_grant",
        "missing_grant",
        "duplicate_grant",
        "reordered_grants",
        "same_grant",
        "same_grant_hash",
        "same_policy_hash",
        "query_backend",
        "unknown",
        "latest",
        "wrong_member",
        "wrong_schema",
        "wrong_media",
    ),
)
def test_config5_never_invents_scope_backend_or_unbounded_budget(fault):
    body, _policy = routed_document(dual=True)
    if fault == "device":
        body["cuda_runtime_profile"]["resource_profile"]["device"] = "CPU"
    elif fault in {"cpu_timeout", "cuda_timeout"}:
        profile = (
            body["cpu_configuration"]["runtime_profile"]
            if fault == "cpu_timeout"
            else body["cuda_runtime_profile"]
        )
        profile["resource_profile"] = seal(
            profile["resource_profile"] | {"timeout_seconds": 181}, "resource_profile_sha256"
        )
    elif fault == "same_space":
        body["cuda_runtime_profile"] = deepcopy(body["cpu_configuration"]["runtime_profile"])
    elif fault == "wrong_grant":
        wrong = "accessrev_" + "0" * 32
        assert wrong not in {g["cpu_service_policy_revision_id"] for g in body["cuda_grants"]}
        body["cuda_grants"][0]["cpu_service_policy_revision_id"] = wrong
    elif fault == "missing_grant":
        body["cuda_grants"].pop()
    elif fault == "duplicate_grant":
        body["cuda_grants"][1] = deepcopy(body["cuda_grants"][0])
    elif fault == "reordered_grants":
        body["cuda_grants"].reverse()
    elif fault in {"same_grant", "same_grant_hash", "same_policy_hash"}:
        field = {
            "same_grant": "service_policy_revision_id",
            "same_grant_hash": "service_policy_sha256",
            "same_policy_hash": "native_execution_policy_sha256",
        }[fault]
        body["cuda_grants"][0][field] = body["cpu_configuration"][field]
    elif fault == "query_backend":
        body["cuda_backend"]["purpose"] = "REFERENCE_QUERY"
    elif fault == "unknown":
        body["operator_id"] = "operator_" + "a" * 32
    elif fault == "latest":
        body["controller_release"] = "latest"
    else:
        field, value = {
            "wrong_member": ("member_path", "source.json"),
            "wrong_schema": ("schema_ref", "wrong"),
            "wrong_media": ("media_type", "image/png"),
        }[fault]
        body["routing_policy"][field] = value
    with pytest.raises(ValueError):
        RoutedLocalIndexingOwnerConfiguration.model_validate(body)


@pytest.mark.parametrize(
    "fault", ("copy_extra", "wire_extra", "duplicate", "noncanonical", "oversize")
)
def test_config5_copy_and_wire_mutations_are_rejected_before_lossy_conversion(fault):
    body, _policy = routed_document()
    selected = RoutedLocalIndexingOwnerConfiguration.model_validate(body)
    if fault == "copy_extra":
        with pytest.raises(ValueError):
            local_indexing_routed_owner_configuration_bytes(
                selected.model_copy(update={"roles": ["ADMIN"]})
            )
        return
    raw = canonical_json_bytes(body)
    if fault == "wire_extra":
        raw = canonical_json_bytes(body | {"roles": ["ADMIN"]})
    elif fault == "duplicate":
        raw = raw[:-1] + b',"schema_version":"local-indexing-owner-configuration/5.0"}'
    elif fault == "noncanonical":
        raw += b"\n"
    else:
        raw = b" " * (64 * 1024 + 1)
    with pytest.raises(ValueError):
        parse_local_indexing_routed_owner_configuration(raw)


@pytest.mark.parametrize("fault", ("cpu_verifier", "recipe", "cuda_profile", "cuda_receipt"))
def test_validly_hashed_routing_policy_must_still_match_every_installed_selection(fault):
    body, original = routed_document()
    candidate = original.model_dump(mode="json")
    if fault == "cpu_verifier":
        candidate["cpu"]["backend"]["backend"]["runtime_verifier"]["source_commit"] = "f" * 40
    elif fault == "recipe":
        candidate["view_recipe_sha256"] = "sha256:" + "f" * 64
    elif fault == "cuda_profile":
        candidate["cuda"]["profile"]["resource_profile"] = seal(
            candidate["cuda"]["profile"]["resource_profile"] | {"timeout_seconds": 179},
            "resource_profile_sha256",
        )
    else:
        candidate["cuda"]["backend"]["backend"]["receipt_raw_sha256"] = "sha256:" + "f" * 64
    candidate = EmbeddingDeviceRoutingPolicy.model_validate(seal(candidate, "policy_sha256"))
    body["routing_policy_sha256"] = candidate.policy_sha256
    selected = RoutedLocalIndexingOwnerConfiguration.model_validate(body)
    with pytest.raises(ValueError):
        require_routed_indexing_policy(selected, candidate)
