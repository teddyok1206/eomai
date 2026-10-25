"""Canonical local parent storage with explicit synthetic current source/lease leaves."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.native_embedding_query_handoff import PreparedNativeQuery
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
    EmbeddingBatchRoute,
    EmbeddingBatchSelection,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow.reference_query_execution import (
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow_runner.embedding_batch_execution import (
    CatalogEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
)
from eom_workflow_runner.embedding_batch_source_authorization import ReferenceQueryBatchSource
from eom_workflow_runner.reference_query_cpu_batch import CatalogCpuReferenceQueryBatchGroup
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQueryOwnerConfiguration,
    build_reference_query_native_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_embedding_batch_plan_admission import source_case
from tests.unit.test_native_embedding_query_handoff import prepared
from tests.unit.test_reference_query_launch_preparation import sources_for


def cpu_batch_case(tmp_path, monkeypatch, *, publisher=None):
    base = prepared()
    context = base.workflow_request.context_request
    planned = planning_case(status="BUSY", batch_id="embeddingbatch_" + uuid4().hex)
    other = planned.selection.anchors[1]
    body = planned.policy.model_dump(mode="json")
    body["cpu"]["profile"].update(
        space=base.policy.spaces.document.model_dump(mode="json"),
        runtime_bundle=base.policy.runtime_bundle.model_dump(mode="json"),
        resource_profile=base.policy.resource_profile.model_dump(mode="json"),
    )
    planned.policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(body, "policy_sha256"))
    body = planned.selection.model_dump(mode="json") | dict(
        scope=seal(
            planned.selection.scope.model_dump(mode="json")
            | dict(
                actor_id=base.workflow_request.operator_audit.operator_id,
                access_policy_sha256=context.policy_sha256,
            ),
            "scope_sha256",
        ),
        graph_snapshot=context.graph_snapshot.model_dump(mode="json"),
        access_policy_revision_id=context.policy_revision_id,
        anchors=[context.anchor.model_dump(mode="json"), other.model_dump(mode="json")],
        recipe=base.request.recipe.model_dump(mode="json"),
        views=[row.view for row in context.views],
        query=dict(
            consumer_purpose=context.consumer_purpose,
            topics=list(context.topics),
            unit_ids=list(context.unit_ids),
            maximum_sources=context.maximum_sources,
            top_k=context.top_k,
        ),
    )
    planned.selection = EmbeddingBatchSelection.model_validate(seal(body, "selection_sha256"))
    value = source_case(
        tmp_path,
        monkeypatch,
        publisher=publisher,
        key="cpu-query-batch:" + uuid4().hex,
        planned=planned,
    )
    control = EmbeddingGpuAllocationRequest.model_validate(
        seal(
            planned.allocation.control_request.model_dump(mode="json")
            | dict(
                parent_request_sha256=value.request.request_sha256,
                child_set_sha256=content_sha256(list(value.request.child_selection_sha256s)),
                routing_policy_sha256=planned.policy.policy_sha256,
            ),
            "message_sha256",
        )
    )
    allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            planned.allocation.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                control_request=control.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            planned.route.observation.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                policy_sha256=planned.policy.policy_sha256,
            ),
            "observation_sha256",
        )
    )
    route = EmbeddingBatchRoute.model_validate(
        seal(
            planned.route.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                allocation_record_sha256=allocation.record_sha256,
                observation=observation.model_dump(mode="json"),
                decision=plan_embedding_device_route(planned.policy, observation).model_dump(
                    mode="json"
                ),
            ),
            "record_sha256",
        )
    )
    store = EmbeddingBatchPlanStore(value.request, value.selection, planned.policy)
    with value.publisher.sessions.begin() as session:
        store.allocate(session, allocation)
        history = store.route(session, route)
    operation = CatalogEmbeddingBatchExecution(
        value.owner, value.publisher, source_commit="a" * 40, controller_release="b" * 40
    )
    owner = object.__new__(CatalogReferenceQueryOwnerAdmission)
    owner.catalog = value.catalog
    owner.settings = value.catalog.settings
    owner.configuration = ReferenceQueryOwnerConfiguration(
        value.catalog.configuration,
        base.workflow_request.native_execution_policy,
        base.workflow_request.native_execution_policy_sha256,
        base.workflow_request.runtime_bundle,
    )
    original = ExistingEmbeddingBatchExecution(history)
    value.operation, value.query_owner, value.original, value.store = (
        operation,
        owner,
        original,
        store,
    )
    value.source_calls = []
    value.denied_child = None
    value.bind_failure = False
    materials, sources = [], []
    for ordinal, anchor in enumerate(value.selection.anchors):
        seed = str(ordinal + 1)
        context_body = seal(
            context.model_dump(mode="json")
            | dict(
                request_id="similarityrequest_" + seed * 32, anchor=anchor.model_dump(mode="json")
            ),
            "request_sha256",
        )
        request = parse_supported_reference_query_workflow_request(
            seal(
                base.workflow_request.model_dump(mode="json") | {"context_request": context_body},
                "request_sha256",
            )
        )
        case = SimpleNamespace(
            request=request, policy=base.policy, bundle=base.bundle, native_input=base.request
        )
        native = build_reference_query_native_input(
            sources_for(case),
            job_id="job_" + seed * 32,
            query_request_id="embeddingquery_" + seed * 32,
        )
        launch = parse_reference_query_launch_association(
            seal(
                base.association.model_dump(mode="json")
                | dict(
                    workflow_id="workflow_" + seed * 32,
                    step_run_id="steprun_" + seed * 32,
                    workflow_request_sha256=request.request_sha256,
                    context_request_sha256=request.context_request.request_sha256,
                    native_launch_job_id=native.job_id,
                    query_request_id=native.query_request_id,
                    query_request_sha256=native.request_sha256,
                    query_input_set_sha256=native.input_set_sha256,
                    original_command_id="wfcmd_" + seed * 32,
                ),
                "association_sha256",
            )
        )
        material = PreparedNativeQuery(seed * 32, request, base.policy, base.bundle, launch, native)

        @contextmanager
        def transaction(workflow_id=launch.workflow_id):
            with value.publisher.sessions.begin() as session:
                session.info["source_workflow"] = workflow_id
                yield session

        source = ReferenceQueryBatchSource(
            owner,
            request,
            launch,
            CommandLeaseIdentity(launch.original_command_id, "test", "test", 1),
            transaction,
        )
        materials.append(material)
        sources.append(source)

    def current(self, native_input):
        with self.transaction() as session:
            assert session.info["source_workflow"] == self.launch.workflow_id
            assert native_input.job_id == self.launch.native_launch_job_id
            value.source_calls.append(self.launch.workflow_id)
            if self.launch.workflow_id == value.denied_child:
                raise ValueError("SYNTHETIC_CURRENT_CHILD_REVOKED")

    monkeypatch.setattr(ReferenceQueryBatchSource, "authorize_current", current)
    value.materials, value.sources = tuple(materials), tuple(sources)
    value.group = CatalogCpuReferenceQueryBatchGroup(operation, value.request, original, owner)
    return value
