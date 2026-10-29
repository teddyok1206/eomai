"""Pure root-notice→route closure only, not an actual allocation/source grant."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from eom_workflow.embedding_batch_owner_control import parse_embedding_batch_owner_control
from eom_workflow_runner.embedding_batch_execution import (
    CatalogEmbeddingBatchExecution,
    _root_route,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import control_frames
from tests.unit.test_embedding_batch_plan import planning_case


@pytest.mark.parametrize("busy", (False, True))
def test_route_uses_exact_original_root_frame_and_device_without_availability_reprobe(busy):
    case = planning_case()
    frames = control_frames(request=case.allocation.control_request)
    notice = frames.busy if busy else frames.ready
    route = _root_route(case.request, case.allocation, case.policy, notice)
    assert route.observation.allocation_reference_sha256 == notice.message_sha256
    assert route.observation.status == ("BUSY" if busy else "ACQUIRED")
    assert route.decision.selected.backend.device == ("CPU" if busy else "CUDA")
    assert route.allocation_record_sha256 == case.allocation.record_sha256


@pytest.mark.parametrize("field", ("allocation_attempt_id", "allocation_request_sha256"))
@pytest.mark.parametrize("busy", (False, True))
def test_other_original_root_frame_cannot_select_a_route(field, busy):
    case = planning_case()
    frames = control_frames(request=case.allocation.control_request)
    notice = frames.busy if busy else frames.ready
    body = notice.model_dump(mode="json")
    body[field] = (
        "embeddingallocation_" + "f" * 32
        if field == "allocation_attempt_id"
        else "sha256:" + "f" * 64
    )
    notice = parse_embedding_batch_owner_control(seal(body, "message_sha256"))
    with pytest.raises(ValueError):
        _root_route(case.request, case.allocation, case.policy, notice)


def test_unknown_or_shape_only_allocation_never_selects_cpu():
    case = planning_case()
    with pytest.raises(ValueError):
        _root_route(case.request, case.allocation, case.policy, SimpleNamespace(status="UNKNOWN"))


def test_automatic_index_allocation_rejects_query_before_any_owner_or_database_access():
    operation = object.__new__(CatalogEmbeddingBatchExecution)
    case = planning_case(purpose="REFERENCE_QUERY")
    with (
        pytest.raises(ValueError, match="EMBEDDING_BATCH_EXECUTION_INVALID"),
        operation.open_index(case.request),
    ):
        pytest.fail("QUERY entered the fresh INDEX allocation boundary")
