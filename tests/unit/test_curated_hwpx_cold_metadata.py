"""Request-only API imports must resolve the queue's cross-owner FK by themselves."""

import os
import subprocess
import sys

import pytest


def test_cold_queue_import_resolves_real_assembly_fk_without_fixture_imports():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from eom_hwpx_manager.curated_build_models import HwpxCuratedBuildRecord; "
            "from sqlalchemy.schema import CreateTable; "
            "from sqlalchemy.dialects.postgresql import dialect; "
            "table=HwpxCuratedBuildRecord.__table__; "
            "assert any(fk.column.table.name == 'curated_document_assembly_revisions' "
            "for fk in table.foreign_keys); "
            "ddl=str(CreateTable(table).compile(dialect=dialect())); "
            "assert 'fk_hwpx_curated_assembly_revision' in ddl; "
            "print('COLD_CURATED_METADATA=PASS')",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "COLD_CURATED_METADATA=PASS"


@pytest.mark.parametrize(
    "entrypoint",
    [
        "eom_api.app",
        "eom_catalog_service.application_runner",
        "eom_workflow_runner.composition",
        "eom_hwpx_manager.runner",
    ],
)
def test_public_entrypoint_resolves_its_own_fk_metadata_in_a_fresh_process(entrypoint):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib,sys; importlib.import_module(sys.argv[1]); "
            "from eom_orchestrator.models import Base; "
            "from sqlalchemy.schema import CreateTable; "
            "from sqlalchemy.dialects.postgresql import dialect; "
            "tables=tuple(Base.metadata.tables.values()); assert tables; "
            "assert all(fk.column.table is not None "
            "for table in tables for fk in table.foreign_keys); "
            "assert all(str(CreateTable(table).compile(dialect=dialect())) for table in tables); "
            "print('COLD_PUBLIC_METADATA=PASS')",
            entrypoint,
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "COLD_PUBLIC_METADATA=PASS"
