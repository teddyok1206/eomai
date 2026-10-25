"""QUERY-only exact device-index metadata; native/planning event frames remain 1.0."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_model_recipe import same_embedding_payload_recipe
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.similarity_context import (
    ApprovedReferenceItemAnchor,
    SimilarityViewSelection,
)
from eom_catalog_contracts.similarity_context_v2 import SimilarityViewSelectionV2
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Resource

from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_SCHEMA_REF,
    MAX_BATCH_PLAN_BYTES,
    embedding_batch_plan_schema,
)
from eom_workflow.embedding_batch_plan_values import (
    EmbeddingBatchPlanRequestValues,
    EmbeddingBatchPlanValue,
    EmbeddingBatchSelectionValues,
)
from eom_workflow.embedding_batch_plan_values import (
    require_embedding_batch_plan_value as require,
)
from eom_workflow.embedding_device_routing import (
    EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
    EmbeddingDeviceRoutingPolicy,
    embedding_device_routing_schema,
)
from eom_workflow.native_embedding_backend_selection import (
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
    native_embedding_backend_selection_schema,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_PLAN_V12_PROTOCOL = "embedding-batch-plan/1.2"
BATCH_PLAN_V12_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.2"
BATCH_PLAN_V12_SCHEMA_SHA256 = (
    "sha256:ede5e13a9046b6ce4d3c2f3bc9bd4799e943ed5f77f052666bfa15673cab6580"
)
BATCH_SELECTION_V12_SCHEMA_REF = BATCH_PLAN_V12_SCHEMA_REF + "#/$defs/selection"
type PinnedQueryView = SimilarityViewSelection | SimilarityViewSelectionV2


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.2.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_PLAN_BYTES + 1)
    if (
        not 0 < len(raw) <= MAX_BATCH_PLAN_BYTES
        or sha256_bytes(raw) != BATCH_PLAN_V12_SCHEMA_SHA256
    ):
        raise ValueError("EMBEDDING_BATCH_PLAN_SCHEMA_INVALID")
    return raw


def embedding_batch_plan_v12_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(_schema_raw())
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = embedding_batch_plan_v12_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resources(
        (
            (BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())),
            (
                EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
                Resource.from_contents(embedding_device_routing_schema()),
            ),
            (
                NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
                Resource.from_contents(native_embedding_backend_selection_schema()),
            ),
        )
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class _QueryPlanMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["embedding-batch-plan/1.2"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            require(len(canonical_json_bytes(document)) <= MAX_BATCH_PLAN_BYTES)
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID") from None


class EmbeddingBatchQueryIndexPair(EmbeddingBatchPlanValue):
    """Only immutable pins; official Catalog resolution supplies current authority."""

    cpu: PinnedQueryView
    cuda: PinnedQueryView

    @model_validator(mode="after")
    def exact_device_pair(self) -> Self:
        cpu, cuda = self.cpu.index, self.cuda.index
        require(cpu is not None and cuda is not None)
        assert cpu is not None and cuda is not None
        require(
            type(self.cpu) is type(self.cuda)
            and self.cpu.view == self.cuda.view
            and self.cpu.recipe == self.cuda.recipe
            and cpu.storage_partition == cuda.storage_partition
            and cpu.spaces.document.runtime.device == "CPU"
            and cuda.spaces.document.runtime.device == "CUDA"
            and cpu.spaces.document.runtime.execution_runtime_sha256
            != cuda.spaces.document.runtime.execution_runtime_sha256
            and cpu.spaces.document.space_sha256 != cuda.spaces.document.space_sha256
            and same_embedding_payload_recipe(
                cpu.spaces.document.model_spec, cuda.spaces.document.model_spec
            )
            and cpu.index_id != cuda.index_id
            and cpu.index_revision_id != cuda.index_revision_id
            and (cpu.index_manifest.artifact_id, cpu.index_manifest.artifact_revision_id)
            != (cuda.index_manifest.artifact_id, cuda.index_manifest.artifact_revision_id)
        )
        return self

    def select(self, device: Literal["CPU", "CUDA"]) -> PinnedQueryView:
        require(device in {"CPU", "CUDA"})
        return self.cpu if device == "CPU" else self.cuda


class EmbeddingBatchSelectionV12(EmbeddingBatchSelectionValues, _QueryPlanMessage):
    anchors: tuple[ApprovedReferenceItemAnchor, ...] = Field(min_length=1, max_length=32)
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    index_pairs: tuple[EmbeddingBatchQueryIndexPair, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def exact_pins(self) -> Self:
        require(self.source_classes == tuple(sorted(set(self.source_classes))))
        require(all(a.source.source_class in self.source_classes for a in self.anchors))
        require(tuple(pair.cpu.view for pair in self.index_pairs) == self.views)
        devices: tuple[Literal["CPU", "CUDA"], ...] = ("CPU", "CUDA")
        for device in devices:
            rows = self.selected_views(device)
            first = rows[0].index
            assert first is not None
            require(all(type(row) is type(rows[0]) for row in rows))
            require(
                all(
                    row.recipe == self.recipe
                    and row.index is not None
                    and row.index.storage_partition == self.scope.storage_partition
                    and row.index.spaces == first.spaces
                    for row in rows
                )
            )
            require(len({row.index.index_id for row in rows if row.index}) == len(rows))
        return self

    def selected_views(self, device: Literal["CPU", "CUDA"]) -> tuple[PinnedQueryView, ...]:
        return tuple(pair.select(device) for pair in self.index_pairs)


class EmbeddingBatchPlanRequestV12(EmbeddingBatchPlanRequestValues, _QueryPlanMessage):
    selection_schema_ref: ClassVar[str] = BATCH_SELECTION_V12_SCHEMA_REF


def validate_embedding_batch_query_index_controls(
    selection: EmbeddingBatchSelectionV12, policy: EmbeddingDeviceRoutingPolicy
) -> None:
    devices: tuple[Literal["CPU", "CUDA"], ...] = ("CPU", "CUDA")
    for device, profile in zip(devices, (policy.cpu.profile, policy.cuda.profile), strict=True):
        require(
            all(
                row.index is not None and row.index.spaces.document == profile.space
                for row in selection.selected_views(device)
            )
        )
