"""Exact public-report lineage plus a derived encoding input, never authority."""

from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_text import PublicSolutionText
from eom_catalog_contracts.validation import validate_contract

PUBLIC_SOLUTION_EMBEDDING_SCHEMA = "public-solution-embedding-entry-v1"
PUBLIC_SOLUTION_EMBEDDING_SCHEMA_REF: Literal[
    "eom://schemas/knowledge/public-solution-embedding-entry/1.0"
] = "eom://schemas/knowledge/public-solution-embedding-entry/1.0"
PUBLIC_SOLUTION_PROJECTION_VERSION = "public-solution-text/1.0"


class PublicSolutionEmbeddingRecipe(FrozenModel):
    """Explicit successor; old EXACT_PROFILE_CLAIMS recipe bytes stay unchanged."""

    schema_version: Literal["inference-transfer-view-recipe/2.0"] = (
        "inference-transfer-view-recipe/2.0"
    )
    content: Literal["CANONICAL_ITEM_TEXT_NO_SOLUTION"] = "CANONICAL_ITEM_TEXT_NO_SOLUTION"
    facets: Literal["FORMAT_NEUTRAL_PUBLIC_SOLUTION"] = "FORMAT_NEUTRAL_PUBLIC_SOLUTION"
    metadata: Literal["SORTED_ACCEPTED_FIELDS"] = "SORTED_ACCEPTED_FIELDS"
    overflow: Literal["REJECT_OVERFLOW"] = "REJECT_OVERFLOW"
    maximum_text_bytes: Literal[262144] = 262144
    ranking: Literal["EXACT_FLOAT64_COSINE_REF_TIES"] = "EXACT_FLOAT64_COSINE_REF_TIES"
    recipe_sha256: Sha256

    @model_validator(mode="after")
    def exact_recipe(self) -> Self:
        if self.recipe_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"recipe_sha256"})
        ):
            raise ValueError("PUBLIC_SOLUTION_RECIPE_HASH_MISMATCH")
        return self


class AcceptedPublicSolutionEvidence(FrozenModel):
    kind: Literal["ACCEPTED_SOLUTION_ANALYSIS"] = "ACCEPTED_SOLUTION_ANALYSIS"
    solution: KnowledgeSolutionEvidencePointer


class CreativePublicSolutionEvidence(FrozenModel):
    kind: Literal["REGISTERED_CREATIVE_SOURCE_REPORT"] = "REGISTERED_CREATIVE_SOURCE_REPORT"
    lineage: ArtifactMemberPointer
    lineage_sha256: Sha256
    role_result: ArtifactMemberPointer
    result_id: str = Field(pattern=r"^extlearnresult_[0-9a-f]{32}$")
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_members(self) -> Self:
        if (
            self.lineage.member_path != "lineage.json"
            or self.lineage.schema_ref != "eom://schemas/external-item/creative-source-lineage/1.0"
            or self.lineage.media_type != "application/json"
            or self.role_result.member_path != "result.json"
            or self.role_result.schema_ref
            not in {"external-item-learning-result@1.0", "external-item-learning-result@2.0"}
            or self.role_result.media_type != "application/json"
        ):
            raise ValueError("PUBLIC_SOLUTION_CREATIVE_MEMBERS_INVALID")
        return self


type PublicSolutionEmbeddingEvidence = Annotated[
    AcceptedPublicSolutionEvidence | CreativePublicSolutionEvidence,
    Field(discriminator="kind"),
]


class PublicSolutionEmbeddingEntry(FrozenModel):
    """Bounded source materialization. A matching text hash never merges identities."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    schema_version: Literal["public-solution-embedding-entry/1.0"] = (
        "public-solution-embedding-entry/1.0"
    )
    source: PopulationSource
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    recipe: PublicSolutionEmbeddingRecipe
    evidence: PublicSolutionEmbeddingEvidence
    public_solution: PublicSolutionText
    entry_sha256: Sha256

    @model_validator(mode="after")
    def exact_entry(self) -> Self:
        document = self.model_dump(mode="json")
        validate_contract(PUBLIC_SOLUTION_EMBEDDING_SCHEMA, document)
        # Frozen instances may be forged with model_copy/model_construct. Close
        # nested semantic hashes as well as their JSON shapes before projection.
        PublicSolutionText.model_validate(document["public_solution"])
        PublicSolutionEmbeddingRecipe.model_validate(document["recipe"])
        if type(self.source) not in (
            ApprovedItemKnowledgeSourceV2,
            ApprovedPastExamItemKnowledgeSourceV3,
        ):
            raise ValueError("PUBLIC_SOLUTION_SOURCE_FAMILY_INVALID")
        source = type(self.source).model_validate(document["source"])
        graph = KnowledgeGraphSnapshotPointer.model_validate(document["graph_snapshot"])
        if graph.manifest_sha256 != graph.manifest_artifact.sha256:
            raise ValueError("PUBLIC_SOLUTION_GRAPH_HASH_MISMATCH")
        if isinstance(self.evidence, AcceptedPublicSolutionEvidence):
            solution = KnowledgeSolutionEvidencePointer.model_validate(
                document["evidence"]["solution"]
            )
            if solution.base_analysis_run_id != self.base_analysis_run_id:
                raise ValueError("PUBLIC_SOLUTION_BASE_ANALYSIS_MISMATCH")
        else:
            CreativePublicSolutionEvidence.model_validate(document["evidence"])
            if source.source_class != "APPROVED_ITEM":
                raise ValueError("PUBLIC_SOLUTION_CREATIVE_SOURCE_CLASS_INVALID")
        if self.entry_sha256 != content_sha256(
            {key: value for key, value in document.items() if key != "entry_sha256"}
        ):
            raise ValueError("PUBLIC_SOLUTION_ENTRY_HASH_MISMATCH")
        return self
