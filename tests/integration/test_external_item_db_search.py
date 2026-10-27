"""Guarded PostgreSQL search over published source pointers; never production DB."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from eom_catalog_service.external_item_read_service import (
    ExternalItemListFilter,
    ExternalItemMetadataPredicate,
    export_external_item_sources,
    list_external_item_sources,
)
from eom_catalog_service.item_db_excel_export import ItemDbExportRow, render_item_database_xlsx
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.unit.test_external_item_import_contract import _manifest

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def source_session():
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh external-item-tests")
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == manifest.owner_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    try:
        with engine.connect() as connection, Session(bind=connection) as session:
            for table in (
                "external_item_sources",
                "external_item_source_revisions",
                "external_item_imports",
                "content_intake_source_files",
            ):
                connection.exec_driver_sql(
                    f"CREATE TEMP TABLE {table} AS SELECT * FROM app.{table} WITH NO DATA"
                )
            connection.exec_driver_sql("SET search_path TO pg_temp, app, public")
            example = _manifest()
            mapping = example["mapping"]
            observation = example["rows"][0]["observation"]
            session.execute(
                text(
                    "INSERT INTO external_item_imports"
                    "(import_id,state,source_namespace,workbook_artifact_id,"
                    "workbook_artifact_revision_id,workbook_sha256,mapping_revision_id,"
                    "mapping_sha256,mapping_document) "
                    "VALUES (:id,'COMPLETED',:namespace,:artifact,:revision,:workbook_sha,"
                    ":mapping_revision,:mapping_sha,CAST(:mapping AS jsonb))"
                ),
                {
                    "id": "extimport_" + "1" * 32,
                    "namespace": "notion-integrated-science",
                    "artifact": observation["workbook_artifact_id"],
                    "revision": observation["workbook_artifact_revision_id"],
                    "workbook_sha": observation["workbook_sha256"],
                    "mapping_revision": mapping["mapping_revision_id"],
                    "mapping_sha": mapping["mapping_sha256"],
                    "mapping": json.dumps(mapping),
                },
            )
            for index, (number, unit, field) in enumerate((
                ("00001", "물질의 상태", "화학"),
                ("00002", "운동", "물리"),
                ("00003", "물질", "화학"),
            ), start=2):
                suffix = f"{int(number):032x}"
                source_id = "extitem_" + suffix
                revision_id = "extitemrev_" + suffix
                observed = deepcopy(observation)
                cells = observed["cells"]
                cells[16]["raw_text"] = unit  # Q
                cells[20]["raw_text"] = number  # U
                cells[25]["raw_text"] = field  # Z
                for cell in (cells[16], cells[20], cells[25]):
                    cell["present"] = True
                    cell["cell_type"] = "s"
                observed["row_number"] = index
                observed["external_number"] = number
                observed["observation_sha256"] = content_sha256(
                    {key: value for key, value in observed.items() if key != "observation_sha256"}
                )
                session.execute(
                    text(
                        "INSERT INTO external_item_sources"
                        "(source_id,source_namespace,external_number,current_revision_id) "
                        "VALUES (:source,'notion-integrated-science',:number,:revision)"
                    ),
                    {"source": source_id, "number": number, "revision": revision_id},
                )
                session.execute(
                    text(
                        "INSERT INTO external_item_source_revisions"
                        "(revision_id,import_id,match_status,cells,unit_major,field_label,"
                        "worksheet_name,row_number,external_number,observation_sha256) "
                        "VALUES (:revision,:import,'MATCHED',CAST(:cells AS jsonb),:unit,:field,"
                        ":worksheet,:row_number,:number,:observation_sha)"
                    ),
                    {
                        "revision": revision_id,
                        "import": "extimport_" + "1" * 32,
                        "cells": json.dumps(cells),
                        "unit": unit,
                        "field": field,
                        "worksheet": observed["worksheet_name"],
                        "row_number": index,
                        "number": number,
                        "observation_sha": observed["observation_sha256"],
                    },
                )
            yield session
    finally:
        engine.dispose()


def test_all_any_exact_empty_and_keyset_use_real_postgres(source_session: Session) -> None:
    common = {"source_namespace": "notion-integrated-science", "limit": 1}
    all_query = ExternalItemListFilter(
        **common,
        match_mode="ALL",
        conditions=(
            ExternalItemMetadataPredicate("Q", "CONTAINS", "물"),
            ExternalItemMetadataPredicate("Z", "EQ", "화학"),
        ),
    )
    first = list_external_item_sources(source_session, all_query)
    assert tuple(value.external_number for value in first.entries) == ("00001",)
    assert first.next_after_number == "00001"
    second = list_external_item_sources(
        source_session,
        ExternalItemListFilter(
            **common,
            match_mode="ALL",
            after_number=first.next_after_number,
            conditions=all_query.conditions,
        ),
    )
    assert tuple(value.external_number for value in second.entries) == ("00003",)
    assert second.next_after_number is None

    any_query = ExternalItemListFilter(
        source_namespace="notion-integrated-science",
        match_mode="ANY",
        conditions=(
            ExternalItemMetadataPredicate("Q", "CONTAINS", "물"),
            ExternalItemMetadataPredicate("U", "EQ", "00002"),
        ),
    )
    assert tuple(
        value.external_number
        for value in list_external_item_sources(source_session, any_query).entries
    ) == ("00001", "00002", "00003")

    empty_query = ExternalItemListFilter(
        source_namespace="notion-integrated-science",
        conditions=(ExternalItemMetadataPredicate("F", "IS_EMPTY"),),
    )
    assert len(list_external_item_sources(source_session, empty_query).entries) == 3


def test_export_uses_same_real_postgres_filters_and_preserves_source_values(
    source_session: Session,
) -> None:
    query = ExternalItemListFilter(
        source_namespace="notion-integrated-science",
        conditions=(ExternalItemMetadataPredicate("Z", "EQ", "화학"),),
    )
    snapshot = export_external_item_sources(source_session, query)
    assert tuple(entry.external_number for entry in snapshot.entries) == ("00001", "00003")
    rows = tuple(
        ItemDbExportRow(
            source_kind="EXTERNAL_SOURCE",
            title=f"문항 {entry.external_number}",
            unit_label=entry.major_unit or "",
            source_label="기존 등록 문항",
            state_label=entry.match_status,
            filename=entry.selected_filename or "",
            external_number=entry.external_number,
            worksheet_name=entry.row.worksheet_name,
            source_row_number=entry.row.row_number,
            original_cells=entry.row.cells,
        )
        for entry in snapshot.entries
    )
    result = render_item_database_xlsx(rows, original_headers=snapshot.original_headers)
    assert result.row_count == 2
    assert result.payload.startswith(b"PK\x03\x04")
