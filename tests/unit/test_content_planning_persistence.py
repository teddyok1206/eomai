"""Frozen migration and indexes match the Catalog-owned pointer model."""

from __future__ import annotations

import importlib
import re

import eom_catalog_service.curated_document_assembly_models
import eom_catalog_service.external_item_models
import eom_catalog_service.knowledge_graph_models
import eom_catalog_service.legacy_usage_models
import eom_catalog_service.models  # noqa: F401
import eom_identity_service.models  # noqa: F401
import pytest
from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentEditionRevisionFormRecord,
    ContentEditionRevisionRecord,
    ContentFormMembershipRecord,
    ContentFormRevisionCompositionRecord,
    ContentPlanningCommandReceiptRecord,
    ContentPlanningEventRecord,
)
from eom_catalog_service.content_print_models import (
    ContentPrintEventRecord,
    ContentPrintRecord,
    ContentPrintScopeRecord,
)
from eom_catalog_service.curated_document_slot_models import CuratedDocumentAssemblySlotRecord
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

TABLES = tuple(
    value.__table__
    for value in (
        ContentEditionRecord,
        ContentEditionRevisionRecord,
        ContentFormMembershipRecord,
        ContentFormRevisionCompositionRecord,
        ContentEditionRevisionFormRecord,
        CuratedDocumentAssemblySlotRecord,
        ContentPrintRecord,
        ContentPrintScopeRecord,
        ContentPrintEventRecord,
        ContentPlanningEventRecord,
        ContentPlanningCommandReceiptRecord,
    )
)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@pytest.mark.parametrize("table", TABLES, ids=lambda table: table.name)
def test_frozen_create_table_matches_current_model_and_stores_no_binary(table) -> None:
    migration = importlib.import_module("migrations.versions.20261109_0075_content_planning")
    actual = _normalized(str(CreateTable(table).compile(dialect=postgresql.dialect())))
    assert actual in {_normalized(value) for value in migration._DDL}
    assert "BYTEA" not in actual
    for index in table.indexes:
        assert _normalized(str(CreateIndex(index).compile(dialect=postgresql.dialect()))) in {
            _normalized(value) for value in migration._DDL
        }


def test_occurrences_are_unique_by_identity_and_position_never_target() -> None:
    table = CuratedDocumentAssemblySlotRecord.__table__
    assert tuple(table.primary_key.columns.keys()) == ("assembly_revision_id", "placement_id")
    uniques = [
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert uniques == [("assembly_revision_id", "position")]
    assert not any(index.unique for index in table.indexes)
    assert {index.name for index in table.indexes} == {
        "ix_curated_slot_item",
        "ix_curated_slot_source",
        "ix_curated_slot_item_revision",
        "ix_curated_slot_source_revision",
    }


def test_head_form_and_print_foreign_keys_keep_revision_ownership() -> None:
    checks = {
        ContentEditionRecord: "fk_content_edition_current_revision",
        ContentEditionRevisionFormRecord: "fk_content_leaf_form_scope",
        ContentFormRevisionCompositionRecord: "fk_content_form_revision_assembly",
        ContentPrintScopeRecord: "fk_content_print_scope_form",
    }
    for model, name in checks.items():
        constraint = next(value for value in model.__table__.constraints if value.name == name)
        assert isinstance(constraint, ForeignKeyConstraint)
        assert len(constraint.elements) == 3
        assert constraint.ondelete == "RESTRICT"


def test_initial_print_is_unique_but_reprints_are_explicit() -> None:
    index = next(
        value
        for value in ContentPrintRecord.__table__.indexes
        if value.name == "uq_content_print_initial"
    )
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE" in sql and "WHERE intent = 'INITIAL'" in sql
    assert "edition_id, scope_sha256" in sql


def test_replay_identity_is_actor_command_and_key() -> None:
    assert tuple(ContentPlanningCommandReceiptRecord.__table__.primary_key.columns.keys()) == (
        "actor_id",
        "command_kind",
        "idempotency_key",
    )


def test_reverse_lookup_starts_from_current_heads_and_exact_form_indexes() -> None:
    for model, expected in (
        (ContentEditionRevisionFormRecord, "ix_content_leaf_form_revision"),
        (ContentFormRevisionCompositionRecord, "ix_content_form_revision_assembly"),
        (ContentPrintScopeRecord, "ix_content_print_scope_form"),
        (ContentEditionRevisionRecord, "ix_content_revision_year"),
    ):
        assert expected in {index.name for index in model.__table__.indexes}
