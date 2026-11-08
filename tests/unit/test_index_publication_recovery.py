"""Publication-only recovery guard contracts; synthetic source/OS seams, no live writes."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_catalog_service import index_publication_recovery_authority as admission
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_identifiers import content_sha256
from eom_workflow.index_publication_recovery import IndexPublicationRecoveryCommand
from eom_workflow_runner.index_publication_recovery import (
    NoNumericalRecoveryExecution,
    PreparedIndexRecoveryFence,
)

from tests.unit.test_embedding_registry_contracts import registration_command
from tests.unit.test_public_solution_indexing_policy import public_policy_document


def recovery_command():
    policy = PublicSolutionIndexingAccessPolicy.model_validate(public_policy_document())
    body = dict(
        schema_version="index-publication-recovery/1.0",
        workflow_id="workflow_" + "1" * 32,
        workflow_request_sha256="sha256:" + "1" * 64,
        native_intent_sha256="sha256:" + "2" * 64,
        registration_request_sha256="sha256:" + "3" * 64,
        current_service=policy.service.model_dump(mode="json"),
        current_policy_revision_id=policy.access_policy_revision_id,
        current_policy_sha256=policy.content_sha256,
    )
    return IndexPublicationRecoveryCommand.model_validate(
        body | {"command_sha256": content_sha256(body)}
    )


@pytest.fixture
def gate(monkeypatch):
    original = PublicSolutionIndexingAccessPolicy.model_validate(public_policy_document())
    current = PublicSolutionIndexingAccessPolicy.model_validate(
        public_policy_document(
            access_policy_revision_id="accessrev_" + "8" * 32,
            service=original.service.model_dump(mode="json")
            | {
                "service_revision_id": "localindexservicerev_" + "8" * 32,
                "service_identity_sha256": "sha256:" + "8" * 64,
            },
            runtime_configuration_sha256="sha256:" + "8" * 64,
            native_execution_policy_sha256="sha256:" + "7" * 64,
        )
    )
    fence = Mock()
    value = admission.IndexPublicationRecoveryAuthority(
        original.service,
        current.service,
        original.access_policy_revision_id,
        original.content_sha256,
        current.access_policy_revision_id,
        current.content_sha256,
        registration_command().graph_snapshot,
        fence,
    )
    retrieval = Mock()
    retrieval.resolve_local_indexing_access_policy.side_effect = lambda _, revision_id, **kwargs: (
        original if revision_id == original.access_policy_revision_id else current
    )
    monkeypatch.setattr(admission.os, "getresuid", lambda: (0, 0, 0))
    return value, retrieval, original, current


def test_hash_and_schema_roundtrip():
    command = recovery_command()
    assert (
        IndexPublicationRecoveryCommand.model_validate(command.model_dump(mode="json")) == command
    )
    for change in (
        {"role": "ADMIN"},
        {"workflow_id": "workflow_" + "9" * 32},
        {"command_sha256": "sha256:" + "0" * 64},
    ):
        with pytest.raises(ValueError):
            IndexPublicationRecoveryCommand.model_validate(command.model_dump(mode="json") | change)


def test_recovery_requires_actual_root_before_source_read(gate, monkeypatch):
    value, retrieval, original, _ = gate
    monkeypatch.setattr(admission.os, "getresuid", lambda: (1000, 1000, 1000))
    with pytest.raises(ValueError, match="FORBIDDEN"):
        value.policy(Mock(), retrieval, original.access_policy_revision_id, original.content_sha256)
    retrieval.resolve_local_indexing_access_policy.assert_not_called()
    value.fence.assert_not_called()


def test_current_maintenance_fence_and_both_released_grants_required(gate):
    value, retrieval, original, _ = gate
    session = Mock()
    assert (
        value.policy(
            session, retrieval, original.access_policy_revision_id, original.content_sha256
        )
        == original
    )
    value.fence.assert_called_once_with(session)
    assert retrieval.resolve_local_indexing_access_policy.call_count == 2
    value.fence.side_effect = ValueError("SCHEMA_OWNER_REQUIRED")
    with pytest.raises(ValueError, match="SCHEMA_OWNER_REQUIRED"):
        value.policy(
            session, retrieval, original.access_policy_revision_id, original.content_sha256
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_sources", 8192),
        ("maximum_page_sources", 512),
        ("source_classes", ["PAST_EXAM"]),
        ("resource_profile_sha256", "sha256:" + "3" * 64),
        ("source_access_policy_sha256", "sha256:" + "3" * 64),
        ("corpus_id", "corpus_" + "3" * 32),
        ("graph_id", "graph_" + "3" * 32),
    ],
)
def test_current_scope_changes_cannot_be_hidden_as_release_metadata(gate, field, value):
    authority, retrieval, original, current = gate
    body = current.model_dump(mode="json") | {field: value}
    body["content_sha256"] = content_sha256(
        {k: v for k, v in body.items() if k != "content_sha256"}
    )
    changed = PublicSolutionIndexingAccessPolicy.model_validate(body)
    retrieval.resolve_local_indexing_access_policy.side_effect = [original, changed]
    with pytest.raises(ValueError, match="FORBIDDEN"):
        authority.policy(
            Mock(), retrieval, original.access_policy_revision_id, original.content_sha256
        )


def test_other_policy_graph_discovery_and_segmented_reads_forbidden(gate):
    value, retrieval, original, _ = gate
    with pytest.raises(ValueError, match="FORBIDDEN"):
        value.policy(Mock(), retrieval, "accessrev_" + "9" * 32, original.content_sha256)
    with pytest.raises(ValueError, match="FORBIDDEN"):
        replace(value, graph=Mock()).require_scope(Mock(graph_snapshot=value.graph))
    owner = CatalogLocalIndexingSourceAuthority(retrieval, value)
    for method in (owner.current_graph, owner._current_segmented_policy):
        with pytest.raises(ValueError, match="FORBIDDEN"):
            method(Mock(), original.access_policy_revision_id, original.content_sha256)


def test_numerical_leaf_always_forbidden():
    leaf = NoNumericalRecoveryExecution()
    assert leaf.device == "CPU"
    with pytest.raises(ValueError, match="NUMERICAL_EXECUTION_FORBIDDEN"):
        leaf.assert_current_runtime(Mock())
    with pytest.raises(ValueError, match="INCOMPLETE_ENCODING"):
        leaf.observe(Mock())
    with pytest.raises(ValueError, match="NUMERICAL_EXECUTION_FORBIDDEN"):
        leaf.execute(Mock(), source=Mock(), transaction=Mock())


def test_fence_rejects_non_root_without_database_calls(monkeypatch):
    monkeypatch.setattr(admission.os, "getresuid", lambda: (1000, 1000, 1000))
    session = Mock()
    with pytest.raises(ValueError, match="SCOPE_INVALID"):
        PreparedIndexRecoveryFence(recovery_command())(session)
    session.get_transaction.assert_not_called()
