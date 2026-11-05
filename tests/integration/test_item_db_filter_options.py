"""One bounded current-source projection in the existing marked disposable DB."""

from __future__ import annotations

import json
import time

import pytest
from eom_catalog_contracts.external_item_filter_options import CATEGORICAL_ITEM_METADATA_FIELDS
from eom_catalog_service.external_item_read_service import read_external_item_filter_options
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from tests.integration.test_external_item_db_search import source_session as source_session

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_choices_are_exact_current_namespace_values_in_one_query(source_session: Session):
    statements = []
    connection = source_session.connection()

    def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", observe)
    try:
        answer = read_external_item_filter_options(
            source_session, source_namespace="notion-integrated-science"
        )
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert len(statements) == 1
    assert tuple(entry.field for entry in answer.fields) == CATEGORICAL_ITEM_METADATA_FIELDS
    by_field = {entry.field: entry for entry in answer.fields}
    assert by_field["Q"].values == ("물질", "물질의 상태", "운동")
    assert by_field["Z"].values == ("물리", "화학")
    assert by_field["Y"].values == ("기출변형", "자유출제")
    assert "JOIN LATERAL" in statements[0] and "row_number() OVER" in statements[0]
    assert (
        read_external_item_filter_options(source_session, source_namespace="another-namespace")
        .fields[0]
        .values
        == ()
    )

    # History, incomplete import and another namespace are not dropdown values.
    source_session.execute(
        text("""
        INSERT INTO external_item_source_revisions(revision_id,source_id,import_id,cells)
        VALUES ('extitemrev_ffffffffffffffffffffffffffffffff',
          'extitem_00000000000000000000000000000001',
          'extimport_11111111111111111111111111111111', CAST(:cells AS jsonb))
    """),
        {"cells": json.dumps([{"column": "Q", "raw_text": "noncurrent-only"}])},
    )
    source_session.execute(
        text("""
        UPDATE external_item_sources SET source_namespace='another-namespace'
        WHERE external_number='00002'
    """)
    )
    source_session.execute(text("UPDATE external_item_imports SET state='RUNNING'"))
    hidden = read_external_item_filter_options(
        source_session, source_namespace="notion-integrated-science"
    )
    assert all(entry.values == () for entry in hidden.fields)


def test_choice_budget_is_bounded_without_copying_long_cell_bodies(source_session: Session):
    # The original fixture supplies the only completed import; rows are pg_temp.
    source_session.execute(
        text("""
        INSERT INTO external_item_sources
          (source_id,source_namespace,external_number,current_revision_id)
        SELECT 'extitem_'||md5(i::text), 'notion-integrated-science',
          lpad(i::text,5,'0'), 'extitemrev_'||md5(i::text)
        FROM generate_series(100, 700) i
    """)
    )
    source_session.execute(
        text("""
        INSERT INTO external_item_source_revisions
          (revision_id,source_id,import_id,cells)
        SELECT 'extitemrev_'||md5(i::text), 'extitem_'||md5(i::text),
          'extimport_11111111111111111111111111111111',
          jsonb_build_array(
            jsonb_build_object('column','Q','raw_text','option-'||lpad(i::text,5,'0')),
            jsonb_build_object('column','R','raw_text',repeat('!',256)),
            jsonb_build_object('column','Y','raw_text','A, B')
          )
        FROM generate_series(100, 700) i
    """)
    )
    started = time.monotonic()
    answer = read_external_item_filter_options(
        source_session, source_namespace="notion-integrated-science"
    )
    elapsed = time.monotonic() - started
    by_field = {entry.field: entry for entry in answer.fields}
    assert len(by_field["Q"].values) == 200 and by_field["Q"].truncated
    assert by_field["R"].values == () and by_field["R"].truncated
    assert "A, B" in by_field["Y"].values and "A" not in by_field["Y"].values
    assert len(answer.model_dump_json()) < 100_000
    assert elapsed < 10, f"bounded synthetic 604-source projection: {elapsed:.3f}s"
    print(f"filter_options_sources=604 sql_queries=1 elapsed_seconds={elapsed:.3f}")
