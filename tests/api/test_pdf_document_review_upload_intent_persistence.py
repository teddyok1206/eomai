from __future__ import annotations

import os
from typing import cast

import pytest
from eom_api.pdf_document_review_models import PdfDocumentReviewUploadIntentRecord
from eom_identifiers import new_pdf_review_upload_intent_id
from eom_orchestrator.database import build_engine
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import Index, LargeBinary, Table, inspect


def _indexes_by_name(table: Table) -> dict[str, Index]:
    values: dict[str, Index] = {}
    for index in table.indexes:
        assert index.name is not None
        values[str(index.name)] = index
    return values


def test_pdf_review_upload_intent_uses_small_metadata_and_indexed_access() -> None:
    table = cast(Table, PdfDocumentReviewUploadIntentRecord.__table__)
    assert table.name == "pdf_document_review_upload_intents"
    assert tuple(column.name for column in table.primary_key.columns) == ("upload_intent_id",)
    assert not any(isinstance(column.type, LargeBinary) for column in table.columns)
    assert "pdf" not in {column.name for column in table.columns}
    assert "content" not in {column.name for column in table.columns}

    indexes = _indexes_by_name(table)
    assert set(indexes) == {
        "ix_pdf_review_upload_intent_owner",
        "ix_pdf_review_upload_intent_lease",
    }
    assert tuple(
        expression.name if hasattr(expression, "name") else str(expression)
        for expression in indexes["ix_pdf_review_upload_intent_owner"].expressions
    ) == ("operator_id", "created_at DESC", "upload_intent_id")
    assert (
        str(indexes["ix_pdf_review_upload_intent_lease"].dialect_options["postgresql"]["where"])
        == "state = 'PROCESSING'"
    )


def test_pdf_review_upload_intent_identifier_and_migration_head_are_exact() -> None:
    value = new_pdf_review_upload_intent_id()
    assert value.startswith("pdfreviewintent_")
    assert len(value) == 48
    assert CURRENT_MIGRATION_REVISION == "20260922_0039"


def test_pdf_review_owner_index_is_part_of_authoritative_workflow_metadata() -> None:
    table = cast(Table, WorkflowInstanceRecord.__table__)
    indexes = _indexes_by_name(table)
    assert "ix_workflow_pdf_document_review_owner" in indexes
    predicate = indexes["ix_workflow_pdf_document_review_owner"].dialect_options["postgresql"][
        "where"
    ]
    assert str(predicate) == (
        "definition_key = 'pdf-document-review' AND created_actor_type = 'human'"
    )


@pytest.mark.integration
@pytest.mark.api_integration
def test_pdf_review_migration_matches_authoritative_models() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run through the guarded disposable PostgreSQL database")
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    try:
        inspector = inspect(engine)
        table = cast(Table, PdfDocumentReviewUploadIntentRecord.__table__)
        expected_columns = tuple(table.columns.keys())
        observed_columns = tuple(
            value["name"]
            for value in inspector.get_columns("pdf_document_review_upload_intents", schema="app")
        )
        assert observed_columns == expected_columns
        assert {
            value["name"]
            for value in inspector.get_indexes("pdf_document_review_upload_intents", schema="app")
        } == {
            "ix_pdf_review_upload_intent_lease",
            "ix_pdf_review_upload_intent_owner",
            "uq_pdf_review_upload_intent_workflow",
        }
        assert {
            (value["name"], tuple(value["column_names"]))
            for value in inspector.get_unique_constraints(
                "pdf_document_review_upload_intents", schema="app"
            )
        } == {("uq_pdf_review_upload_intent_workflow", ("workflow_id",))}
        assert {
            value["name"]
            for value in inspector.get_check_constraints(
                "pdf_document_review_upload_intents", schema="app"
            )
        } == {
            "ck_pdf_review_upload_intents_bounds",
            "ck_pdf_review_upload_intents_document",
            "ck_pdf_review_upload_intents_guidance",
            "ck_pdf_review_upload_intents_lease",
            "ck_pdf_review_upload_intents_payload",
            "ck_pdf_review_upload_intents_preset",
            "ck_pdf_review_upload_intents_state",
        }
        foreign_keys = {
            tuple(value["constrained_columns"]): (
                value["referred_table"],
                tuple(value["referred_columns"]),
            )
            for value in inspector.get_foreign_keys(
                "pdf_document_review_upload_intents", schema="app"
            )
        }
        assert foreign_keys == {
            ("operator_id",): ("operators", ("operator_id",)),
            ("workflow_id",): ("workflow_instances", ("workflow_id",)),
        }
        workflow_indexes = {
            value["name"] for value in inspector.get_indexes("workflow_instances", schema="app")
        }
        assert "ix_workflow_pdf_document_review_owner" in workflow_indexes
    finally:
        engine.dispose()
