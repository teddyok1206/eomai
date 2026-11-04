"""Request-only API imports must resolve the queue's cross-owner FK by themselves."""

import os
import subprocess
import sys


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
