"""Bounded mixed materialization with original evidence-family identities intact."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_catalog_contracts.mixed_embedding_index import RegisteredReviewEmbeddingEntry
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_contracts.similarity_context_v2 import (
    AcceptedSimilarityCandidateV2,
    RegisteredReviewSimilarityCandidateV2,
    SimilarityContextV2,
    parse_similarity_context_v2,
    validate_deliverable_similarity_context_v2,
)
from eom_catalog_contracts.similarity_materials import (
    MAX_SIMILARITY_MATERIAL_CANDIDATES,
    MAX_SIMILARITY_MATERIALS_BYTES,
)

type MixedSimilarityEntry = StagedExperimentEntry | RegisteredReviewEmbeddingEntry


class SimilarityReferenceMaterialsV2(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["system-rag-similarity-materials/2.0"] = (
        "system-rag-similarity-materials/2.0"
    )
    request_sha256: Sha256
    context_sha256: Sha256
    anchor_profile: InferenceTransferProfile | None
    entries: tuple[MixedSimilarityEntry, ...] = Field(max_length=MAX_SIMILARITY_MATERIAL_CANDIDATES)
    materials_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-similarity-materials-v2", MAX_SIMILARITY_MATERIALS_BYTES
        )

    @model_validator(mode="after")
    def exact_identity(self) -> SimilarityReferenceMaterialsV2:
        sources = tuple(
            entry.profile.source_basis.source.item_revision_id for entry in self.entries
        )
        if len(set(sources)) != len(sources) or (
            self.anchor_profile is not None
            and self.anchor_profile.source_basis.source.item_revision_id in sources
        ):
            raise ValueError("SIMILARITY_MATERIALS_V2_DUPLICATE")
        if self.materials_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"materials_sha256"})
        ):
            raise ValueError("SIMILARITY_MATERIALS_V2_HASH_MISMATCH")
        return self


def parse_similarity_materials_v2(value: object) -> SimilarityReferenceMaterialsV2:
    return SimilarityReferenceMaterialsV2.model_validate(value)


def validate_similarity_materials_v2(
    materials: SimilarityReferenceMaterialsV2, context: SimilarityContextV2
) -> SimilarityReferenceMaterialsV2:
    checked = parse_similarity_materials_v2(materials)
    context = parse_similarity_context_v2(context)
    validate_deliverable_similarity_context_v2(context, expected_request=context.request)
    if (
        checked.request_sha256 != context.request.request_sha256
        or checked.context_sha256 != context.context_sha256
        or len(checked.entries) != len(context.candidates)
        or (checked.anchor_profile is None) != (context.request.anchor.profile is None)
    ):
        raise ValueError("SIMILARITY_MATERIALS_V2_CONTEXT_MISMATCH")
    if checked.anchor_profile is not None:
        anchor = checked.anchor_profile
        if (
            anchor.source_basis.source != context.request.anchor.source
            or InferenceTransferProfilePointer.from_profile(anchor)
            != context.request.anchor.profile
            or anchor.source_basis.solution_evidence != context.request.anchor.solution_evidence
            or anchor.source_basis.graph_snapshot != context.request.graph_snapshot
        ):
            raise ValueError("SIMILARITY_MATERIALS_V2_ANCHOR_MISMATCH")
    for entry, candidate in zip(checked.entries, context.candidates, strict=True):
        if entry.profile.source_basis.source != candidate.source or (
            entry.profile.source_basis.graph_snapshot != context.request.graph_snapshot
        ):
            raise ValueError("SIMILARITY_MATERIALS_V2_SOURCE_MISMATCH")
        if isinstance(entry, RegisteredReviewEmbeddingEntry):
            valid = isinstance(candidate, RegisteredReviewSimilarityCandidateV2) and (
                RegisteredReviewProfilePointer.from_profile(entry.profile) == candidate.profile
                and entry.profile.source_basis.review_evidence == candidate.review_evidence
            )
        else:
            valid = isinstance(candidate, AcceptedSimilarityCandidateV2) and (
                InferenceTransferProfilePointer.from_profile(entry.profile) == candidate.profile
                and entry.profile.source_basis.solution_evidence == candidate.solution_evidence
            )
        if not valid:
            raise ValueError("SIMILARITY_MATERIALS_V2_EVIDENCE_MISMATCH")
    return checked


def build_similarity_materials_v2(
    context: SimilarityContextV2,
    *,
    anchor_profile: InferenceTransferProfile | None,
    entries: tuple[MixedSimilarityEntry, ...],
) -> SimilarityReferenceMaterialsV2:
    context = parse_similarity_context_v2(context)
    body = {
        "schema_version": "system-rag-similarity-materials/2.0",
        "request_sha256": context.request.request_sha256,
        "context_sha256": context.context_sha256,
        "anchor_profile": raw_similarity_contract_value(anchor_profile),
        "entries": raw_similarity_contract_value(entries),
    }
    value = parse_similarity_materials_v2(body | {"materials_sha256": content_sha256(body)})
    return validate_similarity_materials_v2(value, context)
