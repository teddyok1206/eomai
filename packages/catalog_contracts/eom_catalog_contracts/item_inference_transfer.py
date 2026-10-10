"""Additive, grounded inference-transfer observations; never a permission or proof of quality."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import AfterValidator, Field, model_validator

from eom_catalog_contracts.knowledge import (
    AnchorId,
    ApprovedItemKnowledgeSourceV2,
    KnowledgeAnalysisSolutionReport,
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
    NodeId,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime


def _safe_transfer_text(value: str) -> str:
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError("inference-transfer text contains a control character")
    return value


TransferText = Annotated[str, AfterValidator(_safe_transfer_text)]
ClaimId = Annotated[str, Field(pattern=r"^transferclaim_[a-z0-9][a-z0-9_-]{0,63}$")]
StepId = Annotated[str, Field(pattern=r"^solutionstep_[a-z0-9][a-z0-9_-]{0,47}$")]


def _canonical_ids(values: tuple[str, ...], label: str) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} must be sorted and unique")


def _require_hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError(f"{field} differs from canonical content")


class TransferFacet(StrEnum):
    GIVEN_CONDITION = "GIVEN_CONDITION"
    INTERMEDIATE_RELATION = "INTERMEDIATE_RELATION"
    DECISIVE_INFERENCE = "DECISIVE_INFERENCE"
    ASKED_JUDGEMENT = "ASKED_JUDGEMENT"
    MISCONCEPTION = "MISCONCEPTION"


class InferenceTransferSourceBasis(FrozenModel):
    """Source identity only: resolution must still authorize the actual operator."""

    source: ApprovedItemKnowledgeSourceV2
    graph_snapshot: KnowledgeGraphSnapshotPointer
    solution_evidence: KnowledgeSolutionEvidencePointer

    @model_validator(mode="after")
    def pinned_graph_hash(self) -> InferenceTransferSourceBasis:
        if self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256:
            raise ValueError("Graph manifest pointer and expected hash differ")
        return self


class InferenceTransferClaim(FrozenModel):
    claim_id: ClaimId
    facet: TransferFacet
    text: TransferText = Field(min_length=1, max_length=4000)
    reasoning_step_ids: tuple[StepId, ...] = Field(min_length=1, max_length=32)
    node_ids: tuple[NodeId, ...] = Field(min_length=1, max_length=32)
    anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)
    inferred: bool

    @model_validator(mode="after")
    def canonical_references(self) -> InferenceTransferClaim:
        for values, label in (
            (self.reasoning_step_ids, "claim solution step IDs"),
            (self.node_ids, "claim node IDs"),
            (self.anchor_ids, "claim anchor IDs"),
        ):
            _canonical_ids(values, label)
        return self


class InferenceTransferExtractionProvenance(FrozenModel):
    method: Literal["DETERMINISTIC_REPORT_PROJECTION", "CODEX_DERIVED"]
    extractor_version: TransferText = Field(min_length=1, max_length=128)
    prompt_sha256: Sha256 | None = None
    model_id: TransferText | None = Field(default=None, min_length=1, max_length=128)
    runtime_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def explicit_extraction_identity(self) -> InferenceTransferExtractionProvenance:
        pins = (self.prompt_sha256, self.model_id, self.runtime_sha256)
        if self.method == "DETERMINISTIC_REPORT_PROJECTION" and any(
            pin is not None for pin in pins
        ):
            raise ValueError("deterministic report projection must not invent model provenance")
        if self.method == "CODEX_DERIVED" and any(pin is None for pin in pins):
            raise ValueError("Codex-derived projection requires prompt, model and runtime pins")
        return self


class InferenceTransferProfile(FrozenModel):
    schema_version: Literal["item-inference-transfer-profile/1.0"] = (
        "item-inference-transfer-profile/1.0"
    )
    profile_id: str = Field(pattern=r"^inferenceprofile_[0-9a-f]{32}$")
    profile_revision_id: str = Field(pattern=r"^inferenceprofilerev_[0-9a-f]{32}$")
    source_basis: InferenceTransferSourceBasis
    claims: tuple[InferenceTransferClaim, ...] = Field(max_length=128)
    limitations: tuple[Annotated[TransferText, Field(min_length=1, max_length=1000)], ...] = Field(
        max_length=32
    )
    extraction: InferenceTransferExtractionProvenance
    created_at: UtcDatetime
    profile_sha256: Sha256

    @model_validator(mode="after")
    def closed_profile(self) -> InferenceTransferProfile:
        ids = tuple(claim.claim_id for claim in self.claims)
        _canonical_ids(ids, "profile claim IDs")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("profile limitations must be unique")
        if (
            not self.claims or any(claim.inferred for claim in self.claims)
        ) and not self.limitations:
            raise ValueError("empty or inferred profiles require an explicit limitation")
        _require_hash(self, "profile_sha256")
        return self


class InferenceTransferProfilePointer(FrozenModel):
    """Exact immutable snapshot reference; not a storage path or authorization grant."""

    profile_id: str = Field(pattern=r"^inferenceprofile_[0-9a-f]{32}$")
    profile_revision_id: str = Field(pattern=r"^inferenceprofilerev_[0-9a-f]{32}$")
    profile_sha256: Sha256
    schema_ref: Literal["eom://schemas/knowledge/item-inference-transfer/1.0"] = (
        "eom://schemas/knowledge/item-inference-transfer/1.0"
    )

    @classmethod
    def from_profile(cls, profile: InferenceTransferProfile) -> InferenceTransferProfilePointer:
        return cls(
            profile_id=profile.profile_id,
            profile_revision_id=profile.profile_revision_id,
            profile_sha256=profile.profile_sha256,
        )


class InferenceTransferRubricPointer(FrozenModel):
    rubric_id: str = Field(pattern=r"^transferrubric_[0-9a-f]{32}$")
    rubric_revision_id: str = Field(pattern=r"^transferrubricrev_[0-9a-f]{32}$")
    rubric_sha256: Sha256


class PairComparisonRequest(FrozenModel):
    schema_version: Literal["item-inference-transfer-pair-request/1.0"] = (
        "item-inference-transfer-pair-request/1.0"
    )
    request_id: str = Field(pattern=r"^transferrequest_[0-9a-f]{32}$")
    left_profile: InferenceTransferProfilePointer
    right_profile: InferenceTransferProfilePointer
    direction: Literal["A_TO_B"] = "A_TO_B"
    rubric: InferenceTransferRubricPointer
    left_claim_ids: tuple[ClaimId, ...] = Field(max_length=128)
    right_claim_ids: tuple[ClaimId, ...] = Field(max_length=128)
    request_sha256: Sha256

    @model_validator(mode="after")
    def bounded_exact_selection(self) -> PairComparisonRequest:
        _canonical_ids(self.left_claim_ids, "left selected claim IDs")
        _canonical_ids(self.right_claim_ids, "right selected claim IDs")
        if self.left_profile == self.right_profile:
            raise ValueError("pair comparison requires two different exact profiles")
        _require_hash(self, "request_sha256")
        return self


class InferenceTransferMapping(FrozenModel):
    mapping_id: str = Field(pattern=r"^transfermapping_[a-z0-9][a-z0-9_-]{0,63}$")
    facet: TransferFacet
    left_claim_ids: tuple[ClaimId, ...] = Field(min_length=1, max_length=16)
    right_claim_ids: tuple[ClaimId, ...] = Field(min_length=1, max_length=16)
    explanation: TransferText = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def canonical_mapping(self) -> InferenceTransferMapping:
        _canonical_ids(self.left_claim_ids, "left mapped claim IDs")
        _canonical_ids(self.right_claim_ids, "right mapped claim IDs")
        return self


class InferenceTransferDifference(FrozenModel):
    left_claim_ids: tuple[ClaimId, ...] = Field(max_length=16)
    right_claim_ids: tuple[ClaimId, ...] = Field(max_length=16)
    explanation: TransferText = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def grounded_difference(self) -> InferenceTransferDifference:
        _canonical_ids(self.left_claim_ids, "left difference claim IDs")
        _canonical_ids(self.right_claim_ids, "right difference claim IDs")
        if not self.left_claim_ids and not self.right_claim_ids:
            raise ValueError("difference or new reasoning requires at least one source claim")
        return self


class PairComparisonResult(FrozenModel):
    schema_version: Literal["item-inference-transfer-pair-result/1.0"] = (
        "item-inference-transfer-pair-result/1.0"
    )
    request_id: str = Field(pattern=r"^transferrequest_[0-9a-f]{32}$")
    request_sha256: Sha256
    left_profile: InferenceTransferProfilePointer
    right_profile: InferenceTransferProfilePointer
    direction: Literal["A_TO_B"] = "A_TO_B"
    rubric: InferenceTransferRubricPointer
    judgement: Literal[
        "INSUFFICIENT", "NO_TRANSFER", "STRUCTURAL_ANALOGY", "NEAR_IDENTICAL_CANDIDATE"
    ]
    mappings: tuple[InferenceTransferMapping, ...] = Field(max_length=64)
    shared_idea: TransferText | None = Field(min_length=1, max_length=2000)
    differences: tuple[InferenceTransferDifference, ...] = Field(max_length=32)
    new_reasoning: tuple[InferenceTransferDifference, ...] = Field(max_length=32)
    limitations: tuple[Annotated[TransferText, Field(min_length=1, max_length=1000)], ...] = Field(
        max_length=32
    )
    assessment_kind: Literal["MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"] = (
        "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def grounded_machine_hypothesis(self) -> PairComparisonResult:
        _canonical_ids(tuple(mapping.mapping_id for mapping in self.mappings), "mapping IDs")
        correspondence_keys = {
            (mapping.facet, mapping.left_claim_ids, mapping.right_claim_ids)
            for mapping in self.mappings
        }
        if len(correspondence_keys) != len(self.mappings):
            raise ValueError("comparison mappings must not duplicate the same correspondence")
        if self.judgement in {"STRUCTURAL_ANALOGY", "NEAR_IDENTICAL_CANDIDATE"}:
            facets = {mapping.facet for mapping in self.mappings}
            if not self.shared_idea or not {
                TransferFacet.GIVEN_CONDITION,
                TransferFacet.DECISIVE_INFERENCE,
            }.issubset(facets):
                raise ValueError(
                    "transfer hypothesis requires grounded condition and decisive mappings"
                )
        if self.judgement == "INSUFFICIENT" and not self.limitations:
            raise ValueError("insufficient comparison requires an explicit limitation")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("comparison limitations must be unique")
        _require_hash(self, "result_sha256")
        return self


class HumanTransferEvaluation(FrozenModel):
    """Recorded reviewer label, not a model-generated educational PASS."""

    schema_version: Literal["item-inference-transfer-human-evaluation/1.0"] = (
        "item-inference-transfer-human-evaluation/1.0"
    )
    evaluation_id: str = Field(pattern=r"^transferevaluation_[0-9a-f]{32}$")
    evaluation_revision_id: str = Field(pattern=r"^transferevaluationrev_[0-9a-f]{32}$")
    left_profile: InferenceTransferProfilePointer
    right_profile: InferenceTransferProfilePointer
    direction: Literal["A_TO_B"] = "A_TO_B"
    rubric: InferenceTransferRubricPointer
    reviewer_id: ActorId
    label: Literal[
        "SURFACE_ONLY",
        "SAME_CONCEPT_DIFFERENT_CRUX",
        "CRUX_TRANSFERS",
        "NEAR_IDENTICAL",
        "UNDETERMINED",
    ]
    where_helped: tuple[Annotated[TransferText, Field(min_length=1, max_length=2000)], ...] = Field(
        max_length=16
    )
    reason: TransferText = Field(min_length=1, max_length=4000)
    evaluated_at: UtcDatetime
    evaluation_sha256: Sha256

    @model_validator(mode="after")
    def recorded_human_evaluation(self) -> HumanTransferEvaluation:
        if self.left_profile == self.right_profile:
            raise ValueError("human transfer evaluation requires two different exact profiles")
        if self.label == "CRUX_TRANSFERS" and not self.where_helped:
            raise ValueError("human transfer label requires where the first problem helped")
        if len(self.where_helped) != len(set(self.where_helped)):
            raise ValueError("human transfer locations must be unique")
        _require_hash(self, "evaluation_sha256")
        return self


class LocalEmbeddingFile(FrozenModel):
    member_path: Literal[
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "sentencepiece.bpe.model",
        "README.md",
        "LICENSE",
        "1_Pooling/config.json",
    ]
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=8 * 1024**3)


class LocalEmbeddingRuntimeVersion(FrozenModel):
    name: Literal["torch", "transformers", "safetensors", "tokenizers"]
    version: str = Field(pattern=r"^[0-9][A-Za-z0-9.+_-]{0,95}$")


class LocalEmbeddingModelSpec(FrozenModel):
    """Pinned offline recipe; owning a manifest does not activate or approve its files."""

    schema_version: Literal["item-local-embedding-model-spec/1.0"] = (
        "item-local-embedding-model-spec/1.0"
    )
    model_id: str = Field(pattern=r"^embeddingmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^embeddingmodelrev_[0-9a-f]{32}$")
    provider_family: Literal["transformers-local-dense/1.0"] = "transformers-local-dense/1.0"
    upstream_repo: Literal[
        "BAAI/bge-m3", "intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"
    ]
    upstream_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    license_id: Literal["MIT"] = "MIT"
    dimension: Literal[384, 768, 1024]
    maximum_tokens: int = Field(ge=2, le=8192)
    pooling: Literal["CLS", "MEAN"]
    normalization: Literal["L2"] = "L2"
    dtype: Literal["float32"] = "float32"
    query_prefix: Literal["", "query: "]
    document_prefix: Literal["", "query: "]
    truncation: Literal["REJECT_OVERFLOW"] = "REJECT_OVERFLOW"
    files: tuple[LocalEmbeddingFile, ...] = Field(min_length=5, max_length=9)
    runtime_versions: tuple[LocalEmbeddingRuntimeVersion, ...] = Field(min_length=4, max_length=4)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def pinned_supported_recipe(self) -> LocalEmbeddingModelSpec:
        file_names = tuple(file.member_path for file in self.files)
        _canonical_ids(file_names, "embedding manifest file names")
        required = {
            "config.json",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
        }
        if not required.issubset(file_names):
            raise ValueError("embedding manifest lacks required safe weights or tokenizer files")
        names = tuple(runtime.name for runtime in self.runtime_versions)
        _canonical_ids(names, "embedding runtime names")
        if set(names) != {"torch", "transformers", "safetensors", "tokenizers"}:
            raise ValueError("embedding manifest requires four exact runtime package versions")
        recipes = {
            "BAAI/bge-m3": (1024, "CLS", "", 8192),
            "intfloat/multilingual-e5-small": (384, "MEAN", "query: ", 512),
            "intfloat/multilingual-e5-base": (768, "MEAN", "query: ", 512),
        }
        dimension, pooling, prefix, ceiling = recipes[self.upstream_repo]
        if (
            self.dimension != dimension
            or self.pooling != pooling
            or self.query_prefix != prefix
            or self.document_prefix != prefix
            or self.maximum_tokens > ceiling
        ):
            raise ValueError("embedding recipe differs from the pinned supported model family")
        _require_hash(self, "manifest_sha256")
        return self


def validate_inference_transfer_profile_references(
    profile: InferenceTransferProfile, report: KnowledgeAnalysisSolutionReport
) -> None:
    """Check local closure after the owner authorizes and hashes the actual report bytes."""

    _require_hash(profile, "profile_sha256")
    if (
        report.base_analysis_result_id
        != profile.source_basis.solution_evidence.base_analysis_result_id
    ):
        raise ValueError("profile and resolved solution report have different accepted bases")
    by_step = {step.step_id: step for step in report.solution_steps}
    nodes_by_step = {step.step_id: set(step.node_ids) for step in report.solution_steps}
    anchors_by_step = {step.step_id: set(step.anchor_ids) for step in report.solution_steps}
    for link in report.concept_assessment_links:
        for step_id in link.reasoning_step_ids:
            nodes_by_step[step_id].add(link.concept_node_id)
            nodes_by_step[step_id].update(link.item_element_node_ids)
            nodes_by_step[step_id].update(link.assessment_pattern_node_ids)
    for choice in report.choice_diagnostics:
        for step_id in choice.reasoning_step_ids:
            nodes_by_step[step_id].update(choice.node_ids)
            anchors_by_step[step_id].update(choice.anchor_ids)
    for claim in profile.claims:
        if not set(claim.reasoning_step_ids).issubset(by_step):
            raise ValueError("profile claim references an unknown report solution step")
        nodes: set[str] = set()
        anchors: set[str] = set()
        for step_id in claim.reasoning_step_ids:
            nodes.update(nodes_by_step[step_id])
            nodes.update(by_step[step_id].item_element_node_ids)
            anchors.update(anchors_by_step[step_id])
        if not set(claim.node_ids).issubset(nodes) or not set(claim.anchor_ids).issubset(anchors):
            raise ValueError("profile claim references outside its selected solution evidence")


def _resolve_selected_pair_claims(
    request: PairComparisonRequest,
    left: InferenceTransferProfile,
    right: InferenceTransferProfile,
) -> tuple[dict[str, InferenceTransferClaim], dict[str, InferenceTransferClaim]]:
    _require_hash(request, "request_sha256")
    _require_hash(left, "profile_sha256")
    _require_hash(right, "profile_sha256")

    if request.left_profile != InferenceTransferProfilePointer.from_profile(
        left
    ) or request.right_profile != InferenceTransferProfilePointer.from_profile(right):
        raise ValueError("comparison request and resolved exact profiles differ")
    left_claims = {claim.claim_id: claim for claim in left.claims}
    right_claims = {claim.claim_id: claim for claim in right.claims}
    left_selected = set(request.left_claim_ids)
    right_selected = set(request.right_claim_ids)
    if not left_selected.issubset(left_claims) or not right_selected.issubset(right_claims):
        raise ValueError("pair selection references an unknown profile claim")
    return left_claims, right_claims


def validate_pair_comparison_request_references(
    request: PairComparisonRequest,
    left: InferenceTransferProfile,
    right: InferenceTransferProfile,
) -> None:
    """Resolve authorized exact profiles and selected claims before constructing worker input."""

    _resolve_selected_pair_claims(request, left, right)


def validate_pair_comparison_references(
    request: PairComparisonRequest,
    result: PairComparisonResult,
    left: InferenceTransferProfile,
    right: InferenceTransferProfile,
) -> None:
    """Resolve one pair in O(claims + referenced IDs), never interpreting similarity as approval."""

    left_claims, right_claims = _resolve_selected_pair_claims(request, left, right)
    _require_hash(result, "result_sha256")
    if (
        result.request_id != request.request_id
        or result.request_sha256 != request.request_sha256
        or result.left_profile != request.left_profile
        or result.right_profile != request.right_profile
        or result.rubric != request.rubric
        or result.direction != request.direction
    ):
        raise ValueError("comparison request, result and resolved exact profiles differ")
    left_selected = set(request.left_claim_ids)
    right_selected = set(request.right_claim_ids)
    for mapping in result.mappings:
        if (
            not set(mapping.left_claim_ids).issubset(left_selected)
            or not set(mapping.right_claim_ids).issubset(right_selected)
            or any(
                left_claims[claim_id].facet != mapping.facet for claim_id in mapping.left_claim_ids
            )
            or any(
                right_claims[claim_id].facet != mapping.facet
                for claim_id in mapping.right_claim_ids
            )
        ):
            raise ValueError("pair mapping has an unresolved claim or mismatched transfer facet")
    for difference in (*result.differences, *result.new_reasoning):
        if not set(difference.left_claim_ids).issubset(left_selected) or not set(
            difference.right_claim_ids
        ).issubset(right_selected):
            raise ValueError("pair difference references an unselected profile claim")
