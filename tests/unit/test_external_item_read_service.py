"""Source-only DB reads stay bounded, current, and distinct from Item Registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from eom_catalog_service.external_item_read_service import (
    ExternalItemListFilter,
    ExternalItemMetadataPredicate,
    ExternalItemReadError,
    export_external_item_sources,
    list_external_item_sources,
)
from sqlalchemy.dialects import postgresql

from tests.unit.test_external_item_import_contract import _manifest


def test_source_list_uses_current_revision_completed_import_and_keyset() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        (
            "extitem_" + "1" * 32,
            "extitemrev_" + "2" * 32,
            "00042",
            "sha256:" + "3" * 64,
            "물질과 규칙성",
            "원소",
            "화학",
            "1",
            "출제자",
            "MATCHED",
            "문항_00042.hwp",
            "source_" + "4" * 32,
        ),
        (
            "extitem_" + "5" * 32,
            "extitemrev_" + "6" * 32,
            "00043",
            "sha256:" + "7" * 64,
            "물질과 규칙성",
            "원소",
            "화학",
            "1",
            "출제자",
            "DOCUMENT_MISSING",
            None,
            None,
        ),
    ]
    result = list_external_item_sources(
        session,
        ExternalItemListFilter(
            source_namespace="notion-integrated-science",
            limit=1,
            after_number="00041",
            major_unit="물질과 규칙성",
            match_status="MATCHED",
        ),
    )
    assert result.entries[0].selected_filename == "문항_00042.hwp"
    assert result.next_after_number == "00042"
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "external_item_sources.current_revision_id" in sql
    assert "external_item_imports.state" in sql
    assert "external_item_sources.external_number >" in sql
    assert "external_item_source_revisions.unit_major" in sql
    assert " LIMIT " in sql


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 101},
        {"limit": True},
        {"after_number": "../42"},
        {"exact_number": "42"},
        {"major_unit": ""},
        {"match_status": "UNKNOWN"},
        {"source_namespace": "../outside"},
    ],
)
def test_source_list_rejects_unbounded_or_invalid_filters(changes: dict[str, object]) -> None:
    with pytest.raises(ExternalItemReadError) as captured:
        ExternalItemListFilter(**{"source_namespace": "notion-integrated-science", **changes})
    assert captured.value.code == "EXTERNAL_ITEM_QUERY_INVALID"


def test_metadata_filters_are_parameterized_combined_and_bounded() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    result = list_external_item_sources(
        session,
        ExternalItemListFilter(
            source_namespace="notion-integrated-science",
            match_mode="ANY",
            conditions=(
                ExternalItemMetadataPredicate("Q", "CONTAINS", "물%_~"),
                ExternalItemMetadataPredicate("U", "EQ", "00042"),
            ),
        ),
    )
    assert result.entries == ()
    compiled = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert " OR " in sql
    assert "external_item_sources.external_number ILIKE" in sql
    assert "external_item_source_revisions.cells" in sql
    assert "%물~%~_~~%" in compiled.params.values()
    assert "물%_~" not in sql


@pytest.mark.parametrize(
    "predicate",
    [
        ("BAD_FIELD", "EQ", "x"),
        ("U", "IS_EMPTY", None),
        ("MATCH_STATUS", "CONTAINS", "MATCHED"),
        ("Q", "EQ", None),
        ("Q", "IS_EMPTY", "x"),
    ],
)
def test_metadata_filter_rejects_invalid_predicate(predicate: tuple[str, str, str | None]) -> None:
    with pytest.raises(ExternalItemReadError) as captured:
        ExternalItemMetadataPredicate(*predicate)
    assert captured.value.code == "EXTERNAL_ITEM_QUERY_INVALID"


def test_export_reads_exact_observation_and_mapping_with_same_filter_statement() -> None:
    manifest = _manifest()
    observation = manifest["rows"][0]["observation"]
    mapping = manifest["mapping"]
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        (
            "00042",
            "MATCHED_DETECTED_HWPX",
            "문항_00042.hwp",
            "물질",
            None,
            "화학",
            observation["worksheet_name"],
            observation["row_number"],
            observation["observation_sha256"],
            observation["cells"],
            observation["workbook_artifact_id"],
            observation["workbook_artifact_revision_id"],
            observation["workbook_sha256"],
            observation["mapping_revision_id"],
            observation["mapping_sha256"],
            mapping,
        )
    ]
    result = export_external_item_sources(
        session,
        ExternalItemListFilter(
            source_namespace="notion-integrated-science",
            conditions=(ExternalItemMetadataPredicate("U", "EQ", "00042"),),
        ),
    )
    assert result.entries[0].row.cells[20].raw_text == "00042"
    assert result.original_headers[20] == "원본 U"
    compiled = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "external_item_source_revisions.cells" in str(compiled)
    assert "external_item_sources.external_number ILIKE" in str(compiled)

    malformed = list(session.execute.return_value.all.return_value[0])
    malformed[8] = "sha256:" + "f" * 64
    session.execute.return_value.all.return_value = [tuple(malformed)]
    with pytest.raises(ExternalItemReadError) as captured:
        export_external_item_sources(
            session, ExternalItemListFilter(source_namespace="notion-integrated-science")
        )
    assert captured.value.code == "EXTERNAL_ITEM_EXPORT_ROW_INVALID"
