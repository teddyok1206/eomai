"""Real guarded PostgreSQL DDL/replay; privileged staging/IAM are synthetic, no production."""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from scripts.api import release_operator_runtime as operator
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def release_case(guarded_engine, tmp_path, monkeypatch):
    from eom_api import build_info
    from eom_orchestrator import database, settings

    # Only this marker-checked disposable owner URL reaches native Alembic,
    # including after the operator deliberately clears the caller's DB env.
    url = guarded_engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("EOM_DATABASE_URL", url)
    monkeypatch.setattr(settings, "database_url", lambda: url)
    monkeypatch.setattr(database, "build_engine", lambda: guarded_engine)
    monkeypatch.setattr(operator, "require_root", lambda: None)
    monkeypatch.setattr(operator, "check_postgres_environment", lambda: None)
    source = tmp_path / "source"
    source.mkdir()
    shutil.copyfile(ROOT / "alembic.ini", source / "alembic.ini")
    shutil.copytree(
        ROOT / "migrations", source / "migrations", ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.syspath_prepend(str(tmp_path / "site-packages"))
    context = operator.OperatorContext(
        "a" * 40,
        "b" * 40,
        "sha256:" + "c" * 64,
        "sha256:" + "d" * 64,
        tmp_path / "synthetic-runtime",
        "sha256:" + "e" * 64,
        tuple(operator.WheelPin("synthetic.whl", "sha256:" + "f" * 64) for _ in range(3)),
        schema_version="release-operator-context/1.14",
        migration_revision="20261031_0066",
    )
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    config = Config(str(source / "alembic.ini"))
    config.set_main_option("script_location", str(source / "migrations"))
    config.set_main_option("prepend_sys_path", "")
    yield tmp_path, context, config, guarded_engine
    # Each case leaves the empty disposable schema compatible for subsequent
    # fixtures. No successor history exists in these DDL-only cases.
    command.upgrade(config, "20261031_0066")


def head(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM app.alembic_version"))


def test_exact64_to66_ddl_and_replay_preserve_original_fence(release_case, monkeypatch):
    stage, context, config, engine = release_case
    command.downgrade(config, "20261030_0064")
    real_upgrade = command.upgrade
    calls = []

    def upgrade(configuration, revision):
        calls.append(revision)
        return real_upgrade(configuration, revision)

    monkeypatch.setattr(command, "upgrade", upgrade)
    operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064)
    operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064)
    operator.run_callback(stage, context, operator.Callback.MIGRATION_VERIFY_0066)
    assert head(engine) == "20261031_0066" and calls == ["20261031_0066"]
    with engine.connect() as connection:
        indexes = dict(
            connection.execute(
                text(
                    "SELECT indexname,indexdef FROM pg_indexes "
                    "WHERE schemaname='app' AND indexname IN "
                    "('uq_knowledge_analysis_accepted_solution_predecessor',"
                    "'uq_knowledge_analysis_registered_solution_predecessor')"
                )
            ).all()
        )
        assert len(indexes) == 2
        assert (
            "knowledge-analysis-request/10.0"
            in indexes["uq_knowledge_analysis_accepted_solution_predecessor"]
        )
        assert (
            "knowledge-analysis-request/11.0"
            in indexes["uq_knowledge_analysis_registered_solution_predecessor"]
        )
        predicate = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='app.embedding_index_revisions'::regclass "
                "AND conname='ck_embedding_index_revision_member'"
            )
        )
        assert "embedding-index-manifest/4.0" in predicate


def test_post_commit_response_loss_replays_without_second_ddl(release_case, monkeypatch):
    stage, context, config, engine = release_case
    command.downgrade(config, "20261030_0064")
    real_upgrade = command.upgrade
    calls = []

    def lost_response(configuration, revision):
        calls.append(revision)
        real_upgrade(configuration, revision)
        raise OSError("synthetic response loss after actual DDL commit")

    monkeypatch.setattr(command, "upgrade", lost_response)
    with pytest.raises(OSError, match="response loss"):
        operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064)
    assert head(engine) == "20261031_0066"
    operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064)
    assert calls == ["20261031_0066"]
    monkeypatch.setattr(command, "upgrade", real_upgrade)


def test_wrong_predecessor_and_old_context_do_not_change_actual_head(release_case):
    stage, context, config, engine = release_case
    command.downgrade(config, "20261031_0065")
    with pytest.raises(operator.OperatorRuntimeError, match="HEAD_MISMATCH"):
        operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064)
    assert head(engine) == "20261031_0065"
    operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0066)
    assert head(engine) == "20261031_0066"
    old = replace(
        context, schema_version="release-operator-context/1.13", migration_revision="20261030_0064"
    )
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(stage, old, operator.Callback.MIGRATION_VERIFY_0066)
    assert head(engine) == "20261031_0066"
