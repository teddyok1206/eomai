"""Explicit public config6; old owner parsers and native/GPU controls stay closed."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.local_indexing_routed_owner_configuration import (
    LOCAL_INDEXING_PUBLIC_OWNER_SCHEMA_SHA256,
    PublicSolutionRoutedOwnerConfiguration,
    RoutedLocalIndexingOwnerConfiguration,
    local_indexing_routed_owner_configuration_bytes,
    parse_local_indexing_routed_owner_configuration,
    parse_supported_routed_indexing_configuration,
    require_routed_indexing_policy,
)
from eom_workflow_runner.local_indexing_service_runtime import parse_indexing_service_configuration

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_local_indexing_routed_owner_configuration import routed_document
from tests.unit.test_public_solution_encoding import public_recipe

ROOT = Path(__file__).resolve().parents[2]


def public_owner_document():
    body, policy = routed_document()
    recipe = public_recipe()
    cpu = body["cpu_configuration"]
    cpu.pop("schema_version")
    cpu["recipe"] = recipe.model_dump(mode="json")
    cpu["source_classes"] = ["APPROVED_ITEM", "PAST_EXAM"]
    cpu["namespace"] = PublicSolutionIndexNamespace(
        storage_partition=cpu["namespace"]["storage_partition"],
        space_sha256=cpu["runtime_profile"]["space"]["space_sha256"],
        recipe_sha256=recipe.recipe_sha256,
    ).model_dump(mode="json")
    cpu["maximum_sources"] = 16384
    body["schema_version"] = "local-indexing-owner-configuration/6.0"
    body["legacy_configuration"] = None
    policy = EmbeddingDeviceRoutingPolicy.model_validate(
        seal(
            policy.model_dump(mode="json") | {"view_recipe_sha256": recipe.recipe_sha256},
            "policy_sha256",
        )
    )
    body["routing_policy_sha256"] = policy.policy_sha256
    body["routing_policy"]["sha256"] = sha256_bytes(
        canonical_json_bytes(policy.model_dump(mode="json"))
    )
    return body, policy


def test_public_owner_schema_roundtrip_and_existing_routing_policy_closure():
    body, policy = public_owner_document()
    selected = PublicSolutionRoutedOwnerConfiguration.model_validate(body)
    raw = local_indexing_routed_owner_configuration_bytes(selected)
    assert raw == canonical_json_bytes(body)
    assert parse_supported_routed_indexing_configuration(raw) == selected
    assert parse_indexing_service_configuration(raw) == selected
    assert len(selected.groups) == 1
    assert selected.groups[0].cpu.maximum_sources == 16384
    assert selected.groups[0].cuda_namespaces(selected.cuda_runtime_profile)[0] == (
        selected.cpu_configuration.namespace.model_copy(
            update={
                "space_sha256": selected.cuda_runtime_profile.space.space_sha256,
            }
        )
    )
    require_routed_indexing_policy(selected, policy)
    with pytest.raises(ValueError):
        parse_local_indexing_routed_owner_configuration(raw)
    with pytest.raises(ValueError):
        RoutedLocalIndexingOwnerConfiguration.model_validate(body)
    # Relabelling a successor as config5 cannot bypass the original schema guard.
    with pytest.raises(ValueError):
        RoutedLocalIndexingOwnerConfiguration.model_validate(
            body | {"schema_version": "local-indexing-owner-configuration/5.0"}
        )


def test_public_owner_mirror_and_pin():
    name = "local-indexing-owner-configuration-v6.schema.json"
    raw = (ROOT / "schemas/workflow" / name).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == LOCAL_INDEXING_PUBLIC_OWNER_SCHEMA_SHA256


@pytest.mark.parametrize(
    "fault",
    [
        "legacy_recipe",
        "space",
        "sources",
        "duplicates",
        "bound",
        "batch_bound",
        "manager",
        "same_space",
        "missing_grant",
        "duplicate_grant",
        "grant",
        "native_hash",
        "cpu_timeout",
        "cuda_timeout",
        "backend",
        "unknown",
        "namespace",
        "resource_device",
        "scope_below_batch",
    ],
)
def test_public_owner_cannot_widen_scope_or_invent_runtime_authority(fault):
    body, _ = public_owner_document()
    cpu = body["cpu_configuration"]
    if fault == "legacy_recipe":
        cpu["recipe"] = routed_document()[0]["cpu_configuration"]["recipe"]
    elif fault == "space":
        cpu["namespace"]["space_sha256"] = "sha256:" + "f" * 64
    elif fault == "sources":
        cpu["source_classes"] = []
    elif fault == "duplicates":
        cpu["source_classes"] = ["PAST_EXAM", "PAST_EXAM"]
    elif fault == "bound":
        cpu["maximum_sources"] = 16385
    elif fault == "batch_bound":
        cpu["maximum_targets"] = 1025
    elif fault == "scope_below_batch":
        cpu["maximum_targets"], cpu["maximum_sources"] = 2, 1
    elif fault == "manager":
        cpu["database_owner"]["role_name"] = "eom_catalog_manager_runtime"
    elif fault == "same_space":
        body["cuda_runtime_profile"] = deepcopy(cpu["runtime_profile"])
    elif fault == "missing_grant":
        body["cuda_grants"] = []
    elif fault == "duplicate_grant":
        body["cuda_grants"] *= 2
    elif fault == "grant":
        body["cuda_grants"][0]["cpu_service_policy_revision_id"] = "accessrev_" + "f" * 32
    elif fault == "native_hash":
        body["cuda_grants"][0]["native_execution_policy_sha256"] = cpu[
            "native_execution_policy_sha256"
        ]
    elif fault in {"cpu_timeout", "cuda_timeout", "resource_device"}:
        profile = (
            cpu["runtime_profile"] if fault != "cuda_timeout" else body["cuda_runtime_profile"]
        )
        changes = {"device": "CUDA"} if fault == "resource_device" else {"timeout_seconds": 181}
        profile["resource_profile"] = seal(
            profile["resource_profile"] | changes, "resource_profile_sha256"
        )
    elif fault == "backend":
        body["cuda_backend"]["purpose"] = "QUERY"
    elif fault == "namespace":
        cpu["namespace"]["projection_version"] = "mixed-solution-comparison/2.0"
    else:
        body["latest"] = True
    with pytest.raises(ValueError):
        PublicSolutionRoutedOwnerConfiguration.model_validate(body)


def test_public_owner_rejects_foreign_routing_recipe_and_noncanonical_bytes():
    body, _ = public_owner_document()
    selected = PublicSolutionRoutedOwnerConfiguration.model_validate(body)
    with pytest.raises(ValueError):
        require_routed_indexing_policy(selected, routed_document()[1])
    with pytest.raises(ValueError):
        parse_supported_routed_indexing_configuration(canonical_json_bytes(body) + b"\n")


def public_owner_with_legacy():
    body, _ = public_owner_document()
    legacy, _ = routed_document(dual=True)
    cpu = body["cpu_configuration"]
    cpu["service_policy_revision_id"] = "accessrev_" + "c" * 32
    cpu["service_policy_sha256"] = "sha256:" + "c" * 64
    body["cuda_grants"][0].update(
        cpu_service_policy_revision_id=cpu["service_policy_revision_id"],
        service_policy_revision_id="accessrev_" + "d" * 32,
        service_policy_sha256="sha256:" + "d" * 64,
    )
    body["legacy_configuration"] = legacy
    return body


def test_public_owner_retains_independently_pinned_legacy_namespaces_and_canonical_bytes():
    body = public_owner_with_legacy()
    selected = PublicSolutionRoutedOwnerConfiguration.model_validate(body)
    wire = local_indexing_routed_owner_configuration_bytes(selected)
    assert wire == canonical_json_bytes(body)
    assert parse_supported_routed_indexing_configuration(wire) == selected
    assert selected.legacy_configuration is not None
    assert sum(len(group.cpu.namespaces) for group in selected.legacy_configuration.groups) == 6
    assert selected.legacy_configuration.routing_policy != selected.routing_policy
    assert (
        selected.legacy_configuration.cpu_configuration.recipe != selected.cpu_configuration.recipe
    )


@pytest.mark.parametrize("fault", ["runtime", "controller", "grant", "owner", "corpus", "backend"])
def test_legacy_composition_cannot_mix_physical_runtime_owner_or_grant_identities(fault):
    body = public_owner_with_legacy()
    if fault == "runtime":
        body["legacy_configuration"]["cuda_runtime_profile"]["runtime_bundle"][
            "artifact_revision_id"
        ] = "rev_" + "f" * 32
    elif fault == "controller":
        body["legacy_configuration"]["controller_release"] = "f" * 40
    elif fault == "grant":
        body["cpu_configuration"]["service_policy_revision_id"] = body["legacy_configuration"][
            "cpu_configuration"
        ]["service_policy_revision_id"]
        body["cuda_grants"][0]["cpu_service_policy_revision_id"] = body["cpu_configuration"][
            "service_policy_revision_id"
        ]
    elif fault == "owner":
        body["cpu_configuration"]["database_owner"]["role_oid"] += 1
    elif fault == "corpus":
        body["cpu_configuration"]["corpus_id"] = "corpus_" + "f" * 32
    else:
        body["legacy_configuration"]["cuda_backend"]["backend"]["receipt_raw_sha256"] = (
            "sha256:" + "f" * 64
        )
    with pytest.raises(ValueError):
        PublicSolutionRoutedOwnerConfiguration.model_validate(body)
