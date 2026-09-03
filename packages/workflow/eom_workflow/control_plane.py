"""Immutable contracts for resolved Codex execution and bounded worker capacity."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal
from unicodedata import normalize
from urllib.parse import urlsplit

from eom_catalog_contracts import (
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationalRetrievalRequirement,
    EvidenceBudget,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphSnapshotPointer,
    KnowledgeSourceClass,
    LegacyItemEditorialCompatibilityRequest,
    LegacyItemExtractionRequest,
)
from eom_identifiers import content_sha256
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


def _safe_canonical_member_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or not path.parts:
        raise ValueError("source member path must be normalized and relative")
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
SafeCanonicalMemberPath = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9._()가-힣/-]+$", min_length=1, max_length=512),
    AfterValidator(_safe_canonical_member_path),
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


class RoleExecutionPolicyV2(RoleExecutionPolicy):
    evidence_access: Literal["NONE", "EVIDENCE_CONTEXT"]


class ExecutionPresetRetrievalPolicy(FrozenModel):
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    allowed_corpus_keys: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")], ...] = (
        Field(min_length=1, max_length=16)
    )
    allowed_query_kinds: tuple[
        Literal["CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE", "ITEM_PREPARATION"], ...
    ] = Field(min_length=1, max_length=3)
    allowed_source_classes: tuple[KnowledgeSourceClass, ...] = Field(min_length=1, max_length=5)
    maximum_budget: EvidenceBudget

    @model_validator(mode="after")
    def deterministic_closed_policy(self) -> ExecutionPresetRetrievalPolicy:
        for values, label in (
            (self.allowed_corpus_keys, "corpus keys"),
            (self.allowed_query_kinds, "query kinds"),
            (self.allowed_source_classes, "source classes"),
        ):
            if tuple(sorted(values)) != values or len(values) != len(set(values)):
                raise ValueError(f"preset retrieval {label} must be sorted and unique")
        return self


class ExecutionPresetRevisionV2(FrozenModel):
    """Additive preset contract selecting graph policy and least-needed role evidence."""

    schema_version: Literal["execution-preset-revision/2.0"] = "execution-preset-revision/2.0"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: RevisionState
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    role_policies: tuple[RoleExecutionPolicyV2, ...] = Field(min_length=1, max_length=5)
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    general_knowledge_policy: Literal["DENY", "ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[
        Annotated[str, Field(pattern=r"^workflow-role/[0-9]+\.[0-9]+\.[0-9]+$")], ...
    ] = Field(min_length=1, max_length=16)
    retrieval_policy: ExecutionPresetRetrievalPolicy
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def unique_roles_protocols_and_private_registration(self) -> ExecutionPresetRevisionV2:
        roles = [policy.role for policy in self.role_policies]
        if len(roles) != len(set(roles)):
            raise ValueError("preset role policies must be unique")
        if len(self.compatible_workflow_protocols) != len(set(self.compatible_workflow_protocols)):
            raise ValueError("compatible workflow protocols must be unique")
        if not any(policy.evidence_access == "EVIDENCE_CONTEXT" for policy in self.role_policies):
            raise ValueError("knowledge-backed preset must expose evidence to at least one role")
        item_management = [
            policy for policy in self.role_policies if policy.role == "item_management"
        ]
        if item_management and item_management[0].evidence_access != "NONE":
            raise ValueError("item management must not receive Evidence Bundle context")
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


class ResolvedExecutionPlanV2(FrozenModel):
    """Single-support-worker plan for one exact knowledge-analysis request and source."""

    schema_version: Literal["resolved-execution-plan/2.0"] = "resolved-execution-plan/2.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    workload_class: Literal["KNOWLEDGE_ANALYSIS"] = "KNOWLEDGE_ANALYSIS"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    workflow_definition_key: Literal["knowledge-analysis"] = "knowledge-analysis"
    workflow_definition_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    workflow_definition_sha256: Sha256
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    analysis_request_sha256: Sha256
    source_artifact_id: ArtifactId
    source_artifact_revision_id: ArtifactRevisionId
    source_member_path: SafeCanonicalMemberPath
    source_materialized_path: str = Field(
        pattern=r"^source/[A-Za-z0-9._()가-힣/-]+$", min_length=8, max_length=512
    )
    source_sha256: Sha256
    source_bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    source_media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$", max_length=128)
    source_schema_ref: str | None = Field(default=None, max_length=256)
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    steps: tuple[ResolvedStepExecution, ...] = Field(min_length=1, max_length=1)
    resolver_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def one_support_step_and_exact_hash(self) -> ResolvedExecutionPlanV2:
        step = self.steps[0]
        if step.step_key != "analyze" or step.role != "support":
            raise ValueError("knowledge analysis plan requires the analyze support step")
        if step.worker_pool_key != "support":
            raise ValueError("knowledge analysis plan requires the support worker pool")
        body = self.model_dump(mode="json", exclude={"plan_sha256"})
        if content_sha256(body) != self.plan_sha256:
            raise ValueError("knowledge analysis plan hash does not match canonical content")
        return self


class ResolvedStepExecutionV3(ResolvedStepExecution):
    evidence_access: Literal["NONE", "EVIDENCE_CONTEXT"]


class ResolvedExecutionPlanV3(FrozenModel):
    """One fresh item workflow pinned to an immutable bounded Evidence Bundle."""

    schema_version: Literal["resolved-execution-plan/3.0"] = "resolved-execution-plan/3.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    workload_class: Literal["KNOWLEDGE_BACKED_ITEM"] = "KNOWLEDGE_BACKED_ITEM"
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
    retrieval_requirement: EducationalRetrievalRequirement
    retrieval_requirement_sha256: Sha256
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    retrieval_request_sha256: Sha256
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    requester_permissions_sha256: Sha256
    evidence_bundle_id: str = Field(pattern=r"^evidence_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    evidence_manifest_artifact: KnowledgeArtifactMemberPointer
    evidence_manifest_sha256: Sha256
    evidence_context_artifact: KnowledgeArtifactMemberPointer
    steps: tuple[ResolvedStepExecutionV3, ...] = Field(min_length=1, max_length=64)
    resolver_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_evidence_and_plan_hashes(self) -> ResolvedExecutionPlanV3:
        keys = [step.step_key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("resolved step keys must be unique")
        if content_sha256(self.retrieval_requirement.model_dump(mode="json")) != (
            self.retrieval_requirement_sha256
        ):
            raise ValueError("educational retrieval requirement hash differs")
        if (
            self.evidence_manifest_artifact.member_path != "evidence/manifest.json"
            or self.evidence_manifest_artifact.media_type != "application/json"
            or self.evidence_manifest_artifact.schema_ref
            not in {
                "eom://schemas/knowledge/evidence-bundle-manifest/2.0",
                "eom://schemas/knowledge/evidence-bundle-manifest/3.0",
                "eom://schemas/knowledge/evidence-bundle-manifest/4.0",
            }
            or self.evidence_context_artifact.member_path != "evidence/context.md"
            or self.evidence_context_artifact.media_type != "text/markdown"
            or self.evidence_context_artifact.schema_ref
            != "eom://schemas/knowledge/evidence-bundle-context/1.0"
        ):
            raise ValueError("Evidence Bundle material pointers are incompatible")
        item_management = [step for step in self.steps if step.role == "item_management"]
        if item_management and item_management[0].evidence_access != "NONE":
            raise ValueError("item management must not receive Evidence Bundle context")
        body = self.model_dump(mode="json", exclude={"plan_sha256"})
        if content_sha256(body) != self.plan_sha256:
            raise ValueError("knowledge-backed execution plan hash differs")
        return self


class ResolvedExecutionPlanV4(FrozenModel):
    """One document analysis plan with exact bounded Markdown materialization pointers."""

    schema_version: Literal["resolved-execution-plan/4.0"] = "resolved-execution-plan/4.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    workload_class: Literal["KNOWLEDGE_ANALYSIS"] = "KNOWLEDGE_ANALYSIS"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    workflow_definition_key: Literal["knowledge-analysis"] = "knowledge-analysis"
    workflow_definition_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    workflow_definition_sha256: Sha256
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    analysis_request_sha256: Sha256
    document_source: EducationalDocumentKnowledgeSourceV3
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    steps: tuple[ResolvedStepExecution, ...] = Field(min_length=1, max_length=1)
    resolver_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def one_document_support_step_and_exact_hash(self) -> ResolvedExecutionPlanV4:
        step = self.steps[0]
        if (
            step.step_key != "analyze"
            or step.role != WorkerRole.SUPPORT
            or step.worker_pool_key != "support"
        ):
            raise ValueError("document analysis plan requires the analyze support step")
        body = self.model_dump(mode="json", exclude={"plan_sha256"})
        if content_sha256(body) != self.plan_sha256:
            raise ValueError("document analysis plan hash does not match canonical content")
        return self


class ResolvedExecutionPlanV5(ResolvedExecutionPlanV4):
    """Multimodal document analysis plan with mandatory page-image pointers."""

    schema_version: Literal["resolved-execution-plan/5.0"] = "resolved-execution-plan/5.0"  # type: ignore[assignment]
    document_source: EducationalDocumentKnowledgeSourceV4  # type: ignore[assignment]


class ResolvedExecutionPlanV6(FrozenModel):
    """One exact legacy item extraction request and its closed local materializations."""

    schema_version: Literal["resolved-execution-plan/6.0"] = "resolved-execution-plan/6.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    workload_class: Literal["KNOWLEDGE_ANALYSIS"] = "KNOWLEDGE_ANALYSIS"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    workflow_definition_key: Literal["legacy-item-extraction"] = "legacy-item-extraction"
    workflow_definition_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    workflow_definition_sha256: Sha256
    extraction_request: LegacyItemExtractionRequest
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    steps: tuple[ResolvedStepExecution, ...] = Field(min_length=1, max_length=1)
    resolver_version: Literal["6.0.0"] = "6.0.0"
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def one_extraction_support_step_and_exact_hash(self) -> ResolvedExecutionPlanV6:
        step = self.steps[0]
        if (
            step.step_key != "extract"
            or step.role != WorkerRole.SUPPORT
            or step.worker_pool_key != "legacy-extraction"
            or step.reference_bundle is not None
        ):
            raise ValueError("legacy item extraction plan requires its isolated support step")
        if (
            self.preset_id,
            self.preset_revision_id,
            self.preset_sha256,
        ) != (
            self.extraction_request.execution_preset_id,
            self.extraction_request.execution_preset_revision_id,
            self.extraction_request.execution_preset_sha256,
        ):
            raise ValueError("legacy item extraction preset differs from its request")
        body = self.model_dump(mode="json", exclude={"plan_sha256"})
        if content_sha256(body) != self.plan_sha256:
            raise ValueError("legacy item extraction plan hash does not match canonical content")
        return self


class ResolvedExecutionPlanV7(FrozenModel):
    """One exact approved Item and two immutable content-team authorities."""

    schema_version: Literal["resolved-execution-plan/7.0"] = "resolved-execution-plan/7.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    workflow_id: WorkflowId
    workload_class: Literal["KNOWLEDGE_ANALYSIS"] = "KNOWLEDGE_ANALYSIS"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    workflow_definition_key: Literal["legacy-item-editorial-compatibility"] = (
        "legacy-item-editorial-compatibility"
    )
    workflow_definition_version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )
    workflow_definition_sha256: Sha256
    compatibility_request: LegacyItemEditorialCompatibilityRequest
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    steps: tuple[ResolvedStepExecution, ...] = Field(min_length=1, max_length=1)
    resolver_version: Literal["7.0.0"] = "7.0.0"
    resolved_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def one_compatibility_support_step_and_exact_hash(self) -> ResolvedExecutionPlanV7:
        step = self.steps[0]
        if (
            step.step_key != "assess"
            or step.role != WorkerRole.SUPPORT
            or step.worker_pool_key != "support"
            or step.reference_bundle is not None
            or step.general_knowledge_mode != "DENIED"
        ):
            raise ValueError("editorial compatibility plan requires its source-only support step")
        body = self.model_dump(mode="json", exclude={"plan_sha256"})
        if content_sha256(body) != self.plan_sha256:
            raise ValueError("editorial compatibility plan hash does not match canonical content")
        return self


class CodexInvocation(FrozenModel):
    """Bounded job-local CLI selection derived from one resolved plan step."""

    schema_version: Literal["codex-invocation/1.0"] = "codex-invocation/1.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    step_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: ReasoningEffort
    invocation_sha256: Sha256

    @model_validator(mode="after")
    def exact_invocation_hash(self) -> CodexInvocation:
        body = self.model_dump(mode="json", exclude={"invocation_sha256"})
        if content_sha256(body) != self.invocation_sha256:
            raise ValueError("Codex invocation hash does not match its canonical content")
        return self


class CodexImageInput(FrozenModel):
    """One bounded, hash-pinned page image attached to a Codex invocation."""

    physical_page: int = Field(ge=1, le=100000)
    relative_path: str = Field(
        pattern=r"^source/document/images/page-[0-9]{6}\.png$", max_length=64
    )
    media_type: Literal["image/png"] = "image/png"
    sha256: Sha256
    bytes: int = Field(ge=1, le=16 * 1024 * 1024)
    width_pixels: int = Field(ge=1, le=10000)
    height_pixels: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def path_matches_physical_page(self) -> CodexImageInput:
        if self.relative_path != (f"source/document/images/page-{self.physical_page:06d}.png"):
            raise ValueError("Codex image-input path must match its physical page")
        return self


class CodexImageInputManifest(FrozenModel):
    """Exact ordered PNG set crossing the worker's multimodal input boundary."""

    schema_version: Literal["codex-image-input-manifest/1.0"] = "codex-image-input-manifest/1.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    images: tuple[CodexImageInput, ...] = Field(min_length=1, max_length=32)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_order_coverage_and_hash(self) -> CodexImageInputManifest:
        pages = tuple(image.physical_page for image in self.images)
        if pages != tuple(range(pages[0], pages[-1] + 1)):
            raise ValueError("Codex image inputs must be unique, contiguous, and ordered")
        body = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if content_sha256(body) != self.manifest_sha256:
            raise ValueError("Codex image-input manifest hash does not match canonical content")
        return self


class CodexAssessmentImageInput(FrozenModel):
    """One extraction image keyed by immutable page-input identity and source role."""

    page_input_id: str = Field(pattern=r"^assessmentpage_[0-9a-f]{32}$")
    source_role: Literal["PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"]
    physical_page: int = Field(ge=1, le=100000)
    relative_path: str = Field(
        pattern=r"^source/pages/assessmentpage_[0-9a-f]{32}\.png$", max_length=64
    )
    media_type: Literal["image/png"] = "image/png"
    sha256: Sha256
    bytes: int = Field(ge=1, le=16 * 1024 * 1024)
    width_pixels: int = Field(ge=1, le=20000)
    height_pixels: int = Field(ge=1, le=20000)

    @model_validator(mode="after")
    def path_matches_page_input(self) -> CodexAssessmentImageInput:
        if self.relative_path != f"source/pages/{self.page_input_id}.png":
            raise ValueError("assessment image-input path must match its page input ID")
        if self.width_pixels * self.height_pixels > 64_000_000:
            raise ValueError("assessment image input exceeds the decoded-pixel limit")
        return self


class CodexAssessmentImageInputManifest(FrozenModel):
    """Exact ordered assessment PNG set crossing the worker invocation boundary."""

    schema_version: Literal["codex-image-input-manifest/2.0"] = "codex-image-input-manifest/2.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    images: tuple[CodexAssessmentImageInput, ...] = Field(min_length=1, max_length=64)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_order_identity_and_hash(self) -> CodexAssessmentImageInputManifest:
        identities = tuple(image.page_input_id for image in self.images)
        source_positions = tuple((image.source_role, image.physical_page) for image in self.images)
        if len(identities) != len(set(identities)) or len(source_positions) != len(
            set(source_positions)
        ):
            raise ValueError("assessment image inputs must be unique and ordered by request")
        if sum(image.width_pixels * image.height_pixels for image in self.images) > 256_000_000:
            raise ValueError("assessment image inputs exceed the aggregate decoded-pixel limit")
        body = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if content_sha256(body) != self.manifest_sha256:
            raise ValueError("assessment image-input manifest hash differs")
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


class CodexAuthEnrollmentRequest(FrozenModel):
    """Credential-free request for one fixed-slot ChatGPT device login."""

    schema_version: Literal["codex-auth-enrollment-request/1.0"] = (
        "codex-auth-enrollment-request/1.0"
    )
    enrollment_id: str = Field(pattern=r"^authflow_[0-9a-f]{32}$")
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    expected_binding_resource_version: int = Field(ge=1)
    slot_key: str = Field(pattern=r"^slot0[1-5]$")
    requested_account_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    requested_by_api_session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    requested_at: UtcDatetime
    expires_at: UtcDatetime
    request_sha256: Sha256

    @field_validator("requested_account_label")
    @classmethod
    def safe_account_label(cls, value: str) -> str:
        if value != value.strip() or value != normalize("NFC", value):
            raise ValueError("account label must be trimmed NFC text")
        return value

    @model_validator(mode="after")
    def bounded_enrollment_window(self) -> CodexAuthEnrollmentRequest:
        duration = self.expires_at - self.requested_at
        if not timedelta(minutes=5) <= duration <= timedelta(minutes=15):
            raise ValueError("auth enrollment window must be between five and fifteen minutes")
        return self


class CodexAuthEnrollmentStatus(FrozenModel):
    """Durable sanitized enrollment projection; never contains a device code."""

    schema_version: Literal["codex-auth-enrollment-status/1.0"] = "codex-auth-enrollment-status/1.0"
    enrollment_id: str = Field(pattern=r"^authflow_[0-9a-f]{32}$")
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    slot_key: str = Field(pattern=r"^slot0[1-5]$")
    requested_account_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    state: Literal[
        "REQUESTED",
        "DRAINING",
        "READY_FOR_LOGIN",
        "WAITING_FOR_USER",
        "VERIFYING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "EXPIRED",
    ]
    challenge_available: bool
    challenge_revealed_at: UtcDatetime | None
    assignment_revision_id: str | None = Field(
        default=None, pattern=r"^authassignrev_[0-9a-f]{32}$"
    )
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    requested_at: UtcDatetime
    started_at: UtcDatetime | None
    expires_at: UtcDatetime
    completed_at: UtcDatetime | None
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def coherent_enrollment_projection(self) -> CodexAuthEnrollmentStatus:
        terminal = self.state in {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}
        failed = self.state in {"FAILED", "CANCELLED", "EXPIRED"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal enrollment state must match completion timestamp")
        if failed != (self.error_code is not None):
            raise ValueError("failed enrollment state must match stable error code")
        if (self.state == "SUCCEEDED") != (self.assignment_revision_id is not None):
            raise ValueError("only successful enrollment may identify an assignment revision")
        if self.challenge_available and self.state != "WAITING_FOR_USER":
            raise ValueError("device challenge is available only while waiting for the user")
        if self.challenge_available and self.challenge_revealed_at is not None:
            raise ValueError("revealed device challenge cannot remain available")
        if self.started_at is not None and self.started_at < self.requested_at:
            raise ValueError("enrollment cannot start before it was requested")
        if self.completed_at is not None and self.completed_at < self.requested_at:
            raise ValueError("enrollment cannot complete before it was requested")
        return self


class CodexDeviceChallenge(FrozenModel):
    """One-time ephemeral challenge; forbidden from durable persistence and logs."""

    schema_version: Literal["codex-device-challenge/1.0"] = "codex-device-challenge/1.0"
    enrollment_id: str = Field(pattern=r"^authflow_[0-9a-f]{32}$")
    slot_key: str = Field(pattern=r"^slot0[1-5]$")
    verification_uri: str = Field(max_length=512)
    user_code: str = Field(pattern=r"^[A-Z0-9]{3,12}(?:-[A-Z0-9]{3,12})?$")
    issued_at: UtcDatetime
    expires_at: UtcDatetime

    @field_validator("verification_uri")
    @classmethod
    def exact_openai_verification_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "auth.openai.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.fragment
        ):
            raise ValueError("device verification URI must use the reviewed OpenAI HTTPS origin")
        return value

    @model_validator(mode="after")
    def bounded_challenge_window(self) -> CodexDeviceChallenge:
        duration = self.expires_at - self.issued_at
        if not timedelta(seconds=30) <= duration <= timedelta(minutes=15):
            raise ValueError("device challenge window is outside the reviewed bound")
        return self


class CodexDeviceLoginStatus(FrozenModel):
    schema_version: Literal["codex-device-login-status/1.0"] = "codex-device-login-status/1.0"
    enrollment_id: str = Field(pattern=r"^authflow_[0-9a-f]{32}$")
    slot_key: str = Field(pattern=r"^slot0[1-5]$")
    state: Literal["STARTING", "WAITING_FOR_USER", "SUCCEEDED", "FAILED", "EXPIRED"]
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_login_status(self) -> CodexDeviceLoginStatus:
        failed = self.state in {"FAILED", "EXPIRED"}
        if failed != (self.reason_code is not None):
            raise ValueError("failed login status must match stable reason code")
        return self


class CodexAuthBrokerRequest(FrozenModel):
    schema_version: Literal["codex-auth-broker-request/1.0"] = "codex-auth-broker-request/1.0"
    action: Literal["STATUS", "REVEAL"]
    enrollment_id: str = Field(pattern=r"^authflow_[0-9a-f]{32}$")
    slot_key: str = Field(pattern=r"^slot0[1-5]$")


class CodexAuthBrokerResponse(FrozenModel):
    schema_version: Literal["codex-auth-broker-response/1.0"] = "codex-auth-broker-response/1.0"
    outcome: Literal["OK", "FAILED"]
    status: CodexDeviceLoginStatus | None
    challenge: CodexDeviceChallenge | None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def coherent_broker_response(self) -> CodexAuthBrokerResponse:
        success = self.outcome == "OK"
        if success != (self.status is not None):
            raise ValueError("successful broker response requires sanitized status")
        if success != (self.error_code is None):
            raise ValueError("failed broker response requires stable error code")
        if self.challenge is not None and (
            self.status is None
            or self.status.state != "WAITING_FOR_USER"
            or self.challenge.enrollment_id != self.status.enrollment_id
            or self.challenge.slot_key != self.status.slot_key
        ):
            raise ValueError("device challenge does not match waiting broker status")
        return self


class CodexAuthEnrollmentRequestV2(CodexAuthEnrollmentRequest):
    """Additive enrollment request for the six-slot inventory."""

    schema_version: Literal["codex-auth-enrollment-request/1.1"] = (
        "codex-auth-enrollment-request/1.1"  # type: ignore[assignment]
    )
    slot_key: str = Field(pattern=r"^slot0[1-6]$")


class CodexAuthEnrollmentStatusV2(CodexAuthEnrollmentStatus):
    schema_version: Literal["codex-auth-enrollment-status/1.1"] = "codex-auth-enrollment-status/1.1"  # type: ignore[assignment]
    slot_key: str = Field(pattern=r"^slot0[1-6]$")


class CodexDeviceChallengeV2(CodexDeviceChallenge):
    schema_version: Literal["codex-device-challenge/1.1"] = "codex-device-challenge/1.1"  # type: ignore[assignment]
    slot_key: str = Field(pattern=r"^slot0[1-6]$")


class CodexDeviceLoginStatusV2(CodexDeviceLoginStatus):
    schema_version: Literal["codex-device-login-status/1.1"] = "codex-device-login-status/1.1"  # type: ignore[assignment]
    slot_key: str = Field(pattern=r"^slot0[1-6]$")


class CodexAuthBrokerRequestV2(CodexAuthBrokerRequest):
    schema_version: Literal["codex-auth-broker-request/1.1"] = "codex-auth-broker-request/1.1"  # type: ignore[assignment]
    slot_key: str = Field(pattern=r"^slot0[1-6]$")


class CodexAuthBrokerResponseV2(FrozenModel):
    schema_version: Literal["codex-auth-broker-response/1.1"] = "codex-auth-broker-response/1.1"
    outcome: Literal["OK", "FAILED"]
    status: CodexDeviceLoginStatusV2 | None
    challenge: CodexDeviceChallengeV2 | None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def coherent_broker_response(self) -> CodexAuthBrokerResponseV2:
        success = self.outcome == "OK"
        if success != (self.status is not None):
            raise ValueError("successful broker response requires sanitized status")
        if success != (self.error_code is None):
            raise ValueError("failed broker response requires stable error code")
        if self.challenge is not None and (
            self.status is None
            or self.status.state != "WAITING_FOR_USER"
            or self.challenge.enrollment_id != self.status.enrollment_id
            or self.challenge.slot_key != self.status.slot_key
        ):
            raise ValueError("device challenge does not match waiting broker status")
        return self


class CodexControlCommand(FrozenModel):
    """Credential-free command consumed only by the orchestrator-owned runner."""

    schema_version: Literal["codex-control-command/1.0"] = "codex-control-command/1.0"
    command_id: str = Field(pattern=r"^codexcmd_[0-9a-f]{32}$")
    command_type: Literal["OBSERVE", "ENABLE", "DRAIN", "DISABLE"]
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    expected_resource_version: int = Field(ge=1)
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    requested_at: UtcDatetime
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    request_sha256: Sha256

    @model_validator(mode="after")
    def bounded_reason(self) -> CodexControlCommand:
        operational = self.command_type in {"DRAIN", "DISABLE"}
        if operational != (self.reason_code is not None):
            raise ValueError("drain/disable require a reason and observe/enable forbid one")
        return self


class CodexControlCommandResult(FrozenModel):
    """Sanitized terminal result; never contains authentication output or credentials."""

    schema_version: Literal["codex-control-command-result/1.0"] = "codex-control-command-result/1.0"
    command_id: str = Field(pattern=r"^codexcmd_[0-9a-f]{32}$")
    command_type: Literal["OBSERVE", "ENABLE", "DRAIN", "DISABLE"]
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    outcome: Literal["SUCCEEDED", "FAILED"]
    result_resource_version: int | None = Field(default=None, ge=1)
    binding_state: (
        Literal["READY", "STALE", "AUTH_REQUIRED", "DEGRADED", "DRAINING", "DISABLED"] | None
    )
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    processed_at: UtcDatetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def coherent_result(self) -> CodexControlCommandResult:
        success = self.outcome == "SUCCEEDED"
        if success and (self.result_resource_version is None or self.binding_state is None):
            raise ValueError("successful control command requires resulting binding state")
        if success != (self.reason_code is None):
            raise ValueError("failed control command requires a reason and success forbids one")
        if not success and (
            self.result_resource_version is not None or self.binding_state is not None
        ):
            raise ValueError("failed control command cannot claim a resulting binding state")
        return self


class ExecutionPresetEvaluationReport(FrozenModel):
    """Bounded report metadata; detailed evidence remains an Artifact Revision."""

    schema_version: Literal["execution-preset-evaluation-report/1.0"] = (
        "execution-preset-evaluation-report/1.0"
    )
    evaluated_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    evaluated_policy_sha256: Sha256
    scope: Literal["STATIC", "NON_LIVE", "LIVE_ONE_SHOT"]
    outcome: Literal["PASS", "FAIL"]
    summary_code: Literal["CONTRACT_VALIDATION", "FAKE_ADAPTER_ACCEPTANCE", "LIVE_ITEM_ACCEPTANCE"]
    cases_total: int = Field(ge=1, le=10000)
    cases_passed: int = Field(ge=0, le=10000)
    quality_score_permille: int | None = Field(default=None, ge=0, le=1000)
    completed_at: UtcDatetime
    report_sha256: Sha256

    @model_validator(mode="after")
    def coherent_evaluation(self) -> ExecutionPresetEvaluationReport:
        if self.cases_passed > self.cases_total:
            raise ValueError("passed evaluation cases cannot exceed total cases")
        if (self.outcome == "PASS") != (self.cases_passed == self.cases_total):
            raise ValueError("PASS requires every evaluation case to pass")
        if self.scope == "STATIC" and self.quality_score_permille is not None:
            raise ValueError("static contract validation cannot claim a quality score")
        if self.scope == "LIVE_ONE_SHOT" and self.summary_code != "LIVE_ITEM_ACCEPTANCE":
            raise ValueError("live evaluation requires the live acceptance summary")
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


class WorkerCapacityPoolV2(FrozenModel):
    """Pool contract for the six-slot fixed-host inventory."""

    pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    roles: tuple[WorkerRole, ...] = Field(min_length=1, max_length=5)
    slot_keys: tuple[SlotKey, ...] = Field(min_length=1, max_length=6)
    max_active: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def bounded_unique_pool(self) -> WorkerCapacityPoolV2:
        if len(self.roles) != len(set(self.roles)) or len(self.slot_keys) != len(
            set(self.slot_keys)
        ):
            raise ValueError("capacity pool roles and slots must be unique")
        if self.max_active > len(self.slot_keys):
            raise ValueError("capacity pool cannot activate more workers than configured slots")
        if any(
            slot_key not in {f"slot{index:02d}" for index in range(1, 7)}
            for slot_key in self.slot_keys
        ):
            raise ValueError("capacity V2 pool references an unsupported fixed slot")
        return self


class WorkerCapacityPolicyV2(FrozenModel):
    """Additive fixed-host capacity revision with two support workers."""

    schema_version: Literal["worker-capacity-policy/1.1"] = "worker-capacity-policy/1.1"
    capacity_policy_id: str = Field(pattern=r"^capacity_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    revision_number: Literal[2] = 2
    state: RevisionState
    max_configured_slots: Literal[6] = 6
    max_active_codex: Literal[3] = 3
    max_active_per_slot: Literal[1] = 1
    max_active_gpu: Literal[1] = 1
    max_active_knowledge_analysis: Literal[2] = 2
    pools: tuple[WorkerCapacityPoolV2, ...] = Field(min_length=5, max_length=5)
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_capacity_limits(self) -> WorkerCapacityPolicyV2:
        pool_keys = [pool.pool_key for pool in self.pools]
        if len(pool_keys) != len(set(pool_keys)):
            raise ValueError("capacity pool keys must be unique")
        all_slots = {slot for pool in self.pools for slot in pool.slot_keys}
        if len(all_slots) > self.max_configured_slots:
            raise ValueError("capacity pools reference too many configured slots")
        if any(pool.max_active > self.max_active_codex for pool in self.pools):
            raise ValueError("pool active limit cannot exceed global active limit")
        reviewed = {
            "authoring": (("authoring",), ("slot01",), 1),
            "review": (("review",), ("slot02",), 1),
            "image": (("image",), ("slot03",), 1),
            "item-management": (("item_management",), ("slot04",), 1),
            "support": (("support",), ("slot05", "slot06"), 2),
        }
        actual = {
            pool.pool_key: (pool.roles, pool.slot_keys, pool.max_active) for pool in self.pools
        }
        if actual != reviewed:
            raise ValueError("capacity V2 differs from the reviewed fixed-host pools")
        return self


class WorkerCapacityPolicyV3(FrozenModel):
    """Six-slot policy isolating textbook analysis from legacy item extraction."""

    schema_version: Literal["worker-capacity-policy/1.2"] = "worker-capacity-policy/1.2"
    capacity_policy_id: str = Field(pattern=r"^capacity_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    revision_number: Literal[3] = 3
    state: RevisionState
    max_configured_slots: Literal[6] = 6
    max_active_codex: Literal[3] = 3
    max_active_per_slot: Literal[1] = 1
    max_active_gpu: Literal[1] = 1
    max_active_knowledge_analysis: Literal[2] = 2
    pools: tuple[WorkerCapacityPoolV2, ...] = Field(min_length=6, max_length=6)
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_isolated_capacity(self) -> WorkerCapacityPolicyV3:
        actual = {
            pool.pool_key: (pool.roles, pool.slot_keys, pool.max_active) for pool in self.pools
        }
        reviewed = {
            "authoring": (("authoring",), ("slot01",), 1),
            "review": (("review",), ("slot02",), 1),
            "image": (("image",), ("slot03",), 1),
            "item-management": (("item_management",), ("slot04",), 1),
            "support": (("support",), ("slot05",), 1),
            "legacy-extraction": (("support",), ("slot06",), 1),
        }
        if actual != reviewed or len(actual) != len(self.pools):
            raise ValueError("capacity V3 differs from the reviewed isolated pools")
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
