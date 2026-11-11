"""Source-only DB reads stay bounded, current, and distinct from Item Registry."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from eom_catalog_service.external_item_read_service import (
    ExternalItemListFilter,
    ExternalItemMetadataPredicate,
    ExternalItemReadError,
    export_external_item_sources,
    list_external_item_sources,
    read_creative_registration_source,
    read_creative_registration_sources,
)
from sqlalchemy.dialects import postgresql

from tests.unit.test_external_item_import_contract import _manifest


def _registered_source_session():
    session = MagicMock()
    item = SimpleNamespace(
        item_revision_id="itemrev_" + "5" * 32,
        manifest_sha256="sha256:" + "a" * 64,
        revision_state="APPROVED",
        registration_key="creative-source:extitem_" + "1" * 32,
        metadata_json={"source_kind": "CREATIVE"},
    )
    value = (
        "extitem_" + "1" * 32,
        "extitemrev_" + "2" * 32,
        "00042",
        "sha256:" + "3" * 64,
        "원본 대단원",
        "원본 소단원",
        "물리",
        "고1",
        "출제자",
        "MATCHED",
        "문항_00042.hwp",
        "sourcefile_" + "4" * 32,
    )
    session.execute.return_value.all.side_effect = [
        [(item, "ACTIVE")],
        [(item.item_revision_id, *value)],
    ]
    return session, item, value


def _read_registered_source(session):
    return read_creative_registration_source(
        session,
        item_revision_id="itemrev_" + "5" * 32,
        manifest_sha256="sha256:" + "a" * 64,
        source_namespace="notion-integrated-science",
    )


def test_registered_source_reads_original_revision_without_graph_or_current_fallback():
    session, _, _ = _registered_source_session()
    result = _read_registered_source(session)
    assert (result.major_unit, result.minor_unit) == ("원본 대단원", "원본 소단원")
    assert session.execute.call_count == 2
    compiled = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "current_revision_id" not in sql and "knowledge_edges" not in sql
    assert "external_item_sources.source_id = external_item_source_revisions.source_id" in sql or (
        "external_item_source_revisions.source_id = external_item_sources.source_id" in sql
    )
    assert "external_item_imports.state" in sql
    assert "item_revisions.manifest_sha256" in sql
    assert {"source_revision_id", "source_id", "external_number", "import_id"}.issubset(
        {value for value in compiled.params.values() if isinstance(value, str)}
    )


@pytest.mark.parametrize("kind", ["AI", "EXTERNAL", None])
def test_noncreative_source_is_absent_not_an_inferred_unit(kind):
    session, item, _ = _registered_source_session()
    item.metadata_json = {"source_kind": kind}
    item.registration_key = "another-registration"
    assert _read_registered_source(session) is None
    assert session.execute.call_count == 1


@pytest.mark.parametrize(
    "failure", ["missing", "hash", "retired", "lifecycle", "metadata", "dangling"]
)
def test_registered_source_missing_stale_or_broken_pointers_fail_explicitly(failure):
    session, item, _ = _registered_source_session()
    if failure == "missing":
        session.execute.return_value.all.side_effect = [[]]
    elif failure == "hash":
        item.manifest_sha256 = "sha256:" + "b" * 64
    elif failure == "retired":
        item.revision_state = "RETIRED"
    elif failure == "lifecycle":
        session.execute.return_value.all.side_effect = [[(item, "RETIRED")]]
    elif failure == "metadata":
        item.metadata_json = {}
    elif failure == "dangling":
        session.execute.return_value.all.side_effect = [[(item, "ACTIVE")], []]
    with pytest.raises(ExternalItemReadError) as exc:
        _read_registered_source(session)
    assert exc.value.code == (
        "ITEM_DB_SOURCE_NOT_FOUND" if failure == "missing" else "ITEM_DB_SOURCE_STALE"
    )


def test_registered_sources_batch_is_two_queries_and_keeps_missing_origin_empty():
    session, item, value = _registered_source_session()
    second = SimpleNamespace(**{**vars(item), "item_revision_id": "itemrev_" + "6" * 32})
    ai = SimpleNamespace(
        **{
            **vars(item),
            "item_revision_id": "itemrev_" + "7" * 32,
            "metadata_json": {"source_kind": "AI"},
            "registration_key": "ai",
        }
    )
    session.execute.return_value.all.side_effect = [
        [(second, "ACTIVE"), (ai, "ACTIVE"), (item, "ACTIVE")],
        [(second.item_revision_id, *value), (item.item_revision_id, *value)],
    ]
    result = read_creative_registration_sources(
        session,
        item_manifests={
            entry.item_revision_id: entry.manifest_sha256 for entry in (item, second, ai)
        },
        source_namespace="notion-integrated-science",
    )
    assert session.execute.call_count == 2
    assert result[item.item_revision_id].minor_unit == "원본 소단원"
    assert result[second.item_revision_id].major_unit == "원본 대단원"
    assert result[ai.item_revision_id] is None
    sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "(item_revisions.item_revision_id, item_revisions.manifest_sha256) IN" in sql
    assert "current_revision_id" not in sql


def test_registered_sources_batch_rejects_duplicate_or_dangling_lineage():
    session, item, value = _registered_source_session()
    session.execute.return_value.all.side_effect = [
        [(item, "ACTIVE")],
        [(item.item_revision_id, *value), (item.item_revision_id, *value)],
    ]
    with pytest.raises(ExternalItemReadError, match="Pinned creative source unavailable"):
        _read_registered_source(session)


def test_registered_sources_batch_empty_and_limit_do_not_query():
    session = MagicMock()
    assert (
        read_creative_registration_sources(session, item_manifests={}, source_namespace="test")
        == {}
    )
    with pytest.raises(ExternalItemReadError, match="too many"):
        read_creative_registration_sources(
            session, item_manifests={str(n): "hash" for n in range(65)}, source_namespace="test"
        )
    session.execute.assert_not_called()


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


@pytest.mark.parametrize("state", ("APPROVED", "IN_REVIEW", "UNREGISTERED"))
def test_creative_approval_filter_is_correlated_before_pagination(state: str) -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    list_external_item_sources(
        session,
        ExternalItemListFilter(
            source_namespace="notion-integrated-science",
            approval_state=state,
            conditions=(ExternalItemMetadataPredicate("AD", "CONTAINS", "선생님"),),
        ),
    )
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "EXISTS" in sql
    assert "item_revisions.metadata_json" in sql
    assert "items.current_revision_id = item_revisions.item_revision_id" in sql
    assert "source_revision_id" in compiled.params.values()
    assert "CREATIVE" in compiled.params.values()
    assert ("NOT (EXISTS" in sql) == (state == "UNREGISTERED")
    assert sql.index("EXISTS") < sql.index("LIMIT")


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
