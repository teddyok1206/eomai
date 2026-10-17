"""Private execution closure using synthetic pointers only; never a native grant."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryInput
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_similarity_basis import (
    PreparedPrivateChatQuery,
    prepare_private_chat_query_execution_input,
)
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.private_chat_query_execution import (
    PRIVATE_CHAT_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
    validate_private_chat_query_execution_input,
    validate_private_chat_query_request_references,
)
from eom_workflow.reference_query_execution import (
    parse_reference_query_execution_policy,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow.schemas import (
    PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE,
    load_local_embedding_admission_schema,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_private_chat_query import private_context_request
from tests.unit.test_private_chat_query_basis import TEXT, basis
from tests.unit.test_reference_query_execution_contracts import case


def execution_case():
    legacy = case()
    policy_body = legacy.policy.model_dump(mode="json") | {
        "schema_version": "private-chat-query-execution-policy/1.0",
        "purpose": "PRIVATE_CHAT_QUERY",
    }
    policy = PrivateChatQueryExecutionPolicy.model_validate(seal(policy_body, "policy_sha256"))
    request_body = legacy.request.model_dump(mode="json") | {
        "schema_version": "private-chat-query-workflow-request/1.0",
        "request_name": "PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST",
        "purpose": "PRIVATE_CHAT_QUERY",
        "workflow_definition_key": "local-embedding-private-chat-query",
        "context_request": private_context_request(
            selected=legacy.request.context_request.views[0]
        ).model_dump(mode="json"),
        "native_execution_policy": legacy.request.native_execution_policy.model_dump(mode="json")
        | {
            "schema_ref": PRIVATE_CHAT_QUERY_POLICY_REF,
            "sha256": sha256_bytes(canonical_json_bytes(policy)),
        },
        "native_execution_policy_sha256": policy.policy_sha256,
    }
    request = PrivateChatQueryWorkflowRequest.model_validate(seal(request_body, "request_sha256"))
    return request, policy, legacy.bundle


def native_input(request, policy, bundle):
    return prepare_private_chat_query_execution_input(
        PreparedPrivateChatQuery(basis(), TEXT),
        request,
        policy,
        bundle,
        job_id="job_" + "7" * 32,
        query_request_id="embeddingquery_" + "8" * 32,
    )


def test_closed_packaged_resource_and_not_yet_admitted_execution():
    entry = PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE
    _, filename, schema_id, digest = entry
    root = Path(__file__).resolve().parents[2]
    payload = (root / "schemas/workflow" / filename).read_bytes()
    assert payload == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(payload) == digest
    schema = load_local_embedding_admission_schema("private-chat-execution")
    assert schema["$id"] == schema_id
    assert set(schema["$defs"]) == {"request", "policy"}
    Draft202012Validator.check_schema(schema)
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "1.0.0")


def test_selected_private_controls_prepare_same_exact_owned_question():
    request, policy, bundle = execution_case()
    validate_private_chat_query_request_references(request, policy, bundle)
    native = native_input(request, policy, bundle)
    validate_private_chat_query_execution_input(request, policy, bundle, native)
    assert native.row.text == TEXT
    assert native.basis == request.context_request.query_basis == basis()
    assert native.context_request_sha256 == request.context_request.request_sha256
    assert native.spaces == policy.spaces
    assert (native.batch_size, native.threads) == (4, 4)
    assert canonical_json_bytes(native) == canonical_json_bytes(
        native_input(request, policy, bundle)
    )
    assert TEXT not in canonical_json_bytes(request).decode()
    assert TEXT not in canonical_json_bytes(policy).decode()
    assert PrivateChatQueryWorkflowRequest.model_validate(request) == request
    assert PrivateChatQueryExecutionPolicy.model_validate(policy) == policy


@pytest.mark.parametrize("target", ["request", "policy"])
@pytest.mark.parametrize("fault", ["version", "purpose", "authority", "bool", "hash", "copied"])
def test_closed_raw_and_unvalidated_copy_cannot_borrow_other_authority(target, fault):
    request, policy, _ = execution_case()
    value = request if target == "request" else policy
    body = value.model_dump(mode="json")
    hash_field = "request_sha256" if target == "request" else "policy_sha256"
    if fault == "version":
        body["schema_version"] = "reference-query-" + target + "/1.0"
    elif fault == "purpose":
        body["purpose"] = "REFERENCE_QUERY"
    elif fault == "authority":
        body["actor_role"] = "ADMIN"
    elif fault == "bool":
        body["resource_profile"]["threads"] = True
        body["resource_profile"] = seal(body["resource_profile"], "resource_profile_sha256")
    elif fault == "hash":
        body[hash_field] = "sha256:" + "f" * 64
    else:
        body = value.model_copy(update={"authority": "ADMIN"})
    if fault not in {"hash", "copied"}:
        body = seal(body, hash_field)
    with pytest.raises(ValueError):
        type(value).model_validate(body)


@pytest.mark.parametrize(
    "fault",
    [
        "semantic_policy",
        "raw_policy",
        "policy_path",
        "policy_schema",
        "definition",
        "bundle",
        "resources",
        "spaces",
        "missing_index",
    ],
)
def test_different_supplied_control_pins_cannot_prepare_native_input(fault):
    request, policy, bundle = execution_case()
    body = request.model_dump(mode="json")
    if fault == "semantic_policy":
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    elif fault == "raw_policy":
        body["native_execution_policy"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "policy_path":
        body["native_execution_policy"]["member_path"] = "other.json"
    elif fault == "policy_schema":
        body["native_execution_policy"]["schema_ref"] = (
            "eom://schemas/workflow/reference-query-execution-policy/1.0"
        )
    elif fault == "definition":
        body["workflow_definition_sha256"] = "sha256:" + "f" * 64
    elif fault == "bundle":
        body["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    elif fault == "resources":
        body["resource_profile"]["threads"] = 2
        body["resource_profile"] = seal(body["resource_profile"], "resource_profile_sha256")
    else:
        selected = body["context_request"]["views"][0]
        if fault == "missing_index":
            selected["index"] = None
        else:
            spaces = deepcopy(selected["index"]["spaces"])
            for space in spaces.values():
                space["model_spec"]["model_revision_id"] = "embeddingmodelrev_" + "f" * 32
                space.update(seal(space, "space_sha256"))
            selected["index"]["spaces"] = spaces
        body["context_request"] = seal(body["context_request"], "request_sha256")
    with pytest.raises(ValueError):
        changed = PrivateChatQueryWorkflowRequest.model_validate(seal(body, "request_sha256"))
        native_input(changed, policy, bundle)


@pytest.mark.parametrize("fault", ["parent", "basis", "recipe", "partition", "batch", "threads"])
def test_native_input_is_bound_to_its_exact_private_execution_intent(fault):
    request, policy, bundle = execution_case()
    body = native_input(request, policy, bundle).model_dump(mode="json")
    if fault == "parent":
        body["context_request_sha256"] = "sha256:" + "f" * 64
    elif fault == "basis":
        body["basis"]["turn_id"] = "chatturn_" + "f" * 32
        body["basis"] = seal(body["basis"], "basis_sha256")
    elif fault == "recipe":
        body["document_recipe"]["maximum_text_bytes"] -= 1
        body["document_recipe"] = seal(body["document_recipe"], "recipe_sha256")
    elif fault == "partition":
        body["row"]["encoding"]["storage_partition"] = "other-partition"
        body["row"]["encoding"] = seal(body["row"]["encoding"], "encoding_sha256")
        body["input_set_sha256"] = sha256_bytes(canonical_json_bytes([body["row"]["encoding"]]))
    else:
        body["batch_size" if fault == "batch" else "threads"] = 2
    if fault == "recipe":
        # This released recipe fixes every field. An unreleased recipe must fail
        # its own schema, not be made valid just to reach the later association check.
        with pytest.raises((ValueError, SchemaError)):
            EmbeddingPrivateChatQueryInput.model_validate(seal(body, "request_sha256"))
        return
    changed = EmbeddingPrivateChatQueryInput.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError, match="exact execution intent"):
        validate_private_chat_query_execution_input(request, policy, bundle, changed)


def test_existing_reference_parsers_and_private_parsers_reject_each_other():
    request, policy, bundle = execution_case()
    legacy = case()
    for parser, value in (
        (parse_supported_reference_query_workflow_request, request),
        (parse_reference_query_execution_policy, policy),
        (PrivateChatQueryWorkflowRequest.model_validate, legacy.request),
        (PrivateChatQueryExecutionPolicy.model_validate, legacy.policy),
    ):
        with pytest.raises(ValueError):
            parser(value)
    with pytest.raises(ValueError):
        native_input(request, legacy.policy, bundle)
    wrong_basis = basis().model_copy(update={"turn_id": "chatturn_" + "f" * 32})
    with pytest.raises(ValueError):
        prepare_private_chat_query_execution_input(
            PreparedPrivateChatQuery(wrong_basis, TEXT),
            request,
            policy,
            bundle,
            job_id="job_" + "7" * 32,
            query_request_id="embeddingquery_" + "8" * 32,
        )


def test_public_schema_cannot_mutate_the_pinned_parser_resource():
    request, policy, bundle = execution_case()
    schema = load_local_embedding_admission_schema("private-chat-execution")
    schema["$defs"]["request"]["properties"]["purpose"] = {"const": "REFERENCE_QUERY"}
    validate_private_chat_query_request_references(request, policy, bundle)


def test_native_validation_error_never_serializes_private_question_or_unknown_fields():
    request, policy, bundle = execution_case()
    native = native_input(request, policy, bundle)
    forged = native.model_copy(update={"untrusted_field": TEXT})
    with pytest.raises(ValueError) as failure:
        validate_private_chat_query_execution_input(request, policy, bundle, forged)
    assert str(failure.value) == "PRIVATE_CHAT_QUERY_EXECUTION_INPUT_INVALID"
    assert TEXT not in str(failure.value)
    assert failure.value.__suppress_context__


def test_private_native_basis_is_not_a_public_approved_anchor():
    request, _, _ = execution_case()
    body = request.context_request.model_dump(mode="json")
    body["query_basis"]["approved_item_revision_id"] = "itemrev_" + "f" * 32
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatSimilarityRequest.model_validate(seal(body, "request_sha256"))
