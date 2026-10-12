"""Synthetic immutable embedding values; no vectors, authorization or model execution."""

from __future__ import annotations

from typing import Any, Literal

from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingBinaryMember,
    EmbeddingEncodingIdentity,
    EmbeddingExecutionRuntime,
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingSpace,
    EmbeddingTextInput,
    EmbeddingVectorRowRef,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    embedding_input_set_sha256,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentView,
    ExperimentViewRecipe,
    StagedExperimentEntry,
    experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_experiment_fixtures import entry as experiment_entry
from tests.unit.inference_transfer_fixtures import NOW, embedding_model, sha

PARTITION = "synthetic-shared"
JOB_ID = "job_" + "1" * 32


def seal(body: dict[str, Any], field: str) -> dict[str, Any]:
    value = {name: item for name, item in body.items() if name != field}
    return value | {field: content_sha256(value)}


def embedding_entry(seed: str = "a", *, source_class: str = "PAST_EXAM") -> StagedExperimentEntry:
    body = experiment_entry(seed, source_class=source_class).model_dump(mode="json")
    body["profile"]["extraction"]["extractor_version"] = "accepted-solution-comparison/1.0"
    body["profile"] = seal(body["profile"], "profile_sha256")
    return StagedExperimentEntry.model_validate(body)


def execution_runtime(
    device: Literal["CPU", "CUDA"] = "CPU", *, fingerprint: str | None = None
) -> EmbeddingExecutionRuntime:
    return EmbeddingExecutionRuntime(
        device=device,
        precision="FLOAT32",
        tf32_enabled=False,
        execution_runtime_sha256=fingerprint
        or content_sha256({"device": device, "implementation": "synthetic-no-execution/1.0"}),
    )


def embedding_space(
    *,
    device: Literal["CPU", "CUDA"] = "CPU",
    purpose: Literal["QUERY", "DOCUMENT"] = "DOCUMENT",
    fingerprint: str | None = None,
) -> EmbeddingSpace:
    body = {
        "model_spec": embedding_model("intfloat/multilingual-e5-small").model_dump(mode="json"),
        "purpose": purpose,
        "runtime": execution_runtime(device, fingerprint=fingerprint).model_dump(mode="json"),
    }
    return EmbeddingSpace.model_validate(seal(body, "space_sha256"))


def encoding_identity(
    text: str,
    space: EmbeddingSpace | None = None,
    *,
    storage_partition: str = PARTITION,
) -> EmbeddingEncodingIdentity:
    actual_space = space or embedding_space()
    return EmbeddingEncodingIdentity.model_validate(
        seal(
            {
                "storage_partition": storage_partition,
                "space_sha256": actual_space.space_sha256,
                "input_text_sha256": content_sha256(text),
            },
            "encoding_sha256",
        )
    )


def view_recipe() -> ExperimentViewRecipe:
    body = ExperimentViewRecipe.model_construct(recipe_sha256=sha()).model_dump(
        mode="json", exclude={"recipe_sha256"}
    )
    return ExperimentViewRecipe.model_validate(seal(body, "recipe_sha256"))


def embedding_input(
    *texts: str,
    space: EmbeddingSpace | None = None,
    storage_partition: str = PARTITION,
    job_id: str = JOB_ID,
) -> IncrementalEmbeddingInput:
    actual_space = space or embedding_space()
    rows = tuple(
        sorted(
            (
                EmbeddingTextInput(
                    encoding=encoding_identity(
                        text, actual_space, storage_partition=storage_partition
                    ),
                    text=text,
                )
                for text in texts or ("마찰이 없다는 조건과 보존 관계를 연결한다.",)
            ),
            key=lambda row: row.encoding.encoding_sha256,
        )
    )
    body = {
        "schema_version": "incremental-embedding-input/1.0",
        "job_id": job_id,
        "space": actual_space.model_dump(mode="json"),
        "rows": [row.model_dump(mode="json") for row in rows],
        "batch_size": 2,
        "threads": 1,
        "input_set_sha256": embedding_input_set_sha256(tuple(row.encoding for row in rows)),
    }
    return IncrementalEmbeddingInput.model_validate(seal(body, "request_sha256"))


def vector_shard(
    rows: tuple[EmbeddingEncodingIdentity, ...] | None = None,
    *,
    space: EmbeddingSpace | None = None,
) -> EmbeddingVectorShardManifest:
    actual_space = space or embedding_space()
    actual_rows = tuple(
        sorted(
            rows
            or (encoding_identity("마찰이 없다는 조건과 보존 관계를 연결한다.", actual_space),),
            key=lambda row: row.encoding_sha256,
        )
    )
    binary = EmbeddingBinaryMember(
        member_path="vectors.f32",
        schema_ref="eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
        media_type="application/octet-stream",
        sha256=sha("e"),
        byte_count=len(actual_rows) * actual_space.model_spec.dimension * 4,
        dtype="FLOAT32",
        byte_order="LITTLE_ENDIAN",
        layout="ROW_MAJOR",
    )
    body = {
        "schema_version": "embedding-vector-shard/1.0",
        "space": actual_space.model_dump(mode="json"),
        "rows": [row.model_dump(mode="json") for row in actual_rows],
        "input_set_sha256": embedding_input_set_sha256(actual_rows),
        "binary": binary.model_dump(mode="json"),
        "dimension": actual_space.model_spec.dimension,
        "row_count": len(actual_rows),
    }
    return EmbeddingVectorShardManifest.model_validate(seal(body, "shard_sha256"))


def shard_pointer(shard: EmbeddingVectorShardManifest, seed: str = "a") -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path="shard.json",
        schema_ref=SHARD_SCHEMA_REF,
        media_type="application/json",
        sha256=content_sha256(shard.model_dump(mode="json")),
    )


def index_pointer(index: EmbeddingIndexManifest, seed: str = "b") -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path="index.json",
        schema_ref=INDEX_SCHEMA_REF,
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )


def source_binding(
    staged: StagedExperimentEntry | None = None,
    *,
    view: ExperimentView = "METADATA_ONLY",
    recipe: ExperimentViewRecipe | None = None,
    space: EmbeddingSpace | None = None,
    shard: EmbeddingVectorShardManifest | None = None,
    pointer: ArtifactMemberPointer | None = None,
) -> EmbeddingSourceBinding:
    actual_entry, actual_space = staged or embedding_entry(), space or embedding_space()
    text = experiment_view_text(actual_entry, view)
    if text is None:
        raise ValueError("a fixture binding requires an available exact view")
    encoding = encoding_identity(text, actual_space)
    actual_shard = shard or vector_shard((encoding,), space=actual_space)
    actual_pointer = pointer or shard_pointer(actual_shard)
    row_index = next(
        index
        for index, row in enumerate(actual_shard.rows)
        if row.encoding_sha256 == encoding.encoding_sha256
    )
    basis = actual_entry.profile.source_basis
    body = {
        "schema_version": "embedding-source-binding/1.0",
        "source": basis.source.model_dump(mode="json"),
        "profile": InferenceTransferProfilePointer.from_profile(actual_entry.profile).model_dump(
            mode="json"
        ),
        "solution_evidence": basis.solution_evidence.model_dump(mode="json"),
        "graph_snapshot": basis.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": "accessrev_" + "d" * 32,
        "policy_sha256": sha("d"),
        "recipe": (recipe or view_recipe()).model_dump(mode="json"),
        "view": view,
        "projection_version": "accepted-solution-comparison/1.0",
        "encoding": encoding.model_dump(mode="json"),
        "row_ref": EmbeddingVectorRowRef(
            shard_manifest=actual_pointer,
            row_index=row_index,
            encoding_sha256=encoding.encoding_sha256,
        ).model_dump(mode="json"),
    }
    return EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))


def index_manifest(
    *bindings: EmbeddingSourceBinding,
    shards: tuple[ArtifactMemberPointer, ...] | None = None,
    space: EmbeddingSpace | None = None,
    view: ExperimentView = "METADATA_ONLY",
    previous_manifest: ArtifactMemberPointer | None = None,
    revision_seed: str = "2",
) -> EmbeddingIndexManifest:
    actual_bindings = tuple(
        sorted(bindings or (source_binding(),), key=lambda value: value.source.item_revision_id)
    )
    unique_pointers = {
        value.row_ref.shard_manifest.model_dump_json(): value.row_ref.shard_manifest
        for value in actual_bindings
    }
    actual_shards = tuple(
        sorted(
            shards or tuple(unique_pointers.values()),
            key=lambda pointer: (
                pointer.artifact_id,
                pointer.artifact_revision_id,
                pointer.member_path,
                pointer.sha256,
            ),
        )
    )
    body = {
        "schema_version": "embedding-index-manifest/1.0",
        "index_id": "embeddingindex_" + "1" * 32,
        "index_revision_id": "embeddingindexrev_" + revision_seed * 32,
        "previous_manifest": (
            previous_manifest.model_dump(mode="json") if previous_manifest is not None else None
        ),
        "storage_partition": PARTITION,
        "space": (space or embedding_space()).model_dump(mode="json"),
        "view": view,
        "recipe": actual_bindings[0].recipe.model_dump(mode="json"),
        "shards": [pointer.model_dump(mode="json") for pointer in actual_shards],
        "bindings": [binding.model_dump(mode="json") for binding in actual_bindings],
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    return EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))


def embedding_result(
    request: IncrementalEmbeddingInput | None = None,
    *,
    shard: EmbeddingVectorShardManifest | None = None,
) -> IncrementalEmbeddingResult:
    actual = request or embedding_input()
    body = {
        "schema_version": "incremental-embedding-result/1.0",
        "job_id": actual.job_id,
        "request_sha256": actual.request_sha256,
        "input_set_sha256": actual.input_set_sha256,
        "shard": (
            shard or vector_shard(tuple(row.encoding for row in actual.rows), space=actual.space)
        ).model_dump(mode="json"),
    }
    return IncrementalEmbeddingResult.model_validate(seal(body, "result_sha256"))
