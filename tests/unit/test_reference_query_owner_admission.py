"""Temporary real control Artifacts with explicitly synthetic Identity/source/index seams.

No installed QUERY, production authentication, numerical inference or NAS evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
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
from eom_workflow.compiler import compile_definition_data
from eom_workflow.reference_query_execution import (
    ReferenceQueryExecutionPolicy,
    ReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_step_output,
    parse_reference_query_workflow_request,
)
from eom_workflow_runner import reference_query_owner_admission as module
from eom_workflow_runner import reference_query_source_read as read_module
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.reference_query_owner_admission import (
    CatalogReferenceQueryOwnerAdmission,
    ReferenceQueryOwnerConfiguration,
    ResolvedReferenceQuerySources,
    build_reference_query_native_input,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    reference_query_business_fingerprint,
)
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_authenticated_session_fence import PIN, verified_capture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_reference_query_workflow_contracts import definition_body
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
    compiled = compile_definition_data(definition_body(), "synthetic-current-query-owner", set())
    base = case(definition_sha256=compiled.sha256)
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

    def prepare_anchor(session: Session, caller: Any, current: Any) -> PreparedSimilarityContext:
        prepared = prepare(session, caller, current)
        read_module.validate_similarity_preparation(current, prepared)
        read(session, caller, current, prepared)
        return prepared

    monkeypatch.setattr(AuthenticatedSessionFence, "assert_current", identity)
    monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
    monkeypatch.setattr(owner.catalog, "prepare_similarity_context_in_session", prepare)
    monkeypatch.setattr(owner.catalog, "read_similarity_views_in_session", read)
    monkeypatch.setattr(owner.catalog, "prepare_reference_query_anchor_in_session", prepare_anchor)
    return result


def test_native_input_bytes_ignore_unrelated_population_but_retain_exact_anchor(
    source, monkeypatch
):
    from eom_identifiers import canonical_json_bytes
    from eom_workflow_runner.reference_query_source_read import build_reference_query_native_input

    monkeypatch.setattr(
        source.owner.catalog,
        "prepare_and_read_similarity_context_in_session",
        lambda *_a: pytest.fail("native QUERY must not materialize the ranking population"),
    )
    with source.publisher.sessions.begin() as session:
        full = source.owner.resolve_sources(session, source.request)
    prepared = full.prepared
    anchor_id = full.request.context_request.anchor.source.item_revision_id
    anchor = replace(
        full,
        prepared=replace(
            prepared,
            sources=tuple(
                value for value in prepared.sources if value.source.item_revision_id == anchor_id
            ),
            graph_scores=(),
            graph_evidence=None,
            truncated=False,
        ),
    )
    assert len(anchor.prepared.sources) == 1 < len(full.prepared.sources)
    identifiers = {"job_id": "job_" + "e" * 32, "query_request_id": "embeddingquery_" + "e" * 32}
    original = build_reference_query_native_input(full, **identifiers)
    narrowed = build_reference_query_native_input(anchor, **identifiers)
    assert canonical_json_bytes(narrowed.model_dump(mode="json")) == canonical_json_bytes(
        original.model_dump(mode="json")
    )
    assert narrowed.request_sha256 == original.request_sha256


def mutation_rows(
    source: OwnerFixture, monkeypatch: pytest.MonkeyPatch
) -> tuple[Session, WorkflowCommandRecord, WorkflowInstanceRecord, CommandLeaseIdentity]:
    """Actual attached ORM/root/lease code, with explicitly synthetic SQL/source seams."""
    with source.publisher.sessions() as root, root.begin():
        sources = source.owner.resolve_sources(root, source.request)
    compiled = compile_definition_data(definition_body(), "synthetic-current-query-owner", set())
    session = Session()
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "a" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        definition_hash=compiled.sha256,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        source_path=compiled.source_path,
    )
    request = source.request
    actor = request.operator_audit.operator_id
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + "a" * 32,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        protocol_version="1.0.1",
        role_schema_version="reference-query/1.0",
        created_actor_type="human",
        created_actor_id=actor,
        initial_request=request.model_dump(mode="json"),
        request_payload=request.model_dump(mode="json"),
        request_hash=reference_query_business_fingerprint(
            definition, request, actor_type="human", actor_id=actor
        ),
    )
    lease = CommandLeaseIdentity("wfcommand_" + "b" * 32, "query-owner", "wflease_" + "c" * 32, 1)
    command = WorkflowCommandRecord(
        command_id=lease.command_id,
        workflow_id=workflow.workflow_id,
        state="PROCESSING",
        attempts=1,
        lease_owner=lease.runner_id,
        lease_token=lease.lease_token,
        lease_generation=1,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    session.add_all((definition, workflow, command))
    monkeypatch.setattr(
        session, "execute", lambda *_a, **_kw: SimpleNamespace(scalar_one_or_none=lambda: command)
    )

    def scalar(query: Any, **_kw: Any) -> Any:
        entity = query.column_descriptions[0]["entity"]
        if entity is WorkflowStepRunRecord:
            return None
        return workflow if entity is WorkflowInstanceRecord else command

    monkeypatch.setattr(session, "scalar", scalar)
    monkeypatch.setattr(
        session,
        "get",
        lambda model, *_a, **_kw: definition if model is WorkflowDefinitionRecord else workflow,
    )
    monkeypatch.setattr(source.owner, "resolve_sources", lambda *_a: sources)
    return session, command, workflow, lease


def test_query_current_owner_only_allows_terminal_transition_inside_acquired_root(
    source: OwnerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, command, workflow, lease = mutation_rows(source, monkeypatch)
    try:
        source.owner.fence_mutation(session, source.request, lease)
        command.state = "SUCCEEDED"
        source.owner.fence_mutation(session, source.request, lease)
        session.rollback()
        session.add_all((workflow, command))
        with pytest.raises(WorkflowError, match="ownership was lost"):
            source.owner.fence_mutation(session, source.request, lease)
    finally:
        session.close()


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "workflow",
        "step_workflow",
        "key",
        "attempt",
        "state",
        "role",
        "result",
        "input",
    ),
)
def test_execution_source_fence_requires_exact_current_step(source, monkeypatch, fault):
    session, _command, workflow, lease = mutation_rows(source, monkeypatch)
    workflow.state = "RUNNING"
    step = WorkflowStepRunRecord(
        step_run_id="steprun_" + "d" * 32,
        workflow_id=workflow.workflow_id,
        step_key="encode_reference_query",
        step_type="application",
        worker_role=None,
        attempt=1,
        state="RUNNING",
        result_schema="embedding-reference-query-result@1.0",
        input_pointer_manifest={"workflow_request_sha256": source.request.request_sha256},
    )
    original_get = session.get
    monkeypatch.setattr(
        session,
        "get",
        lambda model, *a, **kw: (
            step if model is WorkflowStepRunRecord else original_get(model, *a, **kw)
        ),
    )
    if fault == "workflow":
        workflow.state = "CANCELLED"
    if fault == "step_workflow":
        step.workflow_id = "workflow_" + "f" * 32
    if fault == "key":
        step.step_key = "encode_batch"
    if fault == "attempt":
        step.attempt = 2
    if fault == "state":
        step.state = "FAILED"
    if fault == "role":
        step.worker_role = "authoring"
    if fault == "result":
        step.result_schema = "incremental-embedding-result@1.0"
    if fault == "input":
        step.input_pointer_manifest = {"changed": True}
    try:
        if fault:
            with pytest.raises(ValueError, match="CURRENT_STEP_INVALID"):
                source.owner.resolve_execution_sources(
                    session,
                    source.request,
                    lease,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                )
        else:
            assert (
                source.owner.resolve_execution_sources(
                    session,
                    source.request,
                    lease,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                ).request
                == source.request
            )
    finally:
        session.close()


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "caller",
        "workflow_missing",
        "definition_missing",
        "definition_hash",
        "workflow_running",
        "workflow_stage",
        "workflow_key",
        "step_missing",
        "step_role",
        "step_result",
        "step_attempt",
        "step_input",
        "step_output",
        "step_failed",
        "step_error",
        "step_superseded",
        "producer",
        "final_pointer",
        "terminal_missing",
        "terminal_attempt",
        "terminal_state",
    ),
)
@pytest.mark.parametrize("owner_kind", ("native", "read_only"))
def test_completed_query_read_requires_exact_terminal_history_not_an_execution_lease(
    source, monkeypatch, fault, owner_kind
):
    session, command, workflow, _lease = mutation_rows(source, monkeypatch)
    owner = source.owner
    if owner_kind == "read_only":
        owner = read_module.CatalogReferenceQueryReadOwner(
            source.publisher.engine,
            source.owner.configuration,
            identity_fence=source.owner.identity,
            settings=source.owner.settings,
        )
        # Keep the existing explicitly synthetic source-resolution seam; terminal
        # row/attempt/producer checks run through the real shared implementation.
        monkeypatch.setattr(owner, "resolve_sources", source.owner.resolve_sources)
    output = parse_reference_query_step_output(
        seal(
            case().output.model_dump(mode="json") | {"workflow_id": workflow.workflow_id},
            "output_sha256",
        )
    )
    step = WorkflowStepRunRecord(
        step_run_id=output.step_run_id,
        workflow_id=workflow.workflow_id,
        step_key="encode_reference_query",
        step_type="application",
        worker_role=None,
        result_schema="embedding-reference-query-result@1.0",
        attempt=1,
        state="SUCCEEDED",
        platform_job_id=output.receipt_owner_job_id,
        input_pointer_manifest={"workflow_request_sha256": source.request.request_sha256},
        output_pointer_manifest=output.model_dump(mode="json"),
    )
    terminal = WorkflowStepRunRecord(
        step_run_id="steprun_" + "e" * 32,
        workflow_id=workflow.workflow_id,
        step_key="complete",
        step_type="terminal",
        attempt=1,
        state="SUCCEEDED",
        input_pointer_manifest={},
    )
    session.add_all((step, terminal))
    workflow.state = workflow.stage = "COMPLETED"
    workflow.current_step_key = "complete"
    workflow.runtime_context = {
        "final_pointer_manifest": {"reference_query_receipt": output.model_dump(mode="json")}
    }
    # A completed read must not acquire or revive this historical command.
    command.state = "COMPLETED"
    command.lease_owner = command.lease_token = command.lease_expires_at = None
    caller = EmbeddingRegistryCaller(source.request.operator_audit.operator_id)
    original_get = session.get

    def get(model, *args, **kwargs):
        if fault == "workflow_missing" and model is WorkflowInstanceRecord:
            return None
        if fault == "definition_missing" and model is WorkflowDefinitionRecord:
            return None
        return original_get(model, *args, **kwargs)

    def scalar(query, **_kwargs):
        entity = query.column_descriptions[0]["entity"]
        if entity is WorkflowInstanceRecord:
            return workflow
        assert entity is WorkflowStepRunRecord
        key = query.compile().params["step_key_1"]
        if key == "complete":
            return None if fault == "terminal_missing" else terminal
        return None if fault == "step_missing" else step

    monkeypatch.setattr(session, "get", get)
    monkeypatch.setattr(session, "scalar", scalar)
    if fault == "caller":
        caller = EmbeddingRegistryCaller("operator_" + "0" * 32)
    elif fault == "definition_hash":
        workflow.definition_hash = "sha256:" + "0" * 64
    elif fault == "workflow_running":
        workflow.state = "RUNNING"
    elif fault == "workflow_stage":
        workflow.stage = "LOCAL_EMBEDDING"
    elif fault == "workflow_key":
        workflow.current_step_key = "encode_reference_query"
    elif fault == "step_role":
        step.worker_role = "review"
    elif fault == "step_result":
        step.result_schema = "incremental-embedding-result@1.0"
    elif fault == "step_attempt":
        step.attempt = 2
    elif fault == "step_input":
        step.input_pointer_manifest = {}
    elif fault == "step_output":
        step.output_pointer_manifest = None
    elif fault == "step_failed":
        step.state = "FAILED"
    elif fault == "step_error":
        step.error_code = "synthetic failure"
    elif fault == "step_superseded":
        step.superseded_by_step_run_id = terminal.step_run_id
    elif fault == "producer":
        step.platform_job_id = "job_" + "0" * 32
    elif fault == "final_pointer":
        workflow.runtime_context = {}
    elif fault == "terminal_attempt":
        terminal.attempt = 2
    elif fault == "terminal_state":
        terminal.state = "RUNNING"
    try:
        if fault:
            with pytest.raises((ValueError, WorkflowError)):
                owner.resolve_completed_sources(
                    session, caller, source.request, workflow_id=workflow.workflow_id
                )
        else:
            current = owner.resolve_completed_sources(
                session, caller, source.request, workflow_id=workflow.workflow_id
            )
            assert current.sources.request == source.request and current.output == output
            assert current.workflow is workflow and current.step is step
            assert command.state == "COMPLETED" and command.lease_token is None
    finally:
        session.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_owner", "other"),
        ("lease_token", "other"),
        ("lease_generation", 2),
        ("state", "CANCELLED"),
    ],
)
def test_query_current_owner_rejects_changed_acquisition(
    source: OwnerFixture,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    session, command, _workflow, lease = mutation_rows(source, monkeypatch)
    try:
        source.owner.fence_mutation(session, source.request, lease)
        setattr(command, field, value)
        with pytest.raises(WorkflowError):
            source.owner.fence_mutation(session, source.request, lease)
    finally:
        session.close()


def test_query_expiry_during_source_resolution_blocks_the_root_commit(
    source: OwnerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, command, _workflow, lease = mutation_rows(source, monkeypatch)
    original = source.owner.resolve_sources

    def expire(*args: Any) -> ResolvedReferenceQuerySources:
        result = original(*args)
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        return result

    monkeypatch.setattr(source.owner, "resolve_sources", expire)
    try:
        with pytest.raises(WorkflowError, match="expired during"):
            source.owner.fence_mutation(session, source.request, lease)
    finally:
        session.close()


def test_query_claim_accepts_only_fresh_pending_and_never_assumes_expiry_means_no_execution(
    source: OwnerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, command, workflow, _lease = mutation_rows(source, monkeypatch)
    try:
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        with pytest.raises(WorkflowError, match="reconciliation"):
            source.owner.resolve_claim(
                session, command=command, workflow=workflow, request=source.request
            )
        command.state, command.attempts, command.lease_generation = "PENDING", 0, 0
        command.lease_owner = command.lease_token = command.lease_expires_at = None
        assert (
            source.owner.resolve_claim(
                session, command=command, workflow=workflow, request=source.request
            ).request
            == source.request
        )
        session.expunge(command)
        with pytest.raises(WorkflowError, match="attached"):
            source.owner.resolve_claim(
                session, command=command, workflow=workflow, request=source.request
            )
    finally:
        session.close()


@pytest.mark.parametrize("state", ("READY", "RUNNING", "FAILED", "CANCELLED"))
def test_fresh_command_cannot_bypass_an_existing_query_attempt(
    source: OwnerFixture,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    session, command, workflow, _lease = mutation_rows(source, monkeypatch)
    command.state, command.attempts, command.lease_generation = "PENDING", 0, 0
    command.lease_owner = command.lease_token = command.lease_expires_at = None
    step = WorkflowStepRunRecord(state=state)
    monkeypatch.setattr(module, "native_application_step", lambda *_args: step)
    try:
        with pytest.raises(WorkflowError, match="prior attempt"):
            source.owner.resolve_claim(
                session, command=command, workflow=workflow, request=source.request
            )
        assert command.lease_generation == 0
    finally:
        session.close()


@pytest.mark.parametrize("kind", ("fresh_poll", "expired_processing", "expired_leased"))
@pytest.mark.parametrize(
    "fault", (None, "missing_launch", "unallocated", "failed", "step", "live_lease")
)
def test_recovery_requires_current_scope_and_original_allocated_history(
    source, monkeypatch, kind, fault
):
    from eom_orchestrator.native_reference_query_coordinator import NativeReferenceQueryHistory
    from eom_workflow.native_reference_query_coordinator import (
        NativeQueryAllocation,
        native_reference_query_checkpoint,
    )
    from eom_workflow.reference_query_execution import parse_reference_query_launch_association

    session, command, workflow, _lease = mutation_rows(source, monkeypatch)
    if kind == "fresh_poll":
        command.state, command.attempts, command.lease_generation = "PENDING", 0, 0
        command.lease_owner = command.lease_token = command.lease_expires_at = None
        if fault == "live_lease":
            command.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
    else:
        command.state = "LEASED" if kind == "expired_leased" else "PROCESSING"
        command.lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=60 if fault == "live_lease" else -1
        )
    step = WorkflowStepRunRecord(
        step_run_id="steprun_" + "d" * 32,
        workflow_id=workflow.workflow_id,
        step_key="encode_reference_query",
        step_type="application",
        worker_role=None,
        attempt=1,
        state="RUNNING",
        result_schema="embedding-reference-query-result@1.0",
        input_pointer_manifest={"workflow_request_sha256": source.request.request_sha256},
    )
    if fault == "step":
        step.attempt = 2
    monkeypatch.setattr(module, "native_application_step", lambda *_: step)
    original = case().launch.model_dump(mode="json")
    original.update(
        workflow_id=workflow.workflow_id,
        step_run_id=step.step_run_id,
        workflow_request_sha256=source.request.request_sha256,
        context_request_sha256=source.request.context_request.request_sha256,
        runtime_bundle=source.request.runtime_bundle.model_dump(mode="json"),
        resource_profile_sha256=source.request.resource_profile.resource_profile_sha256,
    )
    launch = parse_reference_query_launch_association(seal(original, "association_sha256"))
    allocation = NativeQueryAllocation.model_validate(
        {
            "query_producer": {
                "job_id": "job_" + "b" * 32,
                "artifact_id": "artifact_" + "b" * 32,
                "artifact_revision_id": "rev_" + "b" * 32,
            },
            "receipt_producer": {
                "job_id": "job_" + "c" * 32,
                "artifact_id": "artifact_" + "c" * 32,
                "artifact_revision_id": "rev_" + "c" * 32,
            },
            "created_at": datetime.now(UTC),
            "source_commit": "a" * 40,
        }
    )
    records = (
        ()
        if fault == "unallocated"
        else (native_reference_query_checkpoint(launch, "ALLOCATION", allocation),)
    )
    history = NativeReferenceQueryHistory(
        "FAILED" if fault == "failed" else "RUNNING", launch, records
    )
    monkeypatch.setattr(
        module,
        "read_native_reference_query_launch",
        lambda *_a, **_kw: None if fault == "missing_launch" else launch,
    )
    monkeypatch.setattr(
        module,
        "NativeReferenceQueryCoordinator",
        lambda *_: SimpleNamespace(read=lambda _: history),
    )
    try:
        if fault:
            with pytest.raises(WorkflowError):
                source.owner.resolve_claim(
                    session, command=command, workflow=workflow, request=source.request
                )
        else:
            assert (
                source.owner.resolve_claim(
                    session, command=command, workflow=workflow, request=source.request
                ).request
                == source.request
            )
        assert command.lease_generation == (0 if kind == "fresh_poll" else 1)
    finally:
        session.close()


def test_source_preparation_keeps_one_root_and_actual_capture_then_checks_late(
    source: OwnerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source.owner.catalog,
        "prepare_similarity_context_in_session",
        Mock(side_effect=AssertionError("redundant source preparation")),
    )
    monkeypatch.setattr(
        source.owner.catalog,
        "read_similarity_views_in_session",
        Mock(side_effect=AssertionError("separate index-read root")),
    )
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
        read_module, "PinnedArtifactReadContext", lambda *_args: pytest.fail("read before Identity")
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
        read_module, "PinnedArtifactReadContext", lambda *_args: pytest.fail("read before scope")
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
