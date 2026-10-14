"""Bounded existing Item/report projections; identity closure is never source authority."""

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
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context import (
    ApprovedReferenceItemAnchor,
    SimilarityCandidate,
    SimilarityContext,
    parse_similarity_context,
)
from eom_catalog_contracts.similarity_delivery import validate_deliverable_similarity_context

SIMILARITY_MATERIALS_SCHEMA = "system-rag-similarity-materials"
SIMILARITY_MATERIALS_REF = "eom://schemas/knowledge/system-rag-similarity-materials/1.0"
MAX_SIMILARITY_MATERIAL_CANDIDATES = 8
MAX_SIMILARITY_MATERIALS_BYTES = 4 * 1024 * 1024


class SimilarityReferenceMaterials(FrozenModel):
    """A local temporary value, not a new canonical Item/report or stored authority receipt."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["system-rag-similarity-materials/1.0"] = (
        "system-rag-similarity-materials/1.0"
    )
    request_sha256: Sha256
    context_sha256: Sha256
    anchor_profile: InferenceTransferProfile | None
    entries: tuple[StagedExperimentEntry, ...] = Field(
        max_length=MAX_SIMILARITY_MATERIAL_CANDIDATES
    )
    materials_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, SIMILARITY_MATERIALS_SCHEMA, MAX_SIMILARITY_MATERIALS_BYTES
        )

    @model_validator(mode="after")
    def exact_identity_and_hash(self) -> SimilarityReferenceMaterials:
        sources = tuple(
            entry.profile.source_basis.source.item_revision_id for entry in self.entries
        )
        profiles = tuple(
            InferenceTransferProfilePointer.from_profile(entry.profile) for entry in self.entries
        )
        if len(set(sources)) != len(sources) or len(set(profiles)) != len(profiles):
            raise ValueError("SIMILARITY_MATERIALS_DUPLICATE")
        if self.anchor_profile is not None and (
            self.anchor_profile.source_basis.source.item_revision_id in sources
            or InferenceTransferProfilePointer.from_profile(self.anchor_profile) in profiles
        ):
            raise ValueError("SIMILARITY_MATERIALS_DUPLICATE")
        if self.materials_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"materials_sha256"})
        ):
            raise ValueError("SIMILARITY_MATERIALS_HASH_MISMATCH")
        return self


def parse_similarity_materials(value: object) -> SimilarityReferenceMaterials:
    return SimilarityReferenceMaterials.model_validate(value)


def validate_similarity_materials(
    materials: SimilarityReferenceMaterials, context: SimilarityContext
) -> SimilarityReferenceMaterials:
    """Match the exact ordered references and accepted lineage, without IO or a grant."""
    checked = parse_similarity_materials(materials)
    context = parse_similarity_context(context)
    validate_deliverable_similarity_context(context, expected_request=context.request)
    if (
        checked.request_sha256 != context.request.request_sha256
        or checked.context_sha256 != context.context_sha256
        or len(checked.entries) != len(context.candidates)
        or (checked.anchor_profile is None) != (context.request.anchor.profile is None)
    ):
        raise ValueError("SIMILARITY_MATERIALS_CONTEXT_MISMATCH")
    references: tuple[
        tuple[InferenceTransferProfile, SimilarityCandidate | ApprovedReferenceItemAnchor], ...
    ] = tuple(
        (entry.profile, candidate)
        for entry, candidate in zip(checked.entries, context.candidates, strict=True)
    )
    if checked.anchor_profile is not None:
        references = ((checked.anchor_profile, context.request.anchor), *references)
    for profile, reference in references:
        if (
            profile.source_basis.source != reference.source
            or InferenceTransferProfilePointer.from_profile(profile) != reference.profile
            or profile.source_basis.solution_evidence != reference.solution_evidence
            or profile.source_basis.graph_snapshot != context.request.graph_snapshot
        ):
            raise ValueError("SIMILARITY_MATERIALS_REFERENCE_MISMATCH")
    return checked


def build_similarity_materials(
    context: SimilarityContext,
    *,
    anchor_profile: InferenceTransferProfile | None,
    entries: tuple[StagedExperimentEntry, ...],
) -> SimilarityReferenceMaterials:
    """Construct at an authorized projection boundary; do not repair supplied hashes."""
    context = parse_similarity_context(context)
    raw = {
        "schema_version": "system-rag-similarity-materials/1.0",
        "request_sha256": context.request.request_sha256,
        "context_sha256": context.context_sha256,
        "anchor_profile": raw_similarity_contract_value(anchor_profile),
        "entries": raw_similarity_contract_value(entries),
    }
    checked = parse_similarity_materials(raw | {"materials_sha256": content_sha256(raw)})
    return validate_similarity_materials(checked, context)
