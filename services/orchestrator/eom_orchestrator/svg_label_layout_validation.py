"""Orchestrator-owned fixed-renderer adapter for SVG label-layout validation."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, cast

from eom_identifiers import content_sha256
from eom_image_contracts import (
    SVG_LABEL_LAYOUT_FONT_SPECS,
    SVG_LABEL_LAYOUT_PACK_BUNDLE_SHA256,
    SVG_LABEL_LAYOUT_RENDERER_PATH,
    SvgLabelLayoutValidationError,
    SvgLabelLayoutValidationReceipt,
    svg_label_layout_font_manifest_sha256,
    validate_contract,
    validate_svg_label_layout,
)
from eom_workflow.models import ContentTeamImageRoleResultV12, GeneratedVectorDrawingV6
from jsonschema import ValidationError as JsonSchemaValidationError

_MAX_RENDERED_PNG_BYTES: Final = 16 * 1024 * 1024


@dataclass(frozen=True)
class _RendererIdentity:
    version: str
    sha256: str
    font_manifest_sha256: str


def validate_image_result_svg_label_layout(
    *,
    result: object,
    result_schema: str,
    plan_document: dict[str, object] | None,
) -> tuple[dict[str, object], ...]:
    """Return per-drawing receipts only for the immutable enforcing Content Pack."""

    if (
        result_schema != "image-result@12.0"
        or not isinstance(result, ContentTeamImageRoleResultV12)
        or plan_document is None
        or plan_document.get("content_pack_sha256") != SVG_LABEL_LAYOUT_PACK_BUNDLE_SHA256
    ):
        return ()
    try:
        identity = _renderer_identity()
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise SvgLabelLayoutValidationError(
            "SVG_LABEL_LAYOUT_RENDER_INVALID", "fixed SVG label runtime is unavailable"
        ) from exc
    receipts: list[dict[str, object]] = []
    for item in result.output.drawings:
        drawing = item.drawing
        if not isinstance(drawing, GeneratedVectorDrawingV6):
            continue
        receipt = validate_svg_label_layout(
            overlay=drawing.svg_overlay,
            required_labels=drawing.required_labels,
            render_svg=_render_svg,
            renderer_version=identity.version,
            renderer_sha256=identity.sha256,
            font_manifest_sha256=identity.font_manifest_sha256,
        )
        _validate_receipt_schema(receipt)
        receipts.append(
            {
                "visual_ordinal": item.visual_ordinal,
                "drawing_sha256": content_sha256(drawing.model_dump(mode="json")),
                "receipt": receipt.model_dump(mode="json"),
            }
        )
    return tuple(sorted(receipts, key=lambda item: cast(int, item["visual_ordinal"])))


def svg_label_layout_event_data(
    receipts: tuple[dict[str, object], ...],
) -> dict[str, object]:
    if not receipts:
        return {}
    return {"svg_label_layout_validation_receipts": list(receipts)}


def _validate_receipt_schema(receipt: SvgLabelLayoutValidationReceipt) -> None:
    try:
        validate_contract("svg-label-layout-validation-receipt", receipt.model_dump(mode="json"))
    except (JsonSchemaValidationError, ValueError) as exc:
        # The Pydantic model and JSON Schema are both authoritative at this boundary.
        raise SvgLabelLayoutValidationError(
            "SVG_LABEL_LAYOUT_RECEIPT_INVALID", "SVG label layout receipt schema drift"
        ) from exc


def _render_svg(payload: bytes) -> bytes:
    if not payload or len(payload) > 96 * 1024:
        raise ValueError("SVG label validation input size is invalid")
    try:
        completed = subprocess.run(
            [
                SVG_LABEL_LAYOUT_RENDERER_PATH,
                "--format=png",
                "--width=800",
                "--height=500",
            ],
            cwd="/",
            env={"HOME": "/nonexistent", "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except subprocess.SubprocessError as exc:
        raise ValueError("fixed SVG label validation renderer failed") from exc
    if completed.returncode != 0 or not 0 < len(completed.stdout) <= _MAX_RENDERED_PNG_BYTES:
        raise ValueError("fixed SVG label validation renderer failed")
    return completed.stdout


def _renderer_identity() -> _RendererIdentity:
    renderer_path = Path(SVG_LABEL_LAYOUT_RENDERER_PATH)
    renderer = renderer_path.lstat()
    if (
        renderer_path.is_symlink()
        or not stat.S_ISREG(renderer.st_mode)
        or renderer.st_uid != 0
        or stat.S_IMODE(renderer.st_mode) & 0o022
        or not os.access(renderer_path, os.X_OK)
    ):
        raise ValueError("fixed SVG renderer metadata is invalid")
    identities = [
        renderer.st_dev,
        renderer.st_ino,
        renderer.st_size,
        renderer.st_mtime_ns,
        renderer.st_ctime_ns,
    ]
    for specification in SVG_LABEL_LAYOUT_FONT_SPECS:
        path = Path(specification.path)
        font = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(font.st_mode)
            or font.st_uid != 0
            or stat.S_IMODE(font.st_mode) != 0o644
            or not os.access(path, os.R_OK)
        ):
            raise ValueError("fixed SVG font metadata is invalid")
        identities.extend(
            (font.st_dev, font.st_ino, font.st_size, font.st_mtime_ns, font.st_ctime_ns)
        )
    return _cached_renderer_identity(tuple(identities))


@lru_cache(maxsize=4)
def _cached_renderer_identity(identity: tuple[int, ...]) -> _RendererIdentity:
    del identity
    completed = subprocess.run(
        [SVG_LABEL_LAYOUT_RENDERER_PATH, "--version"],
        cwd="/",
        env={"HOME": "/nonexistent", "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
    )
    version = completed.stdout.decode("ascii", errors="strict").strip()
    if completed.returncode != 0 or not version.startswith("rsvg-convert version 2.58."):
        raise ValueError("fixed SVG renderer version is invalid")
    for specification in SVG_LABEL_LAYOUT_FONT_SPECS:
        if _sha256_file(Path(specification.path)) != specification.sha256:
            raise ValueError("fixed SVG font hash is invalid")
    return _RendererIdentity(
        version=version,
        sha256=_sha256_file(Path(SVG_LABEL_LAYOUT_RENDERER_PATH)),
        font_manifest_sha256=svg_label_layout_font_manifest_sha256(),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
