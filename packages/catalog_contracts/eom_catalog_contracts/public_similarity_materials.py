"""Bounded question/public-solution staging values, not source or QUERY authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_experiment import CanonicalExperimentItemText
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_delivery import (
    validate_deliverable_public_solution_context,
)
from eom_catalog_contracts.registered_public_solution_embedding import PublicSolutionEncodingEntry
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
    public_solution_reference_for_entry,
)
from eom_catalog_contracts.similarity_materials import (
    MAX_SIMILARITY_MATERIAL_CANDIDATES,
    MAX_SIMILARITY_MATERIALS_BYTES,
)

PUBLIC_SIMILARITY_MATERIALS_SCHEMA = "system-rag-similarity-materials-v3"
PUBLIC_SIMILARITY_MATERIALS_REF = "eom://schemas/knowledge/system-rag-similarity-materials/3.0"
PUBLIC_SIMILARITY_MATERIAL_LIMITATIONS = (
    "PUBLIC_SOLUTION_TEXT_NOT_FULL_REPORT",
    "TEXT_ONLY_NO_PIXEL_INSPECTION",
)


class _MaterialValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def exact_raw_value(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class PublicQuestionAvailable(_MaterialValue):
    status: Literal["AVAILABLE"] = "AVAILABLE"
    content: CanonicalExperimentItemText


class PublicQuestionUnavailable(_MaterialValue):
    status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    reason: Literal[
        "MEDIA_TYPE_UNSUPPORTED",
        "SCHEMA_UNSUPPORTED",
        "SOURCE_BYTE_LIMIT_EXCEEDED",
        "QUESTION_TEXT_LIMIT_EXCEEDED",
    ]


class PublicSolutionReferenceMaterial(_MaterialValue):
    entry: PublicSolutionEncodingEntry
    question: Annotated[
        PublicQuestionAvailable | PublicQuestionUnavailable, Field(discriminator="status")
    ]

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        if self.entry.public_solution.status != "AVAILABLE":
            raise ValueError("PUBLIC_SIMILARITY_MATERIAL_SOLUTION_UNAVAILABLE")
        if isinstance(self.question, PublicQuestionAvailable) and (
            self.question.content.original_source != self.entry.source.artifact_member
            or self.question.content.original_source.media_type != "application/json"
        ):
            raise ValueError("PUBLIC_SIMILARITY_MATERIAL_QUESTION_SOURCE_MISMATCH")
        return self


class PublicSolutionSimilarityMaterials(_MaterialValue):
    schema_version: Literal["system-rag-similarity-materials/3.0"] = (
        "system-rag-similarity-materials/3.0"
    )
    request_sha256: Sha256
    context_sha256: Sha256
    anchor: PublicSolutionReferenceMaterial
    entries: tuple[PublicSolutionReferenceMaterial, ...] = Field(
        max_length=MAX_SIMILARITY_MATERIAL_CANDIDATES
    )
    limitations: tuple[
        Literal["PUBLIC_SOLUTION_TEXT_NOT_FULL_REPORT"], Literal["TEXT_ONLY_NO_PIXEL_INSPECTION"]
    ]
    materials_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, PUBLIC_SIMILARITY_MATERIALS_SCHEMA, MAX_SIMILARITY_MATERIALS_BYTES
        )

    @model_validator(mode="after")
    def exact_identity(self) -> Self:
        revisions = tuple(
            value.entry.source.item_revision_id for value in (self.anchor, *self.entries)
        )
        if len(set(revisions)) != len(revisions):
            raise ValueError("PUBLIC_SIMILARITY_MATERIALS_DUPLICATE")
        if self.materials_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"materials_sha256"})
        ):
            raise ValueError("PUBLIC_SIMILARITY_MATERIALS_HASH_MISMATCH")
        return self


def parse_public_similarity_materials(value: object) -> PublicSolutionSimilarityMaterials:
    return PublicSolutionSimilarityMaterials.model_validate(value)


def validate_public_similarity_materials(
    materials: PublicSolutionSimilarityMaterials,
    context: SupportedPublicSolutionSimilarityContext,
) -> PublicSolutionSimilarityMaterials:
    checked = parse_public_similarity_materials(materials)
    context = validate_deliverable_public_solution_context(
        context, expected_request=context.request
    )
    if (
        checked.request_sha256 != context.request.request_sha256
        or checked.context_sha256 != context.context_sha256
        or len(checked.entries) != len(context.candidates)
    ):
        raise ValueError("PUBLIC_SIMILARITY_MATERIALS_CONTEXT_MISMATCH")
    references = (context.request.anchor, *context.candidates)
    for material, reference in zip((checked.anchor, *checked.entries), references, strict=True):
        entry = material.entry
        if (
            public_solution_reference_for_entry(entry).model_dump(mode="json")
            != reference.model_dump(mode="json", exclude={"observation"})
            or entry.graph_snapshot != context.request.graph_snapshot
            or entry.policy_revision_id != context.request.policy_revision_id
            or entry.policy_sha256 != context.request.policy_sha256
            or entry.recipe != context.request.views[0].recipe
        ):
            raise ValueError("PUBLIC_SIMILARITY_MATERIALS_SOURCE_MISMATCH")
    return checked


def build_public_similarity_materials(
    context: SupportedPublicSolutionSimilarityContext,
    *,
    anchor: PublicSolutionReferenceMaterial,
    entries: tuple[PublicSolutionReferenceMaterial, ...],
) -> PublicSolutionSimilarityMaterials:
    body = {
        "schema_version": "system-rag-similarity-materials/3.0",
        "request_sha256": context.request.request_sha256,
        "context_sha256": context.context_sha256,
        "anchor": raw_similarity_contract_value(anchor),
        "entries": raw_similarity_contract_value(entries),
        "limitations": list(PUBLIC_SIMILARITY_MATERIAL_LIMITATIONS),
    }
    materials = parse_public_similarity_materials(body | {"materials_sha256": content_sha256(body)})
    return validate_public_similarity_materials(materials, context)
