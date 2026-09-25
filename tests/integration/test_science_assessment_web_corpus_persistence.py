from __future__ import annotations

import os

import pytest
from eom_orchestrator.database import build_engine
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION

pytestmark = pytest.mark.skipif(
    os.environ.get("EOM_RUN_INTEGRATION") != "1",
    reason="run through a guarded disposable PostgreSQL database",
)


def test_content_intake_hash_lookup_uses_the_dedicated_index() -> None:
    engine = build_engine()
    try:
        with engine.begin() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT version_num FROM app.alembic_version"
                ).scalar_one()
                == CURRENT_MIGRATION_REVISION
            )
            index = connection.exec_driver_sql(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'app' AND tablename = 'content_intake_source_files' "
                "AND indexname = 'ix_content_intake_source_sha256'"
            ).scalar_one()
            assert "USING btree (sha256)" in index
            connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
            plan = "\n".join(
                connection.exec_driver_sql(
                    "EXPLAIN (COSTS OFF) SELECT source_file_id "
                    "FROM app.content_intake_source_files WHERE sha256 = "
                    "'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"
                ).scalars()
            )
            assert "ix_content_intake_source_sha256" in plan
            binary_columns = connection.exec_driver_sql(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'app' AND table_name = 'content_intake_source_files' "
                "AND data_type = 'bytea'"
            ).all()
            assert binary_columns == []
    finally:
        engine.dispose()
