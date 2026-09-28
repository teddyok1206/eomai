"""Fixed-unit local GPU background adapter owned by the Catalog use case."""

from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from eom_identifiers import sha256_bytes, sha256_file
from eom_image_contracts import (
    LocalImageCompositeReceipt,
    LocalImageCompositeRequest,
    LocalImageGenerationRequest,
    LocalImageOverlayInput,
    LocalImageProviderBinding,
    LocalImageProviderBindingV2,
    LocalImageProviderBindingV3,
    LocalImageProviderBindingV4,
    LocalImageReferenceConditionedCompositeReceipt,
    LocalImageReferenceConditionedCompositeReceiptV2,
    LocalImageReferenceConditionedCompositeReceiptV3,
    LocalImageReferenceConditionedCompositeReceiptV4,
    LocalImageReferenceConditionedCompositeRequest,
    LocalImageReferenceConditionedCompositeRequestV2,
    LocalImageReferenceConditionedCompositeRequestV3,
    LocalImageReferenceConditionedCompositeRequestV4,
    LocalImageReferenceConditioning,
    LocalImageVisualReferencePointer,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_reference_conditioned_receipt,
    validate_reference_conditioned_receipt_v2,
    validate_reference_conditioned_receipt_v3,
    validate_reference_conditioned_receipt_v4,
)
from eom_workflow.models import (
    GeneratedVectorDrawingV5,
    GeneratedVectorDrawingV6,
)

from eom_catalog_service.local_image_prompt_policy import (
    LOCAL_GPU_MAX_SUBJECT_CHARS,
    LocalGpuPromptContract,
    compose_local_gpu_prompt_plan,
    local_gpu_prompt_policy_revision,
)
from eom_catalog_service.settings import CatalogSettings

SYSTEMCTL: Final = Path("/usr/bin/systemctl")
SYSTEMCTL_ENV: Final = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
WORKSPACE_ROOT_MODE: Final = 0o3770
WORKSPACE_MODE: Final = 0o1730
INPUT_MODE: Final = 0o440
OUTPUT_MODE: Final = 0o640
OVERLAY_MEMBER: Final = "generated-overlay.png"
BACKGROUND_MEMBER: Final = "generated-background.png"
FINAL_MEMBER: Final = "generated-stimulus.png"
RECEIPT_MEMBER: Final = "local-image-receipt.json"
PROVIDER_RECEIPT_MEMBER: Final = "composite-receipt.json"
_FORBIDDEN_GENERATION_STYLE_TERMS: Final = (
    "photoreal",
    "photo-real",
    "photograph",
    "realistic human",
    "realistic person",
    "detailed face",
    "detailed skin",
    "cinematic",
    "dramatic lighting",
    "studio lighting",
    "3d render",
    "실사",
    "사진풍",
    "사실적인 사람",
    "상세한 얼굴",
    "시네마틱",
)
_FORBIDDEN_CHROMATIC_TERMS: Final = re.compile(
    r"(?:\b(?:red|orange|yellow|green|blue|purple|violet|pink|brown|cyan|magenta|gold|golden|"
    r"color|colored|colour|coloured|colorful)\b|"
    r"빨간|붉은|주황|노란|노랑|초록|녹색|파란|푸른|남색|보라|분홍|갈색|청록|자홍|금색|"
    r"컬러|색채|색상)",
    re.IGNORECASE,
)
_FORBIDDEN_GPU_HUMAN_SUBJECT: Final = re.compile(
    r"(?:\b(?:student|person|people|human|boy|girl|man|woman|teacher|child|teenager)\b|"
    r"학생|사람|소년|소녀|남자|여자|교사|선생|어린이|청소년)",
    re.IGNORECASE,
)
_HUMAN_EXCLUSION: Final = re.compile(
    r"(?:없(?:이|는|도록)|제외(?:하|된|한다|하고)?|배제(?:하|된|한다|하고)?|"
    r"(?:포함|배치|묘사|표현|등장)(?:하지|하지\s+않|하지\s+말)|"
    r"(?:그리|넣)(?:지|지\s+않|지\s+말)|"
    r"\b(?:must\s+not|do\s+not|not\s+included|excluded|absent)\b)",
    re.IGNORECASE,
)
_HUMAN_AFFIRMATIVE_ACTION: Final = re.compile(
    r"(?:배치|묘사|표현|포함|등장)(?:하고|하며|한다|하도록|해|하여|된|하는)|"
    r"(?:그리|넣)(?:고|며|도록|어|어서|은|는)|"
    r"\b(?:draw|include|show|depict|place|feature)(?:s|ed|ing)?\b",
    re.IGNORECASE,
)
_HUMAN_AFFIRMATIVE_PREFIX: Final = re.compile(
    r"\b(?:draw|include|show|depict|place|feature)\s+(?:(?:one|a|the|some)\s+)?$",
    re.IGNORECASE,
)
_WORKFLOW_ID: Final = re.compile(r"^workflow_[0-9a-f]{32}$")
_REVISION_ID: Final = re.compile(r"^rev_[0-9a-f]{32}$")
_SHA256: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


class LocalImageAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LocalImageMaterialization:
    request: LocalImageCompositeRequest
    receipt: LocalImageCompositeReceipt
    background_path: Path
    final_path: Path
    receipt_path: Path
    unit_name: str
    prompt_policy_revision: str


@dataclass(frozen=True)
class ReferenceConditionedLocalImageMaterialization:
    request: LocalImageReferenceConditionedCompositeRequest
    receipt: LocalImageReferenceConditionedCompositeReceipt
    background_path: Path
    final_path: Path
    receipt_path: Path
    unit_name: str
    prompt_policy_revision: str


@dataclass(frozen=True)
class StyleReferenceConditionedLocalImageMaterialization:
    request: LocalImageReferenceConditionedCompositeRequestV2
    receipt: LocalImageReferenceConditionedCompositeReceiptV2
    background_path: Path
    final_path: Path
    receipt_path: Path
    unit_name: str
    prompt_policy_revision: str


@dataclass(frozen=True)
class SimplifiedStyleReferenceLocalImageMaterialization:
    request: LocalImageReferenceConditionedCompositeRequestV3
    receipt: LocalImageReferenceConditionedCompositeReceiptV3
    background_path: Path
    final_path: Path
    conditioning_path: Path
    receipt_path: Path
    unit_name: str
    prompt_policy_revision: str


@dataclass(frozen=True)
class SimplifiedBaseReferenceLocalImageMaterialization:
    request: LocalImageReferenceConditionedCompositeRequestV4
    receipt: LocalImageReferenceConditionedCompositeReceiptV4
    background_path: Path
    final_path: Path
    conditioning_path: Path
    receipt_path: Path
    unit_name: str
    prompt_policy_revision: str


def load_local_image_provider_binding(
    path: Path,
    *,
    trusted_owner_uid: int = 0,
    trusted_group_gid: int = 0,
) -> LocalImageProviderBinding:
    """Load one root-controlled binding without following a symlink."""

    value = _load_provider_binding_document(
        path,
        trusted_owner_uid=trusted_owner_uid,
        trusted_group_gid=trusted_group_gid,
        maximum_bytes=64 * 1024,
    )
    try:
        validate_contract("provider-binding", value)
        return LocalImageProviderBinding.model_validate(value)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc


def load_local_image_provider_binding_v2(
    path: Path,
    *,
    trusted_owner_uid: int = 0,
    trusted_group_gid: int = 0,
) -> LocalImageProviderBindingV2:
    """Load one root-controlled style/reference binding without implicit V1 fallback."""

    value = _load_provider_binding_document(
        path,
        trusted_owner_uid=trusted_owner_uid,
        trusted_group_gid=trusted_group_gid,
        maximum_bytes=512 * 1024,
    )
    try:
        validate_contract("provider-binding-v2", value)
        return LocalImageProviderBindingV2.model_validate(value)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc


def load_local_image_provider_binding_v3(
    path: Path,
    *,
    trusted_owner_uid: int = 0,
    trusted_group_gid: int = 0,
) -> LocalImageProviderBindingV3:
    """Load one root-controlled simplified-reference binding without fallback."""

    value = _load_provider_binding_document(
        path,
        trusted_owner_uid=trusted_owner_uid,
        trusted_group_gid=trusted_group_gid,
        maximum_bytes=512 * 1024,
    )
    try:
        validate_contract("provider-binding-v3", value)
        return LocalImageProviderBindingV3.model_validate(value)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc


def load_local_image_provider_binding_v4(
    path: Path,
    *,
    trusted_owner_uid: int = 0,
    trusted_group_gid: int = 0,
) -> LocalImageProviderBindingV4:
    """Load one root-controlled base-only simplified-reference binding."""

    value = _load_provider_binding_document(
        path,
        trusted_owner_uid=trusted_owner_uid,
        trusted_group_gid=trusted_group_gid,
        maximum_bytes=512 * 1024,
    )
    try:
        validate_contract("provider-binding-v4", value)
        return LocalImageProviderBindingV4.model_validate(value)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc


def load_local_image_provider_binding_any(
    path: Path,
    *,
    trusted_owner_uid: int = 0,
    trusted_group_gid: int = 0,
) -> (
    LocalImageProviderBinding
    | LocalImageProviderBindingV2
    | LocalImageProviderBindingV3
    | LocalImageProviderBindingV4
):
    """Load the exact immutable V1 or V2 binding selected by its schema discriminator."""

    value = _load_provider_binding_document(
        path,
        trusted_owner_uid=trusted_owner_uid,
        trusted_group_gid=trusted_group_gid,
        maximum_bytes=512 * 1024,
    )
    schema_version = value.get("schema_version")
    try:
        if schema_version == "local-image-provider-binding/1.0":
            validate_contract("provider-binding", value)
            return LocalImageProviderBinding.model_validate(value)
        if schema_version == "local-image-provider-binding/2.0":
            validate_contract("provider-binding-v2", value)
            return LocalImageProviderBindingV2.model_validate(value)
        if schema_version == "local-image-provider-binding/3.0":
            validate_contract("provider-binding-v3", value)
            return LocalImageProviderBindingV3.model_validate(value)
        if schema_version == "local-image-provider-binding/4.0":
            validate_contract("provider-binding-v4", value)
            return LocalImageProviderBindingV4.model_validate(value)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")


def _load_provider_binding_document(
    path: Path,
    *,
    trusted_owner_uid: int,
    trusted_group_gid: int,
    maximum_bytes: int,
) -> dict[str, object]:
    _require_absolute_components(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != trusted_owner_uid
        or metadata.st_gid != trusted_group_gid
        or stat.S_IMODE(metadata.st_mode) != 0o644
        or not 0 < metadata.st_size <= maximum_bytes
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")
    return _load_json(path, maximum_bytes=maximum_bytes)


class FixedLocalImageProviderAdapter:
    """Stage one immutable request and start only the fixed provider unit."""

    def __init__(self, settings: CatalogSettings) -> None:
        self.settings = settings

    def generate(
        self,
        *,
        workflow_id: str,
        result_revision_id: str,
        drawing_hash: str,
        drawing: GeneratedVectorDrawingV5 | GeneratedVectorDrawingV6,
        overlay_path: Path,
        binding: LocalImageProviderBinding,
        output_directory: Path,
        prompt_contract: LocalGpuPromptContract,
    ) -> LocalImageMaterialization:
        if drawing.production_route not in {
            "LOCAL_GENERATIVE_BACKGROUND",
            "HYBRID_LOCAL_GENERATIVE",
        }:
            raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")
        request = _build_request(
            workflow_id=workflow_id,
            result_revision_id=result_revision_id,
            drawing_hash=drawing_hash,
            drawing=drawing,
            binding=binding,
            overlay_path=overlay_path,
            prompt_contract=prompt_contract,
        )
        provider_gid = _provider_group_id(self.settings.local_image_provider_group)
        workspace = _prepare_workspace(
            self.settings.local_image_workspace_root,
            request.generation.request_id,
            provider_gid,
        )
        request_bytes = _canonical_json(request.model_dump(mode="json"))
        _stage_exact_file(workspace / "request.json", request_bytes, provider_gid)
        _stage_exact_source(workspace / OVERLAY_MEMBER, overlay_path, provider_gid)
        provider_receipt = workspace / PROVIDER_RECEIPT_MEMBER
        unit_name = f"eom-image-provider@{request.generation.request_id}.service"
        if not provider_receipt.exists() and not provider_receipt.is_symlink():
            _run_fixed_unit(unit_name, binding.timeout_seconds)
        receipt = _validate_handoff(workspace, request, provider_gid)
        _copy_result(workspace / BACKGROUND_MEMBER, output_directory / BACKGROUND_MEMBER)
        _copy_result(workspace / FINAL_MEMBER, output_directory / FINAL_MEMBER)
        receipt_path = output_directory / RECEIPT_MEMBER
        _copy_result(provider_receipt, receipt_path)
        return LocalImageMaterialization(
            request=request,
            receipt=receipt,
            background_path=output_directory / BACKGROUND_MEMBER,
            final_path=output_directory / FINAL_MEMBER,
            receipt_path=receipt_path,
            unit_name=unit_name,
            prompt_policy_revision=local_gpu_prompt_policy_revision(prompt_contract),
        )

    def generate_with_reference(
        self,
        *,
        workflow_id: str,
        result_revision_id: str,
        drawing_hash: str,
        drawing: GeneratedVectorDrawingV6,
        overlay_path: Path,
        binding: LocalImageProviderBinding,
        output_directory: Path,
        prompt_contract: LocalGpuPromptContract,
        visual_reference: LocalImageVisualReferencePointer,
        reference_bytes: bytes,
    ) -> ReferenceConditionedLocalImageMaterialization:
        """Stage one exact reference without changing the reviewed generation prompt."""

        composite = _build_request(
            workflow_id=workflow_id,
            result_revision_id=result_revision_id,
            drawing_hash=drawing_hash,
            drawing=drawing,
            binding=binding,
            overlay_path=overlay_path,
            prompt_contract=prompt_contract,
        )
        request = _build_reference_conditioned_request(composite, visual_reference)
        provider_gid = _provider_group_id(self.settings.local_image_provider_group)
        instance_id = "imgreq_" + request.request_sha256.removeprefix("sha256:")[:32]
        workspace = _prepare_workspace(
            self.settings.local_image_workspace_root,
            instance_id,
            provider_gid,
        )
        _stage_exact_file(
            workspace / "request.json",
            _canonical_json(request.model_dump(mode="json")),
            provider_gid,
        )
        _stage_exact_source(workspace / OVERLAY_MEMBER, overlay_path, provider_gid)
        reference_target = workspace / visual_reference.reference_member.member_path
        if (
            not 0 < len(reference_bytes) <= 8 * 1024 * 1024
            or len(reference_bytes) != visual_reference.reference_member.size_bytes
            or sha256_bytes(reference_bytes) != visual_reference.reference_member.sha256
        ):
            raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
        _prepare_input_directory(reference_target.parent, workspace, provider_gid)
        _stage_exact_file(
            reference_target,
            reference_bytes,
            provider_gid,
            maximum_bytes=8 * 1024 * 1024,
        )
        conditioned_receipt_path = workspace / "reference-conditioned-receipt.json"
        unit_name = f"eom-image-reference-provider@{instance_id}.service"
        if not conditioned_receipt_path.exists() and not conditioned_receipt_path.is_symlink():
            _run_fixed_unit(unit_name, binding.timeout_seconds)
        receipt = _validate_reference_handoff(
            workspace,
            request,
            provider_gid,
        )
        _copy_result(workspace / BACKGROUND_MEMBER, output_directory / BACKGROUND_MEMBER)
        _copy_result(workspace / FINAL_MEMBER, output_directory / FINAL_MEMBER)
        receipt_path = output_directory / RECEIPT_MEMBER
        _copy_result(conditioned_receipt_path, receipt_path)
        return ReferenceConditionedLocalImageMaterialization(
            request=request,
            receipt=receipt,
            background_path=output_directory / BACKGROUND_MEMBER,
            final_path=output_directory / FINAL_MEMBER,
            receipt_path=receipt_path,
            unit_name=unit_name,
            prompt_policy_revision=local_gpu_prompt_policy_revision(prompt_contract),
        )

    def generate_with_style_reference(
        self,
        *,
        workflow_id: str,
        result_revision_id: str,
        drawing_hash: str,
        drawing: GeneratedVectorDrawingV6,
        overlay_path: Path,
        binding: LocalImageProviderBindingV2,
        output_directory: Path,
        prompt_contract: LocalGpuPromptContract,
        visual_reference: LocalImageVisualReferencePointer,
        reference_bytes: bytes,
    ) -> StyleReferenceConditionedLocalImageMaterialization:
        """Stage one exact reference and one pinned released style adapter identity."""

        composite = _build_request(
            workflow_id=workflow_id,
            result_revision_id=result_revision_id,
            drawing_hash=drawing_hash,
            drawing=drawing,
            binding=binding,
            overlay_path=overlay_path,
            prompt_contract=prompt_contract,
        )
        request = _build_reference_conditioned_request_v2(
            composite,
            visual_reference,
            binding,
        )
        provider_gid = _provider_group_id(self.settings.local_image_provider_group)
        instance_id = "imgreq_" + request.request_sha256.removeprefix("sha256:")[:32]
        workspace = _prepare_workspace(
            self.settings.local_image_workspace_root,
            instance_id,
            provider_gid,
        )
        _stage_exact_file(
            workspace / "request.json",
            _canonical_json(request.model_dump(mode="json")),
            provider_gid,
        )
        _stage_exact_source(workspace / OVERLAY_MEMBER, overlay_path, provider_gid)
        reference_target = workspace / visual_reference.reference_member.member_path
        if (
            len(reference_bytes) != visual_reference.reference_member.size_bytes
            or "sha256:" + hashlib.sha256(reference_bytes).hexdigest()
            != visual_reference.reference_member.sha256
        ):
            raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
        _prepare_input_directory(reference_target.parent, workspace, provider_gid)
        _stage_exact_file(
            reference_target,
            reference_bytes,
            provider_gid,
            maximum_bytes=8 * 1024 * 1024,
        )
        conditioned_receipt_path = workspace / "reference-conditioned-receipt.json"
        unit_name = f"eom-image-reference-style-provider@{instance_id}.service"
        if not conditioned_receipt_path.exists() and not conditioned_receipt_path.is_symlink():
            _run_fixed_unit(unit_name, binding.timeout_seconds)
        receipt = _validate_reference_handoff_v2(workspace, request, provider_gid)
        _copy_result(workspace / BACKGROUND_MEMBER, output_directory / BACKGROUND_MEMBER)
        _copy_result(workspace / FINAL_MEMBER, output_directory / FINAL_MEMBER)
        receipt_path = output_directory / RECEIPT_MEMBER
        _copy_result(conditioned_receipt_path, receipt_path)
        return StyleReferenceConditionedLocalImageMaterialization(
            request=request,
            receipt=receipt,
            background_path=output_directory / BACKGROUND_MEMBER,
            final_path=output_directory / FINAL_MEMBER,
            receipt_path=receipt_path,
            unit_name=unit_name,
            prompt_policy_revision=local_gpu_prompt_policy_revision(prompt_contract),
        )

    def generate_with_simplified_style_reference(
        self,
        *,
        workflow_id: str,
        result_revision_id: str,
        drawing_hash: str,
        drawing: GeneratedVectorDrawingV6,
        overlay_path: Path,
        binding: LocalImageProviderBindingV3,
        output_directory: Path,
        prompt_contract: LocalGpuPromptContract,
        visual_reference: LocalImageVisualReferencePointer,
        reference_bytes: bytes,
    ) -> SimplifiedStyleReferenceLocalImageMaterialization:
        """Stage one source reference and require a committed simplified conditioning member."""

        composite = _build_request(
            workflow_id=workflow_id,
            result_revision_id=result_revision_id,
            drawing_hash=drawing_hash,
            drawing=drawing,
            binding=binding,
            overlay_path=overlay_path,
            prompt_contract=prompt_contract,
        )
        request = _build_reference_conditioned_request_v3(
            composite,
            visual_reference,
            binding,
        )
        provider_gid = _provider_group_id(self.settings.local_image_provider_group)
        instance_id = "imgreq_" + request.request_sha256.removeprefix("sha256:")[:32]
        workspace = _prepare_workspace(
            self.settings.local_image_workspace_root,
            instance_id,
            provider_gid,
        )
        _stage_exact_file(
            workspace / "request.json",
            _canonical_json(request.model_dump(mode="json")),
            provider_gid,
        )
        _stage_exact_source(workspace / OVERLAY_MEMBER, overlay_path, provider_gid)
        reference_target = workspace / visual_reference.reference_member.member_path
        if (
            len(reference_bytes) != visual_reference.reference_member.size_bytes
            or "sha256:" + hashlib.sha256(reference_bytes).hexdigest()
            != visual_reference.reference_member.sha256
        ):
            raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
        _prepare_input_directory(reference_target.parent, workspace, provider_gid)
        _stage_exact_file(
            reference_target,
            reference_bytes,
            provider_gid,
            maximum_bytes=8 * 1024 * 1024,
        )
        conditioned_receipt_path = workspace / "reference-conditioned-receipt.json"
        unit_name = f"eom-image-reference-style-provider@{instance_id}.service"
        if not conditioned_receipt_path.exists() and not conditioned_receipt_path.is_symlink():
            _run_fixed_unit(unit_name, binding.timeout_seconds)
        receipt = _validate_reference_handoff_v3(workspace, request, provider_gid)
        _copy_result(workspace / BACKGROUND_MEMBER, output_directory / BACKGROUND_MEMBER)
        _copy_result(workspace / FINAL_MEMBER, output_directory / FINAL_MEMBER)
        conditioning_path = output_directory / receipt.conditioning_output.member_path
        _copy_result(
            workspace / receipt.conditioning_output.member_path,
            conditioning_path,
        )
        receipt_path = output_directory / RECEIPT_MEMBER
        _copy_result(conditioned_receipt_path, receipt_path)
        return SimplifiedStyleReferenceLocalImageMaterialization(
            request=request,
            receipt=receipt,
            background_path=output_directory / BACKGROUND_MEMBER,
            final_path=output_directory / FINAL_MEMBER,
            conditioning_path=conditioning_path,
            receipt_path=receipt_path,
            unit_name=unit_name,
            prompt_policy_revision=local_gpu_prompt_policy_revision(prompt_contract),
        )

    def generate_with_simplified_base_reference(
        self,
        *,
        workflow_id: str,
        result_revision_id: str,
        drawing_hash: str,
        drawing: GeneratedVectorDrawingV6,
        overlay_path: Path,
        binding: LocalImageProviderBindingV4,
        output_directory: Path,
        prompt_contract: LocalGpuPromptContract,
        visual_reference: LocalImageVisualReferencePointer,
        reference_bytes: bytes,
    ) -> SimplifiedBaseReferenceLocalImageMaterialization:
        """Stage one source reference for base-only simplified monochrome generation."""

        composite = _build_request(
            workflow_id=workflow_id,
            result_revision_id=result_revision_id,
            drawing_hash=drawing_hash,
            drawing=drawing,
            binding=binding,
            overlay_path=overlay_path,
            prompt_contract=prompt_contract,
        )
        request = _build_reference_conditioned_request_v4(
            composite,
            visual_reference,
            binding,
        )
        provider_gid = _provider_group_id(self.settings.local_image_provider_group)
        instance_id = "imgreq_" + request.request_sha256.removeprefix("sha256:")[:32]
        workspace = _prepare_workspace(
            self.settings.local_image_workspace_root,
            instance_id,
            provider_gid,
        )
        _stage_exact_file(
            workspace / "request.json",
            _canonical_json(request.model_dump(mode="json")),
            provider_gid,
        )
        _stage_exact_source(workspace / OVERLAY_MEMBER, overlay_path, provider_gid)
        reference_target = workspace / visual_reference.reference_member.member_path
        if (
            len(reference_bytes) != visual_reference.reference_member.size_bytes
            or "sha256:" + hashlib.sha256(reference_bytes).hexdigest()
            != visual_reference.reference_member.sha256
        ):
            raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
        _prepare_input_directory(reference_target.parent, workspace, provider_gid)
        _stage_exact_file(
            reference_target,
            reference_bytes,
            provider_gid,
            maximum_bytes=8 * 1024 * 1024,
        )
        conditioned_receipt_path = workspace / "reference-conditioned-receipt.json"
        unit_name = f"eom-image-reference-base-provider@{instance_id}.service"
        if not conditioned_receipt_path.exists() and not conditioned_receipt_path.is_symlink():
            _run_fixed_unit(unit_name, binding.timeout_seconds)
        receipt = _validate_reference_handoff_v4(workspace, request, provider_gid)
        _copy_result(workspace / BACKGROUND_MEMBER, output_directory / BACKGROUND_MEMBER)
        _copy_result(workspace / FINAL_MEMBER, output_directory / FINAL_MEMBER)
        conditioning_path = output_directory / receipt.conditioning_output.member_path
        _copy_result(
            workspace / receipt.conditioning_output.member_path,
            conditioning_path,
        )
        receipt_path = output_directory / RECEIPT_MEMBER
        _copy_result(conditioned_receipt_path, receipt_path)
        return SimplifiedBaseReferenceLocalImageMaterialization(
            request=request,
            receipt=receipt,
            background_path=output_directory / BACKGROUND_MEMBER,
            final_path=output_directory / FINAL_MEMBER,
            conditioning_path=conditioning_path,
            receipt_path=receipt_path,
            unit_name=unit_name,
            prompt_policy_revision=local_gpu_prompt_policy_revision(prompt_contract),
        )


def _build_reference_conditioned_request(
    composite: LocalImageCompositeRequest,
    visual_reference: LocalImageVisualReferencePointer,
) -> LocalImageReferenceConditionedCompositeRequest:
    body = {
        "schema_version": "local-image-reference-conditioned-composite-request/1.0",
        "composite_request": composite.model_dump(mode="json"),
        "visual_reference": visual_reference.model_dump(mode="json"),
        "conditioning": LocalImageReferenceConditioning().model_dump(mode="json"),
    }
    request = LocalImageReferenceConditionedCompositeRequest.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )
    validate_contract("reference-conditioned-composite-request", request.model_dump(mode="json"))
    return request


def _build_reference_conditioned_request_v2(
    composite: LocalImageCompositeRequest,
    visual_reference: LocalImageVisualReferencePointer,
    binding: LocalImageProviderBindingV2,
) -> LocalImageReferenceConditionedCompositeRequestV2:
    body = {
        "schema_version": "local-image-reference-conditioned-composite-request/2.0",
        "composite_request": composite.model_dump(mode="json"),
        "visual_reference": visual_reference.model_dump(mode="json"),
        "conditioning": LocalImageReferenceConditioning(
            strength=binding.reference_policy.conditioning_strength
        ).model_dump(mode="json"),
        "style_adapter": binding.style_adapter.model_dump(mode="json"),
    }
    request = LocalImageReferenceConditionedCompositeRequestV2.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )
    validate_contract("reference-conditioned-composite-request-v2", request.model_dump(mode="json"))
    return request


def _build_reference_conditioned_request_v3(
    composite: LocalImageCompositeRequest,
    visual_reference: LocalImageVisualReferencePointer,
    binding: LocalImageProviderBindingV3,
) -> LocalImageReferenceConditionedCompositeRequestV3:
    body = {
        "schema_version": "local-image-reference-conditioned-composite-request/3.0",
        "composite_request": composite.model_dump(mode="json"),
        "visual_reference": visual_reference.model_dump(mode="json"),
        "conditioning": binding.reference_policy.conditioning.model_dump(mode="json"),
        "style_adapter": binding.style_adapter.model_dump(mode="json"),
    }
    request = LocalImageReferenceConditionedCompositeRequestV3.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )
    validate_contract("reference-conditioned-composite-request-v3", request.model_dump(mode="json"))
    return request


def _build_reference_conditioned_request_v4(
    composite: LocalImageCompositeRequest,
    visual_reference: LocalImageVisualReferencePointer,
    binding: LocalImageProviderBindingV4,
) -> LocalImageReferenceConditionedCompositeRequestV4:
    body = {
        "schema_version": "local-image-reference-conditioned-composite-request/4.0",
        "composite_request": composite.model_dump(mode="json"),
        "visual_reference": visual_reference.model_dump(mode="json"),
        "conditioning": binding.reference_policy.conditioning.model_dump(mode="json"),
    }
    request = LocalImageReferenceConditionedCompositeRequestV4.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )
    validate_contract("reference-conditioned-composite-request-v4", request.model_dump(mode="json"))
    return request


def _build_request(
    *,
    workflow_id: str,
    result_revision_id: str,
    drawing_hash: str,
    drawing: GeneratedVectorDrawingV5 | GeneratedVectorDrawingV6,
    binding: (
        LocalImageProviderBinding
        | LocalImageProviderBindingV2
        | LocalImageProviderBindingV3
        | LocalImageProviderBindingV4
    ),
    overlay_path: Path,
    prompt_contract: LocalGpuPromptContract = "LEGACY_COMPAT",
) -> LocalImageCompositeRequest:
    if (
        _WORKFLOW_ID.fullmatch(workflow_id) is None
        or _REVISION_ID.fullmatch(result_revision_id) is None
        or _SHA256.fullmatch(drawing_hash) is None
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
    if drawing.generation_prompt is None:
        raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
    if _has_forbidden_gpu_content(drawing.generation_prompt):
        raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
    if isinstance(drawing, GeneratedVectorDrawingV6):
        subject = drawing.alt_text
        if len(subject) > LOCAL_GPU_MAX_SUBJECT_CHARS or _has_forbidden_gpu_content(subject):
            raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
    else:
        subject = drawing.generation_prompt
    production_route = cast(
        Literal["LOCAL_GENERATIVE_BACKGROUND", "HYBRID_LOCAL_GENERATIVE"],
        drawing.production_route,
    )
    try:
        prompt_plan = compose_local_gpu_prompt_plan(
            subject=subject,
            production_route=production_route,
            prompt_contract=prompt_contract,
        )
    except ValueError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID") from exc
    prompt = prompt_plan.positive_prompt
    negative = prompt_plan.negative_prompt
    if len(prompt) > 4000 or len(negative) > 2000:
        raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
    prompt_sha256 = text_sha256(prompt)
    negative_prompt_sha256 = text_sha256(negative)
    identity = content_sha256(
        {
            "workflow_id": workflow_id,
            "result_revision_id": result_revision_id,
            "drawing_sha256": drawing_hash,
            "binding_sha256": binding.binding_sha256,
            "prompt_policy_revision": prompt_plan.policy_revision,
            "prompt_sha256": prompt_sha256,
            "negative_prompt_sha256": negative_prompt_sha256,
        }
    ).removeprefix("sha256:")
    request_id = "imgreq_" + identity[:32]
    seed = int(identity[32:40], 16)
    generation_body = {
        "schema_version": "local-image-generation-request/1.0",
        "request_id": request_id,
        "idempotency_key": "local-image:" + identity,
        "model": binding.model.model_dump(mode="json"),
        "prompt": prompt,
        "prompt_sha256": prompt_sha256,
        "negative_prompt": negative,
        "negative_prompt_sha256": negative_prompt_sha256,
        "seed": seed,
        "sampler": binding.sampler.model_dump(mode="json"),
        "generation_canvas": {"width_px": 800, "height_px": 504},
        "delivery_canvas": {"width_px": 800, "height_px": 500},
        "output_member": BACKGROUND_MEMBER,
        "timeout_seconds": binding.timeout_seconds,
    }
    generation = LocalImageGenerationRequest.model_validate(
        {**generation_body, "request_sha256": content_sha256(generation_body)}
    )
    overlay = _overlay_pointer(overlay_path)
    composite_body = {
        "schema_version": "local-image-composite-request/1.0",
        "generation": generation.model_dump(mode="json"),
        "overlay": overlay.model_dump(mode="json"),
        "final_output_member": FINAL_MEMBER,
    }
    request = LocalImageCompositeRequest.model_validate(
        {
            **composite_body,
            "composite_request_sha256": content_sha256(composite_body),
        }
    )
    validate_contract("composite-request", request.model_dump(mode="json"))
    return request


def _has_forbidden_gpu_content(value: str) -> bool:
    normalized = value.casefold()
    return (
        any(forbidden in normalized for forbidden in _FORBIDDEN_GENERATION_STYLE_TERMS)
        or _contains_positive_human_subject(value)
        or _FORBIDDEN_CHROMATIC_TERMS.search(value) is not None
    )


def _contains_positive_human_subject(value: str) -> bool:
    """Reject human subjects while allowing an explicit bounded exclusion clause."""

    for match in _FORBIDDEN_GPU_HUMAN_SUBJECT.finditer(value):
        sentence_start = max(
            value.rfind(marker, 0, match.start()) for marker in (".", "!", "?", ";", "\n")
        )
        sentence_end_candidates = tuple(
            position
            for marker in (".", "!", "?", ";", "\n")
            if (position := value.find(marker, match.end())) >= 0
        )
        sentence_end = min(sentence_end_candidates, default=len(value))
        before = value[max(sentence_start + 1, match.start() - 24) : match.start()]
        after = value[match.end() : min(sentence_end, match.end() + 128)]
        exclusion = _HUMAN_EXCLUSION.search(after)
        if (
            exclusion is not None
            and _HUMAN_AFFIRMATIVE_PREFIX.search(before) is None
            and _HUMAN_AFFIRMATIVE_ACTION.search(after[: exclusion.start()]) is None
        ):
            continue
        if re.search(r"(?:\b(?:no|without)\s+)$", before, re.IGNORECASE):
            continue
        return True
    return False


def _overlay_pointer(path: Path) -> LocalImageOverlayInput:
    metadata = _require_regular(path, maximum_bytes=8 * 1024 * 1024, mode=0o640)
    with path.open("rb") as source:
        header = source.read(26)
    if (
        len(header) != 26
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or header[12:16] != b"IHDR"
        or struct.unpack(">II", header[16:24]) != (800, 500)
        or header[24:26] != b"\x08\x06"
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    return LocalImageOverlayInput(size_bytes=metadata.st_size, sha256=sha256_file(path))


def _validate_handoff(
    workspace: Path,
    request: LocalImageCompositeRequest,
    provider_gid: int,
) -> LocalImageCompositeReceipt:
    try:
        provider_uid = pwd.getpwnam("eom-image").pw_uid
    except KeyError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    receipt_path = workspace / PROVIDER_RECEIPT_MEMBER
    value = _load_json(receipt_path, maximum_bytes=256 * 1024)
    try:
        validate_contract("composite-receipt", value)
        receipt = LocalImageCompositeReceipt.model_validate(value)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    generation_value = _load_json(workspace / "generation-receipt.json", maximum_bytes=256 * 1024)
    if (
        receipt.composite_request_sha256 != request.composite_request_sha256
        or receipt.generation.model_dump(mode="json") != generation_value
        or receipt.generation.request_sha256 != request.generation.request_sha256
        or receipt.generation.model != request.generation.model
        or receipt.generation.prompt_sha256 != request.generation.prompt_sha256
        or receipt.generation.negative_prompt_sha256 != request.generation.negative_prompt_sha256
        or receipt.generation.seed != request.generation.seed
        or receipt.generation.sampler != request.generation.sampler
        or receipt.overlay != request.overlay
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    expected = {
        BACKGROUND_MEMBER: receipt.generation.output.sha256,
        "generation-receipt.json": None,
        FINAL_MEMBER: receipt.output.sha256,
        PROVIDER_RECEIPT_MEMBER: None,
    }
    for name, expected_hash in expected.items():
        path = workspace / name
        _require_regular(
            path,
            maximum_bytes=8 * 1024 * 1024,
            mode=OUTPUT_MODE,
            uid=provider_uid,
            gid=provider_gid,
        )
        if expected_hash is not None and sha256_file(path) != expected_hash:
            raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    return receipt


def _validate_reference_handoff(
    workspace: Path,
    request: LocalImageReferenceConditionedCompositeRequest,
    provider_gid: int,
) -> LocalImageReferenceConditionedCompositeReceipt:
    try:
        provider_uid = pwd.getpwnam("eom-image").pw_uid
    except KeyError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    receipt_path = workspace / "reference-conditioned-receipt.json"
    value = _load_json(receipt_path, maximum_bytes=256 * 1024)
    try:
        validate_contract("reference-conditioned-composite-receipt", value)
        receipt = LocalImageReferenceConditionedCompositeReceipt.model_validate(value)
        validate_reference_conditioned_receipt(request, receipt)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    composite = _validate_handoff(workspace, request.composite_request, provider_gid)
    if receipt.composite_receipt != composite:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    reference = request.visual_reference.reference_member
    reference_path = workspace / reference.member_path
    metadata = _require_regular(
        reference_path,
        maximum_bytes=8 * 1024 * 1024,
        mode=INPUT_MODE,
        uid=os.geteuid(),
        gid=provider_gid,
    )
    if metadata.st_size != reference.size_bytes or sha256_file(reference_path) != reference.sha256:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    _require_regular(
        receipt_path,
        maximum_bytes=256 * 1024,
        mode=OUTPUT_MODE,
        uid=provider_uid,
        gid=provider_gid,
    )
    return receipt


def _validate_reference_handoff_v2(
    workspace: Path,
    request: LocalImageReferenceConditionedCompositeRequestV2,
    provider_gid: int,
) -> LocalImageReferenceConditionedCompositeReceiptV2:
    try:
        provider_uid = pwd.getpwnam("eom-image").pw_uid
    except KeyError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    receipt_path = workspace / "reference-conditioned-receipt.json"
    value = _load_json(receipt_path, maximum_bytes=512 * 1024)
    try:
        validate_contract("reference-conditioned-composite-receipt-v2", value)
        receipt = LocalImageReferenceConditionedCompositeReceiptV2.model_validate(value)
        validate_reference_conditioned_receipt_v2(request, receipt)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    composite = _validate_handoff(workspace, request.composite_request, provider_gid)
    if receipt.composite_receipt != composite:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    reference = request.visual_reference.reference_member
    reference_path = workspace / reference.member_path
    metadata = _require_regular(
        reference_path,
        maximum_bytes=8 * 1024 * 1024,
        mode=INPUT_MODE,
        uid=os.geteuid(),
        gid=provider_gid,
    )
    if metadata.st_size != reference.size_bytes or sha256_file(reference_path) != reference.sha256:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    _require_regular(
        receipt_path,
        maximum_bytes=512 * 1024,
        mode=OUTPUT_MODE,
        uid=provider_uid,
        gid=provider_gid,
    )
    return receipt


def _validate_reference_handoff_v3(
    workspace: Path,
    request: LocalImageReferenceConditionedCompositeRequestV3,
    provider_gid: int,
) -> LocalImageReferenceConditionedCompositeReceiptV3:
    try:
        provider_uid = pwd.getpwnam("eom-image").pw_uid
    except KeyError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    receipt_path = workspace / "reference-conditioned-receipt.json"
    value = _load_json(receipt_path, maximum_bytes=512 * 1024)
    try:
        validate_contract("reference-conditioned-composite-receipt-v3", value)
        receipt = LocalImageReferenceConditionedCompositeReceiptV3.model_validate(value)
        validate_reference_conditioned_receipt_v3(request, receipt)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    composite = _validate_handoff(workspace, request.composite_request, provider_gid)
    if receipt.composite_receipt != composite:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    reference = request.visual_reference.reference_member
    reference_path = workspace / reference.member_path
    metadata = _require_regular(
        reference_path,
        maximum_bytes=8 * 1024 * 1024,
        mode=INPUT_MODE,
        uid=os.geteuid(),
        gid=provider_gid,
    )
    if metadata.st_size != reference.size_bytes or sha256_file(reference_path) != reference.sha256:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    conditioning_path = workspace / receipt.conditioning_output.member_path
    conditioning_metadata = _require_regular(
        conditioning_path,
        maximum_bytes=8 * 1024 * 1024,
        mode=OUTPUT_MODE,
        uid=provider_uid,
        gid=provider_gid,
    )
    if (
        conditioning_metadata.st_size != receipt.conditioning_output.size_bytes
        or sha256_file(conditioning_path) != receipt.conditioning_output.sha256
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    with conditioning_path.open("rb") as source:
        conditioning_header = source.read(26)
    if (
        len(conditioning_header) != 26
        or conditioning_header[:8] != b"\x89PNG\r\n\x1a\n"
        or conditioning_header[12:16] != b"IHDR"
        or struct.unpack(">II", conditioning_header[16:24]) != (800, 504)
        or conditioning_header[24:26] != b"\x08\x02"
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    _require_regular(
        receipt_path,
        maximum_bytes=512 * 1024,
        mode=OUTPUT_MODE,
        uid=provider_uid,
        gid=provider_gid,
    )
    return receipt


def _validate_reference_handoff_v4(
    workspace: Path,
    request: LocalImageReferenceConditionedCompositeRequestV4,
    provider_gid: int,
) -> LocalImageReferenceConditionedCompositeReceiptV4:
    try:
        provider_uid = pwd.getpwnam("eom-image").pw_uid
    except KeyError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    receipt_path = workspace / "reference-conditioned-receipt.json"
    value = _load_json(receipt_path, maximum_bytes=512 * 1024)
    try:
        validate_contract("reference-conditioned-composite-receipt-v4", value)
        receipt = LocalImageReferenceConditionedCompositeReceiptV4.model_validate(value)
        validate_reference_conditioned_receipt_v4(request, receipt)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    composite = _validate_handoff(workspace, request.composite_request, provider_gid)
    if receipt.composite_receipt != composite:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    reference = request.visual_reference.reference_member
    reference_path = workspace / reference.member_path
    metadata = _require_regular(
        reference_path,
        maximum_bytes=8 * 1024 * 1024,
        mode=INPUT_MODE,
        uid=os.geteuid(),
        gid=provider_gid,
    )
    if metadata.st_size != reference.size_bytes or sha256_file(reference_path) != reference.sha256:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    conditioning_path = workspace / receipt.conditioning_output.member_path
    conditioning_metadata = _require_regular(
        conditioning_path,
        maximum_bytes=8 * 1024 * 1024,
        mode=OUTPUT_MODE,
        uid=provider_uid,
        gid=provider_gid,
    )
    if (
        conditioning_metadata.st_size != receipt.conditioning_output.size_bytes
        or sha256_file(conditioning_path) != receipt.conditioning_output.sha256
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    with conditioning_path.open("rb") as source:
        conditioning_header = source.read(26)
    if (
        len(conditioning_header) != 26
        or conditioning_header[:8] != b"\x89PNG\r\n\x1a\n"
        or conditioning_header[12:16] != b"IHDR"
        or struct.unpack(">II", conditioning_header[16:24]) != (800, 504)
        or conditioning_header[24:26] != b"\x08\x02"
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    _require_regular(
        receipt_path,
        maximum_bytes=512 * 1024,
        mode=OUTPUT_MODE,
        uid=provider_uid,
        gid=provider_gid,
    )
    return receipt


def _prepare_workspace(root: Path, request_id: str, provider_gid: int) -> Path:
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    if (
        root.is_symlink()
        or not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != 0
        or root_metadata.st_gid != provider_gid
        or stat.S_IMODE(root_metadata.st_mode) != WORKSPACE_ROOT_MODE
        or provider_gid not in {os.getegid(), *os.getgroups()}
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")
    workspace = root / request_id
    if not workspace.exists() and not workspace.is_symlink():
        try:
            workspace.mkdir(mode=0o700)
            _finalize_owned_directory(workspace, provider_gid, WORKSPACE_MODE)
        except OSError as exc:
            raise LocalImageAdapterError("LOCAL_IMAGE_HANDOFF_INVALID") from exc
    metadata = workspace.lstat()
    if (
        workspace.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != provider_gid
        or stat.S_IMODE(metadata.st_mode) != WORKSPACE_MODE
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_HANDOFF_INVALID")
    return workspace


def _prepare_input_directory(path: Path, workspace: Path, provider_gid: int) -> None:
    try:
        path.relative_to(workspace)
        if not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700, parents=True)
        descriptor = os.open(
            path,
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise OSError("unsafe local image input directory")
            os.fchown(descriptor, -1, provider_gid)
            os.fchmod(descriptor, 0o750)
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_HANDOFF_INVALID") from exc


def _stage_exact_file(
    path: Path,
    payload: bytes,
    provider_gid: int,
    *,
    maximum_bytes: int = 128 * 1024,
) -> None:
    if not 0 < len(payload) <= maximum_bytes:
        raise LocalImageAdapterError("LOCAL_IMAGE_HANDOFF_INVALID")
    if path.exists() or path.is_symlink():
        metadata = _require_regular(
            path,
            maximum_bytes=maximum_bytes,
            mode=INPUT_MODE,
            uid=os.geteuid(),
            gid=provider_gid,
        )
        if metadata.st_size != len(payload) or path.read_bytes() != payload:
            raise LocalImageAdapterError("LOCAL_IMAGE_HANDOFF_INVALID")
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        INPUT_MODE,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.fchown(descriptor, -1, provider_gid)
        os.fchmod(descriptor, INPUT_MODE)
    finally:
        os.close(descriptor)


def _stage_exact_source(path: Path, source: Path, provider_gid: int) -> None:
    source_metadata = _require_regular(source, maximum_bytes=8 * 1024 * 1024, mode=0o640)
    if path.exists() or path.is_symlink():
        metadata = _require_regular(
            path,
            maximum_bytes=8 * 1024 * 1024,
            mode=INPUT_MODE,
            uid=os.geteuid(),
            gid=provider_gid,
        )
        if metadata.st_size != source_metadata.st_size or sha256_file(path) != sha256_file(source):
            raise LocalImageAdapterError("LOCAL_IMAGE_HANDOFF_INVALID")
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        INPUT_MODE,
    )
    try:
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb", closefd=False) as target:
            shutil.copyfileobj(input_file, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        os.fchown(descriptor, -1, provider_gid)
        os.fchmod(descriptor, INPUT_MODE)
    finally:
        os.close(descriptor)


def _copy_result(source: Path, target: Path) -> None:
    payload_hash = sha256_file(source)
    if target.exists() or target.is_symlink():
        _require_regular(target, maximum_bytes=8 * 1024 * 1024, mode=0o640)
        if sha256_file(target) != payload_hash:
            raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
        return
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o640,
    )
    try:
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb", closefd=False) as output:
            shutil.copyfileobj(input_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)
    if sha256_file(target) != payload_hash:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")


def _run_fixed_unit(unit_name: str, timeout_seconds: int) -> None:
    try:
        completed = subprocess.run(
            [str(SYSTEMCTL), "--no-ask-password", "--wait", "start", unit_name],
            capture_output=True,
            timeout=timeout_seconds + 30,
            check=False,
            env=SYSTEMCTL_ENV,
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_PROVIDER_TIMEOUT") from exc
    if completed.returncode != 0:
        raise LocalImageAdapterError("LOCAL_IMAGE_PROVIDER_FAILED")


def _provider_group_id(group_name: str) -> int:
    try:
        return grp.getgrnam(group_name).gr_gid
    except KeyError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc


def _finalize_owned_directory(path: Path, group_id: int, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise OSError("unsafe local image workspace")
        os.fchown(descriptor, -1, group_id)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _require_regular(
    path: Path,
    *,
    maximum_bytes: int,
    mode: int,
    uid: int | None = None,
    gid: int | None = None,
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= maximum_bytes
        or stat.S_IMODE(metadata.st_mode) != mode
        or (uid is not None and metadata.st_uid != uid)
        or (gid is not None and metadata.st_gid != gid)
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    return metadata


def _require_absolute_components(path: Path) -> None:
    if not path.is_absolute():
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")


def _load_json(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink() or metadata.st_size > maximum_bytes:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
            value[key] = item
        return value

    try:
        loaded = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    if not isinstance(loaded, dict):
        raise LocalImageAdapterError("LOCAL_IMAGE_OUTPUT_INVALID")
    return loaded


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
