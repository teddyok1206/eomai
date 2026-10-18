"""Exact static release policy is not a live source, paired owner or native grant."""

from unittest.mock import Mock

import pytest
from eom_workflow.admission import workflow_admission, workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition_data
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.private_chat_query_admission import (
    resolve_private_chat_query_submission_controls,
)
from eom_workflow_runner.repository import (
    admitted_workflow_definition,
    import_workflow_definition,
    workflow_definition_admission_statuses,
)
from sqlalchemy.orm import Session

from tests.unit.test_private_chat_query_submission_context import context_case
from tests.unit.test_private_chat_query_workflow import definition_body


def test_exact_private_static_tuple_has_native_protocol_not_codex_role_protocol():
    value = workflow_admission("local-embedding-private-chat-query", "1.0.0")
    assert value is not None and value.role_protocol_version == "private-chat-query/1.0"
    assert workflow_definition_is_admitted("local-embedding-reference-query", "1.0.0")
    assert workflow_definition_is_admitted("local-embedding-index", "1.0.0")


@pytest.mark.parametrize(
    "key,version",
    [
        ("local-embedding-private-chat-query", "1.0.1"),
        ("local-embedding-private-chat-query", "latest"),
        ("local-embedding-private-chat-query", "1.0"),
        ("local-embedding-private-chat-query-other", "1.0.0"),
    ],
)
def test_private_static_release_does_not_admit_versions_or_latest_aliases(key, version):
    assert workflow_admission(key, version) is None
    assert not workflow_definition_is_admitted(key, version)


def test_private_static_tuple_does_not_activate_an_existing_inactive_snapshot():
    compiled = compile_definition_data(definition_body(), "declared-private-static", set())
    session = Mock(spec=Session)
    session.scalar.return_value = None
    record, created = import_workflow_definition(session, compiled)
    assert created and record.active
    record.active = False
    session.scalar.return_value = record
    replay, created = import_workflow_definition(session, compiled)
    assert replay is record and not created and record.active is False
    session.scalars.return_value = (record,)
    (status,) = workflow_definition_admission_statuses(session)
    assert status.admitted and not status.active and not status.accepts_new_work
    session.scalar.return_value = None
    assert (
        admitted_workflow_definition(
            session,
            definition_key=record.definition_key,
            definition_version=record.definition_version,
        )
        is None
    )


@pytest.mark.parametrize("owner,executor", [(None, None), (object(), None), (None, object())])
def test_real_private_static_admission_still_requires_both_actual_private_ports(owner, executor):
    value = context_case()
    session = Mock(spec=Session)
    with pytest.raises(WorkflowError, match="paired owner/executor"):
        resolve_private_chat_query_submission_controls(
            session,
            definition=Mock(),
            request=value.request,
            context=value.context,
            actor_type="human",
            actor_id=value.context.origin.actor_id,
            owner=owner,
            executor=executor,
        )
    session.get.assert_not_called()
    session.execute.assert_not_called()
    session.add.assert_not_called()


def test_private_definition_hash_conflict_does_not_rewrite_existing_identity():
    compiled = compile_definition_data(definition_body(), "declared-private-conflict", set())
    session = Mock(spec=Session)
    existing = Mock(definition_hash="sha256:" + "f" * 64)
    session.scalar.return_value = existing
    with pytest.raises(WorkflowError, match="different hash"):
        import_workflow_definition(session, compiled)
    session.add.assert_not_called()
    session.flush.assert_not_called()
