"""Existing marker-guarded PlanStore with private metadata; no source/compute grant.

Reuse the original persistence cases instead of copying their concurrency rules.
Child authorization and physical observations remain explicit synthetic seams.
"""

from uuid import uuid4

import pytest
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_workflow.embedding_batch_plan_family import parse_embedding_batch_plan_request
from eom_workflow.embedding_batch_plan_v17 import EmbeddingBatchSelectionV17
from sqlalchemy.orm import Session

from tests.integration import test_embedding_batch_plan_store as cases
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.private_chat_batch_plan_fixtures import private_planning_case
from tests.unit.test_private_chat_query_batch_plan import parent_request

pytestmark = pytest.mark.integration


@pytest.fixture(params=("ACQUIRED", "BUSY"))
def planned(guarded_engine, request):
    value = private_planning_case(batch_id="embeddingbatch_" + uuid4().hex, status=request.param)
    value.engine = guarded_engine
    value.store = EmbeddingBatchPlanStore(value.request, value.selection, value.policy)
    expected = {child.native_input_sha256: child for child in value.bound.children}

    def authorize(child):
        if expected.get(child.native_input_sha256) != child:
            raise PermissionError("synthetic foreign private child")

    value.authorize = authorize
    return value


test_private_atomic_binding_replay = (
    cases.test_atomic_plan_binding_and_exact_replay_are_not_numerical_success
)
test_private_original_allocation_expiry = (
    cases.test_concurrent_larger_window_candidates_keep_original_allocation_and_expiry
)
test_private_one_original_dispatch_owner = (
    cases.test_two_controllers_reserve_one_original_allocation_and_only_one_dispatch_owner
)
test_private_interruption_rolls_back = cases.test_route_and_binding_roll_back_with_the_caller_root
test_private_failed_history_preserved = (
    cases.test_failed_planning_history_is_preserved_and_cannot_bind_or_become_success
)
test_private_concurrent_terminal_failure = (
    cases.test_concurrent_unbound_failure_has_one_terminal_event_and_exact_replay
)
test_private_late_failure_rollback = (
    cases.test_late_unbound_failure_evidence_change_rolls_back_terminal_history
)
test_private_routed_parent_not_unbound_failure = (
    cases.test_unbound_only_failure_never_closes_a_routed_parent
)
test_private_route_failure_race = (
    cases.test_concurrent_route_and_unbound_failure_have_one_atomic_winner
)
test_private_missing_allocation_and_savepoint = (
    cases.test_missing_allocation_and_savepoint_are_not_dispatch_authority
)
test_private_indexed_key = cases.test_plan_key_lookup_uses_existing_unique_btree_capability
test_private_late_child_denial = (
    cases.test_child_authorization_denial_rolls_back_binding_without_changing_route
)


def test_private_same_logical_batch_cannot_be_replaced_by_another_valid_selection(planned):
    with Session(planned.engine) as session, session.begin():
        original, _ = planned.store.allocate(session, planned.allocation)
    body = planned.selection.model_dump(mode="json")
    body["query"]["top_k"] -= 1
    selection = EmbeddingBatchSelectionV17.model_validate(seal(body, "selection_sha256"))
    request = parent_request(selection, planned.policy)
    changed = parse_embedding_batch_plan_request(
        seal(
            request.model_dump(mode="json") | {"batch_id": planned.request.batch_id},
            "request_sha256",
        )
    )
    conflicting = EmbeddingBatchPlanStore(changed, selection, planned.policy)
    assert conflicting.key == planned.store.key
    with pytest.raises(ValueError), Session(planned.engine) as session, session.begin():
        conflicting.read(session)
    with Session(planned.engine) as session, session.begin():
        assert planned.store.read(session) == original
