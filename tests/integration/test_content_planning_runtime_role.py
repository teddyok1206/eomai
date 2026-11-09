"""Execute editor/print/output use cases with a limited role in the disposable DB."""

import os
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from eom_catalog_service.content_planning_service import ContentPlanningService
from eom_catalog_service.runtime_privileges import (
    EXTRA_SEQUENCES,
    INSERT_TABLES,
    TABLE_PRIVILEGES,
    catalog_runtime_privileges_ready,
)
from eom_orchestrator.database import build_engine
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from scripts.api.testdb_guard import (
    TestDatabaseManifest as DisposableManifest,
)
from scripts.api.testdb_guard import (
    validate_state_directory,
)
from tests.integration.test_content_delivery_application import command as delivery_command
from tests.integration.test_content_planning_application import change, key, section, slots
from tests.integration.test_content_planning_application import planning as planning
from tests.integration.test_content_print_application import command, filled, history
from tests.integration.test_content_usage_read import query_for

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def catalog_role(creative_engine):
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    url = values["EOM_API_DATABASE_URL"]
    parsed = urlsplit(url)
    assert parsed.username == manifest.runtime_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    runtime = build_engine(url)
    added = []
    role = manifest.runtime_role
    try:
        with creative_engine.begin() as connection:
            for privilege, tables in TABLE_PRIVILEGES:
                for table in tables:
                    if not connection.scalar(
                        text("SELECT has_table_privilege(:r,:t,:p)"),
                        {"r": role, "t": f"app.{table}", "p": privilege},
                    ):
                        connection.exec_driver_sql(
                            f'GRANT {privilege} ON app."{table}" TO "{role}"'
                        )
                        added.append(("TABLE", table, privilege))
            sequences = set(EXTRA_SEQUENCES)
            for table in INSERT_TABLES:
                sequences.update(
                    connection.scalars(
                        text(
                            "SELECT c.relname FROM pg_class c JOIN pg_depend d ON d.objid=c.oid "
                            "WHERE c.relkind='S' AND d.deptype IN ('a','i') "
                            "AND d.refobjid=to_regclass(:t)"
                        ),
                        {"t": f"app.{table}"},
                    )
                )
            for name in sorted(sequences):
                if not connection.scalar(
                    text("SELECT has_sequence_privilege(:r,:t,'USAGE')"),
                    {"r": role, "t": f"app.{name}"},
                ):
                    connection.exec_driver_sql(f'GRANT USAGE ON SEQUENCE app."{name}" TO "{role}"')
                    added.append(("SEQUENCE", name, "USAGE"))
        yield runtime
    finally:
        runtime.dispose()
        with creative_engine.begin() as connection:
            for kind, name, privilege in reversed(added):
                connection.exec_driver_sql(
                    f'REVOKE {privilege} ON {kind} app."{name}" FROM "{role}"'
                )


def test_catalog_runtime_role_can_edit_print_and_prepare_shared_output(
    catalog_role, creative_engine, planning
):
    with catalog_role.connect() as connection:
        assert catalog_runtime_privileges_ready(connection)
    limited = replace(planning, service=ContentPlanningService(catalog_role))
    saved = filled(limited, creative_engine)
    assert len(section(limited, saved).placements) == 2
    record = limited.service.prints.execute(
        command(saved), actor=limited.editor, idempotency_key=key()
    )
    assert history(limited, saved).rows[0].record == record.record
    assert (
        limited.service.query(query_for(limited, saved), actor=limited.viewer).total_locations == 2
    )
    output = limited.service.deliveries.prepare(
        delivery_command(saved, sections=(saved.sections[0].section_id,)),
        actor=limited.editor,
        idempotency_key=key(),
    )
    assert output.assembly_revision_id
    limited.service.execute(
        change(saved, {0: slots(1)}), actor=limited.editor, idempotency_key=key()
    )
    for table in (
        "content_print_records",
        "content_edition_revision_forms",
        "curated_document_assembly_slots_v2",
    ):
        with catalog_role.connect() as connection, pytest.raises(ProgrammingError) as error:
            connection.exec_driver_sql(f'DELETE FROM app."{table}" WHERE false')
        assert error.value.orig.sqlstate == "42501"
