"""Build one immutable LoRA dataset from orchestrator-staged source pages."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
import warnings
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageModelPointer,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCandidate,
    LocalImageTrainingCandidateInventory,
    LocalImageTrainingDatasetManifest,
    LocalImageTrainingEligibilityReview,
    content_sha256,
    validate_contract,
    validate_training_dataset_authorization,
    validate_training_dataset_inventory,
    validate_training_inventory_review,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError as PydanticValidationError

MAX_SOURCE_PNG_BYTES = 64 * 1024 * 1024
MAX_SOURCE_IMAGE_PIXELS = 50_000_000
OUTPUT_WIDTH = 768
OUTPUT_HEIGHT = 512
NEAR_DUPLICATE_HAMMING_DISTANCE = 2
MINIMUM_SAMPLES = 100
MAXIMUM_SAMPLES = 200

PointerKey = tuple[str, str]


class DatasetBuildError(RuntimeError):
    """Stable fail-closed error raised before publication."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class StagedPageImage:
    """One exact source-page pointer materialized under ``staged_root/pages``."""

    pointer: ImageEvaluationArtifactMember

    @property
    def filename(self) -> str:
        return str(self.pointer.sha256).removeprefix("sha256:") + ".png"

    @property
    def key(self) -> PointerKey:
        return (self.pointer.artifact_revision_id, self.pointer.member_path)


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


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _safe_page_directory(staged_root: Path) -> int:
    if not staged_root.is_absolute():
        raise DatasetBuildError("IMAGE_TRAINING_STAGE_ROOT_INVALID")
    pages_path = staged_root / "pages"
    try:
        root = staged_root.lstat()
        pages = pages_path.lstat()
        if (
            staged_root.is_symlink()
            or pages_path.is_symlink()
            or not stat.S_ISDIR(root.st_mode)
            or not stat.S_ISDIR(pages.st_mode)
        ):
            raise DatasetBuildError("IMAGE_TRAINING_STAGE_ROOT_INVALID")
        root_descriptor = os.open(
            staged_root,
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            return os.open(
                "pages",
                os.O_RDONLY
                | os.O_CLOEXEC
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_descriptor,
            )
        finally:
            os.close(root_descriptor)
    except DatasetBuildError:
        raise
    except OSError as exc:
        raise DatasetBuildError("IMAGE_TRAINING_STAGE_ROOT_INVALID") from exc


def _read_staged_page(directory_descriptor: int, staged: StagedPageImage) -> bytes:
    try:
        descriptor = os.open(
            staged.filename,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_SOURCE_PNG_BYTES
        ):
            raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_CHANGED")
    finally:
        os.close(descriptor)
    value = bytes(payload)
    if "sha256:" + hashlib.sha256(value).hexdigest() != staged.pointer.sha256:
        raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_HASH_MISMATCH")
    return value


def _decode_png(payload: bytes) -> Image.Image:
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as source:
                if source.format != "PNG" or getattr(source, "n_frames", 1) != 1:
                    raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_FORMAT_INVALID")
                source.load()
                return source.convert("RGB")
    except DatasetBuildError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_TOO_LARGE") from exc
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise DatasetBuildError("IMAGE_TRAINING_SOURCE_PAGE_DECODE_FAILED") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _crop(candidate: LocalImageTrainingCandidate, source: Image.Image) -> Image.Image:
    box = candidate.bounding_box
    left = box.left * source.width // 10_000
    top = box.top * source.height // 10_000
    right = (box.right * source.width + 9_999) // 10_000
    bottom = (box.bottom * source.height + 9_999) // 10_000
    if not (0 <= left < right <= source.width and 0 <= top < bottom <= source.height):
        raise DatasetBuildError("IMAGE_TRAINING_BOUNDING_BOX_INVALID")
    crop = source.crop((left, top, right, bottom)).convert("L")
    crop.thumbnail((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (OUTPUT_WIDTH, OUTPUT_HEIGHT), 255)
    offset = ((OUTPUT_WIDTH - crop.width) // 2, (OUTPUT_HEIGHT - crop.height) // 2)
    canvas.paste(crop, offset)
    return canvas.convert("RGB")


def _png_bytes(image: Image.Image) -> bytes:
    target = io.BytesIO()
    image.save(target, format="PNG", optimize=False, compress_level=9)
    payload = target.getvalue()
    if not 0 < len(payload) <= 8 * 1024 * 1024:
        raise DatasetBuildError("IMAGE_TRAINING_CROP_SIZE_INVALID")
    return payload


def _average_hash(image: Image.Image) -> tuple[str, int]:
    grayscale = image.convert("L")
    ink_box = ImageOps.invert(grayscale).getbbox()
    if ink_box is None:
        raise DatasetBuildError("IMAGE_TRAINING_CROP_EMPTY")
    pixels = tuple(grayscale.crop(ink_box).resize((8, 8), Image.Resampling.LANCZOS).tobytes())
    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)
    return f"{value:016x}", value


class _PerceptualIndex:
    """Four-band candidate index for bounded Hamming-distance lookup."""

    def __init__(self) -> None:
        self._values: list[int] = []
        self._buckets: dict[tuple[int, int], set[int]] = defaultdict(set)

    def contains_near_duplicate(self, value: int) -> bool:
        candidates: set[int] = set()
        for band in range(4):
            candidates.update(self._buckets[(band, (value >> (band * 16)) & 0xFFFF)])
        return any(
            (value ^ self._values[index]).bit_count() <= NEAR_DUPLICATE_HAMMING_DISTANCE
            for index in candidates
        )

    def add(self, value: int) -> None:
        index = len(self._values)
        self._values.append(value)
        for band in range(4):
            self._buckets[(band, (value >> (band * 16)) & 0xFFFF)].add(index)


def _require_inventory_authorized(
    inventory: LocalImageTrainingCandidateInventory,
    authorization: LocalImageTrainingAuthorization,
) -> None:
    if inventory.source_snapshot != authorization.source_snapshot:
        raise DatasetBuildError("IMAGE_TRAINING_SOURCE_SNAPSHOT_UNAUTHORIZED")
    authorized = {
        policy.rights_policy_revision_id: policy for policy in authorization.rights_policies
    }
    for candidate in inventory.candidates:
        if (
            authorized.get(candidate.rights_policy.rights_policy_revision_id)
            != candidate.rights_policy
        ):
            raise DatasetBuildError("TRAINING_SOURCE_RIGHTS_UNCONFIRMED")


def _staged_page_index(
    inventory: LocalImageTrainingCandidateInventory,
    staged_pages: tuple[StagedPageImage, ...],
) -> Mapping[PointerKey, StagedPageImage]:
    keys = tuple(page.key for page in staged_pages)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise DatasetBuildError("IMAGE_TRAINING_STAGED_PAGES_INVALID")
    index = {page.key: page for page in staged_pages}
    required = {
        (
            candidate.source_page_image.artifact_revision_id,
            candidate.source_page_image.member_path,
        ): (candidate.source_page_image)
        for candidate in inventory.candidates
    }
    if set(index) != set(required):
        raise DatasetBuildError("IMAGE_TRAINING_STAGED_PAGES_INVALID")
    if any(index[key].pointer != pointer for key, pointer in required.items()):
        raise DatasetBuildError("IMAGE_TRAINING_STAGED_PAGE_POINTER_MISMATCH")
    return index


def build_training_dataset(
    *,
    inventory: LocalImageTrainingCandidateInventory,
    inventory_pointer: ImageEvaluationArtifactMember,
    eligibility_review: LocalImageTrainingEligibilityReview,
    eligibility_review_pointer: ImageEvaluationArtifactMember,
    authorization: LocalImageTrainingAuthorization,
    authorization_pointer: ImageEvaluationArtifactMember,
    base_model: LocalImageModelPointer,
    staged_root: Path,
    staged_pages: tuple[StagedPageImage, ...],
    output_root: Path,
    created_at: datetime,
    created_by: str,
    maximum_samples: int = MAXIMUM_SAMPLES,
) -> LocalImageTrainingDatasetManifest:
    """Build and atomically publish one local workspace dataset directory."""

    if not MINIMUM_SAMPLES <= maximum_samples <= MAXIMUM_SAMPLES:
        raise DatasetBuildError("IMAGE_TRAINING_SAMPLE_LIMIT_INVALID")
    try:
        validate_training_inventory_review(inventory, eligibility_review)
    except ValueError as exc:
        raise DatasetBuildError("IMAGE_TRAINING_ELIGIBILITY_REVIEW_INVALID") from exc
    _require_inventory_authorized(inventory, authorization)
    staged_index = _staged_page_index(inventory, staged_pages)
    if not output_root.is_absolute():
        raise DatasetBuildError("IMAGE_TRAINING_OUTPUT_ROOT_INVALID")
    try:
        output_metadata = output_root.lstat()
    except OSError as exc:
        raise DatasetBuildError("IMAGE_TRAINING_OUTPUT_ROOT_INVALID") from exc
    if output_root.is_symlink() or not stat.S_ISDIR(output_metadata.st_mode):
        raise DatasetBuildError("IMAGE_TRAINING_OUTPUT_ROOT_INVALID")
    final_root = output_root / "dataset"
    if final_root.exists() or final_root.is_symlink():
        raise DatasetBuildError("IMAGE_TRAINING_DATASET_ALREADY_EXISTS")

    pages_descriptor = _safe_page_directory(staged_root)
    temporary: Path | None = None
    try:
        temporary = Path(tempfile.mkdtemp(prefix=".dataset-building-", dir=output_root))
        temporary.chmod(0o700)
        samples_root = temporary / "samples"
        samples_root.mkdir(mode=0o700)
        manifests_root = temporary / "manifests"
        manifests_root.mkdir(mode=0o700)
    except OSError as exc:
        os.close(pages_descriptor)
        if temporary is not None and temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise DatasetBuildError("IMAGE_TRAINING_OUTPUT_ROOT_INVALID") from exc
    assert temporary is not None
    holdout_anchors = set(inventory.holdout_source_anchor_ids)
    exact_hashes: set[str] = set()
    perceptual = _PerceptualIndex()
    samples: list[dict[str, object]] = []
    try:
        by_page: dict[PointerKey, list[LocalImageTrainingCandidate]] = defaultdict(list)
        for candidate in inventory.candidates:
            if candidate.source_anchor_id not in holdout_anchors:
                key = (
                    candidate.source_page_image.artifact_revision_id,
                    candidate.source_page_image.member_path,
                )
                by_page[key].append(candidate)
        for key in sorted(by_page):
            source = _decode_png(_read_staged_page(pages_descriptor, staged_index[key]))
            for candidate in sorted(by_page[key], key=lambda value: value.candidate_id):
                image = _crop(candidate, source)
                payload = _png_bytes(image)
                crop_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
                perceptual_hash, perceptual_value = _average_hash(image)
                if crop_sha256 in exact_hashes or perceptual.contains_near_duplicate(
                    perceptual_value
                ):
                    continue
                identity = content_sha256(
                    {
                        "inventory_id": inventory.inventory_id,
                        "candidate_id": candidate.candidate_id,
                        "source_anchor_id": candidate.source_anchor_id,
                        "crop_sha256": crop_sha256,
                        "caption_sha256": candidate.caption_sha256,
                    }
                ).removeprefix("sha256:")[:32]
                sample_id = "imgtrainsample_" + identity
                member_path = f"samples/{sample_id}.png"
                _write_exclusive(temporary / member_path, payload)
                samples.append(
                    {
                        "training_sample_id": sample_id,
                        "item_revision_id": candidate.item_revision_id,
                        "extraction_result": candidate.extraction_result.model_dump(mode="json"),
                        "source_anchor_id": candidate.source_anchor_id,
                        "visual_pattern_ids": list(candidate.visual_pattern_ids),
                        "source_page_image": candidate.source_page_image.model_dump(mode="json"),
                        "bounding_box": candidate.bounding_box.model_dump(mode="json"),
                        "rights_policy": candidate.rights_policy.model_dump(mode="json"),
                        "representation_kind": candidate.representation_kind,
                        "rendering_mode": candidate.rendering_mode,
                        "crop_member": {
                            "member_path": member_path,
                            "media_type": "image/png",
                            "width_px": OUTPUT_WIDTH,
                            "height_px": OUTPUT_HEIGHT,
                            "size_bytes": len(payload),
                            "sha256": crop_sha256,
                        },
                        "caption_en": candidate.caption_en,
                        "caption_sha256": candidate.caption_sha256,
                        "perceptual_hash": perceptual_hash,
                    }
                )
                exact_hashes.add(crop_sha256)
                perceptual.add(perceptual_value)
                if len(samples) == maximum_samples:
                    break
            if len(samples) == maximum_samples:
                break
        if len(samples) < MINIMUM_SAMPLES:
            raise DatasetBuildError("IMAGE_TRAINING_DATASET_TOO_SMALL")
        samples.sort(key=lambda value: str(value["training_sample_id"]))
        sample_set_sha256 = content_sha256(samples)
        logical_identity = content_sha256(
            {
                "authorization": authorization_pointer.model_dump(mode="json"),
                "eligibility_review": eligibility_review_pointer.model_dump(mode="json"),
                "candidate_inventory": inventory_pointer.model_dump(mode="json"),
                "base_model": base_model.model_dump(mode="json"),
            }
        ).removeprefix("sha256:")
        revision_identity = content_sha256(
            {"logical_identity": logical_identity, "sample_set_sha256": sample_set_sha256}
        ).removeprefix("sha256:")
        body = {
            "schema_version": "local-image-training-dataset-manifest/1.0",
            "dataset_id": "imgdataset_" + logical_identity[:32],
            "dataset_revision_id": "imgdatasetrev_" + revision_identity[:32],
            "revision_number": 1,
            "previous_revision_id": None,
            "source_snapshot": inventory.source_snapshot.model_dump(mode="json"),
            "training_authorization": authorization_pointer.model_dump(mode="json"),
            "eligibility_review": eligibility_review_pointer.model_dump(mode="json"),
            "candidate_inventory": inventory_pointer.model_dump(mode="json"),
            "base_model": base_model.model_dump(mode="json"),
            "eligibility_policy_revision": "local-image-lora-eligibility/1.0",
            "holdout_evaluation_plan": inventory.holdout_evaluation_plan.model_dump(mode="json"),
            "holdout_sample_ids": list(inventory.holdout_sample_ids),
            "holdout_source_anchor_ids": list(inventory.holdout_source_anchor_ids),
            "samples": samples,
            "sample_set_sha256": sample_set_sha256,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "created_by": created_by,
        }
        value = {**body, "dataset_sha256": content_sha256(body)}
        validate_contract("training-dataset-manifest", value)
        dataset = LocalImageTrainingDatasetManifest.model_validate(value)
        validate_training_dataset_authorization(dataset, authorization)
        validate_training_dataset_inventory(dataset, inventory)
        _write_exclusive(manifests_root / "training-dataset.json", _canonical_json(value))
        temporary.rename(final_root)
        temporary = final_root
        return dataset
    except DatasetBuildError:
        raise
    except (JsonSchemaValidationError, OSError, PydanticValidationError, ValueError) as exc:
        raise DatasetBuildError("IMAGE_TRAINING_DATASET_BUILD_FAILED") from exc
    finally:
        os.close(pages_descriptor)
        if temporary != final_root and temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary)
