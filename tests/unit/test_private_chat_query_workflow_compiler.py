"""Private fixed-graph compiler support is not a source/claim/native runtime grant."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.compiler import WorkflowDefinitionError, compile_definition_data
from eom_workflow.definition_execution_protocol import (
    DefinitionExecutionProtocolError,
    definition_execution_protocol,
)
from eom_workflow.private_chat_query_workflow import (
    PRIVATE_CHAT_QUERY_EXECUTION_PROTOCOL,
    PrivateChatQueryStep,
    PrivateChatQueryWorkflowDefinition,
)
from eom_workflow_runner.repository import (
    import_workflow_definition,
    workflow_definition_admission_statuses,
)
from sqlalchemy.orm import Session

from tests.unit.test_private_chat_query_workflow import definition_body


def test_private_definition_compiles_without_codex_roles_and_preserves_its_fixed_hash():
    raw = definition_body()
    typed = PrivateChatQueryWorkflowDefinition.model_validate(raw)
    compiled = compile_definition_data(raw, "synthetic-private-fixed-graph", set())
    assert type(compiled.definition) is PrivateChatQueryWorkflowDefinition
    assert compiled.definition == typed
    assert compiled.canonical_bytes == canonical_json_bytes(typed)
    assert compiled.sha256 == sha256_bytes(canonical_json_bytes(typed))
    assert (
        definition_execution_protocol(compiled.definition) == PRIVATE_CHAT_QUERY_EXECUTION_PROTOCOL
    )
    assert isinstance(compiled.steps_by_key["encode_private_chat_query"], PrivateChatQueryStep)
    assert tuple(compiled.steps_by_key) == ("encode_private_chat_query", "complete")
    assert compiled.automatic_review_rework is None
    assert (
        compile_definition_data(compiled.as_dict(), "same-fixed-graph", set()).sha256
        == compiled.sha256
    )


@pytest.mark.parametrize(
    "fault", ["key", "schema", "operation", "role", "attempt", "terminal", "extra"]
)
def test_private_compiler_rejects_relabelled_or_broadened_fixed_graphs(fault):
    raw = deepcopy(definition_body())
    if fault == "key":
        raw["definition_key"] = "local-embedding-reference-query"
    elif fault == "schema":
        raw["schema_version"] = "1.2"
    elif fault == "operation":
        raw["steps"][0]["operation"] = "BUILD_REFERENCE_QUERY_EMBEDDINGS"
    elif fault == "role":
        raw["steps"][0]["worker_role"] = "authoring"
    elif fault == "attempt":
        raw["limits"]["max_step_attempts"] = 2
    elif fault == "terminal":
        raw["steps"][1]["terminal_status"] = "FAILED"
    else:
        raw["authority"] = "ADMIN"
    with pytest.raises(WorkflowDefinitionError):
        compile_definition_data(raw, "synthetic-invalid-private", {"authoring"})


def test_private_protocol_calculation_revalidates_untrusted_model_copies():
    fixed = PrivateChatQueryWorkflowDefinition.model_validate(definition_body())
    assert definition_execution_protocol(fixed) == PRIVATE_CHAT_QUERY_EXECUTION_PROTOCOL
    copied = fixed.model_copy(update={"authority": "ADMIN"})
    with pytest.raises(DefinitionExecutionProtocolError):
        definition_execution_protocol(copied)


def test_private_definition_import_remains_inactive_and_reports_its_own_protocol():
    compiled = compile_definition_data(definition_body(), "synthetic-inactive-private", set())
    session = Mock(spec=Session)
    session.scalar.return_value = None
    record, created = import_workflow_definition(session, compiled)
    assert created and record.active is False
    session.scalars.return_value = (record,)
    (status,) = workflow_definition_admission_statuses(session)
    assert status.role_protocol_version == PRIVATE_CHAT_QUERY_EXECUTION_PROTOCOL
    assert not status.active and not status.admitted and not status.accepts_new_work
