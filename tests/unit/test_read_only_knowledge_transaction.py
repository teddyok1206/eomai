"""Synthetic transaction/cache guards; no DB connection, real authority or latency claim."""

from __future__ import annotations

from collections import Counter, deque
from contextlib import suppress
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import validate_contract
from eom_catalog_contracts.application import CreateEvidenceBundleCommand
from eom_catalog_contracts.knowledge import EvidenceBudget
from eom_catalog_service import knowledge_analysis_sources as sources
from eom_catalog_service import knowledge_retrieval_service as retrieval
from eom_catalog_service import past_exam_source_provenance as provenance
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalCandidate,
    KnowledgeRetrievalServiceError,
    ReadOnlyCandidatePoolScope,
    ReadOnlyKnowledgeReuseContext,
)
from eom_catalog_service.past_exam_source_provenance import PastExamSourceResolutionCache
from eom_identifiers import content_sha256
from jsonschema import ValidationError as SchemaError
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import NOW, sha, source_basis
from tests.unit.test_past_exam_source_provenance import (
    _decode_all,
    _documents,
    _member,
    _Reader,
    _source_fixture,
)

INVALID = "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID"


def _scope() -> ReadOnlyCandidatePoolScope:
    return ReadOnlyCandidatePoolScope(
        graph_snapshot=source_basis().graph_snapshot,
        access_policy_revision_id="accessrev_" + "5" * 32,
        access_policy_sha256=sha("5"),
        requested_by="operator_" + "6" * 32,
        requester_role="ADMIN",
        requester_permission_keys=("knowledge_graph:read", "knowledge_graph:retrieve"),
        source_classes=("PAST_EXAM",),
        evidence_budget=EvidenceBudget(
            max_documents=2,
            max_item_revisions=8,
            max_graph_nodes=128,
            max_claims=32,
            max_context_tokens=4000,
        ),
    )


def _command(scope: ReadOnlyCandidatePoolScope, ordinal: int = 0) -> CreateEvidenceBundleCommand:
    body = {
        "operation": "CREATE_EVIDENCE_BUNDLE",
        "graph_snapshot_revision_id": scope.graph_snapshot.graph_snapshot_revision_id,
        "query_kind": scope.query_kind,
        "curriculum_scope": None,
        "topic_keys": [f"synthetic.topic-{ordinal}"],
        "target_item_revision_id": None,
        "required_item_elements": [],
        "source_classes": list(scope.source_classes),
        "evidence_budget": scope.evidence_budget.model_dump(mode="json"),
        "access_policy_revision_id": scope.access_policy_revision_id,
        "requester_role": scope.requester_role,
        "requester_permission_keys": list(scope.requester_permission_keys),
        "requested_by": scope.requested_by,
    }
    return CreateEvidenceBundleCommand.model_validate(
        body
        | {
            "idempotency_key": f"synthetic-read-only-{ordinal}",
            "submission_sha256": content_sha256(body),
        }
    )


def _service(
    monkeypatch: pytest.MonkeyPatch, session: Session, scope: ReadOnlyCandidatePoolScope
) -> tuple[KnowledgeRetrievalApplicationService, _Reader, Counter[str]]:
    service = object.__new__(KnowledgeRetrievalApplicationService)
    reader = _Reader(_documents())
    service.artifacts = cast(Any, reader)
    calls: Counter[str] = Counter()
    policy = SimpleNamespace(
        content_sha256=scope.access_policy_sha256,
        access_policy_revision_id=scope.access_policy_revision_id,
        answer_bearing_roles=("ADMIN",),
    )

    def authorize(*_args: Any) -> None:
        calls["authorization"] += 1

    monkeypatch.setattr(service, "_authorize", authorize)
    monkeypatch.setattr(service, "_snapshot_pointer", lambda *_args: scope.graph_snapshot)
    monkeypatch.setattr(service, "resolve_snapshot_pointer", lambda *_args: scope.graph_snapshot)
    monkeypatch.setattr(service, "_policy", lambda *_args: policy)
    monkeypatch.setattr(service, "resolve_access_policy", lambda *_args, **_kwargs: policy)
    monkeypatch.setattr(session, "scalars", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(service, "_candidates", lambda *_args, **_kwargs: ())
    original_request = KnowledgeRetrievalApplicationService._request
    monkeypatch.setattr(
        service,
        "_request",
        lambda command, **kwargs: original_request(command, **(kwargs | {"created_at": NOW})),
    )
    return service, reader, calls


def _pool(
    service: KnowledgeRetrievalApplicationService,
    session: Session,
    scope: ReadOnlyCandidatePoolScope,
    context: ReadOnlyKnowledgeReuseContext,
) -> None:
    service.admit_read_only_candidate_pool(session, scope, reuse_context=context)


def test_context_creation_requires_actual_active_root_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session() as session:
        service, _, calls = _service(monkeypatch, session, _scope())
        with pytest.raises(KnowledgeRetrievalServiceError) as missing:
            service.create_read_only_reuse_context(session, _scope())
        assert missing.value.code == INVALID
        with session.begin():
            context = service.create_read_only_reuse_context(session, _scope())
            assert isinstance(context, ReadOnlyKnowledgeReuseContext)
            assert repr(context) == "ReadOnlyKnowledgeReuseContext()"
            with pytest.raises(FrozenInstanceError):
                cast(Any, context)._thread_id = 0
            with session.begin_nested():
                with pytest.raises(KnowledgeRetrievalServiceError) as nested:
                    service.create_read_only_reuse_context(session, _scope())
                assert nested.value.code == INVALID
        assert calls["authorization"] == 0  # Construction does not manufacture authority.


@pytest.mark.parametrize(
    "field",
    [
        "graph_snapshot",
        "access_policy_revision_id",
        "access_policy_sha256",
        "requested_by",
        "requester_role",
        "requester_permission_keys",
        "source_classes",
        "evidence_budget",
        "query_kind",
    ],
)
def test_pool_rejects_each_exact_scope_mismatch_before_cache_use(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = _scope()
    replacements: dict[str, Any] = {
        "graph_snapshot": scope.graph_snapshot.model_copy(update={"manifest_sha256": sha("f")}),
        "access_policy_revision_id": "accessrev_" + "f" * 32,
        "access_policy_sha256": sha("f"),
        "requested_by": "operator_" + "f" * 32,
        "requester_role": "EDITOR",
        "requester_permission_keys": ("knowledge_graph:retrieve",),
        "source_classes": ("APPROVED_ITEM",),
        "evidence_budget": scope.evidence_budget.model_copy(update={"max_claims": 31}),
        "query_kind": "APPROVED_ITEM_STRUCTURE",
    }
    changed = replace(scope, **{field: replacements[field]})
    with Session() as session, session.begin():
        service, _, calls = _service(monkeypatch, session, scope)
        context = service.create_read_only_reuse_context(session, scope)
        # These represent fresh owner-resolved values, not a permission grant.
        monkeypatch.setattr(
            service, "resolve_snapshot_pointer", lambda *_args: changed.graph_snapshot
        )
        monkeypatch.setattr(
            service,
            "resolve_access_policy",
            lambda *_args, **_kwargs: SimpleNamespace(
                content_sha256=changed.access_policy_sha256, answer_bearing_roles=("ADMIN",)
            ),
        )
        monkeypatch.setattr(
            session, "scalars", lambda *_args: pytest.fail("no cached source lookup")
        )
        with pytest.raises(KnowledgeRetrievalServiceError) as captured:
            _pool(service, session, changed, context)
        assert captured.value.code == INVALID
        assert calls["authorization"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("requested_by", "operator_" + "f" * 32),
        ("requester_role", "REVIEWER"),
        ("requester_permission_keys", ("knowledge_graph:retrieve",)),
        ("source_classes", ("APPROVED_ITEM",)),
        ("access_policy_revision_id", "accessrev_" + "f" * 32),
        ("query_kind", "APPROVED_ITEM_STRUCTURE"),
        ("evidence_budget", _scope().evidence_budget.model_copy(update={"max_graph_nodes": 127})),
    ],
)
def test_retrieval_model_copy_cannot_bypass_scope_binding(
    field: str, value: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = _scope()
    with Session() as session, session.begin():
        service, _, calls = _service(monkeypatch, session, scope)
        context = service.create_read_only_reuse_context(session, scope)
        command = _command(scope).model_copy(update={field: value})
        monkeypatch.setattr(
            service, "_candidates", lambda *_args, **_kwargs: pytest.fail("no source use")
        )
        with pytest.raises(KnowledgeRetrievalServiceError) as captured:
            service.retrieve_read_only(session, command, reuse_context=context)
        assert captured.value.code == INVALID
        assert calls["authorization"] == 1


@pytest.mark.parametrize("different", ["session", "service", "reader", "thread"])
def test_context_rejects_foreign_owner_execution_boundary(
    different: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = _scope()
    with Session() as session, session.begin(), Session() as other, other.begin():
        service, _, _ = _service(monkeypatch, session, scope)
        context = service.create_read_only_reuse_context(session, scope)
        actual_service, actual_session = service, session
        if different == "session":
            actual_session = other
        elif different == "service":
            actual_service, _, _ = _service(monkeypatch, session, scope)
        elif different == "reader":
            service.artifacts = cast(Any, _Reader(_documents()))
        else:
            monkeypatch.setattr(retrieval, "get_ident", lambda: context._thread_id + 1)
        with pytest.raises(KnowledgeRetrievalServiceError) as captured:
            _pool(actual_service, actual_session, scope, context)
        assert captured.value.code == INVALID


@pytest.mark.parametrize("state", ["finished", "next_root", "nested"])
def test_context_rejects_closed_replaced_or_nested_transaction(
    state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = _scope()
    with Session() as session:
        service, _, _ = _service(monkeypatch, session, scope)
        with session.begin():
            context = service.create_read_only_reuse_context(session, scope)
            if state == "nested":
                with session.begin_nested():
                    with pytest.raises(KnowledgeRetrievalServiceError) as captured:
                        _pool(service, session, scope, context)
                    assert captured.value.code == INVALID
                return
        if state == "next_root":
            with session.begin(), pytest.raises(KnowledgeRetrievalServiceError) as captured:
                _pool(service, session, scope, context)
        else:
            with pytest.raises(KnowledgeRetrievalServiceError) as captured:
                _pool(service, session, scope, context)
        assert captured.value.code == INVALID


def _five_calls(
    monkeypatch: pytest.MonkeyPatch, *, reuse: bool
) -> tuple[Any, _Reader, Counter[str], list[Any], Counter[str]]:
    """Real public admission, fake current source/SQL and deterministic ranking fixture.

    Existing Graph ranking tests own scientific/query ranking behavior. This test
    measures immutable decoder reuse and exact fixture output/order equivalence.
    """
    documents = _documents()
    # Current relation SQL/source checks are this fixture's explicit fake seam;
    # fresh real relation batching has its own source-resolver regression suite.
    monkeypatch.setattr(retrieval, "read_item_source_relations", lambda *_args: None)
    scope = _scope()
    validations: Counter[str] = Counter()
    real_validate = validate_contract

    def validate(name: str, value: dict[str, Any]) -> None:
        validations[name] += 1
        real_validate(name, value)

    monkeypatch.setattr(provenance, "validate_contract", validate)
    with Session() as session, session.begin():
        service, reader, calls = _service(monkeypatch, session, scope)
        run_ids = tuple(f"analysisrun_{ordinal:032x}" for ordinal in range(520))
        source = source_basis().source
        sources = {
            run_id: source.model_copy(
                update={
                    "item_id": f"item_{ordinal:032x}",
                    "item_revision_id": f"itemrev_{ordinal:032x}",
                }
            )
            for ordinal, run_id in enumerate(run_ids)
        }
        pointers = tuple(
            SimpleNamespace(
                analysis_run_id=run_id,
                node_id=f"node_{ordinal:032x}",
                anchor_id="anchor_1",
                source_class="PAST_EXAM",
                source_revision_id=sources[run_id].item_revision_id,
            )
            for ordinal, run_id in enumerate(run_ids)
        )
        nodes = tuple(
            SimpleNamespace(
                node_id=value.node_id, label="synthetic", node_type="CONCEPT", answer_bearing=False
            )
            for value in pointers
        )
        selections = tuple(pointers[ordinal * 32 : ordinal * 32 + 64] for ordinal in range(4))
        responses: deque[Any] = deque([run_ids])
        for selected in (pointers, *selections):
            responses.extend(
                [tuple(SimpleNamespace(analysis_run_id=p.analysis_run_id) for p in selected)] * 2
            )
        monkeypatch.setattr(session, "scalars", lambda *_args: responses.popleft())
        monkeypatch.setattr(
            session, "execute", lambda *_args: tuple(zip(pointers, nodes, strict=True))
        )
        per_call_caches: list[Any] = []

        def resolve(_session: Session, _snapshot: str, pointer: Any, *, cache: Any) -> Any:
            if pointer.analysis_run_id not in cache.resolved_sources_by_run_id:
                calls["current_source"] += 1
                _decode_all(cache.past_exam_provenance, cache.artifacts, documents)
                cache.resolved_sources_by_run_id[pointer.analysis_run_id] = sources[
                    pointer.analysis_run_id
                ]
                if not per_call_caches or per_call_caches[-1] is not cache:
                    per_call_caches.append(cache)
            return cache.resolved_sources_by_run_id[pointer.analysis_run_id]

        monkeypatch.setattr(service, "_resolve_snapshot_source", resolve)
        query_number = 0

        def candidates(
            _session: Session, _command: Any, _policy: Any, **kwargs: Any
        ) -> tuple[Any, ...]:
            nonlocal query_number
            selected = selections[query_number]
            query_number += 1
            cache = service._snapshot_source_resolution_cache(
                session,
                scope.graph_snapshot.graph_snapshot_revision_id,
                cast(Any, selected),
                reuse_context=kwargs["reuse_context"],
            )
            return tuple(
                KnowledgeRetrievalCandidate(
                    analysis_run_id=pointer.analysis_run_id,
                    source=resolve(session, "", pointer, cache=cache),
                    node_ids=(pointer.node_id,),
                    anchor_ids=(pointer.anchor_id,),
                    node_labels=("synthetic",),
                    node_types=("CONCEPT",),
                    relevance_milli=1000 - ordinal,
                    answer_bearing=False,
                )
                for ordinal, pointer in enumerate(selected)
            )

        monkeypatch.setattr(service, "_candidates", candidates)
        context = service.create_read_only_reuse_context(session, scope) if reuse else None
        pool = service.admit_read_only_candidate_pool(session, scope, reuse_context=context)
        query_results = tuple(
            service.retrieve_read_only(session, _command(scope, ordinal), reuse_context=context)
            for ordinal in range(4)
        )
        assert not responses
        return (pool, query_results), reader, calls, per_call_caches, validations


def test_520_admission_plus_four_queries_share_only_successful_immutable_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as isolated:
        old, old_reader, old_calls, _, old_validations = _five_calls(isolated, reuse=False)
    with monkeypatch.context() as isolated:
        new, reader, calls, caches, validations = _five_calls(isolated, reuse=True)
    assert new == old
    assert calls == old_calls == Counter(authorization=5, current_source=520 + 4 * 64)
    assert len(reader.calls) == 4 and len(old_reader.calls) == 20
    assert set(validations.values()) == {1} and set(old_validations.values()) == {5}
    assert len(caches) == 5 and len({id(cache) for cache in caches}) == 5
    assert len({id(cache.artifacts) for cache in caches}) == 1
    assert len({id(cache.past_exam_provenance) for cache in caches}) == 1
    for field in (
        "associations_by_run_id",
        "runs_by_id",
        "declared_sources_by_run_id",
        "resolved_sources_by_run_id",
        "validated_sources_by_pointer",
        "educational_documents",
    ):
        assert len({id(getattr(cache, field)) for cache in caches}) == 5


def test_current_authorization_revoke_is_not_hidden_by_warm_immutable_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope()
    with Session() as session, session.begin():
        service, reader, calls = _service(monkeypatch, session, scope)
        context = service.create_read_only_reuse_context(session, scope)
        cache = service._snapshot_source_resolution_cache(
            session, scope.graph_snapshot.graph_snapshot_revision_id, (), reuse_context=context
        )
        _decode_all(cache.past_exam_provenance, cast(_Reader, cache.artifacts), _documents())
        _pool(service, session, scope, context)

        def revoke(*_args: Any) -> None:
            calls["authorization"] += 1
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PERMISSION_DENIED", "synthetic revoke"
            )

        monkeypatch.setattr(service, "_authorize", revoke)
        with pytest.raises(KnowledgeRetrievalServiceError) as captured:
            service.retrieve_read_only(session, _command(scope), reuse_context=context)
        assert captured.value.code == "KNOWLEDGE_RETRIEVAL_PERMISSION_DENIED"
        assert calls["authorization"] == 2 and len(reader.calls) == 4


def test_next_transaction_context_revalidates_successes_and_failure_is_never_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, documents = _scope(), _documents()
    with Session() as session:
        service, reader, _ = _service(monkeypatch, session, scope)
        with session.begin():
            context = service.create_read_only_reuse_context(session, scope)
            cache = service._snapshot_source_resolution_cache(
                session, scope.graph_snapshot.graph_snapshot_revision_id, (), reuse_context=context
            )
            reader.fail_next = True
            with pytest.raises(ValueError):
                _decode_all(cache.past_exam_provenance, cast(_Reader, cache.artifacts), documents)
            first = _decode_all(
                cache.past_exam_provenance, cast(_Reader, cache.artifacts), documents
            )
            assert (
                _decode_all(cache.past_exam_provenance, cast(_Reader, cache.artifacts), documents)
                == first
            )
            assert len(reader.calls) == 5
        with session.begin():
            next_context = service.create_read_only_reuse_context(session, scope)
            next_cache = service._snapshot_source_resolution_cache(
                session,
                scope.graph_snapshot.graph_snapshot_revision_id,
                (),
                reuse_context=next_context,
            )
            assert (
                _decode_all(
                    next_cache.past_exam_provenance, cast(_Reader, next_cache.artifacts), documents
                )
                == first
            )
            assert len(reader.calls) == 9


@pytest.mark.parametrize(
    "budget", [{"max_members": 0}, {"max_source_bytes": 0}, {"max_index_rows": 0}]
)
def test_shared_cache_retention_bounds_fall_back_without_truncation(
    budget: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, documents = _scope(), _documents()
    monkeypatch.setattr(retrieval, "MAX_REQUEST_ARTIFACT_CACHE_MEMBERS", 0)
    with Session() as session, session.begin():
        service, reader, _ = _service(monkeypatch, session, scope)
        context = service.create_read_only_reuse_context(session, scope)
        # Constructor injection is test-only: force both independent retention budgets to zero.
        bounded = replace(context, _past_exam=PastExamSourceResolutionCache(**budget))
        cache = service._snapshot_source_resolution_cache(
            session, scope.graph_snapshot.graph_snapshot_revision_id, (), reuse_context=bounded
        )
        first = _decode_all(cache.past_exam_provenance, cast(_Reader, cache.artifacts), documents)
        second = _decode_all(cache.past_exam_provenance, cast(_Reader, cache.artifacts), documents)
        assert first == second and len(reader.calls) == 8


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_id", "artifact_" + "f" * 32),
        ("revision_id", "rev_" + "f" * 32),
        ("member_path", "other.json"),
        ("sha256", sha("f")),
        ("schema_ref", "eom://schemas/test/different/1.0"),
        ("media_type", "text/plain"),
        ("max_bytes", 2**20),
    ],
)
def test_transaction_shared_member_cache_keeps_each_pointer_field(
    field: str, value: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope, documents = _scope(), _documents()
    with Session() as session, session.begin():
        service, reader, _ = _service(monkeypatch, session, scope)
        member = _member("batch.json", documents["batch.json"])
        context = service.create_read_only_reuse_context(session, scope)
        cache = service._snapshot_source_resolution_cache(
            session, scope.graph_snapshot.graph_snapshot_revision_id, (), reuse_context=context
        )
        arguments = {
            "artifact_id": member.artifact_id,
            "revision_id": member.artifact_revision_id,
            "member_path": member.member_path,
            "sha256": member.sha256,
            "schema_ref": member.schema_ref,
            "media_type": member.media_type,
            "max_bytes": member.max_bytes,
        }
        cache.artifacts.read_member(**cast(Any, arguments))
        changed = arguments | {field: value}
        with suppress(ValueError, KeyError):
            cache.artifacts.read_member(**cast(Any, changed))
        assert len(reader.calls) == 2


def test_failed_typed_validation_is_not_cached_and_decoder_kind_cannot_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, documents = _scope(), _documents()
    with Session() as session, session.begin():
        service, reader, _ = _service(monkeypatch, session, scope)
        context = service.create_read_only_reuse_context(session, scope)
        cache = service._snapshot_source_resolution_cache(
            session, scope.graph_snapshot.graph_snapshot_revision_id, (), reuse_context=context
        )
        member = _member("batch.json", documents["batch.json"])
        validations = 0
        original = validate_contract

        def validate(name: str, value: dict[str, Any]) -> None:
            nonlocal validations
            validations += 1
            if validations == 1:
                raise SchemaError("synthetic transient schema validator failure")
            original(name, value)

        monkeypatch.setattr(provenance, "validate_contract", validate)
        with pytest.raises(SchemaError):
            cache.past_exam_provenance.batch(cache.artifacts, member)
        decoded = cache.past_exam_provenance.batch(cache.artifacts, member)
        assert cache.past_exam_provenance.batch(cache.artifacts, member) is decoded
        assert validations == 2 and len(reader.calls) == 1
        with pytest.raises(SchemaError):
            cache.past_exam_provenance.acceptance(cache.artifacts, member)
        assert validations == 3
        assert cache.past_exam_provenance.batch(cache.artifacts, member) is decoded


@pytest.mark.parametrize("changed", ["decision", "coverage", "artifact", "revision", "lineage"])
def test_actual_source_resolver_keeps_current_checks_with_transaction_shared_decoders(
    changed: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session, reader, state = _source_fixture(monkeypatch)
    scope = _scope()
    with Session() as session, session.begin():
        service = object.__new__(KnowledgeRetrievalApplicationService)
        service.artifacts = cast(Any, reader)
        context = service.create_read_only_reuse_context(session, scope)
        cache = service._snapshot_source_resolution_cache(
            session, scope.graph_snapshot.graph_snapshot_revision_id, (), reuse_context=context
        )
        monkeypatch.setattr(session, "get", fake_session.get)
        monkeypatch.setattr(session, "scalars", fake_session.scalars)
        arguments = {
            "artifacts": cache.artifacts,
            "item_revision_id": state["item_revision_id"],
            "source_class": "PAST_EXAM",
            "past_exam_cache": cache.past_exam_provenance,
        }
        first = sources.resolve_historically_approved_item_source(session, **arguments)
        assert sources.resolve_historically_approved_item_source(session, **arguments) == first
        assert len(reader.calls) == 4
        if changed == "decision":
            state["decision"].decision = "REJECT"
        elif changed == "coverage":
            state["acceptance"].coverage_state = "INCOMPLETE"
        elif changed == "artifact":
            state["approved"]["value"] = False
        elif changed == "revision":
            state["revision"].revision_state = "DRAFT"
        else:
            state["unit"].request_sha256 = sha("0")
        with pytest.raises(sources.KnowledgeAnalysisSourceError):
            sources.resolve_historically_approved_item_source(session, **arguments)
        assert len(reader.calls) == 4


def test_direct_helper_also_rejects_foreign_graph_and_expired_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope()
    with Session() as session:
        service, _, _ = _service(monkeypatch, session, scope)
        with session.begin():
            context = service.create_read_only_reuse_context(session, scope)
            with pytest.raises(KnowledgeRetrievalServiceError) as foreign:
                service._snapshot_source_resolution_cache(
                    session, "graphrev_" + "f" * 32, (), reuse_context=context
                )
            assert foreign.value.code == INVALID
        with pytest.raises(KnowledgeRetrievalServiceError) as expired:
            service._snapshot_source_resolution_cache(
                session, scope.graph_snapshot.graph_snapshot_revision_id, (), reuse_context=context
            )
        assert expired.value.code == INVALID
