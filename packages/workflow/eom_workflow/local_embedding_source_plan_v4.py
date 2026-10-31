"""Mixed original and registered full reports, one immutable numeric demand recipe."""

from typing import Annotated, Literal, Self

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_embedding import (
    AcceptedPublicSolutionEvidence,
    CreativePublicSolutionEvidence,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
    PublicSolutionProfilePointer,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    PublicSolutionEncodingEntry,
    RegisteredPublicSolutionEvidence,
    parse_public_solution_encoding_entry,
)
from eom_catalog_contracts.registered_public_solution_index import (
    PublicSolutionEmbeddingIndexV4,
    RegisteredPublicSolutionProfilePointer,
)
from pydantic import ConfigDict, Field, model_validator

from eom_workflow.local_embedding_source_plan import SourceRevisionId
from eom_workflow.local_embedding_source_plan_v3 import (
    PublicSolutionUnavailableView,
    validate_public_solution_plan_entry_values,
    validate_public_solution_plan_values,
    validate_public_solution_selected_index_values,
)
from eom_workflow.schemas import validate_local_embedding_admission_message

LOCAL_EMBEDDING_SOURCE_PLAN_V4_SCHEMA_REF = "eom://schemas/workflow/local-embedding-source-plan/4.0"
type PublicSolutionProfileV4 = Annotated[
    PublicSolutionProfilePointer | RegisteredPublicSolutionProfilePointer,
    Field(discriminator="schema_ref"),
]
type PublicSolutionEvidenceV4 = Annotated[
    AcceptedPublicSolutionEvidence
    | CreativePublicSolutionEvidence
    | RegisteredPublicSolutionEvidence,
    Field(discriminator="kind"),
]


class PublicSolutionEncodingDemandV4(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    source_revision_id: SourceRevisionId
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: PublicSolutionProfileV4
    evidence: PublicSolutionEvidenceV4
    encoding: EmbeddingEncodingIdentity

    @model_validator(mode="after")
    def exact_family(self) -> Self:
        registered = isinstance(self.evidence, RegisteredPublicSolutionEvidence)
        if registered != isinstance(self.profile, RegisteredPublicSolutionProfilePointer):
            raise ValueError("PUBLIC_SOLUTION_DEMAND_PROFILE_FAMILY_MISMATCH")
        return self


class LocalEmbeddingSourcePlanV4(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    schema_version: Literal["local-embedding-source-plan/4.0"] = "local-embedding-source-plan/4.0"
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    namespace: PublicSolutionIndexNamespace
    space: EmbeddingSpace
    recipe: PublicSolutionEmbeddingRecipe
    sources: tuple[PopulationSource, ...] = Field(
        min_length=1, max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    demands: tuple[PublicSolutionEncodingDemandV4, ...] = Field(
        max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    missing_solution_report_revision_ids: tuple[SourceRevisionId, ...] = Field(
        max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    unavailable_views: tuple[PublicSolutionUnavailableView, ...] = Field(
        max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    source_set_sha256: Sha256
    encoding_set_sha256: Sha256
    plan_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_public_solution_contract_value(value)
        validate_local_embedding_admission_message("registered-public-source-plan", document)
        return document

    @model_validator(mode="after")
    def exact_plan(self) -> Self:
        validate_public_solution_plan_values(self)
        return self


def parse_local_embedding_source_plan_v4(value: object) -> LocalEmbeddingSourcePlanV4:
    return LocalEmbeddingSourcePlanV4.model_validate(value)


def validate_local_embedding_plan_entries_v4(
    plan: LocalEmbeddingSourcePlanV4, entries: tuple[PublicSolutionEncodingEntry, ...]
) -> None:
    plan = parse_local_embedding_source_plan_v4(plan)
    checked = tuple(parse_public_solution_encoding_entry(entry) for entry in entries)
    validate_public_solution_plan_entry_values(plan, checked)


def validate_local_embedding_selected_index_coverage_v4(
    plan: LocalEmbeddingSourcePlanV4, index: PublicSolutionEmbeddingIndexV4
) -> None:
    plan = parse_local_embedding_source_plan_v4(plan)
    index = PublicSolutionEmbeddingIndexV4.model_validate(index)
    validate_public_solution_selected_index_values(plan, index)
