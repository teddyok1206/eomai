"""Execute editor/print/output use cases with a limited role in the disposable DB."""

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import unquote, urlsplit

import pytest
from eom_catalog_service.content_planning_service import ContentPlanningService
from eom_catalog_service.curated_document_assembly_service import CuratedDocumentAssemblyService
from eom_catalog_service.runtime_privileges import (
    EXTRA_SEQUENCES,
    INSERT_TABLES,
    TABLE_PRIVILEGES,
    catalog_runtime_privileges_ready,
)
from eom_hwpx_contracts.curated_occurrences import CuratedHwpxBuildInputV2
from eom_hwpx_manager.curated_application_service import (
    CuratedBuildPending,
    CuratedHwpxApplicationService,
    CuratedRecoveryState,
)
from eom_hwpx_manager.curated_build_models import HwpxCuratedBuildRecord
from eom_hwpx_manager.runtime_privileges import TABLE_PRIVILEGES as MANAGER_TABLE_PRIVILEGES
from eom_hwpx_manager.runtime_privileges import manager_runtime_privileges_ready
from eom_orchestrator.database import build_engine
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import (
    TestDatabaseManifest as DisposableManifest,
)
from scripts.api.testdb_guard import (
    validate_state_directory,
)
from tests.integration.test_content_delivery_application import command as delivery_command
from tests.integration.test_content_delivery_application import filled as delivery_filled
from tests.integration.test_content_delivery_application import manifest as delivery_manifest
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


@pytest.fixture
def manager_role(creative_engine):
    """Temporarily use the exact Manager table matrix, not permissive API grants.

    Only the manifest-bound disposable role is changed. Every changed privilege
    is restored in teardown; no other role, row, sequence or production DB is touched.
    """
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    url = values["EOM_API_DATABASE_URL"]
    parsed = urlsplit(url)
    assert parsed.username == manifest.runtime_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    runtime, role = build_engine(url), manifest.runtime_role
    wanted = {
        (table, privilege) for privilege, tables in MANAGER_TABLE_PRIVILEGES for table in tables
    }
    changes = []
    try:
        with creative_engine.begin() as connection:
            prior = connection.execute(
                text(
                    "SELECT c.relname, p.privilege, has_table_privilege(:role,c.oid,p.privilege) "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE',"
                    "'REFERENCES','TRIGGER']) AS p(privilege) "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','p')"
                ),
                {"role": role},
            ).all()
            for table, privilege, existed in prior:
                expected = (table, privilege) in wanted
                if bool(existed) != expected:
                    action, preposition = ("GRANT", "TO") if expected else ("REVOKE", "FROM")
                    connection.exec_driver_sql(
                        f'{action} {privilege} ON app."{table}" {preposition} "{role}"'
                    )
                    changes.append((table, privilege, bool(existed)))
        with runtime.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == role
            for table, privilege, _existed in prior:
                assert bool(
                    connection.scalar(
                        text("SELECT has_table_privilege(current_user,:t,:p)"),
                        {"t": f"app.{table}", "p": privilege},
                    )
                ) == ((table, privilege) in wanted)
        yield runtime, role
    finally:
        runtime.dispose()
        with creative_engine.begin() as connection:
            for table, privilege, existed in reversed(changes):
                action, preposition = ("GRANT", "TO") if existed else ("REVOKE", "FROM")
                connection.exec_driver_sql(
                    f'{action} {privilege} ON app."{table}" {preposition} "{role}"'
                )


def test_manager_role_reauthorizes_excel_scope_before_render_and_recovery(
    creative_engine, planning, manager_role
):
    runtime, role = manager_role
    saved = delivery_filled(planning, creative_engine)
    prepared = planning.service.deliveries.prepare(
        delivery_command(saved), actor=planning.editor, idempotency_key=key()
    )
    pinned = delivery_manifest(creative_engine, prepared, planning.editor)
    assemblies = CuratedDocumentAssemblyService(runtime, media=Mock())
    # Reproduce the formerly missing SELECT and require readiness to reject it.
    with creative_engine.begin() as connection:
        connection.exec_driver_sql(f'REVOKE SELECT ON app.content_delivery_scopes FROM "{role}"')
    try:
        with runtime.connect() as connection:
            assert not manager_runtime_privileges_ready(connection)
        with pytest.raises(ProgrammingError) as error:
            delivery_manifest(runtime, prepared, planning.editor)
        assert error.value.orig.sqlstate == "42501"
    finally:
        with creative_engine.begin() as connection:
            connection.exec_driver_sql(f'GRANT SELECT ON app.content_delivery_scopes TO "{role}"')
    with runtime.connect() as connection:
        assert manager_runtime_privileges_ready(connection)
    assert delivery_manifest(runtime, prepared, planning.peer) == pinned
    renderer = Mock()
    renderer.pin_inputs.return_value = CuratedHwpxBuildInputV2(
        assembly_id=pinned.assembly_id,
        assembly_revision_id=pinned.assembly_revision_id,
        assembly_manifest_sha256=pinned.manifest_sha256,
        handoff=None,
        converter=None,
        placements=tuple(
            dict(
                kind="NATIVE_DOCUMENT",
                position=slot.position,
                placement_id=slot.placement_id,
                source_format=slot.target.source_format,
                document=slot.target.document_artifact.model_dump(),
                size_bytes=slot.target.document_size_bytes,
            )
            for slot in pinned.placements
        ),
    )
    renderer.finish.side_effect = CuratedBuildPending("synthetic renderer pending; no dispatch")
    renderer.build_may_be_active.return_value = False
    admission = CuratedHwpxApplicationService(
        creative_engine,
        assemblies=CuratedDocumentAssemblyService(creative_engine, media=Mock()),
        input_pins=renderer,
    )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(HwpxCuratedBuildRecord.build_id)
                .where(HwpxCuratedBuildRecord.state.in_(("REQUESTED", "RUNNING", "VALIDATING")))
                .limit(1)
            )
            is None
        )
    record, created = admission.request_build(
        pinned.assembly_id,
        assembly_revision_id=pinned.assembly_revision_id,
        manifest_sha256=pinned.manifest_sha256,
        actor=planning.editor,
        idempotency_key=key(),
    )
    assert created
    try:
        manager = CuratedHwpxApplicationService(runtime, assemblies=assemblies, renderer=renderer)
        started = manager.process_next()
        assert started is not None and started.build_id == record.build_id
        assert started.state == "RUNNING"
        renderer.finish.assert_called_once()
        recovered = manager.recover_interrupted()
        assert recovered.state is CuratedRecoveryState.ACTIVE
        assert recovered.record is not None and recovered.record.build_id == record.build_id
        assert renderer.finish.call_count == 2
        renderer.secure_download.assert_not_called()
    finally:
        # Remove only this fixture's never-dispatched queue row, not real history.
        with Session(creative_engine) as session, session.begin():
            own = session.get(HwpxCuratedBuildRecord, record.build_id)
            assert own is not None and own.platform_job_id is None
            assert own.output_artifact_id is None and own.output_artifact_revision_id is None
            session.delete(own)
