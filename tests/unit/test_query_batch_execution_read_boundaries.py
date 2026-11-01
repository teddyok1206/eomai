"""Explicit entry/type and pure metadata checks; no canonical/source/physical execution proof."""

import pytest
from eom_workflow.native_private_chat_query_coordinator import NativePrivateQueryBatchExecuted
from eom_workflow.native_reference_query_coordinator import NativeQueryBatchExecuted
from eom_workflow_runner import query_batch_execution_read as shared
from eom_workflow_runner import reference_query_batch_execution_read as public

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.private_chat_batch_plan_fixtures import private_planning_case
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_execution_contracts import pointer


def observations():
    private = NativePrivateQueryBatchExecuted(
        batch_receipt=pointer(
            "receipt.json",
            "eom://schemas/workflow/embedding-batch-execution-receipt/1.1",
            "sha256:" + "c" * 64,
        ),
        batch_receipt_sha256="sha256:" + "a" * 64,
        child_ordinal=0,
        result_sha256="sha256:" + "b" * 64,
        completed_observed_at="2026-10-24T19:00:01Z",
    )
    body = private.model_dump(mode="json")
    body["batch_receipt"]["schema_ref"] = (
        "eom://schemas/workflow/embedding-batch-execution-receipt/1.0"
    )
    return private, NativeQueryBatchExecuted.model_validate(body)


def test_public_compatibility_exports_use_one_authoritative_reader_and_comparison():
    assert (
        public.resolve_reference_query_batch_execution
        is shared.resolve_reference_query_batch_execution
    )
    assert (
        public.validate_reference_query_batch_child_result
        is shared.validate_reference_query_batch_child_result
    )


def test_private_observation_cannot_enter_public_source_or_pointer_resolution():
    private, _public = observations()
    with pytest.raises(ValueError, match="REFERENCE_QUERY_BATCH_EXECUTION_INVALID"):
        public.resolve_reference_query_batch_execution(
            object(),
            reader=object(),
            sources=object(),
            launch=object(),
            native_input=object(),
            executed=private,
        )


def test_public_observation_cannot_enter_private_resolution_even_inside_a_root(tmp_path):
    _private, public_observation = observations()
    publisher, _engine = _publisher(tmp_path)
    with (
        publisher.sessions.begin() as session,
        pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_BATCH_EXECUTION_INVALID"),
    ):
        shared.resolve_private_chat_query_batch_execution(
            session,
            reader=object(),
            sources=object(),
            launch=object(),
            native_input=object(),
            executed=public_observation,
        )


@pytest.mark.parametrize("field", (None, "result_sha256", "input_sha256"))
def test_shared_result_comparison_is_small_metadata_not_a_source_grant(field):
    value = execution_case(planned=private_planning_case())
    child, result = value.receipt.children[0], value.result.children[0].result
    if field is None:
        assert shared.validate_query_batch_child_result(child, result) is None
    else:
        altered = child.model_copy(update={field: "sha256:" + "f" * 64})
        with pytest.raises(shared.QueryBatchExecutionReadError):
            shared.validate_query_batch_child_result(altered, result)
        with pytest.raises(ValueError, match="REFERENCE_QUERY_BATCH_EXECUTION_INVALID"):
            public.validate_reference_query_batch_child_result(altered, result)
