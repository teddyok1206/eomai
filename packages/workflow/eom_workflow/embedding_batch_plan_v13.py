"""Public-report INDEX selection; the numerical and physical allocation wires stay unchanged."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_embedding import (
    AcceptedPublicSolutionEvidence,
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingEvidence,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionProfilePointer
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Resource

from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_SCHEMA_REF,
    MAX_BATCH_PLAN_BYTES,
    embedding_batch_plan_schema,
)
from eom_workflow.embedding_batch_plan_v11 import MAX_BULK_BATCH_SELECTION_BYTES
from eom_workflow.embedding_batch_plan_values import (
    EmbeddingBatchPlanRequestValues,
    EmbeddingBatchPlanValue,
    require_embedding_batch_plan_value,
    validate_embedding_batch_value_hash,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_PLAN_V13_PROTOCOL = "embedding-batch-plan/1.3"
BATCH_PLAN_V13_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.3"
BATCH_PLAN_V13_SCHEMA_SHA256 = (
    "sha256:472609d692c7a373d05ddac44ab0d3fc66f10d460b4566ab699182df476a3084"
)
BATCH_SELECTION_V13_SCHEMA_REF = BATCH_PLAN_V13_SCHEMA_REF + "#/$defs/selection"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.3.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BULK_BATCH_SELECTION_BYTES + 1)
    if sha256_bytes(raw) != BATCH_PLAN_V13_SCHEMA_SHA256:
        raise ValueError("EMBEDDING_BATCH_PLAN_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resource(
        BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class PublicSolutionBatchAnchor(EmbeddingBatchPlanValue):
    """No report/text duplication and no authority; admission must resolve these exact pointers."""

    basis: Literal["VERIFIABLE_PUBLIC_SOLUTION"] = "VERIFIABLE_PUBLIC_SOLUTION"
    source: PopulationSource
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: PublicSolutionProfilePointer
    evidence: PublicSolutionEmbeddingEvidence

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        logical = content_sha256(
            {"item_id": self.source.item_id, "projection_version": "public-solution-text/1.0"}
        )
        require_embedding_batch_plan_value(
            self.profile.profile_id == "inferenceprofile_" + logical[7:39]
            and self.profile.profile_revision_id
            == "inferenceprofilerev_" + self.profile.profile_sha256[7:39]
        )
        if isinstance(self.evidence, AcceptedPublicSolutionEvidence):
            require_embedding_batch_plan_value(
                self.evidence.solution.base_analysis_run_id == self.base_analysis_run_id
            )
        else:
            require_embedding_batch_plan_value(self.source.source_class == "APPROVED_ITEM")
        return self

    @classmethod
    def from_entry(cls, entry: PublicSolutionEmbeddingEntry) -> Self:
        entry = PublicSolutionEmbeddingEntry.model_validate(entry.model_dump(mode="json"))
        return cls(
            source=entry.source,
            base_analysis_run_id=entry.base_analysis_run_id,
            profile=PublicSolutionProfilePointer.from_entry(entry),
            evidence=entry.evidence,
        )


class _PublicPlanMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["embedding-batch-plan/1.3"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            maximum = (
                MAX_BULK_BATCH_SELECTION_BYTES
                if document.get("message_type") == "SELECTION"
                else MAX_BATCH_PLAN_BYTES
            )
            if len(canonical_json_bytes(document)) > maximum:
                raise ValueError("oversized metadata")
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID") from None


class EmbeddingBatchSelectionV13(_PublicPlanMessage):
    message_type: Literal["SELECTION"]
    purpose: Literal["INDEX"]
    scope: EmbeddingWorkBatchScope
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    anchors: tuple[PublicSolutionBatchAnchor, ...] = Field(min_length=1, max_length=1024)
    recipe: PublicSolutionEmbeddingRecipe
    views: tuple[Literal["CONCRETE_FACETS"], ...] = Field(min_length=1, max_length=1)
    query: None
    selection_sha256: Sha256

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        revisions = {anchor.source.item_revision_id for anchor in self.anchors}
        require_embedding_batch_plan_value(
            len(revisions) == len(self.anchors)
            and self.graph_snapshot.manifest_artifact.sha256 == self.graph_snapshot.manifest_sha256
        )
        validate_embedding_batch_value_hash(self, "selection_sha256")
        return self

    @property
    def child_selection_sha256s(self) -> tuple[str, ...]:
        return (
            content_sha256({"selection_sha256": self.selection_sha256, "child": self.views[0]}),
        )


class EmbeddingBatchPlanRequestV13(EmbeddingBatchPlanRequestValues, _PublicPlanMessage):
    selection_schema_ref: ClassVar[str] = BATCH_SELECTION_V13_SCHEMA_REF
    purpose: Literal["INDEX"]
    child_selection_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=1)
