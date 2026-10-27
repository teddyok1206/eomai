"""External source storage must not masquerade as approved Item storage."""

from __future__ import annotations

import eom_catalog_service.models as catalog_models
from alembic.config import Config
from alembic.script import ScriptDirectory
from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


def test_external_item_tables_are_separate_and_pointer_based() -> None:
    source_file_table = catalog_models.ContentIntakeSourceFileRecord.__table__
    assert source_file_table.name == "content_intake_source_files"
    tables = (
        ExternalItemImportRecord.__table__,
        ExternalItemSourceRecord.__table__,
        ExternalItemSourceRevisionRecord.__table__,
        ExternalItemEditionDocumentRecord.__table__,
    )
    assert {table.name for table in tables} == {
        "external_item_imports",
        "external_item_sources",
        "external_item_source_revisions",
        "external_item_edition_documents",
    }
    for table in tables:
        assert "BYTEA" not in str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "cells" in ExternalItemSourceRevisionRecord.__table__.columns
    assert "mapping_document" in ExternalItemImportRecord.__table__.columns
    assert "workbook_source_file_id" in ExternalItemImportRecord.__table__.columns
    assert "selected_source_file_id" in ExternalItemSourceRevisionRecord.__table__.columns
    assert "item_revision_id" not in ExternalItemSourceRevisionRecord.__table__.columns


def test_external_item_uniqueness_and_pinned_file_reference() -> None:
    source_table = ExternalItemSourceRecord.__table__
    revision_table = ExternalItemSourceRevisionRecord.__table__
    source_uniques = {
        tuple(constraint.columns.keys())
        for constraint in source_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    revision_uniques = {
        tuple(constraint.columns.keys())
        for constraint in revision_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("source_namespace", "external_number") in source_uniques
    assert ("source_id", "revision_number") in revision_uniques
    assert ("import_id", "row_number") in revision_uniques
    assert ("import_id", "external_number") in revision_uniques
    assert any(
        "content_intake_source_files.source_file_id" in str(constraint)
        for constraint in revision_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    )
    assert any(
        "jsonb_array_length(cells) = 32" in str(constraint.sqltext)
        for constraint in revision_table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_external_item_migration_remains_in_the_single_revision_chain() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_revision("20261027_0060") is not None
    assert scripts.get_heads() == ["20261027_0062"]
