"""Fixed25 DOCUMENT pair observations; no query, authority or approval judgement."""

from __future__ import annotations

from itertools import combinations
from typing import Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.assessment_assembly import MockExamAssemblyCohortV1
from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.inference_transfer_experiment import VIEWS, ExperimentView
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context import (
    ApprovedReferenceItemAnchor,
    SimilarityViewSelection,
)

EXAM_OBSERVATION_SCHEMA = "system-rag-exam-observation"
MAX_EXAM_OBSERVATION_BYTES = 1024 * 1024


class _Value(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class ExamObservationRequest(_Value):
    schema_version: Literal["system-rag-exam-observation-request/1.0"]
    consumer_purpose: Literal["MOCK_EXAM_OBSERVATION"]
    cohort: MockExamAssemblyCohortV1
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    views: tuple[SimilarityViewSelection, ...] = Field(min_length=1, max_length=3)
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, EXAM_OBSERVATION_SCHEMA, MAX_EXAM_OBSERVATION_BYTES
        )

    @model_validator(mode="after")
    def exact_scope(self) -> ExamObservationRequest:
        views = tuple(selection.view for selection in self.views)
        indexes = tuple(selection.index for selection in self.views if selection.index is not None)
        if (
            self.source_classes != tuple(sorted(set(self.source_classes)))
            or views != tuple(view for view in VIEWS if view in views)
            or self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256
            or len({(pin.index_id, pin.index_revision_id) for pin in indexes}) != len(indexes)
            or any(
                pin.spaces != indexes[0].spaces
                or pin.storage_partition != indexes[0].storage_partition
                for pin in indexes
            )
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("exam observation scope/order/hash differs")
        return self


class ExamObservationMember(_Value):
    position: int = Field(ge=1, le=25, strict=True)
    reference: ApprovedReferenceItemAnchor


class ExamObservationRow(_Value):
    position: int = Field(ge=1, le=25, strict=True)
    document_row: EmbeddingVectorRowRef


class ExamPairObservation(_Value):
    left_position: int = Field(ge=1, le=25, strict=True)
    right_position: int = Field(ge=1, le=25, strict=True)
    cosine_millionths: int = Field(ge=-1000000, le=1000000, strict=True)


class ExamViewObservation(_Value):
    view: ExperimentView
    status: Literal["COMPLETE", "PARTIAL", "EMPTY", "INDEX_NOT_PREPARED"]
    rows: tuple[ExamObservationRow, ...] = Field(max_length=25)
    pairs: tuple[ExamPairObservation, ...] = Field(max_length=300)

    @model_validator(mode="after")
    def exact_pairs(self) -> ExamViewObservation:
        positions = tuple(row.position for row in self.rows)
        expected = tuple(combinations(positions, 2))
        actual = tuple((pair.left_position, pair.right_position) for pair in self.pairs)
        status = (
            "COMPLETE" if len(positions) == 25 else "PARTIAL" if len(positions) >= 2 else "EMPTY"
        )
        if (
            positions != tuple(sorted(set(positions)))
            or actual != expected
            or (self.status == "INDEX_NOT_PREPARED" and (self.rows or self.pairs))
            or (self.status != "INDEX_NOT_PREPARED" and self.status != status)
        ):
            raise ValueError("exam pair order/coverage/status differs")
        return self


class ExamSimilarityObservation(_Value):
    schema_version: Literal["system-rag-exam-observation/1.0"]
    request: ExamObservationRequest
    status: Literal["READY", "PARTIAL", "EMPTY"]
    members: tuple[ExamObservationMember, ...] = Field(min_length=25, max_length=25)
    views: tuple[ExamViewObservation, ...] = Field(min_length=1, max_length=3)
    score_semantics: Literal["ROUNDED_DISPLAY_ONLY_NOT_SOLUTION_EQUALITY_OR_APPROVAL"]
    result_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, EXAM_OBSERVATION_SCHEMA, MAX_EXAM_OBSERVATION_BYTES
        )

    @model_validator(mode="after")
    def exact_result(self) -> ExamSimilarityObservation:
        expected = tuple((m.position, m.item_revision_id) for m in self.request.cohort.members)
        actual = tuple((m.position, m.reference.source.item_revision_id) for m in self.members)
        reported = {m.position for m in self.members if m.reference.profile is not None}
        status = (
            "READY"
            if len(reported) == 25 and all(v.status == "COMPLETE" for v in self.views)
            else "PARTIAL"
            if any(v.pairs for v in self.views)
            else "EMPTY"
        )
        if (
            actual != expected
            or tuple(v.view for v in self.views) != tuple(s.view for s in self.request.views)
            or any(
                m.reference.source.source_class not in self.request.source_classes
                for m in self.members
            )
            or any(
                (s.index is None) != (v.status == "INDEX_NOT_PREPARED")
                or not {r.position for r in v.rows}.issubset(reported)
                for s, v in zip(self.request.views, self.views, strict=True)
            )
            or self.status != status
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("exam result membership/coverage/hash differs")
        return self


def parse_exam_observation_request(value: object) -> ExamObservationRequest:
    return ExamObservationRequest.model_validate(raw_similarity_contract_value(value))


def parse_exam_similarity_observation(value: object) -> ExamSimilarityObservation:
    return ExamSimilarityObservation.model_validate(raw_similarity_contract_value(value))
