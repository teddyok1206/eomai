"""Pure compatibility and non-DB owner denials; no service or policy activation."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.knowledge import EducationRetrievalAccessPolicy
from eom_catalog_contracts.local_indexing_policy import (
    LocalIndexingAccessPolicy,
    require_local_indexing_source_policy,
)
from eom_catalog_service.local_indexing_policy_publication import (
    LocalIndexingPolicyPublicationError,
    publish_local_indexing_access_policy,
)
from eom_identifiers import content_sha256
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.unit.test_local_indexing_policy_contracts import policy_document


def source_policy(**changes: object) -> EducationRetrievalAccessPolicy:
    body: dict[str, Any] = dict(
        schema_version="education-retrieval-access-policy/1.0",
        access_policy_revision_id="accessrev_" + "a" * 32,
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
    body.update(changes)
    body["content_sha256"] = content_sha256(body)
    return EducationRetrievalAccessPolicy.model_validate(body)


def policy_for(
    source: EducationRetrievalAccessPolicy, **changes: object
) -> LocalIndexingAccessPolicy:
    return LocalIndexingAccessPolicy.model_validate(
        policy_document(
            source_access_policy_revision_id=source.access_policy_revision_id,
            source_access_policy_sha256=source.content_sha256,
            **changes,
        )
    )


def test_pure_source_compatibility_never_invents_a_requester_role() -> None:
    source = source_policy()
    policy = policy_for(source)
    assert require_local_indexing_source_policy(policy, source) is None
    assert not hasattr(policy, "requester_role")


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_query_kinds": ["APPROVED_ITEM_STRUCTURE"]},
        {"allowed_source_classes": ["TEXTBOOK"]},
        {"answer_bearing_roles": []},
        {
            "maximum_budget": dict(
                max_documents=1,
                max_item_revisions=0,
                max_graph_nodes=32,
                max_claims=8,
                max_context_tokens=1000,
            )
        },
    ],
)
def test_one_compatibility_rule_denies_parent_limits_before_publication(changes) -> None:
    source = source_policy(**changes)
    policy = policy_for(source)
    with pytest.raises(ValueError):
        require_local_indexing_source_policy(policy, source)


def test_no_implicit_root_no_non_postgres_fallback() -> None:
    policy = policy_for(source_policy())
    with Session() as session, pytest.raises(LocalIndexingPolicyPublicationError) as caught:
        publish_local_indexing_access_policy(session, policy)
    assert caught.value.code == "LOCAL_INDEXING_POLICY_CONTEXT_INVALID"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session, session.begin():
            with pytest.raises(LocalIndexingPolicyPublicationError) as caught:
                publish_local_indexing_access_policy(session, policy)
            assert caught.value.code == "LOCAL_INDEXING_POLICY_CONTEXT_INVALID"
    finally:
        engine.dispose()


def test_copied_policy_extra_fields_rejected_before_any_database_access() -> None:
    policy = policy_for(source_policy()).model_copy(update={"roles": ["ADMIN"]})
    with Session() as session, pytest.raises(ValueError):
        publish_local_indexing_access_policy(session, policy)
    assert session.get_transaction() is None


def test_publication_uses_public_identity_boundary_and_never_installs_or_executes() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "services/catalog_service/eom_catalog_service/local_indexing_policy_publication.py"
    )
    tree = ast.parse(path.read_text())
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "eom_identity_service" in modules
    assert not any((name or "").startswith("eom_identity_service.") for name in modules)
    assert not modules.intersection({"subprocess", "eom_workflow_runner", "eom_gpu_lease"})
    source = path.read_text()
    assert "on_conflict_do_nothing" in source and 'schema_translate_map={None: "app"}' in source
    assert "lock_current_local_indexing_service_metadata" in source
    assert "require_local_indexing_source_policy" in source
    assert "TransactionStatus.INTRANS" in source and "begin_nested" in source
    assert "GRANT " not in source and "UPDATE " not in source
