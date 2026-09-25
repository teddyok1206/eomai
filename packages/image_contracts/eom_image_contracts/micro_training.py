"""Evaluation-only contracts for one bounded local-image LoRA micro probe."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    ImageEvaluationSourceSnapshot,
    LocalImageModelPointer,
    Sha256,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.training import (
    LocalImageLoraAdapterFile,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainerDependencies,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCropProposalSet,
)

MICRO_PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-lora-micro-probe-plan/1.0"
MICRO_ADAPTER_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-lora-micro-adapter-manifest/1.0"
)
AUTHORIZATION_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-authorization/1.0"
CROP_PROPOSAL_SET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-training-crop-proposal-set/1.0"
)
EVALUATION_PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _require_pointer(
    pointer: ImageEvaluationArtifactMember,
    *,
    schema_ref: str,
    member_path: str,
) -> None:
    if (
        pointer.schema_ref != schema_ref
        or pointer.media_type != "application/json"
        or pointer.member_path != member_path
    ):
        raise ValueError("artifact pointer contract mismatch")


class LocalImageLoraMicroSelection(FrozenModel):
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    crop_proposal_id: str = Field(pattern=r"^imgcropproposal_[0-9a-f]{32}$")
    caption_en: str = Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    )
    caption_sha256: Sha256

    @model_validator(mode="after")
    def caption_is_coherent(self) -> LocalImageLoraMicroSelection:
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("micro-probe caption hash mismatch")
        return self


class LocalImageLoraMicroHyperparameters(FrozenModel):
    adapter_type: Literal["UNET_LORA"]
    rank: Literal[8]
    alpha: Literal[8]
    resolution_width: Literal[768]
    resolution_height: Literal[512]
    train_batch_size: Literal[1]
    gradient_accumulation_steps: Literal[4]
    gradient_checkpointing: Literal[True]
    mixed_precision: Literal["fp16"]
    optimizer: Literal["adamw_8bit"]
    learning_rate: Literal["1e-4"]
    max_train_steps: Literal[200]
    checkpointing_steps: Literal[200]
    random_flip: Literal[False]
    train_text_encoders: Literal[False]
    train_vae: Literal[False]


class LocalImageLoraMicroProbePlan(FrozenModel):
    schema_version: Literal["local-image-lora-micro-probe-plan/1.0"]
    probe_id: str = Field(pattern=r"^imgmicroprobe_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    training_authorization: ImageEvaluationArtifactMember
    crop_proposal_set: ImageEvaluationArtifactMember
    crop_proposal_set_sha256: Sha256
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    base_model: LocalImageModelPointer
    preprocessing_revision: Literal["local-image-micro-crop-preprocess/1.0"]
    selections: tuple[LocalImageLoraMicroSelection, ...] = Field(min_length=12, max_length=18)
    trainer_contract: Literal["eom-local-image-lora-micro-trainer/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LocalImageLoraMicroHyperparameters
    seed: int = Field(ge=0, le=2**32 - 1)
    purpose: Literal["EVALUATION_ONLY_MICRO_PROBE"]
    activation_policy: Literal["FORBIDDEN"]
    authorized_at: datetime
    authorized_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    authorization_reference_sha256: Sha256
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    plan_sha256: Sha256

    @field_validator("authorized_at", "created_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("holdout_sample_ids")
    @classmethod
    def valid_holdout_samples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"imgsample_[0-9a-f]{32}", item) is None for item in value):
            raise ValueError("invalid holdout sample identity")
        return value

    @field_validator("holdout_source_anchor_ids")
    @classmethod
    def valid_holdout_anchors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"assessmentanchor_[0-9a-f]{32}", item) is None for item in value):
            raise ValueError("invalid holdout source-anchor identity")
        return value

    @model_validator(mode="after")
    def immutable_plan_is_coherent(self) -> LocalImageLoraMicroProbePlan:
        _require_pointer(
            self.training_authorization,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            member_path="manifests/training-authorization.json",
        )
        _require_pointer(
            self.crop_proposal_set,
            schema_ref=CROP_PROPOSAL_SET_SCHEMA_REF,
            member_path="manifests/crop-proposals.json",
        )
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        if self.authorized_at > self.created_at:
            raise ValueError("micro-probe authorization occurs after plan creation")
        for values, label in (
            (self.holdout_sample_ids, "holdout samples"),
            (self.holdout_source_anchor_ids, "holdout source anchors"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"micro-probe {label} must be sorted and unique")
        proposal_ids = tuple(value.crop_proposal_id for value in self.selections)
        anchors = tuple(value.source_anchor_id for value in self.selections)
        if proposal_ids != tuple(sorted(set(proposal_ids))):
            raise ValueError("micro-probe selections must be sorted by unique proposal ID")
        if len(anchors) != len(set(anchors)):
            raise ValueError("micro-probe selections must use unique source anchors")
        if set(anchors) & set(self.holdout_source_anchor_ids):
            raise ValueError("micro-probe selection contains a holdout source anchor")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"probe_id", "plan_sha256"})
        ).removeprefix("sha256:")
        if self.probe_id != "imgmicroprobe_" + identity[:32]:
            raise ValueError("micro-probe ID does not bind its plan inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("micro-probe plan hash mismatch")
        return self


class LocalImageLoraMicroProbeCommand(FrozenModel):
    schema_version: Literal["local-image-lora-micro-probe-command/1.0"]
    training_run_id: str = Field(pattern=r"^imgmicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    probe_plan: LocalImageLoraMicroProbePlan
    attempt: Literal[1]
    staged_plan_member: Literal["inputs/micro-probe-plan.json"]
    staged_authorization_member: Literal["inputs/training-authorization.json"]
    staged_proposal_set_member: Literal["inputs/crop-proposals.json"]
    staged_pages_root: Literal["inputs/pages"]
    runtime_dataset_root: Literal["runtime-dataset"]
    output_root_member: Literal["outputs"]
    checkpoint_root_member: Literal["checkpoints"]
    timeout_seconds: int = Field(ge=600, le=14_400)
    command_sha256: Sha256

    @property
    def training_plan(self) -> LocalImageLoraMicroProbePlan:
        """Present the shared trainer backend with its immutable plan view."""

        return self.probe_plan

    @property
    def training_plan_sha256(self) -> Sha256:
        """Present the shared trainer backend with its immutable plan hash."""

        return self.probe_plan_sha256

    @model_validator(mode="after")
    def command_is_coherent(self) -> LocalImageLoraMicroProbeCommand:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=MICRO_PLAN_SCHEMA_REF,
            member_path="manifests/micro-probe-plan.json",
        )
        if self.probe_plan_sha256 != self.probe_plan.plan_sha256:
            raise ValueError("micro-probe command plan hash mismatch")
        identity = content_sha256(
            {
                "probe_plan_pointer": self.probe_plan_pointer.model_dump(mode="json"),
                "probe_plan_sha256": self.probe_plan_sha256,
                "attempt": self.attempt,
            }
        ).removeprefix("sha256:")
        if self.training_run_id != "imgmicrotrainrun_" + identity[:32]:
            raise ValueError("micro-probe training run ID does not bind the command")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("micro-probe command hash mismatch")
        return self


class LocalImageLoraMicroRealizedSample(FrozenModel):
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    crop_proposal_id: str = Field(pattern=r"^imgcropproposal_[0-9a-f]{32}$")
    training_sample_id: str = Field(pattern=r"^imgtrainsample_[0-9a-f]{32}$")
    crop_sha256: Sha256
    caption_sha256: Sha256
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")


class LocalImageLoraMicroAdapterManifest(FrozenModel):
    schema_version: Literal["local-image-lora-micro-adapter-manifest/1.0"]
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    base_model: LocalImageModelPointer
    probe_plan: ImageEvaluationArtifactMember
    sample_set_sha256: Sha256
    files: tuple[LocalImageLoraAdapterFile, ...] = Field(min_length=2, max_length=2)
    created_at: datetime
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_adapter_is_coherent(self) -> LocalImageLoraMicroAdapterManifest:
        _require_pointer(
            self.probe_plan,
            schema_ref=MICRO_PLAN_SCHEMA_REF,
            member_path="manifests/micro-probe-plan.json",
        )
        paths = tuple(value.relative_path for value in self.files)
        if paths != ("adapter_config.json", "adapter_model.safetensors"):
            raise ValueError("micro-probe adapter files must be exact and sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("micro-probe adapter manifest hash mismatch")
        return self


class LocalImageLoraMicroProbeWorkerResult(FrozenModel):
    schema_version: Literal["local-image-lora-micro-probe-worker-result/1.0"]
    training_run_id: str = Field(pattern=r"^imgmicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    command_sha256: Sha256
    attempt: Literal[1]
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    adapter_manifest: LocalImageLoraMicroAdapterManifest | None
    realized_samples: tuple[LocalImageLoraMicroRealizedSample, ...] = Field(max_length=18)
    sample_set_sha256: Sha256 | None
    error_code: str | None = Field(pattern=r"^IMAGE_TRAINING_[A-Z0-9_]{3,96}$")
    runtime: LocalImageLoraTrainingRuntime | None
    completed_steps: int = Field(ge=0, le=200)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def terminal_result_is_coherent(self) -> LocalImageLoraMicroProbeWorkerResult:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=MICRO_PLAN_SCHEMA_REF,
            member_path="manifests/micro-probe-plan.json",
        )
        if self.completed_at < self.started_at:
            raise ValueError("micro-probe completion precedes start")
        if self.status == "SUCCEEDED":
            if (
                self.adapter_manifest is None
                or self.error_code is not None
                or self.runtime is None
                or self.sample_set_sha256 is None
                or self.completed_steps != 200
                or self.final_loss is None
                or len(self.realized_samples) < 12
            ):
                raise ValueError("successful micro-probe result is incomplete")
            sample_ids = tuple(value.training_sample_id for value in self.realized_samples)
            proposal_ids = tuple(value.crop_proposal_id for value in self.realized_samples)
            anchors = tuple(value.source_anchor_id for value in self.realized_samples)
            crop_hashes = tuple(value.crop_sha256 for value in self.realized_samples)
            if sample_ids != tuple(sorted(set(sample_ids))):
                raise ValueError("realized micro samples must be sorted and unique")
            if len(proposal_ids) != len(set(proposal_ids)) or len(anchors) != len(set(anchors)):
                raise ValueError("realized micro samples contain duplicate sources")
            if len(crop_hashes) != len(set(crop_hashes)):
                raise ValueError("realized micro samples contain duplicate crop bytes")
            expected_set = content_sha256(
                [value.model_dump(mode="json") for value in self.realized_samples]
            )
            if self.sample_set_sha256 != expected_set:
                raise ValueError("realized micro sample-set hash mismatch")
            if self.adapter_manifest.sample_set_sha256 != self.sample_set_sha256:
                raise ValueError("micro adapter does not bind its realized samples")
        elif self.adapter_manifest is not None or self.error_code is None:
            raise ValueError("failed micro-probe result requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("micro-probe result hash mismatch")
        return self


class LocalImageLoraMicroEvaluationCase(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsample_[0-9a-f]{32}$")
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    positive_prompt: str = Field(min_length=1, max_length=4000)
    positive_prompt_sha256: Sha256
    negative_prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt_sha256: Sha256
    seed: int = Field(ge=0, le=2**32 - 1)

    @field_validator("positive_prompt", "negative_prompt")
    @classmethod
    def prompt_is_bounded_text(cls, value: str) -> str:
        if value != value.strip() or value != unicodedata.normalize("NFC", value):
            raise ValueError("micro evaluation prompt must be trimmed NFC text")
        if any(
            character not in {"\n", "\t"} and unicodedata.category(character).startswith("C")
            for character in value
        ):
            raise ValueError("micro evaluation prompt contains a control character")
        return value

    @model_validator(mode="after")
    def prompt_hashes_match(self) -> LocalImageLoraMicroEvaluationCase:
        if self.positive_prompt_sha256 != text_sha256(
            self.positive_prompt
        ) or self.negative_prompt_sha256 != text_sha256(self.negative_prompt):
            raise ValueError("micro evaluation prompt hash mismatch")
        return self


class LocalImageLoraMicroEvaluationCommand(FrozenModel):
    schema_version: Literal["local-image-lora-micro-evaluation-command/1.0"]
    evaluation_run_id: str = Field(pattern=r"^imgmicroevalrun_[0-9a-f]{32}$")
    training_run_id: str = Field(pattern=r"^imgmicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    training_result_sha256: Sha256
    adapter_manifest: LocalImageLoraMicroAdapterManifest
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_plan_sha256: Sha256
    cases: tuple[LocalImageLoraMicroEvaluationCase, ...] = Field(min_length=3, max_length=3)
    inference_steps: Literal[20]
    guidance_scale: float = Field(ge=7.5, le=7.5)
    generation_width: Literal[800]
    generation_height: Literal[504]
    delivery_width: Literal[800]
    delivery_height: Literal[500]
    staged_adapter_root: Literal["inputs/adapter"]
    output_root_member: Literal["outputs"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    timeout_seconds: int = Field(ge=600, le=3600)
    command_sha256: Sha256

    @model_validator(mode="after")
    def command_is_coherent(self) -> LocalImageLoraMicroEvaluationCommand:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=MICRO_PLAN_SCHEMA_REF,
            member_path="manifests/micro-probe-plan.json",
        )
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        if (
            self.adapter_manifest.probe_plan != self.probe_plan_pointer
            or self.holdout_plan_sha256 != self.holdout_evaluation_plan.sha256
            or self.adapter_manifest.base_model.provider_family != "diffusers-ssd-1b"
            or self.adapter_manifest.state != "EVALUATION_ONLY"
            or self.adapter_manifest.activation_policy != "FORBIDDEN"
        ):
            raise ValueError("micro evaluation adapter binding mismatch")
        case_ids = tuple(value.sample_id for value in self.cases)
        anchors = tuple(value.source_anchor_id for value in self.cases)
        if case_ids != tuple(sorted(set(case_ids))) or len(anchors) != len(set(anchors)):
            raise ValueError("micro evaluation cases must be sorted and unique")
        identity_body = self.model_dump(
            mode="json", exclude={"evaluation_run_id", "command_sha256"}
        )
        identity = content_sha256(identity_body).removeprefix("sha256:")
        if self.evaluation_run_id != "imgmicroevalrun_" + identity[:32]:
            raise ValueError("micro evaluation run ID does not bind command inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("micro evaluation command hash mismatch")
        return self


class LocalImageLoraMicroEvaluationOutput(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsample_[0-9a-f]{32}$")
    variant: Literal["ADAPTER", "BASE"]
    member_path: str = Field(pattern=r"^outputs/imgsample_[0-9a-f]{32}-(adapter|base)\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=64, le=64 * 1024 * 1024)
    width_px: Literal[800]
    height_px: Literal[500]

    @model_validator(mode="after")
    def member_path_matches_identity(self) -> LocalImageLoraMicroEvaluationOutput:
        suffix = self.variant.lower()
        if self.member_path != f"outputs/{self.sample_id}-{suffix}.png":
            raise ValueError("micro evaluation output path mismatch")
        return self


class LocalImageLoraMicroEvaluationResult(FrozenModel):
    schema_version: Literal["local-image-lora-micro-evaluation-result/1.0"]
    evaluation_run_id: str = Field(pattern=r"^imgmicroevalrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    training_result_sha256: Sha256
    adapter_manifest_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    outputs: tuple[LocalImageLoraMicroEvaluationOutput, ...] = Field(max_length=6)
    error_code: str | None = Field(pattern=r"^IMAGE_EVALUATION_[A-Z0-9_]{3,96}$")
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def result_is_coherent(self) -> LocalImageLoraMicroEvaluationResult:
        if self.completed_at < self.started_at:
            raise ValueError("micro evaluation completion precedes start")
        keys = tuple((value.sample_id, value.variant) for value in self.outputs)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("micro evaluation outputs must be sorted and unique")
        if self.status == "SUCCEEDED":
            if len(self.outputs) != 6 or self.error_code is not None:
                raise ValueError("successful micro evaluation is incomplete")
        elif self.error_code is None:
            raise ValueError("failed micro evaluation requires an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("micro evaluation result hash mismatch")
        return self


def validate_micro_evaluation_result(
    command: LocalImageLoraMicroEvaluationCommand,
    result: LocalImageLoraMicroEvaluationResult,
) -> None:
    """Bind one terminal evaluation result to the exact three planned prompt pairs."""

    if (
        result.evaluation_run_id != command.evaluation_run_id
        or result.command_sha256 != command.command_sha256
        or result.training_result_sha256 != command.training_result_sha256
        or result.adapter_manifest_sha256 != command.adapter_manifest.manifest_sha256
    ):
        raise ValueError("micro evaluation result command binding mismatch")
    expected = {
        (case.sample_id, variant) for case in command.cases for variant in ("ADAPTER", "BASE")
    }
    actual = {(value.sample_id, value.variant) for value in result.outputs}
    if result.status == "SUCCEEDED" and actual != expected:
        raise ValueError("micro evaluation result lacks exact paired coverage")
    if not actual.issubset(expected):
        raise ValueError("micro evaluation result contains an unplanned output")


def validate_micro_probe_plan_sources(
    plan: LocalImageLoraMicroProbePlan,
    proposal_set: LocalImageTrainingCropProposalSet,
    authorization: LocalImageTrainingAuthorization,
) -> None:
    """Bind every micro selection to the exact proposal and approved rights set."""

    if (
        plan.source_snapshot != authorization.source_snapshot
        or plan.source_snapshot != proposal_set.source_snapshot
        or proposal_set.training_authorization != plan.training_authorization
        or proposal_set.holdout_evaluation_plan != plan.holdout_evaluation_plan
        or proposal_set.holdout_sample_ids != plan.holdout_sample_ids
        or proposal_set.holdout_source_anchor_ids != plan.holdout_source_anchor_ids
        or proposal_set.proposal_set_sha256 != plan.crop_proposal_set_sha256
        or plan.crop_proposal_set.sha256 != content_sha256(proposal_set.model_dump(mode="json"))
    ):
        raise ValueError("micro-probe plan source pins do not match")
    proposals = {value.crop_proposal_id: value for value in proposal_set.proposals}
    rights = {value.rights_policy_revision_id: value for value in authorization.rights_policies}
    for selection in plan.selections:
        proposal = proposals.get(selection.crop_proposal_id)
        if (
            proposal is None
            or proposal.source_anchor_id != selection.source_anchor_id
            or rights.get(proposal.rights_policy.rights_policy_revision_id)
            != proposal.rights_policy
        ):
            raise ValueError("micro-probe selection is absent or unauthorized")


def validate_micro_probe_worker_result(
    command: LocalImageLoraMicroProbeCommand,
    result: LocalImageLoraMicroProbeWorkerResult,
) -> None:
    if (
        result.training_run_id != command.training_run_id
        or result.probe_plan_pointer != command.probe_plan_pointer
        or result.probe_plan_sha256 != command.probe_plan_sha256
        or result.command_sha256 != command.command_sha256
        or result.attempt != command.attempt
    ):
        raise ValueError("micro-probe result does not bind the exact command")
    if result.adapter_manifest is not None and (
        result.adapter_manifest.base_model != command.probe_plan.base_model
        or result.adapter_manifest.probe_plan != command.probe_plan_pointer
    ):
        raise ValueError("micro-probe adapter does not bind the exact plan")
