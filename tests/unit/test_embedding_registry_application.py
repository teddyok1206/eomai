"""Synthetic application semantics and SQL shape; no DB or actual owner admission."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_service import embedding_registry_application as application
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryVerificationPort,
    MissingEmbeddingBindings,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.embedding_registry_repository import EmbeddingRegistryRepository
from jsonschema.exceptions import ValidationError as JsonSchemaError
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.unit.embedding_registry_application_fixtures import (
    MemoryRepository,
    MemorySession,
    SyntheticVerifier,
    capture_pair,
)
from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.inference_transfer_fixtures import NOW, sha

CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)
type MemoryFixture = tuple[MemorySession, SyntheticVerifier]


@pytest.fixture
def memory(monkeypatch: pytest.MonkeyPatch) -> tuple[MemorySession, SyntheticVerifier]:
    _, capture = capture_pair()
    monkeypatch.setattr(application, "EmbeddingRegistryRepository", MemoryRepository)
    return MemorySession(), SyntheticVerifier(capture)


def _register(
    session: MemorySession, owner: SyntheticVerifier, command: RegisterEmbeddingIndexCommand
) -> EmbeddingIndexRegistrationResult:
    return application.register_embedding_index(
        cast(Session, session),
        CALLER,
        command,
        cast(EmbeddingRegistryVerificationPort, owner),
        now=NOW,
    )


def _query(command: RegisterEmbeddingIndexCommand) -> EmbeddingRegistryLookup:
    return EmbeddingRegistryLookup(
        command.corpus_id,
        command.namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )


def test_registration_exact_replay_and_current_receipt(memory: MemoryFixture) -> None:
    session, owner = memory
    command, _ = capture_pair()
    first = _register(session, owner, command)
    replay = _register(session, owner, command)
    assert not first.replayed and first.is_current and replay.replayed and replay.is_current
    assert first.registered_at == replay.registered_at
    assert first.registered_lock_version == replay.current_lock_version == 2
    assert {name: len(rows) for name, rows in session.state.items()} == {
        "heads": 1,
        "revisions": 1,
        "encodings": 1,
        "bindings": 1,
    }
    assert owner.calls.count("resolve") == 2 and owner.calls.count("authorize") == 2


def test_registration_authority_fence_precedes_savepoint_but_resolution_stays_inside(
    memory: MemoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, owner = memory
    command, _ = capture_pair()
    original_nested = session.begin_nested
    original_authorize = owner.authorize_scope
    original_resolve = owner.resolve_registration
    events: list[str] = []
    depth = 0

    @contextmanager
    def nested() -> Iterator[None]:
        nonlocal depth
        events.append("savepoint")
        depth += 1
        try:
            with original_nested():
                yield
        finally:
            depth -= 1

    def authorize(
        current: Session,
        caller: EmbeddingRegistryCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
    ) -> None:
        assert depth == 0
        events.append("authority")
        original_authorize(current, caller, intent)

    def resolve(
        current: Session, caller: EmbeddingRegistryCaller, intent: RegisterEmbeddingIndexCommand
    ) -> ResolvedEmbeddingRegistration:
        assert depth == 1
        events.append("source-resolution")
        return original_resolve(current, caller, intent)

    monkeypatch.setattr(session, "begin_nested", nested)
    monkeypatch.setattr(owner, "authorize_scope", authorize)
    monkeypatch.setattr(owner, "resolve_registration", resolve)
    _register(session, owner, command)
    _register(session, owner, command)
    assert events[:3] == ["authority", "savepoint", "source-resolution"]
    assert events.count("authority") == 2


def test_registration_authority_denial_does_not_enter_savepoint_or_touch_registry(
    memory: MemoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, owner = memory
    command, _ = capture_pair()
    nested = Mock(side_effect=AssertionError("no savepoint before authority"))
    denied = Mock(side_effect=EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN"))
    monkeypatch.setattr(session, "begin_nested", nested)
    monkeypatch.setattr(owner, "authorize_scope", denied)
    with pytest.raises(EmbeddingRegistryError, match="EMBEDDING_REGISTRY_FORBIDDEN"):
        _register(session, owner, command)
    nested.assert_not_called()
    assert not owner.calls
    assert all(not rows for rows in session.state.values())


def test_historical_replay_never_rewinds_and_keeps_first_binding_origin(
    memory: MemoryFixture,
) -> None:
    session, owner = memory
    command, capture = capture_pair()
    second, successor = capture_pair(capture)
    owner.captures[successor.index.index_revision_id] = successor
    _register(session, owner, command)
    _register(session, owner, second)
    replay = _register(session, owner, command)
    assert replay.replayed and not replay.is_current
    assert replay.registered_lock_version == 2 and replay.current_lock_version == 3
    assert replay.current_index_revision_id == second.index_revision_id
    assert len(session.state["bindings"]) == len(session.state["encodings"]) == 1
    binding = next(iter(session.state["bindings"].values()))
    assert (
        binding.binding_manifest_artifact_revision_id == command.index_manifest.artifact_revision_id
    )


def test_same_operation_mismatch_is_stable_before_member_resolution(memory: MemoryFixture) -> None:
    session, owner = memory
    command, _ = capture_pair()
    _register(session, owner, command)
    calls = owner.calls.count("resolve")
    body = command.model_dump(mode="json")
    body["requested_at"] = "2026-10-12T02:00:00Z"
    changed = RegisterEmbeddingIndexCommand.model_validate(seal(body, "request_sha256"))
    with pytest.raises(EmbeddingRegistryError, match="REGISTRATION_CONFLICT"):
        _register(session, owner, changed)
    assert owner.calls.count("resolve") == calls
    assert len(session.state["revisions"]) == 1


def test_failed_cas_rolls_back_every_new_component(memory: MemoryFixture) -> None:
    session, owner = memory
    command, _ = capture_pair()
    session.cas_succeeds = False
    with pytest.raises(EmbeddingRegistryError, match="STALE_CURRENT"):
        _register(session, owner, command)
    assert all(not rows for rows in session.state.values())


@pytest.mark.parametrize(
    "field,state",
    [
        ("item_state", "DRAFT"),
        ("analysis_state", "REQUESTED"),
        ("member_state", "UNCOMMITTED"),
    ],
)
def test_foreign_keys_or_uncommitted_members_never_supply_authority(
    memory: MemoryFixture,
    field: str,
    state: str,
) -> None:
    session, owner = memory
    command, _ = capture_pair()
    setattr(owner, field, state)
    with pytest.raises(EmbeddingRegistryError):
        _register(session, owner, command)
    assert all(not rows for rows in session.state.values())


def test_revocation_blocks_replay_and_lookup_without_deleting_history(
    memory: MemoryFixture,
) -> None:
    session, owner = memory
    command, _ = capture_pair()
    _register(session, owner, command)
    owner.item_state = "RETIRED"
    for action in (
        lambda: _register(session, owner, command),
        lambda: application.lookup_missing_embedding_bindings(
            cast(Session, session),
            CALLER,
            _query(command),
            cast(EmbeddingRegistryVerificationPort, owner),
        ),
    ):
        with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
            action()
    assert len(session.state["revisions"]) == 1


def test_missing_lookup_then_exact_coverage_with_reusable_row(memory: MemoryFixture) -> None:
    session, owner = memory
    command, _ = capture_pair()

    def lookup() -> MissingEmbeddingBindings:
        return application.lookup_missing_embedding_bindings(
            cast(Session, session),
            CALLER,
            _query(command),
            cast(EmbeddingRegistryVerificationPort, owner),
        )

    first = lookup()
    assert len(first.missing) == 1 and not first.reusable_rows
    _register(session, owner, command)
    second = lookup()
    assert not second.missing and len(second.reusable_rows) == 1
    assert second.eligible_source_count == second.available_view_count == 1


def test_graph_only_binding_change_reuses_encoding_without_registering_rows(
    memory: MemoryFixture,
) -> None:
    session, owner = memory
    command, capture = capture_pair()
    _register(session, owner, command)
    body = capture.entries[0].model_dump(mode="json")
    graph = body["profile"]["source_basis"]["graph_snapshot"]
    graph["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    body["profile"]["profile_revision_id"] = "inferenceprofilerev_" + "f" * 32
    body["profile"] = seal(body["profile"], "profile_sha256")
    entry = StagedExperimentEntry.model_validate(body)
    owner.capture = replace(capture, entries=(entry,))
    query = replace(_query(command), graph_snapshot=entry.profile.source_basis.graph_snapshot)
    result = application.lookup_missing_embedding_bindings(
        cast(Session, session),
        CALLER,
        query,
        cast(EmbeddingRegistryVerificationPort, owner),
    )
    assert len(result.missing) == len(result.reusable_rows) == 1
    assert result.missing[0].encoding_sha256 == capture.index.bindings[0].encoding.encoding_sha256
    assert len(session.state["encodings"]) == len(session.state["bindings"]) == 1


@pytest.mark.parametrize(
    "change", ["corpus", "truncated", "foreign_entry", "index_hash", "source_set"]
)
def test_verified_capture_still_requires_exact_semantic_closure(change: str) -> None:
    command, capture = capture_pair()
    if change == "corpus":
        capture = replace(capture, corpus_id="corpus_" + "f" * 32)
    elif change == "truncated":
        capture = replace(capture, truncated=True)
    elif change == "foreign_entry":
        capture = replace(capture, entries=(*capture.entries, embedding_entry("b")))
    else:
        body = command.model_dump(mode="json")
        body["index_sha256" if change == "index_hash" else "source_set_sha256"] = sha("f")
        command = RegisterEmbeddingIndexCommand.model_validate(seal(body, "request_sha256"))
    with pytest.raises(EmbeddingRegistryError):
        application.validate_resolved_embedding_registration(command, capture)


def test_missing_verifier_transaction_and_model_role_are_explicit(memory: MemoryFixture) -> None:
    session, owner = memory
    command, _ = capture_pair()
    with pytest.raises(EmbeddingRegistryError, match="AUTHORITY_UNAVAILABLE"):
        application.register_embedding_index(cast(Session, session), CALLER, command, None)
    session.transaction_active = False
    with pytest.raises(EmbeddingRegistryError, match="TRANSACTION_REQUIRED"):
        _register(session, owner, command)
    session.transaction_active = True
    with pytest.raises(EmbeddingRegistryError, match="CALLER_INVALID"):
        application.register_embedding_index(
            cast(Session, session),
            EmbeddingRegistryCaller("ADMIN"),
            command,
            cast(EmbeddingRegistryVerificationPort, owner),
        )


def test_json_schema_failures_are_redacted_and_lookup_bound_precedes_owner(
    memory: MemoryFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, owner = memory
    command, _ = capture_pair()
    forged = command.model_copy(update={"operation": "ADMIN"})
    with pytest.raises(EmbeddingRegistryError, match="REQUEST_INVALID"):
        _register(session, owner, forged)
    monkeypatch.setattr(
        owner, "resolve_registration", Mock(side_effect=JsonSchemaError("untrusted item contents"))
    )
    with pytest.raises(EmbeddingRegistryError) as error:
        _register(session, owner, command)
    assert "untrusted" not in str(error.value)
    before = list(owner.calls)
    with pytest.raises(EmbeddingRegistryError, match="REQUEST_INVALID"):
        application.lookup_missing_embedding_bindings(
            cast(Session, session),
            CALLER,
            replace(_query(command), maximum_sources=1025),
            cast(EmbeddingRegistryVerificationPort, owner),
        )
    assert owner.calls == before


def test_same_operation_unique_retry_is_bounded_and_redacts_validation_failure(
    memory: MemoryFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, owner = memory
    command, _ = capture_pair()
    _register(session, owner, command)

    class DuplicateOperation(Exception):
        sqlstate = "23505"

    duplicate = IntegrityError(None, None, DuplicateOperation())
    attempt = Mock(side_effect=[duplicate, JsonSchemaError("private source contents")])
    monkeypatch.setattr(application, "_registration", attempt)
    with pytest.raises(EmbeddingRegistryError) as error:
        _register(session, owner, command)
    assert error.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"
    assert "private" not in str(error.value) and attempt.call_count == 2
    attempt.side_effect = [duplicate, duplicate, duplicate]
    with pytest.raises(EmbeddingRegistryError, match="REGISTRATION_CONFLICT"):
        _register(session, owner, command)
    assert attempt.call_count == 4


def test_repository_head_refresh_and_indexed_values_antijoin_shape() -> None:
    session = Mock(spec=Session)
    repository = EmbeddingRegistryRepository(session)
    repository.head("embeddingindex_" + "a" * 32)
    statement = session.scalar.call_args.args[0]
    assert statement.get_execution_options()["populate_existing"] is True
    assert statement._for_update_arg is not None
    _, capture = capture_pair()
    key = application._key(capture.index.bindings[0])
    session.execute.return_value.all.return_value = []
    assert repository.missing_bindings((key,)) == ()
    sql = str(session.execute.call_args.args[0].compile(dialect=cast(type[Dialect], PGDialect)()))
    assert "VALUES" in sql and "NOT (EXISTS" in sql and "embedding_source_bindings" in sql
    assert "base_analysis_run_id" in sql and "solution_analysis_run_id" in sql
    assert session.execute.call_count == 1
