"""Closed protocol and owner-root negatives; no real service/source grant."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_workflow.local_indexing_unstarted_cancellation import (
    LOCAL_INDEXING_UNSTARTED_CANCELLATION_SCHEMA_RESOURCE,
    parse_local_indexing_cancellation_command,
    parse_local_indexing_cancellation_receipt,
)
from eom_workflow_runner.local_indexing_unstarted_cancellation import (
    LocalIndexingCancellationError,
    cancel_unstarted_indexing_workflow,
)
from sqlalchemy.orm import Session

from tests.unit.local_embedding_service_fixtures import service_fixture


def command_document(**changes):
    native = service_fixture()
    body = {
        "schema_version": "local-indexing-unstarted-cancellation/1.0",
        "record_type": "COMMAND",
        "workflow_id": "workflow_" + "a" * 32,
        "workflow_request_sha256": native.request.request_sha256,
        "command_id": "wfcmd_" + "b" * 32,
        "service": {
            key: getattr(native.request.actor_context, key)
            for key in ("service_id", "service_revision_id", "service_identity_sha256")
        },
        "successor_source_commit": "c" * 40,
        "reason": "NATIVE_RUNTIME_RELEASE_SUPERSEDED",
    } | changes
    return body | {"command_sha256": content_sha256(body)}


def receipt_document(**changes):
    body = {
        "schema_version": "local-indexing-unstarted-cancellation/1.0",
        "record_type": "RECEIPT",
        "command": command_document(),
        "performed_by": "synthetic_owner",
        "performed_at": "2026-10-14T13:00:00Z",
        "prior_workflow_state": "REQUESTED",
        "prior_command_state": "PENDING",
        "step_run_count": 0,
        "new_workflow_state": "CANCELLED",
        "new_stage": "CANCELLED",
        "new_command_state": "CANCELLED",
    } | changes
    return body | {"receipt_sha256": content_sha256(body)}


def test_released_resource_and_exact_bounded_roundtrip():
    filename, schema_id, expected = LOCAL_INDEXING_UNSTARTED_CANCELLATION_SCHEMA_RESOURCE
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == expected
    assert json.loads(raw)["$id"] == schema_id
    command = parse_local_indexing_cancellation_command(command_document())
    assert parse_local_indexing_cancellation_command(command) == command
    receipt = parse_local_indexing_cancellation_receipt(receipt_document())
    assert parse_local_indexing_cancellation_receipt(receipt).command == command


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
        parse_local_indexing_cancellation_command(command_document(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"new_workflow_state": "COMPLETED"},
        {"step_run_count": True},
        {"performed_at": "2026-10-14T13:00:00+09:00"},
        {"performed_by": "ADMIN/worker"},
        {"prior_command_state": "PROCESSING"},
        {"extra": True},
    ],
)
def test_receipt_never_claims_execution_or_success(changes):
    with pytest.raises(ValueError):
        parse_local_indexing_cancellation_receipt(receipt_document(**changes))


def test_unvalidated_copy_hash_or_nested_mutation_is_not_trusted():
    command = parse_local_indexing_cancellation_command(command_document())
    with pytest.raises(ValueError):
        parse_local_indexing_cancellation_command(
            command.model_copy(update={"successor_source_commit": "changed"})
        )
    receipt = parse_local_indexing_cancellation_receipt(receipt_document())
    with pytest.raises(ValueError):
        parse_local_indexing_cancellation_receipt(
            receipt.model_copy(update={"command": command.model_copy(update={"reason": "FORCE"})})
        )


@pytest.mark.parametrize(
    "fault", ["no_root", "inactive", "nested", "new", "dirty", "deleted", "dialect"]
)
def test_clean_explicit_owner_root_is_required(fault):
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
    with pytest.raises(LocalIndexingCancellationError, match="CANCELLATION_CONTEXT_INVALID"):
        cancel_unstarted_indexing_workflow(
            session, parse_local_indexing_cancellation_command(command_document())
        )
    session.execute.assert_not_called()
