"""Synthetic metadata only; no corpus authority, installed proof, ML or device execution."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from eom_catalog_contracts.embedding_device_benchmark import (
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    BenchmarkAck,
    BenchmarkCapacityInput,
    BenchmarkCheckpoint,
    BenchmarkDevice,
    BenchmarkDeviceResult,
    BenchmarkExecutionPolicy,
    BenchmarkInvocationTimings,
    BenchmarkLaunchReceipt,
    BenchmarkLocalInput,
    BenchmarkLocalVector,
    BenchmarkModelFamily,
    BenchmarkNearTieReference,
    BenchmarkNumericalEvidence,
    BenchmarkOwnerGateEvidence,
    BenchmarkOwnerRequest,
    BenchmarkOwnerResult,
    BenchmarkPurposeSpaces,
    BenchmarkRecipe,
    BenchmarkResourceEvidence,
    BenchmarkRowRef,
    BenchmarkRuntime,
    BenchmarkSampleKey,
    BenchmarkSession,
    BenchmarkStagedInputs,
    BenchmarkSyntheticCase,
    BenchmarkTextRow,
    BenchmarkTimingEvidence,
    BenchmarkTokenStratum,
    BenchmarkTokenWitness,
    BenchmarkVectorEvidence,
    BenchmarkVectorSample,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    benchmark_input_set_sha256,
    benchmark_model_family_sha256,
    benchmark_public_fixture_sha256,
    benchmark_row_key,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProof,
    EmbeddingRuntimeProfile,
    embedding_numeric_library_versions,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    RUNTIME_BUNDLE_SCHEMA_REF,
    EmbeddingNumericalRecipe,
    EmbeddingNumericalRuntimeDescriptor,
    EmbeddingNumericImplementationPin,
    EmbeddingRuntimeBundlePointer,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.embedding_installed_runtime_fixtures import proof_pointer, runtime_proof
from tests.unit.inference_transfer_embedding_fixtures import seal, view_recipe
from tests.unit.inference_transfer_experiment_fixtures import entry
from tests.unit.inference_transfer_fixtures import embedding_model, sha

BENCHMARK_ID = "embeddingbenchmark_" + "1" * 32
BENCHMARK_REVISION = "embeddingbenchmarkrev_" + "2" * 32


def artifact_member(
    definition: str, name: str, *, seed: str = "a", digest: str | None = None
) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path=name,
        schema_ref=f"{EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF}#/$defs/{definition}",
        media_type="application/json",
        sha256=digest or sha(seed),
    )


def token_digest(count: int) -> str:
    return content_sha256({"input_ids": [101] + [42] * (count - 2) + [102], "token_type_ids": None})


@lru_cache(maxsize=1)
def benchmark_family() -> BenchmarkModelFamily:
    model_body = embedding_model().model_dump(mode="json")
    model_body["upstream_revision"] = "9a0624b896d81da7492a910ffa53731274b6cf3d"
    model_body["maximum_tokens"] = 2048
    versions = dict(embedding_numeric_library_versions("CPU_INDEX_FP32"))
    model_body["runtime_versions"] = [
        {"name": pin["name"], "version": versions[pin["name"]]}
        for pin in model_body["runtime_versions"]
    ]
    model = LocalEmbeddingModelSpec.model_validate(seal(model_body, "manifest_sha256"))
    implementations = tuple(
        EmbeddingNumericImplementationPin.model_validate(
            {
                "component": component,
                "recipe_version": "synthetic-no-execution/1.0",
                "sha256": content_sha256(component),
            }
        )
        for component in ("FLOAT32_CODEC", "HOST_L2", "OFFLINE_ENCODER")
    )
    recipe = EmbeddingNumericalRecipe(cublas_workspace=None, batch_size=4, threads=4)
    return BenchmarkModelFamily(
        model=model,
        implementations=implementations,
        recipe=recipe,
        family_sha256=benchmark_model_family_sha256(model, implementations, recipe),
    )


@lru_cache(maxsize=2)
def benchmark_runtime(device: BenchmarkDevice) -> BenchmarkRuntime:
    profile: EmbeddingRuntimeProfile = "CPU_INDEX_FP32" if device == "CPU" else "CUDA_INDEX_FP32"
    proof_body = runtime_proof(profile).model_dump(mode="json")
    seed = "3" if device == "CPU" else "4"
    proof_body["proof_id"] = "embeddingruntimeproof_" + seed * 32
    proof_body["proof_revision_id"] = "embeddingruntimeproofrev_" + seed * 32
    proof = EmbeddingInstalledRuntimeProof.model_validate(seal(proof_body, "proof_sha256"))
    family = benchmark_family()
    numeric = EmbeddingNumericalRuntimeDescriptor.model_validate(
        seal(
            {
                "schema_version": "embedding-numerical-runtime/1.0",
                "python_version": proof.python_version,
                "implementations": [pin.model_dump(mode="json") for pin in family.implementations],
                "libraries": [
                    {
                        "name": pin.name,
                        "version": pin.version,
                        "distribution_sha256": pin.archive.sha256,
                    }
                    for pin in proof.numeric_libraries
                ],
                "device": proof.device_capture.numeric_device.model_dump(mode="json"),
                "recipe": EmbeddingNumericalRecipe(
                    cublas_workspace=None if device == "CPU" else ":4096:8", batch_size=4, threads=4
                ).model_dump(mode="json"),
                "torch_build_cuda_version": proof.torch_build_cuda_version,
            },
            "runtime_sha256",
        )
    )
    model_body = family.model.model_dump(mode="json")
    model_body["model_revision_id"] = "embeddingmodelrev_" + seed * 32
    versions = dict(embedding_numeric_library_versions(profile))
    model_body["runtime_versions"] = [
        {"name": pin["name"], "version": versions[pin["name"]]}
        for pin in model_body["runtime_versions"]
    ]
    model = LocalEmbeddingModelSpec.model_validate(seal(model_body, "manifest_sha256"))

    def space(purpose: str) -> EmbeddingSpace:
        return EmbeddingSpace.model_validate(
            seal(
                {
                    "model_spec": model.model_dump(mode="json"),
                    "purpose": purpose,
                    "runtime": {
                        "device": device,
                        "precision": "FLOAT32",
                        "tf32_enabled": False,
                        "execution_runtime_sha256": numeric.runtime_sha256,
                    },
                },
                "space_sha256",
            )
        )

    raw_sha = content_sha256({"synthetic_bundle_raw": device})
    bundle = EmbeddingRuntimeBundlePointer(
        bundle_id="embeddingbundle_" + seed * 32,
        bundle_revision_id="embeddingbundlerev_" + seed * 32,
        bundle_sha256=content_sha256({"synthetic_bundle": device}),
        bundle_raw_sha256=raw_sha,
        manifest_member=ArtifactMemberPointer(
            artifact_id="artifact_" + seed * 32,
            artifact_revision_id="rev_" + seed * 32,
            member_path="bundle.json",
            schema_ref=RUNTIME_BUNDLE_SCHEMA_REF,
            media_type="application/json",
            sha256=raw_sha,
        ),
    )
    return BenchmarkRuntime(
        profile=profile,
        bundle=bundle,
        installed_proof=proof_pointer(proof),
        numerical_runtime=numeric,
        spaces=BenchmarkPurposeSpaces(document=space("DOCUMENT"), query=space("QUERY")),
    )


@lru_cache(maxsize=1)
def staged_inputs() -> BenchmarkStagedInputs:
    documents: list[BenchmarkTextRow] = []
    queries: list[BenchmarkTextRow] = []
    for index, seed in enumerate("abcdef"):
        profile = InferenceTransferProfilePointer.from_profile(entry(seed).profile)
        count = (10, 10, 200, 200, 1000, 1000)[index]
        for view in ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"):
            text = f"합성 fixture {seed} {view}: 실제 tokenizer/원본 인가 증거가 아니다."
            row = BenchmarkRowRef.model_validate(
                seal(
                    {
                        "profile": profile.model_dump(mode="json"),
                        "view": view,
                        "purpose": "DOCUMENT",
                        "input_text_sha256": content_sha256(text),
                    },
                    "row_sha256",
                )
            )
            documents.append(
                BenchmarkTextRow(
                    row=row, text=text, token_count=count, token_ids_sha256=token_digest(count)
                )
            )
            if seed in "ab" and view == "CONTENT_ONLY":
                query = BenchmarkRowRef.model_validate(
                    seal({**row.model_dump(mode="json"), "purpose": "QUERY"}, "row_sha256")
                )
                queries.append(
                    BenchmarkTextRow(
                        row=query,
                        text=text,
                        token_count=count,
                        token_ids_sha256=token_digest(count),
                    )
                )
    doc_tuple = tuple(sorted(documents, key=lambda text: benchmark_row_key(text.row)))
    query_tuple = tuple(sorted(queries, key=lambda text: benchmark_row_key(text.row)))
    recipe = view_recipe()
    texts = (
        "공개 합성 한국어",
        "F = ma",
        "36 km/h = 10 m/s",
        "힘이 작용하지 않는다",
        "정확히 같은 합성문장",
        "정확히 같은 합성문장",
        "",
        "초과 synthetic " * 2049,
    )
    cases = tuple(
        BenchmarkSyntheticCase(
            case_ordinal=index,
            text=value,
            input_text_sha256=content_sha256(value),
            token_count=0 if index == 7 else 2049 if index == 8 else 10,
            token_ids_sha256=None if index == 7 else token_digest(2049 if index == 8 else 10),
            expected="EMPTY_REJECTED"
            if index == 7
            else "OVERFLOW_REJECTED"
            if index == 8
            else "VALID",
        )
        for index, value in enumerate(texts, 1)
    )
    capacity_text = "합성 capacity 값, 실제 tokenizer2048 증거 아님 " * 2048
    capacity = BenchmarkCapacityInput(
        text=capacity_text,
        input_text_sha256=content_sha256(capacity_text),
        token_ids_sha256=token_digest(2048),
    )
    return BenchmarkStagedInputs(
        benchmark_id=BENCHMARK_ID,
        benchmark_revision_id=BENCHMARK_REVISION,
        view_recipe=recipe,
        documents=doc_tuple,
        queries=query_tuple,
        synthetic_cases=cases,
        capacity=capacity,
        public_fixture_sha256=benchmark_public_fixture_sha256(cases, capacity),
        input_set_sha256=benchmark_input_set_sha256(doc_tuple, query_tuple, recipe),
    )


@lru_cache(maxsize=1)
def benchmark_recipe() -> BenchmarkRecipe:
    body = BenchmarkRecipe.model_construct(
        token_strata=(
            BenchmarkTokenStratum(minimum_tokens=1, maximum_tokens=128, profile_count=2),
            BenchmarkTokenStratum(minimum_tokens=129, maximum_tokens=512, profile_count=2),
            BenchmarkTokenStratum(minimum_tokens=513, maximum_tokens=2048, profile_count=2),
        ),
        recipe_sha256=sha(),
        public_fixture_sha256=staged_inputs().public_fixture_sha256,
    ).model_dump(mode="json")
    return BenchmarkRecipe.model_validate(seal(body, "recipe_sha256"))


@lru_cache(maxsize=1)
def benchmark_policy() -> BenchmarkExecutionPolicy:
    body = BenchmarkExecutionPolicy.model_construct(
        policy_id="embeddingbenchmarkpolicy_" + "5" * 32,
        policy_revision_id="embeddingbenchmarkpolicyrev_" + "6" * 32,
        policy_sha256=sha(),
    ).model_dump(mode="json")
    return BenchmarkExecutionPolicy.model_validate(seal(body, "policy_sha256"))


@lru_cache(maxsize=1)
def owner_request() -> BenchmarkOwnerRequest:
    inputs = staged_inputs()
    sources = []
    for index, seed in enumerate("abcdef"):
        current = entry(seed).profile
        sources.append(
            {
                "profile": InferenceTransferProfilePointer.from_profile(current).model_dump(
                    mode="json"
                ),
                "source": current.source_basis.source.model_dump(mode="json"),
                "solution_evidence": current.source_basis.solution_evidence.model_dump(mode="json"),
                "selection_view": "CONTENT_ONLY",
                "selection_token_count": (10, 10, 200, 200, 1000, 1000)[index],
            }
        )
    body = {
        "schema_version": "embedding-device-benchmark-request/1.0",
        "kind": "OWNER_REQUEST",
        "purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK",
        "benchmark_id": BENCHMARK_ID,
        "benchmark_revision_id": BENCHMARK_REVISION,
        "operator_audit_id": "synthetic-audit-not-authority",
        "graph_snapshot": entry().profile.source_basis.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": "accessrev_" + "7" * 32,
        "policy_sha256": sha("7"),
        "sources": sources,
        "document_rows": [text.row.model_dump(mode="json") for text in inputs.documents],
        "query_rows": [text.row.model_dump(mode="json") for text in inputs.queries],
        "input_manifest": artifact_member(
            "stagedInputs",
            "benchmark-inputs.json",
            digest=sha256_bytes(canonical_json_bytes(inputs.model_dump(mode="json"))),
        ).model_dump(mode="json"),
        "input_set_sha256": inputs.input_set_sha256,
        "view_recipe": inputs.view_recipe.model_dump(mode="json"),
        "family": benchmark_family().model_dump(mode="json"),
        "cpu": benchmark_runtime("CPU").model_dump(mode="json"),
        "cuda": benchmark_runtime("CUDA").model_dump(mode="json"),
        "recipe": benchmark_recipe().model_dump(mode="json"),
        "execution_policy": benchmark_policy().model_dump(mode="json"),
    }
    return BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))


def worker_invocation(ordinal: int = 1) -> BenchmarkWorkerInvocation:
    request, inputs = owner_request(), staged_inputs()
    device: BenchmarkDevice = "CPU" if ordinal in (1, 4, 5) else "CUDA"
    raw = canonical_json_bytes(inputs.model_dump(mode="json"))
    body = {
        "schema_version": "embedding-device-benchmark-invocation/1.0",
        "kind": "WORKER_INVOCATION",
        "purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK",
        "benchmark_id": BENCHMARK_ID,
        "benchmark_revision_id": BENCHMARK_REVISION,
        "job_id": "job_" + str(ordinal) * 32,
        "execution_id": str(ordinal) * 32,
        "owner_request_sha256": request.request_sha256,
        "launch_ordinal": ordinal,
        "device": device,
        "local_input": BenchmarkLocalInput(
            sha256=sha256_bytes(raw), byte_count=len(raw)
        ).model_dump(mode="json"),
        "input_set_sha256": inputs.input_set_sha256,
        "family": request.family.model_dump(mode="json"),
        "runtime": (request.cpu if device == "CPU" else request.cuda).model_dump(mode="json"),
        "recipe": request.recipe.model_dump(mode="json"),
        "execution_policy": request.execution_policy.model_dump(mode="json"),
    }
    return BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))


def session(ordinal: int = 1) -> BenchmarkSession:
    invocation = worker_invocation(ordinal)
    checkpoints: list[BenchmarkCheckpoint] = []
    acks: list[BenchmarkAck] = []
    for sequence in range(1, 22 if ordinal in (1, 2) else 2):
        query, remainder = divmod(sequence - 2, 10) if sequence != 1 else (-1, 0)
        repetition, ready = divmod(remainder, 2)
        phase = "COLD_READY" if sequence == 1 else "QUERY_READY" if ready else "QUERY_PREPARED"
        vector = (
            None
            if phase == "QUERY_PREPARED"
            else BenchmarkLocalVector.model_validate(
                {
                    "member_name": "cold-documents.f32"
                    if sequence == 1
                    else f"query-{query + 1}-{repetition + 1}.f32",
                    "sha256": content_sha256({"synthetic_checkpoint": sequence}),
                    "byte_count": 18 * 4096 if sequence == 1 else 4096,
                    "row_count": 18 if sequence == 1 else 1,
                    "purpose": "DOCUMENT" if sequence == 1 else "QUERY",
                    "space_sha256": invocation.runtime.spaces.document.space_sha256
                    if sequence == 1
                    else invocation.runtime.spaces.query.space_sha256,
                }
            )
        )
        body = {
            "schema_version": "embedding-device-benchmark-checkpoint/1.0",
            "kind": "LOCAL_CHECKPOINT",
            "execution_id": invocation.execution_id,
            "invocation_sha256": invocation.invocation_sha256,
            "sequence": sequence,
            "phase": phase,
            "query_ordinal": None if sequence == 1 else query + 1,
            "query_repetition": None if sequence == 1 else repetition + 1,
            "vector": None if vector is None else vector.model_dump(mode="json"),
            "encode_duration_ns": None if phase == "QUERY_PREPARED" else 1000000,
        }
        checkpoint = BenchmarkCheckpoint.model_validate(seal(body, "checkpoint_sha256"))
        checkpoints.append(checkpoint)
        ack = checkpoint.model_dump(
            mode="json", exclude={"schema_version", "kind", "vector", "encode_duration_ns"}
        ) | {"schema_version": "embedding-device-benchmark-ack/1.0", "kind": "OWNER_CONTINUE"}
        acks.append(BenchmarkAck.model_validate(ack))
    return BenchmarkSession.model_validate(
        seal(
            {
                "schema_version": "embedding-device-benchmark-session/1.0",
                "execution_id": invocation.execution_id,
                "invocation_sha256": invocation.invocation_sha256,
                "launch_ordinal": ordinal,
                "checkpoints": [cp.model_dump(mode="json") for cp in checkpoints],
                "acks": [ack.model_dump(mode="json") for ack in acks],
            },
            "session_sha256",
        )
    )


def invocation_timings(ordinal: int = 1) -> BenchmarkInvocationTimings:
    invocation = worker_invocation(ordinal)
    body = {
        "schema_version": "embedding-device-benchmark-invocation-timings/1.0",
        "invocation_sha256": invocation.invocation_sha256,
        "launch_ordinal": ordinal,
        "device": invocation.device,
        "startup_ns": 1000000,
        "load_hash_ns": 1000000,
        "cold_encode_ns": 1000000,
        "warmup_count": int(ordinal in (1, 2)),
        "warm_encode_ns": [1000000] * 5 if ordinal in (1, 2) else [],
        "query_encode_ns": [
            {"query_ordinal": q, "repetition": r, "encode_ns": 1000000}
            for q in (1, 2)
            for r in range(1, 6)
        ]
        if ordinal in (1, 2)
        else [],
    }
    return BenchmarkInvocationTimings.model_validate(seal(body, "timing_sha256"))


def timing_evidence(device: BenchmarkDevice = "CPU") -> BenchmarkTimingEvidence:
    ns = 1000999
    convert = ns // 1000 if device == "CPU" else (ns + 999) // 1000
    total = ns * 3
    total_us = total // 1000 if device == "CPU" else (total + 999) // 1000
    body = {
        "schema_version": "embedding-device-benchmark-timing-evidence/1.0",
        "device": device,
        "cold": [
            {
                "launch_ordinal": ordinal,
                "end_to_end_ns": total,
                "startup_ns": ns,
                "load_hash_ns": ns,
                "encode_ns": ns,
            }
            for ordinal in ((1, 4, 5) if device == "CPU" else (2, 3, 6))
        ],
        "warm_encode_ns": [ns] * 5,
        "queries": [
            {
                "query_ordinal": q,
                "repetition": r,
                "encode_ns": ns,
                "authorization_ns": ns,
                "end_to_end_ns": total,
            }
            for q in (1, 2)
            for r in range(1, 6)
        ],
        "gate_timings": {
            "device": device,
            "cold_end_to_end_us": [total_us] * 3,
            "warm_batch_encode_us": [convert] * 5,
            "query_encode_us": [[convert] * 5] * 2,
            "query_end_to_end_us": [[total_us] * 5] * 2,
        },
    }
    return BenchmarkTimingEvidence.model_validate(seal(body, "timing_sha256"))


def insufficient_result() -> BenchmarkOwnerResult:
    request = owner_request()
    body: dict[str, Any] = {
        "schema_version": "embedding-device-benchmark-result/1.0",
        "kind": "OWNER_RESULT",
        "purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK",
        "benchmark_id": BENCHMARK_ID,
        "benchmark_revision_id": BENCHMARK_REVISION,
        "request_sha256": request.request_sha256,
        "status": "INSUFFICIENT",
        "reason_codes": ["SOURCE_COVERAGE_INSUFFICIENT"],
        "cpu": None,
        "cuda": None,
        "numerical_evidence": None,
        "near_tie_reference": None,
        "owner_gate_evidence": artifact_member("ownerGateEvidence", "owner-gates.json").model_dump(
            mode="json"
        ),
    }
    return BenchmarkOwnerResult.model_validate(seal(body, "result_sha256"))


def sample_keys(ordinal: int) -> tuple[BenchmarkSampleKey, ...]:
    def key(
        phase: str,
        *,
        repetition: int | None = None,
        query: int | None = None,
        case: int | None = None,
        batch: int = 4,
    ) -> BenchmarkSampleKey:
        return BenchmarkSampleKey.model_validate(
            {
                "phase": phase,
                "repetition": repetition,
                "query_ordinal": query,
                "synthetic_case": case,
                "batch_size": batch,
            }
        )

    cold = key("COLD_DOCUMENT")
    if ordinal not in (1, 2):
        return (cold,)
    return (
        cold,
        *(key("SYNTHETIC", case=case, batch=batch) for case in range(1, 7) for batch in (1, 4)),
        *(key("WARM_DOCUMENT", repetition=repeat) for repeat in range(1, 6)),
        *(
            key("QUERY", query=q, repetition=repeat, batch=1)
            for q in (1, 2)
            for repeat in range(1, 6)
        ),
        *(key("CAPACITY", batch=batch) for batch in (1, 4)),
    )


def vector_samples(ordinal: int = 1) -> tuple[BenchmarkVectorSample, ...]:
    invocation, inputs = worker_invocation(ordinal), staged_inputs()
    keys = sample_keys(ordinal)

    def row_count(key: BenchmarkSampleKey) -> int:
        return 18 if key.phase in ("COLD_DOCUMENT", "WARM_DOCUMENT") else key.batch_size

    supplementary_bytes = sum(
        row_count(key) * 4096
        for key in keys
        if key.phase in ("SYNTHETIC", "WARM_DOCUMENT", "CAPACITY")
    )
    cursor = 0
    result = []
    for key in keys:
        name = (
            "cold-documents.f32"
            if key.phase == "COLD_DOCUMENT"
            else f"query-{key.query_ordinal}-{key.repetition}.f32"
            if key.phase == "QUERY"
            else "supplementary-documents.f32"
        )
        supplementary = name == "supplementary-documents.f32"
        rows = (
            []
            if key.phase in ("SYNTHETIC", "CAPACITY")
            else [inputs.queries[key.query_ordinal - 1].row.row_sha256]
            if key.query_ordinal is not None
            else [text.row.row_sha256 for text in inputs.documents]
        )
        count = row_count(key)
        body = {
            "key": key.model_dump(mode="json"),
            "purpose": "QUERY" if key.phase == "QUERY" else "DOCUMENT",
            "space_sha256": invocation.runtime.spaces.query.space_sha256
            if key.phase == "QUERY"
            else invocation.runtime.spaces.document.space_sha256,
            "ordered_rows": rows,
            "binary": {
                "member_name": name,
                "sha256": content_sha256({"synthetic_f32_member": name, "ordinal": ordinal}),
                "byte_count": supplementary_bytes if supplementary else count * 4096,
                "dtype": "FLOAT32",
                "byte_order": "LITTLE_ENDIAN",
                "layout": "ROW_MAJOR",
            },
            "byte_offset": cursor if supplementary else 0,
            "byte_count": count * 4096,
            "row_count": count,
            "dimension": 1024,
        }
        result.append(BenchmarkVectorSample.model_validate(seal(body, "sample_sha256")))
        if supplementary:
            cursor += count * 4096
    return tuple(result)


def resources(ordinal: int = 1) -> BenchmarkResourceEvidence:
    invocation = worker_invocation(ordinal)
    gpu = 1024 if invocation.device == "CUDA" else None
    capacity = (
        [
            {
                "batch_size": batch,
                "maximum_tokens": 2048,
                "input_text_sha256": staged_inputs().capacity.input_text_sha256,
                "token_ids_sha256": staged_inputs().capacity.token_ids_sha256,
                "peak_rss_bytes": 1024,
                "peak_allocated_gpu_bytes": gpu,
                "peak_reserved_gpu_bytes": gpu,
                "peak_whole_process_gpu_bytes": gpu,
            }
            for batch in (1, 4)
        ]
        if ordinal in (1, 2)
        else []
    )
    body = {
        "schema_version": "embedding-device-benchmark-resources/1.0",
        "invocation_sha256": invocation.invocation_sha256,
        "launch_ordinal": ordinal,
        "device": invocation.device,
        "peak_rss_bytes": 1024,
        "peak_allocated_gpu_bytes": gpu,
        "peak_reserved_gpu_bytes": gpu,
        "peak_whole_process_gpu_bytes": gpu,
        "peak_whole_device_gpu_bytes": gpu,
        "owner_observation_count": 1 if gpu is not None else 0,
        "oom_count": 0,
        "other_consumer_overlap_count": 0,
        "capacity_samples": capacity,
    }
    return BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))


def worker_result(ordinal: int = 1) -> BenchmarkWorkerResult:
    invocation = worker_invocation(ordinal)
    body = {
        "schema_version": "embedding-device-benchmark-worker-result/1.0",
        "kind": "WORKER_RESULT",
        "execution_id": invocation.execution_id,
        "invocation_sha256": invocation.invocation_sha256,
        "launch_ordinal": ordinal,
        "device": invocation.device,
        "status": "COMPLETED",
        "reason_codes": [],
        "vectors": [sample.model_dump(mode="json") for sample in vector_samples(ordinal)],
        "synthetic_rejections": [
            {
                "synthetic_case": case,
                "batch_size": batch,
                "reason": "EMPTY_REJECTED" if case == 7 else "OVERFLOW_REJECTED",
            }
            for case in (7, 8)
            for batch in (1, 4)
        ]
        if ordinal in (1, 2)
        else [],
        "token_witness": {
            "member_name": "token-witness.json",
            "sha256": sha(),
            "byte_count": 100,
            "schema_ref": f"{EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF}#/$defs/tokenWitness",
        },
        "timings": invocation_timings(ordinal).model_dump(mode="json"),
        "resources": resources(ordinal).model_dump(mode="json"),
    }
    return BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))


def cold_token_witness(ordinal: int = 3) -> BenchmarkTokenWitness:
    inputs = staged_inputs()
    batches = []
    for start in range(0, len(inputs.documents), 4):
        texts = inputs.documents[start : start + 4]
        width = max(text.token_count for text in texts)
        rows = [
            {
                "row_sha256": text.row.row_sha256,
                "input_ids": [101]
                + [42] * (text.token_count - 2)
                + [102]
                + [0] * (width - text.token_count),
                "attention_mask": [1] * text.token_count + [0] * (width - text.token_count),
                "token_type_ids": None,
                "token_count": text.token_count,
                "token_ids_sha256": text.token_ids_sha256,
            }
            for text in texts
        ]
        batches.append(
            seal({"purpose": "DOCUMENT", "pad_token_id": 0, "rows": rows}, "batch_sha256")
        )
    sample = seal(
        {"key": sample_keys(ordinal)[0].model_dump(mode="json"), "batches": batches},
        "sample_sha256",
    )
    body = {
        "schema_version": "embedding-device-benchmark-token-witness/1.0",
        "invocation_sha256": worker_invocation(ordinal).invocation_sha256,
        "launch_ordinal": ordinal,
        "samples": [sample],
    }
    return BenchmarkTokenWitness.model_validate(seal(body, "witness_sha256"))


def completed_device(device: BenchmarkDevice) -> BenchmarkDeviceResult:
    ordinals = (1, 4, 5) if device == "CPU" else (2, 3, 6)
    return BenchmarkDeviceResult(
        device=device,
        spaces=benchmark_runtime(device).spaces,
        document_vectors=artifact_member("vectorEvidence", f"{device.lower()}-documents.json"),
        query_vectors=artifact_member("vectorEvidence", f"{device.lower()}-queries.json"),
        token_witness=artifact_member("tokenWitness", "token-witness.json"),
        timing_evidence=artifact_member("timingEvidence", f"{device.lower()}-timings.json"),
        resource_evidence=tuple(
            artifact_member("resources", "resources.json", seed=str(ordinal))
            for ordinal in ordinals
        ),
        timings=timing_evidence(device).gate_timings,
        launch_receipts=tuple(
            artifact_member("launchReceipt", "launch-receipt.json", seed=str(ordinal))
            for ordinal in ordinals
        ),
    )


def measured_result() -> BenchmarkOwnerResult:
    body = insufficient_result().model_dump(mode="json")
    body.update(
        status="MEASURED",
        reason_codes=[],
        cpu=completed_device("CPU").model_dump(mode="json"),
        cuda=completed_device("CUDA").model_dump(mode="json"),
        numerical_evidence=artifact_member(
            "numericalEvidence", "numerical-evidence.json"
        ).model_dump(mode="json"),
        near_tie_reference=artifact_member(
            "nearTieReference", "near-tie-reference.json"
        ).model_dump(mode="json"),
    )
    return BenchmarkOwnerResult.model_validate(seal(body, "result_sha256"))


def owner_gates() -> BenchmarkOwnerGateEvidence:
    gates = (
        "SOURCE_AUTHORIZATION",
        "RUNTIME",
        "NUMERICAL",
        "PERFORMANCE",
        "CAPACITY",
        "SANDBOX",
        "GPU_LEASE",
        "CLEANUP",
        "IMAGE_TRAINER_REGRESSION",
    )
    body = {
        "schema_version": "embedding-device-benchmark-owner-gate-evidence/1.0",
        "request_sha256": owner_request().request_sha256,
        "gates": [
            {
                "gate": gate,
                "status": "NOT_RUN",
                "reason_codes": ["SOURCE_ONLY_NOT_ACTIVATED"],
                "evidence": None,
            }
            for gate in gates
        ],
    }
    return BenchmarkOwnerGateEvidence.model_validate(seal(body, "evidence_sha256"))


def launch_receipt(ordinal: int = 1) -> BenchmarkLaunchReceipt:
    invocation = worker_invocation(ordinal)
    body = {
        "schema_version": "embedding-device-benchmark-launch-receipt/1.0",
        "job_id": invocation.job_id,
        "execution_id": invocation.execution_id,
        "launch_ordinal": ordinal,
        "device": invocation.device,
        "invocation_sha256": invocation.invocation_sha256,
        "observed_runtime_sha256": invocation.runtime.numerical_runtime.runtime_sha256,
        "worker_result": artifact_member("workerResult", "worker-result.json").model_dump(
            mode="json"
        ),
        "session": artifact_member("session", "session.json").model_dump(mode="json"),
        "cleanup": "CONFIRMED",
        "evidence": artifact_member("ownerGateEvidence", "owner-gates.json").model_dump(
            mode="json"
        ),
    }
    return BenchmarkLaunchReceipt.model_validate(seal(body, "receipt_sha256"))


def vector_evidence() -> BenchmarkVectorEvidence:
    invocation = worker_invocation()
    published = []
    for ordinal in (1, 4, 5):
        for sample in vector_samples(ordinal):
            if sample.purpose != "DOCUMENT":
                continue
            pointer = ArtifactMemberPointer(
                artifact_id="artifact_" + str(ordinal) * 32,
                artifact_revision_id="rev_" + str(ordinal) * 32,
                member_path=sample.binary.member_name,
                schema_ref="eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                media_type="application/octet-stream",
                sha256=sample.binary.sha256,
            )
            published.append(
                {
                    "launch_ordinal": ordinal,
                    "sample": sample.model_dump(mode="json"),
                    "binary_member": pointer.model_dump(mode="json"),
                }
            )
    body = {
        "schema_version": "embedding-device-benchmark-vector-evidence/1.0",
        "device": "CPU",
        "purpose": "DOCUMENT",
        "space": invocation.runtime.spaces.document.model_dump(mode="json"),
        "rows": [text.row.model_dump(mode="json") for text in staged_inputs().documents],
        "samples": published,
    }
    return BenchmarkVectorEvidence.model_validate(seal(body, "evidence_sha256"))


def near_tie_reference() -> BenchmarkNearTieReference:
    request = owner_request()
    queries = []
    for ordinal, query in enumerate(request.query_rows, 1):
        candidates = [row for row in request.document_rows if row.profile != query.profile]
        queries.append(
            {
                "query_ordinal": ordinal,
                "query_row": query.model_dump(mode="json"),
                "ordered_candidates": [row.model_dump(mode="json") for row in candidates],
                "clusters": [
                    {
                        "cluster_ordinal": 1,
                        "row_sha256": [row.row_sha256 for row in candidates],
                        "cpu_score_offsets": [index * 8 for index in range(len(candidates))],
                    }
                ],
            }
        )
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "a" * 32,
        member_path="rank-evidence.f64",
        schema_ref="eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0",
        media_type="application/octet-stream",
        sha256=sha(),
    )
    body = {
        "schema_version": "embedding-device-benchmark-near-tie-reference/1.0",
        "request_sha256": request.request_sha256,
        "input_set_sha256": request.input_set_sha256,
        "family_sha256": request.family.family_sha256,
        "cpu_document_space_sha256": request.cpu.spaces.document.space_sha256,
        "cpu_query_space_sha256": request.cpu.spaces.query.space_sha256,
        "score_binary": pointer.model_dump(mode="json"),
        "queries": queries,
    }
    return BenchmarkNearTieReference.model_validate(seal(body, "reference_sha256"))


def numerical_evidence() -> BenchmarkNumericalEvidence:
    request = owner_request()
    body = {
        "schema_version": "embedding-device-benchmark-numerical-evidence/1.0",
        "input_set_sha256": request.input_set_sha256,
        "family_sha256": request.family.family_sha256,
        "score_binary": {
            "member_path": "rank-evidence.f64",
            "schema_ref": "eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0",
            "media_type": "application/octet-stream",
            "sha256": sha(),
            "byte_count": 1280,
            "dtype": "FLOAT64",
            "byte_order": "LITTLE_ENDIAN",
        },
        "near_tie_reference": artifact_member(
            "nearTieReference", "near-tie-reference.json"
        ).model_dump(mode="json"),
        "norm_failures": 0,
        "cosine_failures": 0,
        "component_failures": 0,
        "query_score_failures": 0,
        "wide_gap_order_failures": 0,
        "cluster_order_failures": 0,
        "top5_boundary_failures": 0,
        "same_device_failures": 0,
        "decisions": [
            {
                "query_ordinal": 1,
                "repetition": 1,
                "left_row_sha256": sha("a"),
                "right_row_sha256": sha("b"),
                "cpu_left_offset": 0,
                "cpu_right_offset": 8,
                "cuda_left_offset": 16,
                "cuda_right_offset": 24,
                "gap_class": "NEAR_TIE",
                "order_preserved": True,
                "top5_same_cluster": True,
            }
        ],
    }
    return BenchmarkNumericalEvidence.model_validate(seal(body, "numerical_sha256"))
