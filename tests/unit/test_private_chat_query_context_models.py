"""Frozen private metadata DDL; neither compiled admission nor installed migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_persistence_guards import (
    PRIVATE_CHAT_QUERY_CONTEXT_CHECK,
    PRIVATE_CHAT_QUERY_CONTEXT_PREDICATE,
    PRIVATE_CHAT_QUERY_TURN_INDEX,
)
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex

from tests.unit.test_private_chat_query_submission_context import context_case

ROOT = Path(__file__).resolve().parents[2]


def migration_module():
    spec = importlib.util.spec_from_file_location(
        "private_query_context_migration",
        ROOT / "migrations/versions/20261017_0056_private_chat_query_context.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_guard_matches_frozen_additive_migration_and_latest_head():
    migration = migration_module()
    assert migration.revision == CURRENT_MIGRATION_REVISION == "20261017_0056"
    assert migration.down_revision == "20261014_0055"
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == [CURRENT_MIGRATION_REVISION]
    checks = {
        c.name: str(c.sqltext)
        for c in WorkflowInstanceRecord.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert (
        checks[PRIVATE_CHAT_QUERY_CONTEXT_CHECK]
        == PRIVATE_CHAT_QUERY_CONTEXT_PREDICATE
        == migration._PREDICATE
    )
    assert "IS TRUE ELSE TRUE END" in migration._PREDICATE
    assert "octet_length(runtime_context::text) <= 65536" in migration._PREDICATE
    assert "runtime_context - ARRAY" in migration._PREDICATE
    assert "SECURITY DEFINER" not in migration._MUTATION_FUNCTION
    assert "SET search_path = pg_catalog" in migration._MUTATION_FUNCTION


def test_persistence_id_patterns_match_the_existing_closed_origin_contract():
    value = context_case()
    conversation = value.context.origin.basis.conversation_id
    turn = value.context.origin.basis.turn_id
    assert conversation.startswith("chat_") and not conversation.startswith("chatconv_")
    assert turn.startswith("chatturn_")
    assert "'^chat_[0-9a-f]{32}$'" in PRIVATE_CHAT_QUERY_CONTEXT_PREDICATE
    assert "'^chatturn_[0-9a-f]{32}$'" in PRIVATE_CHAT_QUERY_CONTEXT_PREDICATE


def test_unique_turn_index_is_partial_keyed_and_does_not_open_private_steps():
    index = next(
        i
        for i in WorkflowInstanceRecord.__table__.indexes
        if i.name == PRIVATE_CHAT_QUERY_TURN_INDEX
    )
    sql = str(CreateIndex(index).compile(dialect=dialect()))
    assert index.unique
    assert (
        "created_actor_id" in sql
        and "{origin,basis,conversation_id}" in sql
        and "{origin,basis,turn_id}" in sql
    )
    assert "WHERE definition_key = 'local-embedding-private-chat-query'" in sql
    assert "GIN" not in sql
    steps = next(
        str(c.sqltext)
        for c in WorkflowStepRunRecord.__table__.constraints
        if c.name == "ck_workflow_step_runs_local_embedding"
    )
    assert "embedding-private-chat-query" not in steps
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "1.0.0")
