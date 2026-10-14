"""Real guarded PostgreSQL policy reads under its owner, NOT live service authority.

Synthetic1.0/1.1 rows exist only in rolled-back roots. No role/service is granted,
no original source is read and no model/worker/Artifact operation occurs.
"""

from __future__ import annotations

import os
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
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_local_indexing_policy_contracts import policy_document

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def exact_opt_in() -> None:
    if os.environ.get("EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION") != "1":
        pytest.skip("use guarded local-indexing-service-tests; never production")


@pytest.fixture
def stored(guarded_engine: Engine, request: pytest.FixtureRequest):
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
    rows = [
        EducationRetrievalAccessPolicyRevisionRecord(
            access_policy_revision_id=policy.access_policy_revision_id,
            schema_version=policy.schema_version,
            state="RELEASED",
            content_sha256=policy.content_sha256,
            canonical_document=policy.model_dump(mode="json"),
            created_by=guarded_engine.url.username,
            created_at=policy.created_at,
        )
        for policy in (source, grant)
    ]
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
