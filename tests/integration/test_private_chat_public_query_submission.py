"""Real disposable PG atomic private2 submission; authority and admission are fake ports.

No production admission, native units or model execution is enabled by these rows.
"""

import pytest

from tests.integration import test_private_chat_query_submission as original
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_public_query_native_persistence import query as query
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_private_chat_public_query_submission import make_common_submission_case

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def submission(query, monkeypatch):
    value = make_common_submission_case(query.source, monkeypatch)
    resolve = value.owner.resolve_submission

    def current(session, request, context):
        value.source.fault.session = session
        return resolve(session, request, context)

    monkeypatch.setattr(value.owner, "resolve_submission", current)
    return value


def test_postgres_common_original_start_replay_keeps_one_text_free_workflow(submission):
    original.test_postgres_original_private_start_is_atomic_replayable_and_text_free(submission)


@pytest.mark.parametrize("deny_at", [2, 3, 4])
def test_postgres_common_late_source_loss_rolls_back_root(submission, monkeypatch, deny_at):
    original.test_postgres_late_current_authority_denial_discards_released_submission_savepoints(
        submission, monkeypatch, deny_at
    )


def test_postgres_common_start_write_failure_discards_workflow_and_audit(submission, monkeypatch):
    original.test_postgres_start_persistence_failure_rolls_back_the_workflow_and_initial_audit(
        submission, monkeypatch
    )


def test_postgres_common_two_simultaneous_submissions_keep_one_original_start(
    submission, monkeypatch
):
    original.test_postgres_concurrent_original_private_submissions_reuse_one_workflow_and_start(
        submission, monkeypatch
    )


def test_postgres_common_failed_original_is_never_replaced_or_revived(submission):
    original.test_postgres_failed_original_workflow_is_not_replaced_or_revived(submission)


def test_postgres_common_missing_original_start_is_not_synthesized(submission):
    original.test_postgres_missing_original_start_is_not_synthesized_on_replay(submission)
