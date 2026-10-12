"""Fixed native benchmark values only: no authority, inference, ranking or activation."""

from __future__ import annotations

import json
from typing import Annotated, Any, Final, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProofPointer,
    EmbeddingRuntimeProfile,
    embedding_numeric_library_versions,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingNumericalRecipe,
    EmbeddingNumericalRuntimeDescriptor,
    EmbeddingNumericImplementationPin,
    EmbeddingRuntimeBundlePointer,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentView,
    ExperimentViewRecipe,
    PopulationSource,
    profile_key,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
    TransferText,
)
from eom_catalog_contracts.knowledge import (
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

EMBEDDING_DEVICE_BENCHMARK_SCHEMA: Final = "embedding-device-benchmark"
EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF: Final = (
    "eom://schemas/knowledge/embedding-device-benchmark/1.0"
)
MAX_BENCHMARK_ENVELOPE_BYTES: Final = 64 * 1024
MAX_BENCHMARK_STAGED_BYTES: Final = 64 * 1024**2
MAX_BENCHMARK_OUTPUT_BYTES: Final = 16 * 1024**2
BENCHMARK_DEVICE_SEQUENCE: Final = ("CPU", "CUDA", "CUDA", "CPU", "CPU", "CUDA")
BENCHMARK_GATE_ORDER: Final = (
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
type BenchmarkDevice = Literal["CPU", "CUDA"]
type BenchmarkPurpose = Literal["DOCUMENT", "QUERY"]
type BenchmarkId = Annotated[str, Field(pattern=r"^embeddingbenchmark_[0-9a-f]{32}$")]
type BenchmarkRevisionId = Annotated[str, Field(pattern=r"^embeddingbenchmarkrev_[0-9a-f]{32}$")]
type BenchmarkExecutionId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
type BenchmarkNanoseconds = Annotated[int, Field(ge=1, le=10**15, strict=True)]
type BenchmarkMicroseconds = Annotated[int, Field(ge=1, le=10**12, strict=True)]
type BenchmarkTokenId = Annotated[int, Field(ge=0, le=2**31 - 1, strict=True)]
type BenchmarkReason = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
type BenchmarkPhase = Literal["COLD_READY", "QUERY_PREPARED", "QUERY_READY"]
type BenchmarkF32Name = Literal[
    "cold-documents.f32",
    "supplementary-documents.f32",
    "query-1-1.f32",
    "query-1-2.f32",
    "query-1-3.f32",
    "query-1-4.f32",
    "query-1-5.f32",
    "query-2-1.f32",
    "query-2-2.f32",
    "query-2-3.f32",
    "query-2-4.f32",
    "query-2-5.f32",
]


def _integer_json(value: object, key: str = "") -> None:
    # Raw copied/constructed fields must be checked before a Literal serializer can hide bools.
    active: set[int] = set()
    nodes = 0

    def walk(current: object, name: str, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 2_000_000 or depth > 32:
            raise ValueError("benchmark raw value exceeds its node/depth bound")
        boolean = name in {"tf32_enabled", "order_preserved", "top5_same_cluster"}
        if boolean and (
            type(current) is not bool or (name == "tf32_enabled" and current is not False)
        ):
            raise ValueError("benchmark declared boolean has an inexact raw value")
        if isinstance(current, float) or (type(current) is bool and not boolean):
            raise ValueError("benchmark JSON requires exact integers or declared booleans")
        if isinstance(current, str):
            if len(current) > 262144:
                raise ValueError("benchmark raw string exceeds its bound")
            return
        if current is None or isinstance(current, (int, bool)):
            return
        if not isinstance(current, (BaseModel, dict, tuple, list)):
            raise ValueError("benchmark raw value is not a JSON scalar/container")
        identity = id(current)
        if identity in active:
            raise ValueError("benchmark raw value is cyclic")
        active.add(identity)
        try:
            if isinstance(current, BaseModel):
                fields = type(current).model_fields
                extra = current.__pydantic_extra__
                if extra is not None and not isinstance(extra, dict):
                    raise ValueError("benchmark constructed model has malformed extra fields")
                if (
                    len(fields) > 64
                    or len(current.__dict__) > 64
                    or (extra is not None and len(extra) > 64)
                ):
                    raise ValueError("benchmark raw model exceeds its field bound")
                for field in fields:
                    try:
                        child = getattr(current, field)
                    except AttributeError as exc:
                        raise ValueError(
                            "benchmark constructed model lacks a declared field"
                        ) from exc
                    walk(child, field, depth + 1)
                if extra:
                    walk(extra, "", depth + 1)
                unknown = set(current.__dict__) - set(fields)
                for field in unknown:
                    walk(current.__dict__[field], field, depth + 1)
                if extra or unknown:
                    raise ValueError(
                        "benchmark copied/constructed model contains undeclared fields"
                    )
            elif isinstance(current, dict):
                if len(current) > 64:
                    raise ValueError("benchmark raw object exceeds its field bound")
                for field, child in current.items():
                    if not isinstance(field, str):
                        raise ValueError("benchmark raw object keys must be strings")
                    walk(child, field, depth + 1)
            else:
                if len(current) > 4096:
                    raise ValueError("benchmark raw sequence exceeds its bound")
                for child in current:
                    walk(child, name, depth + 1)
        finally:
            active.remove(identity)

    walk(value, key, 0)


class _BenchmarkContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_json_values(cls, value: object) -> object:
        _integer_json(value)
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            if set(value) - set(cls.model_fields):
                raise ValueError("benchmark raw model contains undeclared fields")
            return {
                name: child.model_dump(mode="json") if isinstance(child, BaseModel) else child
                for name, child in value.items()
            }
        return value


def _hash(value: FrozenModel, field: str, limit: int = MAX_BENCHMARK_ENVELOPE_BYTES) -> None:
    document = value.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > limit:
        raise ValueError("benchmark value exceeds its byte bound")
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError(f"{field} differs from canonical benchmark content")


def _member(pointer: ArtifactMemberPointer, definition: str, name: str | None = None) -> None:
    if (
        pointer.schema_ref != f"{EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF}#/$defs/{definition}"
        or pointer.media_type != "application/json"
        or (name is not None and pointer.member_path != name)
    ):
        raise ValueError("benchmark Artifact member schema, media or fixed name differs")


def _device_ordinal(device: BenchmarkDevice, ordinal: int) -> None:
    if device != BENCHMARK_DEVICE_SEQUENCE[ordinal - 1]:
        raise ValueError("benchmark device differs from the fixed six-launch order")


def _benchmark_model(model: LocalEmbeddingModelSpec) -> None:
    if (
        model.upstream_repo != "BAAI/bge-m3"
        or model.upstream_revision != "9a0624b896d81da7492a910ffa53731274b6cf3d"
        or model.dimension != 1024
        or model.maximum_tokens != 2048
    ):
        raise ValueError("benchmark model differs from the pinned BGE2048 recipe")


def benchmark_model_family_sha256(
    model: LocalEmbeddingModelSpec,
    implementations: tuple[EmbeddingNumericImplementationPin, ...],
    recipe: EmbeddingNumericalRecipe,
) -> str:
    """Relevant payload/both prefixes/common recipe only; not device or release authority."""
    _integer_json(model)
    _integer_json(implementations)
    _integer_json(recipe)
    model = LocalEmbeddingModelSpec.model_validate(model.model_dump(mode="json"))
    recipe = EmbeddingNumericalRecipe.model_validate(recipe.model_dump(mode="json"))
    _benchmark_model(model)
    if tuple(pin.component for pin in implementations) != (
        "FLOAT32_CODEC",
        "HOST_L2",
        "OFFLINE_ENCODER",
    ):
        raise ValueError("benchmark family requires all three ordered implementation pins")
    if recipe.batch_size != 4 or recipe.threads != 4:
        raise ValueError("benchmark family requires maximum batch4 and threads4")
    return content_sha256(
        {
            "model": model.model_dump(
                mode="json", exclude={"model_revision_id", "runtime_versions", "manifest_sha256"}
            ),
            "implementations": [
                EmbeddingNumericImplementationPin.model_validate(
                    pin.model_dump(mode="json")
                ).model_dump(mode="json")
                for pin in implementations
            ],
            "recipe": recipe.model_dump(mode="json", exclude={"cublas_workspace"}),
        }
    )


class BenchmarkTokenStratum(_BenchmarkContract):
    minimum_tokens: int = Field(ge=1, le=2048, strict=True)
    maximum_tokens: int = Field(ge=1, le=2048, strict=True)
    profile_count: int = Field(ge=1, le=4, strict=True)

    @model_validator(mode="after")
    def ordered_range(self) -> BenchmarkTokenStratum:
        if self.minimum_tokens > self.maximum_tokens:
            raise ValueError("benchmark token stratum is reversed")
        return self


class BenchmarkRecipe(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-recipe/1.0"] = (
        "embedding-device-benchmark-recipe/1.0"
    )
    cold_sequence: tuple[
        Literal["CPU"],
        Literal["CUDA"],
        Literal["CUDA"],
        Literal["CPU"],
        Literal["CPU"],
        Literal["CUDA"],
    ] = BENCHMARK_DEVICE_SEQUENCE
    cold_repeats: Literal[3] = 3
    warm_repeats: Literal[5] = 5
    query_repeats: Literal[5] = 5
    synthetic_cases: Literal[8] = 8
    maximum_tokens: Literal[2048] = 2048
    maximum_batch_size: Literal[4] = 4
    threads: Literal[4] = 4
    public_fixture_sha256: Sha256
    token_strata: tuple[BenchmarkTokenStratum, ...] = Field(min_length=3, max_length=3)
    near_tie_rule: Literal["CPU_COMPLETE_SPAN_4E-5_STABLE_REAL_ROW/1.0"] = (
        "CPU_COMPLETE_SPAN_4E-5_STABLE_REAL_ROW/1.0"
    )
    gate_microseconds: Literal["CPU_FLOOR_CUDA_CEIL_FROM_NS/1.0"] = (
        "CPU_FLOOR_CUDA_CEIL_FROM_NS/1.0"
    )
    recipe_sha256: Sha256

    @model_validator(mode="after")
    def exact_strata(self) -> BenchmarkRecipe:
        expected = 1
        for stratum in self.token_strata:
            if stratum.minimum_tokens != expected:
                raise ValueError("benchmark token strata must cover1..2048 without gap/overlap")
            expected = stratum.maximum_tokens + 1
        if expected != 2049 or sum(s.profile_count for s in self.token_strata) != 6:
            raise ValueError("benchmark strata require exact six-profile coverage")
        _hash(self, "recipe_sha256")
        return self


class BenchmarkModelFamily(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-family/1.0"] = (
        "embedding-device-benchmark-family/1.0"
    )
    model: LocalEmbeddingModelSpec
    implementations: tuple[EmbeddingNumericImplementationPin, ...] = Field(
        min_length=3, max_length=3
    )
    recipe: EmbeddingNumericalRecipe
    family_sha256: Sha256

    @model_validator(mode="after")
    def common_family(self) -> BenchmarkModelFamily:
        if self.recipe.cublas_workspace is not None:
            raise ValueError("common family recipe cannot choose a CUDA workspace")
        if self.family_sha256 != benchmark_model_family_sha256(
            self.model, self.implementations, self.recipe
        ):
            raise ValueError("benchmark compatible-family hash differs")
        return self


class BenchmarkPurposeSpaces(_BenchmarkContract):
    document: EmbeddingSpace
    query: EmbeddingSpace

    @model_validator(mode="after")
    def genuine_purposes(self) -> BenchmarkPurposeSpaces:
        if (
            self.document.purpose != "DOCUMENT"
            or self.query.purpose != "QUERY"
            or self.document.model_spec != self.query.model_spec
            or self.document.runtime != self.query.runtime
            or self.document.space_sha256 == self.query.space_sha256
        ):
            raise ValueError(
                "benchmark requires distinct genuine DOCUMENT/QUERY spaces of one runtime"
            )
        _benchmark_model(self.document.model_spec)
        return self


class BenchmarkRuntime(_BenchmarkContract):
    """Expected exact pins; an asserted descriptor does not verify installed bytes."""

    profile: EmbeddingRuntimeProfile
    bundle: EmbeddingRuntimeBundlePointer
    installed_proof: EmbeddingInstalledRuntimeProofPointer
    numerical_runtime: EmbeddingNumericalRuntimeDescriptor
    spaces: BenchmarkPurposeSpaces

    @model_validator(mode="after")
    def closed_runtime(self) -> BenchmarkRuntime:
        runtime, model = self.numerical_runtime, self.spaces.document.model_spec
        device: BenchmarkDevice = "CPU" if self.profile == "CPU_INDEX_FP32" else "CUDA"
        if (
            self.installed_proof.profile != self.profile
            or runtime.device.kind != device
            or self.spaces.document.runtime.device != device
            or self.spaces.document.runtime.execution_runtime_sha256 != runtime.runtime_sha256
            or tuple((pin.name, pin.version) for pin in runtime.libraries)
            != embedding_numeric_library_versions(self.profile)
            or runtime.recipe.batch_size != 4
            or runtime.recipe.threads != 4
            or runtime.torch_build_cuda_version != (None if device == "CPU" else "12.8")
        ):
            raise ValueError("benchmark exact CPU5/CUDA20 profile/runtime closure differs")
        versions = {pin.name: pin.version for pin in runtime.libraries}
        if any(versions[pin.name] != pin.version for pin in model.runtime_versions):
            raise ValueError("benchmark model and numeric library versions differ")
        return self


class BenchmarkSourceSelection(_BenchmarkContract):
    profile: InferenceTransferProfilePointer
    source: PopulationSource
    solution_evidence: KnowledgeSolutionEvidencePointer
    selection_view: ExperimentView
    selection_token_count: int = Field(ge=1, le=2048, strict=True)


class BenchmarkRowRef(_BenchmarkContract):
    """Real profile/view/text identity; never an index row or an access grant."""

    profile: InferenceTransferProfilePointer
    view: ExperimentView
    purpose: BenchmarkPurpose
    input_text_sha256: Sha256
    row_sha256: Sha256

    @model_validator(mode="after")
    def exact_row(self) -> BenchmarkRowRef:
        _hash(self, "row_sha256")
        return self


def benchmark_row_key(row: BenchmarkRowRef) -> tuple[str, str, str, str, str]:
    """Stable real row identity only; no cosine/rank behavior is introduced here."""
    return *profile_key(row.profile), row.view, row.input_text_sha256


def _rows(rows: tuple[BenchmarkRowRef, ...], purpose: BenchmarkPurpose) -> None:
    keys = tuple(benchmark_row_key(row) for row in rows)
    if keys != tuple(sorted(set(keys))) or any(row.purpose != purpose for row in rows):
        raise ValueError("benchmark rows must be ordered, unique and purpose-exact")
    if len({(profile_key(row.profile), row.view) for row in rows}) != len(rows):
        raise ValueError("benchmark repeats a real profile/view with a different text")


class BenchmarkTextRow(_BenchmarkContract):
    row: BenchmarkRowRef
    text: TransferText = Field(min_length=1, max_length=262144)
    token_count: int = Field(ge=1, le=2048, strict=True)
    token_ids_sha256: Sha256

    @model_validator(mode="after")
    def exact_text(self) -> BenchmarkTextRow:
        if (
            not self.text.strip()
            or len(self.text.encode("utf-8")) > 262144
            or self.row.input_text_sha256 != content_sha256(self.text)
        ):
            raise ValueError("benchmark staged text is empty, oversized or hash-mismatched")
        return self


class BenchmarkSyntheticCase(_BenchmarkContract):
    case_ordinal: int = Field(ge=1, le=8, strict=True)
    text: TransferText = Field(max_length=262144)
    input_text_sha256: Sha256
    token_count: int = Field(ge=0, le=4096, strict=True)
    token_ids_sha256: Sha256 | None
    expected: Literal["VALID", "EMPTY_REJECTED", "OVERFLOW_REJECTED"]

    @model_validator(mode="after")
    def exact_public_case(self) -> BenchmarkSyntheticCase:
        expected = (
            "VALID"
            if self.case_ordinal < 7
            else "EMPTY_REJECTED"
            if self.case_ordinal == 7
            else "OVERFLOW_REJECTED"
        )
        if (
            self.expected != expected
            or self.input_text_sha256 != content_sha256(self.text)
            or len(self.text.encode("utf-8")) > 262144
        ):
            raise ValueError("benchmark public synthetic identity/text hash differs")
        if self.case_ordinal == 7:
            if self.text != "" or self.token_count or self.token_ids_sha256 is not None:
                raise ValueError("benchmark empty negative must reject before tokenization")
        elif (
            not self.text.strip()
            or self.token_ids_sha256 is None
            or not (
                1 <= self.token_count <= 2048 if self.case_ordinal < 7 else self.token_count > 2048
            )
        ):
            raise ValueError("benchmark public valid/overflow case token shape differs")
        return self


class BenchmarkCapacityInput(_BenchmarkContract):
    text: TransferText = Field(min_length=1, max_length=262144)
    input_text_sha256: Sha256
    token_count: Literal[2048] = 2048
    token_ids_sha256: Sha256

    @model_validator(mode="after")
    def exact_capacity_input(self) -> BenchmarkCapacityInput:
        if (
            not self.text.strip()
            or len(self.text.encode("utf-8")) > 262144
            or self.input_text_sha256 != content_sha256(self.text)
        ):
            raise ValueError("benchmark exact2048 capacity input text/hash differs")
        return self


def benchmark_public_fixture_sha256(
    cases: tuple[BenchmarkSyntheticCase, ...], capacity: BenchmarkCapacityInput
) -> str:
    _integer_json(cases)
    _integer_json(capacity)
    return content_sha256(
        {
            "synthetic_cases": [case.model_dump(mode="json", exclude={"text"}) for case in cases],
            "capacity": capacity.model_dump(mode="json", exclude={"text"}),
        }
    )


def benchmark_input_set_sha256(
    documents: tuple[BenchmarkTextRow, ...],
    queries: tuple[BenchmarkTextRow, ...],
    recipe: ExperimentViewRecipe,
) -> str:
    _integer_json(documents)
    _integer_json(queries)
    _integer_json(recipe)
    return content_sha256(
        {
            "view_recipe_sha256": recipe.recipe_sha256,
            "documents": [row.model_dump(mode="json", exclude={"text"}) for row in documents],
            "queries": [row.model_dump(mode="json", exclude={"text"}) for row in queries],
        }
    )


class BenchmarkStagedInputs(_BenchmarkContract):
    """Explicit local text materialization; not owner DB metadata or authority."""

    schema_version: Literal["embedding-device-benchmark-inputs/1.0"] = (
        "embedding-device-benchmark-inputs/1.0"
    )
    benchmark_id: BenchmarkId
    benchmark_revision_id: BenchmarkRevisionId
    view_recipe: ExperimentViewRecipe
    documents: tuple[BenchmarkTextRow, ...] = Field(min_length=6, max_length=18)
    queries: tuple[BenchmarkTextRow, ...] = Field(min_length=2, max_length=2)
    synthetic_cases: tuple[BenchmarkSyntheticCase, ...] = Field(min_length=8, max_length=8)
    capacity: BenchmarkCapacityInput
    public_fixture_sha256: Sha256
    input_set_sha256: Sha256

    @model_validator(mode="after")
    def exact_input(self) -> BenchmarkStagedInputs:
        _rows(tuple(row.row for row in self.documents), "DOCUMENT")
        _rows(tuple(row.row for row in self.queries), "QUERY")
        profiles = {profile_key(row.row.profile) for row in self.documents}
        if (
            len(profiles) != 6
            or len({row.row.profile.profile_id for row in self.documents}) != 6
            or any(profile_key(row.row.profile) not in profiles for row in self.queries)
        ):
            raise ValueError(
                "benchmark inputs require six real profiles and exact selected query profiles"
            )
        if self.input_set_sha256 != benchmark_input_set_sha256(
            self.documents, self.queries, self.view_recipe
        ):
            raise ValueError("benchmark input-set hash differs from exact ordered purpose rows")
        if (
            tuple(case.case_ordinal for case in self.synthetic_cases) != tuple(range(1, 9))
            or self.synthetic_cases[4].text != self.synthetic_cases[5].text
            or self.synthetic_cases[4].token_ids_sha256 != self.synthetic_cases[5].token_ids_sha256
        ):
            raise ValueError("benchmark synthetic8 order/exact duplicate fixture differs")
        if self.public_fixture_sha256 != benchmark_public_fixture_sha256(
            self.synthetic_cases, self.capacity
        ):
            raise ValueError("benchmark public fixture hash differs")
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > MAX_BENCHMARK_STAGED_BYTES:
            raise ValueError("benchmark staged inputs exceed the byte bound")
        return self


class BenchmarkExecutionPolicy(_BenchmarkContract):
    """Numerical/resource limits only; no actor, principal, device lease or admission grant."""

    schema_version: Literal["embedding-device-benchmark-policy/1.0"] = (
        "embedding-device-benchmark-policy/1.0"
    )
    purpose: Literal["LOCAL_EMBEDDING_DEVICE_BENCHMARK"] = "LOCAL_EMBEDDING_DEVICE_BENCHMARK"
    policy_id: str = Field(pattern=r"^embeddingbenchmarkpolicy_[0-9a-f]{32}$")
    policy_revision_id: str = Field(pattern=r"^embeddingbenchmarkpolicyrev_[0-9a-f]{32}$")
    timeout_seconds: Literal[180] = 180
    cpu_quota_percent: Literal[400] = 400
    tasks_max: Literal[64] = 64
    rss_limit_bytes: Literal[6442450944] = 6442450944
    gpu_limit_bytes: Literal[8589934592] = 8589934592
    maximum_envelope_bytes: Literal[65536] = 65536
    maximum_staged_bytes: Literal[67108864] = 67108864
    maximum_output_bytes: Literal[16777216] = 16777216
    maximum_output_members: Literal[64] = 64
    policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_policy(self) -> BenchmarkExecutionPolicy:
        _hash(self, "policy_sha256")
        return self


class BenchmarkOwnerRequest(_BenchmarkContract):
    """Owner-built pointer metadata; audit identity is not authentication/authorization."""

    schema_version: Literal["embedding-device-benchmark-request/1.0"] = (
        "embedding-device-benchmark-request/1.0"
    )
    kind: Literal["OWNER_REQUEST"] = "OWNER_REQUEST"
    purpose: Literal["LOCAL_EMBEDDING_DEVICE_BENCHMARK"] = "LOCAL_EMBEDDING_DEVICE_BENCHMARK"
    benchmark_id: BenchmarkId
    benchmark_revision_id: BenchmarkRevisionId
    operator_audit_id: ActorId
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    sources: tuple[BenchmarkSourceSelection, ...] = Field(min_length=6, max_length=6)
    document_rows: tuple[BenchmarkRowRef, ...] = Field(min_length=6, max_length=18)
    query_rows: tuple[BenchmarkRowRef, ...] = Field(min_length=2, max_length=2)
    input_manifest: ArtifactMemberPointer
    input_set_sha256: Sha256
    view_recipe: ExperimentViewRecipe
    family: BenchmarkModelFamily
    cpu: BenchmarkRuntime
    cuda: BenchmarkRuntime
    recipe: BenchmarkRecipe
    execution_policy: BenchmarkExecutionPolicy
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_plan(self) -> BenchmarkOwnerRequest:
        _rows(self.document_rows, "DOCUMENT")
        _rows(self.query_rows, "QUERY")
        keys = tuple(profile_key(source.profile) for source in self.sources)
        selected = {profile_key(row.profile) for row in self.document_rows}
        if (
            keys != tuple(sorted(set(keys)))
            or set(keys) != selected
            or len({source.profile.profile_id for source in self.sources}) != 6
            or len({source.source.item_revision_id for source in self.sources}) != 6
            or any(profile_key(row.profile) not in selected for row in self.query_rows)
            or self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256
            or self.cpu.profile != "CPU_INDEX_FP32"
            or self.cuda.profile != "CUDA_INDEX_FP32"
        ):
            raise ValueError("benchmark source/profile/Graph/device closure differs")
        row_by_view = {(profile_key(row.profile), row.view): row for row in self.document_rows}
        for source in self.sources:
            if (profile_key(source.profile), source.selection_view) not in row_by_view:
                raise ValueError("benchmark stratum selection view is unavailable")
        for stratum in self.recipe.token_strata:
            count = sum(
                stratum.minimum_tokens <= source.selection_token_count <= stratum.maximum_tokens
                for source in self.sources
            )
            if count != stratum.profile_count:
                raise ValueError("benchmark selected profile counts differ from predeclared strata")
        for runtime in (self.cpu, self.cuda):
            actual = benchmark_model_family_sha256(
                runtime.spaces.document.model_spec,
                runtime.numerical_runtime.implementations,
                runtime.numerical_runtime.recipe,
            )
            if actual != self.family.family_sha256:
                raise ValueError(
                    "benchmark devices do not share the exact compatible payload/encoder family"
                )
        if (
            (self.cpu.bundle.bundle_id, self.cpu.bundle.bundle_revision_id)
            == (self.cuda.bundle.bundle_id, self.cuda.bundle.bundle_revision_id)
            or (self.cpu.installed_proof.proof_id, self.cpu.installed_proof.proof_revision_id)
            == (self.cuda.installed_proof.proof_id, self.cuda.installed_proof.proof_revision_id)
            or self.cpu.spaces.document.model_spec.model_revision_id
            == self.cuda.spaces.document.model_spec.model_revision_id
        ):
            raise ValueError(
                "CPU/CUDA execution successors cannot reuse conflicting immutable revisions"
            )
        if (
            len(
                {
                    space.space_sha256
                    for runtime in (self.cpu, self.cuda)
                    for space in (runtime.spaces.document, runtime.spaces.query)
                }
            )
            != 4
        ):
            raise ValueError("benchmark requires four distinct device/purpose spaces")
        _member(self.input_manifest, "stagedInputs", "benchmark-inputs.json")
        _hash(self, "request_sha256")
        return self


class BenchmarkLocalInput(_BenchmarkContract):
    member_name: Literal["benchmark-inputs.json"] = "benchmark-inputs.json"
    sha256: Sha256
    byte_count: int = Field(ge=1, le=MAX_BENCHMARK_STAGED_BYTES, strict=True)


class BenchmarkWorkerInvocation(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-invocation/1.0"] = (
        "embedding-device-benchmark-invocation/1.0"
    )
    kind: Literal["WORKER_INVOCATION"] = "WORKER_INVOCATION"
    purpose: Literal["LOCAL_EMBEDDING_DEVICE_BENCHMARK"] = "LOCAL_EMBEDDING_DEVICE_BENCHMARK"
    benchmark_id: BenchmarkId
    benchmark_revision_id: BenchmarkRevisionId
    job_id: JobId
    execution_id: BenchmarkExecutionId
    owner_request_sha256: Sha256
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    device: BenchmarkDevice
    local_input: BenchmarkLocalInput
    input_set_sha256: Sha256
    family: BenchmarkModelFamily
    runtime: BenchmarkRuntime
    recipe: BenchmarkRecipe
    execution_policy: BenchmarkExecutionPolicy
    invocation_sha256: Sha256

    @model_validator(mode="after")
    def exact_invocation(self) -> BenchmarkWorkerInvocation:
        _device_ordinal(self.device, self.launch_ordinal)
        if (
            self.runtime.numerical_runtime.device.kind != self.device
            or benchmark_model_family_sha256(
                self.runtime.spaces.document.model_spec,
                self.runtime.numerical_runtime.implementations,
                self.runtime.numerical_runtime.recipe,
            )
            != self.family.family_sha256
        ):
            raise ValueError("benchmark invocation runtime/family differs")
        _hash(self, "invocation_sha256")
        return self


def validate_benchmark_staged_inputs(
    request: BenchmarkOwnerRequest, inputs: BenchmarkStagedInputs
) -> None:
    """Pure closure; caller still owns actual permissions, raw files and lifecycle."""
    _integer_json(request)
    _integer_json(inputs)
    request = BenchmarkOwnerRequest.model_validate(request.model_dump(mode="json"))
    inputs = BenchmarkStagedInputs.model_validate(inputs.model_dump(mode="json"))
    if (
        request.benchmark_id != inputs.benchmark_id
        or request.benchmark_revision_id != inputs.benchmark_revision_id
        or request.input_set_sha256 != inputs.input_set_sha256
        or request.view_recipe != inputs.view_recipe
        or request.recipe.public_fixture_sha256 != inputs.public_fixture_sha256
        or request.document_rows != tuple(row.row for row in inputs.documents)
        or request.query_rows != tuple(row.row for row in inputs.queries)
        or request.input_manifest.sha256
        != sha256_bytes(canonical_json_bytes(inputs.model_dump(mode="json")))
    ):
        raise ValueError(
            "benchmark staged input pointer, purpose rows or immutable identities differ"
        )
    tokens = {
        (profile_key(row.row.profile), row.row.view): row.token_count for row in inputs.documents
    }
    if any(
        tokens[(profile_key(source.profile), source.selection_view)] != source.selection_token_count
        for source in request.sources
    ):
        raise ValueError("benchmark selected tokenizer lengths differ from staged witnesses")


def validate_benchmark_invocation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    inputs: BenchmarkStagedInputs,
) -> None:
    """Compare pure projections; no constructor grants launch or validates a protected prefix."""
    _integer_json(invocation)
    validate_benchmark_staged_inputs(request, inputs)
    invocation = BenchmarkWorkerInvocation.model_validate(invocation.model_dump(mode="json"))
    expected_runtime = request.cpu if invocation.device == "CPU" else request.cuda
    raw = canonical_json_bytes(inputs.model_dump(mode="json"))
    if (
        invocation.owner_request_sha256 != request.request_sha256
        or invocation.runtime != expected_runtime
        or invocation.benchmark_id != request.benchmark_id
        or invocation.benchmark_revision_id != request.benchmark_revision_id
        or invocation.input_set_sha256 != request.input_set_sha256
        or invocation.family != request.family
        or invocation.recipe != request.recipe
        or invocation.execution_policy != request.execution_policy
        or invocation.local_input.sha256 != sha256_bytes(raw)
        or invocation.local_input.byte_count != len(raw)
    ):
        raise ValueError("benchmark worker projection differs from its exact owner request")


class BenchmarkLocalBinary(_BenchmarkContract):
    member_name: BenchmarkF32Name
    sha256: Sha256
    byte_count: int = Field(ge=4096, le=MAX_BENCHMARK_OUTPUT_BYTES, strict=True)
    dtype: Literal["FLOAT32"] = "FLOAT32"
    byte_order: Literal["LITTLE_ENDIAN"] = "LITTLE_ENDIAN"
    layout: Literal["ROW_MAJOR"] = "ROW_MAJOR"

    @model_validator(mode="after")
    def complete_rows(self) -> BenchmarkLocalBinary:
        if self.byte_count % 4096:
            raise ValueError("benchmark f32 member must contain complete1024-component rows")
        return self


class BenchmarkLocalJson(_BenchmarkContract):
    member_name: Literal[
        "token-witness.json", "timings.json", "resources.json", "worker-result.json"
    ]
    sha256: Sha256
    byte_count: int = Field(ge=1, le=MAX_BENCHMARK_OUTPUT_BYTES, strict=True)
    schema_ref: str

    @model_validator(mode="after")
    def fixed_json_member(self) -> BenchmarkLocalJson:
        definition = {
            "token-witness.json": "tokenWitness",
            "timings.json": "invocationTimings",
            "resources.json": "resources",
            "worker-result.json": "workerResult",
        }[self.member_name]
        if self.schema_ref != f"{EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF}#/$defs/{definition}":
            raise ValueError("benchmark fixed local JSON alias/schema differs")
        return self


class BenchmarkSampleKey(_BenchmarkContract):
    phase: Literal["COLD_DOCUMENT", "WARM_DOCUMENT", "QUERY", "CAPACITY", "SYNTHETIC"]
    repetition: int | None = Field(ge=1, le=5, strict=True)
    query_ordinal: int | None = Field(ge=1, le=2, strict=True)
    synthetic_case: int | None = Field(ge=1, le=6, strict=True)
    batch_size: int = Field(ge=1, le=4, strict=True)

    @model_validator(mode="after")
    def exact_sample(self) -> BenchmarkSampleKey:
        expected = {
            "COLD_DOCUMENT": (False, False, False, (4,)),
            "WARM_DOCUMENT": (True, False, False, (4,)),
            "QUERY": (True, True, False, (1,)),
            "CAPACITY": (False, False, False, (1, 4)),
            "SYNTHETIC": (False, False, True, (1, 4)),
        }[self.phase]
        if (
            self.repetition is not None,
            self.query_ordinal is not None,
            self.synthetic_case is not None,
        ) != expected[:3] or self.batch_size not in expected[3]:
            raise ValueError("benchmark sample identity differs from its fixed phase")
        return self


def _sample_program(ordinal: int) -> tuple[BenchmarkSampleKey, ...]:
    cold = BenchmarkSampleKey(
        phase="COLD_DOCUMENT",
        repetition=None,
        query_ordinal=None,
        synthetic_case=None,
        batch_size=4,
    )
    if ordinal not in (1, 2):
        return (cold,)
    return (
        cold,
        *(
            BenchmarkSampleKey(
                phase="SYNTHETIC",
                repetition=None,
                query_ordinal=None,
                synthetic_case=case,
                batch_size=batch,
            )
            for case in range(1, 7)
            for batch in (1, 4)
        ),
        *(
            BenchmarkSampleKey(
                phase="WARM_DOCUMENT",
                repetition=repetition,
                query_ordinal=None,
                synthetic_case=None,
                batch_size=4,
            )
            for repetition in range(1, 6)
        ),
        *(
            BenchmarkSampleKey(
                phase="QUERY",
                repetition=repetition,
                query_ordinal=query,
                synthetic_case=None,
                batch_size=1,
            )
            for query in (1, 2)
            for repetition in range(1, 6)
        ),
        *(
            BenchmarkSampleKey(
                phase="CAPACITY",
                repetition=None,
                query_ordinal=None,
                synthetic_case=None,
                batch_size=batch,
            )
            for batch in (1, 4)
        ),
    )


class BenchmarkVectorSample(_BenchmarkContract):
    """Closed ranges in immutable local members; byte/norm verification belongs to owner."""

    key: BenchmarkSampleKey
    purpose: BenchmarkPurpose
    space_sha256: Sha256
    ordered_rows: tuple[Sha256, ...] = Field(max_length=18)
    binary: BenchmarkLocalBinary
    byte_offset: int = Field(ge=0, le=MAX_BENCHMARK_OUTPUT_BYTES - 4096, strict=True)
    byte_count: int = Field(ge=4096, le=18 * 4096, strict=True)
    row_count: int = Field(ge=1, le=18, strict=True)
    dimension: Literal[1024] = 1024
    sample_sha256: Sha256

    @model_validator(mode="after")
    def exact_vector_range(self) -> BenchmarkVectorSample:
        fixture = self.key.phase in {"SYNTHETIC", "CAPACITY"}
        expected_purpose = "QUERY" if self.key.phase == "QUERY" else "DOCUMENT"
        name = (
            "cold-documents.f32"
            if self.key.phase == "COLD_DOCUMENT"
            else f"query-{self.key.query_ordinal}-{self.key.repetition}.f32"
            if self.key.phase == "QUERY"
            else "supplementary-documents.f32"
        )
        if (
            self.purpose != expected_purpose
            or self.binary.member_name != name
            or self.byte_count != self.row_count * 4096
            or self.byte_offset % 4096
            or self.byte_offset + self.byte_count > self.binary.byte_count
            or len(set(self.ordered_rows)) != len(self.ordered_rows)
            or (fixture and (self.ordered_rows or self.row_count != self.key.batch_size))
            or (not fixture and len(self.ordered_rows) != self.row_count)
            or (self.key.phase == "QUERY" and self.row_count != 1)
            or (self.key.phase in {"COLD_DOCUMENT", "WARM_DOCUMENT"} and self.row_count < 6)
            or (
                self.key.phase in {"COLD_DOCUMENT", "QUERY"}
                and (self.byte_offset or self.binary.byte_count != self.byte_count)
            )
        ):
            raise ValueError("benchmark sample purpose/member/order/range differs")
        _hash(self, "sample_sha256")
        return self


class BenchmarkTokenRow(_BenchmarkContract):
    row_sha256: Sha256
    input_ids: tuple[BenchmarkTokenId, ...] = Field(min_length=1, max_length=2048)
    attention_mask: tuple[Annotated[int, Field(ge=0, le=1, strict=True)], ...] = Field(
        min_length=1, max_length=2048
    )
    token_type_ids: tuple[BenchmarkTokenId, ...] | None = Field(min_length=1, max_length=2048)
    token_count: int = Field(ge=1, le=2048, strict=True)
    token_ids_sha256: Sha256

    @model_validator(mode="after")
    def exact_token_row(self) -> BenchmarkTokenRow:
        if (
            self.token_count > len(self.input_ids)
            or len(self.attention_mask) != len(self.input_ids)
            or self.attention_mask
            != (1,) * self.token_count + (0,) * (len(self.input_ids) - self.token_count)
            or (self.token_type_ids is not None and len(self.token_type_ids) != len(self.input_ids))
        ):
            raise ValueError("benchmark actual token IDs/mask/type lengths differ")
        if self.token_ids_sha256 != content_sha256(
            {
                "input_ids": self.input_ids[: self.token_count],
                "token_type_ids": None
                if self.token_type_ids is None
                else self.token_type_ids[: self.token_count],
            }
        ):
            raise ValueError("benchmark unpadded token-ID hash differs")
        return self


class BenchmarkTokenBatch(_BenchmarkContract):
    purpose: BenchmarkPurpose
    pad_token_id: BenchmarkTokenId
    rows: tuple[BenchmarkTokenRow, ...] = Field(min_length=1, max_length=4)
    batch_sha256: Sha256

    @model_validator(mode="after")
    def exact_padding(self) -> BenchmarkTokenBatch:
        if len({len(row.input_ids) for row in self.rows}) != 1 or len(
            self.rows[0].input_ids
        ) != max(row.token_count for row in self.rows):
            raise ValueError("benchmark token batch must use exact longest padding")
        if any(
            any(token != self.pad_token_id for token in row.input_ids[row.token_count :])
            for row in self.rows
        ):
            raise ValueError("benchmark masked token IDs differ from the actual pad token")
        _hash(self, "batch_sha256", MAX_BENCHMARK_OUTPUT_BYTES)
        return self


class BenchmarkTokenSample(_BenchmarkContract):
    key: BenchmarkSampleKey
    batches: tuple[BenchmarkTokenBatch, ...] = Field(min_length=1, max_length=5)
    sample_sha256: Sha256

    @model_validator(mode="after")
    def exact_batch_program(self) -> BenchmarkTokenSample:
        purpose = "QUERY" if self.key.phase == "QUERY" else "DOCUMENT"
        if any(
            batch.purpose != purpose or len(batch.rows) > self.key.batch_size
            for batch in self.batches
        ):
            raise ValueError("benchmark token sample mixes purpose or exceeds actual batch")
        if self.key.phase in {"QUERY", "CAPACITY", "SYNTHETIC"} and (
            len(self.batches) != 1 or len(self.batches[0].rows) != self.key.batch_size
        ):
            raise ValueError("benchmark single-call token sample shape differs")
        if self.key.phase == "CAPACITY" and any(
            row.token_count != 2048 for row in self.batches[0].rows
        ):
            raise ValueError("benchmark capacity witness must have exactly2048 tokens")
        _hash(self, "sample_sha256", MAX_BENCHMARK_OUTPUT_BYTES)
        return self


class BenchmarkTokenWitness(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-token-witness/1.0"] = (
        "embedding-device-benchmark-token-witness/1.0"
    )
    invocation_sha256: Sha256
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    samples: tuple[BenchmarkTokenSample, ...] = Field(min_length=1, max_length=64)
    witness_sha256: Sha256

    @model_validator(mode="after")
    def complete_witness(self) -> BenchmarkTokenWitness:
        if tuple(sample.key for sample in self.samples) != _sample_program(self.launch_ordinal):
            raise ValueError("benchmark token witness omits/reorders/repeats a prescribed sample")
        _hash(self, "witness_sha256", MAX_BENCHMARK_OUTPUT_BYTES)
        return self


class BenchmarkLocalVector(_BenchmarkContract):
    member_name: BenchmarkF32Name
    sha256: Sha256
    byte_count: int = Field(ge=4096, le=18 * 4096, strict=True)
    row_count: int = Field(ge=1, le=18, strict=True)
    dimension: Literal[1024] = 1024
    purpose: BenchmarkPurpose
    space_sha256: Sha256

    @model_validator(mode="after")
    def exact_local_vector(self) -> BenchmarkLocalVector:
        if (
            self.byte_count != self.row_count * 4096
            or self.member_name == "supplementary-documents.f32"
        ):
            raise ValueError("benchmark checkpoint requires one complete fixed cold/query member")
        return self


def _phase_identity(sequence: int) -> tuple[BenchmarkPhase, int | None, int | None]:
    if sequence == 1:
        return "COLD_READY", None, None
    query, remainder = divmod(sequence - 2, 10)
    repetition, ready = divmod(remainder, 2)
    return ("QUERY_READY" if ready else "QUERY_PREPARED"), query + 1, repetition + 1


class BenchmarkCheckpoint(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-checkpoint/1.0"] = (
        "embedding-device-benchmark-checkpoint/1.0"
    )
    kind: Literal["LOCAL_CHECKPOINT"] = "LOCAL_CHECKPOINT"
    execution_id: BenchmarkExecutionId
    invocation_sha256: Sha256
    sequence: int = Field(ge=1, le=21, strict=True)
    phase: BenchmarkPhase
    query_ordinal: int | None = Field(ge=1, le=2, strict=True)
    query_repetition: int | None = Field(ge=1, le=5, strict=True)
    vector: BenchmarkLocalVector | None
    encode_duration_ns: BenchmarkNanoseconds | None
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def exact_checkpoint(self) -> BenchmarkCheckpoint:
        if (self.phase, self.query_ordinal, self.query_repetition) != _phase_identity(
            self.sequence
        ):
            raise ValueError("benchmark checkpoint sequence/phase/query identity differs")
        if self.phase == "QUERY_PREPARED":
            if self.vector is not None or self.encode_duration_ns is not None:
                raise ValueError("prepared query cannot include an already encoded vector/span")
        else:
            expected_name = (
                "cold-documents.f32"
                if self.phase == "COLD_READY"
                else f"query-{self.query_ordinal}-{self.query_repetition}.f32"
            )
            expected_purpose = "DOCUMENT" if self.phase == "COLD_READY" else "QUERY"
            if (
                self.vector is None
                or self.encode_duration_ns is None
                or self.vector.member_name != expected_name
                or self.vector.purpose != expected_purpose
                or (self.phase == "QUERY_READY" and self.vector.row_count != 1)
                or (self.phase == "COLD_READY" and self.vector.row_count < 6)
            ):
                raise ValueError("benchmark ready checkpoint vector/purpose/shape/span differs")
        _hash(self, "checkpoint_sha256")
        return self


class BenchmarkAck(_BenchmarkContract):
    """Phase identity only; actual parent FD and fresh authorization remain owner duties."""

    schema_version: Literal["embedding-device-benchmark-ack/1.0"] = (
        "embedding-device-benchmark-ack/1.0"
    )
    kind: Literal["OWNER_CONTINUE"] = "OWNER_CONTINUE"
    execution_id: BenchmarkExecutionId
    invocation_sha256: Sha256
    sequence: int = Field(ge=1, le=21, strict=True)
    phase: BenchmarkPhase
    query_ordinal: int | None = Field(ge=1, le=2, strict=True)
    query_repetition: int | None = Field(ge=1, le=5, strict=True)
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def exact_ack(self) -> BenchmarkAck:
        if (self.phase, self.query_ordinal, self.query_repetition) != _phase_identity(
            self.sequence
        ):
            raise ValueError("benchmark ACK sequence/phase/query identity differs")
        return self


class BenchmarkSession(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-session/1.0"] = (
        "embedding-device-benchmark-session/1.0"
    )
    execution_id: BenchmarkExecutionId
    invocation_sha256: Sha256
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    checkpoints: tuple[BenchmarkCheckpoint, ...] = Field(min_length=1, max_length=21)
    acks: tuple[BenchmarkAck, ...] = Field(min_length=1, max_length=21)
    session_sha256: Sha256

    @model_validator(mode="after")
    def fixed_session(self) -> BenchmarkSession:
        count = 21 if self.launch_ordinal in (1, 2) else 1
        if len(self.checkpoints) != count or len(self.acks) != count:
            raise ValueError("benchmark session requires the exact1/21 checkpoint/ACK program")
        for expected, (checkpoint, ack) in enumerate(
            zip(self.checkpoints, self.acks, strict=True), 1
        ):
            identity = checkpoint.model_dump(
                mode="json", exclude={"schema_version", "kind", "vector", "encode_duration_ns"}
            )
            if (
                checkpoint.sequence != expected
                or checkpoint.execution_id != self.execution_id
                or checkpoint.invocation_sha256 != self.invocation_sha256
                or ack.model_dump(mode="json", exclude={"schema_version", "kind"}) != identity
            ):
                raise ValueError("benchmark session missing/reordered/foreign or mismatched ACK")
        _hash(self, "session_sha256")
        return self


class BenchmarkQueryEncodeTiming(_BenchmarkContract):
    query_ordinal: int = Field(ge=1, le=2, strict=True)
    repetition: int = Field(ge=1, le=5, strict=True)
    encode_ns: BenchmarkNanoseconds


class BenchmarkInvocationTimings(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-invocation-timings/1.0"] = (
        "embedding-device-benchmark-invocation-timings/1.0"
    )
    invocation_sha256: Sha256
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    device: BenchmarkDevice
    startup_ns: BenchmarkNanoseconds
    load_hash_ns: BenchmarkNanoseconds
    cold_encode_ns: BenchmarkNanoseconds
    warmup_count: int = Field(ge=0, le=1, strict=True)
    warm_encode_ns: tuple[BenchmarkNanoseconds, ...] = Field(max_length=5)
    query_encode_ns: tuple[BenchmarkQueryEncodeTiming, ...] = Field(max_length=10)
    timing_sha256: Sha256

    @model_validator(mode="after")
    def fixed_repetitions(self) -> BenchmarkInvocationTimings:
        _device_ordinal(self.device, self.launch_ordinal)
        warm = self.launch_ordinal in (1, 2)
        keys = tuple((query.query_ordinal, query.repetition) for query in self.query_encode_ns)
        expected = (
            tuple((query, repetition) for query in (1, 2) for repetition in range(1, 6))
            if warm
            else ()
        )
        if (
            self.warmup_count != int(warm)
            or len(self.warm_encode_ns) != (5 if warm else 0)
            or keys != expected
        ):
            raise ValueError("benchmark invocation timing lacks the exact warm/query program")
        _hash(self, "timing_sha256")
        return self


class BenchmarkDeviceTimings(_BenchmarkContract):
    """Exact pure performance-gate input shape; no performance verdict is computed here."""

    device: BenchmarkDevice
    cold_end_to_end_us: tuple[BenchmarkMicroseconds, ...] = Field(min_length=3, max_length=3)
    warm_batch_encode_us: tuple[BenchmarkMicroseconds, ...] = Field(min_length=5, max_length=5)
    query_encode_us: tuple[tuple[BenchmarkMicroseconds, ...], ...] = Field(
        min_length=2, max_length=2
    )
    query_end_to_end_us: tuple[tuple[BenchmarkMicroseconds, ...], ...] = Field(
        min_length=2, max_length=2
    )

    @model_validator(mode="after")
    def exact_query_samples(self) -> BenchmarkDeviceTimings:
        if any(len(samples) != 5 for samples in (*self.query_encode_us, *self.query_end_to_end_us)):
            raise ValueError("benchmark requires exactly five samples of each query clock")
        return self


class BenchmarkColdTiming(_BenchmarkContract):
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    end_to_end_ns: BenchmarkNanoseconds
    startup_ns: BenchmarkNanoseconds
    load_hash_ns: BenchmarkNanoseconds
    encode_ns: BenchmarkNanoseconds

    @model_validator(mode="after")
    def serial_cold_spans(self) -> BenchmarkColdTiming:
        if self.end_to_end_ns < self.startup_ns + self.load_hash_ns + self.encode_ns:
            raise ValueError("benchmark cold total cannot exclude its serial startup/load/encode")
        return self


class BenchmarkQueryTiming(BenchmarkQueryEncodeTiming):
    authorization_ns: BenchmarkNanoseconds
    end_to_end_ns: BenchmarkNanoseconds

    @model_validator(mode="after")
    def authorization_included(self) -> BenchmarkQueryTiming:
        if self.end_to_end_ns < self.authorization_ns + self.encode_ns:
            raise ValueError("benchmark query total cannot exclude fresh authorization/encode")
        return self


class BenchmarkTimingEvidence(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-timing-evidence/1.0"] = (
        "embedding-device-benchmark-timing-evidence/1.0"
    )
    device: BenchmarkDevice
    cold: tuple[BenchmarkColdTiming, ...] = Field(min_length=3, max_length=3)
    warm_encode_ns: tuple[BenchmarkNanoseconds, ...] = Field(min_length=5, max_length=5)
    queries: tuple[BenchmarkQueryTiming, ...] = Field(min_length=10, max_length=10)
    gate_timings: BenchmarkDeviceTimings
    timing_sha256: Sha256

    @model_validator(mode="after")
    def exact_clocks(self) -> BenchmarkTimingEvidence:
        ordinals = tuple(
            index
            for index, device in enumerate(BENCHMARK_DEVICE_SEQUENCE, 1)
            if device == self.device
        )
        if tuple(cold.launch_ordinal for cold in self.cold) != ordinals or tuple(
            (query.query_ordinal, query.repetition) for query in self.queries
        ) != tuple((query, repeat) for query in (1, 2) for repeat in range(1, 6)):
            raise ValueError(
                "benchmark raw timing order differs from the fixed device/query recipe"
            )

        def microseconds(ns: int) -> int:
            return ns // 1000 if self.device == "CPU" else (ns + 999) // 1000

        expected = {
            "device": self.device,
            "cold_end_to_end_us": [microseconds(cold.end_to_end_ns) for cold in self.cold],
            "warm_batch_encode_us": [microseconds(ns) for ns in self.warm_encode_ns],
            "query_encode_us": [
                [
                    microseconds(query.encode_ns)
                    for query in self.queries
                    if query.query_ordinal == ordinal
                ]
                for ordinal in (1, 2)
            ],
            "query_end_to_end_us": [
                [
                    microseconds(query.end_to_end_ns)
                    for query in self.queries
                    if query.query_ordinal == ordinal
                ]
                for ordinal in (1, 2)
            ],
        }
        if self.gate_timings.model_dump(mode="json") != expected:
            raise ValueError(
                "benchmark gate microseconds differ from conservative raw-ns conversion"
            )
        _hash(self, "timing_sha256")
        return self


class BenchmarkCapacitySample(_BenchmarkContract):
    batch_size: Literal[1, 4]
    maximum_tokens: Literal[2048] = 2048
    input_text_sha256: Sha256
    token_ids_sha256: Sha256
    peak_rss_bytes: int = Field(ge=1, le=64 * 1024**3, strict=True)
    peak_allocated_gpu_bytes: int | None = Field(ge=0, le=64 * 1024**3, strict=True)
    peak_reserved_gpu_bytes: int | None = Field(ge=0, le=64 * 1024**3, strict=True)
    peak_whole_process_gpu_bytes: int | None = Field(ge=0, le=64 * 1024**3, strict=True)


class BenchmarkResourceEvidence(_BenchmarkContract):
    """Integer observations retain failures above policy limits; they do not attest cleanup."""

    schema_version: Literal["embedding-device-benchmark-resources/1.0"] = (
        "embedding-device-benchmark-resources/1.0"
    )
    invocation_sha256: Sha256
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    device: BenchmarkDevice
    peak_rss_bytes: int = Field(ge=1, le=64 * 1024**3, strict=True)
    peak_allocated_gpu_bytes: int | None = Field(ge=0, le=64 * 1024**3, strict=True)
    peak_reserved_gpu_bytes: int | None = Field(ge=0, le=64 * 1024**3, strict=True)
    peak_whole_process_gpu_bytes: int | None = Field(ge=0, le=64 * 1024**3, strict=True)
    peak_whole_device_gpu_bytes: int | None = Field(ge=0, le=64 * 1024**3, strict=True)
    owner_observation_count: int = Field(ge=0, le=4096, strict=True)
    oom_count: int = Field(ge=0, le=64, strict=True)
    other_consumer_overlap_count: int = Field(ge=0, le=4096, strict=True)
    capacity_samples: tuple[BenchmarkCapacitySample, ...] = Field(max_length=2)
    resource_sha256: Sha256

    @model_validator(mode="after")
    def resource_shape(self) -> BenchmarkResourceEvidence:
        _device_ordinal(self.device, self.launch_ordinal)
        keys = tuple(sample.batch_size for sample in self.capacity_samples)
        if keys not in ((), (1,), (1, 4)) or (self.launch_ordinal not in (1, 2) and keys):
            raise ValueError(
                "benchmark capacity observations reorder/duplicate/extend the fixed program"
            )
        peaks = (
            self.peak_allocated_gpu_bytes,
            self.peak_reserved_gpu_bytes,
            self.peak_whole_process_gpu_bytes,
            self.peak_whole_device_gpu_bytes,
        )
        for sample in self.capacity_samples:
            if sample.peak_rss_bytes > self.peak_rss_bytes:
                raise ValueError("benchmark aggregate RSS omits a capacity peak")
            for sample_peak, total in zip(
                (
                    sample.peak_allocated_gpu_bytes,
                    sample.peak_reserved_gpu_bytes,
                    sample.peak_whole_process_gpu_bytes,
                ),
                peaks,
                strict=False,
            ):
                if sample_peak is not None and (total is None or sample_peak > total):
                    raise ValueError("benchmark aggregate GPU peak omits a capacity observation")
        if self.device == "CPU" and (
            any(peak is not None for peak in peaks)
            or self.owner_observation_count
            or self.other_consumer_overlap_count
            or any(
                sample.peak_allocated_gpu_bytes is not None
                or sample.peak_reserved_gpu_bytes is not None
                or sample.peak_whole_process_gpu_bytes is not None
                for sample in self.capacity_samples
            )
        ):
            raise ValueError("CPU benchmark cannot assert GPU observations")
        _hash(self, "resource_sha256")
        return self


class BenchmarkSyntheticRejection(_BenchmarkContract):
    synthetic_case: Literal[7, 8]
    batch_size: Literal[1, 4]
    reason: Literal["EMPTY_REJECTED", "OVERFLOW_REJECTED"]

    @model_validator(mode="after")
    def exact_negative(self) -> BenchmarkSyntheticRejection:
        if self.reason != ("EMPTY_REJECTED" if self.synthetic_case == 7 else "OVERFLOW_REJECTED"):
            raise ValueError("benchmark public negative case/reason differs")
        return self


class BenchmarkWorkerResult(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-worker-result/1.0"] = (
        "embedding-device-benchmark-worker-result/1.0"
    )
    kind: Literal["WORKER_RESULT"] = "WORKER_RESULT"
    execution_id: BenchmarkExecutionId
    invocation_sha256: Sha256
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    device: BenchmarkDevice
    status: Literal["COMPLETED", "FAILED"]
    reason_codes: tuple[BenchmarkReason, ...] = Field(max_length=16)
    vectors: tuple[BenchmarkVectorSample, ...] = Field(max_length=32)
    synthetic_rejections: tuple[BenchmarkSyntheticRejection, ...] = Field(max_length=4)
    token_witness: BenchmarkLocalJson | None
    timings: BenchmarkInvocationTimings | None
    resources: BenchmarkResourceEvidence | None
    result_sha256: Sha256

    @model_validator(mode="after")
    def complete_or_explicit_failure(self) -> BenchmarkWorkerResult:
        _device_ordinal(self.device, self.launch_ordinal)
        if self.reason_codes != tuple(sorted(set(self.reason_codes))) or (
            self.status == "FAILED"
        ) != bool(self.reason_codes):
            raise ValueError("benchmark worker result needs unique ordered failure reasons")
        program = _sample_program(self.launch_ordinal)
        if tuple(vector.key for vector in self.vectors) != program[: len(self.vectors)]:
            raise ValueError(
                "benchmark partial/completed vectors must preserve the exact phase prefix"
            )
        if self.status == "COMPLETED":
            if (
                tuple(vector.key for vector in self.vectors) != _sample_program(self.launch_ordinal)
                or self.token_witness is None
                or self.timings is None
                or self.resources is None
            ):
                raise ValueError(
                    "completed result lacks its exact vector/token/timing/resource program"
                )
            if self.token_witness.member_name != "token-witness.json":
                raise ValueError("benchmark token witness alias differs")
            expected_negatives = (
                tuple((case, batch) for case in (7, 8) for batch in (1, 4))
                if self.launch_ordinal in (1, 2)
                else ()
            )
            if tuple(
                (negative.synthetic_case, negative.batch_size)
                for negative in self.synthetic_rejections
            ) != expected_negatives or tuple(
                sample.batch_size for sample in self.resources.capacity_samples
            ) != ((1, 4) if self.launch_ordinal in (1, 2) else ()):
                raise ValueError(
                    "benchmark completed result lacks its prescribed negative/capacity probes"
                )
            if self.device == "CUDA" and (
                not self.resources.owner_observation_count
                or any(
                    peak is None
                    for peak in (
                        self.resources.peak_allocated_gpu_bytes,
                        self.resources.peak_reserved_gpu_bytes,
                        self.resources.peak_whole_process_gpu_bytes,
                        self.resources.peak_whole_device_gpu_bytes,
                    )
                )
            ):
                raise ValueError(
                    "complete CUDA evidence needs reserved and independent GPU observations"
                )
        for evidence in (self.timings, self.resources):
            if evidence is not None and (
                evidence.invocation_sha256 != self.invocation_sha256
                or evidence.launch_ordinal != self.launch_ordinal
                or evidence.device != self.device
            ):
                raise ValueError("benchmark emitted evidence belongs to another invocation/device")
        _hash(self, "result_sha256")
        return self


class BenchmarkLaunchReceipt(_BenchmarkContract):
    """Owner evidence pointer; parsing alone cannot establish process/device cleanup."""

    schema_version: Literal["embedding-device-benchmark-launch-receipt/1.0"] = (
        "embedding-device-benchmark-launch-receipt/1.0"
    )
    job_id: JobId
    execution_id: BenchmarkExecutionId
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    device: BenchmarkDevice
    invocation_sha256: Sha256
    observed_runtime_sha256: Sha256
    worker_result: ArtifactMemberPointer
    session: ArtifactMemberPointer
    cleanup: Literal["CONFIRMED", "UNCERTAIN"]
    evidence: ArtifactMemberPointer
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def fixed_launch(self) -> BenchmarkLaunchReceipt:
        _device_ordinal(self.device, self.launch_ordinal)
        _member(self.worker_result, "workerResult", "worker-result.json")
        _member(self.session, "session", "session.json")
        _hash(self, "receipt_sha256")
        return self


class BenchmarkPublishedVectorSample(_BenchmarkContract):
    launch_ordinal: int = Field(ge=1, le=6, strict=True)
    sample: BenchmarkVectorSample
    binary_member: ArtifactMemberPointer

    @model_validator(mode="after")
    def canonical_binary_pointer(self) -> BenchmarkPublishedVectorSample:
        if (
            self.binary_member.member_path != self.sample.binary.member_name
            or self.binary_member.sha256 != self.sample.binary.sha256
            or self.binary_member.schema_ref
            != "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"
            or self.binary_member.media_type != "application/octet-stream"
        ):
            raise ValueError(
                "benchmark published sample points to different canonical binary bytes"
            )
        return self


class BenchmarkVectorEvidence(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-vector-evidence/1.0"] = (
        "embedding-device-benchmark-vector-evidence/1.0"
    )
    device: BenchmarkDevice
    purpose: BenchmarkPurpose
    space: EmbeddingSpace
    rows: tuple[BenchmarkRowRef, ...] = Field(min_length=2, max_length=18)
    samples: tuple[BenchmarkPublishedVectorSample, ...] = Field(min_length=1, max_length=32)
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def fixed_vector_evidence(self) -> BenchmarkVectorEvidence:
        _rows(self.rows, self.purpose)
        if (
            self.space.purpose != self.purpose
            or self.space.runtime.device != self.device
            or (self.purpose == "QUERY" and len(self.rows) != 2)
            or (self.purpose == "DOCUMENT" and len(self.rows) < 6)
        ):
            raise ValueError("benchmark vector evidence mixes device/purpose/row matrix")
        _benchmark_model(self.space.model_spec)
        expected = tuple(
            (ordinal, key)
            for ordinal, device in enumerate(BENCHMARK_DEVICE_SEQUENCE, 1)
            if device == self.device
            for key in _sample_program(ordinal)
            if (key.phase == "QUERY") == (self.purpose == "QUERY")
        )
        if (
            tuple((published.launch_ordinal, published.sample.key) for published in self.samples)
            != expected
        ):
            raise ValueError("benchmark published vector evidence lacks exact prescribed samples")
        for published in self.samples:
            sample = published.sample
            expected_rows = (
                (self.rows[sample.key.query_ordinal - 1].row_sha256,)
                if sample.key.phase == "QUERY" and sample.key.query_ordinal is not None
                else tuple(row.row_sha256 for row in self.rows)
                if sample.key.phase in {"COLD_DOCUMENT", "WARM_DOCUMENT"}
                else ()
            )
            if (
                sample.purpose != self.purpose
                or sample.space_sha256 != self.space.space_sha256
                or sample.ordered_rows != expected_rows
            ):
                raise ValueError("benchmark vector evidence points to other purpose/rows/space")
        _hash(self, "evidence_sha256", MAX_BENCHMARK_OUTPUT_BYTES)
        return self


class BenchmarkDeviceResult(_BenchmarkContract):
    device: BenchmarkDevice
    spaces: BenchmarkPurposeSpaces
    document_vectors: ArtifactMemberPointer
    query_vectors: ArtifactMemberPointer
    token_witness: ArtifactMemberPointer
    timing_evidence: ArtifactMemberPointer
    resource_evidence: tuple[ArtifactMemberPointer, ...] = Field(min_length=3, max_length=3)
    timings: BenchmarkDeviceTimings
    launch_receipts: tuple[ArtifactMemberPointer, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def completed_device(self) -> BenchmarkDeviceResult:
        if self.spaces.document.runtime.device != self.device or self.timings.device != self.device:
            raise ValueError("benchmark completed-device space/timing device differs")
        _member(self.document_vectors, "vectorEvidence", f"{self.device.lower()}-documents.json")
        _member(self.query_vectors, "vectorEvidence", f"{self.device.lower()}-queries.json")
        _member(self.token_witness, "tokenWitness", "token-witness.json")
        _member(self.timing_evidence, "timingEvidence", f"{self.device.lower()}-timings.json")
        for pointer in self.resource_evidence:
            _member(pointer, "resources", "resources.json")
        for pointer in self.launch_receipts:
            _member(pointer, "launchReceipt", "launch-receipt.json")
        for pointers in (self.resource_evidence, self.launch_receipts):
            if len({(p.artifact_id, p.artifact_revision_id, p.member_path) for p in pointers}) != 3:
                raise ValueError("benchmark completed-device receipts repeat an Artifact member")
        return self


class BenchmarkScoreBinary(_BenchmarkContract):
    member_path: Literal["rank-evidence.f64"] = "rank-evidence.f64"
    schema_ref: Literal["eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0"] = (
        "eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0"
    )
    media_type: Literal["application/octet-stream"] = "application/octet-stream"
    sha256: Sha256
    byte_count: int = Field(ge=8, le=1024**2, strict=True)
    dtype: Literal["FLOAT64"] = "FLOAT64"
    byte_order: Literal["LITTLE_ENDIAN"] = "LITTLE_ENDIAN"

    @model_validator(mode="after")
    def complete_scalars(self) -> BenchmarkScoreBinary:
        if self.byte_count % 8:
            raise ValueError("benchmark f64 evidence must contain complete binary scalars")
        return self


class BenchmarkNearTieCluster(_BenchmarkContract):
    cluster_ordinal: int = Field(ge=1, le=18, strict=True)
    row_sha256: tuple[Sha256, ...] = Field(min_length=1, max_length=18)
    cpu_score_offsets: tuple[Annotated[int, Field(ge=0, le=1024**2 - 8, strict=True)], ...] = Field(
        min_length=1, max_length=18
    )

    @model_validator(mode="after")
    def pinned_cluster_shape(self) -> BenchmarkNearTieCluster:
        if (
            len(self.row_sha256) != len(self.cpu_score_offsets)
            or len(set(self.row_sha256)) != len(self.row_sha256)
            or len(set(self.cpu_score_offsets)) != len(self.cpu_score_offsets)
            or any(offset % 8 for offset in self.cpu_score_offsets)
        ):
            raise ValueError("benchmark near-tie cluster row/score offsets differ")
        return self


class BenchmarkNearTieQuery(_BenchmarkContract):
    query_ordinal: int = Field(ge=1, le=2, strict=True)
    query_row: BenchmarkRowRef
    ordered_candidates: tuple[BenchmarkRowRef, ...] = Field(min_length=5, max_length=17)
    clusters: tuple[BenchmarkNearTieCluster, ...] = Field(min_length=1, max_length=17)

    @model_validator(mode="after")
    def pinned_reference_order(self) -> BenchmarkNearTieQuery:
        hashes = tuple(row.row_sha256 for row in self.ordered_candidates)
        if (
            self.query_row.purpose != "QUERY"
            or any(
                row.purpose != "DOCUMENT"
                or profile_key(row.profile) == profile_key(self.query_row.profile)
                for row in self.ordered_candidates
            )
            or len(set(hashes)) != len(hashes)
            or len({profile_key(row.profile) for row in self.ordered_candidates}) < 5
            or tuple(cluster.cluster_ordinal for cluster in self.clusters)
            != tuple(range(1, len(self.clusters) + 1))
            or tuple(value for cluster in self.clusters for value in cluster.row_sha256) != hashes
        ):
            raise ValueError(
                "benchmark CPU near-tie reference loses real rows/self exclusion/cluster order"
            )
        return self


class BenchmarkNearTieReference(_BenchmarkContract):
    """Pre-CUDA CPU decision pointer; actual f64 span/gap validation is not implemented here."""

    schema_version: Literal["embedding-device-benchmark-near-tie-reference/1.0"] = (
        "embedding-device-benchmark-near-tie-reference/1.0"
    )
    request_sha256: Sha256
    input_set_sha256: Sha256
    family_sha256: Sha256
    cpu_document_space_sha256: Sha256
    cpu_query_space_sha256: Sha256
    score_binary: ArtifactMemberPointer
    queries: tuple[BenchmarkNearTieQuery, ...] = Field(min_length=2, max_length=2)
    reference_sha256: Sha256

    @model_validator(mode="after")
    def exact_reference(self) -> BenchmarkNearTieReference:
        if (
            tuple(query.query_ordinal for query in self.queries) != (1, 2)
            or self.cpu_document_space_sha256 == self.cpu_query_space_sha256
        ):
            raise ValueError("benchmark CPU near-tie reference purpose/query order differs")
        if (
            self.score_binary.member_path != "rank-evidence.f64"
            or self.score_binary.media_type != "application/octet-stream"
            or self.score_binary.schema_ref
            != "eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0"
        ):
            raise ValueError("benchmark near-tie reference score binary pointer differs")
        _hash(self, "reference_sha256")
        return self


class BenchmarkRankDecision(_BenchmarkContract):
    query_ordinal: int = Field(ge=1, le=2, strict=True)
    repetition: int = Field(ge=1, le=5, strict=True)
    left_row_sha256: Sha256
    right_row_sha256: Sha256
    cpu_left_offset: int = Field(ge=0, le=1024**2 - 8, strict=True)
    cpu_right_offset: int = Field(ge=0, le=1024**2 - 8, strict=True)
    cuda_left_offset: int = Field(ge=0, le=1024**2 - 8, strict=True)
    cuda_right_offset: int = Field(ge=0, le=1024**2 - 8, strict=True)
    gap_class: Literal["WIDE_GAP", "NEAR_TIE", "EXACT_TIE"]
    order_preserved: bool = Field(strict=True)
    top5_same_cluster: bool = Field(strict=True)

    @model_validator(mode="after")
    def distinct_rows_and_offsets(self) -> BenchmarkRankDecision:
        if self.left_row_sha256 == self.right_row_sha256 or any(
            offset % 8
            for offset in (
                self.cpu_left_offset,
                self.cpu_right_offset,
                self.cuda_left_offset,
                self.cuda_right_offset,
            )
        ):
            raise ValueError("benchmark decision needs distinct real rows and aligned f64 offsets")
        return self


class BenchmarkNumericalEvidence(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-numerical-evidence/1.0"] = (
        "embedding-device-benchmark-numerical-evidence/1.0"
    )
    input_set_sha256: Sha256
    family_sha256: Sha256
    score_binary: BenchmarkScoreBinary
    near_tie_reference: ArtifactMemberPointer
    norm_failures: int = Field(ge=0, le=4096, strict=True)
    cosine_failures: int = Field(ge=0, le=4096, strict=True)
    component_failures: int = Field(ge=0, le=4096, strict=True)
    query_score_failures: int = Field(ge=0, le=4096, strict=True)
    wide_gap_order_failures: int = Field(ge=0, le=4096, strict=True)
    cluster_order_failures: int = Field(ge=0, le=4096, strict=True)
    top5_boundary_failures: int = Field(ge=0, le=4096, strict=True)
    same_device_failures: int = Field(ge=0, le=4096, strict=True)
    decisions: tuple[BenchmarkRankDecision, ...] = Field(max_length=4096)
    numerical_sha256: Sha256

    @model_validator(mode="after")
    def bounded_decisions(self) -> BenchmarkNumericalEvidence:
        _member(self.near_tie_reference, "nearTieReference", "near-tie-reference.json")
        keys = tuple(
            (
                decision.query_ordinal,
                decision.repetition,
                decision.left_row_sha256,
                decision.right_row_sha256,
            )
            for decision in self.decisions
        )
        if keys != tuple(sorted(set(keys))) or any(
            offset + 8 > self.score_binary.byte_count
            for decision in self.decisions
            for offset in (
                decision.cpu_left_offset,
                decision.cpu_right_offset,
                decision.cuda_left_offset,
                decision.cuda_right_offset,
            )
        ):
            raise ValueError(
                "benchmark numerical decisions repeat/reorder or point outside binary evidence"
            )
        _hash(self, "numerical_sha256", MAX_BENCHMARK_OUTPUT_BYTES)
        return self


class BenchmarkGateAssessment(_BenchmarkContract):
    gate: Literal[
        "SOURCE_AUTHORIZATION",
        "RUNTIME",
        "NUMERICAL",
        "PERFORMANCE",
        "CAPACITY",
        "SANDBOX",
        "GPU_LEASE",
        "CLEANUP",
        "IMAGE_TRAINER_REGRESSION",
    ]
    status: Literal["PASS", "FAIL", "NOT_RUN"]
    reason_codes: tuple[BenchmarkReason, ...] = Field(max_length=16)
    evidence: ArtifactMemberPointer | None

    @model_validator(mode="after")
    def explicit_gate_evidence(self) -> BenchmarkGateAssessment:
        if (
            self.reason_codes != tuple(sorted(set(self.reason_codes)))
            or (self.status == "FAIL" and not self.reason_codes)
            or (self.status == "PASS" and (self.reason_codes or self.evidence is None))
        ):
            raise ValueError("benchmark gate status lacks consistent evidence/reasons")
        return self


class BenchmarkOwnerGateEvidence(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-owner-gate-evidence/1.0"] = (
        "embedding-device-benchmark-owner-gate-evidence/1.0"
    )
    request_sha256: Sha256
    gates: tuple[BenchmarkGateAssessment, ...] = Field(min_length=9, max_length=9)
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def fixed_gate_set(self) -> BenchmarkOwnerGateEvidence:
        if tuple(gate.gate for gate in self.gates) != BENCHMARK_GATE_ORDER:
            raise ValueError("benchmark owner evidence must retain the exact nine gates")
        _hash(self, "evidence_sha256")
        return self


class BenchmarkOwnerResult(_BenchmarkContract):
    schema_version: Literal["embedding-device-benchmark-result/1.0"] = (
        "embedding-device-benchmark-result/1.0"
    )
    kind: Literal["OWNER_RESULT"] = "OWNER_RESULT"
    purpose: Literal["LOCAL_EMBEDDING_DEVICE_BENCHMARK"] = "LOCAL_EMBEDDING_DEVICE_BENCHMARK"
    benchmark_id: BenchmarkId
    benchmark_revision_id: BenchmarkRevisionId
    request_sha256: Sha256
    status: Literal["MEASURED", "INSUFFICIENT", "FAILED", "UNCERTAIN", "WAIT_FOR_GPU"]
    reason_codes: tuple[BenchmarkReason, ...] = Field(max_length=16)
    cpu: BenchmarkDeviceResult | None
    cuda: BenchmarkDeviceResult | None
    numerical_evidence: ArtifactMemberPointer | None
    near_tie_reference: ArtifactMemberPointer | None
    owner_gate_evidence: ArtifactMemberPointer
    result_sha256: Sha256

    @model_validator(mode="after")
    def explicit_result(self) -> BenchmarkOwnerResult:
        if self.reason_codes != tuple(sorted(set(self.reason_codes))) or (
            self.status != "MEASURED" and not self.reason_codes
        ):
            raise ValueError(
                "benchmark result requires ordered explicit failure/limitation reasons"
            )
        if (self.cpu is not None and self.cpu.device != "CPU") or (
            self.cuda is not None and self.cuda.device != "CUDA"
        ):
            raise ValueError("benchmark owner result swaps device evidence")
        if self.status == "MEASURED" and any(
            value is None
            for value in (self.cpu, self.cuda, self.numerical_evidence, self.near_tie_reference)
        ):
            raise ValueError(
                "MEASURED requires both complete devices and numerical/near-tie evidence"
            )
        if self.numerical_evidence is not None:
            _member(self.numerical_evidence, "numericalEvidence", "numerical-evidence.json")
        if self.near_tie_reference is not None:
            _member(self.near_tie_reference, "nearTieReference", "near-tie-reference.json")
        _member(self.owner_gate_evidence, "ownerGateEvidence", "owner-gates.json")
        _hash(self, "result_sha256")
        return self


type EmbeddingDeviceBenchmarkMessage = Annotated[
    BenchmarkRecipe
    | BenchmarkModelFamily
    | BenchmarkStagedInputs
    | BenchmarkExecutionPolicy
    | BenchmarkOwnerRequest
    | BenchmarkWorkerInvocation
    | BenchmarkTokenWitness
    | BenchmarkCheckpoint
    | BenchmarkAck
    | BenchmarkSession
    | BenchmarkInvocationTimings
    | BenchmarkTimingEvidence
    | BenchmarkResourceEvidence
    | BenchmarkWorkerResult
    | BenchmarkLaunchReceipt
    | BenchmarkVectorEvidence
    | BenchmarkNearTieReference
    | BenchmarkNumericalEvidence
    | BenchmarkOwnerGateEvidence
    | BenchmarkOwnerResult,
    Field(discriminator="schema_version"),
]


def parse_embedding_device_benchmark(document: dict[str, Any]) -> EmbeddingDeviceBenchmarkMessage:
    """Schema plus frozen semantic closure, never storage/authority or live acceptance."""
    _integer_json(document)
    if len(canonical_json_bytes(document)) > MAX_BENCHMARK_STAGED_BYTES:
        raise ValueError("benchmark JSON exceeds the external byte bound")
    validate_contract(EMBEDDING_DEVICE_BENCHMARK_SCHEMA, document)
    return TypeAdapter(EmbeddingDeviceBenchmarkMessage).validate_python(document)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("benchmark JSON repeats an object field")
        result[key] = value
    return result


def _json_integer(value: str) -> int:
    if len(value) > 20:
        raise ValueError("benchmark JSON integer exceeds its lexical bound")
    return int(value)


def _forbidden_json_number(value: str) -> object:
    raise ValueError("benchmark JSON cannot contain float or non-finite numeric values")


def parse_embedding_device_benchmark_bytes(
    raw: bytes, *, maximum_bytes: int = MAX_BENCHMARK_ENVELOPE_BYTES
) -> EmbeddingDeviceBenchmarkMessage:
    """Trusted caller selects the known member budget; wire data cannot choose it."""
    if type(maximum_bytes) is not int or maximum_bytes not in (
        MAX_BENCHMARK_ENVELOPE_BYTES,
        MAX_BENCHMARK_OUTPUT_BYTES,
        MAX_BENCHMARK_STAGED_BYTES,
    ):
        raise ValueError("benchmark parser requires a declared fixed caller byte bound")
    if len(raw) > maximum_bytes:
        raise ValueError("benchmark raw JSON exceeds its external byte bound")
    depth, quoted, escaped = 0, False, False
    for character in raw:
        if quoted:
            if escaped:
                escaped = False
            elif character == 92:
                escaped = True
            elif character == 34:
                quoted = False
        elif character == 34:
            quoted = True
        elif character in (91, 123):
            depth += 1
            if depth > 32:
                raise ValueError("benchmark JSON nesting exceeds its pre-allocation bound")
        elif character in (93, 125):
            depth -= 1
    if quoted or depth:
        raise ValueError("benchmark JSON framing is incomplete")
    document: object = json.loads(
        raw,
        object_pairs_hook=_unique_json_object,
        parse_int=_json_integer,
        parse_float=_forbidden_json_number,
        parse_constant=_forbidden_json_number,
    )
    if not isinstance(document, dict):
        raise ValueError("benchmark JSON must be one object")
    return parse_embedding_device_benchmark(document)


def embedding_device_benchmark_bytes(value: EmbeddingDeviceBenchmarkMessage) -> bytes:
    _integer_json(value)
    checked = parse_embedding_device_benchmark(value.model_dump(mode="json"))
    return canonical_json_bytes(checked.model_dump(mode="json"))
