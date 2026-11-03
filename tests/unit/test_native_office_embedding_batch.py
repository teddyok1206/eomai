"""Native Office source provenance in the existing finite GPU parent; no live model."""

import pytest
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_plan_controls,
)
from eom_workflow_runner.document_embedding_parent_preparation import (
    prepare_document_embedding_parent,
)

from tests.unit.document_embedding_parent_fixtures import parent_case as parent_case
from tests.unit.test_local_indexing_routed_sources import routed as routed
from tests.unit.test_local_indexing_routed_sources import routed_publisher as routed_publisher


@pytest.mark.parametrize("routed", ["registered_public"], indirect=True)
@pytest.mark.parametrize("parent_case", [True], indirect=True)
def test_native_office_parent_pins_true_report_and_reuses_original_gpu_execution(parent_case):
    value = parent_case
    assert value.request.schema_version == "local-embedding-workflow-request/5.0"
    parent = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    replay = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    assert parent.request == replay.request
    assert parent.request.schema_version == "embedding-batch-plan/1.8"
    assert embedding_batch_plan_schema_identity(parent.request)[0] == "embedding-batch-plan/1.8"
    assert parse_embedding_batch_plan_request(parent.request) == parent.request
    with (
        value.routed.publisher.sessions.begin() as session,
        parent.operation.admission.admit(session, parent.request) as admitted,
    ):
        selection = admitted.selection
        assert parse_embedding_batch_selection(selection) == selection
        validate_embedding_batch_plan_controls(parent.request, selection, admitted.policy)
        native = next(
            a for a in selection.anchors if a.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT"
        )
        assert native.profile.schema_ref.endswith("/3.0")
        assert native.evidence.role_result.schema_ref == "external-item-learning-result@3.0"
