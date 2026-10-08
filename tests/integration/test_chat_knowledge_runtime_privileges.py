"""Actual limited API role, never owner-created shadow table permissions."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from eom_api.runtime_privileges import runtime_table_privileges_ready
from eom_api.services.chat_knowledge_query_adapter import (
    candidate_statement,
    discovery_origin_statement,
    topic_source_statement,
)
from eom_api_contracts.chat_knowledge import ChatKnowledgeRequest, ChatTopicQuery
from eom_orchestrator.database import build_engine
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def role_engines():
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh chat-knowledge-tests; never production")
    state = validate_state_directory(Path(os.environ["EOM_CHAT_KNOWLEDGE_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    runtime_url = values["EOM_API_DATABASE_URL"]
    owner_url = os.environ["EOM_DATABASE_URL"]
    for url, expected_role in (
        (runtime_url, manifest.runtime_role),
        (owner_url, manifest.owner_role),
    ):
        parsed = urlsplit(url)
        assert parsed.username == expected_role
        assert unquote(parsed.path.removeprefix("/")) == manifest.database
    runtime, owner = build_engine(runtime_url), build_engine(owner_url)
    try:
        yield runtime, owner, manifest.runtime_role
    finally:
        runtime.dispose()
        owner.dispose()


def test_limited_api_role_executes_actual_discovery_queries(role_engines):
    runtime, _, _ = role_engines
    with runtime.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        assert runtime_table_privileges_ready(connection)
        connection.execute(discovery_origin_statement(())).all()
        connection.execute(
            candidate_statement(
                ChatKnowledgeRequest(query={"kind": "RECENT", "source": "GENERATED"}), None
            )
        ).all()
        connection.execute(
            topic_source_statement(
                ChatTopicQuery(kind="TOPIC", terms=("전류",)), "graphrev_" + "0" * 32
            )
        ).all()


@pytest.mark.parametrize(
    "statement",
    (
        "SELECT created_by FROM app.item_origin_profiles WHERE false",
        "SELECT rights_policy_sha256 FROM app.item_origin_profiles WHERE false",
        "SELECT * FROM app.item_origin_profiles WHERE false",
        "UPDATE app.item_origin_profiles SET source_domain=source_domain WHERE false",
        "DELETE FROM app.knowledge_node_terms WHERE false",
    ),
)
def test_limited_api_role_denies_unused_origin_metadata_and_writes(role_engines, statement):
    runtime, _, _ = role_engines
    with runtime.connect() as connection, pytest.raises(ProgrammingError) as error:
        connection.execute(text(statement))
    assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("drift", ("missing", "extra_column", "table_wide"))
def test_readiness_rejects_read_grant_drift_and_preserves_exact_profile(role_engines, drift):
    runtime, owner, role = role_engines
    column = "source_domain" if drift == "missing" else "created_by"
    grant = "REVOKE" if drift == "missing" else "GRANT"
    direction = "FROM" if drift == "missing" else "TO"
    target = "" if drift == "table_wide" else f"({column})"
    # Role/target names come from the guarded manifest and fixed enum above.
    with owner.begin() as connection:
        connection.exec_driver_sql(
            f'{grant} SELECT {target} ON app.item_origin_profiles {direction} "{role}"'
        )
    try:
        with runtime.connect() as connection:
            assert not runtime_table_privileges_ready(connection)
    finally:
        restore = "GRANT" if drift == "missing" else "REVOKE"
        restore_direction = "TO" if drift == "missing" else "FROM"
        with owner.begin() as connection:
            connection.exec_driver_sql(
                f"{restore} SELECT {target} ON app.item_origin_profiles "
                f'{restore_direction} "{role}"'
            )
            # Revoking table-wide SELECT can also affect column ACLs on some versions.
            connection.exec_driver_sql(
                "GRANT SELECT (item_id,item_revision_id,item_manifest_sha256,source_domain) "
                f'ON app.item_origin_profiles TO "{role}"'
            )
    with runtime.connect() as connection:
        assert runtime_table_privileges_ready(connection)
