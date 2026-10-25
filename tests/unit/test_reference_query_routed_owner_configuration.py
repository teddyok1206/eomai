"""Pure deployment selection; no installed files, source permission, DB or numerical call."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.reference_query_execution import ReferenceQueryExecutionPolicy
from eom_workflow.reference_query_owner_configuration import (
    ReferenceQueryOwnerConfigurationError,
    parse_supported_reference_query_service_configuration,
)
from eom_workflow.reference_query_routed_owner_configuration import (
    ROUTED_QUERY_OWNER_SCHEMA_SHA256,
    RoutedReferenceQueryOwnerConfiguration,
    parse_reference_query_routed_owner_configuration,
    reference_query_routed_owner_configuration_bytes,
    reference_query_routed_owner_configuration_schema,
    require_routed_reference_query_policy,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.reference_query_batch_execution_fixtures import query_plan_case
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_owner_configuration import owner_body


@pytest.fixture
def selected(source):
    query, planned = query_plan_case(key="1" * 32)
    routing, cuda = planned.policy, query.policy
    profile = routing.cpu.profile
    document = profile.space.model_dump(mode="json")
    spaces = dict(
        document=document,
        query=seal(document | {"purpose": "QUERY"}, "space_sha256"),
    )
    cpu = ReferenceQueryExecutionPolicy.model_validate(
        seal(
            cuda.model_dump(mode="json")
            | {
                "spaces": spaces,
                "runtime_bundle": profile.runtime_bundle.model_dump(mode="json"),
                "resource_profile": profile.resource_profile.model_dump(mode="json"),
            },
            "policy_sha256",
        )
    )
    primary = owner_body(source)
    primary["namespace"]["space_sha256"] = document["space_sha256"]
    primary.update(
        native_execution_policy_sha256=cpu.policy_sha256,
        runtime_bundle=profile.runtime_bundle.model_dump(mode="json"),
    )
    cuda_pointer = deepcopy(primary["native_execution_policy"])
    cuda_pointer["artifact_revision_id"] = "rev_" + "c" * 32
    cuda_pointer["sha256"] = sha256_bytes(canonical_json_bytes(cuda))
    route_pointer = {
        "artifact_id": "artifact_" + "e" * 32,
        "artifact_revision_id": "rev_" + "e" * 32,
        "member_path": "policy.json",
        "sha256": sha256_bytes(canonical_json_bytes(routing)),
        "schema_ref": "eom://schemas/workflow/embedding-device-routing/1.0",
        "media_type": "application/json",
    }
    return (
        dict(
            schema_version="reference-query-owner-configuration/3.0",
            cpu_configuration=primary,
            cuda_native_execution_policy=cuda_pointer,
            cuda_native_execution_policy_sha256=cuda.policy_sha256,
            routing_policy=route_pointer,
            routing_policy_sha256=routing.policy_sha256,
            controller_release="d" * 40,
        ),
        routing,
        cpu,
        cuda,
    )


@pytest.mark.parametrize("mixed", (False, True))
def test_closed_schema_mirror_roundtrip_and_legacy_decoder_still_closed(selected, mixed):
    body, routing, cpu, cuda = selected
    if mixed:
        body["cpu_configuration"]["schema_version"] = "reference-query-owner-configuration/2.0"
        body["cpu_configuration"]["namespace"].update(
            projection_version="mixed-solution-comparison/2.0",
            population_scope="ALL_ADMITTED_GRAPH_ITEMS",
        )
    root = Path(__file__).resolve().parents[2]
    name = "reference-query-owner-configuration-v3.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == ROUTED_QUERY_OWNER_SCHEMA_SHA256
    schema = reference_query_routed_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"])
    config = RoutedReferenceQueryOwnerConfiguration.model_validate(body)
    encoded = reference_query_routed_owner_configuration_bytes(config)
    assert parse_reference_query_routed_owner_configuration(encoded) == config
    assert require_routed_reference_query_policy(config, routing, cpu, cuda) is None
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        parse_supported_reference_query_service_configuration(encoded)


@pytest.mark.parametrize(
    "field,value",
    (
        ("actor_id", "operator_" + "a" * 32),
        ("roles", ["ADMIN"]),
        ("password", "synthetic-not-secret"),
        ("command", "/bin/true"),
        ("source_ids", []),
        ("maximum_authentication_age_seconds", 86400),
        ("model", "arbitrary"),
        ("controller_release", True),
        ("schema_version", "reference-query-owner-configuration/4.0"),
    ),
)
def test_no_caller_authority_password_path_ttl_or_unknown_configuration(selected, field, value):
    body, *_ = selected
    body[field] = value
    with pytest.raises(ValueError, match="REFERENCE_QUERY_OWNER_CONFIGURATION_INVALID"):
        RoutedReferenceQueryOwnerConfiguration.model_validate(body)


@pytest.mark.parametrize(
    "fault",
    (
        "route_schema",
        "route_path",
        "route_media",
        "cuda_schema",
        "cuda_path",
        "same_pointer",
        "same_policy",
        "nested_authority",
    ),
)
def test_typed_pointer_and_device_policy_selection_is_not_reinterpreted(selected, fault):
    body, *_ = selected
    if fault == "route_schema":
        body["routing_policy"]["schema_ref"] = (
            "eom://schemas/workflow/reference-query-execution-policy/1.0"
        )
    elif fault == "route_path":
        body["routing_policy"]["member_path"] = "../policy.json"
    elif fault == "route_media":
        body["routing_policy"]["media_type"] = "text/plain"
    elif fault == "cuda_schema":
        body["cuda_native_execution_policy"]["schema_ref"] = (
            "eom://schemas/workflow/private-chat-query-execution-policy/1.0"
        )
    elif fault == "cuda_path":
        body["cuda_native_execution_policy"]["member_path"] = "input.json"
    elif fault == "same_pointer":
        body["cuda_native_execution_policy"] = body["cpu_configuration"]["native_execution_policy"]
    elif fault == "same_policy":
        body["cuda_native_execution_policy_sha256"] = body["cpu_configuration"][
            "native_execution_policy_sha256"
        ]
    else:
        body["cpu_configuration"]["roles"] = ["ADMIN"]
    with pytest.raises(ValueError, match="REFERENCE_QUERY_OWNER_CONFIGURATION_INVALID"):
        RoutedReferenceQueryOwnerConfiguration.model_validate(body)


@pytest.mark.parametrize(
    "fault", ("newline", "duplicate", "constant", "budget", "constructed", "copied")
)
def test_untrusted_raw_values_are_not_normalized_or_smuggled(selected, fault):
    body, *_ = selected
    config = RoutedReferenceQueryOwnerConfiguration.model_validate(body)
    raw = reference_query_routed_owner_configuration_bytes(config)
    if fault == "newline":
        raw += b"\n"
    elif fault == "duplicate":
        raw = raw[:-1] + b',"controller_release":"' + b"d" * 40 + b'"}'
    elif fault == "constant":
        raw = b'{"controller_release":NaN}'
    elif fault == "budget":
        raw = b" " * 65537
    elif fault == "constructed":
        config = RoutedReferenceQueryOwnerConfiguration.model_construct(
            schema_version="reference-query-owner-configuration/3.0"
        )
    else:
        config = config.model_copy(update={"roles": ["ADMIN"]})
    with pytest.raises(ValueError):
        if fault in {"constructed", "copied"}:
            reference_query_routed_owner_configuration_bytes(config)
        else:
            parse_reference_query_routed_owner_configuration(raw)


@pytest.mark.parametrize(
    "fault",
    (
        "purpose",
        "route_hash",
        "recipe",
        "space",
        "cpu_hash",
        "cuda_hash",
        "cuda_bundle",
        "definition",
        "resource",
    ),
)
def test_individually_valid_but_wrong_resolved_controls_are_rejected(selected, fault):
    body, route, cpu, cuda = selected
    if fault in {"purpose", "recipe"}:
        changed = route.model_dump(mode="json")
        changed["purpose" if fault == "purpose" else "view_recipe_sha256"] = (
            "INDEX" if fault == "purpose" else "sha256:" + "9" * 64
        )
        if fault == "purpose":
            for device in ("cpu", "cuda"):
                changed[device]["backend"]["purpose"] = "INDEX"
        route = EmbeddingDeviceRoutingPolicy.model_validate(seal(changed, "policy_sha256"))
        body["routing_policy_sha256"] = route.policy_sha256
    elif fault == "route_hash":
        body["routing_policy_sha256"] = "sha256:" + "9" * 64
    elif fault == "space":
        body["cpu_configuration"]["namespace"]["space_sha256"] = "sha256:" + "9" * 64
    elif fault in {"cpu_hash", "cuda_hash"}:
        target = body["cpu_configuration"] if fault == "cpu_hash" else body
        target[
            "native_execution_policy_sha256"
            if fault == "cpu_hash"
            else "cuda_native_execution_policy_sha256"
        ] = "sha256:" + "9" * 64
    else:
        changed = cuda.model_dump(mode="json")
        if fault == "cuda_bundle":
            changed["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "9" * 32
        elif fault == "definition":
            changed["workflow_definition_sha256"] = "sha256:" + "9" * 64
        else:
            changed["resource_profile"] = seal(
                changed["resource_profile"] | {"batch_size": 3}, "resource_profile_sha256"
            )
        cuda = ReferenceQueryExecutionPolicy.model_validate(seal(changed, "policy_sha256"))
        body["cuda_native_execution_policy_sha256"] = cuda.policy_sha256
    config = RoutedReferenceQueryOwnerConfiguration.model_validate(body)
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        require_routed_reference_query_policy(config, route, cpu, cuda)
