"""Versioned application contracts for intake, packs, registry, and usage."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


def _safe_text(value: str) -> str:
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError("text contains a control character")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
IntakeBatchId = Annotated[str, Field(pattern=r"^intake_[0-9a-f]{32}$")]
SourceFileId = Annotated[str, Field(pattern=r"^sourcefile_[0-9a-f]{32}$")]
ActorId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class AnalysisSourceType(StrEnum):
    HUMAN = "HUMAN"
    MANUAL_EXTERNAL_ANALYSIS = "MANUAL_EXTERNAL_ANALYSIS"
    CHATGPT_MANUAL = "CHATGPT_MANUAL"
    CODEX_LOCAL = "CODEX_LOCAL"
    OTHER = "OTHER"


class IntakeDecisionValue(StrEnum):
    PENDING = "PENDING"
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_CHANGES = "ACCEPT_WITH_CHANGES"
    REJECT = "REJECT"
    SUPERSEDE = "SUPERSEDE"


class SourceOwner(FrozenModel):
    type: Literal["internal_team_member", "external_partner", "legacy_system", "other"]
    reference: str = Field(min_length=1, max_length=128)

    _text = field_validator("reference")(_safe_text)


class IntakeSourceFile(FrozenModel):
    source_file_id: SourceFileId
    relative_path: str = Field(
        pattern=r"^source/[A-Za-z0-9._()가-힣/-]+$", min_length=8, max_length=512
    )
    original_filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$")
    size_bytes: int = Field(ge=0, le=100 * 1024 * 1024)
    sha256: Sha256
    declared_role: Literal["REFERENCE", "GUIDELINE", "DATA", "ASSET", "OTHER"]
    declared_description: str = Field(min_length=1, max_length=500)

    _text = field_validator("relative_path", "original_filename", "declared_description")(
        _safe_text
    )


class IntakeManifest(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: IntakeBatchId
    batch_name: str = Field(min_length=1, max_length=128)
    received_at: UtcDatetime
    received_by: ActorId
    source_owner: SourceOwner
    purpose: str = Field(min_length=1, max_length=500)
    files: tuple[IntakeSourceFile, ...] = Field(min_length=1, max_length=500)

    _text = field_validator("batch_name", "purpose")(_safe_text)


class ProposalChange(FrozenModel):
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    source_reference: str = Field(min_length=1, max_length=128)
    value: dict[str, Any]


class ChangeSet(FrozenModel):
    add: tuple[ProposalChange, ...] = Field(max_length=500)
    update: tuple[ProposalChange, ...] = Field(max_length=500)


class TaxonomyChangeSet(ChangeSet):
    retire: tuple[ProposalChange, ...] = Field(max_length=500)


class ProfileChanges(FrozenModel):
    authoring: ChangeSet
    review: ChangeSet
    image: ChangeSet
    registration: ChangeSet


class ProposalChanges(FrozenModel):
    taxonomies: TaxonomyChangeSet
    item_types: ChangeSet
    profiles: ProfileChanges
    prompt_templates: ChangeSet
    metadata_schemas: ChangeSet
    rubrics: ChangeSet


class IntakeUncertainty(FrozenModel):
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    description: str = Field(min_length=1, max_length=1000)
    blocking: bool

    _text = field_validator("description")(_safe_text)


class ExcludedSource(FrozenModel):
    source_reference: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)

    _text = field_validator("source_reference", "reason")(_safe_text)


class ProposalHeader(FrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    source_batch_id: IntakeBatchId
    analysis_source_type: AnalysisSourceType
    created_by: ActorId
    created_at: UtcDatetime


class MappingProposal(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    proposal: ProposalHeader
    changes: ProposalChanges
    uncertainties: tuple[IntakeUncertainty, ...] = Field(max_length=200)
    excluded: tuple[ExcludedSource, ...] = Field(max_length=500)


class UncertaintiesDocument(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: IntakeBatchId
    items: tuple[IntakeUncertainty, ...] = Field(max_length=200)


class HumanDecision(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: IntakeBatchId
    proposal_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    decision: IntakeDecisionValue
    decided_by: ActorId
    decided_at: UtcDatetime
    accepted_change_keys: tuple[str, ...]
    rejected_change_keys: tuple[str, ...]
    required_corrections: tuple[str, ...]
    notes: str = Field(min_length=1, max_length=2000)

    _text = field_validator("notes")(_safe_text)


# GUI and future HTTP adapters depend on these DTOs instead of persistence records.
class CreateIntakeBatch(FrozenModel):
    source_directory: str = Field(min_length=1, max_length=1024)
    batch_name: str = Field(min_length=1, max_length=128)
    received_by: ActorId


class AttachIntakeAnalysis(FrozenModel):
    intake_batch_id: IntakeBatchId
    analysis_source_type: AnalysisSourceType
    created_by: ActorId


class DecideIntakeBatch(FrozenModel):
    intake_batch_id: IntakeBatchId
    decision: IntakeDecisionValue
    actor_id: ActorId


class GeneratePackSource(FrozenModel):
    intake_batch_id: IntakeBatchId
    pack_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class ImportContentPack(FrozenModel):
    bundle_path: str = Field(min_length=1, max_length=1024)


class ReleaseContentPack(FrozenModel):
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    actor_id: ActorId


class ActivateContentPack(FrozenModel):
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    environment: Literal["development", "test"]
    actor_id: ActorId


class CreateItem(FrozenModel):
    actor_id: ActorId
    idempotency_key: str = Field(min_length=1, max_length=200)


class CreateItemRevision(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    base_revision_id: str | None = Field(default=None, pattern=r"^itemrev_[0-9a-f]{32}$")
    actor_id: ActorId


class ApproveItemRevision(FrozenModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    actor_id: ActorId


class RetireItem(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    actor_id: ActorId
    reason: str = Field(min_length=1, max_length=1000)


class CreateDeliverable(FrozenModel):
    deliverable_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    actor_id: ActorId


class CreateUsagePlan(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    actor_id: ActorId


class UsagePlanCommand(FrozenModel):
    usage_plan_id: str = Field(pattern=r"^usageplan_[0-9a-f]{32}$")
    actor_id: ActorId


ReserveUsagePlan = UsagePlanCommand
FulfillUsagePlan = UsagePlanCommand
CancelUsagePlan = UsagePlanCommand


class CatalogPageQuery(FrozenModel):
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=512)


class GetIntakeBatch(FrozenModel):
    intake_batch_id: IntakeBatchId


class ListIntakeBatches(CatalogPageQuery):
    state: str | None = Field(default=None, max_length=40)


class GetContentPackRelease(FrozenModel):
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")


class ListContentPackReleases(CatalogPageQuery):
    pack_key: str | None = Field(default=None, max_length=64)


class ResolveActiveContentPack(FrozenModel):
    pack_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    environment: Literal["development", "test"]


class GetItem(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")


class GetItemRevision(FrozenModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")


class SearchItems(CatalogPageQuery):
    item_state: str | None = Field(default=None, max_length=32)
    revision_state: str | None = Field(default=None, max_length=32)
    pack_key: str | None = Field(default=None, max_length=64)
    item_type_key: str | None = Field(default=None, max_length=128)
    unused_only: bool = False


ListItemRevisions = GetItem
GetItemUsageHistory = GetItem


class GetDeliverable(FrozenModel):
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")


class ListDeliverables(CatalogPageQuery):
    deliverable_type: str | None = Field(default=None, max_length=32)


class ListUsagePlans(CatalogPageQuery):
    status: str | None = Field(default=None, max_length=32)


class ListUsageRecords(CatalogPageQuery):
    deliverable_id: str | None = Field(default=None, pattern=r"^deliverable_[0-9a-f]{32}$")
