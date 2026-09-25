"""Isolated command/result boundary for deterministic visual crop localization.

The runner reads only an orchestrator-staged 0700 workspace.  It performs O(s + p) exact
member validation over ``s`` source descriptors and ``p`` unique staged page members, caches OCR
by immutable page hash, writes one typed result with O_EXCL, and never reads PostgreSQL or NAS.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import warnings
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from eom_image_contracts import (
    ImageEvaluationBoundingBox,
    LocalImageCropLocatorCommand,
    LocalImageCropLocatorResult,
    LocalImageTrainingCropProposalSet,
    content_sha256,
    validate_contract,
    validate_crop_locator_result,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError  # type: ignore[import-not-found]
from pydantic import ValidationError as PydanticValidationError

from eom_image_trainer.crop_locator import CropLocatorError, run_tesseract
from eom_image_trainer.proposal_builder import (
    CropProposalBuildError,
    StagedVisualCropSource,
    build_training_crop_proposal_set,
)

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PAGE_BYTES = 64 * 1024 * 1024
MAX_PAGE_PIXELS = 100_000_000
CONTACT_SHEET_COLUMNS = 4
CONTACT_SHEET_ROWS = 5
CONTACT_TILE_WIDTH = 380
CONTACT_TILE_HEIGHT = 300


class CropLocatorRunnerError(RuntimeError):
    """Stable fail-closed boundary error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise CropLocatorRunnerError("IMAGE_TRAINING_JSON_INVALID")
        value[key] = item
    return value


def _parse_json(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CropLocatorRunnerError("IMAGE_TRAINING_JSON_INVALID")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise CropLocatorRunnerError("IMAGE_TRAINING_JSON_INVALID")
    return value


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


def _require_workspace(workspace: Path) -> None:
    if not workspace.is_absolute():
        raise CropLocatorRunnerError("IMAGE_TRAINING_WORKSPACE_INVALID")
    try:
        metadata = workspace.lstat()
    except OSError as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_WORKSPACE_INVALID") from exc
    if (
        workspace.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise CropLocatorRunnerError("IMAGE_TRAINING_WORKSPACE_INVALID")


def _member_path(workspace: Path, member: str) -> Path:
    relative = PurePosixPath(member)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise CropLocatorRunnerError("IMAGE_TRAINING_MEMBER_PATH_INVALID")
    current = workspace
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CropLocatorRunnerError("IMAGE_TRAINING_INPUT_MISSING") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CropLocatorRunnerError("IMAGE_TRAINING_INPUT_INVALID")
    return current


def _read_regular(path: Path, *, maximum_bytes: int, expected_sha256: str | None) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_INPUT_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise CropLocatorRunnerError("IMAGE_TRAINING_INPUT_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise CropLocatorRunnerError("IMAGE_TRAINING_INPUT_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CropLocatorRunnerError("IMAGE_TRAINING_INPUT_CHANGED")
    finally:
        os.close(descriptor)
    body = bytes(payload)
    if expected_sha256 is not None and (
        "sha256:" + hashlib.sha256(body).hexdigest() != expected_sha256
    ):
        raise CropLocatorRunnerError("IMAGE_TRAINING_INPUT_HASH_MISMATCH")
    return body


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_OUTPUT_EXISTS") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def load_crop_locator_command(path: Path) -> LocalImageCropLocatorCommand:
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES, expected_sha256=None))
    try:
        validate_contract("crop-locator-command", value)
        return LocalImageCropLocatorCommand.model_validate(value)
    except (JsonSchemaValidationError, PydanticValidationError, TypeError, ValueError) as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_CROP_LOCATOR_COMMAND_INVALID") from exc


def _decode_page(payload: bytes) -> Image.Image:
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as source:
                if source.format != "PNG" or getattr(source, "n_frames", 1) != 1:
                    raise CropLocatorRunnerError("IMAGE_TRAINING_SOURCE_PAGE_INVALID")
                source.load()
                return source.convert("RGB")
    except CropLocatorRunnerError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_SOURCE_PAGE_TOO_LARGE") from exc
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_SOURCE_PAGE_INVALID") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _staged_sources(
    workspace: Path,
    command: LocalImageCropLocatorCommand,
) -> tuple[StagedVisualCropSource, ...]:
    page_cache: dict[str, Image.Image] = {}
    staged: list[StagedVisualCropSource] = []
    for source in command.sources:
        page = page_cache.get(source.source_page_image.sha256)
        if page is None:
            payload = _read_regular(
                _member_path(workspace, source.staged_page_member),
                maximum_bytes=MAX_PAGE_BYTES,
                expected_sha256=source.source_page_image.sha256,
            )
            page = _decode_page(payload)
            page_cache[source.source_page_image.sha256] = page
        staged.append(
            StagedVisualCropSource(
                item_revision_id=source.item_revision_id,
                extraction_result=source.extraction_result,
                source_anchor_id=source.source_anchor_id,
                visual_pattern_ids=source.visual_pattern_ids,
                source_page_image=source.source_page_image,
                physical_page=source.physical_page,
                context_bounding_box=source.context_bounding_box,
                rights_policy=source.rights_policy,
                representation_kind=source.representation_kind,
                rendering_mode=source.rendering_mode,
                visual_features=source.visual_features,
                page_image=page,
            )
        )
    return tuple(staged)


def _pixel_box(
    value: ImageEvaluationBoundingBox,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    return (
        max(0, value.left * width // 10_000),
        max(0, value.top * height // 10_000),
        min(width, (value.right * width + 9_999) // 10_000),
        min(height, (value.bottom * height + 9_999) // 10_000),
    )


def _write_contact_sheets(
    *,
    workspace: Path,
    proposal_set: LocalImageTrainingCropProposalSet,
    staged_sources: tuple[StagedVisualCropSource, ...],
) -> None:
    review_root = workspace / "review"
    try:
        review_root.mkdir(mode=0o700, exist_ok=False)
    except OSError as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_REVIEW_OUTPUT_INVALID") from exc
    by_anchor = {value.source_anchor_id: value for value in staged_sources}
    tiles: list[tuple[Image.Image, dict[str, object]]] = []
    for proposal in proposal_set.proposals:
        source = by_anchor[proposal.source_anchor_id]
        page = source.page_image
        crop_box = _pixel_box(
            proposal.crop_bounding_box,
            width=page.width,
            height=page.height,
        )
        crop = page.crop(crop_box).convert("L")
        drawing = ImageDraw.Draw(crop)
        for redaction in proposal.redaction_boxes:
            page_box = _pixel_box(redaction, width=page.width, height=page.height)
            drawing.rectangle(
                (
                    max(0, page_box[0] - crop_box[0]),
                    max(0, page_box[1] - crop_box[1]),
                    min(crop.width, page_box[2] - crop_box[0]),
                    min(crop.height, page_box[3] - crop_box[1]),
                ),
                fill=255,
            )
        fitted = ImageOps.contain(crop, (CONTACT_TILE_WIDTH - 20, CONTACT_TILE_HEIGHT - 50))
        tile = Image.new("L", (CONTACT_TILE_WIDTH, CONTACT_TILE_HEIGHT), 255)
        tile.paste(fitted, ((CONTACT_TILE_WIDTH - fitted.width) // 2, 32))
        ImageDraw.Draw(tile).text(
            (8, 8),
            f"{proposal.crop_proposal_id[-8:]} rank={proposal.candidate_rank}",
            fill=0,
        )
        tiles.append(
            (
                tile,
                {
                    "crop_proposal_id": proposal.crop_proposal_id,
                    "source_anchor_id": proposal.source_anchor_id,
                    "candidate_rank": proposal.candidate_rank,
                    "contact_sheet": "",
                    "tile_index": 0,
                },
            )
        )
    per_sheet = CONTACT_SHEET_COLUMNS * CONTACT_SHEET_ROWS
    index: list[dict[str, object]] = []
    for offset in range(0, len(tiles), per_sheet):
        sheet_name = f"contact-sheet-{offset // per_sheet + 1:03d}.png"
        sheet = Image.new(
            "L",
            (CONTACT_SHEET_COLUMNS * CONTACT_TILE_WIDTH, CONTACT_SHEET_ROWS * CONTACT_TILE_HEIGHT),
            255,
        )
        for local_index, (tile, metadata) in enumerate(tiles[offset : offset + per_sheet]):
            sheet.paste(
                tile,
                (
                    local_index % CONTACT_SHEET_COLUMNS * CONTACT_TILE_WIDTH,
                    local_index // CONTACT_SHEET_COLUMNS * CONTACT_TILE_HEIGHT,
                ),
            )
            index.append({**metadata, "contact_sheet": sheet_name, "tile_index": local_index})
        target = io.BytesIO()
        sheet.save(target, format="PNG", optimize=False)
        _write_exclusive(review_root / sheet_name, target.getvalue())
    _write_exclusive(
        review_root / "review-index.json",
        _canonical_json(
            {
                "proposal_set_id": proposal_set.proposal_set_id,
                "proposal_set_sha256": proposal_set.proposal_set_sha256,
                "entries": index,
            }
        ),
    )


def _result(
    command: LocalImageCropLocatorCommand,
    *,
    status: Literal["SUCCEEDED", "FAILED"],
    proposal_set: object | None,
    error_code: str | None,
) -> LocalImageCropLocatorResult:
    body = {
        "schema_version": "local-image-crop-locator-result/1.0",
        "locator_run_id": command.locator_run_id,
        "command_sha256": command.command_sha256,
        "status": status,
        "proposal_set": proposal_set,
        "error_code": error_code,
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("crop-locator-result", value)
    result = LocalImageCropLocatorResult.model_validate(value)
    validate_crop_locator_result(command, result)
    return result


def run_crop_locator_command(
    *,
    workspace: Path,
    command: LocalImageCropLocatorCommand,
) -> LocalImageCropLocatorResult:
    """Execute one command and always persist a typed terminal result after command validation."""

    _require_workspace(workspace)
    output_path = workspace / command.output_member
    output_parent = output_path.parent
    try:
        metadata = output_parent.lstat()
    except OSError as exc:
        raise CropLocatorRunnerError("IMAGE_TRAINING_OUTPUT_ROOT_INVALID") from exc
    if (
        output_parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise CropLocatorRunnerError("IMAGE_TRAINING_OUTPUT_ROOT_INVALID")

    try:
        staged = _staged_sources(workspace, command)
        ocr_cache: dict[int, tuple[ImageEvaluationBoundingBox, ...]] = {}

        def cached_ocr(image: Image.Image) -> tuple[ImageEvaluationBoundingBox, ...]:
            identity = id(image)
            value = ocr_cache.get(identity)
            if value is None:
                value = run_tesseract(image)
                ocr_cache[identity] = value
            return value

        proposal_set = build_training_crop_proposal_set(
            sources=staged,
            preliminary_omissions=command.preliminary_omissions,
            source_snapshot=command.source_snapshot,
            training_authorization=command.training_authorization,
            holdout_evaluation_plan=command.holdout_evaluation_plan,
            holdout_sample_ids=command.holdout_sample_ids,
            holdout_source_anchor_ids=command.holdout_source_anchor_ids,
            created_at=command.created_at,
            created_by=command.created_by,
            ocr_locator=cached_ocr,
        )
        result = _result(
            command,
            status="SUCCEEDED",
            proposal_set=proposal_set.model_dump(mode="json"),
            error_code=None,
        )
        _write_contact_sheets(
            workspace=workspace,
            proposal_set=proposal_set,
            staged_sources=staged,
        )
    except (CropLocatorRunnerError, CropLocatorError, CropProposalBuildError) as exc:
        result = _result(
            command,
            status="FAILED",
            proposal_set=None,
            error_code=str(exc),
        )
    _write_exclusive(output_path, _canonical_json(result.model_dump(mode="json")))
    return result
