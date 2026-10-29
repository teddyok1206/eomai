"""Immutable numerical artifacts and source associations, never authority tokens."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal, Protocol

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, field_validator, model_validator

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentView,
    ExperimentViewRecipe,
    PopulationSource,
    StagedExperimentEntry,
    experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
    TransferText,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
    same_approved_item_source_identity,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.validation import validate_contract

SCHEMA_NAME = "item-inference-transfer-embedding"
SHARD_SCHEMA_REF = "eom://schemas/knowledge/embedding-vector-shard/1.0"
BINDING_SCHEMA_REF = "eom://schemas/knowledge/embedding-source-binding/1.0"
INDEX_SCHEMA_REF = "eom://schemas/knowledge/embedding-index-manifest/1.0"
INPUT_SCHEMA_REF = "eom://schemas/knowledge/incremental-embedding-input/1.0"
RESULT_SCHEMA_REF = "eom://schemas/knowledge/incremental-embedding-result/1.0"
INCREMENTAL_EMBEDDING_RESULT_SCHEMA = "incremental-embedding-result@1.0"
MAX_EMBEDDING_ROWS = 1024
MAX_EMBEDDING_INPUT_BYTES = 64 * 1024**2
type StoragePartition = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


class _EmbeddingContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")


def _hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError(f"{field} differs from canonical embedding content")
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > MAX_EMBEDDING_INPUT_BYTES:
        raise ValueError("embedding metadata exceeds its byte budget")


def _pointer_key(value: ArtifactMemberPointer) -> tuple[str, str, str, str]:
    return value.artifact_id, value.artifact_revision_id, value.member_path, value.sha256


def validate_embedding_manifest_pointer(
    value: ArtifactMemberPointer, schema: str, member: str
) -> None:
    checked = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(value))
    if (
        checked.schema_ref != schema
        or checked.media_type != "application/json"
        or checked.member_path != member
    ):
        raise ValueError("embedding manifest pointer schema, media or member differs")


class EmbeddingExecutionRuntime(_EmbeddingContract):
    """Actual installed execution fingerprint is verified by the owner, not this pure DTO."""

    device: Literal["CPU", "CUDA"]
    precision: Literal["FLOAT32"] = "FLOAT32"
    tf32_enabled: Literal[False] = False
    execution_runtime_sha256: Sha256

    @field_validator("tf32_enabled", mode="before")
    @classmethod
    def exact_disabled_tf32(cls, value: object) -> object:
        if type(value) is not bool or value is not False:
            raise ValueError("TF32 must be the exact boolean false")
        return value


class EmbeddingSpace(_EmbeddingContract):
    model_spec: LocalEmbeddingModelSpec
    purpose: Literal["QUERY", "DOCUMENT"]
    runtime: EmbeddingExecutionRuntime
    space_sha256: Sha256

    @model_validator(mode="after")
    def exact_numerical_recipe(self) -> EmbeddingSpace:
        LocalEmbeddingModelSpec.model_validate(self.model_spec.model_dump(mode="json"))
        EmbeddingExecutionRuntime.model_validate(self.runtime.model_dump(mode="json"))
        _hash(self, "space_sha256")
        return self


class EmbeddingEncodingIdentity(_EmbeddingContract):
    storage_partition: StoragePartition
    space_sha256: Sha256
    input_text_sha256: Sha256
    encoding_sha256: Sha256

    @model_validator(mode="after")
    def exact_encoding_key(self) -> EmbeddingEncodingIdentity:
        _hash(self, "encoding_sha256")
        return self


def embedding_input_set_sha256(rows: tuple[EmbeddingEncodingIdentity, ...]) -> str:
    """Hash exact ordered identities, without deduplication or source authorization."""
    return content_sha256([row.model_dump(mode="json") for row in rows])


def _ordered_rows(
    rows: tuple[EmbeddingEncodingIdentity, ...], space: EmbeddingSpace, expected: str
) -> None:
    keys = tuple(row.encoding_sha256 for row in rows)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("encoding rows must be sorted and unique")
    if len({row.storage_partition for row in rows}) != 1 or any(
        row.space_sha256 != space.space_sha256 for row in rows
    ):
        raise ValueError("encoding rows mix numerical spaces or storage partitions")
    if expected != embedding_input_set_sha256(rows):
        raise ValueError("input set hash differs from exact ordered encoding rows")


class EmbeddingBinaryMember(_EmbeddingContract):
    """Precommit same-file-set descriptor. Binary validation remains an owner adapter duty."""

    member_path: Literal["vectors.f32"] = "vectors.f32"
    schema_ref: Literal["eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"] = (
        "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"
    )
    media_type: Literal["application/octet-stream"] = "application/octet-stream"
    sha256: Sha256
    byte_count: int = Field(ge=4, le=16 * 1024**2, strict=True)
    dtype: Literal["FLOAT32"] = "FLOAT32"
    byte_order: Literal["LITTLE_ENDIAN"] = "LITTLE_ENDIAN"
    layout: Literal["ROW_MAJOR"] = "ROW_MAJOR"


class EmbeddingVectorShardManifest(_EmbeddingContract):
    schema_version: Literal["embedding-vector-shard/1.0"] = "embedding-vector-shard/1.0"
    space: EmbeddingSpace
    rows: tuple[EmbeddingEncodingIdentity, ...] = Field(min_length=1, max_length=MAX_EMBEDDING_ROWS)
    input_set_sha256: Sha256
    binary: EmbeddingBinaryMember
    dimension: int = Field(ge=1, le=4096, strict=True)
    row_count: int = Field(ge=1, le=MAX_EMBEDDING_ROWS, strict=True)
    shard_sha256: Sha256

    @model_validator(mode="after")
    def exact_shape_and_rows(self) -> EmbeddingVectorShardManifest:
        _ordered_rows(self.rows, self.space, self.input_set_sha256)
        if (
            self.dimension != self.space.model_spec.dimension
            or self.row_count != len(self.rows)
            or self.binary.byte_count != self.row_count * self.dimension * 4
        ):
            raise ValueError("binary byte count, rows or dimension differs from its pinned shape")
        _hash(self, "shard_sha256")
        return self


class EmbeddingVectorRowRef(_EmbeddingContract):
    shard_manifest: ArtifactMemberPointer
    row_index: int = Field(ge=0, le=MAX_EMBEDDING_ROWS - 1, strict=True)
    encoding_sha256: Sha256

    @model_validator(mode="after")
    def exact_shard_pointer(self) -> EmbeddingVectorRowRef:
        validate_embedding_manifest_pointer(self.shard_manifest, SHARD_SCHEMA_REF, "shard.json")
        return self


class EmbeddingIndexBindingShape(Protocol):
    """Read-only layout shared by released binding1 and registered-review binding2."""

    @property
    def source(self) -> ApprovedItemKnowledgeSourceV2: ...

    @property
    def encoding(self) -> EmbeddingEncodingIdentity: ...

    @property
    def row_ref(self) -> EmbeddingVectorRowRef: ...

    @property
    def view(self) -> ExperimentView: ...

    @property
    def recipe(self) -> ExperimentViewRecipe | PublicSolutionEmbeddingRecipe: ...


class EmbeddingIndexReferenceShape(Protocol):
    """Schema-validated reference layout shared by the two released index families."""

    @property
    def index_id(self) -> str: ...

    @property
    def index_revision_id(self) -> str: ...

    @property
    def previous_manifest(self) -> ArtifactMemberPointer | None: ...

    @property
    def storage_partition(self) -> str: ...

    @property
    def space(self) -> EmbeddingSpace: ...

    @property
    def view(self) -> ExperimentView: ...

    @property
    def recipe(self) -> ExperimentViewRecipe | PublicSolutionEmbeddingRecipe: ...

    @property
    def shards(self) -> tuple[ArtifactMemberPointer, ...]: ...

    @property
    def bindings(self) -> Sequence[EmbeddingIndexBindingShape]: ...

    def model_dump(self, *, mode: Literal["json"]) -> dict[str, Any]: ...


def validate_embedding_index_layout(
    *,
    previous_manifest: ArtifactMemberPointer | None,
    previous_schema_refs: tuple[str, ...],
    storage_partition: str,
    space: EmbeddingSpace,
    view: ExperimentView,
    recipe: ExperimentViewRecipe | PublicSolutionEmbeddingRecipe,
    shards: tuple[ArtifactMemberPointer, ...],
    bindings: Sequence[EmbeddingIndexBindingShape],
) -> None:
    """One authoritative pure layout rule, after each owner's schema validation."""
    if type(recipe) is PublicSolutionEmbeddingRecipe:
        PublicSolutionEmbeddingRecipe.model_validate(recipe.model_dump(mode="json"))
    elif type(recipe) is ExperimentViewRecipe:
        ExperimentViewRecipe.model_validate(recipe.model_dump(mode="json"))
    else:
        raise ValueError("index recipe family is unsupported")
    if space.purpose != "DOCUMENT":
        raise ValueError("a corpus index requires document vectors")
    if previous_manifest is not None:
        if previous_manifest.schema_ref not in previous_schema_refs:
            raise ValueError("index predecessor schema is not supported by this version")
        validate_embedding_manifest_pointer(
            previous_manifest, previous_manifest.schema_ref, "index.json"
        )
    keys = tuple(_pointer_key(pointer) for pointer in shards)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("index shard pointers must be sorted and unique")
    for pointer in shards:
        validate_embedding_manifest_pointer(pointer, SHARD_SCHEMA_REF, "shard.json")
    revisions = tuple(binding.source.item_revision_id for binding in bindings)
    if revisions != tuple(sorted(set(revisions))):
        raise ValueError("index bindings must be sorted by unique source revision")
    if {binding.row_ref.shard_manifest for binding in bindings} != set(shards):
        raise ValueError("index shards differ from its source binding references")
    if any(
        binding.encoding.storage_partition != storage_partition
        or binding.encoding.space_sha256 != space.space_sha256
        or binding.view != view
        or binding.recipe != recipe
        for binding in bindings
    ):
        raise ValueError("index binding space, partition, view or recipe differs")


class EmbeddingSourceBinding(_EmbeddingContract):
    """Owner-built exact source association; permission must be rechecked before use."""

    schema_version: Literal["embedding-source-binding/1.0"] = "embedding-source-binding/1.0"
    source: PopulationSource
    profile: InferenceTransferProfilePointer
    solution_evidence: KnowledgeSolutionEvidencePointer
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    recipe: ExperimentViewRecipe
    view: ExperimentView
    projection_version: Literal["accepted-solution-comparison/1.0"] = (
        "accepted-solution-comparison/1.0"
    )
    encoding: EmbeddingEncodingIdentity
    row_ref: EmbeddingVectorRowRef
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_binding_identity(self) -> EmbeddingSourceBinding:
        KnowledgeSolutionEvidencePointer.model_validate(
            self.solution_evidence.model_dump(mode="json")
        )
        ExperimentViewRecipe.model_validate(self.recipe.model_dump(mode="json"))
        if (
            self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256
            or self.row_ref.encoding_sha256 != self.encoding.encoding_sha256
        ):
            raise ValueError("binding Graph or encoding pointer identity differs")
        _hash(self, "binding_sha256")
        return self


class EmbeddingIndexManifest(_EmbeddingContract):
    schema_version: Literal["embedding-index-manifest/1.0"] = "embedding-index-manifest/1.0"
    index_id: str = Field(pattern=r"^embeddingindex_[0-9a-f]{32}$")
    index_revision_id: str = Field(pattern=r"^embeddingindexrev_[0-9a-f]{32}$")
    previous_manifest: ArtifactMemberPointer | None
    storage_partition: StoragePartition
    space: EmbeddingSpace
    view: ExperimentView
    recipe: ExperimentViewRecipe
    shards: tuple[ArtifactMemberPointer, ...] = Field(min_length=1, max_length=MAX_EMBEDDING_ROWS)
    bindings: tuple[EmbeddingSourceBinding, ...] = Field(
        min_length=1, max_length=MAX_EMBEDDING_ROWS
    )
    created_at: UtcDatetime
    index_sha256: Sha256

    @model_validator(mode="after")
    def exact_index_namespace(self) -> EmbeddingIndexManifest:
        validate_embedding_index_layout(
            previous_manifest=self.previous_manifest,
            previous_schema_refs=(INDEX_SCHEMA_REF,),
            storage_partition=self.storage_partition,
            space=self.space,
            view=self.view,
            recipe=self.recipe,
            shards=self.shards,
            bindings=self.bindings,
        )
        _hash(self, "index_sha256")
        return self


class EmbeddingTextInput(_EmbeddingContract):
    encoding: EmbeddingEncodingIdentity
    text: TransferText = Field(min_length=1, max_length=262144)

    @model_validator(mode="after")
    def exact_input_text(self) -> EmbeddingTextInput:
        if (
            not self.text.strip()
            or len(self.text.encode("utf-8")) > 262144
            or self.encoding.input_text_sha256 != content_sha256(self.text)
        ):
            raise ValueError("encoding input text hash or byte bound differs")
        return self


class IncrementalEmbeddingInput(_EmbeddingContract):
    schema_version: Literal["incremental-embedding-input/1.0"] = "incremental-embedding-input/1.0"
    job_id: JobId
    space: EmbeddingSpace
    rows: tuple[EmbeddingTextInput, ...] = Field(min_length=1, max_length=MAX_EMBEDDING_ROWS)
    batch_size: int = Field(ge=1, le=16, strict=True)
    threads: int = Field(ge=1, le=16, strict=True)
    input_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_input_rows(self) -> IncrementalEmbeddingInput:
        if self.space.purpose != "DOCUMENT":
            raise ValueError("incremental corpus encoding requires DOCUMENT purpose")
        _ordered_rows(tuple(row.encoding for row in self.rows), self.space, self.input_set_sha256)
        _hash(self, "request_sha256")
        return self


class IncrementalEmbeddingResult(_EmbeddingContract):
    schema_version: Literal["incremental-embedding-result/1.0"] = "incremental-embedding-result/1.0"
    job_id: JobId
    request_sha256: Sha256
    input_set_sha256: Sha256
    shard: EmbeddingVectorShardManifest
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_result_rows(self) -> IncrementalEmbeddingResult:
        if self.input_set_sha256 != self.shard.input_set_sha256:
            raise ValueError("result input set differs from its shard")
        _hash(self, "result_sha256")
        return self


def parse_embedding_shard(value: dict[str, Any]) -> EmbeddingVectorShardManifest:
    validate_contract(SCHEMA_NAME, value)
    return EmbeddingVectorShardManifest.model_validate(value)


def parse_embedding_binding(value: dict[str, Any]) -> EmbeddingSourceBinding:
    validate_contract(SCHEMA_NAME, value)
    return EmbeddingSourceBinding.model_validate(value)


def parse_embedding_index(value: dict[str, Any]) -> EmbeddingIndexManifest:
    validate_contract(SCHEMA_NAME, value)
    return EmbeddingIndexManifest.model_validate(value)


def parse_incremental_embedding_input(value: dict[str, Any]) -> IncrementalEmbeddingInput:
    validate_contract(SCHEMA_NAME, value)
    return IncrementalEmbeddingInput.model_validate(value)


def parse_incremental_embedding_result(value: dict[str, Any]) -> IncrementalEmbeddingResult:
    validate_contract(SCHEMA_NAME, value)
    return IncrementalEmbeddingResult.model_validate(value)


def validate_incremental_embedding_result(
    request: IncrementalEmbeddingInput, result: IncrementalEmbeddingResult
) -> None:
    request = parse_incremental_embedding_input(request.model_dump(mode="json"))
    result = parse_incremental_embedding_result(result.model_dump(mode="json"))
    if (
        result.job_id != request.job_id
        or result.request_sha256 != request.request_sha256
        or result.input_set_sha256 != request.input_set_sha256
        or result.shard.space != request.space
        or result.shard.rows != tuple(row.encoding for row in request.rows)
    ):
        raise ValueError("embedding result differs from its exact job, request, space or rows")


def validate_embedding_source_binding(
    binding: EmbeddingSourceBinding,
    entry: StagedExperimentEntry,
    shard_pointer: ArtifactMemberPointer,
    shard: EmbeddingVectorShardManifest,
) -> None:
    """Validate materialized references; caller still owns current source authorization."""
    binding = parse_embedding_binding(binding.model_dump(mode="json"))
    entry = StagedExperimentEntry.model_validate(entry.model_dump(mode="json"))
    shard = parse_embedding_shard(shard.model_dump(mode="json"))
    shard_pointer = ArtifactMemberPointer.model_validate(shard_pointer.model_dump(mode="json"))
    validate_embedding_manifest_pointer(shard_pointer, SHARD_SCHEMA_REF, "shard.json")
    _validate_binding_source_and_row(
        binding, entry, shard_pointer, shard, content_sha256(shard.model_dump(mode="json"))
    )


def _validate_binding_source_and_row(
    binding: EmbeddingSourceBinding,
    entry: StagedExperimentEntry,
    shard_pointer: ArtifactMemberPointer,
    shard: EmbeddingVectorShardManifest,
    shard_member_sha256: str,
) -> None:
    """One semantic leaf, called only after public validators revalidate each input."""
    basis = entry.profile.source_basis
    if (
        not same_approved_item_source_identity(binding.source, basis.source)
        or binding.profile != InferenceTransferProfilePointer.from_profile(entry.profile)
        or binding.solution_evidence != basis.solution_evidence
        or binding.graph_snapshot != basis.graph_snapshot
        or entry.profile.extraction.method != "DETERMINISTIC_REPORT_PROJECTION"
        or entry.profile.extraction.extractor_version != binding.projection_version
    ):
        raise ValueError("binding differs from its exact approved profile and source basis")
    text = experiment_view_text(entry, binding.view)
    if (
        text is None
        or not text.strip()
        or binding.encoding.input_text_sha256 != content_sha256(text)
    ):
        raise ValueError("binding differs from its exact available source text view")
    if (
        shard_pointer != binding.row_ref.shard_manifest
        or shard_pointer.sha256 != shard_member_sha256
        or binding.encoding.space_sha256 != shard.space.space_sha256
        or shard.space.purpose != "DOCUMENT"
        or binding.row_ref.row_index >= len(shard.rows)
        or shard.rows[binding.row_ref.row_index] != binding.encoding
    ):
        raise ValueError("binding has a foreign shard, row, space or encoding identity")


def validate_embedding_source_bindings(
    bindings: tuple[EmbeddingSourceBinding, ...],
    entries: tuple[StagedExperimentEntry, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
) -> None:
    """Validate a bounded exact capture in linear work; this never grants access.

    Each unique shard is parsed and hashed once, even when many bindings share it.
    The owner still resolves/authorizes current sources and committed Artifact bytes.
    Unused entries are permitted for a bounded verified population capture. Shards
    are the exact sorted binding closure; unexpected/duplicate/missing pins fail.
    """
    if any(len(values) > MAX_EMBEDDING_ROWS for values in (bindings, entries, shards)):
        raise ValueError("embedding source-binding capture exceeds its row budget")
    by_source: dict[str, StagedExperimentEntry] = {}
    for original_entry in entries:
        entry = StagedExperimentEntry.model_validate(original_entry.model_dump(mode="json"))
        revision = entry.profile.source_basis.source.item_revision_id
        if revision in by_source:
            raise ValueError("binding entries contain duplicate source revisions")
        by_source[revision] = entry
    by_pointer: dict[ArtifactMemberPointer, tuple[EmbeddingVectorShardManifest, str]] = {}
    pointer_keys = tuple(_pointer_key(pointer) for pointer, _ in shards)
    if pointer_keys != tuple(sorted(set(pointer_keys))):
        raise ValueError("index shard pointers must be sorted and unique")
    for original_pointer, original_shard in shards:
        pointer = ArtifactMemberPointer.model_validate(original_pointer.model_dump(mode="json"))
        validate_embedding_manifest_pointer(pointer, SHARD_SCHEMA_REF, "shard.json")
        if pointer in by_pointer:
            raise ValueError("index references duplicate, foreign or changed shard content")
        shard = parse_embedding_shard(original_shard.model_dump(mode="json"))
        by_pointer[pointer] = shard, content_sha256(shard.model_dump(mode="json"))
    seen_bindings: set[str] = set()
    referenced_pointers: set[ArtifactMemberPointer] = set()
    for original_binding in bindings:
        binding = parse_embedding_binding(original_binding.model_dump(mode="json"))
        if binding.binding_sha256 in seen_bindings:
            raise ValueError("binding capture contains duplicate source bindings")
        seen_bindings.add(binding.binding_sha256)
        referenced_pointers.add(binding.row_ref.shard_manifest)
        selected_entry = by_source.get(binding.source.item_revision_id)
        if selected_entry is None:
            raise ValueError("binding differs from its exact approved profile and source basis")
        selected = by_pointer.get(binding.row_ref.shard_manifest)
        if selected is None:
            raise ValueError("binding has a foreign shard, row, space or encoding identity")
        shard, member_sha256 = selected
        _validate_binding_source_and_row(
            binding, selected_entry, binding.row_ref.shard_manifest, shard, member_sha256
        )
    if referenced_pointers != set(by_pointer):
        raise ValueError("referenced index shard set is missing or differs")


def validate_embedding_index_references(
    index: EmbeddingIndexManifest,
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None = None,
) -> None:
    """Resolve supplied exact manifests, never guess a row or substitute a current revision."""
    index = parse_embedding_index(index.model_dump(mode="json"))
    parent = (
        None
        if previous is None
        else (previous[0], parse_embedding_index(previous[1].model_dump(mode="json")))
    )
    validate_embedding_index_reference_layout(index, shards, parent)


def validate_embedding_index_reference_layout(
    index: EmbeddingIndexReferenceShape,
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexReferenceShape] | None = None,
) -> None:
    """One shared reference rule, AFTER each public boundary validates its index schema.

    This pure helper validates supplied values, not canonical bytes or authority.
    Neither family can use it to admit a different family's raw wire document.
    """
    by_pointer: dict[ArtifactMemberPointer, EmbeddingVectorShardManifest] = {}
    encodings: set[str] = set()
    for pointer, shard in shards:
        pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointer))
        shard = parse_embedding_shard(raw_similarity_contract_value(shard))
        validate_embedding_manifest_pointer(pointer, SHARD_SCHEMA_REF, "shard.json")
        if (
            pointer in by_pointer
            or pointer.sha256 != content_sha256(shard.model_dump(mode="json"))
            or shard.space != index.space
            or any(
                row.storage_partition != index.storage_partition or row.encoding_sha256 in encodings
                for row in shard.rows
            )
        ):
            raise ValueError("index references duplicate, foreign or changed shard content")
        by_pointer[pointer] = shard
        encodings.update(row.encoding_sha256 for row in shard.rows)
    if set(by_pointer) != set(index.shards):
        raise ValueError("referenced index shard set is missing or differs")
    for binding in index.bindings:
        shard = by_pointer[binding.row_ref.shard_manifest]
        if (
            binding.row_ref.row_index >= len(shard.rows)
            or shard.rows[binding.row_ref.row_index] != binding.encoding
        ):
            raise ValueError("index source binding references a foreign or missing row")
    if index.previous_manifest is None:
        if previous is not None:
            raise ValueError("an initial index cannot resolve a guessed predecessor")
        return
    if previous is None:
        raise ValueError("the exact index predecessor must be resolved")
    pointer, parent = previous
    pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointer))
    if (
        pointer != index.previous_manifest
        or pointer.sha256 != content_sha256(parent.model_dump(mode="json"))
        or parent.index_id != index.index_id
        or parent.index_revision_id == index.index_revision_id
        or parent.storage_partition != index.storage_partition
        or parent.space != index.space
        or parent.view != index.view
        or parent.recipe != index.recipe
    ):
        raise ValueError("index predecessor identity or immutable namespace differs")
