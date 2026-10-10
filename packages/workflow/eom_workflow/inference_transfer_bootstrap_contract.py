"""Reviewed comparison-control inputs, not release or source-access authorization.

Publisher-produced Artifact identities remain outputs. Capacity references an
existing native control revision; the owner must resolve its current lifecycle.
"""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.item_inference_transfer import InferenceTransferRubricPointer
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import Field, model_validator

from eom_workflow.control_plane import FrozenModel, ModelCandidate, Sha256, UtcDatetime
from eom_workflow.control_schemas import validate_control_contract

MAX_TRANSFER_BOOTSTRAP_BYTES = 16 * 1024
MAX_TRANSFER_INSTRUCTION_BYTES = 256 * 1024


class InferenceTransferBootstrapSource(FrozenModel):
    """Immutable reviewed source provenance, without a runtime Git dependency."""

    repository_key: Literal["EOM"] = "EOM"
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_tree: str = Field(pattern=r"^[0-9a-f]{40}$")
    reviewed_at: UtcDatetime


class InferenceTransferBootstrapCapacityPin(FrozenModel):
    """Exact native capacity record, not a fabricated capacity Artifact."""

    capacity_policy_id: str = Field(pattern=r"^capacity_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    schema_version: Literal[
        "worker-capacity-policy/1.0",
        "worker-capacity-policy/1.1",
        "worker-capacity-policy/1.2",
        "worker-capacity-policy/1.3",
    ]
    content_sha256: Sha256


class InferenceTransferReviewedInstructionMember(FrozenModel):
    """Reviewed raw-byte identity; publication creates the actual Artifact pointer."""

    layer: Literal["PLATFORM", "ROLE"]
    relative_path: Literal["instructions/platform.md", "instructions/transfer-rubric.md"]
    logical_name: Literal["instructions/platform.md", "instructions/transfer-rubric.md"]
    schema_ref: Literal["eom://schemas/workflow/instruction-member/1.0"] = (
        "eom://schemas/workflow/instruction-member/1.0"
    )
    media_type: Literal["text/markdown"] = "text/markdown"
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=MAX_TRANSFER_INSTRUCTION_BYTES, strict=True)

    @model_validator(mode="after")
    def exact_member_purpose(self) -> InferenceTransferReviewedInstructionMember:
        expected = (
            "instructions/platform.md"
            if self.layer == "PLATFORM"
            else "instructions/transfer-rubric.md"
        )
        if self.relative_path != expected or self.logical_name != expected:
            raise ValueError("reviewed comparison instruction path/layer differs")
        return self


class InferenceTransferBootstrapManifest(FrozenModel):
    schema_version: Literal["inference-transfer-control-bootstrap/1.0"] = (
        "inference-transfer-control-bootstrap/1.0"
    )
    workflow_definition_key: Literal["item-inference-transfer-comparison"] = (
        "item-inference-transfer-comparison"
    )
    workflow_definition_version: Literal["1.0.0"] = "1.0.0"
    workflow_definition_sha256: Sha256
    workflow_role_schema_version: Literal["workflow-role/1.29.0"] = "workflow-role/1.29.0"
    result_schema: Literal["item-inference-transfer-pair-result@1.0"] = (
        "item-inference-transfer-pair-result@1.0"
    )
    source: InferenceTransferBootstrapSource
    capacity: InferenceTransferBootstrapCapacityPin
    rubric: InferenceTransferRubricPointer
    platform_instruction: InferenceTransferReviewedInstructionMember
    rubric_instruction: InferenceTransferReviewedInstructionMember
    model_candidate: ModelCandidate
    timeout_seconds: int = Field(ge=30, le=900, strict=True)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_reviewed_inputs(self) -> InferenceTransferBootstrapManifest:
        if self.platform_instruction.layer != "PLATFORM" or self.rubric_instruction.layer != "ROLE":
            raise ValueError("bootstrap requires exact platform and role instruction members")
        if self.rubric.rubric_sha256 != self.rubric_instruction.sha256:
            raise ValueError("bootstrap rubric logical revision and reviewed member hash differ")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("bootstrap manifest hash differs from its canonical reviewed inputs")
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > MAX_TRANSFER_BOOTSTRAP_BYTES:
            raise ValueError("bootstrap manifest exceeds its encoded byte bound")
        return self


def validate_inference_transfer_bootstrap_manifest(
    value: object,
) -> InferenceTransferBootstrapManifest:
    """Validate the installed schema first; this does not publish or release controls."""
    if not isinstance(value, dict):
        raise ValueError("bootstrap manifest must be a JSON object")
    validate_control_contract("inference-transfer-control-bootstrap", value)
    return InferenceTransferBootstrapManifest.model_validate(value)


def validate_inference_transfer_reviewed_instruction(
    manifest: InferenceTransferBootstrapManifest,
    *,
    layer: Literal["PLATFORM", "ROLE"],
    payload: bytes,
) -> None:
    """Check bounded already-materialized bytes; no file reads or publication occur."""
    checked = InferenceTransferBootstrapManifest.model_validate(manifest.model_dump(mode="json"))
    if layer not in {"PLATFORM", "ROLE"}:
        raise ValueError("bootstrap instruction layer is unsupported")
    member = checked.platform_instruction if layer == "PLATFORM" else checked.rubric_instruction
    if not isinstance(payload, bytes) or len(payload) != member.size_bytes:
        raise ValueError("bootstrap instruction bytes differ from the reviewed size")
    if sha256_bytes(payload) != member.sha256:
        raise ValueError("bootstrap instruction bytes differ from the reviewed SHA")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("bootstrap instruction bytes are not UTF-8 Markdown") from exc
