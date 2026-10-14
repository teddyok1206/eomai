"""Closed protocol and owner-root negatives; no real service/source grant."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_workflow.local_indexing_preallocation_retirement import (
    LOCAL_INDEXING_RETIREMENT_SCHEMA_RESOURCE,
    parse_local_indexing_retirement_command,
    parse_local_indexing_retirement_receipt,
)
from eom_workflow_runner.local_indexing_preallocation_retirement import (
    LocalIndexingRetirementError,
    retire_unallocated_indexing_workflow,
)
from sqlalchemy.orm import Session

from tests.unit.local_embedding_service_fixtures import service_fixture


def command_document(**changes):
    native = service_fixture()
    body = {
        "schema_version": "local-indexing-preallocation-retirement/1.0",
        "record_type": "COMMAND",
        "workflow_id": "workflow_" + "a" * 32,
        "workflow_request_sha256": native.request.request_sha256,
        "command_id": "wfcmd_" + "b" * 32,
        "lease_generation": 1,
        "service": {
            key: getattr(native.request.actor_context, key)
            for key in ("service_id", "service_revision_id", "service_identity_sha256")
        },
        "successor_source_commit": "c" * 40,
        "reason": "EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE",
    } | changes
    return body | {"command_sha256": content_sha256(body)}


def receipt_document(**changes):
    body = {
        "schema_version": "local-indexing-preallocation-retirement/1.0",
        "record_type": "RECEIPT",
        "command": command_document(),
        "step_run_id": "steprun_" + "d" * 32,
        "performed_by": "synthetic_owner",
        "performed_at": "2026-10-14T13:00:00Z",
        "prior_command_state": "PROCESSING",
        "new_workflow_state": "FAILED",
        "new_stage": "FAILED",
        "new_command_state": "FAILED",
        "new_step_state": "FAILED",
    } | changes
    return body | {"receipt_sha256": content_sha256(body)}


def test_released_resource_and_exact_bounded_roundtrip():
    filename, schema_id, expected = LOCAL_INDEXING_RETIREMENT_SCHEMA_RESOURCE
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == expected
    assert json.loads(raw)["$id"] == schema_id
    command = parse_local_indexing_retirement_command(command_document())
    assert parse_local_indexing_retirement_command(command) == command
    receipt = parse_local_indexing_retirement_receipt(receipt_document())
    assert parse_local_indexing_retirement_receipt(receipt).command == command


@pytest.mark.parametrize(
    "changes",
    [
        {"lease_generation": True},
        {"lease_generation": 0},
        {"reason": "FORCE"},
        {"reason": "TIMEOUT"},
        {"record_type": "RECEIPT"},
        {"extra": True},
        {"successor_source_commit": "latest"},
        {"workflow_id": "workflow_invalid"},
    ],
)
def test_closed_command_rejects_invalid_or_unbounded_operations(changes):
    with pytest.raises(ValueError):
        parse_local_indexing_retirement_command(command_document(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"new_workflow_state": "COMPLETED"},
        {"new_step_state": "SUCCEEDED"},
        {"performed_at": "2026-10-14T13:00:00+09:00"},
        {"performed_by": "ADMIN/worker"},
        {"prior_command_state": "PENDING"},
        {"extra": True},
    ],
)
def test_receipt_never_reinterprets_failure_as_success(changes):
    with pytest.raises(ValueError):
        parse_local_indexing_retirement_receipt(receipt_document(**changes))


def test_unvalidated_copy_hash_or_nested_mutation_is_not_trusted():
    command = parse_local_indexing_retirement_command(command_document())
    with pytest.raises(ValueError):
        parse_local_indexing_retirement_command(command.model_copy(update={"lease_generation": 2}))
    receipt = parse_local_indexing_retirement_receipt(receipt_document())
    with pytest.raises(ValueError):
        parse_local_indexing_retirement_receipt(
            receipt.model_copy(update={"command": command.model_copy(update={"reason": "FORCE"})})
        )


@pytest.mark.parametrize(
    "fault", ["no_root", "inactive", "nested", "new", "dirty", "deleted", "dialect"]
)
def test_maintenance_requires_a_clean_explicit_postgres_root(fault):
    session = Mock(spec=Session)
    session.get_transaction.return_value = (
        None if fault == "no_root" else SimpleNamespace(is_active=fault != "inactive")
    )
    session.in_nested_transaction.return_value = fault == "nested"
    session.new, session.dirty, session.deleted = (
        {1} if fault == "new" else set(),
        {1} if fault == "dirty" else set(),
        {1} if fault == "deleted" else set(),
    )
    session.get_bind.return_value.dialect.name = "sqlite" if fault == "dialect" else "postgresql"
    with pytest.raises(LocalIndexingRetirementError, match="CONTEXT_INVALID"):
        retire_unallocated_indexing_workflow(
            session, parse_local_indexing_retirement_command(command_document())
        )
    session.execute.assert_not_called()
