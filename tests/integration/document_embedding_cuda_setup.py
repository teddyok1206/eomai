"""Existing Workflow fixture's CUDA composition, with synthetic root/identity/model leaves."""

import os
import time
from contextlib import ExitStack
from dataclasses import replace
from uuid import uuid4

from eom_catalog_service.embedding_registry_ports import ResolvedEmbeddingLookup
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
    EmbeddingBatchSelection,
)
from eom_workflow.embedding_batch_plan_family import parse_embedding_batch_plan_request
from eom_workflow.embedding_batch_plan_v11 import (
    BATCH_PLAN_V11_PROTOCOL,
    BATCH_SELECTION_V11_SCHEMA_REF,
    EmbeddingBatchPlanRequestV11,
    EmbeddingBatchSelectionV11,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow_runner import document_embedding_batch_material as material
from eom_workflow_runner.document_embedding_cpu_batch_execution import (
    CatalogCpuDocumentBatchExecution,
)
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.document_embedding_cuda_execution import (
    CatalogCudaDocumentEmbeddingExecution,
)
from eom_workflow_runner.local_embedding_actor_authority import OperatorLocalEmbeddingActorAuthority
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import CatalogLocalEmbeddingOwnerAdmission
from eom_workflow_runner.native_command_fence import NativeCommandMutationFence

from tests.integration.embedding_batch_root_fixtures import configure_synthetic_batch_runtime
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.reference_query_batch_execution_fixtures import query_plan_case
from tests.unit.test_embedding_batch_plan import member, planning_case
from tests.unit.test_embedding_batch_plan_admission import source_case
from tests.unit.test_embedding_device_routing import policy_document


def make_document_cuda_execution(
    *,
    source_owner,
    request,
    plan,
    profile,
    resolved,
    publisher,
    tmp_path,
    monkeypatch,
    finalizer,
    parent_protocol="embedding-batch-plan/1.0",
    cpu_launcher=None,
    defer_open=False,
    paired_catchup=False,
):
    # The same explicit synthetic Identity/source delegates as the CPU integration
    # fixture; real Catalog/index/encoding/Workflow/Artifact persistence is retained.
    owner = object.__new__(CatalogLocalEmbeddingOwnerAdmission)
    for name in (
        "configuration",
        "catalog",
        "settings",
        "registry_caller",
        "fence_current_actor",
        "resolve_submission",
        "resolve_sources",
        "resolve_claim",
    ):
        setattr(owner, name, getattr(source_owner, name))
    owner._actor_authority = OperatorLocalEmbeddingActorAuthority(source_owner.identity)
    owner._command_fence = NativeCommandMutationFence()
    _unused_query, cpu_template = query_plan_case(key="a" * 32)
    policy = policy_document("INDEX")
    if cpu_launcher is None:
        policy["cpu"]["profile"] = cpu_template.policy.cpu.profile.model_dump(mode="json")
        policy["cuda"]["profile"] = profile.model_dump(mode="json")
    else:
        policy["cpu"]["profile"] = profile.model_dump(mode="json")
    template = planning_case(purpose="INDEX")
    template.policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(policy, "policy_sha256"))
    paired = None
    if paired_catchup:
        from tests.integration.document_embedding_paired_source import paired_gpu_source

        paired = paired_gpu_source(
            owner, request, plan, profile, template.policy.cuda.profile, publisher, monkeypatch
        )
    scope = seal(
        template.selection.scope.model_dump(mode="json")
        | dict(
            actor_id=request.actor_context.operator_id,
            storage_partition=request.namespace.storage_partition,
            access_policy_sha256=request.access_policy_sha256,
        ),
        "scope_sha256",
    )
    entries = {
        entry.profile.source_basis.source.item_revision_id: entry for entry in resolved.entries
    }
    anchors = []
    from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer

    for source in plan.sources:
        entry = entries[source.item_revision_id]
        anchors.append(
            dict(
                basis="APPROVED_REFERENCE_ITEM",
                source=source.model_dump(mode="json"),
                profile=InferenceTransferProfilePointer.from_profile(entry.profile).model_dump(
                    mode="json"
                ),
                solution_evidence=entry.profile.source_basis.solution_evidence.model_dump(
                    mode="json"
                ),
            )
        )
    body = template.selection.model_dump(mode="json") | dict(
        scope=scope,
        corpus_id=request.corpus_id,
        graph_snapshot=request.graph_snapshot.model_dump(mode="json"),
        access_policy_revision_id=request.access_policy_revision_id,
        recipe=plan.recipe.model_dump(mode="json"),
        anchors=anchors,
        views=[request.namespace.view],
    )
    if parent_protocol == BATCH_PLAN_V11_PROTOCOL:
        template.selection = EmbeddingBatchSelectionV11.model_validate(
            seal(body | {"schema_version": BATCH_PLAN_V11_PROTOCOL}, "selection_sha256")
        )
        template.request = EmbeddingBatchPlanRequestV11.model_validate(
            seal(
                template.request.model_dump(mode="json")
                | dict(
                    schema_version=BATCH_PLAN_V11_PROTOCOL,
                    selection_manifest=member(
                        "selection.json", BATCH_SELECTION_V11_SCHEMA_REF, template.selection, "1"
                    ).model_dump(mode="json"),
                    selection_sha256=template.selection.selection_sha256,
                    child_selection_sha256s=list(template.selection.child_selection_sha256s),
                ),
                "request_sha256",
            )
        )
    elif parent_protocol == "embedding-batch-plan/1.0":
        template.selection = EmbeddingBatchSelection.model_validate(seal(body, "selection_sha256"))
    else:
        raise ValueError("unsupported synthetic parent protocol")
    value = source_case(
        tmp_path, monkeypatch, publisher=publisher, planned=template, key=uuid4().hex
    )
    value.request = parse_embedding_batch_plan_request(
        seal(
            value.request.model_dump(mode="json")
            | {
                "batch_id": "embeddingbatch_" + uuid4().hex,
                "parent_request_sha256": paired.request.request_sha256
                if paired is not None
                else request.request_sha256,
            },
            "request_sha256",
        )
    )
    value.current = ResolvedEmbeddingLookup(
        request.corpus_id,
        template.policy.cpu.profile.space,
        plan.recipe,
        plan.sources,
        resolved.entries,
    )
    control = seal(
        template.allocation.control_request.model_dump(mode="json")
        | dict(
            parent_request_sha256=value.request.request_sha256,
            child_set_sha256=content_sha256(list(value.request.child_selection_sha256s)),
            routing_policy_sha256=template.policy.policy_sha256,
            expires_monotonic_ns=time.monotonic_ns() + 180 * 10**9,
        ),
        "message_sha256",
    )
    value.allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            template.allocation.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                control_request=control,
            ),
            "record_sha256",
        )
    )
    value.store = EmbeddingBatchPlanStore(value.request, value.selection, template.policy)
    if paired is not None:
        value.pair, value.source_request = paired.pair, paired.request
    configure_synthetic_batch_runtime(
        value, monkeypatch, allocation_status="READY" if cpu_launcher is None else "BUSY"
    )
    root = tmp_path / "cuda-publications"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(material, "DOCUMENT_PUBLICATION_ROOT", root)
    monkeypatch.setattr(
        material, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    if defer_open:
        from eom_orchestrator.local_embedding_control_artifacts import (
            LocalEmbeddingControlArtifactPublisher,
        )
        from eom_workflow.local_embedding_execution_policy import LocalEmbeddingExecutionPolicy
        from eom_workflow_runner.local_embedding_owner_admission import (
            LocalEmbeddingOwnerConfiguration,
        )
        from eom_workflow_runner.local_embedding_service_reconciliation import (
            LocalEmbeddingServicePreparation,
        )
        from eom_workflow_runner.local_indexing_routed_sources import (
            PairedIndexingNamespacePreparation,
        )

        from tests.unit.local_embedding_admission_fixtures import native_fixture

        cpu_profile = template.policy.cpu.profile
        cpu_policy = LocalEmbeddingExecutionPolicy.model_validate(
            seal(
                native_fixture().policy.model_dump(mode="json")
                | dict(
                    workflow_definition_sha256=request.workflow_definition_sha256,
                    profiles=[cpu_profile.model_dump(mode="json")],
                ),
                "policy_sha256",
            )
        )
        saved_cpu = LocalEmbeddingControlArtifactPublisher(
            publisher, source_commit="a" * 40
        ).publish_policy(
            cpu_policy,
            idempotency_key="test:deferred-cpu-policy:" + uuid4().hex,
            created_at=cpu_policy.created_at,
        )
        cpu_owner = CatalogLocalEmbeddingOwnerAdmission(
            publisher.engine,
            LocalEmbeddingOwnerConfiguration(
                replace(
                    value.catalog.configuration,
                    source_classes=owner.configuration.registry.source_classes,
                ),
                saved_cpu.member,
                cpu_policy.policy_sha256,
            ),
            actor_authority=OperatorLocalEmbeddingActorAuthority(source_owner.identity),
            settings=value.catalog.settings,
        )
        value.pair = PairedIndexingNamespacePreparation(
            LocalEmbeddingServicePreparation(
                cpu_owner, publisher, cpu_profile, source_commit="a" * 40
            ),
            LocalEmbeddingServicePreparation(owner, publisher, profile, source_commit="a" * 40),
        )
        value.child_owner, value.executor = owner, None
        return value
    stack = ExitStack()
    finalizer(stack.close)
    active = stack.enter_context(value.operation.open(value.request, value.allocation))
    value.adapter = (
        CatalogCudaDocumentEmbeddingExecution(active, owner, request)
        if cpu_launcher is None
        else CatalogCpuDocumentBatchExecution(
            value.operation,
            value.request,
            active,
            owner,
            request,
            FixedCpuDocumentEmbeddingExecution(cpu_launcher),
        )
    )
    value.child_owner = owner
    value.executor = CatalogNativeEmbeddingExecutor(
        owner=owner,
        publisher=publisher,
        execution_backend=value.adapter,
        runtime_profile=profile,
        source_commit="a" * 40,
    )
    return value
