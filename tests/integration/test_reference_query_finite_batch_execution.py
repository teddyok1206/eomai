"""Guarded PG actual Runner/claim/lease/Workflow/Artifact flow; IAM/root/GPU leaves synthetic."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    read_native_reference_query_launch,
)
from eom_orchestrator.settings import Settings
from eom_workflow.compiler import compile_definition_data
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
)
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_query_key,
    parse_embedding_batch_plan_request,
)
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from eom_workflow_runner import reference_query_batch_material as material_module
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_command_fence import NativeCommandMutationFence
from eom_workflow_runner.reference_query_batch_driver import (
    drive_batch_reference_queries,
    prepare_batch_reference_query_context,
)
from eom_workflow_runner.reference_query_batch_executor import CatalogBatchReferenceQueryExecutor
from eom_workflow_runner.reference_query_batch_group import CatalogReferenceQueryBatchGroup
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQueryOwnerConfiguration,
)
from eom_workflow_runner.reference_query_submission import start_reference_query_in_session
from eom_workflow_runner.repository import (
    command_lease_identity,
    import_workflow_definition,
    renew_command_lease,
)
from sqlalchemy import select

from tests.integration.embedding_batch_root_fixtures import configure_synthetic_batch_runtime
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.reference_query_batch_execution_fixtures import (
    pair_existing_query_plan,
    two_query_plan_case,
)
from tests.unit.test_embedding_batch_plan_admission import source_case
from tests.unit.test_reference_query_launch_preparation import sources_for
from tests.unit.test_reference_query_workflow_contracts import definition_body

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def finite(guarded_engine, tmp_path, monkeypatch, request):
    import os

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine, Settings(staging_root=tmp_path / "staging", nas_artifact_root=artifacts)
    )
    compiled = compile_definition_data(definition_body(), "synthetic/finite-batch-query", set())
    queries, plan = two_query_plan_case(definition_sha256=compiled.sha256)
    if getattr(request, "param", None) == "paired":
        from eom_catalog_service.embedding_device_index_pair import (
            EmbeddingDeviceIndexPair,
            EmbeddingDeviceIndexPin,
        )
        from eom_workflow_runner import embedding_batch_plan_admission as admission

        queries, plan = pair_existing_query_plan(queries, plan)

        def synthetic_pair(_session, _caller, *, cpu_intent, cuda_intent, **_kwargs):
            rows = (cpu_intent.selection, cuda_intent.selection)
            pins = tuple(
                EmbeddingDeviceIndexPin(
                    r.index.index_id,
                    r.index.index_revision_id,
                    r.index.index_manifest,
                    r.index.index_sha256,
                    r.index.spaces.document,
                )
                for r in rows
            )
            return EmbeddingDeviceIndexPair(
                pins[0],
                pins[1],
                cpu_intent.scope.namespace.storage_partition,
                rows[0].view,
                rows[0].recipe.recipe_sha256,
                "sha256:" + "a" * 64,
                len(queries),
            )

        monkeypatch.setattr(
            admission,
            "resolve_embedding_device_index_pair",
            synthetic_pair,
        )
    with publisher.sessions.begin() as session:
        definition, _created = import_workflow_definition(session, compiled)
    value = source_case(tmp_path, monkeypatch, publisher=publisher, planned=plan, key=uuid4().hex)
    value.request = parse_embedding_batch_plan_request(
        seal(
            value.request.model_dump(mode="json") | {"batch_id": "embeddingbatch_" + uuid4().hex},
            "request_sha256",
        )
    )
    # Match the real batch preparation: each new parent owns distinct logical
    # child intents, without changing source/index/Graph pins or old Workflows.
    queries = tuple(
        replace(
            query,
            request=parse_supported_reference_query_workflow_request(
                seal(
                    query.request.model_dump(mode="json")
                    | {
                        "context_request": prepare_batch_reference_query_context(
                            value.request, ordinal, query.request.context_request
                        ).model_dump(mode="json")
                    },
                    "request_sha256",
                )
            ),
        )
        for ordinal, query in enumerate(queries)
    )
    control = seal(
        plan.allocation.control_request.model_dump(mode="json")
        | {
            "parent_request_sha256": value.request.request_sha256,
            "child_set_sha256": content_sha256(list(value.request.child_selection_sha256s)),
            "routing_policy_sha256": plan.policy.policy_sha256,
            "expires_monotonic_ns": time.monotonic_ns() + 180 * 10**9,
        },
        "message_sha256",
    )
    value.allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            plan.allocation.model_dump(mode="json")
            | {"request_sha256": value.request.request_sha256, "control_request": control},
            "record_sha256",
        )
    )
    value.store = EmbeddingBatchPlanStore(value.request, value.selection, plan.policy)
    registry = replace(
        value.catalog.configuration,
        namespace=type(value.catalog.configuration.namespace).model_validate(
            value.catalog.configuration.namespace.model_dump(mode="json")
            | {"space_sha256": plan.policy.cuda.profile.space.space_sha256}
        ),
        space=plan.policy.cuda.profile.space,
    )
    owner = object.__new__(CatalogReferenceQueryOwnerAdmission)
    owner.configuration = ReferenceQueryOwnerConfiguration(
        registry,
        queries[0].request.native_execution_policy,
        queries[0].request.native_execution_policy_sha256,
        queries[0].request.runtime_bundle,
    )
    owner.settings = value.catalog.settings
    owner.catalog = CatalogEmbeddingRegistryVerifier(
        guarded_engine, registry, identity_fence=Mock(), settings=owner.settings
    )
    owner._command_fence = NativeCommandMutationFence()
    value.denied_child = False
    value.current_calls = []

    def identity(session, operator_id):
        assert operator_id == value.selection.scope.actor_id and session.get_transaction().is_active
        if value.denied_child:
            raise ValueError("synthetic actual operator access revoked")
        value.current_calls.append(operator_id)

    owner.identity = SimpleNamespace(fence_current_operator=identity)
    source_by_hash = {query.request.request_sha256: sources_for(query) for query in queries}

    def current(session, request, *, artifact_reader=None):
        identity(session, request.operator_audit.operator_id)
        return source_by_hash[request.request_sha256]

    owner.resolve_sources = current
    value.owner_query, value.queries, value.definition = owner, queries, definition
    root = tmp_path / "query-publications"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(material_module, "QUERY_PUBLICATION_ROOT", root)
    monkeypatch.setattr(
        material_module,
        "fixed_owner_identity",
        lambda: CpuHandoffIdentity(os.getuid(), os.getgid()),
    )
    configure_synthetic_batch_runtime(value, monkeypatch)

    @contextmanager
    def opened():
        with value.operation.open(value.request, value.allocation) as active:
            value.group = CatalogReferenceQueryBatchGroup(active, owner)
            value.executor = CatalogBatchReferenceQueryExecutor(value.group)
            ids = []
            with publisher.sessions.begin() as session:
                for ordinal, query in enumerate(queries):
                    submitted = start_reference_query_in_session(
                        session,
                        definition=definition,
                        request=query.request,
                        idempotency_key=embedding_batch_query_key(value.request, ordinal),
                        actor_type="human",
                        actor_id=query.request.operator_audit.operator_id,
                        owner=owner,
                        executor=value.executor,
                    )
                    ids.append(submitted.workflow.workflow_id)
            value.workflow_ids = tuple(ids)
            yield value

    value.opened = opened
    return value


def histories(value):
    with value.publisher.sessions.begin() as session:
        values = []
        for workflow_id, query in zip(value.workflow_ids, value.queries, strict=True):
            step = session.scalar(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == workflow_id,
                    WorkflowStepRunRecord.step_key == "encode_reference_query",
                )
            )
            launch = read_native_reference_query_launch(
                session,
                request=query.request,
                workflow_id=workflow_id,
                step_run_id=step.step_run_id,
            )
            values.append(NativeReferenceQueryCoordinator(query.request, launch).read(session))
        return tuple(values)


def test_actual_runner_executes_two_queries_with_one_batch_and_preserves_exact_canonical_replay(
    finite,
):
    with finite.opened() as value:
        outputs = drive_batch_reference_queries(value.executor, value.workflow_ids)
        original = histories(value)
        assert all(
            history.state == "SUCCEEDED" and len(history.records) == 4 for history in original
        )
        assert len({history.launch.native_launch_job_id for history in original}) == 2
        assert tuple(row.workflow_id for row in outputs) == value.workflow_ids
        assert value.acked and len(value.dispatches) == 1
        assert len(value.numeric.result.children) == 2
        value.channel.require_direct_peer.side_effect = AssertionError(
            "replay revived completed physical work"
        )
        assert drive_batch_reference_queries(value.executor, value.workflow_ids) == outputs
        assert histories(value) == original and len(value.dispatches) == 1
        with value.publisher.sessions.begin() as session:
            rows = tuple(
                session.scalars(
                    select(WorkflowCommandRecord).where(
                        WorkflowCommandRecord.workflow_id.in_(value.workflow_ids)
                    )
                )
            )
            assert len(rows) == 2 and all(
                row.state == "SUCCEEDED" and row.attempts == 1 for row in rows
            )
            assert all(
                session.get(WorkflowInstanceRecord, workflow_id).state == "COMPLETED"
                for workflow_id in value.workflow_ids
            )


@pytest.mark.parametrize("finite", ["paired"], indirect=True)
def test_paired_original_parent_uses_same_actual_runner_bind_completion_and_replay(finite):
    assert finite.request.schema_version == "embedding-batch-plan/1.2"
    test_actual_runner_executes_two_queries_with_one_batch_and_preserves_exact_canonical_replay(
        finite
    )


@pytest.mark.parametrize(
    "boundary", ("query_before", "query_after", "receipt_before", "receipt_after")
)
def test_partial_child_publication_recovers_original_expired_command_without_reencoding(
    finite, monkeypatch, boundary
):
    with finite.opened() as value:
        target = (
            EmbeddingArtifactStore
            if boundary.startswith("query")
            else NativeEmbeddingCompletionPublisher
        )
        original = target.publish_reference_query
        failed = []
        failure_lock = Lock()

        def interrupt(self, *args, **kwargs):
            # Only one child is interrupted, not a second model run or a new identity.
            with failure_lock:
                interrupt_this = not failed
                if interrupt_this:
                    failed.append(True)
            if interrupt_this:
                if boundary.endswith("after"):
                    original(self, *args, **kwargs)
                raise RuntimeError("synthetic publication process interruption")
            return original(self, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(target, "publish_reference_query", interrupt)
            with pytest.raises(RuntimeError):
                drive_batch_reference_queries(value.executor, value.workflow_ids)
        prior = histories(value)
        # Isolated fault injection through the official repository clock seam,
        # not production row UPDATE or a failed-history reinterpretation.
        with value.publisher.sessions.begin() as session:
            for command in session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id.in_(value.workflow_ids),
                    WorkflowCommandRecord.state == "PROCESSING",
                )
            ):
                renew_command_lease(
                    session,
                    command_lease_identity(command),
                    lease_seconds=1,
                    observed_at=datetime.now(UTC) - timedelta(seconds=2),
                )
        value.channel.require_direct_peer.side_effect = AssertionError(
            "recovery revived completed GPU work"
        )
        outputs = drive_batch_reference_queries(value.executor, value.workflow_ids)
        after = histories(value)
        assert len(outputs) == 2 and len(value.dispatches) == 1
        assert all(history.state == "SUCCEEDED" for history in after)
        assert all(
            old.launch == new.launch and old.records[0] == new.records[0]
            for old, new in zip(prior, after, strict=True)
        )


def test_wrong_workflow_parent_or_order_is_rejected_before_claim(finite):
    with finite.opened() as value:
        with pytest.raises(ValueError):
            drive_batch_reference_queries(value.executor, tuple(reversed(value.workflow_ids)))
        with value.publisher.sessions.begin() as session:
            commands = tuple(
                session.scalars(
                    select(WorkflowCommandRecord).where(
                        WorkflowCommandRecord.workflow_id.in_(value.workflow_ids)
                    )
                )
            )
            assert all(row.state == "PENDING" and row.attempts == 0 for row in commands)
