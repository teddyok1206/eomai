"""Closed metadata dispatch preserves old public rows and unchanged numerical jobs."""

import pytest
from eom_workflow.local_embedding_request_v2 import parse_supported_local_embedding_request
from eom_workflow.local_embedding_source_plan_dispatch import (
    parse_supported_local_embedding_source_plan,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    build_supported_local_embedding_step_output,
    parse_supported_local_embedding_step_output,
    parse_supported_local_embedding_workflow_receipt,
)
from eom_workflow.native_embedding_coordinator_dispatch import (
    native_completed_payload,
    native_prepared_payload,
    native_registered_payload,
)

from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_public_solution_native_carriers import public_native_fixture
from tests.unit.test_registered_public_solution_completion import completion_case


@pytest.mark.parametrize("version", ["3.0", "4.0"])
def test_exact_request_plan_receipt_and_output_dispatch_preserve_numeric_one(version):
    if version == "3.0":
        value = public_native_fixture(device="CUDA")
        request, plan, receipt, output = (
            value[key] for key in ("request", "plan", "receipt", "output")
        )
    else:
        value = completion_case()
        request, plan, receipt, output = (
            value.case.request,
            value.case.plan,
            value.receipt,
            value.output,
        )
    for wire in (plan, plan.model_dump(mode="json")):
        assert parse_supported_local_embedding_source_plan(wire) == plan
    assert parse_supported_local_embedding_request(request.model_dump(mode="json")) == request
    assert (
        parse_supported_local_embedding_workflow_receipt(receipt.model_dump(mode="json")) == receipt
    )
    assert parse_supported_local_embedding_step_output(output.model_dump(mode="json")) == output
    assert build_supported_local_embedding_step_output(receipt, output.receipt) == output
    assert output.execution_result_schema == "incremental-embedding-result@1.0"
    assert request.workflow_definition_version == "2.0.0"
    assert request.schema_version.endswith(version)
    assert (
        native_prepared_payload(receipt.registration_command, created_at=NOW).registration_command
        == receipt.registration_command
    )
    assert (
        native_registered_payload(
            receipt.registration_result, observed_at=receipt.registration_observed_at
        ).registration_result
        == receipt.registration_result
    )
    assert native_completed_payload(output).output == output


@pytest.mark.parametrize("fault", ["unknown", "extra", "wrong_pointer", "foreign_receipt"])
def test_registered_metadata_dispatch_does_not_erase_family_or_pointer_validation(fault):
    value = completion_case()
    if fault in {"unknown", "extra"}:
        document = value.case.plan.model_dump(mode="json")
        if fault == "unknown":
            document["schema_version"] = "local-embedding-source-plan/5.0"
        else:
            document["permission_override"] = True
        with pytest.raises(ValueError):
            parse_supported_local_embedding_source_plan(document)
    else:
        receipt = value.case.original["receipt"] if fault == "foreign_receipt" else value.receipt
        pointer = (
            value.output.receipt.model_copy(update={"sha256": "sha256:" + "0" * 64})
            if fault == "wrong_pointer"
            else value.output.receipt
        )
        with pytest.raises(ValueError):
            build_supported_local_embedding_step_output(receipt, pointer)


@pytest.mark.parametrize(
    "builder", [native_prepared_payload, native_registered_payload, native_completed_payload]
)
def test_unknown_runtime_family_cannot_be_silently_retagged(builder):
    from tests.unit.inference_transfer_fixtures import NOW

    kwargs = (
        {"created_at": NOW}
        if builder is native_prepared_payload
        else {"observed_at": NOW}
        if builder is native_registered_payload
        else {}
    )
    with pytest.raises(ValueError, match="FAMILY_MISMATCH"):
        builder(object(), **kwargs)
