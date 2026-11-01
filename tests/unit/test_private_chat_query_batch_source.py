"""Actual private control/Chat reads; command/launch ports are explicit test doubles.

These checks neither prove PG locks nor activate private GPU execution.
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_work_batch import PrivateChatWorkBatchInput
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryHistory
from eom_workflow.embedding_batch_plan import EmbeddingBatchChildBinding
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    native_private_chat_public_query_checkpoint,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow_runner import embedding_batch_source_authorization as module
from eom_workflow_runner.local_embedding_publications import new_native_artifact_producer
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_source_read import (
    build_private_chat_public_query_native_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed


def private_batch_for(native, request):
    scope = seal(
        dict(
            actor_kind="OPERATOR",
            actor_id=request.operator_audit.operator_id,
            storage_partition=native.rows[0].encoding.storage_partition,
            access_policy_sha256=request.context_request.policy_sha256,
        ),
        "scope_sha256",
    )
    return PrivateChatWorkBatchInput.model_validate(
        seal(
            dict(
                schema_version="embedding-work-batch-input/3.0",
                purpose="PRIVATE_CHAT_QUERY",
                scope=scope,
                routing_decision_sha256="sha256:" + "d" * 64,
                resource_profile_sha256=request.resource_profile.resource_profile_sha256,
                timeout_seconds=min(request.resource_profile.timeout_seconds, 180),
                vector_max_bytes=16 * 1024**2,
                children=[
                    dict(scope_sha256=scope["scope_sha256"], request=native.model_dump(mode="json"))
                ],
            ),
            "request_sha256",
        )
    )


def private_launch_for(request, native, template):
    return PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            template.model_dump(mode="json")
            | dict(
                workflow_request_sha256=request.request_sha256,
                context_request_sha256=request.context_request.request_sha256,
                basis_sha256=request.context_request.query_basis.basis_sha256,
                native_launch_job_id=native.job_id,
                query_request_id=native.query_request_id,
                query_request_sha256=native.request_sha256,
                query_input_set_sha256=native.input_set_sha256,
                recipe_sha256=native.recipe.recipe_sha256,
                runtime_bundle=request.runtime_bundle.model_dump(mode="json"),
                resource_profile_sha256=request.resource_profile.resource_profile_sha256,
            ),
            "association_sha256",
        )
    )


def private_binding(value):
    launch = value.launch
    return EmbeddingBatchChildBinding(
        selection_sha256="sha256:" + "c" * 64,
        workflow_id=launch.workflow_id,
        step_run_id=launch.step_run_id,
        native_job_id=launch.native_launch_job_id,
        workflow_request_sha256=value.request.request_sha256,
        native_input_sha256=launch.query_request_sha256,
        launch_association_sha256=launch.association_sha256,
    )


@pytest.fixture
def private(tmp_path, monkeypatch, public_completed):
    current = make_private_public_source_case(tmp_path, monkeypatch)
    owner = CatalogPrivateChatQueryOwnerAdmission(current.owner)
    roots, leases, calls = [], [], []
    state = SimpleNamespace(deny_lease=False)

    @contextmanager
    def transaction():
        with current.old.publisher.sessions.begin() as session:
            current.old.fault.session = session
            roots.append("open")
            try:
                yield session
            finally:
                roots.append("close")

    with transaction() as session:
        resolved = current.owner.resolve_sources(
            session, current.request, current.old.projection.origin
        )
    native = build_private_chat_public_query_native_input(
        resolved,
        job_id=public_completed.launch.native_launch_job_id,
        query_request_id=public_completed.launch.query_request_id,
    )
    launch = private_launch_for(current.request, native, public_completed.launch)
    lease = CommandLeaseIdentity(launch.original_command_id, "private-batch-test", "lease", 1)

    def resolve(session, request, actual_lease, **kwargs):
        assert request == current.request and actual_lease == lease
        assert kwargs == dict(workflow_id=launch.workflow_id, step_run_id=launch.step_run_id)
        calls.append("private-owner")
        return current.owner.resolve_sources(session, request, current.old.projection.origin)

    def late(session, actual_lease):
        assert session is current.old.fault.session and actual_lease == lease
        leases.append(actual_lease)
        if state.deny_lease:
            raise ValueError("SYNTHETIC_PRIVATE_LEASE_EXPIRED")

    state.saved_launch = launch
    allocation = NativePrivateQueryAllocation(
        allocation=NativeQueryAllocation(
            query_producer=new_native_artifact_producer(),
            receipt_producer=new_native_artifact_producer(),
            created_at=datetime.now(UTC),
            source_commit="a" * 40,
        ),
        origin=current.old.projection.origin,
    )
    state.history = NativePrivateChatQueryHistory(
        "RUNNING",
        launch,
        (native_private_chat_public_query_checkpoint(launch, "ALLOCATION", allocation),),
    )

    def history(coordinator, session):
        assert coordinator.request == current.request and coordinator.launch == launch
        assert session is current.old.fault.session
        return state.history

    monkeypatch.setattr(owner, "resolve_execution_sources", resolve)
    monkeypatch.setattr(module.NativePrivateChatQueryCoordinator, "read", history)
    monkeypatch.setattr(
        module, "read_native_query_launch", lambda *_args, **_kwargs: state.saved_launch
    )
    monkeypatch.setattr(module, "require_command_lease", late)
    source = module.PrivateChatQueryBatchSource(owner, current.request, launch, lease, transaction)
    batch = private_batch_for(native, current.request)
    fence = module.CatalogEmbeddingBatchSourceAuthorization(batch, (source,))
    roots.clear()
    current.old.events.clear()
    return SimpleNamespace(
        current=current,
        owner=owner,
        request=current.request,
        launch=launch,
        native=native,
        lease=lease,
        source=source,
        batch=batch,
        fence=fence,
        roots=roots,
        leases=leases,
        calls=calls,
        state=state,
        transaction=transaction,
    )


def test_private_batch_rechecks_existing_private_owner_without_jobs_or_retained_authority(private):
    publisher = private.current.old.publisher
    with publisher.sessions() as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (JobRecord, ArtifactRevisionRecord)
        )
    for _ in range(2):
        private.fence.authorize_batch()
    private.fence.authorize_binding(private_binding(private))
    assert private.calls == ["private-owner"] * 3
    assert private.roots == ["open", "close"] * 3 and private.leases == [private.lease] * 3
    assert private.current.old.events.count("materialize") == 3
    assert private.current.old.events.count("authorize") == 3
    with publisher.sessions() as session:
        after = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (JobRecord, ArtifactRevisionRecord)
        )
    assert before == after and TEXT not in repr(private.source)


@pytest.mark.parametrize(
    "fault",
    (
        "identity",
        "chat",
        "claim",
        "origin",
        "text",
        "public",
        "index",
        "public_during_private_auth",
    ),
)
def test_private_batch_cannot_cache_private_or_public_permission(private, fault):
    private.fence.authorize_batch()
    private.current.old.events.clear()
    private.current.old.fault.value = fault
    with pytest.raises((ValueError, RuntimeError)) as error:
        private.fence.authorize_batch()
    assert TEXT not in str(error.value)
    assert len(private.leases) == 1


@pytest.mark.parametrize("fault", ("actor", "policy", "resources"))
def test_private_batch_scope_is_checked_before_source_rpc(private, fault):
    body = private.batch.model_dump(mode="json")
    if fault == "resources":
        body["resource_profile_sha256"] = "sha256:" + "f" * 64
    else:
        field = "actor_id" if fault == "actor" else "access_policy_sha256"
        body["scope"] = seal(
            body["scope"]
            | {field: "operator_" + "f" * 32 if fault == "actor" else "sha256:" + "f" * 64},
            "scope_sha256",
        )
        body["children"][0]["scope_sha256"] = body["scope"]["scope_sha256"]
    batch = PrivateChatWorkBatchInput.model_validate(seal(body, "request_sha256"))
    fence = module.CatalogEmbeddingBatchSourceAuthorization(batch, (private.source,))
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_SOURCE_AUTHORIZATION_INVALID"):
        fence.authorize_batch()
    assert not private.calls and not private.roots


@pytest.mark.parametrize("missing", (False, True))
def test_private_original_launch_cannot_be_changed_or_replaced_by_a_new_execution(private, missing):
    private.state.saved_launch = (
        None
        if missing
        else PrivateChatQueryLaunchAssociation.model_validate(
            seal(
                private.launch.model_dump(mode="json")
                | {"original_command_id": "wfcmd_" + "f" * 32},
                "association_sha256",
            )
        )
    )
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_SOURCE_AUTHORIZATION_INVALID"):
        private.fence.authorize_batch()
    assert not private.leases


def test_private_late_lease_revocation_is_not_cached_by_a_previous_success(private):
    private.fence.authorize_batch()
    private.state.deny_lease = True
    with pytest.raises(ValueError, match="SYNTHETIC_PRIVATE_LEASE_EXPIRED"):
        private.fence.authorize_batch()
    assert private.calls == ["private-owner"] * 2


@pytest.mark.parametrize(
    "field",
    (
        "workflow_request_sha256",
        "basis_sha256",
        "context_request_sha256",
        "resource_profile_sha256",
    ),
)
def test_private_source_revalidates_constructed_launch_before_opening_any_root(private, field):
    changed = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            private.launch.model_dump(mode="json") | {field: "sha256:" + "f" * 64},
            "association_sha256",
        )
    )
    with pytest.raises(ValueError):
        module.PrivateChatQueryBatchSource(
            private.owner, private.request, changed, private.lease, private.transaction
        )
    assert not private.calls and not private.roots


def test_private_binding_mismatch_never_looks_up_another_workflow(private):
    wrong = private_binding(private).model_copy(update={"workflow_id": "workflow_" + "f" * 32})
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_SOURCE_AUTHORIZATION_INVALID"):
        private.fence.authorize_binding(wrong)
    assert not private.calls and not private.roots


@pytest.mark.parametrize("fault", ("FAILED", "CANCELLED", "empty", "other_origin"))
def test_private_original_allocation_or_terminal_history_is_not_a_compute_permission(
    private, fault
):
    original = private.state.history
    if fault == "empty":
        private.state.history = replace(original, records=())
    elif fault == "other_origin":
        record = original.records[0]
        origin = record.payload.origin
        altered = type(origin).model_validate(
            seal(
                origin.model_dump(mode="json") | {"runtime_id": "chatrt_" + "f" * 32},
                "origin_sha256",
            )
        )
        allocation = record.payload.model_copy(update={"origin": altered})
        private.state.history = replace(
            original, records=(record.model_copy(update={"payload": allocation}),)
        )
    else:
        private.state.history = replace(original, state=fault)
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_SOURCE_AUTHORIZATION_INVALID"):
        private.fence.authorize_batch()
    assert not private.leases
