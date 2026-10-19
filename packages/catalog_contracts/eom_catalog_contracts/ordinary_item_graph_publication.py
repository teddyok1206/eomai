"""Ordinary approved registration publication, separate from 25-item production."""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

ORDINARY_ITEM_GRAPH_COMMAND_SCHEMA = "ordinary-item-graph-publication-command"
ORDINARY_ITEM_GRAPH_RESULT_SCHEMA = "ordinary-item-graph-publication-result"


class _PublicationValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def untrusted_frozen_value(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class OrdinaryItemGraphPublicationSource(_PublicationValue):
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    source: ApprovedItemKnowledgeSourceV2
    accepted_result: KnowledgeArtifactMemberPointer
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    expected_curriculum_unit_key: str = Field(min_length=1, max_length=80)
    expected_plan_sha256: Sha256
    review_evidence_sha256: Sha256

    @model_validator(mode="after")
    def approved_v2_only(self) -> Self:
        if (
            self.source.source_class != "APPROVED_ITEM"
            or self.accepted_result.schema_ref
            != "eom://schemas/knowledge/knowledge-analysis-result/2.0"
            or self.accepted_result.media_type != "application/json"
        ):
            raise ValueError("ordinary publication requires an approved Item and real accepted V2")
        return self


class _PublicationSources(_PublicationValue):
    corpus_key: Literal["integrated-science-textbooks"] = "integrated-science-textbooks"
    sources: tuple[OrdinaryItemGraphPublicationSource, ...] = Field(min_length=1, max_length=16)
    authorized_at: UtcDatetime

    @model_validator(mode="after")
    def canonical_unique_sources(self) -> Self:
        run_ids = tuple(row.analysis_run_id for row in self.sources)
        if (
            run_ids != tuple(sorted(set(run_ids)))
            or len({row.source.item_revision_id for row in self.sources}) != len(self.sources)
            or len({row.workflow_id for row in self.sources}) != len(self.sources)
        ):
            raise ValueError("ordinary sources must be unique and ordered by analysis run ID")
        return self


class PublishOrdinaryApprovedItemAnalysesCommand(_PublicationSources):
    operation: Literal["PUBLISH_ORDINARY_APPROVED_ITEM_ANALYSES"] = (
        "PUBLISH_ORDINARY_APPROVED_ITEM_ANALYSES"
    )
    schema_version: Literal["ordinary-item-graph-publication-command/1.0"] = (
        "ordinary-item-graph-publication-command/1.0"
    )
    expected_graph_snapshot: KnowledgeGraphSnapshotPointer
    expected_graph_snapshot_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=16, max_length=96, pattern=r"^[!-~]+$")
    submission_sha256: Sha256

    @model_validator(mode="after")
    def exact_submission(self) -> Self:
        if (
            self.expected_graph_snapshot.manifest_sha256
            != self.expected_graph_snapshot.manifest_artifact.sha256
            or content_sha256(
                self.model_dump(mode="json", exclude={"idempotency_key", "submission_sha256"})
            )
            != self.submission_sha256
        ):
            raise ValueError("ordinary publication submission hash/pointer differs")
        return self


class OrdinaryItemGraphPublicationResult(_PublicationSources):
    schema_version: Literal["ordinary-item-graph-publication-result/1.0"] = (
        "ordinary-item-graph-publication-result/1.0"
    )
    publication_id: str = Field(pattern=r"^graphpub_[0-9a-f]{32}$")
    previous_graph_snapshot: KnowledgeGraphSnapshotPointer
    previous_graph_snapshot_sha256: Sha256
    graph_snapshot: KnowledgeGraphSnapshotPointer
    graph_snapshot_sha256: Sha256
    submission_sha256: Sha256
    outcome: Literal["CREATED", "REPLAYED"]
    published_at: UtcDatetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        if (
            self.authorized_at > self.published_at
            or self.previous_graph_snapshot.graph_snapshot_revision_id
            == self.graph_snapshot.graph_snapshot_revision_id
            or any(
                pointer.manifest_sha256 != pointer.manifest_artifact.sha256
                for pointer in (self.previous_graph_snapshot, self.graph_snapshot)
            )
            or content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
            != self.result_sha256
        ):
            raise ValueError("ordinary publication result hash/pointer differs")
        return self
