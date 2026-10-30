"""Closed public owner values; synthetic policies, no installed grant or model work."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.reference_query_execution import parse_reference_query_execution_policy
from eom_workflow.reference_query_owner_configuration import (
    REFERENCE_QUERY_PUBLIC_OWNER_SCHEMA_SHA256,
    ReferenceQueryPublicServiceConfiguration,
    ReferenceQueryServiceConfiguration,
    ReferenceQueryServiceConfigurationV2,
    parse_reference_query_service_configuration,
    parse_supported_reference_query_service_configuration,
    require_public_reference_query_cohost,
    supported_reference_query_service_configuration_bytes,
)
from eom_workflow.reference_query_routed_owner_configuration import (
    PUBLIC_ROUTED_QUERY_OWNER_SCHEMA_SHA256,
    PublicRoutedReferenceQueryOwnerConfiguration,
    RoutedReferenceQueryOwnerConfiguration,
    parse_reference_query_installed_owner_selection,
    parse_reference_query_routed_owner_configuration,
    require_supported_routed_reference_query_policy,
    supported_routed_reference_query_configuration_bytes,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_reference_query_execution import public_definition_body
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected


@pytest.fixture
def public(selected):
    body, routing, cpu, cuda = selected
    primary = ReferenceQueryServiceConfiguration.model_validate(body["cpu_configuration"])
    recipe = public_similarity_case()[0].views[0].recipe
    routing = EmbeddingDeviceRoutingPolicy.model_validate(
        seal(
            routing.model_dump(mode="json") | {"view_recipe_sha256": recipe.recipe_sha256},
            "policy_sha256",
        )
    )
    cpu, cuda = tuple(
        parse_reference_query_execution_policy(
            seal(
                policy.model_dump(mode="json")
                | {"workflow_definition_sha256": content_sha256(public_definition_body())},
                "policy_sha256",
            )
        )
        for policy in (cpu, cuda)
    )
    base = body["cpu_configuration"]
    base.update(
        schema_version="reference-query-owner-configuration/4.0",
        namespace=PublicSolutionIndexNamespace(
            storage_partition="public-solution",
            space_sha256=cpu.spaces.document.space_sha256,
            recipe_sha256=recipe.recipe_sha256,
        ).model_dump(mode="json"),
        recipe=recipe.model_dump(mode="json"),
        native_execution_policy_sha256=cpu.policy_sha256,
    )
    base["native_execution_policy"]["sha256"] = sha256_bytes(canonical_json_bytes(cpu))
    body.update(
        schema_version="reference-query-owner-configuration/5.0",
        cuda_native_execution_policy_sha256=cuda.policy_sha256,
        routing_policy_sha256=routing.policy_sha256,
    )
    body["cuda_native_execution_policy"]["sha256"] = sha256_bytes(canonical_json_bytes(cuda))
    body["routing_policy"]["sha256"] = sha256_bytes(canonical_json_bytes(routing))
    return body, routing, cpu, cuda, primary


def test_public_cpu_and_routed_are_explicit_closed_canonical_selections(public):
    body, routing, cpu, cuda, primary = public
    config = PublicRoutedReferenceQueryOwnerConfiguration.model_validate(body)
    base = config.cpu_configuration
    raw_base = supported_reference_query_service_configuration_bytes(base)
    raw = supported_routed_reference_query_configuration_bytes(config)
    assert parse_supported_reference_query_service_configuration(raw_base) == base
    assert parse_reference_query_installed_owner_selection(raw_base) == (base, None)
    assert parse_reference_query_installed_owner_selection(raw) == (base, config)
    require_supported_routed_reference_query_policy(config, routing, cpu, cuda)
    require_public_reference_query_cohost(primary, base)
    for old in (ReferenceQueryServiceConfiguration, ReferenceQueryServiceConfigurationV2):
        with pytest.raises(ValueError):
            old.model_validate(base.model_dump(mode="json"))
    with pytest.raises(ValueError):
        RoutedReferenceQueryOwnerConfiguration.model_validate(body)
    with pytest.raises(ValueError):
        parse_reference_query_service_configuration(raw_base)
    with pytest.raises(ValueError):
        parse_reference_query_routed_owner_configuration(raw)


@pytest.mark.parametrize(
    "version,digest",
    ((4, REFERENCE_QUERY_PUBLIC_OWNER_SCHEMA_SHA256), (5, PUBLIC_ROUTED_QUERY_OWNER_SCHEMA_SHA256)),
)
def test_public_owner_schema_mirrors_and_hashes_are_pinned(version, digest):
    root = Path(__file__).resolve().parents[2]
    name = f"reference-query-owner-configuration-v{version}.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == digest


@pytest.mark.parametrize("fault", ("commit", "provider", "database"))
def test_public_cohost_cannot_borrow_another_installed_owner_or_identity_provider(public, fault):
    body, _routing, _cpu, _cuda, primary = public
    base = deepcopy(body["cpu_configuration"])
    if fault == "commit":
        base["owner_source_commit"] = "e" * 40
    elif fault == "provider":
        base["api_provider"]["source_commit"] = "e" * 40
    else:
        base["database_owner"]["role_oid"] += 1
    with pytest.raises(ValueError, match="PUBLIC_COHOST"):
        require_public_reference_query_cohost(
            primary, ReferenceQueryPublicServiceConfiguration.model_validate(base)
        )


@pytest.mark.parametrize(
    "field", ("actor_id", "maximum_authentication_age_seconds", "password", "source_ids", "model")
)
def test_public_configuration_does_not_grant_user_authority_or_runtime_overrides(public, field):
    body, *_ = public
    body[field] = "not-a-grant"
    with pytest.raises(ValueError, match="REFERENCE_QUERY_OWNER_CONFIGURATION_INVALID"):
        PublicRoutedReferenceQueryOwnerConfiguration.model_validate(body)
