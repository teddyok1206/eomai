"""Public QUERY workflow provenance values only; no actual launch or source authority."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_INPUT_REF,
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryInput,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.reference_query_execution import (
    PUBLIC_REFERENCE_QUERY_RECEIPT_REF,
    ReferenceQueryStepOutputV2,
    ReferenceQueryWorkflowReceiptV2,
    ReferenceQueryWorkflowRequestV3,
    parse_reference_query_launch_association,
    parse_reference_query_step_output,
    parse_reference_query_workflow_receipt,
    parse_reference_query_workflow_request_v2,
    parse_supported_reference_query_step_output,
    parse_supported_reference_query_workflow_intent,
    parse_supported_reference_query_workflow_receipt,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_launch_association,
    validate_reference_query_request_references,
    validate_reference_query_step_output,
)
from eom_workflow.reference_query_workflow import (
    parse_public_solution_reference_query_workflow_definition,
    parse_reference_query_workflow_definition,
)
from eom_workflow.schemas import REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE

from tests.unit.inference_transfer_embedding_fixtures import encoding_identity, seal
from tests.unit.test_public_solution_query_contracts import public_query_input, public_query_result
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_reference_query_execution_contracts import case, checked_receipt, pointer
from tests.unit.test_reference_query_workflow_contracts import definition_body

ROOT = Path(__file__).resolve().parents[2]


def public_definition_body():
    body = definition_body()
    body["definition_version"] = "2.0.0"
    body["steps"][0]["result_schema"] = "embedding-reference-query-result@2.0"
    return body


def public_workflow_case(*, identity=None, device="CPU"):
    previous = case(device=device)
    definition = parse_public_solution_reference_query_workflow_definition(public_definition_body())
    policy = type(previous.policy).model_validate(
        seal(
            previous.policy.model_dump(mode="json")
            | {"workflow_definition_sha256": content_sha256(definition.model_dump(mode="json"))},
            "policy_sha256",
        )
    )
    context = public_similarity_case()[0].model_dump(mode="json")
    if identity is not None:
        context["request_id"] = "similarityrequest_" + identity
    context["views"][0]["index"]["spaces"] = policy.spaces.model_dump(mode="json")
    context = seal(context, "request_sha256")
    body = previous.request.model_dump(mode="json") | {
        "schema_version": "reference-query-workflow-request/3.0",
        "workflow_definition_version": "2.0.0",
        "workflow_definition_sha256": policy.workflow_definition_sha256,
        "context_request": context,
        "native_execution_policy_sha256": policy.policy_sha256,
    }
    body["native_execution_policy"]["sha256"] = sha256_bytes(
        canonical_json_bytes(policy.model_dump(mode="json"))
    )
    request = ReferenceQueryWorkflowRequestV3.model_validate(seal(body, "request_sha256"))
    numerical = public_query_input(device=device).model_dump(mode="json")
    if identity is not None:
        numerical["job_id"] = "job_" + identity
        numerical["query_request_id"] = "embeddingquery_" + identity
    numerical["context_request_sha256"] = request.context_request.request_sha256
    numerical["spaces"] = policy.spaces.model_dump(mode="json")
    numerical["batch_size"], numerical["threads"] = (
        request.resource_profile.batch_size,
        request.resource_profile.threads,
    )
    for row in numerical["rows"]:
        row["encoding"] = encoding_identity(
            row["text"],
            policy.spaces.query,
            storage_partition=request.context_request.views[0].index.storage_partition,
        ).model_dump(mode="json")
    numerical["input_set_sha256"] = content_sha256([row["encoding"] for row in numerical["rows"]])
    native = PublicSolutionQueryInput.model_validate(seal(numerical, "request_sha256"))
    result = public_query_result(native)
    launch = parse_reference_query_launch_association(
        seal(
            previous.launch.model_dump(mode="json")
            | {
                "workflow_id": previous.launch.workflow_id
                if identity is None
                else "workflow_" + identity,
                "step_run_id": previous.launch.step_run_id
                if identity is None
                else "steprun_" + identity,
                "workflow_request_sha256": request.request_sha256,
                "context_request_sha256": request.context_request.request_sha256,
                "native_launch_job_id": native.job_id,
                "query_request_id": native.query_request_id,
                "query_request_sha256": native.request_sha256,
                "query_input_set_sha256": native.input_set_sha256,
                "recipe_sha256": native.recipe.recipe_sha256,
            },
            "association_sha256",
        )
    )
    receipt_body = previous.receipt.model_dump(mode="json") | {
        "schema_version": "reference-query-workflow-receipt/2.0",
        "workflow_id": launch.workflow_id,
        "step_run_id": launch.step_run_id,
        "workflow_definition_sha256": request.workflow_definition_sha256,
        "workflow_request_sha256": request.request_sha256,
        "context_request_sha256": request.context_request.request_sha256,
        "native_launch_job_id": native.job_id,
        "launch_association_sha256": launch.association_sha256,
        "execution_result_schema": "embedding-reference-query-result@2.0",
        "query_input": pointer(
            "input.json",
            PUBLIC_SOLUTION_QUERY_INPUT_REF,
            sha256_bytes(canonical_json_bytes(native.model_dump(mode="json"))),
        ).model_dump(mode="json"),
        "query_execution": {
            "job_id": native.job_id,
            "query_request_id": native.query_request_id,
            "request_sha256": native.request_sha256,
            "input_set_sha256": native.input_set_sha256,
            "result_member": pointer(
                "result.json",
                PUBLIC_SOLUTION_QUERY_RESULT_REF,
                sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
            ).model_dump(mode="json"),
            "result_sha256": result.result_sha256,
        },
        "shard": pointer(
            "shard.json",
            previous.receipt.shard.schema_ref,
            sha256_bytes(canonical_json_bytes(result.shard.model_dump(mode="json"))),
        ).model_dump(mode="json"),
        "binary": pointer(
            "vectors.f32",
            previous.receipt.binary.schema_ref,
            result.shard.binary.sha256,
            media="application/octet-stream",
        ).model_dump(mode="json"),
    }
    if identity is not None:
        # Distinct original/Artifact/receipt producers remain independent even
        # when several fixtures share the same disposable PostgreSQL database.
        query_seed = content_sha256({"identity": identity, "role": "query"})[-32:]
        receipt_seed = content_sha256({"identity": identity, "role": "receipt"})[-32:]
        receipt_body["query_artifact_owner_job_id"] = "job_" + query_seed
        receipt_body["receipt_owner_job_id"] = "job_" + receipt_seed
        for member in (
            receipt_body["query_input"],
            receipt_body["query_execution"]["result_member"],
            receipt_body["shard"],
            receipt_body["binary"],
        ):
            member.update(
                artifact_id="artifact_" + query_seed, artifact_revision_id="rev_" + query_seed
            )
    receipt = ReferenceQueryWorkflowReceiptV2.model_validate(seal(receipt_body, "receipt_sha256"))
    output = ReferenceQueryStepOutputV2.model_validate(
        seal(
            previous.output.model_dump(mode="json")
            | {
                "schema_version": "reference-query-step-output/2.0",
                "workflow_id": launch.workflow_id,
                "step_run_id": launch.step_run_id,
                "receipt_owner_job_id": receipt.receipt_owner_job_id,
                "execution_result_schema": "embedding-reference-query-result@2.0",
                "receipt_schema": PUBLIC_REFERENCE_QUERY_RECEIPT_REF,
                "receipt": pointer(
                    "receipt.json",
                    PUBLIC_REFERENCE_QUERY_RECEIPT_REF,
                    sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json"))),
                    seed="c",
                ).model_dump(mode="json"),
                "receipt_sha256": receipt.receipt_sha256,
            },
            "output_sha256",
        )
    )
    if identity is not None:
        output_body = output.model_dump(mode="json")
        output_body["receipt"].update(
            artifact_id="artifact_" + receipt_seed, artifact_revision_id="rev_" + receipt_seed
        )
        output = ReferenceQueryStepOutputV2.model_validate(seal(output_body, "output_sha256"))
    return SimpleNamespace(
        definition=definition,
        request=request,
        policy=policy,
        bundle=previous.bundle,
        launch=launch,
        native_input=native,
        result=result,
        receipt=receipt,
        output=output,
    )


def test_schema_bytes_and_public_definition_are_separate_from_released_definition():
    name, _, digest = REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE
    raw = (ROOT / "schemas/workflow" / name).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == digest
    definition = parse_public_solution_reference_query_workflow_definition(public_definition_body())
    assert definition.definition_version == "2.0.0" and definition.limits.max_step_attempts == 1
    with pytest.raises(ValueError):
        parse_reference_query_workflow_definition(definition)
    with pytest.raises(ValueError):
        parse_public_solution_reference_query_workflow_definition(definition_body())


def test_public_source_request_native_launch_receipt_and_output_form_one_exact_chain():
    c = public_workflow_case()
    validate_reference_query_request_references(c.request, c.policy, c.bundle)
    validate_reference_query_launch_association(
        c.launch, c.request, c.policy, c.bundle, c.native_input
    )
    checked_receipt(c, c.receipt)
    validate_reference_query_step_output(c.output, c.receipt)
    assert parse_supported_reference_query_workflow_intent(c.request) == c.request
    assert parse_supported_reference_query_workflow_receipt(c.receipt) == c.receipt
    assert parse_supported_reference_query_step_output(c.output) == c.output
    for parse, value in [
        (parse_supported_reference_query_workflow_request, c.request),
        (parse_reference_query_workflow_request_v2, c.request),
        (parse_reference_query_workflow_receipt, c.receipt),
        (parse_reference_query_step_output, c.output),
    ]:
        with pytest.raises(ValueError):
            parse(value)


@pytest.mark.parametrize(
    "field",
    [
        "workflow_request_sha256",
        "context_request_sha256",
        "launch_association_sha256",
        "workflow_definition_sha256",
        "resource_profile_sha256",
    ],
)
def test_resealed_public_receipt_cannot_claim_another_request_or_execution(field):
    c = public_workflow_case()
    receipt = ReferenceQueryWorkflowReceiptV2.model_validate(
        seal(
            c.receipt.model_dump(mode="json") | {field: content_sha256({"other": field})},
            "receipt_sha256",
        )
    )
    with pytest.raises(ValueError, match="differs"):
        checked_receipt(c, receipt)


def test_public_workflow_rejects_historical_numerical_input_and_receipt_even_if_text_matches():
    c, old = public_workflow_case(), case()
    with pytest.raises(ValueError):
        validate_reference_query_launch_association(
            c.launch, c.request, c.policy, c.bundle, old.native_input
        )
    with pytest.raises(ValueError):
        checked_receipt(c, old.receipt)
    with pytest.raises(ValueError):
        validate_reference_query_step_output(c.output, old.receipt)
    with pytest.raises(ValueError):
        validate_reference_query_step_output(old.output, c.receipt)


def test_public_request_rejects_unhashed_nested_mutation_and_old_definition_pin():
    c = public_workflow_case()
    mutated = deepcopy(c.request.model_dump(mode="json"))
    mutated["context_request"]["anchor"]["base_analysis_run_id"] = "analysisrun_" + "f" * 32
    with pytest.raises(ValueError):
        ReferenceQueryWorkflowRequestV3.model_validate(mutated)
    mutated = c.request.model_dump(mode="json") | {"workflow_definition_version": "1.0.0"}
    with pytest.raises(ValueError):
        ReferenceQueryWorkflowRequestV3.model_validate(seal(mutated, "request_sha256"))
