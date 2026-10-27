"""Exercise the real PostgreSQL foreign-key order in a disposable database."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from eom_catalog_contracts import ExternalItemImportManifest
from eom_catalog_service.external_item_import_service import _publish_rows
from eom_orchestrator.database import build_engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.unit.test_external_item_import_contract import _manifest

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_publication_persists_parent_revisions_before_edition_documents() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh external-item-tests")
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    disposable = DisposableManifest.load(state / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == disposable.owner_role
    assert unquote(parsed.path.removeprefix("/")) == disposable.database

    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                for table in (
                    "external_item_imports",
                    "external_item_sources",
                    "external_item_source_revisions",
                    "external_item_edition_documents",
                ):
                    connection.exec_driver_sql(
                        f"CREATE TEMP TABLE {table} "
                        f"(LIKE app.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS "
                        "INCLUDING INDEXES)"
                    )
                connection.exec_driver_sql(
                    "ALTER TABLE external_item_source_revisions ADD FOREIGN KEY (source_id) "
                    "REFERENCES external_item_sources(source_id)"
                )
                connection.exec_driver_sql(
                    "ALTER TABLE external_item_source_revisions ADD FOREIGN KEY (import_id) "
                    "REFERENCES external_item_imports(import_id)"
                )
                connection.exec_driver_sql(
                    "ALTER TABLE external_item_edition_documents ADD FOREIGN KEY "
                    "(source_revision_id) REFERENCES external_item_source_revisions(revision_id)"
                )
                connection.exec_driver_sql(
                    "ALTER TABLE external_item_sources ADD FOREIGN KEY (current_revision_id) "
                    "REFERENCES external_item_source_revisions(revision_id)"
                )
                connection.exec_driver_sql("SET search_path TO pg_temp, app, public")
                with Session(bind=connection) as session:
                    manifest = ExternalItemImportManifest.model_validate(_manifest())
                    _publish_rows(session, manifest)
                    session.flush()
                    assert (
                        session.execute(
                            text("SELECT count(*) FROM external_item_source_revisions")
                        ).scalar_one()
                        == 1
                    )
                    assert session.execute(
                        text("SELECT count(*) FROM external_item_edition_documents")
                    ).scalar_one() == len(manifest.rows[0].edition_links)
                    assert (
                        session.execute(
                            text("SELECT current_revision_id FROM external_item_sources")
                        ).scalar_one()
                        is not None
                    )
            finally:
                outer.rollback()
    finally:
        engine.dispose()
