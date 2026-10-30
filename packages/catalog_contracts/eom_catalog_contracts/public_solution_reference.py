"""One source/report pointer invariant shared by public INDEX and similarity consumers."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.public_solution_embedding import (
    AcceptedPublicSolutionEvidence,
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingEvidence,
)
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionProfilePointer


class PublicSolutionSourceReference(FrozenModel):
    """Value closure only; actual source/Graph/Artifact authorization belongs to Catalog."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    basis: Literal["VERIFIABLE_PUBLIC_SOLUTION"] = "VERIFIABLE_PUBLIC_SOLUTION"
    source: PopulationSource
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: PublicSolutionProfilePointer
    evidence: PublicSolutionEmbeddingEvidence

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        logical = content_sha256(
            {"item_id": self.source.item_id, "projection_version": "public-solution-text/1.0"}
        )
        if (
            self.profile.profile_id != "inferenceprofile_" + logical[7:39]
            or self.profile.profile_revision_id
            != "inferenceprofilerev_" + self.profile.profile_sha256[7:39]
            or (
                isinstance(self.evidence, AcceptedPublicSolutionEvidence)
                and self.evidence.solution.base_analysis_run_id != self.base_analysis_run_id
            )
            or (
                not isinstance(self.evidence, AcceptedPublicSolutionEvidence)
                and self.source.source_class != "APPROVED_ITEM"
            )
        ):
            raise ValueError("PUBLIC_SOLUTION_REFERENCE_INVALID")
        return self

    @classmethod
    def from_entry(cls, entry: PublicSolutionEmbeddingEntry) -> Self:
        entry = PublicSolutionEmbeddingEntry.model_validate(raw_similarity_contract_value(entry))
        return cls(
            source=entry.source,
            base_analysis_run_id=entry.base_analysis_run_id,
            profile=PublicSolutionProfilePointer.from_entry(entry),
            evidence=entry.evidence,
        )
