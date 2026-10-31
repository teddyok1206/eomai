"""Actual disposable metadata/history with explicitly synthetic source/OS/numerical leaves."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_identifiers import content_sha256
from eom_identity_service import activate_local_indexing_service, register_local_indexing_service
from eom_operator_identity import local_indexing_service_reference
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.embedding_encoding_reservations import EmbeddingEncodingReservations
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import create_native_embedding_launch
from eom_workflow.compiler import compile_definition
from eom_workflow.embedding_batch_plan import (
    BATCH_SELECTION_SCHEMA_REF,
    EmbeddingBatchAllocation,
    EmbeddingBatchBound,
    EmbeddingBatchPlanRequest,
    EmbeddingBatchRoute,
    EmbeddingBatchSelection,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow.embedding_encoding_recovery import (
    ENCODING_RECOVERY_PROTOCOL,
    NativeEmbeddingFailureRecoveryCommand,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.local_embedding_request_v2 import parse_supported_local_embedding_request
from eom_workflow.native_embedding_coordinator import NativeCoordinatorAllocation
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_publications import new_native_artifact_producer
from eom_workflow_runner.local_embedding_submission import start_local_embedding_in_session
from eom_workflow_runner.repository import create_step_run, import_workflow_definition
from eom_workflow_runner.state_machine import (
    CommandState,
    StepState,
    WorkflowState,
    transition_command,
    transition_step,
    transition_workflow,
)

from tests.integration.test_local_embedding_runner import ClaimFixture, SyntheticOwner
from tests.integration.test_local_indexing_service_registry import identity
from tests.unit.embedding_encoding_reservation_fixtures import (
    fixture_for_jobs,
    partition_fixture,
    requests,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture, runtime_profile
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.test_embedding_batch_plan import member, planning_case
from tests.unit.test_embedding_encoding_reservations import SyntheticAdmission
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle, _pointer
from tests.unit.test_local_embedding_runner_admission import scope_fixture
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture
from tests.unit.test_public_solution_native_carriers import public_native_fixture


def seed_allocated_execution(engine, *, device="CUDA", request_family="1.2"):
    sessions = build_session_factory(engine)
    service = identity()
    ref = local_indexing_service_reference(service)
    key = "synthetic-allocated-recovery:" + uuid4().hex
    with sessions.begin() as session:
        register_local_indexing_service(session, service, operation_key=key + ":register")
        activate_local_indexing_service(
            session, ref, expected_resource_version=1, operation_key=key + ":activate"
        )
    _, compiled = scope_fixture()
    if request_family in {"2.0", "3.0"}:
        assert device == "CPU"
        compiled = compile_definition(
            Path(__file__).resolve().parents[2] / "config/workflows/local-embedding-index.v2.yaml",
            set(),
        )
    native = service_fixture(
        base=partition_fixture(
            native_fixture("a", "b", device=device, timeout_seconds=180), "test-" + uuid4().hex
        ),
        service=ref,
        workflow_definition_sha256=compiled.sha256,
    )
    if request_family in {"2.0", "3.0"}:
        mixed = public_native_fixture() if request_family == "3.0" else carrier_fixture()
        plan = mixed["plan"]
        policy = type(native.policy).model_validate(
            seal(
                native.policy.model_dump(mode="json")
                | {"workflow_definition_sha256": compiled.sha256},
                "policy_sha256",
            )
        )
        body = native.request.model_dump(mode="json") | {
            "schema_version": "local-embedding-workflow-request/" + request_family,
            "workflow_definition_version": "2.0.0",
            "workflow_definition_sha256": compiled.sha256,
            **{
                field: getattr(plan, field).model_dump(mode="json")
                if hasattr(getattr(plan, field), "model_dump")
                else getattr(plan, field)
                for field in (
                    "corpus_id",
                    "graph_snapshot",
                    "access_policy_revision_id",
                    "access_policy_sha256",
                    "namespace",
                    "space",
                )
            },
            "source_plan": member(
                "source-plan.json",
                mixed["request"].source_plan.schema_ref,
                plan,
                "d",
            ).model_dump(mode="json"),
            "source_plan_sha256": plan.plan_sha256,
            "native_execution_policy": member(
                "policy.json",
                native.request.native_execution_policy.schema_ref,
                policy,
                "e",
            ).model_dump(mode="json"),
            "native_execution_policy_sha256": policy.policy_sha256,
        }
        request = parse_supported_local_embedding_request(seal(body, "request_sha256"))
        base = partition_fixture(
            replace(
                native.base,
                request=request,
                policy=policy,
                plan=plan,
                association=mixed["association"],
                native_input=mixed["input"],
                result=mixed["result"],
                completions=mixed["events"],
            ),
            "test-" + uuid4().hex,
        )
        native = SimpleNamespace(base=base, request=base.request, policy=policy)
    request = native.request
    owner = SyntheticOwner(
        ResolvedLocalEmbeddingAdmission(request, native.base.plan, native.policy)
    )
    with sessions.begin() as session:
        EmbeddingEncodingReservationStorage.prepare_protocol(session)
        if request_family == "2.0":
            EmbeddingEncodingReservationStorage.prepare_mixed_ownership_protocol(session)
        elif request_family == "3.0":
            EmbeddingEncodingReservationStorage.prepare_mixed_ownership_protocol(session)
            EmbeddingEncodingReservationStorage.prepare_public_ownership_protocol(session)
        definition, _ = import_workflow_definition(session, compiled)
        submitted = start_local_embedding_in_session(
            session,
            definition=definition,
            request=request,
            idempotency_key=key,
            actor_type="local_indexing_service",
            actor_id=ref.service_id,
            owner=owner,
            executor=Mock(),
        )
        workflow_id, command_id = submitted.workflow.workflow_id, submitted.command.command_id
    claimed = ClaimFixture(engine, sessions, owner, Mock(), workflow_id, command_id)
    candidate = claimed.peek()
    with sessions.begin() as session:
        command = claimed.claim(session, candidate)
        transition_command(command, CommandState.PROCESSING)
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=2)
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.RUNNING,
            "SYNTHETIC_ALLOCATED_START",
            actor_type="local_indexing_service",
            actor_id=ref.service_id,
            command_id=command_id,
            step_key="encode_batch",
        )
        step = create_step_run(
            session,
            workflow_id=workflow_id,
            step_key="encode_batch",
            step_type="application",
            worker_role=None,
            result_schema="incremental-embedding-result@1.0",
            input_pointer_manifest=dict(
                source_plan=request.source_plan.model_dump(mode="json"),
                source_plan_sha256=request.source_plan_sha256,
            ),
            max_attempts=1,
        )
        transition_step(step, StepState.RUNNING)
        session.flush()
        step_id = step.step_run_id
        launch = create_native_embedding_launch(
            session,
            request=request,
            workflow_id=workflow_id,
            step_run_id=step_id,
            command_id=command_id,
            runner_id=command.lease_owner,
            lease_generation=command.lease_generation,
        )
        coordinator = NativeEmbeddingCoordinator(launch.intent, request)
        allocated = NativeCoordinatorAllocation(
            index_producer=new_native_artifact_producer(),
            receipt_producer=new_native_artifact_producer(),
            created_at=datetime.now(UTC),
            source_commit="a" * 40,
        )
        coordinator.append(session, coordinator.checkpoint("ALLOCATION", allocated))
    synthetic = replace(
        native.base,
        request=request,
        policy=native.policy,
        association=native.base.association.model_copy(update={"intent": launch.intent}),
    )
    gate = SyntheticAdmission(synthetic)
    encoding = EmbeddingEncodingReservations(sessions, gate)
    rows = encoding.reserve_and_attach(requests(synthetic), launch.intent)
    synthetic = fixture_for_jobs(synthetic, tuple(r.owned_job for r in rows))
    gate.fixture = synthetic
    encoding.bind_launch(synthetic.association)
    return SimpleNamespace(
        sessions=sessions,
        request=request,
        workflow_id=workflow_id,
        origin_command_id=command_id,
        step_id=step_id,
        coordinator=coordinator,
        association=synthetic.association,
        native_input=synthetic.native_input,
        encoding=encoding,
        gate=gate,
        service=service,
        owner=owner,
    )


def seed_allocated_failure(engine):
    value = seed_allocated_execution(engine)
    sessions, request = value.sessions, value.request
    workflow_id, command_id = value.workflow_id, value.origin_command_id
    parent = parent_case(request, value.association, value.native_input)
    store = EmbeddingBatchPlanStore(parent.request, parent.selection, parent.policy)
    with sessions.begin() as session:
        store.allocate(session, parent.allocation)
        store.route(session, parent.route)
        history = store.bind(
            session, parent.bound, parent.batch, authorize_child=lambda child: None
        )
    command = NativeEmbeddingFailureRecoveryCommand.model_validate(
        seal(
            dict(
                schema_version=ENCODING_RECOVERY_PROTOCOL,
                record_type="RECOVER",
                workflow_id=workflow_id,
                workflow_request_sha256=request.request_sha256,
                command_id=command_id,
                lease_generation=1,
                root=dict(
                    allocation_attempt_id=parent.allocation.control_request.allocation_attempt_id,
                    invocation_id="f" * 32,
                    retirement_sha256="sha256:" + "f" * 64,
                    retired_at="2026-10-25T05:31:15Z",
                    parent_plan_job_id=history.job_id,
                    parent_request_sha256=parent.request.request_sha256,
                    original_outcome="FAILED",
                    stored_descriptors=0,
                ),
            ),
            "command_sha256",
        )
    )
    value.command, value.parent = command, parent
    value.store, value.parent_history = store, history
    return value


def parent_case(request, association, native_input):
    value = planning_case(purpose="INDEX", batch_id="embeddingbatch_" + uuid4().hex)
    # Valid distinct metadata bundles, never an installed CPU/GPU qualification.
    cpu_bundle_body = _bundle("CPU").model_dump(mode="json")
    cpu_bundle_body["execution_model_spec"] = seal(
        cpu_bundle_body["execution_model_spec"]
        | {"model_revision_id": "embeddingmodelrev_" + "f" * 32},
        "manifest_sha256",
    )
    cpu_bundle_body["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    cpu_bundle = type(_bundle("CPU")).model_validate(seal(cpu_bundle_body, "bundle_sha256"))
    cpu_profile = runtime_profile("CPU").model_dump(mode="json")
    cpu_profile["space"] = seal(
        cpu_profile["space"]
        | {"model_spec": cpu_bundle.execution_model_spec.model_dump(mode="json")},
        "space_sha256",
    )
    cpu_profile["runtime_bundle"] = _pointer(cpu_bundle).model_dump(mode="json")
    cpu_profile["runtime_bundle"]["manifest_member"]["artifact_revision_id"] = "rev_" + "f" * 32
    policy_body = value.policy.model_dump(mode="json")
    policy_body["cpu"]["profile"] = LocalEmbeddingRuntimeProfile.model_validate(
        cpu_profile
    ).model_dump(mode="json")
    policy_body["cuda"]["profile"] = LocalEmbeddingRuntimeProfile(
        space=request.space,
        runtime_bundle=request.runtime_bundle,
        resource_profile=request.resource_profile,
    ).model_dump(mode="json")
    value.policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(policy_body, "policy_sha256"))
    scope = seal(
        value.selection.scope.model_dump(mode="json")
        | dict(
            actor_kind="LOCAL_INDEXING_SERVICE",
            actor_id=request.actor_context.service_id,
            storage_partition=request.namespace.storage_partition,
            access_policy_sha256=request.access_policy_sha256,
        ),
        "scope_sha256",
    )
    value.selection = EmbeddingBatchSelection.model_validate(
        seal(
            value.selection.model_dump(mode="json")
            | dict(
                scope=scope,
                views=[request.namespace.view],
                corpus_id=request.corpus_id,
                graph_snapshot=request.graph_snapshot.model_dump(mode="json"),
                access_policy_revision_id=request.access_policy_revision_id,
            ),
            "selection_sha256",
        )
    )
    value.request = EmbeddingBatchPlanRequest.model_validate(
        seal(
            value.request.model_dump(mode="json")
            | dict(
                scope=scope,
                parent_request_sha256=request.request_sha256,
                selection_manifest=member(
                    "selection.json", BATCH_SELECTION_SCHEMA_REF, value.selection, "1"
                ).model_dump(mode="json"),
                selection_sha256=value.selection.selection_sha256,
                child_selection_sha256s=list(value.selection.child_selection_sha256s),
                routing_policy=member(
                    "policy.json",
                    "eom://schemas/workflow/embedding-device-routing/1.0",
                    value.policy,
                    "2",
                ).model_dump(mode="json"),
                routing_policy_sha256=value.policy.policy_sha256,
            ),
            "request_sha256",
        )
    )
    control = EmbeddingGpuAllocationRequest.model_validate(
        seal(
            value.allocation.control_request.model_dump(mode="json")
            | dict(
                allocation_attempt_id="embeddingallocation_" + uuid4().hex,
                parent_request_sha256=value.request.request_sha256,
                child_set_sha256=content_sha256(list(value.request.child_selection_sha256s)),
                routing_policy_sha256=value.policy.policy_sha256,
            ),
            "message_sha256",
        )
    )
    value.allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            value.allocation.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                control_request=control.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            value.route.observation.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                allocation_attempt_id=control.allocation_attempt_id,
                policy_sha256=value.policy.policy_sha256,
            ),
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(value.policy, observation)
    value.route = EmbeddingBatchRoute.model_validate(
        seal(
            value.route.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                allocation_record_sha256=value.allocation.record_sha256,
                observation=observation.model_dump(mode="json"),
                decision=decision.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    value.batch = EmbeddingWorkBatchInput.model_validate(
        seal(
            value.batch.model_dump(mode="json")
            | dict(
                scope=scope,
                routing_decision_sha256=decision.decision_sha256,
                resource_profile_sha256=request.resource_profile.resource_profile_sha256,
                children=[
                    dict(
                        scope_sha256=scope["scope_sha256"],
                        request=native_input.model_dump(mode="json"),
                    )
                ],
            ),
            "request_sha256",
        )
    )
    value.bound = EmbeddingBatchBound.model_validate(
        seal(
            value.bound.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                route_record_sha256=value.route.record_sha256,
                batch_request_sha256=value.batch.request_sha256,
                resource_profile_sha256=request.resource_profile.resource_profile_sha256,
                children=[
                    dict(
                        selection_sha256=value.selection.child_selection_sha256s[0],
                        workflow_id=association.intent.workflow_id,
                        step_run_id=association.intent.step_run_id,
                        native_job_id=association.intent.native_launch_job_id,
                        workflow_request_sha256=request.request_sha256,
                        launch_association_sha256=association.association_sha256,
                        native_input_sha256=association.owned_input_request_sha256,
                    )
                ],
            ),
            "record_sha256",
        )
    )
    return value
