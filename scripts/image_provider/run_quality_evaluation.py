#!/usr/bin/env python3
"""Run one bounded, non-production local-image quality evaluation."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import pwd
import shutil
import stat
import struct
import subprocess
import zlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from eom_image_contracts import (
    ImageEvaluationMetrics,
    LocalImageCompositeReceipt,
    LocalImageCompositeRequest,
    LocalImageGenerationRequest,
    LocalImageOverlayInput,
    LocalImageQualityEvaluationPlan,
    LocalImageQualityEvaluationResult,
    content_sha256,
    validate_contract,
    validate_quality_evaluation_result,
)
from PIL import Image, ImageDraw, ImageOps

WORKSPACE_ROOT = Path("/srv/eom/image-workspaces")
UNIT_SOURCE = Path("/home/eom/EOM/infra/systemd/eom-image-provider@.service")
UNIT_INSTALLED = Path("/etc/systemd/system/eom-image-provider@.service")
BINDING_INSTALLED = Path("/etc/eom/local-image-provider.json")
SYSTEMCTL = Path("/usr/bin/systemctl")
TESSERACT = Path("/usr/bin/tesseract")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PNG_BYTES = 64 * 1024 * 1024
OUTPUT_ROOT_NAME = "outputs"
RESULT_MEMBER = "result.json"
CONTACT_SHEET_MEMBER = "contact-sheet.png"
REFERENCE_METRICS_MEMBER = "reference-metrics.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-root", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--finalize-existing", action="store_true")
    return parser


def _json_bytes(value: object) -> bytes:
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


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise SystemExit("IMAGE_EVAL_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _load_json(path: Path, maximum_bytes: int) -> dict[str, object]:
    payload = _read_regular(path, maximum_bytes=maximum_bytes)
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON value")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit("IMAGE_EVAL_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise SystemExit("IMAGE_EVAL_JSON_INVALID")
    return value


def _read_regular(
    path: Path,
    *,
    maximum_bytes: int,
    expected_mode: int | None = None,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or (expected_mode is not None and stat.S_IMODE(before.st_mode) != expected_mode)
            or (expected_uid is not None and before.st_uid != expected_uid)
            or (expected_gid is not None and before.st_gid != expected_gid)
        ):
            raise SystemExit("IMAGE_EVAL_FILE_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise SystemExit("IMAGE_EVAL_FILE_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_identity != after_identity:
            raise SystemExit("IMAGE_EVAL_FILE_CHANGED")
    finally:
        os.close(descriptor)
    return bytes(payload)


def _write_exclusive(path: Path, payload: bytes, *, uid: int, gid: int, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _transparent_overlay_png() -> bytes:
    width, height = 800, 500
    rows = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))

    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(rows, level=9)),
            chunk(b"IEND", b""),
        )
    )


def _request_for(
    plan: LocalImageQualityEvaluationPlan,
    sample_id: str,
    variant_id: str,
) -> LocalImageCompositeRequest:
    sample = next(sample for sample in plan.samples if sample.sample_id == sample_id)
    prompt = next(prompt for prompt in sample.prompts if prompt.variant_id == variant_id)
    identity = content_sha256(
        {
            "evaluation_id": plan.evaluation_id,
            "plan_sha256": plan.plan_sha256,
            "sample_id": sample.sample_id,
            "variant_id": prompt.variant_id,
            "prompt_sha256": prompt.positive_prompt_sha256,
            "negative_prompt_sha256": prompt.negative_prompt_sha256,
            "seed": sample.seed,
            "binding_sha256": plan.provider_binding.binding_sha256,
        }
    ).removeprefix("sha256:")
    generation_body = {
        "schema_version": "local-image-generation-request/1.0",
        "request_id": "imgreq_" + identity[:32],
        "idempotency_key": "image-quality-evaluation:" + identity,
        "model": plan.provider_binding.model.model_dump(mode="json"),
        "prompt": prompt.positive_prompt,
        "prompt_sha256": prompt.positive_prompt_sha256,
        "negative_prompt": prompt.negative_prompt,
        "negative_prompt_sha256": prompt.negative_prompt_sha256,
        "seed": sample.seed,
        "sampler": plan.provider_binding.sampler.model_dump(mode="json"),
        "generation_canvas": {"width_px": 800, "height_px": 504},
        "delivery_canvas": {"width_px": 800, "height_px": 500},
        "output_member": "generated-background.png",
        "timeout_seconds": plan.provider_binding.timeout_seconds,
    }
    generation = LocalImageGenerationRequest.model_validate(
        {**generation_body, "request_sha256": content_sha256(generation_body)}
    )
    overlay_bytes = _transparent_overlay_png()
    overlay = LocalImageOverlayInput.model_validate(
        {
            "member_path": "generated-overlay.png",
            "media_type": "image/png",
            "width_px": 800,
            "height_px": 500,
            "mode": "RGBA",
            "size_bytes": len(overlay_bytes),
            "sha256": "sha256:" + hashlib.sha256(overlay_bytes).hexdigest(),
        }
    )
    body = {
        "schema_version": "local-image-composite-request/1.0",
        "generation": generation.model_dump(mode="json"),
        "overlay": overlay.model_dump(mode="json"),
        "final_output_member": "generated-stimulus.png",
    }
    request = LocalImageCompositeRequest.model_validate(
        {**body, "composite_request_sha256": content_sha256(body)}
    )
    validate_contract("composite-request", request.model_dump(mode="json"))
    return request


def _require_root_directory(path: Path, *, uid: int, gid: int, mode: int) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != uid
        or metadata.st_gid != gid
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise SystemExit("IMAGE_EVAL_DIRECTORY_INVALID")


def _preflight(
    evaluation_root: Path,
    *,
    allow_existing_outputs: bool = False,
) -> tuple[LocalImageQualityEvaluationPlan, dict[str, object], int, int]:
    account = pwd.getpwnam("eom")
    if not evaluation_root.is_absolute() or not evaluation_root.name.startswith(
        "eom-local-image-quality-eval-"
    ):
        raise SystemExit("IMAGE_EVAL_ROOT_INVALID")
    _require_root_directory(evaluation_root, uid=account.pw_uid, gid=account.pw_gid, mode=0o700)
    if UNIT_SOURCE.read_bytes() != UNIT_INSTALLED.read_bytes():
        raise SystemExit("IMAGE_EVAL_PROVIDER_UNIT_DRIFT")
    workspace_metadata = WORKSPACE_ROOT.lstat()
    provider_gid = __import__("grp").getgrnam("eom-image").gr_gid
    if (
        WORKSPACE_ROOT.is_symlink()
        or not stat.S_ISDIR(workspace_metadata.st_mode)
        or workspace_metadata.st_uid != 0
        or workspace_metadata.st_gid != provider_gid
        or stat.S_IMODE(workspace_metadata.st_mode) != 0o3770
    ):
        raise SystemExit("IMAGE_EVAL_WORKSPACE_ROOT_INVALID")
    plan_value = _load_json(evaluation_root / "plan.json", MAX_JSON_BYTES)
    validate_contract("quality-evaluation-plan", plan_value)
    plan = LocalImageQualityEvaluationPlan.model_validate(plan_value)
    binding_value = _load_json(BINDING_INSTALLED, 64 * 1024)
    validate_contract("provider-binding", binding_value)
    if binding_value != plan.provider_binding.model_dump(mode="json"):
        raise SystemExit("IMAGE_EVAL_PROVIDER_BINDING_DRIFT")
    index = _load_json(evaluation_root / "reference-index.json", MAX_JSON_BYTES)
    expected_samples = {sample.sample_id for sample in plan.samples}
    if set(index) != expected_samples:
        raise SystemExit("IMAGE_EVAL_REFERENCE_INDEX_INVALID")
    for sample in plan.samples:
        entry = index[sample.sample_id]
        if not isinstance(entry, dict):
            raise SystemExit("IMAGE_EVAL_REFERENCE_INDEX_INVALID")
        member = entry.get("page_member")
        page_sha256 = entry.get("page_sha256")
        if not isinstance(member, str) or not member.startswith("references/"):
            raise SystemExit("IMAGE_EVAL_REFERENCE_INDEX_INVALID")
        path = evaluation_root / member
        payload = _read_regular(
            path,
            maximum_bytes=MAX_PNG_BYTES,
            expected_mode=0o600,
            expected_uid=account.pw_uid,
        )
        if "sha256:" + hashlib.sha256(payload).hexdigest() != page_sha256:
            raise SystemExit("IMAGE_EVAL_REFERENCE_HASH_MISMATCH")
        if page_sha256 != sample.source_page_image.sha256:
            raise SystemExit("IMAGE_EVAL_REFERENCE_POINTER_MISMATCH")
        if entry.get("bounding_box") != (
            None if sample.bounding_box is None else sample.bounding_box.model_dump(mode="json")
        ):
            raise SystemExit("IMAGE_EVAL_REFERENCE_POINTER_MISMATCH")
        for variant in plan.variants:
            _request_for(plan, sample.sample_id, variant.variant_id)
    output_targets = tuple(
        evaluation_root / name
        for name in (
            OUTPUT_ROOT_NAME,
            RESULT_MEMBER,
            CONTACT_SHEET_MEMBER,
            REFERENCE_METRICS_MEMBER,
        )
    )
    if allow_existing_outputs:
        if not output_targets[0].is_dir() or not output_targets[1].is_file():
            raise SystemExit("IMAGE_EVAL_EXISTING_OUTPUT_MISSING")
        if any(target.exists() or target.is_symlink() for target in output_targets[2:]):
            raise SystemExit("IMAGE_EVAL_FINAL_OUTPUT_ALREADY_EXISTS")
    elif any(target.exists() or target.is_symlink() for target in output_targets):
        raise SystemExit("IMAGE_EVAL_OUTPUT_ALREADY_EXISTS")
    active = subprocess.run(
        [
            str(SYSTEMCTL),
            "list-units",
            "--state=activating,active",
            "--no-legend",
            "eom-image-provider@*.service",
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if active.returncode != 0 or active.stdout.strip():
        raise SystemExit("IMAGE_EVAL_PROVIDER_BUSY")
    return plan, index, account.pw_uid, account.pw_gid


def _stage_request(request: LocalImageCompositeRequest, provider_gid: int) -> Path:
    workspace = WORKSPACE_ROOT / request.generation.request_id
    if workspace.exists() or workspace.is_symlink():
        raise SystemExit("IMAGE_EVAL_WORKSPACE_COLLISION")
    workspace.mkdir(mode=0o700)
    os.chown(workspace, 0, provider_gid)
    os.chmod(workspace, 0o1730)
    _write_exclusive(
        workspace / "request.json",
        _json_bytes(request.model_dump(mode="json")),
        uid=0,
        gid=provider_gid,
        mode=0o440,
    )
    _write_exclusive(
        workspace / "generated-overlay.png",
        _transparent_overlay_png(),
        uid=0,
        gid=provider_gid,
        mode=0o440,
    )
    return workspace


def _run_unit(request: LocalImageCompositeRequest) -> None:
    completed = subprocess.run(
        [
            str(SYSTEMCTL),
            "--no-ask-password",
            "--wait",
            "start",
            f"eom-image-provider@{request.generation.request_id}.service",
        ],
        capture_output=True,
        check=False,
        timeout=request.generation.timeout_seconds + 30,
    )
    if completed.returncode != 0:
        raise SystemExit("IMAGE_EVAL_PROVIDER_FAILED")


def _validate_receipt(
    workspace: Path,
    request: LocalImageCompositeRequest,
) -> LocalImageCompositeReceipt:
    provider = pwd.getpwnam("eom-image")
    provider_gid = __import__("grp").getgrnam("eom-image").gr_gid
    for name, maximum_bytes in (
        ("composite-receipt.json", 256 * 1024),
        ("generation-receipt.json", 256 * 1024),
        ("generated-background.png", 8 * 1024 * 1024),
        ("generated-stimulus.png", 8 * 1024 * 1024),
    ):
        _read_regular(
            workspace / name,
            maximum_bytes=maximum_bytes,
            expected_mode=0o640,
            expected_uid=provider.pw_uid,
            expected_gid=provider_gid,
        )
    value = _load_json(workspace / "composite-receipt.json", 256 * 1024)
    validate_contract("composite-receipt", value)
    receipt = LocalImageCompositeReceipt.model_validate(value)
    generation_value = _load_json(workspace / "generation-receipt.json", 256 * 1024)
    if (
        receipt.composite_request_sha256 != request.composite_request_sha256
        or receipt.generation.model_dump(mode="json") != generation_value
        or receipt.generation.request_sha256 != request.generation.request_sha256
        or receipt.generation.output.sha256
        != "sha256:"
        + hashlib.sha256(
            _read_regular(workspace / "generated-background.png", maximum_bytes=8 * 1024 * 1024)
        ).hexdigest()
    ):
        raise SystemExit("IMAGE_EVAL_PROVIDER_OUTPUT_INVALID")
    return receipt


def _ocr_glyph_count(path: Path) -> int:
    if not TESSERACT.is_file():
        raise SystemExit("IMAGE_EVAL_OCR_UNAVAILABLE")
    completed = subprocess.run(
        [str(TESSERACT), str(path), "stdout", "-l", "eng+kor", "--psm", "6"],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise SystemExit("IMAGE_EVAL_OCR_FAILED")
    try:
        text = completed.stdout.decode("utf-8")
    except UnicodeError as exc:
        raise SystemExit("IMAGE_EVAL_OCR_FAILED") from exc
    return min(sum(1 for character in text if character.isalnum()), 10_000)


def _metrics(path: Path, *, require_delivery_canvas: bool = True) -> ImageEvaluationMetrics:
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
    if require_delivery_canvas and image.size != (800, 500):
        raise SystemExit("IMAGE_EVAL_OUTPUT_DIMENSIONS_INVALID")
    # Weighted RGB luminance reaches 255000 before division; int16 silently wraps it.
    # int32 keeps the metric exact while remaining negligible for the bounded 800x500 canvas.
    pixels = np.asarray(image, dtype=np.int32)
    channel_span = pixels.max(axis=2) - pixels.min(axis=2)
    grayscale = channel_span <= 3
    white = pixels.min(axis=2) >= 245
    luminance = (pixels[:, :, 0] * 299 + pixels[:, :, 1] * 587 + pixels[:, :, 2] * 114) // 1000
    dark = luminance <= 64
    horizontal = np.abs(np.diff(luminance, axis=1)) > 24
    vertical = np.abs(np.diff(luminance, axis=0)) > 24
    edge_pixels = int(horizontal.sum()) + int(vertical.sum())
    edge_denominator = horizontal.size + vertical.size
    ink = luminance < 245
    if ink.any():
        y_values, x_values = np.nonzero(ink)
        coverage = (
            (int(x_values.max()) - int(x_values.min()) + 1)
            * (int(y_values.max()) - int(y_values.min()) + 1)
        ) / ink.size
    else:
        coverage = 0.0
    return ImageEvaluationMetrics(
        grayscale_fraction_milli=round(float(grayscale.mean()) * 1000),
        white_background_fraction_milli=round(float(white.mean()) * 1000),
        dark_ink_fraction_milli=round(float(dark.mean()) * 1000),
        edge_fraction_milli=round(edge_pixels / edge_denominator * 1000),
        ink_bbox_coverage_milli=round(coverage * 1000),
        ocr_glyph_count=_ocr_glyph_count(path),
    )


def _reference_crop(
    evaluation_root: Path,
    index: dict[str, object],
    sample_id: str,
) -> Image.Image:
    entry = index[sample_id]
    if not isinstance(entry, dict) or not isinstance(entry.get("page_member"), str):
        raise SystemExit("IMAGE_EVAL_REFERENCE_INDEX_INVALID")
    with Image.open(evaluation_root / str(entry["page_member"])) as opened:
        opened.load()
        image = opened.convert("RGB")
    bounding_box = entry.get("bounding_box")
    if isinstance(bounding_box, dict):
        left = bounding_box.get("left")
        top = bounding_box.get("top")
        right = bounding_box.get("right")
        bottom = bounding_box.get("bottom")
        if all(isinstance(value, int) for value in (left, top, right, bottom)):
            assert isinstance(left, int)
            assert isinstance(top, int)
            assert isinstance(right, int)
            assert isinstance(bottom, int)
            width, height = image.size
            crop = (
                max(0, min(width - 1, round(left / 10_000 * width))),
                max(0, min(height - 1, round(top / 10_000 * height))),
                max(1, min(width, round(right / 10_000 * width))),
                max(1, min(height, round(bottom / 10_000 * height))),
            )
            if crop[2] > crop[0] and crop[3] > crop[1]:
                image = image.crop(crop)
    return image


def _tile(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.pad(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, color="white")


def _contact_sheet(
    evaluation_root: Path,
    plan: LocalImageQualityEvaluationPlan,
    index: dict[str, object],
) -> bytes:
    tile_size = (360, 225)
    header_height = 30
    sheet = Image.new(
        "RGB",
        (tile_size[0] * 4, (tile_size[1] + header_height) * len(plan.samples)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    labels = ("REFERENCE", "CURRENT_KO", "ENGLISH_SUBJECT", "ASSESSMENT_STYLE_EN")
    for row, sample in enumerate(plan.samples):
        images = [_reference_crop(evaluation_root, index, sample.sample_id)]
        for variant_id in labels[1:]:
            images.append(
                Image.open(
                    evaluation_root / OUTPUT_ROOT_NAME / sample.sample_id / f"{variant_id}.png"
                ).convert("RGB")
            )
        top = row * (tile_size[1] + header_height)
        for column, (label, image) in enumerate(zip(labels, images, strict=True)):
            left = column * tile_size[0]
            draw.text((left + 6, top + 7), f"{row + 1:02d} {label}", fill="black")
            sheet.paste(_tile(image, tile_size), (left, top + header_height))
            image.close()
    from io import BytesIO

    buffer = BytesIO()
    sheet.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _reference_metrics(
    evaluation_root: Path,
    plan: LocalImageQualityEvaluationPlan,
    index: dict[str, object],
    *,
    eom_uid: int,
    eom_gid: int,
) -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for sample in plan.samples:
        reference = _reference_crop(evaluation_root, index, sample.sample_id)
        temporary = evaluation_root / f".reference-{sample.sample_id}.png"
        if temporary.exists() or temporary.is_symlink():
            raise SystemExit("IMAGE_EVAL_TEMPORARY_COLLISION")
        reference.save(temporary, format="PNG")
        os.chown(temporary, eom_uid, eom_gid)
        os.chmod(temporary, 0o600)
        reference.close()
        try:
            values[sample.sample_id] = _metrics(
                temporary,
                require_delivery_canvas=False,
            ).model_dump(mode="json")
        finally:
            temporary.unlink(missing_ok=True)
    return values


def _finalize_existing(
    evaluation_root: Path,
    plan: LocalImageQualityEvaluationPlan,
    index: dict[str, object],
    *,
    eom_uid: int,
    eom_gid: int,
) -> LocalImageQualityEvaluationResult:
    value = _load_json(evaluation_root / RESULT_MEMBER, MAX_JSON_BYTES)
    validate_contract("quality-evaluation-result", value)
    result = LocalImageQualityEvaluationResult.model_validate(value)
    validate_quality_evaluation_result(plan, result)
    output_paths = {
        path.relative_to(evaluation_root / OUTPUT_ROOT_NAME).as_posix()
        for path in (evaluation_root / OUTPUT_ROOT_NAME).glob("*/*.png")
        if path.is_file() and not path.is_symlink()
    }
    expected_paths = {f"{output.sample_id}/{output.variant_id}.png" for output in result.outputs}
    if output_paths != expected_paths:
        raise SystemExit("IMAGE_EVAL_EXISTING_OUTPUT_SET_INVALID")
    provider_gid = __import__("grp").getgrnam("eom-image").gr_gid
    validated_workspaces: list[Path] = []
    for output in result.outputs:
        target = evaluation_root / OUTPUT_ROOT_NAME / output.sample_id / f"{output.variant_id}.png"
        payload = _read_regular(
            target,
            maximum_bytes=8 * 1024 * 1024,
            expected_mode=0o600,
            expected_uid=eom_uid,
            expected_gid=eom_gid,
        )
        if "sha256:" + hashlib.sha256(payload).hexdigest() != output.receipt.output.sha256:
            raise SystemExit("IMAGE_EVAL_EXISTING_OUTPUT_HASH_MISMATCH")
        if _metrics(target) != output.metrics:
            raise SystemExit("IMAGE_EVAL_EXISTING_METRICS_MISMATCH")
        request = _request_for(plan, output.sample_id, output.variant_id)
        if request.generation != output.request:
            raise SystemExit("IMAGE_EVAL_EXISTING_REQUEST_MISMATCH")
        workspace = WORKSPACE_ROOT / output.request.request_id
        metadata = workspace.lstat()
        if (
            workspace.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != provider_gid
            or stat.S_IMODE(metadata.st_mode) != 0o1730
        ):
            raise SystemExit("IMAGE_EVAL_EXISTING_WORKSPACE_INVALID")
        receipt = _validate_receipt(workspace, request)
        if receipt.generation != output.receipt:
            raise SystemExit("IMAGE_EVAL_EXISTING_RECEIPT_MISMATCH")
        validated_workspaces.append(workspace)
    reference_metrics = _reference_metrics(
        evaluation_root,
        plan,
        index,
        eom_uid=eom_uid,
        eom_gid=eom_gid,
    )
    _write_exclusive(
        evaluation_root / REFERENCE_METRICS_MEMBER,
        _json_bytes(reference_metrics),
        uid=eom_uid,
        gid=eom_gid,
        mode=0o600,
    )
    _write_exclusive(
        evaluation_root / CONTACT_SHEET_MEMBER,
        _contact_sheet(evaluation_root, plan, index),
        uid=eom_uid,
        gid=eom_gid,
        mode=0o600,
    )
    for workspace in validated_workspaces:
        shutil.rmtree(workspace)
    return result


def main() -> None:
    args = _parser().parse_args()
    if args.preflight_only and args.finalize_existing:
        raise SystemExit("IMAGE_EVAL_OPERATION_INVALID")
    plan, index, eom_uid, eom_gid = _preflight(
        args.evaluation_root,
        allow_existing_outputs=args.finalize_existing,
    )
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "event": "LOCAL_IMAGE_QUALITY_EVALUATION_PREFLIGHT_PASS",
                    "evaluation_id": plan.evaluation_id,
                    "generation_count": len(plan.samples) * len(plan.variants),
                    "plan_sha256": plan.plan_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    if os.geteuid() != 0:
        raise SystemExit("IMAGE_EVAL_ROOT_REQUIRED")
    if args.finalize_existing:
        result = _finalize_existing(
            args.evaluation_root,
            plan,
            index,
            eom_uid=eom_uid,
            eom_gid=eom_gid,
        )
        print(
            json.dumps(
                {
                    "contact_sheet": str(args.evaluation_root / CONTACT_SHEET_MEMBER),
                    "event": "LOCAL_IMAGE_QUALITY_EVALUATION_FINALIZED",
                    "evaluation_id": plan.evaluation_id,
                    "output_count": len(result.outputs),
                    "result_sha256": result.result_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    provider_gid = __import__("grp").getgrnam("eom-image").gr_gid
    output_root = args.evaluation_root / OUTPUT_ROOT_NAME
    output_root.mkdir(mode=0o700)
    os.chown(output_root, eom_uid, eom_gid)
    os.chmod(output_root, 0o700)
    outputs: list[dict[str, object]] = []
    successful_workspaces: list[Path] = []
    try:
        for sample in plan.samples:
            sample_root = output_root / sample.sample_id
            sample_root.mkdir(mode=0o700)
            os.chown(sample_root, eom_uid, eom_gid)
            os.chmod(sample_root, 0o700)
            for variant in plan.variants:
                request = _request_for(plan, sample.sample_id, variant.variant_id)
                workspace = _stage_request(request, provider_gid)
                _run_unit(request)
                receipt = _validate_receipt(workspace, request)
                target = sample_root / f"{variant.variant_id}.png"
                payload = _read_regular(
                    workspace / "generated-background.png", maximum_bytes=8 * 1024 * 1024
                )
                _write_exclusive(target, payload, uid=eom_uid, gid=eom_gid, mode=0o600)
                metrics = _metrics(target)
                outputs.append(
                    {
                        "sample_id": sample.sample_id,
                        "variant_id": variant.variant_id,
                        "request": request.generation.model_dump(mode="json"),
                        "receipt": receipt.generation.model_dump(mode="json"),
                        "metrics": metrics.model_dump(mode="json"),
                        "manual_review": None,
                    }
                )
                successful_workspaces.append(workspace)
        outputs.sort(key=lambda value: (str(value["sample_id"]), str(value["variant_id"])))
        body = {
            "schema_version": "local-image-quality-evaluation-result/1.0",
            "evaluation_id": plan.evaluation_id,
            "plan_sha256": plan.plan_sha256,
            "status": "AUTOMATED_COMPLETE",
            "completed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "outputs": outputs,
        }
        result_value = {**body, "result_sha256": content_sha256(body)}
        validate_contract("quality-evaluation-result", result_value)
        result = LocalImageQualityEvaluationResult.model_validate(result_value)
        validate_quality_evaluation_result(plan, result)
        _write_exclusive(
            args.evaluation_root / RESULT_MEMBER,
            _json_bytes(result.model_dump(mode="json")),
            uid=eom_uid,
            gid=eom_gid,
            mode=0o600,
        )
        reference_metrics = _reference_metrics(
            args.evaluation_root,
            plan,
            index,
            eom_uid=eom_uid,
            eom_gid=eom_gid,
        )
        _write_exclusive(
            args.evaluation_root / REFERENCE_METRICS_MEMBER,
            _json_bytes(reference_metrics),
            uid=eom_uid,
            gid=eom_gid,
            mode=0o600,
        )
        _write_exclusive(
            args.evaluation_root / CONTACT_SHEET_MEMBER,
            _contact_sheet(args.evaluation_root, plan, index),
            uid=eom_uid,
            gid=eom_gid,
            mode=0o600,
        )
    except BaseException:
        raise
    else:
        for workspace in successful_workspaces:
            shutil.rmtree(workspace)
    print(
        json.dumps(
            {
                "contact_sheet": str(args.evaluation_root / CONTACT_SHEET_MEMBER),
                "event": "LOCAL_IMAGE_QUALITY_EVALUATION_AUTOMATED_COMPLETE",
                "evaluation_id": plan.evaluation_id,
                "output_count": len(outputs),
                "result_sha256": result.result_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
