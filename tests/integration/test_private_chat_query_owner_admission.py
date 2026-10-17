"""Real PostgreSQL row/command/lease roots with registered control/index files.

Chat/IAM/source population and declared Workflow/START are synthetic, not private
compiler/native admission. No step/model/unit/activation is exercised or granted.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow_runner import native_command_fence as fence_module
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.native_workflow_transaction import native_fenced_runner_transaction
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_query_source_owner import owned as owned
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_owner_admission import seed_owner_rows

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def declared(owned):
    value = seed_owner_rows(owned.publisher, owned.request, owned.origin)
    value.source = owned
    value.owner = CatalogPrivateChatQueryOwnerAdmission(owned.owner)
    return value


def _processing(value, *, expired=False):
    lease = CommandLeaseIdentity(
        value.command_id, "synthetic-private-owner", "wflease_" + uuid4().hex, 1
    )
    with value.source.publisher.sessions.begin() as session:
        command = session.get(WorkflowCommandRecord, value.command_id)
        assert command is not None
        command.state, command.attempts = "PROCESSING", 1
        command.lease_owner, command.lease_token, command.lease_generation = (
            lease.runner_id,
            lease.lease_token,
            1,
        )
        command.lease_expires_at = datetime.now(UTC) + timedelta(seconds=-1 if expired else 60)
    return lease


def test_postgres_original_claim_is_read_only_and_resolves_registered_controls(declared):
    with declared.source.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, declared.workflow_id)
        command = session.get(WorkflowCommandRecord, declared.command_id)
        root = session.get_transaction()
        result = declared.owner.resolve_claim(
            session, workflow=workflow, command=command, request=declared.request
        )
        assert result.projection.origin == declared.context.origin
        assert len(result.documents.sources) == 1 and TEXT not in repr(result)
        assert command.state == "PENDING" and command.lease_generation == 0
        assert session.get_transaction() is root and not session.new and not session.dirty
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "1.0.0")


def test_postgres_private_shared_root_terminal_witness_does_not_survive_commit(declared):
    lease = _processing(declared)
    arguments = dict(
        owner=declared.owner,
        workflow_id=declared.workflow_id,
        request=declared.request,
        lease=lease,
    )
    with native_fenced_runner_transaction(
        declared.source.publisher.sessions, **arguments
    ) as session:
        command = session.get(WorkflowCommandRecord, declared.command_id)
        command.state = "SUCCEEDED"
    with (
        pytest.raises(WorkflowError, match="ownership was lost"),
        native_fenced_runner_transaction(declared.source.publisher.sessions, **arguments),
    ):
        pytest.fail("completed command cannot become an execution grant in another root")
    with declared.source.publisher.sessions.begin() as session:
        assert session.get(WorkflowCommandRecord, declared.command_id).state == "SUCCEEDED"


@pytest.mark.parametrize("fault", ("claim", "expiry_after_io", "generation"))
def test_postgres_late_private_authority_or_lease_loss_rolls_back_the_caller_root(
    declared, monkeypatch, fault
):
    lease = _processing(declared)
    source = declared.source.owner.chat
    original = source.authorize
    clock = {"late": False, "authorizations": 0}
    observed = datetime.now(UTC)

    class Clock:
        @staticmethod
        def now(_tz):
            return observed + timedelta(hours=1) if clock["late"] else datetime.now(UTC)

    def authorize(origin):
        clock["authorizations"] += 1
        result = original(origin)
        if clock["authorizations"] == 2 and fault == "expiry_after_io":
            clock["late"] = True
        return result

    if fault == "expiry_after_io":
        monkeypatch.setattr(fence_module, "datetime", Clock)
        monkeypatch.setattr(source, "authorize", authorize)
    expected = SimilarityContextReadError if fault == "claim" else WorkflowError
    with (
        pytest.raises(expected),
        native_fenced_runner_transaction(
            declared.source.publisher.sessions,
            owner=declared.owner,
            workflow_id=declared.workflow_id,
            request=declared.request,
            lease=lease,
        ) as session,
    ):
        workflow = session.get(WorkflowInstanceRecord, declared.workflow_id)
        command = session.get(WorkflowCommandRecord, declared.command_id)
        workflow.lock_version += 1
        if fault == "claim":
            declared.source.fault.value = "claim"
        elif fault == "generation":
            command.lease_generation += 1
    if fault == "expiry_after_io":
        assert clock["authorizations"] == 2 and clock["late"]
    with declared.source.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, declared.workflow_id)
        command = session.get(WorkflowCommandRecord, declared.command_id)
        assert workflow.lock_version == 1 and command.lease_generation == 1
        assert workflow.runtime_context == declared.context.model_dump(mode="json")


def test_postgres_expired_original_without_step_is_not_a_fresh_numerical_retry(declared):
    _processing(declared, expired=True)
    with (
        declared.source.publisher.sessions.begin() as session,
        pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_MISSING"),
    ):
        declared.owner.resolve_claim(
            session,
            workflow=session.get(WorkflowInstanceRecord, declared.workflow_id),
            command=session.get(WorkflowCommandRecord, declared.command_id),
            request=declared.request,
        )


def test_postgres_pending_caller_write_cannot_autoflush_before_source_admission(declared):
    with declared.source.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, declared.workflow_id)
        command = session.get(WorkflowCommandRecord, declared.command_id)
        command.state = "FAILED"
        assert not declared.source.fault.final_authorization_reached
        with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
            declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )
        assert not declared.source.fault.final_authorization_reached
        session.rollback()
