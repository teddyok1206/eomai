"""Synthetic IAM/SQL seams for real policy/owner logic, NOT installed data admission."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.local_indexing_policy import LocalIndexingAccessPolicy
from eom_catalog_service.inference_transfer_service import AdmittedInferenceTransferCorpus
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    InferenceTransferSessionCapturePhase,
    LocalIndexingSessionCapture,
)
from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalAccessPolicyRevisionRecord,
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
    ReadOnlyKnowledgeCandidatePool,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceError,
    LocalIndexingSourceReadIntent,
)
from eom_identity_service import LocalIndexingFenceError, PostgresLocalIndexingServiceFence
from eom_operator_identity import LocalIndexingServiceIdentity
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from tests.unit.test_embedding_registry_contracts import registration_command
from tests.unit.test_local_indexing_policy_contracts import policy_document
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_postgres_local_indexing_fence import case as case


def intent(policy: LocalIndexingAccessPolicy) -> LocalIndexingSourceReadIntent:
    return LocalIndexingSourceReadIntent(
        corpus_id=policy.corpus_id,
        graph_snapshot=registration_command().graph_snapshot,
        access_policy_revision_id=policy.source_access_policy_revision_id,
        access_policy_sha256=policy.source_access_policy_sha256,
        service_policy_revision_id=policy.access_policy_revision_id,
        service_policy_sha256=policy.content_sha256,
        source_classes=policy.source_classes,
        namespace=policy.namespaces[0],
        space=policy.space,
        recipe=policy.recipe,
        native_execution_policy_sha256=policy.native_execution_policy_sha256,
        resource_profile_sha256=policy.resource_profile_sha256,
    )


class MetadataSession:
    def __init__(self, policy: LocalIndexingAccessPolicy) -> None:
        self.policy = EducationRetrievalAccessPolicyRevisionRecord(
            access_policy_revision_id=policy.access_policy_revision_id,
            schema_version=policy.schema_version,
            state=policy.state,
            content_sha256=policy.content_sha256,
            canonical_document=policy.model_dump(mode="json"),
        )
        self.corpus = SimpleNamespace(graph_id=policy.graph_id, lifecycle_state="ACTIVE")
        self.publication: object | None = object()
        self.calls: list[object] = []

    def scalar(self, statement: Any) -> Any:
        self.calls.append(statement)
        model = statement.column_descriptions[0]["entity"]
        return {
            EducationRetrievalAccessPolicyRevisionRecord: self.policy,
            KnowledgeCorpusRecord: self.corpus,
            KnowledgeGraphPublicationRecord: self.publication,
        }[model]


@pytest.fixture
def owner(case, monkeypatch: pytest.MonkeyPatch):
    fence, synthetic_sql = case
    policy = LocalIndexingAccessPolicy.model_validate(
        policy_document(
            service=fence.pin.service.model_dump(mode="json"),
            runtime_configuration_sha256=fence.pin.configuration_sha256,
        )
    )
    selection = intent(policy)
    checked = LocalIndexingServiceIdentity.model_validate(synthetic_sql.db.value["identity"])
    iam = Mock(return_value=checked)
    monkeypatch.setattr(PostgresLocalIndexingServiceFence, "fence_current_service", iam)
    retrieval = Mock(spec=KnowledgeRetrievalApplicationService)
    retrieval.resolve_local_indexing_access_policy.return_value = policy
    retrieval.resolve_access_policy.return_value = SimpleNamespace(
        access_policy_revision_id=policy.source_access_policy_revision_id,
        content_sha256=policy.source_access_policy_sha256,
        allowed_source_classes=policy.source_classes,
        allowed_query_kinds=("ITEM_PREPARATION",),
        answer_bearing_roles=("EDITOR",),
        maximum_budget=SimpleNamespace(max_item_revisions=64),
    )
    retrieval.resolve_snapshot_pointer.return_value = selection.graph_snapshot
    authority = CatalogLocalIndexingSourceAuthority(retrieval, fence)
    return SimpleNamespace(
        authority=authority,
        policy=policy,
        intent=selection,
        iam=iam,
        retrieval=retrieval,
        session=MetadataSession(policy),
    )


def authorize(owner):
    return owner.authority.authorize_scope(cast(Session, owner.session), owner.intent)


def test_exact_service_locks_mutable_head_but_only_reads_immutable_metadata(owner) -> None:
    assert authorize(owner) == owner.policy
    owner.iam.assert_called_once_with(owner.session)
    owner.retrieval.resolve_local_indexing_access_policy.assert_called_once_with(
        owner.session,
        owner.policy.access_policy_revision_id,
        sha256=owner.policy.content_sha256,
    )
    owner.retrieval.resolve_access_policy.assert_called_once_with(
        owner.session,
        owner.policy.source_access_policy_revision_id,
        sha256=owner.policy.source_access_policy_sha256,
    )
    assert owner.policy.access_policy_revision_id != owner.intent.access_policy_revision_id
    corpus, publication = owner.session.calls
    assert corpus._for_update_arg.read
    assert publication._for_update_arg is None
    owner.retrieval.lock_source_access_policy.assert_not_called()
    assert all(
        statement.get_execution_options()["populate_existing"] for statement in owner.session.calls
    )
    assert not hasattr(owner.intent, "requester_role")
    assert not hasattr(owner.intent, "requester_permission_keys")


def test_current_graph_discovery_authenticates_and_pins_actual_head(owner):
    graph = owner.intent.graph_snapshot
    owner.session.corpus.current_graph_snapshot_revision_id = graph.graph_snapshot_revision_id
    policy, actual = owner.authority.current_graph(
        owner.session, owner.policy.access_policy_revision_id, owner.policy.content_sha256
    )
    assert policy == owner.policy and actual == graph
    assert owner.iam.call_count == 2
    owner.retrieval.resolve_snapshot_pointer.assert_called_once_with(
        owner.session, graph.graph_snapshot_revision_id
    )
    assert all(statement._for_update_arg.read for statement in owner.session.calls)


def test_current_graph_legitimate_unpublished_corpus_has_no_invented_pointer(owner):
    owner.session.corpus.current_graph_snapshot_revision_id = None
    policy, actual = owner.authority.current_graph(
        owner.session, owner.policy.access_policy_revision_id, owner.policy.content_sha256
    )
    assert policy == owner.policy and actual is None
    owner.retrieval.resolve_snapshot_pointer.assert_not_called()


@pytest.mark.parametrize("failure", ["revoked", "unavailable"])
def test_current_graph_authority_failure_precedes_corpus_discovery(owner, failure):
    owner.iam.side_effect = LocalIndexingFenceError(
        "LOCAL_INDEXING_FENCE_FORBIDDEN"
        if failure == "revoked"
        else "LOCAL_INDEXING_FENCE_UNAVAILABLE"
    )
    with pytest.raises(LocalIndexingSourceError, match=r"FORBIDDEN|UNAVAILABLE"):
        owner.authority.current_graph(
            owner.session, owner.policy.access_policy_revision_id, owner.policy.content_sha256
        )
    assert not owner.session.calls
    owner.retrieval.resolve_snapshot_pointer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("corpus_id", "corpus_" + "f" * 32),
        ("access_policy_revision_id", "accessrev_" + "f" * 32),
        ("access_policy_sha256", "sha256:" + "f" * 64),
        ("native_execution_policy_sha256", "sha256:" + "f" * 64),
        ("resource_profile_sha256", "sha256:" + "f" * 64),
        ("source_classes", ("APPROVED_ITEM", "PAST_EXAM")),
    ],
)
def test_out_of_grant_selection_denied_before_corpus_discovery(owner, field, value) -> None:
    owner.intent = replace(owner.intent, **{field: value})
    with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
        authorize(owner)
    assert not owner.session.calls


@pytest.mark.parametrize("fault", ["service", "runtime_config", "namespace", "maximum"])
def test_exact_runtime_namespace_and_capacity_not_merely_uid(owner, fault: str) -> None:
    changes: dict[str, object] = {}
    if fault == "service":
        changes["service"] = owner.policy.service.model_copy(
            update={"service_identity_sha256": "sha256:" + "f" * 64}
        )
    elif fault == "runtime_config":
        changes["runtime_configuration_sha256"] = "sha256:" + "f" * 64
    elif fault == "namespace":
        changes["namespaces"] = (
            owner.policy.namespaces[0].model_copy(
                update={
                    "view": "METADATA_ONLY"
                    if owner.policy.namespaces[0].view != "METADATA_ONLY"
                    else "CONTENT_ONLY",
                }
            ),
        )
    else:
        changes["maximum_sources"] = 1
    # Synthetic resolver return only; the real resolver revalidates immutable bytes/hash.
    owner.retrieval.resolve_local_indexing_access_policy.return_value = owner.policy.model_copy(
        update=changes
    )
    with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
        authorize(owner)


@pytest.mark.parametrize(
    "fault",
    [
        "corpus_missing",
        "inactive",
        "different_graph",
        "unpublished",
        "graph_hash",
        "source_class",
        "query_kind",
        "answer_bearing",
        "item_budget",
    ],
)
def test_current_graph_publication_lifecycle_and_source_policy_constraints(
    owner, fault: str
) -> None:
    if fault == "corpus_missing":
        owner.session.corpus = None
    elif fault == "inactive":
        owner.session.corpus.lifecycle_state = "RETIRED"
    elif fault == "different_graph":
        owner.session.corpus.graph_id = "graph_" + "f" * 32
    elif fault == "unpublished":
        owner.session.publication = None
    elif fault == "graph_hash":
        owner.retrieval.resolve_snapshot_pointer.return_value = None
    elif fault == "source_class":
        owner.retrieval.resolve_access_policy.return_value.allowed_source_classes = ("TEXTBOOK",)
    elif fault == "query_kind":
        owner.retrieval.resolve_access_policy.return_value.allowed_query_kinds = ()
    elif fault == "answer_bearing":
        owner.retrieval.resolve_access_policy.return_value.answer_bearing_roles = ()
    else:
        owner.retrieval.resolve_access_policy.return_value.maximum_budget.max_item_revisions = 0
    with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
        authorize(owner)


@pytest.mark.parametrize(
    "fault", ["revoked", "runtime_unavailable", "policy_unavailable", "database"]
)
def test_authority_failures_redacted_without_synthetic_fallback(owner, fault: str) -> None:
    if fault in {"revoked", "runtime_unavailable"}:
        owner.iam.side_effect = LocalIndexingFenceError(
            "LOCAL_INDEXING_FENCE_FORBIDDEN"
            if fault == "revoked"
            else "LOCAL_INDEXING_FENCE_UNAVAILABLE",
        )
    elif fault == "policy_unavailable":
        owner.retrieval.resolve_local_indexing_access_policy.side_effect = ValueError(
            "SECRET_MARKER"
        )
    else:
        owner.session.scalar = Mock(side_effect=SQLAlchemyError("SECRET_MARKER"))
    with pytest.raises(LocalIndexingSourceError) as caught:
        authorize(owner)
    assert "SECRET_MARKER" not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize(
    "fault", ["absent", "old_schema", "state", "raw_hash", "id", "semantic_hash", "extra"]
)
def test_actual_policy_resolver_revalidates_exact_released_metadata(owner, fault: str) -> None:
    row = owner.session.policy
    revision, sha = owner.policy.access_policy_revision_id, owner.policy.content_sha256
    if fault == "absent":
        owner.session.policy = None
    elif fault == "old_schema":
        row.schema_version = "education-retrieval-access-policy/1.0"
    elif fault == "state":
        row.state = "ACTIVE"
    elif fault == "raw_hash":
        row.content_sha256 = "sha256:" + "f" * 64
    elif fault == "id":
        revision = "accessrev_" + "f" * 32
    elif fault == "semantic_hash":
        row.canonical_document["maximum_sources"] = 1
    else:
        row.canonical_document["roles"] = ["ADMIN"]
    with pytest.raises(KnowledgeRetrievalServiceError):
        KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            cast(Session, owner.session),
            revision,
            sha256=sha,
        )


def test_actual_policy_resolver_returns_exact_small_model_without_write_privilege(owner) -> None:
    actual = KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
        cast(Session, owner.session),
        owner.policy.access_policy_revision_id,
        sha256=owner.policy.content_sha256,
    )
    assert actual == owner.policy and owner.session.calls[0]._for_update_arg is None
    assert owner.session.calls[0].get_execution_options()["populate_existing"]


def test_service_front_door_reuses_candidate_algorithm_without_operator_authorization(
    owner,
) -> None:
    retrieval = object.__new__(KnowledgeRetrievalApplicationService)
    retrieval.resolve_snapshot_pointer = Mock(return_value=owner.intent.graph_snapshot)
    pool = ReadOnlyKnowledgeCandidatePool(owner.intent.graph_snapshot, (), False)
    retrieval._read_candidate_pool = Mock(return_value=pool)
    retrieval._authorize = Mock(side_effect=AssertionError("must not invent an operator"))
    authority = Mock()
    authority.authorize_scope.return_value = owner.policy
    assert (
        retrieval.admit_local_indexing_candidate_pool(
            owner.session,
            owner.intent,
            authority=authority,
        )
        is pool
    )
    assert authority.authorize_scope.call_count == 2
    assert retrieval._read_candidate_pool.call_args.kwargs["allow_answer_bearing"] is True
    retrieval._authorize.assert_not_called()
    retrieval._read_candidate_pool.reset_mock()
    authority.authorize_scope.side_effect = [
        owner.policy,
        LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN"),
    ]
    with pytest.raises(LocalIndexingSourceError):
        retrieval.admit_local_indexing_candidate_pool(
            owner.session, owner.intent, authority=authority
        )
    assert retrieval._read_candidate_pool.call_count == 1


@pytest.mark.parametrize("maximum", [True, 0, 1025, "10"])
def test_bad_bound_cannot_become_an_unbounded_selection(owner, maximum) -> None:
    with pytest.raises(LocalIndexingSourceError, match="SCOPE_INVALID"):
        replace(owner.intent, maximum_candidates=maximum)


def test_absent_actual_fence_cannot_create_service_authority(owner) -> None:
    with pytest.raises(LocalIndexingSourceError, match="UNAVAILABLE"):
        CatalogLocalIndexingSourceAuthority(owner.retrieval, None)


def test_scope_only_service_capture_reads_no_population_or_source_bytes(owner) -> None:
    adapter = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    adapter._capture_population = Mock(side_effect=AssertionError("no early source IO"))
    authority, reader = Mock(), Mock()
    authority.authorize_scope.return_value = owner.policy
    result = adapter.capture_indexing_in_session(
        owner.session,
        owner.intent,
        authority=authority,
        artifact_reader=reader,
        phase=InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE,
    )
    assert result == LocalIndexingSessionCapture(owner.intent)
    assert authority.authorize_scope.call_count == 1
    reader.require_session.assert_called_once_with(owner.session)
    reader.verify_member.assert_not_called()
    adapter._capture_population.assert_not_called()


def test_population_service_capture_uses_shared_body_and_rechecks_late(owner) -> None:
    adapter = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    adapter.sources = Mock()
    authority, reader = Mock(), Mock()
    authority.authorize_scope.return_value = owner.policy
    pool = ReadOnlyKnowledgeCandidatePool(owner.intent.graph_snapshot, (), False)
    adapter.sources.retrieval.admit_local_indexing_candidate_pool.return_value = pool
    corpus = AdmittedInferenceTransferCorpus((), (), False, 0, ())

    def capture(session, scope, recipe, *, artifact_reader, read_pool):
        assert (session, scope, recipe, artifact_reader) == (
            owner.session,
            owner.intent,
            owner.intent.recipe,
            reader,
        )
        assert read_pool() is pool
        return corpus, ()

    adapter._capture_population = Mock(side_effect=capture)
    result = adapter.capture_indexing_in_session(
        owner.session,
        owner.intent,
        authority=authority,
        artifact_reader=reader,
    )
    assert result == LocalIndexingSessionCapture(owner.intent, corpus, ())
    assert authority.authorize_scope.call_count == 2
    adapter.sources._scope.assert_not_called()
    adapter.sources.retrieval.admit_read_only_candidate_pool.assert_not_called()
    authority.authorize_scope.side_effect = [
        owner.policy,
        LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN"),
    ]
    with pytest.raises(LocalIndexingSourceError):
        adapter.capture_indexing_in_session(
            owner.session,
            owner.intent,
            authority=authority,
            artifact_reader=reader,
        )


def test_missing_service_authority_is_explicit_unavailable_before_source_discovery(owner) -> None:
    adapter = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    with pytest.raises(LocalIndexingSourceError, match="UNAVAILABLE"):
        adapter.capture_indexing_in_session(
            owner.session,
            owner.intent,
            authority=None,
            artifact_reader=Mock(),
        )
