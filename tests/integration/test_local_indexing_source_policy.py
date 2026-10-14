"""Real guarded PostgreSQL policy reads under its owner, NOT live service authority.

Synthetic1.0/1.1 rows exist only in rolled-back roots. No role/service is granted,
no original source is read and no model/worker/Artifact operation occurs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from eom_catalog_contracts.knowledge import EducationRetrievalAccessPolicy
from eom_catalog_contracts.local_indexing_policy import LocalIndexingAccessPolicy
from eom_catalog_service.knowledge_graph_models import EducationRetrievalAccessPolicyRevisionRecord
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_local_indexing_policy_contracts import policy_document

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def exact_opt_in() -> None:
    if os.environ.get("EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION") != "1":
        pytest.skip("use guarded local-indexing-service-tests; never production")


def policies():
    source_id, grant_id = ("accessrev_" + uuid4().hex for _ in range(2))
    base: dict[str, Any] = dict(
        schema_version="education-retrieval-access-policy/1.0",
        access_policy_revision_id=source_id,
        state="RELEASED",
        allowed_query_kinds=["ITEM_PREPARATION"],
        allowed_requester_roles=["EDITOR"],
        allowed_source_classes=["PAST_EXAM"],
        answer_bearing_roles=["EDITOR"],
        maximum_budget=dict(
            max_documents=1,
            max_item_revisions=1,
            max_graph_nodes=32,
            max_claims=8,
            max_context_tokens=1000,
        ),
        created_at="2026-10-14T00:00:00Z",
    )
    base["content_sha256"] = content_sha256(base)
    source = EducationRetrievalAccessPolicy.model_validate(base)
    grant = LocalIndexingAccessPolicy.model_validate(
        policy_document(
            access_policy_revision_id=grant_id,
            source_access_policy_revision_id=source_id,
            source_access_policy_sha256=source.content_sha256,
        )
    )
    return source, grant


def records(source, grant, owner):
    return [
        EducationRetrievalAccessPolicyRevisionRecord(
            access_policy_revision_id=policy.access_policy_revision_id,
            schema_version=policy.schema_version,
            state="RELEASED",
            content_sha256=policy.content_sha256,
            canonical_document=policy.model_dump(mode="json"),
            created_by=owner,
            created_at=policy.created_at,
        )
        for policy in (source, grant)
    ]


@pytest.fixture
def stored(guarded_engine: Engine, request: pytest.FixtureRequest):
    source, grant = policies()
    rows = records(source, grant, guarded_engine.url.username)
    fault = getattr(request, "param", "")
    if fault == "row_hash":
        rows[1].content_sha256 = "sha256:" + "f" * 64
    elif fault == "schema":
        rows[1].schema_version = "education-retrieval-access-policy/1.0"
    elif fault == "semantic_hash":
        rows[1].canonical_document["maximum_sources"] = 1
    elif fault == "extra":
        rows[1].canonical_document["roles"] = ["ADMIN"]
    with Session(guarded_engine) as session:
        root = session.begin()
        try:
            session.add_all(rows)
            session.flush()
            yield session, source, grant
        finally:
            if root.is_active:
                root.rollback()


@pytest.fixture
def limited_policies(guarded_engine: Engine):
    """Real disposable SELECT-only login, not an authenticated indexing service.

    No cluster role/grant change or production credential is used. Only these two
    synthetic rows are committed for the separate login. Append-only triggers
    preserve them until guarded disposable-database cleanup, like other accepted
    control histories; teardown must not delete or disable the trigger.
    """
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    url = make_url(values["EOM_API_DATABASE_URL"])
    assert url.username == manifest.runtime_role and url.database == manifest.database
    assert url.drivername == "postgresql+psycopg" and url.host == "127.0.0.1"
    source, grant = policies()
    runtime = build_engine(
        url.set(query={"options": "-csearch_path=app,pg_catalog"}).render_as_string(
            hide_password=False
        )
    )
    try:
        with Session(guarded_engine) as session, session.begin():
            session.add_all(records(source, grant, manifest.owner_role))
        yield runtime, source, grant
    finally:
        runtime.dispose()


def test_actual_select_only_login_resolves_both_policy_families_without_update(limited_policies):
    runtime, source, grant = limited_policies
    service = object.__new__(KnowledgeRetrievalApplicationService)
    with Session(runtime) as session, session.begin():
        assert (
            session.scalar(
                text(
                    "SELECT has_table_privilege(SESSION_USER,"
                    "'app.education_retrieval_access_policy_revisions','UPDATE')"
                )
            )
            is False
        )
        assert (
            service.resolve_local_indexing_access_policy(
                session, grant.access_policy_revision_id, sha256=grant.content_sha256
            )
            == grant
        )
        assert (
            service.resolve_access_policy(
                session, source.access_policy_revision_id, sha256=source.content_sha256
            )
            == source
        )
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_locks "
                    "WHERE pid=pg_catalog.pg_backend_pid() "
                    "AND relation='app.education_retrieval_access_policy_revisions'::regclass "
                    "AND mode='RowShareLock'"
                )
            )
            == 0
        )


@pytest.mark.parametrize(
    "table", ["education_retrieval_access_policy_revisions", "knowledge_graph_publications"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_actual_select_only_login_still_cannot_mutate_immutable_records(
    limited_policies, table, operation
):
    runtime, _, _ = limited_policies
    statement = f"DELETE FROM app.{table} WHERE false"
    if operation == "UPDATE":
        column = (
            "content_sha256" if table.startswith("education_") else "graph_snapshot_revision_id"
        )
        statement = f"UPDATE app.{table} SET {column}={column} WHERE false"
    with runtime.connect() as connection, pytest.raises(DBAPIError) as caught:
        connection.execute(text(statement))
    assert caught.value.orig.sqlstate == "42501"


def test_actual_service_policy_pk_hash_and_source_policy_lock(stored) -> None:
    session, source, grant = stored
    service = object.__new__(KnowledgeRetrievalApplicationService)
    assert (
        service.resolve_local_indexing_access_policy(
            session,
            grant.access_policy_revision_id,
            sha256=grant.content_sha256,
        )
        == grant
    )
    assert (
        service.lock_source_access_policy(
            session,
            source.access_policy_revision_id,
            sha256=source.content_sha256,
        )
        == source
    )
    assert source.access_policy_revision_id != grant.access_policy_revision_id
    assert (
        session.scalar(
            text(
                "SELECT count(*) FROM pg_catalog.pg_locks "
                "WHERE pid=pg_catalog.pg_backend_pid() "
                "AND relation='app.education_retrieval_access_policy_revisions'::regclass "
                "AND mode='RowShareLock'"
            )
        )
        == 1
    )


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_actual_policy_immutability_is_database_enforced_even_for_owner(stored, operation):
    session, source, grant = stored
    query = "DELETE FROM app.education_retrieval_access_policy_revisions WHERE "
    if operation == "UPDATE":
        query = "UPDATE app.education_retrieval_access_policy_revisions SET state=state WHERE "
    with pytest.raises(DBAPIError) as caught, session.begin_nested():
        session.execute(
            text(query + "access_policy_revision_id=:id"), {"id": grant.access_policy_revision_id}
        )
    assert caught.value.orig.sqlstate == "P0001"
    assert (
        KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            session, grant.access_policy_revision_id, sha256=grant.content_sha256
        )
        == grant
    )
    service = object.__new__(KnowledgeRetrievalApplicationService)
    assert (
        service.resolve_access_policy(
            session, source.access_policy_revision_id, sha256=source.content_sha256
        )
        == source
    )


@pytest.mark.parametrize("stored", ["row_hash", "schema", "semantic_hash", "extra"], indirect=True)
def test_actual_untrusted_service_policy_metadata_cannot_authorize(stored) -> None:
    session, _source, grant = stored
    with pytest.raises(KnowledgeRetrievalServiceError):
        KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            session,
            grant.access_policy_revision_id,
            sha256=grant.content_sha256,
        )


@pytest.mark.parametrize("fault", ["missing", "hash", "wrong_family"])
def test_actual_missing_hash_and_family_are_not_silently_substituted(stored, fault) -> None:
    session, source, grant = stored
    revision_id = (
        "accessrev_" + uuid4().hex if fault == "missing" else grant.access_policy_revision_id
    )
    sha = "sha256:" + "f" * 64 if fault == "hash" else grant.content_sha256
    if fault == "wrong_family":
        revision_id, sha = source.access_policy_revision_id, source.content_sha256
    with pytest.raises(KnowledgeRetrievalServiceError):
        KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            session,
            revision_id,
            sha256=sha,
        )


def test_actual_human_reader_cannot_interpret_service_grant_as_source_policy(stored) -> None:
    session, _source, grant = stored
    service = object.__new__(KnowledgeRetrievalApplicationService)
    for operation in (service.resolve_access_policy, service.lock_source_access_policy):
        with pytest.raises(KnowledgeRetrievalServiceError):
            operation(session, grant.access_policy_revision_id, sha256=grant.content_sha256)
