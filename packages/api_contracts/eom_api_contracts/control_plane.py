"""Bounded Application API contracts for the Codex execution control plane."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_catalog_contracts import EvidenceBudget, KnowledgeSourceClass
from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, OpaqueId, Sha256, UtcDatetime


class ControlArtifactPointerInput(ApiModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: Sha256
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    logical_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class BundleRevisionPointerInput(ApiModel):
    bundle_id: str = Field(pattern=r"^(?:instrbundle|refbundle)_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^(?:instrrev|refrev)_[0-9a-f]{32}$")
    manifest_artifact: ControlArtifactPointerInput
    manifest_sha256: Sha256


class ModelCandidateInput(ApiModel):
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"]


class PresetRolePolicyInput(ApiModel):
    role: Literal["authoring", "image", "review", "item_management", "support"]
    model_candidates: tuple[ModelCandidateInput, ...] = Field(min_length=1, max_length=4)
    instruction_bundle: BundleRevisionPointerInput
    reference_bundle: BundleRevisionPointerInput | None
    worker_pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    timeout_seconds: int = Field(ge=30, le=7200)
    sandbox: Literal["read-only"] = "read-only"
    network: Literal["disabled"] = "disabled"
    evidence_access: Literal["NONE", "EVIDENCE_CONTEXT"] | None = None


class PresetRetrievalPolicyInput(ApiModel):
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
    def deterministic_policy(self) -> PresetRetrievalPolicyInput:
        for values in (
            self.allowed_corpus_keys,
            self.allowed_query_kinds,
            self.allowed_source_classes,
        ):
            if tuple(sorted(values)) != values or len(values) != len(set(values)):
                raise ValueError("retrieval policy collections must be sorted and unique")
        return self


class CreateExecutionPresetDraftRequest(ApiModel):
    schema_version: Literal["execution-preset-revision/1.0", "execution-preset-revision/2.0"] = (
        "execution-preset-revision/1.0"
    )
    preset_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    role_policies: tuple[PresetRolePolicyInput, ...] = Field(min_length=1, max_length=5)
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    general_knowledge_policy: Literal["DENY", "ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[str, ...] = Field(min_length=1, max_length=16)
    retrieval_policy: PresetRetrievalPolicyInput | None = None

    @model_validator(mode="after")
    def exact_schema_family(self) -> CreateExecutionPresetDraftRequest:
        is_v2 = self.schema_version == "execution-preset-revision/2.0"
        if is_v2 != (self.retrieval_policy is not None):
            raise ValueError("V2 preset drafts require exactly one retrieval policy")
        evidence_values = [policy.evidence_access for policy in self.role_policies]
        if is_v2 and any(value is None for value in evidence_values):
            raise ValueError("V2 preset roles require explicit evidence access")
        if not is_v2 and any(value is not None for value in evidence_values):
            raise ValueError("V1 preset roles cannot declare evidence access")
        return self


class CodexAccountCommandRequest(ApiModel):
    command_type: Literal["OBSERVE", "ENABLE", "DRAIN", "DISABLE"]
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def coherent_reason(self) -> CodexAccountCommandRequest:
        operational = self.command_type in {"DRAIN", "DISABLE"}
        if operational != (self.reason_code is not None):
            raise ValueError("drain/disable require a reason and observe/enable forbid one")
        return self


class CodexCapabilityView(ApiModel):
    model: str
    reasoning_effort: str
    state: str


class CodexAccountView(ApiModel):
    binding_id: OpaqueId
    slot_key: str
    account_label: str
    state: str
    reason_code: str | None
    codex_cli_version: str | None
    observed_at: UtcDatetime | None
    valid_until: UtcDatetime | None
    resource_version: int = Field(ge=1)
    capabilities: tuple[CodexCapabilityView, ...]
    active_lease_count: int = Field(ge=0)
    last_successful_job_id: OpaqueId | None


class CodexControlCommandView(ApiModel):
    command_id: OpaqueId
    command_type: str
    binding_id: OpaqueId
    state: str
    attempts: int = Field(ge=0, le=3)
    result_resource_version: int | None
    error_code: str | None
    requested_at: UtcDatetime
    processed_at: UtcDatetime | None


class ExecutionPresetEvaluationView(ApiModel):
    evaluation_id: OpaqueId
    evaluated_preset_revision_id: OpaqueId
    evaluated_policy_sha256: Sha256
    scope: str
    outcome: str
    summary_code: str
    cases_total: int = Field(ge=1)
    cases_passed: int = Field(ge=0)
    quality_score_permille: int | None = Field(default=None, ge=0, le=1000)
    report_artifact_id: OpaqueId
    report_artifact_revision_id: OpaqueId
    report_content_sha256: Sha256
    completed_at: UtcDatetime


class ExecutionPresetRevisionView(ApiModel):
    schema_version: str
    preset_revision_id: OpaqueId
    preset_id: OpaqueId
    revision_number: int = Field(ge=1)
    state: str
    display_name: str
    description: str
    capacity_policy_revision_id: OpaqueId
    general_knowledge_policy: str
    compatible_workflow_protocols: tuple[str, ...]
    content_sha256: Sha256
    created_at: UtcDatetime
    role_policies: tuple[PresetRolePolicyInput, ...]
    retrieval_policy: PresetRetrievalPolicyInput | None = None
    evaluations: tuple[ExecutionPresetEvaluationView, ...]


class ExecutionPresetView(ApiModel):
    preset_id: OpaqueId
    preset_key: str
    current_revision_id: OpaqueId | None
    state: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    revisions: tuple[ExecutionPresetRevisionView, ...]
