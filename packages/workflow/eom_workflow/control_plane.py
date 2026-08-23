"""Immutable contracts for resolved Codex execution and bounded worker capacity."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


def _safe_relative_markdown_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("materialized path must be a normalized relative path")
    if not value.endswith(".md") or path.parts[0] not in {"instructions", "references"}:
        raise ValueError("materialized path must be an instruction or reference Markdown member")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ArtifactId = Annotated[str, Field(pattern=r"^artifact_[0-9a-f]{32}$")]
ArtifactRevisionId = Annotated[str, Field(pattern=r"^rev_[0-9a-f]{32}$")]
WorkflowId = Annotated[str, Field(pattern=r"^workflow_[0-9a-f]{32}$")]
JobId = Annotated[str, Field(pattern=r"^job_[0-9a-f]{32}$")]
SlotKey = Annotated[str, Field(pattern=r"^slot[0-9]{2}$")]
SafeRelativeMarkdownPath = Annotated[
    str,
    Field(pattern=r"^(instructions|references)/[A-Za-z0-9._/-]+\.md$", max_length=512),
    AfterValidator(_safe_relative_markdown_path),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class ReasoningEffort(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class WorkerRole(StrEnum):
    AUTHORING = "authoring"
    IMAGE = "image"
    REVIEW = "review"
    ITEM_MANAGEMENT = "item_management"
    SUPPORT = "support"


class RevisionState(StrEnum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    DEPRECATED = "DEPRECATED"


class ControlArtifactPointer(FrozenModel):
    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId
    sha256: Sha256
    schema_ref: str = Field(
        pattern=r"^eom(?:\.assess(?:ment)?|://schemas/)[A-Za-z0-9._/@:-]{1,191}$",
        max_length=256,
    )
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$", max_length=128)
    logical_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class BundleRevisionPointer(FrozenModel):
    bundle_id: str = Field(pattern=r"^(?:instrbundle|refbundle)_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^(?:instrrev|refrev)_[0-9a-f]{32}$")
    manifest_artifact: ControlArtifactPointer
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def matched_bundle_family(self) -> BundleRevisionPointer:
        instruction = self.bundle_id.startswith("instrbundle_")
        if instruction != self.bundle_revision_id.startswith("instrrev_"):
            raise ValueError("bundle logical and revision IDs must use the same family")
        return self


class ModelCandidate(FrozenModel):
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: ReasoningEffort


class RoleExecutionPolicy(FrozenModel):
    role: WorkerRole
    model_candidates: tuple[ModelCandidate, ...] = Field(min_length=1, max_length=4)
    instruction_bundle: BundleRevisionPointer
    reference_bundle: BundleRevisionPointer | None
    worker_pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    timeout_seconds: int = Field(ge=30, le=7200)
    sandbox: Literal["read-only"] = "read-only"
    network: Literal["disabled"] = "disabled"

    @model_validator(mode="after")
    def unique_candidates_and_bundle_types(self) -> RoleExecutionPolicy:
        candidates = [
            (candidate.model, candidate.reasoning_effort) for candidate in self.model_candidates
        ]
        if len(candidates) != len(set(candidates)):
            raise ValueError("model candidates must be unique and ordered")
        if not self.instruction_bundle.bundle_id.startswith("instrbundle_"):
            raise ValueError("instruction policy requires an Instruction Bundle pointer")
        if self.reference_bundle is not None and not self.reference_bundle.bundle_id.startswith(
            "refbundle_"
        ):
            raise ValueError("reference policy requires a Reference Bundle pointer")
        return self


class ExecutionPresetRevision(FrozenModel):
    schema_version: Literal["execution-preset-revision/1.0"] = "execution-preset-revision/1.0"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: RevisionState
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    role_policies: tuple[RoleExecutionPolicy, ...] = Field(min_length=1, max_length=5)
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    general_knowledge_policy: Literal["DENY", "ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[
        Annotated[str, Field(pattern=r"^workflow-role/[0-9]+\.[0-9]+\.[0-9]+$")], ...
    ] = Field(min_length=1, max_length=16)
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def unique_roles_and_protocols(self) -> ExecutionPresetRevision:
        roles = [policy.role for policy in self.role_policies]
        if len(roles) != len(set(roles)):
            raise ValueError("preset role policies must be unique")
        if len(self.compatible_workflow_protocols) != len(set(self.compatible_workflow_protocols)):
            raise ValueError("compatible workflow protocols must be unique")
        return self


class InstructionComponent(FrozenModel):
    layer: Literal["PLATFORM", "ROLE"]
    relative_path: SafeRelativeMarkdownPath
    artifact: ControlArtifactPointer

    @field_validator("relative_path")
    @classmethod
    def instruction_member_path(cls, value: str) -> str:
        if not value.startswith("instructions/"):
            raise ValueError("instruction component must materialize under instructions/")
        return value


class InstructionBundleManifest(FrozenModel):
    schema_version: Literal["instruction-bundle-manifest/1.0"] = "instruction-bundle-manifest/1.0"
    bundle_id: str = Field(pattern=r"^instrbundle_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^instrrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: RevisionState
    components: tuple[InstructionComponent, ...] = Field(min_length=1, max_length=32)
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def unique_component_paths(self) -> InstructionBundleManifest:
        paths = [component.relative_path for component in self.components]
        if len(paths) != len(set(paths)):
            raise ValueError("instruction component paths must be unique")
        return self


class ReferenceEntry(FrozenModel):
    reference_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    source_class: Literal["CURRICULUM", "TEXTBOOK", "APPROVED_ITEM", "PAST_EXAM", "INTERNAL_GUIDE"]
    relative_path: SafeRelativeMarkdownPath
    source_logical_id: str = Field(pattern=r"^[a-z][a-z0-9]*_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^[a-z][a-z0-9]*rev_[0-9a-f]{32}$")
    rights_policy_revision_id: str = Field(pattern=r"^rightsrev_[0-9a-f]{32}$")
    artifact: ControlArtifactPointer

    @field_validator("relative_path")
    @classmethod
    def reference_member_path(cls, value: str) -> str:
        if not value.startswith("references/"):
            raise ValueError("reference entry must materialize under references/")
        return value


class ReferenceBundleManifest(FrozenModel):
    schema_version: Literal["reference-bundle-manifest/1.0"] = "reference-bundle-manifest/1.0"
    bundle_id: str = Field(pattern=r"^refbundle_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^refrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: RevisionState
    entries: tuple[ReferenceEntry, ...] = Field(min_length=1, max_length=256)
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def unique_entries(self) -> ReferenceBundleManifest:
        keys = [entry.reference_key for entry in self.entries]
        paths = [entry.relative_path for entry in self.entries]
        if len(keys) != len(set(keys)) or len(paths) != len(set(paths)):
            raise ValueError("reference keys and paths must be unique")
        return self


class ResolvedStepExecution(FrozenModel):
    step_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    role: WorkerRole
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: ReasoningEffort
    instruction_bundle: BundleRevisionPointer
    reference_bundle: BundleRevisionPointer | None
    worker_pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    timeout_seconds: int = Field(ge=30, le=7200)
    sandbox: Literal["read-only"] = "read-only"
    network: Literal["disabled"] = "disabled"
    general_knowledge_mode: Literal["DENIED", "ALLOWED_WITH_PROVENANCE"]

    @model_validator(mode="after")
    def validate_bundle_types(self) -> ResolvedStepExecution:
        if not self.instruction_bundle.bundle_id.startswith("instrbundle_"):
            raise ValueError("resolved instruction pointer has the wrong bundle family")
        if self.reference_bundle is not None and not self.reference_bundle.bundle_id.startswith(
            "refbundle_"
        ):
            raise ValueError("resolved reference pointer has the wrong bundle family")
        return self


class ResolvedExecutionPlan(FrozenModel):
    schema_version: Literal["resolved-execution-plan/1.0"] = "resolved-execution-plan/1.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    workflow_definition_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    workflow_definition_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    workflow_definition_sha256: Sha256
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    content_pack_sha256: Sha256
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str | None = Field(default=None, pattern=r"^graphrev_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str | None = Field(
        default=None, pattern=r"^evidencerev_[0-9a-f]{32}$"
    )
    steps: tuple[ResolvedStepExecution, ...] = Field(min_length=1, max_length=64)
    resolver_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def stable_step_and_evidence_pointers(self) -> ResolvedExecutionPlan:
        keys = [step.step_key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("resolved step keys must be unique")
        if self.evidence_bundle_revision_id is not None and self.graph_snapshot_revision_id is None:
            raise ValueError("an Evidence Bundle requires its pinned Graph Snapshot")
        return self


class CodexAuthHealthView(FrozenModel):
    schema_version: Literal["codex-auth-health-view/1.0"] = "codex-auth-health-view/1.0"
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    slot_key: SlotKey
    account_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    state: Literal["READY", "STALE", "AUTH_REQUIRED", "DEGRADED", "DRAINING", "DISABLED"]
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    codex_cli_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    observed_at: UtcDatetime
    valid_until: UtcDatetime

    @model_validator(mode="after")
    def coherent_health_window(self) -> CodexAuthHealthView:
        if self.valid_until <= self.observed_at:
            raise ValueError("authentication observation must expire after it was observed")
        if self.state == "READY" and self.reason_code is not None:
            raise ValueError("READY authentication health cannot include a failure reason")
        if self.state != "READY" and self.reason_code is None:
            raise ValueError("non-READY authentication health requires a reason code")
        return self


class ModelCapability(FrozenModel):
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_efforts: tuple[ReasoningEffort, ...] = Field(min_length=1, max_length=5)
    state: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]

    @model_validator(mode="after")
    def unique_efforts(self) -> ModelCapability:
        if len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
            raise ValueError("capability reasoning efforts must be unique")
        return self


class CodexCapabilitySnapshot(FrozenModel):
    schema_version: Literal["codex-capability-snapshot/1.0"] = "codex-capability-snapshot/1.0"
    capability_snapshot_id: str = Field(pattern=r"^capsnap_[0-9a-f]{32}$")
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    codex_cli_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    source: Literal["LOCAL_OBSERVATION", "OPERATOR_ASSERTED"]
    capabilities: tuple[ModelCapability, ...] = Field(min_length=1, max_length=64)
    observed_at: UtcDatetime
    valid_until: UtcDatetime
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def coherent_capability_snapshot(self) -> CodexCapabilitySnapshot:
        models = [capability.model for capability in self.capabilities]
        if len(models) != len(set(models)):
            raise ValueError("capability models must be unique")
        if self.valid_until <= self.observed_at:
            raise ValueError("capability snapshot must expire after it was observed")
        return self


class WorkerCapacityPool(FrozenModel):
    pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    roles: tuple[WorkerRole, ...] = Field(min_length=1, max_length=5)
    slot_keys: tuple[SlotKey, ...] = Field(min_length=1, max_length=5)
    max_active: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def bounded_unique_pool(self) -> WorkerCapacityPool:
        if len(self.roles) != len(set(self.roles)) or len(self.slot_keys) != len(
            set(self.slot_keys)
        ):
            raise ValueError("capacity pool roles and slots must be unique")
        if self.max_active > len(self.slot_keys):
            raise ValueError("capacity pool cannot activate more workers than configured slots")
        return self


class WorkerCapacityPolicy(FrozenModel):
    schema_version: Literal["worker-capacity-policy/1.0"] = "worker-capacity-policy/1.0"
    capacity_policy_id: str = Field(pattern=r"^capacity_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: RevisionState
    max_configured_slots: int = Field(ge=1, le=5)
    max_active_codex: int = Field(ge=1, le=3)
    max_active_per_slot: Literal[1] = 1
    max_active_gpu: Literal[1] = 1
    max_active_knowledge_analysis: Literal[1] = 1
    pools: tuple[WorkerCapacityPool, ...] = Field(min_length=1, max_length=5)
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_capacity_limits(self) -> WorkerCapacityPolicy:
        if self.max_active_codex > self.max_configured_slots:
            raise ValueError("global active limit cannot exceed configured slots")
        pool_keys = [pool.pool_key for pool in self.pools]
        if len(pool_keys) != len(set(pool_keys)):
            raise ValueError("capacity pool keys must be unique")
        all_slots = {slot for pool in self.pools for slot in pool.slot_keys}
        if len(all_slots) > self.max_configured_slots:
            raise ValueError("capacity pools reference too many configured slots")
        if any(pool.max_active > self.max_active_codex for pool in self.pools):
            raise ValueError("pool active limit cannot exceed global active limit")
        return self


class WorkerLeaseView(FrozenModel):
    schema_version: Literal["worker-lease-view/1.0"] = "worker-lease-view/1.0"
    lease_id: str = Field(pattern=r"^workerlease_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    slot_key: SlotKey
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    job_id: JobId
    attempt: int = Field(ge=1, le=10)
    state: Literal["ACTIVE", "RELEASED", "EXPIRED", "RECONCILING"]
    acquired_at: UtcDatetime
    expires_at: UtcDatetime
    released_at: UtcDatetime | None
    release_reason: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def coherent_lease_window(self) -> WorkerLeaseView:
        if self.expires_at <= self.acquired_at:
            raise ValueError("worker lease must expire after acquisition")
        released = self.state in {"RELEASED", "EXPIRED"}
        if released != (self.released_at is not None and self.release_reason is not None):
            raise ValueError("terminal lease state requires release time and reason")
        if self.released_at is not None and self.released_at < self.acquired_at:
            raise ValueError("lease release cannot predate acquisition")
        return self
