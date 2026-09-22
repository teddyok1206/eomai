from __future__ import annotations

from eom_api.pdf_document_review_models import PdfDocumentReviewUploadIntentRecord
from eom_identifiers import new_pdf_review_upload_intent_id
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy import LargeBinary


def test_pdf_review_upload_intent_uses_small_metadata_and_indexed_access() -> None:
    table = PdfDocumentReviewUploadIntentRecord.__table__
    assert table.name == "pdf_document_review_upload_intents"
    assert tuple(column.name for column in table.primary_key.columns) == ("upload_intent_id",)
    assert not any(isinstance(column.type, LargeBinary) for column in table.columns)
    assert "pdf" not in {column.name for column in table.columns}
    assert "content" not in {column.name for column in table.columns}

    indexes = {index.name: index for index in table.indexes}
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
