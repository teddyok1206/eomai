"""Private lifecycle2 and common QUERY2 closure; CPU/CUDA are synthetic, not admission."""

from functools import lru_cache
from pathlib import Path

import pytest
from eom_catalog_contracts.private_chat_query_basis import (
    PrivateChatQueryBasis,
    private_chat_query_text_sha256,
)
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityRequestV2
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_public_query_projection import (
    prepare_private_chat_public_query_execution_input,
    project_private_chat_public_query,
)
from eom_orchestrator.general_chat_similarity_basis import PreparedPrivateChatQuery
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.private_chat_query_execution import (
    parse_private_chat_query_workflow_request,
    validate_private_chat_query_execution_input,
)
from eom_workflow.private_chat_query_execution_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
    parse_supported_private_chat_query_execution_policy,
    parse_supported_private_chat_query_workflow_request,
    validate_private_chat_public_query_execution_input,
    validate_private_chat_public_query_request_references,
    validate_supported_private_chat_query_request_references,
)
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    private_chat_query_submission_fingerprint,
    private_chat_query_submission_key,
    validate_private_chat_query_submission_context,
)
from eom_workflow.schemas import (
    PRIVATE_CHAT_PUBLIC_QUERY_EXECUTION_SCHEMA_RESOURCE,
    load_local_embedding_admission_schema,
    validate_local_embedding_admission_message,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_private_chat_public_similarity_service import private_public_case
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_execution import execution_case as legacy_execution_case
from tests.unit.test_private_chat_query_submission_context import context_case
from tests.unit.test_reference_query_execution_contracts import case as reference_case


@lru_cache(maxsize=2)
def execution_case(device="CPU"):
    reference = reference_case(device=device)
    selected = private_public_case()[0].model_dump(mode="json")
    selected["views"][0]["index"]["spaces"] = reference.policy.spaces.model_dump(mode="json")
    selected = PrivateChatSimilarityRequestV2.model_validate(seal(selected, "request_sha256"))
    policy = PrivateChatQueryExecutionPolicyV2.model_validate(
        seal(
            reference.policy.model_dump(mode="json")
            | {
                "schema_version": "private-chat-query-execution-policy/2.0",
                "purpose": "PRIVATE_CHAT_QUERY",
            },
            "policy_sha256",
        )
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            reference.request.model_dump(mode="json")
            | {
                "schema_version": "private-chat-query-workflow-request/2.0",
                "request_name": "PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST",
                "purpose": "PRIVATE_CHAT_QUERY",
                "workflow_definition_key": "local-embedding-private-chat-query",
                "workflow_definition_version": "2.0.0",
                "context_request": selected.model_dump(mode="json"),
                "native_execution_policy": reference.request.native_execution_policy.model_dump(
                    mode="json"
                )
                | {
                    "schema_ref": PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
                    "sha256": sha256_bytes(canonical_json_bytes(policy)),
                },
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    return request, policy, reference.bundle


def native(request, policy, bundle, *, prepared=None):
    return prepare_private_chat_public_query_execution_input(
        prepared or PreparedPrivateChatQuery(request.context_request.query_basis, TEXT),
        request,
        policy,
        bundle,
        job_id="job_" + "7" * 32,
        query_request_id="embeddingquery_" + "8" * 32,
    )


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_private2_uses_common_query2_and_the_exact_selected_policy_numerical_bundle(device):
    request, policy, bundle = execution_case(device)
    assert validate_private_chat_public_query_request_references(request, policy, bundle) == (
        request,
        policy,
    )
    assert validate_supported_private_chat_query_request_references(request, policy, bundle) == (
        request,
        policy,
    )
    value = native(request, policy, bundle)
    assert value.native.schema_version == "embedding-reference-query-input/2.0"
    assert value.native.spaces == policy.spaces
    assert value.native.spaces.query.runtime.device == device
    assert value.native.rows[0].text == TEXT and value.basis == request.context_request.query_basis
    assert "conversation_id" not in value.native.model_dump_json()
    assert TEXT not in repr(value)
    backend = SyntheticNativeBackend(policy.spaces.query)
    backend.batch_size, backend.threads = value.native.batch_size, value.native.threads
    result = encode_public_solution_query(value.native, backend).result
    assert backend.calls == [((TEXT,), "QUERY")]
    assert result.schema_version == "embedding-reference-query-result/2.0"
    assert native(request, policy, bundle) == value


def test_execution2_resource_is_closed_mirrored_and_does_not_activate_a_new_definition():
    _, filename, identity, digest = PRIVATE_CHAT_PUBLIC_QUERY_EXECUTION_SCHEMA_RESOURCE
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == digest
    was_admitted = workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")
    schema = load_local_embedding_admission_schema("private-chat-public-execution")
    assert schema["$id"] == identity
    Draft202012Validator.check_schema(schema)
    assert workflow_definition_is_admitted("local-embedding-private-chat-query", "1.0.0")
    assert (
        workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")
        == was_admitted
    )


def test_supported_dispatch_preserves_legacy_but_never_mixes_policy_families():
    old, old_policy, old_bundle = legacy_execution_case()
    request, policy, bundle = execution_case()
    for value in (old, request):
        assert parse_supported_private_chat_query_workflow_request(value) == value
    for value in (old_policy, policy):
        assert parse_supported_private_chat_query_execution_policy(value) == value
    assert validate_supported_private_chat_query_request_references(
        old, old_policy, old_bundle
    ) == (old, old_policy)
    with pytest.raises(ValueError):
        parse_private_chat_query_workflow_request(request)
    for first, second in ((old, policy), (request, old_policy)):
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_REQUEST_POLICY_FAMILY_MISMATCH"):
            validate_supported_private_chat_query_request_references(first, second, bundle)
    with pytest.raises(ValueError):
        validate_private_chat_query_execution_input(
            old, old_policy, old_bundle, native(request, policy, bundle).native
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("purpose", "REFERENCE_QUERY"),
        ("schema_version", "private-chat-query-workflow-request/1.0"),
        ("authority", TEXT),
        ("workflow_definition_version", "1.0.0"),
    ),
)
def test_private2_does_not_borrow_reference_authority_or_erase_unknown_fields(field, value):
    request, _, _ = execution_case()
    document = seal(request.model_dump(mode="json") | {field: value}, "request_sha256")
    with pytest.raises(ValueError, match=r"^PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST_INVALID$") as error:
        parse_supported_private_chat_query_workflow_request(document)
    assert TEXT not in str(error.value)


@pytest.mark.parametrize(
    "fault",
    (
        "raw_policy",
        "semantic_policy",
        "resource",
        "bundle",
        "space",
        "missing_index",
        "copied_extra",
        "bool",
    ),
)
def test_wrong_control_or_schema_cannot_prepare_a_private_native_input(fault):
    request, policy, bundle = execution_case()
    body = request.model_dump(mode="json")
    if fault == "raw_policy":
        body["native_execution_policy"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "semantic_policy":
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    elif fault == "resource":
        body["resource_profile"] = seal(
            body["resource_profile"] | {"batch_size": 2}, "resource_profile_sha256"
        )
    elif fault == "bundle":
        body["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    elif fault == "space":
        policy = execution_case("CUDA")[1]
    elif fault == "missing_index":
        body["context_request"]["views"][0]["index"] = None
        body["context_request"] = seal(body["context_request"], "request_sha256")
    elif fault == "bool":
        body["resource_profile"]["threads"] = True
        body["resource_profile"] = seal(body["resource_profile"], "resource_profile_sha256")
    else:
        request = request.model_copy(update={"authority": TEXT})
    with pytest.raises(ValueError):
        if fault != "copied_extra":
            request = PrivateChatQueryWorkflowRequestV2.model_validate(seal(body, "request_sha256"))
        native(request, policy, bundle)


def test_missing_index_is_rejected_by_workflow_json_schema_before_pydantic():
    document = execution_case()[0].model_dump(mode="json")
    document["context_request"]["views"][0]["index"] = None
    document["context_request"] = seal(document["context_request"], "request_sha256")
    with pytest.raises(ValueError):
        validate_local_embedding_admission_message(
            "private-chat-public-execution", seal(document, "request_sha256")
        )


def test_same_text_from_another_turn_cannot_borrow_a_current_private_execution():
    request, policy, bundle = execution_case()
    original = request.context_request.query_basis
    changed = PrivateChatQueryBasis.model_validate(
        seal(original.model_dump(mode="json") | {"turn_id": "chatturn_" + "f" * 32}, "basis_sha256")
    )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_PUBLIC_QUERY_EXECUTION_INPUT_INVALID"):
        native(request, policy, bundle, prepared=PreparedPrivateChatQuery(changed, TEXT))


def test_valid_common_numerical_query_for_different_text_cannot_borrow_private_parent():
    request, policy, bundle = execution_case()
    text = TEXT + "다른 조건"
    basis = PrivateChatQueryBasis.model_validate(
        seal(
            request.context_request.query_basis.model_dump(mode="json")
            | {
                "query_text_sha256": private_chat_query_text_sha256(text),
            },
            "basis_sha256",
        )
    )
    other = project_private_chat_public_query(
        PreparedPrivateChatQuery(basis, text),
        PublicSolutionSimilarityViewV4.model_validate(
            request.context_request.views[0].model_dump(mode="json")
        ),
        context_request_sha256=request.context_request.request_sha256,
        job_id="job_" + "7" * 32,
        query_request_id="embeddingquery_" + "8" * 32,
        batch_size=request.resource_profile.batch_size,
        threads=request.resource_profile.threads,
    )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTION_INPUT_INVALID"):
        validate_private_chat_public_query_execution_input(request, policy, bundle, other.native)


@pytest.mark.parametrize(
    "fault", ("context", "private_text", "batch", "threads", "authority", "old_input")
)
def test_exact_original_numerical_input_is_required_without_leaking_private_text(fault):
    request, policy, bundle = execution_case()
    query = native(request, policy, bundle).native
    if fault == "old_input":
        from tests.unit.test_private_chat_query_execution import native_input

        query = native_input(*legacy_execution_case())
    else:
        update = {
            "context": {"context_request_sha256": "sha256:" + "f" * 64},
            "private_text": {"rows": ()},
            "batch": {"batch_size": 2},
            "threads": {"threads": 2},
            "authority": {"authority": TEXT},
        }[fault]
        query = query.model_copy(update=update)
    with pytest.raises(ValueError, match=r"^PRIVATE_CHAT_QUERY_EXECUTION_INPUT_INVALID$") as error:
        validate_private_chat_public_query_execution_input(request, policy, bundle, query)
    assert TEXT not in str(error.value) and error.value.__suppress_context__


def test_original_turn_key_is_shared_across_versions_but_the_exact_fingerprint_changes():
    legacy = context_case()
    request = execution_case()[0]
    context_body = request.context_request.model_dump(mode="json") | {
        "query_basis": legacy.context.origin.basis.model_dump(mode="json")
    }
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "context_request": seal(context_body, "request_sha256"),
                "operator_audit": request.operator_audit.model_dump(mode="json")
                | {"operator_id": legacy.context.origin.actor_id},
            },
            "request_sha256",
        )
    )
    context = build_private_chat_query_submission_context(request, legacy.context.origin)
    assert context.schema_version == "private-chat-query-submission-context/1.0"
    assert private_chat_query_submission_key(context) == private_chat_query_submission_key(
        legacy.context
    )
    assert validate_private_chat_query_submission_context(request, context) == context
    with pytest.raises(ValueError):
        validate_private_chat_query_submission_context(request, legacy.context)
    fingerprints = tuple(
        private_chat_query_submission_fingerprint(
            item,
            metadata,
            definition_sha256=item.workflow_definition_sha256,
            actor_type="human",
            actor_id=metadata.origin.actor_id,
        )
        for item, metadata in ((legacy.request, legacy.context), (request, context))
    )
    assert fingerprints[0] != fingerprints[1]
