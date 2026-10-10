"""Closed preparation/release values; none carries authenticated authority.

The owner independently resolves published artifacts and current permissions.
These contracts only bind small exact metadata and preserve the initial DRAFT
versus explicit RELEASE distinction. No file reads, publication, or model runs.
"""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import Field, model_validator

from eom_workflow.control_plane import (
    BundleRevisionPointer,
    ControlArtifactPointer,
    ExecutionPresetRevision,
    FrozenModel,
    RevisionState,
    Sha256,
    WorkerRole,
)
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.inference_transfer_bootstrap_contract import (
    InferenceTransferBootstrapManifest,
    InferenceTransferBootstrapManifestV11,
    validate_inference_transfer_bootstrap_manifest,
    validate_inference_transfer_bootstrap_manifest_v11,
)

MAX_TRANSFER_CONTROL_INVOCATION_BYTES = 256 * 1024
_FAMILY = "inference-transfer-control-invocation"


def _canonical_hash(value: FrozenModel, hash_field: str) -> None:
    if getattr(value, hash_field) != content_sha256(
        value.model_dump(mode="json", exclude={hash_field})
    ):
        raise ValueError("control invocation hash differs from canonical metadata")
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > (
        MAX_TRANSFER_CONTROL_INVOCATION_BYTES
    ):
        raise ValueError("control invocation exceeds its encoded byte budget")


def _preset(
    value: ExecutionPresetRevision,
    *,
    state: RevisionState,
    protocol: str = "workflow-role/1.29.0",
) -> ExecutionPresetRevision:
    body = value.model_dump(mode="json")
    validate_control_contract("execution-preset-revision", body)
    checked = ExecutionPresetRevision.model_validate(body)
    _canonical_hash(checked, "content_sha256")
    if (
        checked.state != state
        or checked.revision_number != (1 if state == RevisionState.DRAFT else 2)
        or checked.general_knowledge_policy != "DENY"
        or checked.compatible_workflow_protocols != (protocol,)
        or len(checked.role_policies) != 1
    ):
        raise ValueError("control invocation requires the exact initial dedicated preset")
    policy = checked.role_policies[0]
    if (
        policy.role != WorkerRole.SUPPORT
        or len(policy.model_candidates) != 1
        or policy.reference_bundle is not None
        or policy.worker_pool_key != "customer-support"
        or not 30 <= policy.timeout_seconds <= 900
    ):
        raise ValueError("control invocation support policy differs")
    return checked


def _artifact(value: ControlArtifactPointer, *, schema_ref: str, logical_name: str) -> None:
    checked = ControlArtifactPointer.model_validate(value.model_dump(mode="json"))
    if (
        checked.schema_ref != schema_ref
        or checked.logical_name != logical_name
        or checked.media_type != "application/json"
    ):
        raise ValueError("control invocation artifact member schema/media/name differs")


class InferenceTransferPreparedReceipt(FrozenModel):
    """Exact publisher-issued pointers and DRAFT, not an authentication receipt."""

    schema_version: Literal["inference-transfer-prepared-receipt/1.0"] = (
        "inference-transfer-prepared-receipt/1.0"
    )
    manifest: InferenceTransferBootstrapManifest
    bootstrap_artifact: ControlArtifactPointer
    instruction_bundle: BundleRevisionPointer
    draft: ExecutionPresetRevision
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_preparation(self) -> InferenceTransferPreparedReceipt:
        manifest = (
            validate_inference_transfer_bootstrap_manifest_v11(
                self.manifest.model_dump(mode="json")
            )
            if isinstance(self.manifest, InferenceTransferBootstrapManifestV11)
            else validate_inference_transfer_bootstrap_manifest(
                self.manifest.model_dump(mode="json")
            )
        )
        _artifact(
            self.bootstrap_artifact,
            schema_ref=(
                "eom://schemas/workflow/inference-transfer-control-bootstrap/1.1"
                if isinstance(manifest, InferenceTransferBootstrapManifestV11)
                else "eom://schemas/workflow/inference-transfer-control-bootstrap/1.0"
            ),
            logical_name="inference-transfer-bootstrap.json",
        )
        # The publisher commits canonical JSON plus LF, not the manifest's
        # self-excluding metadata hash or newline-free canonical JSON hash.
        if self.bootstrap_artifact.sha256 != sha256_bytes(
            canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"
        ):
            raise ValueError("prepared bootstrap pointer differs from the full manifest bytes")
        bundle = BundleRevisionPointer.model_validate(
            self.instruction_bundle.model_dump(mode="json")
        )
        _artifact(
            bundle.manifest_artifact,
            schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
            logical_name="instruction-bundle.json",
        )
        if (
            not bundle.bundle_id.startswith("instrbundle_")
            or bundle.manifest_sha256 != bundle.manifest_artifact.sha256
        ):
            raise ValueError("prepared instruction bundle family or manifest hash differs")
        draft = _preset(
            self.draft, state=RevisionState.DRAFT, protocol=manifest.workflow_role_schema_version
        )
        policy = draft.role_policies[0]
        if (
            draft.capacity_policy_revision_id != manifest.capacity.capacity_policy_revision_id
            or draft.created_at != manifest.source.reviewed_at
            or policy.instruction_bundle != bundle
            or policy.model_candidates != (manifest.model_candidate,)
            or policy.timeout_seconds != manifest.timeout_seconds
        ):
            raise ValueError("prepared DRAFT differs from reviewed bootstrap inputs")
        _canonical_hash(self, "receipt_sha256")
        return self


class InferenceTransferPreparedReceiptV11(InferenceTransferPreparedReceipt):
    schema_version: Literal["inference-transfer-prepared-receipt/1.1"] = (
        "inference-transfer-prepared-receipt/1.1"  # type: ignore[assignment]
    )
    manifest: InferenceTransferBootstrapManifestV11


class InferenceTransferControlReleaseRequest(FrozenModel):
    schema_version: Literal["inference-transfer-control-release-request/1.0"] = (
        "inference-transfer-control-release-request/1.0"
    )
    receipt: InferenceTransferPreparedReceipt
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> InferenceTransferControlReleaseRequest:
        if isinstance(self.receipt, InferenceTransferPreparedReceiptV11):
            parse_inference_transfer_prepared_receipt_v11(self.receipt.model_dump(mode="json"))
        else:
            parse_inference_transfer_prepared_receipt(self.receipt.model_dump(mode="json"))
        _canonical_hash(self, "request_sha256")
        return self


class InferenceTransferControlReleaseRequestV11(InferenceTransferControlReleaseRequest):
    schema_version: Literal["inference-transfer-control-release-request/1.1"] = (
        "inference-transfer-control-release-request/1.1"  # type: ignore[assignment]
    )
    receipt: InferenceTransferPreparedReceiptV11


class InferenceTransferControlReleaseResult(FrozenModel):
    """Technical NON_LIVE release metadata, never scientific or human approval."""

    schema_version: Literal["inference-transfer-control-release-result/1.0"] = (
        "inference-transfer-control-release-result/1.0"
    )
    prepared_receipt_sha256: Sha256
    preset: ExecutionPresetRevision
    evaluation_id: str = Field(pattern=r"^preseteval_[0-9a-f]{32}$")
    evaluation_artifact: ControlArtifactPointer
    executed_cases: tuple[
        Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_:.-]{0,127}$")], ...
    ] = Field(min_length=1, max_length=64)
    quality_score_permille: None = None
    scientific_evaluation: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    human_transfer_evaluation: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_result(self) -> InferenceTransferControlReleaseResult:
        protocol = (
            "workflow-role/1.30.0"
            if isinstance(self, InferenceTransferControlReleaseResultV11)
            else "workflow-role/1.29.0"
        )
        _preset(self.preset, state=RevisionState.RELEASED, protocol=protocol)
        _artifact(
            self.evaluation_artifact,
            schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            logical_name="inference-transfer-preset-evaluation.json",
        )
        if len(set(self.executed_cases)) != len(self.executed_cases):
            raise ValueError("executed technical cases must be unique")
        _canonical_hash(self, "result_sha256")
        return self


class InferenceTransferControlReleaseResultV11(InferenceTransferControlReleaseResult):
    schema_version: Literal["inference-transfer-control-release-result/1.1"] = (
        "inference-transfer-control-release-result/1.1"  # type: ignore[assignment]
    )


def _parse[T: FrozenModel](value: object, model: type[T]) -> T:
    if not isinstance(value, dict):
        raise ValueError("control invocation must be a JSON object")
    validate_control_contract(_FAMILY, value)
    return model.model_validate(value)


def _parse_v11[T: FrozenModel](value: object, model: type[T]) -> T:
    if not isinstance(value, dict):
        raise ValueError("control invocation must be a JSON object")
    validate_control_contract("inference-transfer-control-invocation-v1.1", value)
    return model.model_validate(value)


def parse_inference_transfer_prepared_receipt_v11(
    value: object,
) -> InferenceTransferPreparedReceiptV11:
    return _parse_v11(value, InferenceTransferPreparedReceiptV11)


def parse_inference_transfer_release_request_v11(
    value: object,
) -> InferenceTransferControlReleaseRequestV11:
    return _parse_v11(value, InferenceTransferControlReleaseRequestV11)


def parse_inference_transfer_release_result_v11(
    value: object,
) -> InferenceTransferControlReleaseResultV11:
    return _parse_v11(value, InferenceTransferControlReleaseResultV11)


def parse_inference_transfer_prepared_receipt(value: object) -> InferenceTransferPreparedReceipt:
    return _parse(value, InferenceTransferPreparedReceipt)


def parse_inference_transfer_release_request(
    value: object,
) -> InferenceTransferControlReleaseRequest:
    return _parse(value, InferenceTransferControlReleaseRequest)


def parse_inference_transfer_release_result(value: object) -> InferenceTransferControlReleaseResult:
    return _parse(value, InferenceTransferControlReleaseResult)


def validate_inference_transfer_release_result_context(
    request: InferenceTransferControlReleaseRequest,
    result: InferenceTransferControlReleaseResult,
) -> None:
    """Exact preparation→release closure only; actual current authorization is owner-owned."""
    request = parse_inference_transfer_release_request(request.model_dump(mode="json"))
    result = parse_inference_transfer_release_result(result.model_dump(mode="json"))
    _validate_release_context(request, result)


def validate_inference_transfer_release_result_context_v11(
    request: InferenceTransferControlReleaseRequestV11,
    result: InferenceTransferControlReleaseResultV11,
) -> None:
    request = parse_inference_transfer_release_request_v11(request.model_dump(mode="json"))
    result = parse_inference_transfer_release_result_v11(result.model_dump(mode="json"))
    _validate_release_context(request, result)


def _validate_release_context(
    request: InferenceTransferControlReleaseRequest,
    result: InferenceTransferControlReleaseResult,
) -> None:
    draft = request.receipt.draft
    mutable_lifecycle = {
        "preset_revision_id",
        "revision_number",
        "state",
        "content_sha256",
        "created_at",
    }
    if (
        result.prepared_receipt_sha256 != request.receipt.receipt_sha256
        or result.preset.preset_revision_id == draft.preset_revision_id
        or result.preset.created_at < draft.created_at
        or result.preset.model_dump(mode="json", exclude=mutable_lifecycle)
        != draft.model_dump(mode="json", exclude=mutable_lifecycle)
    ):
        raise ValueError("release result differs from the exact initial prepared policy")
