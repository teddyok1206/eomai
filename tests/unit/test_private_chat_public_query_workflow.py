"""Common QUERY2 completion chain with synthetic encoder/owner; not actual execution."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.compiler import (
    WorkflowDefinitionError,
    compile_definition,
    compile_definition_data,
)
from eom_workflow.definition_execution_protocol import definition_execution_protocol
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)
from eom_workflow.private_chat_query_publication import (
    PrivateChatQueryExecutionRecord,
    PrivateChatQueryLaunchAssociation,
)
from eom_workflow.private_chat_query_publication_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_RECORD_REF,
    PrivateChatPublicQueryExecutionRecord,
    validate_private_chat_public_query_launch,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowReceipt,
)
from eom_workflow.private_chat_query_workflow_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_EXECUTION_PROTOCOL,
    PRIVATE_CHAT_PUBLIC_QUERY_RECEIPT_REF,
    PrivateChatPublicQueryStep,
    PrivateChatQueryStepOutputV2,
    PrivateChatQueryWorkflowDefinitionV2,
    PrivateChatQueryWorkflowReceiptV2,
    parse_supported_private_chat_query_step_output,
    parse_supported_private_chat_query_workflow_receipt,
    validate_private_chat_public_query_definition,
    validate_private_chat_public_query_step_output,
    validate_private_chat_public_query_workflow_receipt,
)
from eom_workflow.schemas import (
    PRIVATE_CHAT_PUBLIC_QUERY_PUBLICATION_SCHEMA_RESOURCE,
    PRIVATE_CHAT_PUBLIC_QUERY_RUNNER_SCHEMA_RESOURCE,
    load_local_embedding_admission_schema,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_private_chat_public_query_execution import execution_case, native
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed
from tests.unit.test_reference_query_execution_contracts import pointer

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def public_completed(completed):
    old = completed
    compiled = compile_definition(
        ROOT / "config/workflows/local-embedding-private-chat-query.v2.yaml", set()
    )
    request, policy, bundle = execution_case()
    policy = PrivateChatQueryExecutionPolicyV2.model_validate(
        seal(
            policy.model_dump(mode="json")
            | {
                "workflow_definition_sha256": compiled.sha256,
            },
            "policy_sha256",
        )
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "workflow_definition_sha256": compiled.sha256,
                "native_execution_policy": request.native_execution_policy.model_dump(mode="json")
                | {"sha256": sha256_bytes(canonical_json_bytes(policy))},
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    numerical = native(request, policy, bundle).native
    backend = SyntheticNativeBackend(numerical.spaces.query)
    backend.batch_size, backend.threads = numerical.batch_size, numerical.threads
    result = encode_public_solution_query(numerical, backend).result
    launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            old.launch.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "context_request_sha256": request.context_request.request_sha256,
                "basis_sha256": request.context_request.query_basis.basis_sha256,
                "native_launch_job_id": numerical.job_id,
                "query_request_id": numerical.query_request_id,
                "query_request_sha256": numerical.request_sha256,
                "query_input_set_sha256": numerical.input_set_sha256,
                "recipe_sha256": numerical.recipe.recipe_sha256,
                "runtime_bundle": request.runtime_bundle.model_dump(mode="json"),
                "resource_profile_sha256": request.resource_profile.resource_profile_sha256,
            },
            "association_sha256",
        )
    )
    record = validate_private_chat_public_query_launch(launch, request, policy, bundle, numerical)
    execution = old.receipt.query_execution.model_dump(mode="json") | dict(
        job_id=numerical.job_id,
        query_request_id=numerical.query_request_id,
        request_sha256=numerical.request_sha256,
        input_set_sha256=numerical.input_set_sha256,
        basis_sha256=request.context_request.query_basis.basis_sha256,
        result_member=pointer(
            "result.json",
            "eom://schemas/knowledge/embedding-reference-query-result/2.0",
            sha256_bytes(canonical_json_bytes(result)),
        ).model_dump(mode="json"),
        result_sha256=result.result_sha256,
    )
    receipt = PrivateChatQueryWorkflowReceiptV2.model_validate(
        seal(
            old.receipt.model_dump(mode="json")
            | dict(
                schema_version="private-chat-query-workflow-receipt/2.0",
                workflow_definition_sha256=compiled.sha256,
                workflow_request_sha256=request.request_sha256,
                context_request_sha256=request.context_request.request_sha256,
                launch_association_sha256=launch.association_sha256,
                execution_result_schema="embedding-reference-query-result@2.0",
                execution_record=pointer(
                    "intent.json",
                    PRIVATE_CHAT_PUBLIC_QUERY_RECORD_REF,
                    sha256_bytes(canonical_json_bytes(record)),
                ).model_dump(mode="json"),
                query_execution=execution,
                shard=pointer(
                    "shard.json",
                    "eom://schemas/knowledge/embedding-vector-shard/1.0",
                    sha256_bytes(canonical_json_bytes(result.shard)),
                ).model_dump(mode="json"),
                binary=pointer(
                    "vectors.f32",
                    "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                    result.shard.binary.sha256,
                    media="application/octet-stream",
                ).model_dump(mode="json"),
                runtime_bundle=request.runtime_bundle.model_dump(mode="json"),
                resource_profile_sha256=request.resource_profile.resource_profile_sha256,
            ),
            "receipt_sha256",
        )
    )
    output = PrivateChatQueryStepOutputV2.model_validate(
        seal(
            old.output.model_dump(mode="json")
            | dict(
                schema_version="private-chat-query-step-output/2.0",
                execution_result_schema="embedding-reference-query-result@2.0",
                receipt_schema=PRIVATE_CHAT_PUBLIC_QUERY_RECEIPT_REF,
                receipt=pointer(
                    "receipt.json",
                    PRIVATE_CHAT_PUBLIC_QUERY_RECEIPT_REF,
                    sha256_bytes(canonical_json_bytes(receipt)),
                    seed="d",
                ).model_dump(mode="json"),
                receipt_sha256=receipt.receipt_sha256,
            ),
            "output_sha256",
        )
    )
    return SimpleNamespace(
        request=request,
        policy=policy,
        bundle=bundle,
        native=numerical,
        launch=launch,
        result=result,
        record=record,
        receipt=receipt,
        output=output,
        compiled=compiled,
        expected=old.expected,
        previous=old,
    )


def check(value, receipt=None, **updates):
    fields = {
        name: getattr(value, name)
        for name in ("request", "policy", "bundle", "launch", "native", "result")
    }
    validate_private_chat_public_query_workflow_receipt(
        value.receipt if receipt is None else receipt, **(fields | updates), **value.expected
    )


def test_fixed_graph_and_original_launch1_bind_the_new_common_query2_receipt(public_completed):
    value = public_completed
    assert type(value.compiled.definition) is PrivateChatQueryWorkflowDefinitionV2
    assert (
        definition_execution_protocol(value.compiled.definition)
        == PRIVATE_CHAT_PUBLIC_QUERY_EXECUTION_PROTOCOL
    )
    assert isinstance(
        value.compiled.steps_by_key["encode_private_chat_query"], PrivateChatPublicQueryStep
    )
    assert value.launch.schema_version == "private-chat-query-launch-association/1.0"
    assert value.native.schema_version == "embedding-reference-query-input/2.0"
    assert value.result.schema_version == "embedding-reference-query-result/2.0"
    validate_private_chat_public_query_definition(value.compiled.definition, value.request)
    check(value)
    validate_private_chat_public_query_step_output(value.output, value.receipt)
    for document in (value.request, value.record, value.receipt, value.output):
        assert TEXT not in canonical_json_bytes(document).decode()
    assert parse_supported_private_chat_query_workflow_receipt(value.receipt) == value.receipt
    assert (
        parse_supported_private_chat_query_workflow_receipt(value.previous.receipt)
        == value.previous.receipt
    )
    assert parse_supported_private_chat_query_step_output(value.output) == value.output
    assert (
        parse_supported_private_chat_query_step_output(value.previous.output)
        == value.previous.output
    )
    for old, new in (
        (PrivateChatQueryExecutionRecord, value.record),
        (PrivateChatQueryWorkflowReceipt, value.receipt),
        (PrivateChatQueryStepOutput, value.output),
    ):
        with pytest.raises((ValueError, SchemaError)):
            old.model_validate(new.model_dump(mode="json"))


@pytest.mark.parametrize(
    "resource",
    (
        PRIVATE_CHAT_PUBLIC_QUERY_PUBLICATION_SCHEMA_RESOURCE,
        PRIVATE_CHAT_PUBLIC_QUERY_RUNNER_SCHEMA_RESOURCE,
    ),
)
def test_successor_protocols_are_closed_mirrored_and_hash_pinned(resource):
    key, filename, identity, digest = resource
    raw = (ROOT / "schemas/workflow" / filename).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == digest
    schema = load_local_embedding_admission_schema(key)
    assert schema["$id"] == identity
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("fault", ("role", "operation", "result", "version", "terminal", "unsafe"))
def test_new_definition_is_not_an_arbitrary_worker_graph(public_completed, fault):
    body = public_completed.compiled.as_dict()
    if fault == "role":
        body["steps"][0]["worker_role"] = "authoring"
    elif fault == "operation":
        body["steps"][0]["operation"] = "BUILD_REFERENCE_QUERY_EMBEDDINGS"
    elif fault == "result":
        body["steps"][0]["result_schema"] = "embedding-private-chat-query-result@1.0"
    elif fault == "version":
        body["definition_version"] = "1.0.0"
    elif fault == "terminal":
        body["steps"][1]["terminal_status"] = "FAILED"
    else:
        body["sql"] = "synthetic-not-executed"
    with pytest.raises(WorkflowDefinitionError):
        compile_definition_data(body, "synthetic-invalid-private2", set())


@pytest.mark.parametrize(
    "fault",
    (
        "workflow",
        "parent",
        "basis",
        "result",
        "member",
        "schema",
        "private_text",
        "record_extra",
        "launch_extra",
        "result_extra",
    ),
)
def test_receipt_rejects_foreign_hashes_or_copied_private_values_without_leaking_text(
    public_completed, fault
):
    value = public_completed
    body = value.receipt.model_dump(mode="json")
    updates = {}
    if fault == "workflow":
        body["workflow_id"] = "workflow_" + "f" * 32
    elif fault == "parent":
        body["workflow_request_sha256"] = "sha256:" + "f" * 64
    elif fault == "basis":
        body["query_execution"]["basis_sha256"] = "sha256:" + "f" * 64
    elif fault == "result":
        body["query_execution"]["result_sha256"] = "sha256:" + "f" * 64
    elif fault == "member":
        body["execution_record"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "schema":
        body["query_execution"]["result_member"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-private-chat-query-result/1.0"
        )
    elif fault == "private_text":
        updates["native"] = value.native.model_copy(update={"authority": TEXT})
    elif fault == "launch_extra":
        updates["launch"] = value.launch.model_copy(update={"authority": TEXT})
    elif fault == "result_extra":
        updates["result"] = value.result.model_copy(update={"authority": TEXT})
    else:
        body["authority"] = TEXT
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_RECEIPT_PROVENANCE_INVALID") as error:
        check(value, seal(body, "receipt_sha256"), **updates)
    assert TEXT not in str(error.value) and error.value.__suppress_context__


def test_wrong_launch_or_receipt_cannot_be_relabelled_as_legacy(public_completed):
    body = deepcopy(public_completed.record.model_dump(mode="json"))
    body["launch"]["basis_sha256"] = "sha256:" + "f" * 64
    body["launch"] = seal(body["launch"], "association_sha256")
    with pytest.raises(ValueError):
        PrivateChatPublicQueryExecutionRecord.model_validate(seal(body, "record_sha256"))
    bad = public_completed.output.model_dump(mode="json")
    bad["receipt_sha256"] = "sha256:" + "f" * 64
    output = PrivateChatQueryStepOutputV2.model_validate(seal(bad, "output_sha256"))
    with pytest.raises(ValueError):
        validate_private_chat_public_query_step_output(output, public_completed.receipt)


@pytest.mark.parametrize("name", ("record", "receipt", "output"))
def test_invalid_private_metadata_does_not_echo_untrusted_question_in_model_error(
    public_completed, name
):
    value = getattr(public_completed, name)
    with pytest.raises(ValueError) as error:
        type(value).model_validate(value.model_copy(update={"authority": TEXT}))
    assert TEXT not in str(error.value) and repr(TEXT) not in str(error.value)
