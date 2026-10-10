"""Fake-session owner checks only; no DB/NAS or source content is queried."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import eom_catalog_service.inference_transfer_metadata_service as module
import pytest
from eom_catalog_service.inference_transfer_metadata_service import (
    CatalogInferenceTransferMetadataService,
)
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRevisionRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalServiceError
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import PermissionKey

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_metadata_fixtures import ACTOR, metadata_graph, metadata_request

PERMISSIONS = {
    PermissionKey.ITEM_READ,
    PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
    PermissionKey.KNOWLEDGE_ANALYSIS_READ,
    PermissionKey.CONTENT_INTAKE_READ,
}


@pytest.fixture
def owner(monkeypatch):
    service = object.__new__(CatalogInferenceTransferMetadataService)
    session, context = MagicMock(), MagicMock()
    context.__enter__.return_value = session
    service.sessions = Mock(return_value=context)
    service.retrieval = Mock()
    actor = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    graph = metadata_graph()
    snapshot = SimpleNamespace(
        state="PUBLISHED",
        snapshot_sha256=sha("9"),
        graph_id=graph.graph_id,
        manifest_sha256=graph.manifest_sha256,
        corpus_revision_id="corpusrev_" + "4" * 32,
    )
    revision = SimpleNamespace(state="PUBLISHED", corpus_id="corpus_" + "4" * 32)
    corpus = SimpleNamespace(
        lifecycle_state="ACTIVE",
        graph_id=graph.graph_id,
        corpus_id=revision.corpus_id,
        current_graph_snapshot_revision_id="graphrev_" + "f" * 32,
    )
    rows = {
        OperatorRecord: actor,
        KnowledgeGraphSnapshotRecord: snapshot,
        KnowledgeCorpusRevisionRecord: revision,
    }
    session.get.side_effect = lambda cls, _identity: rows.get(cls)
    session.scalar.return_value = corpus
    policy = SimpleNamespace(
        access_policy_revision_id=metadata_request().access_policy_revision_id,
        content_sha256=metadata_request().access_policy_sha256,
        allowed_requester_roles=("ADMIN", "EDITOR"),
        answer_bearing_roles=("ADMIN", "EDITOR"),
        allowed_query_kinds=("ITEM_PREPARATION",),
        allowed_source_classes=("APPROVED_ITEM", "PAST_EXAM"),
    )
    service.retrieval.resolve_access_policy.return_value = policy
    service.retrieval.resolve_snapshot_pointer.return_value = graph
    monkeypatch.setattr(module, "effective_permissions", Mock(return_value=PERMISSIONS))
    monkeypatch.setattr(
        module,
        "active_role_assignments",
        Mock(return_value=[(None, SimpleNamespace(role_key="EDITOR"))]),
    )
    return SimpleNamespace(
        service=service,
        session=session,
        actor=actor,
        snapshot=snapshot,
        revision=revision,
        corpus=corpus,
        policy=policy,
        rows=rows,
    )


def rejected(owner, code):
    with pytest.raises(InferenceTransferServiceError) as error:
        owner.service.resolve(ACTOR, metadata_request())
    assert error.value.code == code


def test_exact_read_uses_official_resolvers_and_read_only_transaction(owner):
    result = owner.service.resolve(ACTOR, metadata_request())
    assert result.graph_snapshot == metadata_graph()
    assert result.snapshot_sha256 != result.graph_snapshot.manifest_sha256
    owner.session.connection.assert_called_once_with(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )
    assert str(owner.session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    owner.service.retrieval.resolve_access_policy.assert_called_once_with(
        owner.session,
        metadata_request().access_policy_revision_id,
        sha256=metadata_request().access_policy_sha256,
    )
    owner.session.commit.assert_not_called()
    # Exact historical pins remain valid inside an active corpus; never substitute current.
    assert (
        result.graph_snapshot.graph_snapshot_revision_id
        != owner.corpus.current_graph_snapshot_revision_id
    )


@pytest.mark.parametrize("permission", tuple(PERMISSIONS))
def test_current_permission_required_before_metadata_lookup(owner, monkeypatch, permission):
    monkeypatch.setattr(
        module, "effective_permissions", Mock(return_value=PERMISSIONS - {permission})
    )
    rejected(owner, "INFERENCE_TRANSFER_FORBIDDEN")
    owner.service.retrieval.resolve_snapshot_pointer.assert_not_called()


def test_registered_items_do_not_need_past_exam_intake_permission(owner, monkeypatch):
    monkeypatch.setattr(
        module,
        "effective_permissions",
        Mock(return_value=PERMISSIONS - {PermissionKey.CONTENT_INTAKE_READ}),
    )
    assert owner.service.resolve(
        ACTOR, metadata_request(source_classes=("APPROVED_ITEM",))
    ).source_classes == ("APPROVED_ITEM",)


@pytest.mark.parametrize(
    "field,value", [("status", "DISABLED"), ("deleted_at", True), ("must_change_password", True)]
)
def test_disabled_deleted_password_change_operator_rejected(owner, field, value):
    setattr(owner.actor, field, value)
    rejected(owner, "INFERENCE_TRANSFER_FORBIDDEN")


def test_unknown_operator_rejected(owner):
    owner.rows.pop(OperatorRecord)
    rejected(owner, "INFERENCE_TRANSFER_FORBIDDEN")


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_requester_roles", ("WORKER",)),
        ("answer_bearing_roles", ()),
        ("allowed_query_kinds", ("CURRICULUM_COMPONENTS",)),
        ("allowed_source_classes", ("APPROVED_ITEM",)),
    ],
)
def test_policy_does_not_broaden_roles_query_or_classes(owner, field, value):
    setattr(owner.policy, field, value)
    rejected(owner, "INFERENCE_TRANSFER_FORBIDDEN")


def test_released_policy_exact_hash_failure_is_explicit(owner):
    owner.service.retrieval.resolve_access_policy.side_effect = KnowledgeRetrievalServiceError(
        "KNOWLEDGE_RETRIEVAL_POLICY_STALE", "synthetic"
    )
    rejected(owner, "INFERENCE_TRANSFER_METADATA_POLICY_INVALID")


@pytest.mark.parametrize(
    "variant",
    [
        "missing_graph",
        "unpublished",
        "semantic_hash",
        "missing_corpus",
        "retired_corpus",
        "missing_revision",
        "unpublished_revision",
        "foreign_revision",
        "foreign_graph",
    ],
)
def test_graph_semantic_and_corpus_lifecycle_pins(owner, variant):
    if variant == "missing_graph":
        owner.rows.pop(KnowledgeGraphSnapshotRecord)
    elif variant == "unpublished":
        owner.snapshot.state = "DRAFT"
    elif variant == "semantic_hash":
        owner.snapshot.snapshot_sha256 = sha("1")
    elif variant == "missing_corpus":
        owner.session.scalar.return_value = None
    elif variant == "retired_corpus":
        owner.corpus.lifecycle_state = "RETIRED"
    elif variant == "missing_revision":
        owner.rows.pop(KnowledgeCorpusRevisionRecord)
    elif variant == "unpublished_revision":
        owner.revision.state = "DRAFT"
    elif variant == "foreign_revision":
        owner.revision.corpus_id = "corpus_" + "1" * 32
    elif variant == "foreign_graph":
        owner.corpus.graph_id = "graph_" + "1" * 32
    rejected(
        owner,
        "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH"
        if variant == "semantic_hash"
        else "INFERENCE_TRANSFER_METADATA_NOT_FOUND",
    )


def test_manifest_official_resolution_failure_is_not_a_synthesized_pointer(owner):
    owner.service.retrieval.resolve_snapshot_pointer.side_effect = KnowledgeRetrievalServiceError(
        "KNOWLEDGE_RETRIEVAL_SNAPSHOT_STALE", "synthetic"
    )
    rejected(owner, "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH")


def test_authorization_revoked_between_identical_reads_is_not_cached(owner, monkeypatch):
    owner.service.resolve(ACTOR, metadata_request())
    monkeypatch.setattr(module, "effective_permissions", Mock(return_value=set()))
    rejected(owner, "INFERENCE_TRANSFER_FORBIDDEN")
    assert owner.service.retrieval.resolve_snapshot_pointer.call_count == 1
