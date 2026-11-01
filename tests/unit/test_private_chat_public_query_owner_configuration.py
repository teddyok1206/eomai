"""Private CPU/CUDA control selection; synthetic canonical values, no installed grants."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.private_chat_query_execution_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicyV2,
)
from eom_workflow.private_chat_query_owner_configuration import (
    MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES,
    PRIVATE_CHAT_PUBLIC_QUERY_OWNER_SCHEMA_SHA256,
    PrivateChatQueryOwnerConfigurationError,
    PrivateChatQueryPublicServiceConfiguration,
    parse_private_chat_query_service_configuration,
    parse_supported_private_chat_query_service_configuration,
    private_chat_public_query_owner_configuration_schema,
    require_private_chat_public_query_policies,
    require_private_chat_public_query_reference_configuration,
    supported_private_chat_query_service_configuration_bytes,
)
from eom_workflow.reference_query_routed_owner_configuration import (
    PublicRoutedReferenceQueryOwnerConfiguration,
    supported_routed_reference_query_configuration_bytes,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_query_owner_configuration import public as public
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected


@pytest.fixture
def private(public):
    body, previous_routing, previous_cpu, previous_cuda, _ = public
    reference = PublicRoutedReferenceQueryOwnerConfiguration.model_validate(body)
    cpu, cuda = tuple(
        PrivateChatQueryExecutionPolicyV2.model_validate(
            seal(
                policy.model_dump(mode="json")
                | {
                    "schema_version": "private-chat-query-execution-policy/2.0",
                    "purpose": "PRIVATE_CHAT_QUERY",
                },
                "policy_sha256",
            )
        )
        for policy in (previous_cpu, previous_cuda)
    )
    routing_body = previous_routing.model_dump(mode="json")
    routing_body["purpose"] = "PRIVATE_CHAT_QUERY"
    for device in ("cpu", "cuda"):
        routing_body[device]["backend"]["purpose"] = "PRIVATE_CHAT_QUERY"
    routing = EmbeddingDeviceRoutingPolicy.model_validate(seal(routing_body, "policy_sha256"))
    base = reference.cpu_configuration
    configuration = PrivateChatQueryPublicServiceConfiguration.model_validate(
        dict(
            schema_version="private-chat-query-owner-configuration/2.0",
            reference_configuration_raw_sha256=sha256_bytes(
                supported_routed_reference_query_configuration_bytes(reference)
            ),
            corpus_id=base.corpus_id,
            namespace=base.namespace.model_dump(mode="json"),
            recipe=base.recipe.model_dump(mode="json"),
            source_classes=list(base.source_classes),
            native_execution_policy=base.native_execution_policy.model_dump(mode="json")
            | {
                "schema_ref": PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
                "sha256": sha256_bytes(canonical_json_bytes(cpu)),
            },
            native_execution_policy_sha256=cpu.policy_sha256,
            runtime_bundle=base.runtime_bundle.model_dump(mode="json"),
            owner_environment_raw_sha256=base.owner_environment_raw_sha256,
            cuda_native_execution_policy=reference.cuda_native_execution_policy.model_dump(
                mode="json"
            )
            | {
                "schema_ref": PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
                "sha256": sha256_bytes(canonical_json_bytes(cuda)),
            },
            cuda_native_execution_policy_sha256=cuda.policy_sha256,
            routing_policy=reference.routing_policy.model_dump(mode="json")
            | {
                "sha256": sha256_bytes(canonical_json_bytes(routing.model_dump(mode="json"))),
            },
            routing_policy_sha256=routing.policy_sha256,
        )
    )
    return configuration, reference, routing, cpu, cuda


def test_closed_private_routed_controls_are_canonical_and_reuse_real_public_cohost_selection(
    private,
):
    configuration, reference, routing, cpu, cuda = private
    raw = supported_private_chat_query_service_configuration_bytes(configuration)
    assert parse_supported_private_chat_query_service_configuration(raw) == configuration
    require_private_chat_public_query_reference_configuration(configuration, reference)
    require_private_chat_public_query_policies(configuration, routing, cpu, cuda)
    assert routing.preferred_device == "CUDA" and routing.fallback_device == "CPU"
    assert routing.purpose == "PRIVATE_CHAT_QUERY"
    assert cpu.spaces.document != cuda.spaces.document
    with pytest.raises(ValueError):
        parse_private_chat_query_service_configuration(raw)


def test_equivalent_timestamp_reencoding_cannot_replace_the_published_routing_bytes(private):
    configuration, _reference, routing, cpu, cuda = private
    body = configuration.model_dump(mode="json")
    reencoded = sha256_bytes(canonical_json_bytes(routing))
    assert reencoded != configuration.routing_policy.sha256
    body["routing_policy"]["sha256"] = reencoded
    changed = PrivateChatQueryPublicServiceConfiguration.model_validate(body)
    with pytest.raises(PrivateChatQueryOwnerConfigurationError):
        require_private_chat_public_query_policies(changed, routing, cpu, cuda)


def test_owner2_schema_is_closed_pinned_and_mirrored():
    root = Path(__file__).resolve().parents[2]
    filename = "private-chat-query-owner-configuration-v2.schema.json"
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == PRIVATE_CHAT_PUBLIC_QUERY_OWNER_SCHEMA_SHA256
    schema = private_chat_public_query_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize(
    "field,value",
    (
        ("authority", "ADMIN"),
        ("password", "synthetic-not-a-credential"),
        ("maximum_authentication_age_seconds", 86400),
        ("source_classes", ["PAST_EXAM", "APPROVED_ITEM"]),
        ("reference_configuration_raw_sha256", True),
        ("actor_id", "operator_" + "f" * 32),
    ),
)
def test_private_owner_selection_does_not_accept_authority_paths_or_implicit_coercion(
    private, field, value
):
    configuration = private[0]
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_INVALID"):
        PrivateChatQueryPublicServiceConfiguration.model_validate(
            configuration.model_dump(mode="json") | {field: value}
        )


@pytest.mark.parametrize(
    "fault",
    (
        "cpu_reference_policy",
        "cuda_reference_policy",
        "recipe",
        "same_policy",
        "copied",
        "route_path",
    ),
)
def test_explicit_private_family_and_common_namespace_are_required(private, fault):
    body = private[0].model_dump(mode="json")
    if fault in {"cpu_reference_policy", "cuda_reference_policy"}:
        field = (
            "native_execution_policy"
            if fault == "cpu_reference_policy"
            else "cuda_native_execution_policy"
        )
        body[field]["schema_ref"] = "eom://schemas/workflow/reference-query-execution-policy/1.0"
    elif fault == "recipe":
        body["namespace"]["recipe_sha256"] = "sha256:" + "f" * 64
    elif fault == "same_policy":
        body["cuda_native_execution_policy"] = deepcopy(body["native_execution_policy"])
        body["cuda_native_execution_policy_sha256"] = body["native_execution_policy_sha256"]
    elif fault == "route_path":
        body["routing_policy"]["member_path"] = "../policy.json"
    else:
        body = private[0].model_copy(update={"authority": "ADMIN"})
    with pytest.raises(ValueError):
        PrivateChatQueryPublicServiceConfiguration.model_validate(body)


@pytest.mark.parametrize(
    "field",
    (
        "corpus_id",
        "namespace",
        "source_classes",
        "runtime_bundle",
        "owner_environment_raw_sha256",
        "reference_configuration_raw_sha256",
    ),
)
def test_individually_valid_but_different_public_owner_cannot_be_borrowed(private, field):
    configuration, reference, *_ = private
    body = configuration.model_dump(mode="json")
    if field == "corpus_id":
        body[field] = "corpus_" + "f" * 32
    elif field == "namespace":
        body["namespace"]["storage_partition"] = "other-partition"
    elif field == "source_classes":
        body[field] = ["PAST_EXAM"]
    elif field == "runtime_bundle":
        body[field]["bundle_revision_id"] = "embeddingbundlerev_" + "0" * 32
    else:
        body[field] = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        require_private_chat_public_query_reference_configuration(
            PrivateChatQueryPublicServiceConfiguration.model_validate(body), reference
        )


@pytest.mark.parametrize(
    "fault",
    (
        "cpu_raw",
        "cuda_raw",
        "routing_raw",
        "cpu_semantic",
        "cuda_semantic",
        "routing_semantic",
        "reference_routing",
        "wrong_profiles",
        "bundle",
        "definition",
    ),
)
def test_resolved_policies_need_exact_purpose_profile_and_artifact_hashes(private, public, fault):
    configuration, _reference, routing, cpu, cuda = private
    body = configuration.model_dump(mode="json")
    if fault.endswith("_raw"):
        body[
            {
                "cpu_raw": "native_execution_policy",
                "cuda_raw": "cuda_native_execution_policy",
                "routing_raw": "routing_policy",
            }[fault]
        ]["sha256"] = "sha256:" + "f" * 64
    elif fault.endswith("_semantic"):
        body[
            {
                "cpu_semantic": "native_execution_policy_sha256",
                "cuda_semantic": "cuda_native_execution_policy_sha256",
                "routing_semantic": "routing_policy_sha256",
            }[fault]
        ] = "sha256:" + "f" * 64
    elif fault == "reference_routing":
        routing = public[1]
        body["routing_policy"]["sha256"] = sha256_bytes(
            canonical_json_bytes(routing.model_dump(mode="json"))
        )
        body["routing_policy_sha256"] = routing.policy_sha256
    elif fault == "wrong_profiles":
        cpu, cuda = cuda, cpu
    elif fault in {"bundle", "definition"}:
        policy = cuda.model_dump(mode="json")
        if fault == "bundle":
            policy["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
        else:
            policy["workflow_definition_sha256"] = "sha256:" + "f" * 64
        cuda = PrivateChatQueryExecutionPolicyV2.model_validate(seal(policy, "policy_sha256"))
    configuration = PrivateChatQueryPublicServiceConfiguration.model_validate(body)
    with pytest.raises(ValueError):
        require_private_chat_public_query_policies(configuration, routing, cpu, cuda)


@pytest.mark.parametrize("device", ("cpu", "cuda"))
def test_even_resealed_controls_cannot_exceed_existing_finite_native_window(private, device):
    configuration, _reference, routing, cpu, cuda = private
    controls = {"cpu": cpu, "cuda": cuda}
    policy = controls[device].model_dump(mode="json")
    resources = seal(
        policy["resource_profile"] | {"timeout_seconds": MAX_EMBEDDING_WORK_BATCH_SECONDS + 1},
        "resource_profile_sha256",
    )
    controls[device] = PrivateChatQueryExecutionPolicyV2.model_validate(
        seal(policy | {"resource_profile": resources}, "policy_sha256")
    )
    route = routing.model_dump(mode="json")
    route[device]["profile"]["resource_profile"] = resources
    routing = EmbeddingDeviceRoutingPolicy.model_validate(seal(route, "policy_sha256"))
    body = configuration.model_dump(mode="json")
    field = "native_execution_policy" if device == "cpu" else "cuda_native_execution_policy"
    body[field]["sha256"] = sha256_bytes(canonical_json_bytes(controls[device]))
    body[field + "_sha256"] = controls[device].policy_sha256
    body["routing_policy"]["sha256"] = sha256_bytes(
        canonical_json_bytes(routing.model_dump(mode="json"))
    )
    body["routing_policy_sha256"] = routing.policy_sha256
    configuration = PrivateChatQueryPublicServiceConfiguration.model_validate(body)
    with pytest.raises(PrivateChatQueryOwnerConfigurationError):
        require_private_chat_public_query_policies(
            configuration, routing, controls["cpu"], controls["cuda"]
        )


@pytest.mark.parametrize("fault", ("whitespace", "duplicate", "too_large", "str", "nan"))
def test_canonical_owner_parser_rejects_untrusted_normalization(private, fault):
    raw = supported_private_chat_query_service_configuration_bytes(private[0])
    if fault == "whitespace":
        raw = b" " + raw
    elif fault == "duplicate":
        raw = raw[:-1] + b',"schema_version":"private-chat-query-owner-configuration/2.0"}'
    elif fault == "too_large":
        raw = b" " * (MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES + 1)
    elif fault == "str":
        raw = raw.decode()
    else:
        raw = b'{"invalid":NaN}'
    with pytest.raises(PrivateChatQueryOwnerConfigurationError):
        parse_supported_private_chat_query_service_configuration(raw)
