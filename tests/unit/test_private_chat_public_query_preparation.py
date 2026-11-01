"""Common private2 preparation using actual local control bytes and synthetic IAM/START."""

from types import SimpleNamespace

import pytest
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)

from tests.unit import test_private_chat_query_preparation as original
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    current = make_private_public_source_case(tmp_path, monkeypatch)
    source = SimpleNamespace(
        publisher=current.old.publisher,
        owner=current.owner,
        request=current.request,
        policy=current.policy,
        saved_policy=current.saved,
        projection=current.old.projection,
        events=current.old.events,
        fault=current.old.fault,
        legacy_request=current.old.request,
    )
    return original.make_private_preparation_case(source, monkeypatch)


@pytest.mark.parametrize(
    "case",
    [
        original.test_read_absence_requires_current_identity_and_live_chat_without_creating_work,
        original.test_read_rejects_failed_full_original_row_validation_before_returning_status,
        original.test_builds_first_request_from_real_control_bytes_and_actual_caller,
    ],
)
def test_common_preparation_reuses_same_original_identity_and_control_boundaries(preparation, case):
    case(preparation)


@pytest.mark.parametrize(
    "case",
    [
        original.test_read_original_pins_never_reselects_head_rebuilds_or_starts,
        original.test_selection_captures_once_then_replays_same_original_without_recapturing,
        original.test_initial_missing_index_does_not_build_controls_start_or_fallback,
        original.test_initial_current_authority_denial_is_not_missing_index,
        original.test_exact_replay_retains_original_audit_context_and_pins_without_rebuilding,
        original.test_preparation_still_cannot_offer_closed_private_definition,
    ],
)
def test_common_preparation_preserves_exact_replay_no_fallback_and_closed_admission(
    preparation, monkeypatch, case
):
    case(preparation, monkeypatch)


@pytest.mark.parametrize("field", ["top_k", "request_id", "policy"])
def test_common_changed_read_intent_never_selects_a_new_head(preparation, field):
    original.test_read_changed_selection_is_not_silently_replaced_by_original(preparation, field)


@pytest.mark.parametrize("field", ["top_k", "request_id", "policy"])
def test_common_changed_selection_never_rebuilds_original(preparation, monkeypatch, field):
    original.test_changed_selection_replay_is_rejected_without_recapture(
        preparation, monkeypatch, field
    )


@pytest.mark.parametrize("field", ["context", "origin", "actor", "actor_type"])
def test_common_cannot_relabel_foreign_original_context(preparation, monkeypatch, field):
    original.test_changed_original_replay_is_rejected_without_reselect_or_new_start(
        preparation, monkeypatch, field
    )


@pytest.mark.parametrize("existing", [False, True])
def test_common_revoked_chat_cannot_disclose_original_state(preparation, monkeypatch, existing):
    original.test_read_revoked_chat_never_discloses_even_original_absence(
        preparation, monkeypatch, existing
    )


def test_legacy_original_is_not_upgraded_to_common_format_on_replay(preparation, monkeypatch):
    value = preparation
    request = value.source.legacy_request
    value.existing = SimpleNamespace(
        workflow_id="workflow_" + "c" * 32,
        state="REQUESTED",
        initial_request=request.model_dump(mode="json"),
        runtime_context=build_private_chat_query_submission_context(
            request, value.source.projection.origin
        ).model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=value.source.projection.origin.actor_id,
    )
    capture = original.Mock(side_effect=AssertionError("old origin must not select a new head"))
    monkeypatch.setattr(value.owner.catalog, "prepare_private_chat_context_in_session", capture)
    with (
        pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"),
        value.source.publisher.sessions.begin() as session,
    ):
        original.prepare_selection(value, session, original.initial_selection(value))
    assert value.existing.initial_request == request.model_dump(mode="json")
    capture.assert_not_called()
    value.start.assert_not_called()
