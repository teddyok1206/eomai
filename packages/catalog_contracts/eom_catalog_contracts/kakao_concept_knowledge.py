"""Private COMPOSE provenance. Source pointers are not worker or retrieval authority."""

from typing import Literal, Self

from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_rag_knowledge import ChatRagScope
from pydantic import Field, model_validator

from .kakao_concept_tasks import ConceptTaskId
from .knowledge import (
    ContentIntakeKnowledgeSourceV2,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
)
from .material_knowledge_analysis import EducationalDocumentKnowledgeSourceV5
from .models import FrozenModel, Sha256
from .validation import validate_contract

CONCEPT_KNOWLEDGE_REF = "eom://schemas/kakao-archive/concept-knowledge/1.0"
MAX_CONCEPT_KNOWLEDGE_BYTES = 2 * 1024 * 1024


class KakaoConceptResultPin(FrozenModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: Sha256


class KakaoConceptTextbookPin(FrozenModel):
    title: str = Field(min_length=1, max_length=256)
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    source: (
        ContentIntakeKnowledgeSourceV2
        | EducationalDocumentKnowledgeSourceV3
        | EducationalDocumentKnowledgeSourceV4
        | EducationalDocumentKnowledgeSourceV5
    )
    node_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    anchor_ids: tuple[str, ...] = Field(min_length=1, max_length=1024)
    accepted_result: ArtifactMemberPointer
    normalized_markdown: ArtifactMemberPointer
    analysis_text_sha256: Sha256

    @model_validator(mode="after")
    def exact_textbook(self) -> Self:
        if (
            self.source.source_class != "TEXTBOOK"
            or any(
                len(set(values)) != len(values) or any(not 1 <= len(v) <= 128 for v in values)
                for values in (self.node_ids, self.anchor_ids)
            )
            or self.accepted_result.media_type != "application/json"
            or self.normalized_markdown.media_type != "text/markdown"
        ):
            raise ValueError("KAKAO_CONCEPT_TEXTBOOK_PIN_INVALID")
        return self


class KakaoConceptPagePin(FrozenModel):
    evidence_key: Literal["E1", "E2", "E3"]
    physical_page: int = Field(strict=True, ge=1, le=100000)
    original: ArtifactMemberPointer

    @model_validator(mode="after")
    def actual_page(self) -> Self:
        if (self.original.schema_ref, self.original.media_type) != (
            "eom://schemas/educational-document/page-image/1.0",
            "image/png",
        ):
            raise ValueError("KAKAO_CONCEPT_PAGE_PIN_INVALID")
        return self


class KakaoConceptKnowledge(FrozenModel):
    schema_version: Literal["kakao-concept-knowledge/1.0"] = "kakao-concept-knowledge/1.0"
    task_id: ConceptTaskId
    request_sha256: Sha256
    plan_result: KakaoConceptResultPin
    scope: ChatRagScope
    materials: tuple[KakaoConceptTextbookPin, ...] = Field(max_length=3)
    pages: tuple[KakaoConceptPagePin, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def closed_provenance(self) -> Self:
        if (
            len({p.analysis_run_id for p in self.materials}) != len(self.materials)
            or len({(p.evidence_key, p.physical_page) for p in self.pages}) != len(self.pages)
            or any(int(p.evidence_key[1:]) > len(self.materials) for p in self.pages)
            or len(canonical_json_bytes(self)) > MAX_CONCEPT_KNOWLEDGE_BYTES
        ):
            raise ValueError("KAKAO_CONCEPT_KNOWLEDGE_INVALID")
        validate_contract("kakao-concept-knowledge-v1", self.model_dump(mode="json"))
        return self
