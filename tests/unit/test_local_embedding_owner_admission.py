"""Real temporary control resolution with explicit synthetic IAM/Catalog source leaves."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_catalog_service.settings import CatalogSettings
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    AuthenticatedSessionFenceError,
    OperatorAuthorizationFenceError,
)
from eom_operator_identity.contracts import PermissionKey
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_workflow.local_embedding_request import LocalEmbeddingWorkflowRequestV11
from eom_workflow_runner import local_embedding_owner_admission as owner_module
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
    ResolvedLocalEmbeddingSources,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    local_embedding_business_fingerprint,
)
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_authenticated_session_fence import PIN, verified_capture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_local_embedding_control_artifacts import NOW


@dataclass
class OwnerFixture:
    owner: CatalogLocalEmbeddingOwnerAdmission
    publisher: ControlFileSetPublisher
    scope: ResolvedLocalEmbeddingAdmission
    current: ResolvedEmbeddingLookup
    deny: bool = False
    deny_after_lookup: bool = False
    calls: list[tuple[str, Session]] = field(default_factory=list)


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OwnerFixture:
    fixture = native_fixture()
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    artifact_owner = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    plan = artifact_owner.publish_source_plan(
        fixture.plan, idempotency_key="synthetic-owner-plan:" + "a" * 32, created_at=NOW
    )
    policy = artifact_owner.publish_policy(
        fixture.policy, idempotency_key="synthetic-owner-policy:" + "a" * 32, created_at=NOW
    )
    _synthetic_identity_rows, capture = verified_capture(monkeypatch)
    request = LocalEmbeddingWorkflowRequestV11.model_validate(
        seal(
            fixture.request.model_dump(mode="json")
            | {
                "actor_context": fixture.request.actor_context.model_dump(mode="json")
                | {
                    "operator_id": capture.operator_id,
                },
                "source_plan": plan.member.model_dump(mode="json"),
                "native_execution_policy": policy.member.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    configuration = LocalEmbeddingOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            fixture.plan.corpus_id,
            fixture.plan.namespace,
            fixture.plan.space,
            fixture.plan.recipe,
            ("PAST_EXAM",),
        ),
        policy.member,
        policy.semantic_sha256,
    )
    owner = CatalogLocalEmbeddingOwnerAdmission(
        publisher.engine,
        configuration,
        capture=capture,
        session_fence=AuthenticatedSessionFence(PIN),
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )
    result = OwnerFixture(
        owner,
        publisher,
        ResolvedLocalEmbeddingAdmission(request, fixture.plan, fixture.policy),
        ResolvedEmbeddingLookup(
            fixture.plan.corpus_id,
            fixture.plan.space,
            fixture.plan.recipe,
            fixture.plan.sources,
            fixture.entries,
        ),
    )

    def authenticated_leaf(
        _self: AuthenticatedSessionFence,
        session: Session,
        actual_capture: AuthenticatedOperatorSession,
        *,
        required_permission: PermissionKey,
    ) -> None:
        # Deliberate unit seam, not a claim of PostgreSQL/installed authentication.
        assert actual_capture is capture
        assert required_permission is PermissionKey.WORKFLOW_START
        assert session.get_transaction() is not None
        result.calls.append(("identity", session))
        if result.deny:
            raise AuthenticatedSessionFenceError("AUTHENTICATED_SESSION_FORBIDDEN")

    def current_source(
        session: Session, caller: EmbeddingRegistryCaller, query: EmbeddingRegistryLookup
    ) -> ResolvedEmbeddingLookup:
        assert caller.operator_id == capture.operator_id
        assert query.graph_snapshot == request.graph_snapshot
        result.calls.append(("catalog", session))
        if result.deny_after_lookup:
            result.deny = True
        return result.current

    def scope_before_bytes(
        session: Session, caller: EmbeddingRegistryCaller, query: EmbeddingRegistryLookup
    ) -> None:
        assert caller.operator_id == capture.operator_id
        assert query.graph_snapshot == request.graph_snapshot
        result.calls.append(("catalog-authorize", session))

    monkeypatch.setattr(AuthenticatedSessionFence, "assert_current", authenticated_leaf)
    monkeypatch.setattr(owner.catalog, "authorize_scope", scope_before_bytes)
    monkeypatch.setattr(owner.catalog, "resolve_lookup", current_source)
    return result


def test_current_operator_and_exact_published_controls_use_same_root(source: OwnerFixture) -> None:
    with source.publisher.sessions() as session, session.begin():
        assert source.owner.resolve_submission(session, source.scope.request) == source.scope
        assert source.calls == [
            ("identity", session),
            ("catalog-authorize", session),
            ("catalog", session),
            ("identity", session),
        ]


@pytest.mark.parametrize("case", ["actor", "session", "policy", "hash", "namespace"])
def test_invalid_admission_is_rejected_before_source_lookup(
    source: OwnerFixture, case: str
) -> None:
    body = source.scope.request.model_dump(mode="json")
    if case == "actor":
        body["actor_context"]["operator_id"] = "operator_" + "f" * 32
    elif case == "session":
        source.deny = True
    elif case == "policy":
        body["native_execution_policy"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif case == "hash":
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    else:
        body["namespace"]["storage_partition"] = "different-partition"
    request = LocalEmbeddingWorkflowRequestV11.model_validate(seal(body, "request_sha256"))
    with source.publisher.sessions() as session, session.begin(), pytest.raises(ValueError):
        source.owner.resolve_submission(session, request)
    assert "catalog" not in [name for name, _session in source.calls]


def test_hash_changed_artifact_fails_not_silently_latest(source: OwnerFixture) -> None:
    pointer = source.scope.request.source_plan
    with source.publisher.sessions() as session:
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        assert revision is not None
        path = Path(revision.nas_path) / pointer.member_path
    # All these bytes are test-owned tmp_path data, never the actual NAS.
    path.write_bytes(b"{}")
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(PinnedArtifactResolutionError),
    ):
        source.owner.resolve_submission(session, source.scope.request)
    assert "catalog" not in [name for name, _session in source.calls]


def test_current_report_removal_makes_saved_plan_stale(source: OwnerFixture) -> None:
    with source.publisher.sessions() as session, session.begin():
        source.owner.resolve_submission(session, source.scope.request)
        source.current = replace(source.current, entries=source.current.entries[:1])
        with pytest.raises(ValueError, match="SOURCE_PLAN_STALE"):
            source.owner.resolve_submission(session, source.scope.request)


def test_late_session_denial_after_source_resolution_is_not_success(source: OwnerFixture) -> None:
    source.deny_after_lookup = True
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(OperatorAuthorizationFenceError, match="FORBIDDEN"),
    ):
        source.owner.resolve_submission(session, source.scope.request)
    assert [name for name, _session in source.calls] == [
        "identity",
        "catalog-authorize",
        "catalog",
        "identity",
    ]


def test_current_read_policy_denies_before_any_control_bytes(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(*_args: Any) -> None:
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")

    monkeypatch.setattr(source.owner.catalog, "authorize_scope", deny)
    monkeypatch.setattr(
        "eom_workflow_runner.local_embedding_owner_admission.PinnedArtifactReadContext",
        lambda *_args: pytest.fail("control bytes read before current source authorization"),
    )
    with (
        source.publisher.sessions() as session,
        session.begin(),
        pytest.raises(EmbeddingRegistryError),
    ):
        source.owner.resolve_submission(session, source.scope.request)


def mutation_rows(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> tuple[Session, WorkflowCommandRecord, WorkflowInstanceRecord, CommandLeaseIdentity]:
    """Attached ORM rows with synthetic query results; real lease/root code is exercised."""
    request = source.scope.request
    session = Session()
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "a" * 32,
        definition_key=request.workflow_definition_key,
        definition_version=request.workflow_definition_version,
        definition_hash=request.workflow_definition_sha256,
    )
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + "a" * 32,
        definition_id=definition.definition_id,
        definition_key=request.workflow_definition_key,
        definition_version=request.workflow_definition_version,
        definition_hash=request.workflow_definition_sha256,
        protocol_version="1.0.1",
        role_schema_version="local-embedding/1.0",
        created_actor_type="human",
        created_actor_id=request.actor_context.operator_id,
        initial_request=request.model_dump(mode="json"),
        request_payload=request.model_dump(mode="json"),
        request_hash=local_embedding_business_fingerprint(
            definition, request, actor_type="human", actor_id=request.actor_context.operator_id
        ),
    )
    lease = CommandLeaseIdentity("wfcommand_" + "b" * 32, "native-runner", "wflease_" + "c" * 32, 1)
    command = WorkflowCommandRecord(
        command_id=lease.command_id,
        workflow_id=workflow.workflow_id,
        state="PROCESSING",
        attempts=1,
        lease_owner=lease.runner_id,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    session.add_all((definition, workflow, command))
    monkeypatch.setattr(
        session, "execute", lambda *_a, **_kw: SimpleNamespace(scalar_one_or_none=lambda: command)
    )
    monkeypatch.setattr(
        session,
        "scalar",
        lambda query, **_kw: (
            workflow
            if query.column_descriptions[0]["entity"] is WorkflowInstanceRecord
            else command
        ),
    )
    monkeypatch.setattr(
        session,
        "get",
        lambda model, *_a, **_kw: definition if model is WorkflowDefinitionRecord else workflow,
    )
    monkeypatch.setattr(
        source.owner, "resolve_sources", lambda *_a: ResolvedLocalEmbeddingSources(source.scope, ())
    )
    return session, command, workflow, lease


def test_only_actual_same_root_processing_transition_can_fence_terminal(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, command, _workflow, lease = mutation_rows(source, monkeypatch)
    try:
        source.owner.fence_mutation(session, source.scope.request, lease)
        command.state = "SUCCEEDED"
        source.owner.fence_mutation(session, source.scope.request, lease)
        session.rollback()
        session.add_all((_workflow, command))
        with pytest.raises(WorkflowError, match="ownership was lost"):
            source.owner.fence_mutation(session, source.scope.request, lease)
    finally:
        session.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_owner", "other"),
        ("lease_token", "wflease_" + "f" * 32),
        ("lease_generation", 2),
        ("state", "CANCELLED"),
    ],
)
def test_mutation_cannot_keep_old_acquisition(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    session, command, _workflow, lease = mutation_rows(source, monkeypatch)
    try:
        source.owner.fence_mutation(session, source.scope.request, lease)
        setattr(command, field, value)
        with pytest.raises(WorkflowError) as failure:
            source.owner.fence_mutation(session, source.scope.request, lease)
        assert failure.value.code is WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT
    finally:
        session.close()


def test_clock_expiry_during_current_source_check_blocks_commit(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, command, _workflow, lease = mutation_rows(source, monkeypatch)

    def expire(*_args: Any) -> ResolvedLocalEmbeddingSources:
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        return ResolvedLocalEmbeddingSources(source.scope, ())

    monkeypatch.setattr(source.owner, "resolve_sources", expire)
    try:
        with pytest.raises(WorkflowError, match="expired during"):
            source.owner.fence_mutation(session, source.scope.request, lease)
    finally:
        session.close()


def test_claim_does_not_reinterpret_expired_previous_execution_as_safe(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, command, workflow, _lease = mutation_rows(source, monkeypatch)
    try:
        with pytest.raises(WorkflowError, match="reconciliation"):
            source.owner.resolve_claim(
                session, command=command, workflow=workflow, request=source.scope.request
            )
        command.state, command.attempts = "PENDING", 0
        assert (
            source.owner.resolve_claim(
                session, command=command, workflow=workflow, request=source.scope.request
            )
            == source.scope
        )
        session.expunge(workflow)
        with pytest.raises(WorkflowError, match="current owner rows"):
            source.owner.resolve_claim(
                session, command=command, workflow=workflow, request=source.scope.request
            )
    finally:
        session.close()


@pytest.mark.parametrize(
    "history", ["valid", "missing", "unallocated", "failed", "bad_step", "denied"]
)
def test_expired_claim_can_only_rejoin_verified_original_context(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch, history: str
) -> None:
    session, command, workflow, _lease = mutation_rows(source, monkeypatch)
    command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    request = source.scope.request
    step = SimpleNamespace(
        step_run_id="steprun_" + "e" * 32,
        state="FAILED" if history == "bad_step" else "RUNNING",
        step_type="application",
        worker_role=None,
        result_schema="incremental-embedding-result@1.0",
        input_pointer_manifest={
            "source_plan": request.source_plan.model_dump(mode="json"),
            "source_plan_sha256": request.source_plan_sha256,
        },
    )
    original_scalar = session.scalar
    monkeypatch.setattr(
        session,
        "scalar",
        lambda query, **kwargs: (
            step
            if query.column_descriptions[0]["entity"] is owner_module.WorkflowStepRunRecord
            else original_scalar(query, **kwargs)
        ),
    )
    original = SimpleNamespace(intent=object())
    read = Mock(return_value=None if history == "missing" else original)
    coordinator = Mock()
    coordinator.return_value.read.return_value = SimpleNamespace(
        state="FAILED" if history == "failed" else "RUNNING",
        records=() if history == "unallocated" else (object(),),
    )
    monkeypatch.setattr(owner_module, "read_native_embedding_launch", read)
    monkeypatch.setattr(owner_module, "NativeEmbeddingCoordinator", coordinator)
    if history == "denied":
        source.deny = True
    try:
        if history == "valid":
            assert (
                source.owner.resolve_claim(
                    session, command=command, workflow=workflow, request=request
                )
                == source.scope
            )
            read.assert_called_once_with(
                session,
                request=request,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
        else:
            with pytest.raises((WorkflowError, OperatorAuthorizationFenceError)):
                source.owner.resolve_claim(
                    session, command=command, workflow=workflow, request=request
                )
        # This is only pre-claim admission, never a rewritten lease/audit/state.
        assert command.attempts == command.lease_generation == 1 and command.state == "PROCESSING"
        if history in {"bad_step", "denied"}:
            read.assert_not_called()
    finally:
        session.close()


def test_mutation_reuses_canonical_request_business_hash_guard(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _command, workflow, lease = mutation_rows(source, monkeypatch)
    workflow.request_hash = "sha256:" + "f" * 64
    try:
        with pytest.raises(ValueError, match="SUBMISSION_REPLAY_INVALID"):
            source.owner.fence_mutation(session, source.scope.request, lease)
    finally:
        session.close()
