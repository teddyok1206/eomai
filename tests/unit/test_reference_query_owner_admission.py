"""Temporary real control Artifacts with explicitly synthetic Identity/source/index seams.

No installed QUERY, production authentication, numerical inference or NAS evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilarityContext,
    SimilarityContextReadError,
)
from eom_identity_service import (
    AuthenticatedSessionFence,
    AuthenticatedSessionFenceError,
    OperatorAuthorizationFenceError,
)
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.embedding_runtime_bundle_artifacts import (
    EmbeddingRuntimeBundleArtifactPublisher,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryExecutionPolicy,
    ReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_workflow_request,
)
from eom_workflow_runner import reference_query_owner_admission as module
from eom_workflow_runner.reference_query_owner_admission import (
    CatalogReferenceQueryOwnerAdmission,
    ReferenceQueryOwnerConfiguration,
    ResolvedReferenceQuerySources,
    build_reference_query_native_input,
)
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_authenticated_session_fence import PIN, verified_capture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_similarity_context_service import case as context_case


@dataclass
class OwnerFixture:
    owner: CatalogReferenceQueryOwnerAdmission
    publisher: ControlFileSetPublisher
    request: ReferenceQueryWorkflowRequest
    policy: ReferenceQueryExecutionPolicy
    prepared: PreparedSimilarityContext
    deny: bool = False
    deny_at_end: bool = False
    calls: list[tuple[str, Session]] = field(default_factory=list)


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OwnerFixture:
    base = case()
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    saved_bundle = EmbeddingRuntimeBundleArtifactPublisher(
        ControlArtifactPublisher(publisher.engine, publisher.settings), source_commit="a" * 40
    ).publish(base.bundle, created_at=NOW)
    policy = parse_reference_query_execution_policy(
        seal(
            base.policy.model_dump(mode="json")
            | {"runtime_bundle": saved_bundle.bundle.model_dump(mode="json")},
            "policy_sha256",
        )
    )
    saved_policy = LocalEmbeddingControlArtifactPublisher(
        publisher, source_commit="a" * 40
    ).publish_reference_query_policy(
        policy, idempotency_key="synthetic-query-policy:" + "b" * 32, created_at=NOW
    )
    _rows, capture = verified_capture(monkeypatch)
    request = parse_reference_query_workflow_request(
        seal(
            base.request.model_dump(mode="json")
            | {
                "native_execution_policy": saved_policy.member.model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
                "runtime_bundle": saved_bundle.bundle.model_dump(mode="json"),
                "operator_audit": base.request.operator_audit.model_dump(mode="json")
                | {"operator_id": capture.operator_id},
            },
            "request_sha256",
        )
    )
    context = request.context_request
    first_index = context.views[0].index
    assert first_index is not None
    namespace = EmbeddingIndexNamespace(
        storage_partition=first_index.storage_partition,
        space_sha256=policy.spaces.document.space_sha256,
        view=context.views[0].view,
        recipe_sha256=context.views[0].recipe.recipe_sha256,
        population_scope="OCCURRENCE_BACKED_PAST_EXAM",
    )
    config = ReferenceQueryOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            "corpus_" + "1" * 32,
            namespace,
            policy.spaces.document,
            context.views[0].recipe,
            ("PAST_EXAM",),
        ),
        saved_policy.member,
        policy.policy_sha256,
        saved_bundle.bundle,
    )
    owner = CatalogReferenceQueryOwnerAdmission(
        publisher.engine,
        config,
        capture=capture,
        session_fence=AuthenticatedSessionFence(PIN),
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )
    _context, sources, _query = context_case()
    selected_views = {selection.view for selection in context.views}
    prepared = replace(
        sources.prepared,
        request_sha256=context.request_sha256,
        query_texts=tuple(
            (view, text) for view, text in sources.prepared.query_texts if view in selected_views
        ),
    )
    result = OwnerFixture(owner, publisher, request, policy, prepared)

    def identity(_self: Any, session: Session, actual: Any, *, required_permission: Any) -> None:
        assert actual is capture and required_permission is PermissionKey.WORKFLOW_START
        assert session.get_transaction() is not None
        result.calls.append(("identity", session))
        if result.deny:
            raise AuthenticatedSessionFenceError("AUTHENTICATED_SESSION_FORBIDDEN")

    def authorize(session: Session, caller: Any, query: Any) -> None:
        assert caller.operator_id == capture.operator_id
        assert query.graph_snapshot == context.graph_snapshot
        result.calls.append(("scope", session))

    def prepare(session: Session, caller: Any, current: Any) -> PreparedSimilarityContext:
        assert caller.operator_id == capture.operator_id and current == context
        result.calls.append(("prepare", session))
        return result.prepared

    def read(session: Session, caller: Any, current: Any, prepared: Any) -> tuple[Any, ...]:
        assert caller.operator_id == capture.operator_id and current == context
        assert prepared == result.prepared
        result.calls.append(("read-indexes", session))
        if result.deny_at_end:
            result.deny = True
        return ()  # Explicit unit index-validation seam, NOT a real registered index.

    monkeypatch.setattr(AuthenticatedSessionFence, "assert_current", identity)
    monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
    monkeypatch.setattr(owner.catalog, "prepare_similarity_context_in_session", prepare)
    monkeypatch.setattr(owner.catalog, "read_similarity_views_in_session", read)
    return result


def test_source_preparation_keeps_one_root_and_actual_capture_then_checks_late(
    source: OwnerFixture,
) -> None:
    with source.publisher.sessions() as session, session.begin():
        result = source.owner.resolve_sources(session, source.request)
        assert result.policy == source.policy and result.prepared == source.prepared
        assert all(captured is session for _name, captured in source.calls)
    assert [name for name, _session in source.calls] == [
        "identity",
        "scope",
        "prepare",
        "read-indexes",
        "identity",
    ]


@pytest.mark.parametrize("actor", (False, True))
def test_stale_or_substituted_actor_denies_before_any_control_read(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch, actor: bool
) -> None:
    source.deny = not actor
    request = source.request
    if actor:
        request = parse_reference_query_workflow_request(
            seal(
                request.model_dump(mode="json")
                | {
                    "operator_audit": request.operator_audit.model_dump(mode="json")
                    | {"operator_id": "operator_" + "f" * 32}
                },
                "request_sha256",
            )
        )
    monkeypatch.setattr(
        module, "PinnedArtifactReadContext", lambda *_args: pytest.fail("read before Identity")
    )
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(OperatorAuthorizationFenceError),
    ):
        source.owner.resolve_sources(session, request)


def test_current_scope_denial_precedes_control_bytes(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(*_args: Any) -> None:
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")

    monkeypatch.setattr(source.owner.catalog, "authorize_scope", deny)
    monkeypatch.setattr(
        module, "PinnedArtifactReadContext", lambda *_args: pytest.fail("read before scope")
    )
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(EmbeddingRegistryError),
    ):
        source.owner.resolve_sources(session, source.request)


def test_late_session_denial_after_index_read_does_not_return_sources(source: OwnerFixture) -> None:
    source.deny_at_end = True
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(OperatorAuthorizationFenceError),
    ):
        source.owner.resolve_sources(session, source.request)
    assert [name for name, _session in source.calls][-2:] == ["read-indexes", "identity"]


def test_corrupt_control_bytes_fail_before_source_materialization(source: OwnerFixture) -> None:
    pointer = source.owner.configuration.native_execution_policy
    path = (
        source.publisher.settings.nas_artifact_root
        / pointer.artifact_id
        / pointer.artifact_revision_id
        / "policy.json"
    )
    path.write_bytes(b"not the published control")
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(PinnedArtifactResolutionError),
    ):
        source.owner.resolve_sources(session, source.request)
    assert [name for name, _session in source.calls] == ["identity", "scope"]


def test_stale_anchor_profile_or_report_never_becomes_a_native_query(source: OwnerFixture) -> None:
    source.prepared = replace(source.prepared, sources=source.prepared.sources[1:])
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(SimilarityContextReadError),
    ):
        source.owner.resolve_sources(session, source.request)
    assert "read-indexes" not in [name for name, _session in source.calls]


def test_resolved_values_do_not_serialize_away_forged_bundle_fields(source: OwnerFixture) -> None:
    with source.publisher.sessions() as session, session.begin():
        result = source.owner.resolve_sources(session, source.request)
    with pytest.raises(ValueError):
        replace(result, bundle=result.bundle.model_copy(update={"authority": "ADMIN"}))


def test_exact_native_rows_use_query_purpose_and_configured_batch_not_row_count(
    source: OwnerFixture,
) -> None:
    with source.publisher.sessions() as session, session.begin():
        resolved = source.owner.resolve_sources(session, source.request)
    context = source.request.context_request.model_dump(mode="json")
    context["views"] = context["views"][:1]
    request = parse_reference_query_workflow_request(
        seal(
            source.request.model_dump(mode="json")
            | {"context_request": seal(context, "request_sha256")},
            "request_sha256",
        )
    )
    selected = {selection.view for selection in request.context_request.views}
    prepared = replace(
        source.prepared,
        request_sha256=request.context_request.request_sha256,
        query_texts=tuple(
            (view, text) for view, text in source.prepared.query_texts if view in selected
        ),
    )
    bounded = ResolvedReferenceQuerySources(request, resolved.policy, resolved.bundle, prepared)
    first = build_reference_query_native_input(
        bounded, job_id="job_" + "1" * 32, query_request_id="embeddingquery_" + "2" * 32
    )
    assert first.batch_size == 4 and len(first.rows) == 1
    assert first.spaces.query.purpose == "QUERY" and first.spaces.document.purpose == "DOCUMENT"
    assert {row.view: row.text for row in first.rows} == dict(prepared.query_texts)
    assert first == build_reference_query_native_input(
        bounded, job_id=first.job_id, query_request_id=first.query_request_id
    )
    assert "operator_id" not in first.model_dump(mode="json")
