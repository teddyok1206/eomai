"""Guarded PostgreSQL original command/Job lineage; not private step/runtime admission.

Controls/index/Workflow/command/Job SQL and files are actual; Chat/IAM/public
population and the not-yet-admitted private step view remain synthetic.
"""

import pytest
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_workflow_runner.models import WorkflowCommandRecord

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_query_source_owner import make_owned_private_source
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_query_command_lineage import (
    enqueue_continuation,
    make_continuation_case,
    resolve_continuation,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def continuation(registered, guarded_engine, tmp_path, monkeypatch):
    source = make_owned_private_source(
        registered,
        guarded_engine,
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )
    return make_continuation_case(tmp_path, monkeypatch, source=source)


def test_postgres_exact_original_continuation_is_read_only_and_idempotent(continuation):
    value = continuation
    command_id, created = enqueue_continuation(value)
    assert created and enqueue_continuation(value) == (command_id, False)
    first = resolve_continuation(value, command_id)
    assert len(first.documents.sources) == 1
    assert resolve_continuation(value, command_id) == first
    launch, history = value.query.history()
    assert launch == value.launch and len(history.records) == 1 and not value.query.runs
    with value.query.publisher.sessions.begin() as session:
        command = session.get(WorkflowCommandRecord, command_id)
        assert command.state == "PENDING" and command.lease_generation == 0
        assert session.get(JobRecord, launch.native_launch_job_id).status == "RUNNING"


def test_postgres_failed_original_job_cannot_supply_a_continuation(continuation):
    value = continuation
    command_id, _ = enqueue_continuation(value)
    with value.query.publisher.sessions.begin() as session:
        NativePrivateChatQueryCoordinator(value.query.request, value.launch).record_known_failure(
            session
        )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_UNAVAILABLE"):
        resolve_continuation(value, command_id)
    with value.query.publisher.sessions.begin() as session:
        assert session.get(JobRecord, value.launch.native_launch_job_id).status == "FAILED"
        assert session.get(WorkflowCommandRecord, command_id).state == "PENDING"
    assert not value.query.runs


def test_postgres_original_lineage_never_substitutes_current_chat_authority(continuation):
    value = continuation
    command_id, _ = enqueue_continuation(value)
    value.query.source.fault.value = "claim"
    with pytest.raises(SimilarityContextReadError):
        resolve_continuation(value, command_id)
    with value.query.publisher.sessions.begin() as session:
        assert session.get(WorkflowCommandRecord, command_id).lease_generation == 0
    assert not value.query.runs
