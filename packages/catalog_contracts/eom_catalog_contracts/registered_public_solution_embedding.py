"""Registered Item report provenance; exactly the same numeric text as other sources.

These values confer no source permission or Graph admission. The Catalog read
owner must resolve the actual accepted V11 chain before constructing an entry.
"""

from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_embedding import (
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_text import PublicSolutionText
from eom_catalog_contracts.validation import validate_contract

REGISTERED_PUBLIC_SOLUTION_SCHEMA = "public-solution-embedding-entry-v2"
REGISTERED_PUBLIC_SOLUTION_SCHEMA_REF = (
    "eom://schemas/knowledge/public-solution-embedding-entry/2.0"
)


class RegisteredItemSolutionEvidencePointer(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    schema_version: Literal["registered-item-solution-evidence-pointer/1.0"] = (
        "registered-item-solution-evidence-pointer/1.0"
    )
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    base_analysis_result_id: str = Field(pattern=r"^knowledgeanalysisresult_[0-9a-f]{32}$")
    solution_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    solution_analysis_result_id: str = Field(pattern=r"^knowledgeanalysisresult_[0-9a-f]{32}$")
    solution_result_sha256: Sha256
    accepted_result_artifact: KnowledgeArtifactMemberPointer
    proposal_receipt: KnowledgeArtifactMemberPointer
    solution_report: KnowledgeArtifactMemberPointer
    proposal_content_set_sha256: Sha256
    pointer_sha256: Sha256

    @model_validator(mode="after")
    def exact_registered_members(self) -> Self:
        expected = (
            (
                self.accepted_result_artifact,
                "evidence/accepted-result.json",
                "accepted-result.json",
                "knowledge-analysis-result/11.0",
            ),
            (
                self.proposal_receipt,
                "normalized/proposal-receipt.json",
                "proposal-receipt.json",
                "knowledge-analysis-proposal-receipt/10.0",
            ),
            (
                self.solution_report,
                "normalized/solution-report.json",
                "solution-report.json",
                "knowledge-analysis-solution-report/1.0",
            ),
        )
        if (
            self.base_analysis_run_id == self.solution_analysis_run_id
            or self.base_analysis_result_id == self.solution_analysis_result_id
            or any(
                pointer.member_path != path
                or pointer.logical_name != logical
                or pointer.schema_ref != "eom://schemas/knowledge/" + schema
                or pointer.media_type != "application/json"
                for pointer, path, logical, schema in expected
            )
            or (self.proposal_receipt.artifact_id, self.proposal_receipt.artifact_revision_id)
            != (self.solution_report.artifact_id, self.solution_report.artifact_revision_id)
            or (
                self.accepted_result_artifact.artifact_id,
                self.accepted_result_artifact.artifact_revision_id,
            )
            == (self.solution_report.artifact_id, self.solution_report.artifact_revision_id)
            or self.pointer_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"pointer_sha256"}))
        ):
            raise ValueError("REGISTERED_SOLUTION_EVIDENCE_POINTER_MISMATCH")
        return self


class RegisteredPublicSolutionEvidence(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    kind: Literal["ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"] = "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
    solution: RegisteredItemSolutionEvidencePointer


class RegisteredPublicSolutionEmbeddingEntry(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    schema_version: Literal["public-solution-embedding-entry/2.0"] = (
        "public-solution-embedding-entry/2.0"
    )
    source: ApprovedItemKnowledgeSourceV2
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    recipe: PublicSolutionEmbeddingRecipe
    evidence: RegisteredPublicSolutionEvidence
    public_solution: PublicSolutionText
    entry_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        if not isinstance(document, dict) or len(canonical_json_bytes(document)) > 2 * 1024**2:
            raise ValueError("REGISTERED_PUBLIC_SOLUTION_METADATA_INVALID")
        try:
            validate_contract(REGISTERED_PUBLIC_SOLUTION_SCHEMA, document)
        except JsonSchemaValidationError:
            raise ValueError("REGISTERED_PUBLIC_SOLUTION_SCHEMA_INVALID") from None
        return document

    @model_validator(mode="after")
    def exact_entry(self) -> Self:
        document = self.model_dump(mode="json")
        ApprovedItemKnowledgeSourceV2.model_validate(document["source"])
        KnowledgeGraphSnapshotPointer.model_validate(document["graph_snapshot"])
        PublicSolutionText.model_validate(document["public_solution"])
        PublicSolutionEmbeddingRecipe.model_validate(document["recipe"])
        evidence = RegisteredPublicSolutionEvidence.model_validate(document["evidence"])
        if (
            self.source.source_class != "APPROVED_ITEM"
            or self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.base_analysis_run_id != evidence.solution.base_analysis_run_id
            or self.entry_sha256
            != content_sha256(
                {key: value for key, value in document.items() if key != "entry_sha256"}
            )
        ):
            raise ValueError("REGISTERED_PUBLIC_SOLUTION_ENTRY_MISMATCH")
        return self


type PublicSolutionEncodingEntry = (
    # Envelopes differ only to preserve their real accepted source contracts.
    PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
)


def parse_public_solution_encoding_entry(value: object) -> PublicSolutionEncodingEntry:
    """Closed format dispatch; this is not INDEX/QUERY runtime admission."""
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        match document.get("schema_version"):
            case "public-solution-embedding-entry/1.0":
                return PublicSolutionEmbeddingEntry.model_validate(document)
            case "public-solution-embedding-entry/2.0":
                return RegisteredPublicSolutionEmbeddingEntry.model_validate(document)
    raise ValueError("PUBLIC_SOLUTION_ENTRY_FAMILY_UNSUPPORTED")
