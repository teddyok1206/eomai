"""Service-only successor protocol/pure closure; NOT authentication or installed execution."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.local_indexing_policy import (
    LocalIndexingAccessPolicy,
    local_indexing_authorization_audit_sha256,
)
from eom_identifiers import sha256_bytes
from eom_workflow import (
    LocalEmbeddingServiceWorkflowRequest,
    local_embedding_request_actor,
    parse_local_embedding_executable_policy,
    parse_local_embedding_executable_request,
    parse_local_embedding_execution_policy,
    parse_local_embedding_service_execution_policy,
    parse_local_embedding_service_workflow_request,
    parse_local_embedding_workflow_request_v11,
    require_local_embedding_operator_seed,
    validate_local_embedding_request_references,
    validate_local_embedding_runtime_profile,
)
from eom_workflow.schemas import (
    LOCAL_EMBEDDING_SCHEMA_RESOURCES,
    LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES,
    LocalEmbeddingAdmissionContractError,
    load_local_embedding_admission_schema,
    local_embedding_admission_schema_registry,
)
from jsonschema import Draft202012Validator, FormatChecker

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name,filename,schema_id,expected", LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES
)
def test_service_schema_precedes_behavior_and_keeps_old_family(name, filename, schema_id, expected):
    assert len(LOCAL_EMBEDDING_SCHEMA_RESOURCES) == 4
    raw = (ROOT / "schemas/workflow" / filename).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == expected
    schema = load_local_embedding_admission_schema(name)
    assert schema["$id"] == schema_id
    Draft202012Validator.check_schema(schema)
    value = service_fixture()
    payload = value.request if name == "service-request" else value.policy
    Draft202012Validator(
        schema,
        registry=local_embedding_admission_schema_registry(),
        format_checker=FormatChecker(),
    ).validate(payload.model_dump(mode="json"))


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_both_actors_keep_exact_numeric_profiles_but_separate_admission(device):
    f = service_fixture(base=native_fixture(device=device))
    assert (
        parse_local_embedding_service_workflow_request(f.request.model_dump(mode="json"))
        == f.request
    )
    assert parse_local_embedding_executable_request(f.request) == f.request
    assert parse_local_embedding_executable_policy(f.policy) == f.policy
    assert (
        parse_local_embedding_service_execution_policy(f.policy.model_dump(mode="json")) == f.policy
    )
    validate_local_embedding_request_references(f.request, f.base.plan, f.policy)
    validate_local_embedding_runtime_profile(f.policy.profiles[0], _bundle(device))
    assert f.policy.profiles == f.base.policy.profiles
    assert f.request.runtime_bundle == f.base.request.runtime_bundle
    assert local_embedding_request_actor(f.request) == (
        "local_indexing_service",
        f.grant.service.service_id,
    )
    assert local_embedding_request_actor(f.base.request) == (
        "human",
        f.base.request.actor_context.operator_id,
    )


def test_v11_service_audit_stays_parseable_but_unexecutable_with_no_upgrade():
    f = service_fixture()
    body = f.base.request.model_dump(mode="json")
    body["actor_context"] = f.request.actor_context.model_dump(mode="json")
    body = seal(body, "request_sha256")
    old = parse_local_embedding_workflow_request_v11(body)
    with pytest.raises(LocalEmbeddingAdmissionContractError, match="SERVICE_UNAVAILABLE"):
        require_local_embedding_operator_seed(old)
    with pytest.raises(LocalEmbeddingAdmissionContractError, match="SERVICE_UNAVAILABLE"):
        parse_local_embedding_executable_request(old)
    assert old.model_dump(mode="json") == body
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_execution_policy(f.policy.model_dump(mode="json"))
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_workflow_request_v11(f.request.model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault", ["human", "old-policy", "other-service", "policy-role", "request-role"]
)
def test_mode_and_exact_service_pins_cannot_be_reinterpreted(fault):
    f = service_fixture()
    request, policy = f.request.model_dump(mode="json"), f.policy.model_dump(mode="json")
    if fault == "human":
        request["actor_context"] = f.base.request.actor_context.model_dump(mode="json")
    elif fault == "old-policy":
        request["native_execution_policy"] = f.base.request.native_execution_policy.model_dump(
            mode="json"
        )
    elif fault == "other-service":
        policy["service"]["service_revision_id"] = "localindexservicerev_" + "f" * 32
        policy = seal(policy, "policy_sha256")
    elif fault == "policy-role":
        policy["roles"] = ["ADMIN"]
    else:
        request["actor_context"]["role"] = "ADMIN"
    with pytest.raises(ValueError):
        checked_request = parse_local_embedding_service_workflow_request(
            seal(request, "request_sha256")
        )
        checked_policy = parse_local_embedding_service_execution_policy(
            seal(policy, "policy_sha256")
        )
        validate_local_embedding_request_references(checked_request, f.base.plan, checked_policy)


@pytest.mark.parametrize("kind", ["request", "policy"])
@pytest.mark.parametrize("fault", ["copy-extra", "nested-bool", "hidden-extra", "oversized"])
def test_copied_or_constructed_messages_fail_content_free(kind, fault):
    f = service_fixture()
    value = f.request if kind == "request" else f.policy
    parse = (
        parse_local_embedding_executable_request
        if kind == "request"
        else parse_local_embedding_executable_policy
    )
    if fault == "copy-extra":
        broken = value.model_copy(update={"token": "SYNTHETIC_DO_NOT_ECHO"})
    elif fault == "nested-bool":
        resource = f.request.resource_profile.model_copy(update={"threads": True})
        broken = (
            value.model_copy(update={"resource_profile": resource})
            if kind == "request"
            else value.model_copy(
                update={
                    "profiles": (
                        f.policy.profiles[0].model_copy(update={"resource_profile": resource}),
                    )
                }
            )
        )
    elif fault == "hidden-extra":
        broken = value.model_copy()
        object.__setattr__(broken, "__pydantic_extra__", {"token": "SYNTHETIC_DO_NOT_ECHO"})
    else:
        broken = value.model_dump(mode="json") | {"instructions": "x" * (65 * 1024)}
    with pytest.raises(LocalEmbeddingAdmissionContractError) as caught:
        parse(broken)
    assert "SYNTHETIC_DO_NOT_ECHO" not in str(caught.value)


def test_audit_is_pinned_scope_provenance_not_current_authentication():
    f = service_fixture()
    assert (
        f.request.actor_context.authorization_audit_sha256
        == local_indexing_authorization_audit_sha256(f.grant)
    )
    body = deepcopy(f.grant.model_dump(mode="json"))
    body["runtime_configuration_sha256"] = "sha256:" + "f" * 64
    changed = LocalIndexingAccessPolicy.model_validate(seal(body, "content_sha256"))
    assert local_indexing_authorization_audit_sha256(
        changed
    ) != local_indexing_authorization_audit_sha256(f.grant)
    # This only recomputes an audit value; no DB/runtime/auth adapter is called.
    assert LocalEmbeddingServiceWorkflowRequest.model_validate(f.request) == f.request
