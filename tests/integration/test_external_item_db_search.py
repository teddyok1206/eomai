"""Guarded PostgreSQL search over published source pointers; never production DB."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from eom_catalog_service.external_creative_learning_targets import (
    ExternalCreativeLearningTargetError,
    get_external_creative_learning_target,
    list_external_creative_learning_targets,
)
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
                "items",
                "item_revisions",
                "workflow_instances",
                "external_item_sources",
                "external_item_source_revisions",
                "external_item_edition_documents",
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
            for index, (number, unit, field, kind) in enumerate(
                (
                    ("00001", "물질의 상태", "화학", "기출변형"),
                    ("00002", "운동", "물리", "자유출제"),
                    ("00003", "물질", "화학", "기출변형"),
                ),
                start=2,
            ):
                suffix = f"{int(number):032x}"
                source_id = "extitem_" + suffix
                revision_id = "extitemrev_" + suffix
                source_file_id = "sourcefile_" + suffix
                document_sha256 = "sha256:" + "8" * 64
                observed = deepcopy(observation)
                cells = observed["cells"]
                cells[16]["raw_text"] = unit  # Q
                cells[20]["raw_text"] = number  # U
                cells[23]["raw_text"] = "" if number == "00002" else "No"  # X
                cells[24]["raw_text"] = kind  # Y
                cells[25]["raw_text"] = field  # Z
                edition = 2 if number == "00002" else 3
                if edition == 2:
                    cells[13]["raw_text"] = ""
                    cells[13]["present"] = False
                    cells[13]["cell_type"] = None
                cells[12 if edition == 2 else 13]["raw_text"] = f"문항_{number}.hwp"
                if number == "00001":
                    cells[22]["raw_text"] = "0"  # W is not the creative classifier.
                    cells[22]["present"] = True
                    cells[22]["cell_type"] = "s"
                for cell in (
                    cells[16],
                    cells[20],
                    cells[23],
                    cells[24],
                    cells[25],
                    cells[12 if edition == 2 else 13],
                ):
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
                        "INSERT INTO content_intake_source_files"
                        "(source_file_id,original_filename,normalized_filename,relative_path,"
                        "media_type,size_bytes,sha256,artifact_id,artifact_revision_id) "
                        "VALUES (:id,:filename,:filename,:path,:media,100,:sha,:artifact,:revision)"
                    ),
                    {
                        "id": source_file_id,
                        "filename": f"문항_{number}.hwp",
                        "path": f"source/{number}.hwp",
                        "media": "application/vnd.hancom.hwp",
                        "sha": document_sha256,
                        "artifact": "artifact_" + suffix,
                        "revision": "rev_" + suffix,
                    },
                )
                session.execute(
                    text(
                        "INSERT INTO external_item_source_revisions"
                        "(revision_id,source_id,import_id,match_status,selected_source_file_id,"
                        "cells,unit_major,field_label,"
                        "worksheet_name,row_number,external_number,observation_sha256) "
                        "VALUES (:revision,:source,:import,'MATCHED',:source_file,"
                        "CAST(:cells AS jsonb),:unit,:field,"
                        ":worksheet,:row_number,:number,:observation_sha)"
                    ),
                    {
                        "revision": revision_id,
                        "source": source_id,
                        "import": "extimport_" + "1" * 32,
                        "source_file": source_file_id,
                        "cells": json.dumps(cells),
                        "unit": unit,
                        "field": field,
                        "worksheet": observed["worksheet_name"],
                        "row_number": index,
                        "number": number,
                        "observation_sha": observed["observation_sha256"],
                    },
                )
                session.execute(
                    text(
                        "INSERT INTO external_item_edition_documents"
                        "(edition_document_id,source_revision_id,edition,match_status,"
                        "source_file_id,document_sha256) "
                        "VALUES (:id,:revision,:edition,'MATCHED',:source_file,:sha)"
                    ),
                    {
                        "id": "extitemdoc_" + suffix,
                        "revision": revision_id,
                        "edition": edition,
                        "source_file": source_file_id,
                        "sha": document_sha256,
                    },
                )
            yield session
    finally:
        engine.dispose()


def test_registered_creative_status_keeps_metadata_filters_and_pinned_sources(
    source_session: Session,
) -> None:
    from eom_catalog_service.external_item_read_service import creative_item_registrations

    for number, state in (("00001", "APPROVED"), ("00002", "IN_REVIEW")):
        suffix = f"{int(number):032x}"
        source_session.execute(
            text(
                "INSERT INTO items(item_id,current_revision_id,lifecycle_state) "
                "VALUES (:item,:revision,'ACTIVE')"
            ),
            {"item": "item_" + suffix, "revision": "itemrev_" + suffix},
        )
        source_session.execute(
            text(
                "INSERT INTO item_revisions(item_id,item_revision_id,revision_state,"
                "metadata_json,registration_key) "
                "VALUES (:item,:revision,:state,CAST(:metadata AS jsonb),:registration)"
            ),
            {
                "item": "item_" + suffix,
                "revision": "itemrev_" + suffix,
                "state": state,
                "registration": "creative-source:extitem_" + suffix,
                "metadata": json.dumps(
                    {
                        "source_kind": "CREATIVE",
                        "source_id": "extitem_" + suffix,
                        "source_revision_id": "extitemrev_" + suffix,
                        "external_number": number,
                    }
                ),
            },
        )
    for state, expected in (
        ("APPROVED", "00001"),
        ("IN_REVIEW", "00002"),
        ("UNREGISTERED", "00003"),
    ):
        result = list_external_item_sources(
            source_session,
            ExternalItemListFilter(
                source_namespace="notion-integrated-science", approval_state=state, limit=1
            ),
        )
        assert [row.external_number for row in result.entries] == [expected]
        assert result.next_after_number is None
        registrations = creative_item_registrations(source_session, result.entries)
        assert bool(registrations) == (state != "UNREGISTERED")
    result = list_external_item_sources(
        source_session,
        ExternalItemListFilter(
            source_namespace="notion-integrated-science",
            approval_state="APPROVED",
            conditions=(ExternalItemMetadataPredicate("Z", "CONTAINS", "物理"),),
        ),
    )
    assert result.entries == ()
    # An obsolete source pin must never inherit the current source's approval.
    source_session.execute(
        text(
            "UPDATE item_revisions SET metadata_json=jsonb_set(metadata_json, "
            "'{source_revision_id}', to_jsonb(CAST(:stale AS text)))"
        ),
        {"stale": "extitemrev_" + "f" * 32},
    )
    result = list_external_item_sources(
        source_session,
        ExternalItemListFilter(
            source_namespace="notion-integrated-science", approval_state="APPROVED"
        ),
    )
    assert result.entries == ()


def test_ai_category_uses_authoring_provenance_and_status_scoped_keyset(
    source_session: Session,
) -> None:
    from contextlib import nullcontext

    from eom_api.services.pagination import CursorCodec
    from eom_api.services.query_adapter import QueryAdapter

    for index, (definition, state) in enumerate(
        (
            ("generic-item-development", "IN_REVIEW"),
            ("generic-item-development", "APPROVED"),
            ("external-item-learning", "APPROVED"),
        ),
        start=10,
    ):
        suffix = f"{index:032x}"
        source_session.execute(
            text(
                "INSERT INTO workflow_instances(workflow_id,definition_key) "
                "VALUES (:workflow,:definition)"
            ),
            {"workflow": "workflow_" + suffix, "definition": definition},
        )
        source_session.execute(
            text(
                "INSERT INTO items(item_id,current_revision_id,lifecycle_state) "
                "VALUES (:item,:revision,'ACTIVE')"
            ),
            {"item": "item_" + suffix, "revision": "itemrev_" + suffix},
        )
        source_session.execute(
            text(
                "INSERT INTO item_revisions(item_id,item_revision_id,workflow_id,"
                "revision_state,manifest_sha256,item_type_key,created_at) "
                "VALUES (:item,:revision,:workflow,:state,:hash,'multiple-choice',now())"
            ),
            {
                "item": "item_" + suffix,
                "revision": "itemrev_" + suffix,
                "workflow": "workflow_" + suffix,
                "state": state,
                "hash": "sha256:" + "a" * 64,
            },
        )
    query = object.__new__(QueryAdapter)
    query.sessions = lambda: nullcontext(source_session)
    query.cursors = CursorCodec(b"test-only-db-category-cursor")
    first = query.ai_item_db_entries(approval_state=None, limit=1, cursor=None)
    second = query.ai_item_db_entries(approval_state=None, limit=1, cursor=first.next_cursor)
    assert first.has_more and not second.has_more
    assert {row.registration.approval_state for row in (*first.data, *second.data)} == {
        "IN_REVIEW",
        "APPROVED",
    }
    approved = query.ai_item_db_entries(approval_state="APPROVED", limit=50, cursor=None)
    assert len(approved.data) == 1
    assert approved.data[0].registration.item_revision_id == "itemrev_" + f"{11:032x}"
    from eom_api.errors import ApiError

    with pytest.raises(ApiError):
        query.ai_item_db_entries(approval_state="APPROVED", limit=1, cursor=first.next_cursor)


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


def test_creative_learning_targets_are_exact_keyset_pages(source_session: Session) -> None:
    import_id = "extimport_" + "1" * 32
    first = list_external_creative_learning_targets(source_session, import_id=import_id, limit=2)
    assert tuple(value.external_number for value in first.entries) == ("00001", "00002")
    assert tuple(value.origin_kind for value in first.entries) == (
        "PAST_EXAM_VARIATION",
        "FREE_AUTHORING",
    )
    assert first.entries[0].document_sha256 == "sha256:" + "8" * 64
    assert first.entries[1].selected_edition == 2
    assert first.next_after_number == "00002"
    second = list_external_creative_learning_targets(
        source_session, import_id=import_id, after_number=first.next_after_number, limit=2
    )
    assert tuple(value.external_number for value in second.entries) == ("00003",)
    assert second.next_after_number is None


def test_creative_learning_target_exact_u_lookup_uses_keyset_boundary(
    source_session: Session,
) -> None:
    import_id = "extimport_" + "1" * 32
    first = get_external_creative_learning_target(
        source_session, import_id=import_id, external_number="00001"
    )
    third = get_external_creative_learning_target(
        source_session, import_id=import_id, external_number="00003"
    )
    assert first.external_number == "00001"
    assert first.source_namespace == "notion-integrated-science"
    assert third.external_number == "00003"
    with pytest.raises(ExternalCreativeLearningTargetError) as missing:
        get_external_creative_learning_target(
            source_session, import_id=import_id, external_number="00004"
        )
    assert missing.value.code == "EXTERNAL_CREATIVE_TARGET_NOT_FOUND"


def test_creative_learning_target_rejects_tampered_observation(source_session: Session) -> None:
    source_session.execute(
        text(
            "UPDATE external_item_source_revisions SET observation_sha256=:changed "
            "WHERE external_number='00001'"
        ),
        {"changed": "sha256:" + "0" * 64},
    )
    with pytest.raises(ExternalCreativeLearningTargetError) as captured:
        list_external_creative_learning_targets(source_session, import_id="extimport_" + "1" * 32)
    assert captured.value.code == "EXTERNAL_CREATIVE_SOURCE_OBSERVATION_INVALID"


def test_creative_learning_target_excludes_stale_and_rejects_document_drift(
    source_session: Session,
) -> None:
    source_session.execute(
        text(
            "UPDATE external_item_sources SET current_revision_id=NULL "
            "WHERE external_number='00001'"
        )
    )
    page = list_external_creative_learning_targets(
        source_session, import_id="extimport_" + "1" * 32
    )
    assert tuple(value.external_number for value in page.entries) == ("00002", "00003")
    source_session.execute(
        text(
            "UPDATE external_item_edition_documents SET document_sha256=:changed "
            "WHERE source_revision_id=:revision"
        ),
        {
            "changed": "sha256:" + "0" * 64,
            "revision": "extitemrev_" + f"{2:032x}",
        },
    )
    with pytest.raises(ExternalCreativeLearningTargetError) as captured:
        list_external_creative_learning_targets(source_session, import_id="extimport_" + "1" * 32)
    assert captured.value.code == "EXTERNAL_CREATIVE_DOCUMENT_POINTER_INVALID"
