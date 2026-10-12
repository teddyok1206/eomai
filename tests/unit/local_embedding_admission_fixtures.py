"""Synthetic protocol-only native intent; never service admission, IO or inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingExecutionRuntime,
    EmbeddingSpace,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    embedding_input_set_sha256,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    experiment_view_text,
    population_sha256,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingCompletedEvent,
    EmbeddingEncodingJobRequest,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingLaunchIntent,
    LocalEmbeddingOwnedJob,
)
from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
    LocalEmbeddingExecutionPolicy,
    LocalEmbeddingResourceProfile,
    LocalEmbeddingRuntimeProfile,
)
from eom_workflow.local_embedding_request import LocalEmbeddingWorkflowRequestV11
from eom_workflow.local_embedding_source_plan import (
    LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
    LocalEmbeddingSourcePlan,
)

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    embedding_input,
    embedding_result,
    encoding_identity,
    seal,
    view_recipe,
)
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle, _pointer


def member(
    path: str, schema: str, payload: dict[str, Any], seed: str = "f"
) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path=path,
        schema_ref=schema,
        media_type="application/json",
        sha256=sha256_bytes(canonical_json_bytes(payload)),
    )


def resources(device: Literal["CPU", "CUDA"] = "CPU") -> LocalEmbeddingResourceProfile:
    return LocalEmbeddingResourceProfile.model_validate(
        seal(
            {
                "device": device,
                "threads": 4,
                "batch_size": 4,
                "memory_max_bytes": 6 * 1024**3,
                "gpu_vram_max_bytes": 8 * 1024**3 if device == "CUDA" else 0,
                "cpu_quota_percent": 400,
                "timeout_seconds": 300,
                "tasks_max": 32,
                "output_max_bytes": 16 * 1024**2,
                "maximum_active_launches": 1,
                "physical_gpu_lease": "SHARED_GPU0" if device == "CUDA" else "NONE",
                "network": "DISABLED",
            },
            "resource_profile_sha256",
        )
    )


def runtime_profile(device: Literal["CPU", "CUDA"] = "CPU") -> LocalEmbeddingRuntimeProfile:
    bundle = _bundle(device)
    space = EmbeddingSpace.model_validate(
        seal(
            {
                "model_spec": bundle.execution_model_spec.model_dump(mode="json"),
                "purpose": "DOCUMENT",
                "runtime": EmbeddingExecutionRuntime(
                    device=device, execution_runtime_sha256=bundle.numerical_runtime.runtime_sha256
                ).model_dump(mode="json"),
            },
            "space_sha256",
        )
    )
    return LocalEmbeddingRuntimeProfile(
        space=space, runtime_bundle=_pointer(bundle), resource_profile=resources(device)
    )


@dataclass(frozen=True)
class NativeAdmissionFixture:
    entries: tuple[StagedExperimentEntry, ...]
    policy: LocalEmbeddingExecutionPolicy
    plan: LocalEmbeddingSourcePlan
    request: LocalEmbeddingWorkflowRequestV11
    association: LocalEmbeddingLaunchAssociation
    native_input: IncrementalEmbeddingInput
    result: IncrementalEmbeddingResult
    completions: tuple[EmbeddingEncodingCompletedEvent, ...]


def native_fixture(
    *seeds: str, owned_seeds: tuple[str, ...] | None = None, device: Literal["CPU", "CUDA"] = "CPU"
) -> NativeAdmissionFixture:
    profile = runtime_profile(device)
    recipe = view_recipe()
    namespace = EmbeddingIndexNamespace(
        storage_partition="synthetic-shared",
        space_sha256=profile.space.space_sha256,
        view="CONTENT_ONLY",
        recipe_sha256=recipe.recipe_sha256,
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
    )
    entries = tuple(embedding_entry(seed) for seed in seeds or ("a", "b"))
    sources = tuple(entry.profile.source_basis.source for entry in entries)
    demands = []
    for entry in entries:
        text = experiment_view_text(entry, namespace.view)
        assert text is not None
        demands.append(
            {
                "source_revision_id": entry.profile.source_basis.source.item_revision_id,
                "profile": InferenceTransferProfilePointer.from_profile(entry.profile).model_dump(
                    mode="json"
                ),
                "solution_evidence": entry.profile.source_basis.solution_evidence.model_dump(
                    mode="json"
                ),
                "encoding": encoding_identity(text, profile.space).model_dump(mode="json"),
            }
        )
    plan = LocalEmbeddingSourcePlan.model_validate(
        seal(
            {
                "schema_version": "local-embedding-source-plan/1.0",
                "corpus_id": "corpus_" + "1" * 32,
                "graph_snapshot": entries[0].profile.source_basis.graph_snapshot.model_dump(
                    mode="json"
                ),
                "access_policy_revision_id": "accessrev_" + "d" * 32,
                "access_policy_sha256": sha("d"),
                "namespace": namespace.model_dump(mode="json"),
                "space": profile.space.model_dump(mode="json"),
                "recipe": recipe.model_dump(mode="json"),
                "sources": [source.model_dump(mode="json") for source in sources],
                "demands": demands,
                "missing_solution_report_revision_ids": [],
                "unavailable_views": [],
                "source_set_sha256": population_sha256(sources),
                "encoding_set_sha256": embedding_input_set_sha256(
                    tuple(
                        sorted(
                            (
                                encoding_identity(
                                    experiment_view_text(e, namespace.view) or "", profile.space
                                )
                                for e in entries
                            ),
                            key=lambda x: x.encoding_sha256,
                        )
                    )
                ),
            },
            "plan_sha256",
        )
    )
    policy = LocalEmbeddingExecutionPolicy.model_validate(
        seal(
            {
                "schema_version": "local-embedding-execution-policy/1.0",
                "purpose": "LOCAL_EMBEDDING",
                "admission_mode": "OPERATOR_SEED_ONLY",
                "workflow_definition_sha256": sha("9"),
                "profiles": [profile.model_dump(mode="json")],
                "default_device": device,
                "gpu_busy": "WAIT",
                "created_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "policy_sha256",
        )
    )
    request = LocalEmbeddingWorkflowRequestV11.model_validate(
        seal(
            {
                "schema_version": "local-embedding-workflow-request/1.1",
                "request_name": "LOCAL_EMBEDDING_WORKFLOW_REQUEST",
                "purpose": "LOCAL_EMBEDDING",
                "workflow_definition_key": "local-embedding-index",
                "workflow_definition_version": "1.0.0",
                "workflow_definition_sha256": policy.workflow_definition_sha256,
                "actor_context": {
                    "kind": "OPERATOR",
                    "operator_id": "operator_" + "1" * 32,
                    "requester_permissions_sha256": sha("1"),
                },
                **{
                    name: getattr(plan, name).model_dump(mode="json")
                    if hasattr(getattr(plan, name), "model_dump")
                    else getattr(plan, name)
                    for name in (
                        "corpus_id",
                        "graph_snapshot",
                        "access_policy_revision_id",
                        "access_policy_sha256",
                        "namespace",
                        "space",
                    )
                },
                "runtime_bundle": profile.runtime_bundle.model_dump(mode="json"),
                "source_plan": member(
                    "source-plan.json",
                    LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
                    plan.model_dump(mode="json"),
                    "2",
                ).model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
                "native_execution_policy": member(
                    "policy.json",
                    LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
                    policy.model_dump(mode="json"),
                    "3",
                ).model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
                "resource_profile": profile.resource_profile.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    owned_entries = tuple(
        entry
        for seed, entry in zip(seeds or ("a", "b"), entries, strict=True)
        if owned_seeds is None or seed in owned_seeds
    )
    input_body = embedding_input(
        *(experiment_view_text(e, namespace.view) or "" for e in owned_entries), space=profile.space
    ).model_dump(mode="json")
    input_body.update(
        batch_size=profile.resource_profile.batch_size, threads=profile.resource_profile.threads
    )
    native_input = IncrementalEmbeddingInput.model_validate(seal(input_body, "request_sha256"))
    jobs = []
    for ordinal, row in enumerate(native_input.rows, start=4):
        job_request = EmbeddingEncodingJobRequest.model_validate(
            seal(
                {
                    "schema_version": "embedding-encoding-job/1.0",
                    "record_type": "REQUEST",
                    "purpose": "LOCAL_EMBEDDING",
                    "space": profile.space.model_dump(mode="json"),
                    "encoding": row.encoding.model_dump(mode="json"),
                },
                "request_sha256",
            )
        )
        seed = f"{ordinal:x}"
        jobs.append(
            LocalEmbeddingOwnedJob.model_validate(
                {
                    "job_reference": {
                        "job_id": "job_" + seed * 32,
                        "request_sha256": job_request.request_sha256,
                        "allocated_artifact_id": "artifact_" + seed * 32,
                        "allocated_artifact_revision_id": "rev_" + seed * 32,
                    },
                    "request": job_request.model_dump(mode="json"),
                }
            )
        )
    intent = LocalEmbeddingLaunchIntent.model_validate(
        seal(
            {
                "workflow_id": "workflow_" + "1" * 32,
                "step_run_id": "steprun_" + "2" * 32,
                "step_key": "encode_batch",
                "attempt": 1,
                "native_launch_job_id": native_input.job_id,
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
                "resource_profile_sha256": profile.resource_profile.resource_profile_sha256,
                "command_id": "wfcmd_" + "3" * 32,
                "runner_id": "synthetic-runner",
                "lease_generation": 1,
            },
            "intent_sha256",
        )
    )
    association = LocalEmbeddingLaunchAssociation.model_validate(
        seal(
            {
                "schema_version": "embedding-encoding-job/1.0",
                "record_type": "LAUNCH_ASSOCIATION",
                "intent": intent.model_dump(mode="json"),
                "owned_jobs": [job.model_dump(mode="json") for job in jobs],
                "owned_input": member(
                    "input.json",
                    "eom://schemas/knowledge/incremental-embedding-input/1.0",
                    native_input.model_dump(mode="json"),
                    "7",
                ).model_dump(mode="json"),
                "owned_input_request_sha256": native_input.request_sha256,
                "owned_input_set_sha256": native_input.input_set_sha256,
            },
            "association_sha256",
        )
    )
    result = embedding_result(native_input)
    completions = []
    for row_index, job in enumerate(jobs):
        shard_pointer = member(
            "shard.json",
            "eom://schemas/knowledge/embedding-vector-shard/1.0",
            result.shard.model_dump(mode="json"),
        )
        binary = shard_pointer.model_dump(mode="json") | {
            "member_path": "vectors.f32",
            "schema_ref": "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
            "media_type": "application/octet-stream",
            "sha256": result.shard.binary.sha256,
        }
        receipt = seal(
            {
                "native_launch_job_id": native_input.job_id,
                "result_manifest": member(
                    "result.json",
                    "eom://schemas/knowledge/incremental-embedding-result/1.0",
                    result.model_dump(mode="json"),
                ).model_dump(mode="json"),
                "result_sha256": result.result_sha256,
                "shard_manifest": shard_pointer.model_dump(mode="json"),
                "shard_sha256": result.shard.shard_sha256,
                "binary_member": binary,
                "row_ref": {
                    "shard_manifest": shard_pointer.model_dump(mode="json"),
                    "row_index": row_index,
                    "encoding_sha256": job.request.encoding.encoding_sha256,
                },
            },
            "receipt_sha256",
        )
        completions.append(
            EmbeddingEncodingCompletedEvent.model_validate(
                seal(
                    {
                        "schema_version": "embedding-encoding-job/1.0",
                        "record_type": "COMPLETED",
                        "owned_job": job.model_dump(mode="json"),
                        "intent": intent.model_dump(mode="json"),
                        "launch_association_sha256": association.association_sha256,
                        "receipt": receipt,
                    },
                    "event_sha256",
                )
            )
        )
    return NativeAdmissionFixture(
        entries, policy, plan, request, association, native_input, result, tuple(completions)
    )
