"""Existing application/Runner for common2; admission/context ports are declared synthetic."""

from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityContextV2
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_workflow.admission import workflow_definition_is_admitted

from tests.unit import test_private_chat_query_prepare_application as legacy
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case
from tests.unit.test_private_chat_public_similarity_contracts import terminal
from tests.unit.test_private_chat_query_prepare_application import (
    observed_application as observed_application,
)
from tests.unit.test_private_chat_similarity_service import case as legacy_similarity_case


@pytest.fixture
def application(tmp_path, monkeypatch):
    current = make_private_public_source_case(tmp_path, monkeypatch)
    source = SimpleNamespace(
        owner=current.owner,
        publisher=current.old.publisher,
        request=current.request,
        policy=current.policy,
        projection=current.old.projection,
        events=current.old.events,
        fault=current.old.fault,
    )
    return legacy.make_private_prepare_application_case(source, monkeypatch)


@pytest.mark.parametrize("state", ("REQUESTED", "RUNNING"))
def test_common_prepare_and_read_keep_original_pending_without_new_work(
    observed_application, state
):
    legacy.test_pending_commits_original_before_offering_the_same_finite_driver(
        observed_application, state
    )
    observed_application.admitted.clear()
    observed_application.offers.clear()
    legacy.test_read_pending_never_offers_original_or_prepares_new_work(observed_application, state)


def test_common_read_missing_never_prepares_or_offers(observed_application):
    legacy.test_read_missing_is_explicit_without_preparation_or_drive(observed_application)


@pytest.mark.parametrize("state", ("FAILED", "CANCELLED", "unexpected"))
def test_common_failed_read_is_not_success_or_automatic_retry(observed_application, state):
    legacy.test_read_terminal_failure_preserves_original_without_drive(observed_application, state)


def test_common_empty_completed_read_truthfully_has_no_query_score(observed_application):
    legacy.test_read_completed_requires_canonical_context_outside_original_root(
        observed_application
    )
    assert isinstance(observed_application.context, PrivateChatSimilarityContextV2)
    assert observed_application.context.query_execution is None
    assert observed_application.context.population.scored_count == 0
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")


@pytest.mark.parametrize(
    "state,command", (("FAILED", None), ("CANCELLED", None), ("RUNNING", "failed"))
)
def test_common_prepare_preserves_terminal_or_command_failure(application, state, command):
    legacy.test_terminal_failure_has_no_drive_read_or_automatic_new_work(
        application, state, command
    )


def test_common_completed_prepare_uses_original_canonical_read(application):
    legacy.test_completed_work_is_ready_only_after_canonical_read_outside_admission_root(
        application
    )


@pytest.mark.parametrize("status", ("FAILED", "UNAVAILABLE"))
def test_common_failed_or_unavailable_context_does_not_become_ready(application, status):
    value = application
    value.state = "COMPLETED"
    body = terminal(status, reason="QUERY_NOT_OFFERED" if status == "UNAVAILABLE" else None)
    body["request"] = value.source.request.context_request.model_dump(mode="json")
    value.context = PrivateChatSimilarityContextV2.model_validate(seal(body, "context_sha256"))
    with pytest.raises(SimilarityContextReadError):
        legacy.prepare(value)
    assert not value.offers and value.executor.mock_calls == []


def test_common_completion_cannot_relabel_a_legacy_context(application):
    value = application
    value.state = "COMPLETED"
    value.context = legacy.empty_completed_context(
        SimpleNamespace(
            request=SimpleNamespace(
                context_request=legacy_similarity_case()[0],
            )
        )
    )
    with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
        legacy.prepare(value)
    assert not value.offers and value.executor.mock_calls == []
