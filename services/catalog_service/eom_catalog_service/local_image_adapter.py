"""Fixed-unit local GPU background adapter owned by the Catalog use case."""

from __future__ import annotations

import grp
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
from typing import Final

from eom_identifiers import sha256_file
from eom_image_contracts import (
    LocalImageCompositeReceipt,
    LocalImageCompositeRequest,
    LocalImageGenerationRequest,
    LocalImageOverlayInput,
    LocalImageProviderBinding,
    content_sha256,
    text_sha256,
    validate_contract,
)
from eom_workflow.models import GeneratedVectorDrawingV5

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
_SAFE_BACKGROUND_PREFIX: Final = (
    "Non-authoritative background layer only. Render no text, labels, numbers, symbols, "
    "equations, graphs, scales, measurement marks, logos, or watermarks. "
)
_SAFE_NEGATIVE_PROMPT: Final = (
    "text, letters, labels, numbers, symbols, equations, graph axes, scale marks, "
    "measurement marks, logo, watermark"
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


def load_local_image_provider_binding(
    path: Path,
    *,
    trusted_owner_uid: int = 0,
    trusted_group_ids: tuple[int, ...] | None = None,
) -> LocalImageProviderBinding:
    """Load one root-controlled binding without following a symlink."""

    _require_absolute_components(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc
    group_ids = (
        tuple({os.getegid(), *os.getgroups()}) if trusted_group_ids is None else trusted_group_ids
    )
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != trusted_owner_uid
        or metadata.st_gid not in group_ids
        or stat.S_IMODE(metadata.st_mode) != 0o640
        or not 0 < metadata.st_size <= 64 * 1024
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")
    value = _load_json(path, maximum_bytes=64 * 1024)
    try:
        validate_contract("provider-binding", value)
        return LocalImageProviderBinding.model_validate(value)
    except Exception as exc:
        raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED") from exc


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
        drawing: GeneratedVectorDrawingV5,
        overlay_path: Path,
        binding: LocalImageProviderBinding,
        output_directory: Path,
    ) -> LocalImageMaterialization:
        if drawing.production_route != "LOCAL_GENERATIVE_BACKGROUND":
            raise LocalImageAdapterError("LOCAL_IMAGE_ROUTE_UNDEPLOYED")
        request = _build_request(
            workflow_id=workflow_id,
            result_revision_id=result_revision_id,
            drawing_hash=drawing_hash,
            drawing=drawing,
            binding=binding,
            overlay_path=overlay_path,
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
        )


def _build_request(
    *,
    workflow_id: str,
    result_revision_id: str,
    drawing_hash: str,
    drawing: GeneratedVectorDrawingV5,
    binding: LocalImageProviderBinding,
    overlay_path: Path,
) -> LocalImageCompositeRequest:
    if (
        _WORKFLOW_ID.fullmatch(workflow_id) is None
        or _REVISION_ID.fullmatch(result_revision_id) is None
        or _SHA256.fullmatch(drawing_hash) is None
    ):
        raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
    prompt = _SAFE_BACKGROUND_PREFIX + drawing.generation_prompt
    negative = (
        _SAFE_NEGATIVE_PROMPT
        if drawing.negative_prompt is None
        else _SAFE_NEGATIVE_PROMPT + ", " + drawing.negative_prompt
    )
    if len(prompt) > 4000 or len(negative) > 2000:
        raise LocalImageAdapterError("LOCAL_IMAGE_INPUT_INVALID")
    identity = content_sha256(
        {
            "workflow_id": workflow_id,
            "result_revision_id": result_revision_id,
            "drawing_sha256": drawing_hash,
            "binding_sha256": binding.binding_sha256,
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
        "prompt_sha256": text_sha256(prompt),
        "negative_prompt": negative,
        "negative_prompt_sha256": text_sha256(negative),
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


def _stage_exact_file(path: Path, payload: bytes, provider_gid: int) -> None:
    if path.exists() or path.is_symlink():
        metadata = _require_regular(
            path,
            maximum_bytes=128 * 1024,
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
