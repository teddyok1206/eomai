"""Source-proof request4 over unchanged QUERY2/receipt2; synthetic, not runtime authority."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_catalog_contracts.registered_public_solution_similarity import (
    public_solution_reference_for_entry,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.native_reference_query_coordinator import validate_native_reference_query_history
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutputV2,
    ReferenceQueryWorkflowReceiptV2,
    ReferenceQueryWorkflowRequestV3,
    ReferenceQueryWorkflowRequestV4,
    parse_reference_query_native_input,
    parse_reference_query_workflow_request_v3,
    parse_supported_reference_query_context,
    parse_supported_reference_query_workflow_request,
    reference_query_result_schema,
    validate_reference_query_launch_association,
    validate_reference_query_request_references,
    validate_reference_query_step_output,
    validate_reference_query_workflow_receipt,
)
from eom_workflow.schemas import (
    REFERENCE_QUERY_REQUEST_V4_SCHEMA_RESOURCE,
    load_reference_query_request_v4_schema,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_query_continuation import public_query_records
from tests.unit.test_public_solution_query_contracts import public_query_result
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)

ROOT = Path(__file__).resolve().parents[2]


def registered_public_workflow_case(*, identity=None, device="CPU", registered_anchor=True):
    previous = public_workflow_case(identity=identity, device=device)
    context = registered_similarity_case()[0].model_dump(mode="json")
    if registered_anchor:
        context["anchor"] = public_solution_reference_for_entry(
            registered_similarity_case()[2]
        ).model_dump(mode="json")
    context["views"][0]["index"]["spaces"] = previous.policy.spaces.model_dump(mode="json")
    request = ReferenceQueryWorkflowRequestV4.model_validate(
        seal(
            previous.request.model_dump(mode="json")
            | dict(
                schema_version="reference-query-workflow-request/4.0",
                context_request=seal(context, "request_sha256"),
            ),
            "request_sha256",
        )
    )
    native = PublicSolutionQueryInput.model_validate(
        seal(
            previous.native_input.model_dump(mode="json")
            | dict(context_request_sha256=request.context_request.request_sha256),
            "request_sha256",
        )
    )
    result = public_query_result(native)
    launch = type(previous.launch).model_validate(
        seal(
            previous.launch.model_dump(mode="json")
            | dict(
                workflow_request_sha256=request.request_sha256,
                context_request_sha256=request.context_request.request_sha256,
                query_request_sha256=native.request_sha256,
            ),
            "association_sha256",
        )
    )
    body = previous.receipt.model_dump(mode="json")
    body.update(
        workflow_request_sha256=request.request_sha256,
        context_request_sha256=request.context_request.request_sha256,
        launch_association_sha256=launch.association_sha256,
    )
    body["query_input"]["sha256"] = sha256_bytes(
        canonical_json_bytes(native.model_dump(mode="json"))
    )
    body["query_execution"].update(
        request_sha256=native.request_sha256, result_sha256=result.result_sha256
    )
    body["query_execution"]["result_member"]["sha256"] = sha256_bytes(
        canonical_json_bytes(result.model_dump(mode="json"))
    )
    body["shard"]["sha256"] = sha256_bytes(
        canonical_json_bytes(result.shard.model_dump(mode="json"))
    )
    body["binary"]["sha256"] = result.shard.binary.sha256
    receipt = ReferenceQueryWorkflowReceiptV2.model_validate(seal(body, "receipt_sha256"))
    output = previous.output.model_dump(mode="json")
    output["receipt_sha256"] = receipt.receipt_sha256
    output["receipt"]["sha256"] = sha256_bytes(
        canonical_json_bytes(receipt.model_dump(mode="json"))
    )
    return SimpleNamespace(
        **(
            vars(previous)
            | dict(
                request=request,
                launch=launch,
                native_input=native,
                result=result,
                receipt=receipt,
                output=ReferenceQueryStepOutputV2.model_validate(seal(output, "output_sha256")),
            )
        ),
    )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("registered_anchor", [False, True])
def test_request4_keeps_numeric2_and_exact_publication_closure(device, registered_anchor):
    value = registered_public_workflow_case(device=device, registered_anchor=registered_anchor)
    previous = public_workflow_case(device=device)
    assert parse_supported_reference_query_workflow_request(value.request) == value.request
    assert (
        parse_supported_reference_query_context(value.request.context_request)
        == value.request.context_request
    )
    assert (
        parse_reference_query_native_input(value.request, value.native_input) == value.native_input
    )
    assert reference_query_result_schema(value.request) == "embedding-reference-query-result@2.0"
    assert value.native_input.rows == previous.native_input.rows
    assert value.native_input.input_set_sha256 == previous.native_input.input_set_sha256
    assert value.native_input.request_sha256 != previous.native_input.request_sha256
    assert value.request.request_sha256 != previous.request.request_sha256
    validate_reference_query_request_references(value.request, value.policy, value.bundle)
    validate_reference_query_launch_association(
        value.launch, value.request, value.policy, value.bundle, value.native_input
    )
    validate_reference_query_workflow_receipt(
        value.receipt,
        value.request,
        value.policy,
        value.bundle,
        value.launch,
        value.native_input,
        value.result,
        workflow_id=value.launch.workflow_id,
        step_run_id=value.launch.step_run_id,
        query_artifact_owner_job_id=value.receipt.query_artifact_owner_job_id,
        receipt_owner_job_id=value.receipt.receipt_owner_job_id,
    )
    validate_reference_query_step_output(value.output, value.receipt)
    records = public_query_records(value, device=device)
    for count in range(5):
        validate_native_reference_query_history(records[:count], value.launch, value.request)
    assert all(row.schema_version == "native-reference-query-coordinator/2.0" for row in records)
    for old_parser in (
        ReferenceQueryWorkflowRequestV3.model_validate,
        parse_reference_query_workflow_request_v3,
    ):
        with pytest.raises(ValueError):
            old_parser(value.request.model_dump(mode="json"))


def test_request4_schema_pin_mirror_and_unmodified_predecessor():
    name, identity, digest = REFERENCE_QUERY_REQUEST_V4_SCHEMA_RESOURCE
    raw = (ROOT / "schemas/workflow" / name).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert (
        sha256_bytes(raw) == digest and load_reference_query_request_v4_schema()["$id"] == identity
    )
    assert (
        sha256_bytes(
            (ROOT / "schemas/workflow/reference-query-execution-v2.schema.json").read_bytes()
        )
        == "sha256:504959a2de7aae1cf4636a277e7144ff0f80526ee11fd4157c98c2776ef09892"
    )


@pytest.mark.parametrize(
    "fault", ["extra", "old_context", "hash", "version", "device", "index", "policy", "float"]
)
def test_request4_rejects_foreign_or_unversioned_metadata(fault):
    value = registered_public_workflow_case()
    body = value.request.model_dump(mode="json")
    if fault == "extra":
        body["authority"] = "ADMIN"
    elif fault == "old_context":
        body["context_request"] = public_workflow_case().request.context_request.model_dump(
            mode="json"
        )
    elif fault == "hash":
        body["request_sha256"] = "sha256:" + "0" * 64
    elif fault == "version":
        body["schema_version"] = "reference-query-workflow-request/5.0"
    elif fault == "device":
        body["resource_profile"]["device"] = "CUDA"
    elif fault == "index":
        body["context_request"]["views"][0]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
        body["context_request"] = seal(body["context_request"], "request_sha256")
    elif fault == "policy":
        body["native_execution_policy"]["member_path"] = "some-other-policy.json"
    else:
        body["context_request"]["top_k"] = 5.0
    if fault not in {"hash", "float"}:
        body = seal(body, "request_sha256")
    with pytest.raises(ValueError):
        parse_supported_reference_query_workflow_request(body)


def test_existing_request3_is_not_retagged_or_reinterpreted():
    previous = public_workflow_case()
    document = deepcopy(previous.request.model_dump(mode="json"))
    assert parse_supported_reference_query_workflow_request(document) == previous.request
    with pytest.raises(ValueError):
        ReferenceQueryWorkflowRequestV4.model_validate(document)
