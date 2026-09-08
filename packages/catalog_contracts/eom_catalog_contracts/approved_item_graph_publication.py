"""Protocol for publishing freshly approved Item analyses into Graph RAG."""

from __future__ import annotations

from typing import Final, Literal

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

APPROVED_ITEM_GRAPH_PUBLICATION_COMMAND_SCHEMA: Final = "approved-item-graph-publication-command"
APPROVED_ITEM_GRAPH_PUBLICATION_RESULT_SCHEMA: Final = "approved-item-graph-publication-result"


class PublishApprovedItemAnalysesCommand(FrozenModel):
    """Publish an exact, ordered set of accepted generated-Item analyses."""

    operation: Literal["PUBLISH_APPROVED_ITEM_ANALYSES"] = "PUBLISH_APPROVED_ITEM_ANALYSES"
    schema_version: Literal["approved-item-graph-publication-command/1.0"] = (
        "approved-item-graph-publication-command/1.0"
    )
    corpus_key: Literal["integrated-science-textbooks"] = "integrated-science-textbooks"
    expected_current_graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    expected_current_graph_snapshot_sha256: Sha256
    accepted_analysis_run_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    expected_workflow_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    authorized_at: UtcDatetime
    idempotency_key: str = Field(
        min_length=16,
        max_length=96,
        pattern=r"^[\x21-\x7e]+$",
    )
    submission_sha256: Sha256

    @field_validator("accepted_analysis_run_ids")
    @classmethod
    def analysis_run_id_syntax(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if (
                len(value) != 44
                or not value.startswith("analysisrun_")
                or any(character not in "0123456789abcdef" for character in value[12:])
            ):
                raise ValueError("accepted analysis run identity is invalid")
        return values

    @field_validator("expected_workflow_ids")
    @classmethod
    def workflow_id_syntax(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if (
                len(value) != 41
                or not value.startswith("workflow_")
                or any(character not in "0123456789abcdef" for character in value[9:])
            ):
                raise ValueError("expected Workflow identity is invalid")
        return values

    @model_validator(mode="after")
    def exact_ordered_analysis_set_and_hash(self) -> PublishApprovedItemAnalysesCommand:
        if len(self.accepted_analysis_run_ids) != len(set(self.accepted_analysis_run_ids)) or len(
            self.expected_workflow_ids
        ) != len(set(self.expected_workflow_ids)):
            raise ValueError("analysis and Workflow IDs must be unique and ordered")
        canonical = self.model_dump(
            mode="json",
            exclude={"idempotency_key", "submission_sha256"},
        )
        if content_sha256(canonical) != self.submission_sha256:
            raise ValueError("approved Item Graph publication submission hash does not match")
        return self


class ApprovedItemGraphPublicationResult(FrozenModel):
    """Pointer-only receipt for a fresh publication or its exact replay."""

    schema_version: Literal["approved-item-graph-publication-result/1.0"] = (
        "approved-item-graph-publication-result/1.0"
    )
    publication_id: str = Field(pattern=r"^graphpub_[0-9a-f]{32}$")
    corpus_key: Literal["integrated-science-textbooks"] = "integrated-science-textbooks"
    previous_graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    previous_graph_snapshot_sha256: Sha256
    graph_snapshot: KnowledgeGraphSnapshotPointer
    graph_snapshot_sha256: Sha256
    revision_number: int = Field(ge=1)
    accepted_analysis_run_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    expected_workflow_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    item_revision_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    authorized_at: UtcDatetime
    outcome: Literal["CREATED", "REPLAYED"]
    published_at: UtcDatetime
    result_sha256: Sha256

    @field_validator("accepted_analysis_run_ids")
    @classmethod
    def result_analysis_run_id_syntax(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if (
                len(value) != 44
                or not value.startswith("analysisrun_")
                or any(character not in "0123456789abcdef" for character in value[12:])
            ):
                raise ValueError("published analysis run identity is invalid")
        return values

    @field_validator("item_revision_ids")
    @classmethod
    def result_item_revision_id_syntax(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if (
                len(value) != 40
                or not value.startswith("itemrev_")
                or any(character not in "0123456789abcdef" for character in value[8:])
            ):
                raise ValueError("published Item Revision identity is invalid")
        return values

    @field_validator("expected_workflow_ids")
    @classmethod
    def result_workflow_id_syntax(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if (
                len(value) != 41
                or not value.startswith("workflow_")
                or any(character not in "0123456789abcdef" for character in value[9:])
            ):
                raise ValueError("published Workflow identity is invalid")
        return values

    @model_validator(mode="after")
    def pointer_set_and_hash_are_closed(self) -> ApprovedItemGraphPublicationResult:
        if (
            len(self.accepted_analysis_run_ids) != len(set(self.accepted_analysis_run_ids))
            or len(self.expected_workflow_ids) != len(set(self.expected_workflow_ids))
            or len(self.item_revision_ids) != len(set(self.item_revision_ids))
            or len(self.accepted_analysis_run_ids) != len(self.expected_workflow_ids)
            or len(self.accepted_analysis_run_ids) != len(self.item_revision_ids)
        ):
            raise ValueError(
                "published analysis, Workflow, and Item Revision identities must be one-to-one"
            )
        if self.authorized_at > self.published_at:
            raise ValueError("Graph publication authorization cannot follow publication")
        if self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256:
            raise ValueError("published Graph manifest hash pointer is inconsistent")
        canonical = self.model_dump(mode="json", exclude={"result_sha256"})
        if content_sha256(canonical) != self.result_sha256:
            raise ValueError("approved Item Graph publication result hash does not match")
        return self
