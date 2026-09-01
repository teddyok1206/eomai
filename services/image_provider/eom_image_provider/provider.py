"""Fail-closed model resolution and local background generation boundary."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import stat
import struct
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Protocol

from eom_image_contracts import (
    LocalImageCompositeReceipt,
    LocalImageCompositeRequest,
    LocalImageCompositorRuntime,
    LocalImageFinalOutput,
    LocalImageGenerationReceipt,
    LocalImageGenerationRequest,
    LocalImageModelManifest,
    LocalImageOutput,
    LocalImageRuntime,
    content_sha256,
    validate_contract,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_MAX_BYTES = 8 * 1024 * 1024
MODEL_FILE_MAX_BYTES = 8 * 1024 * 1024 * 1024


class ProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class GeneratedBackground:
    png_bytes: bytes
    runtime: LocalImageRuntime


class ImageBackend(Protocol):
    def generate(
        self,
        *,
        model_directory: Path,
        request: LocalImageGenerationRequest,
    ) -> GeneratedBackground: ...


@contextmanager
def acquire_gpu_lease(lock_path: Path) -> Iterator[None]:
    """Hold the one reviewed physical-GPU lease for the unit lifetime."""

    _require_absolute_no_symlink_components(lock_path.parent)
    _require_directory(lock_path.parent, mode=0o700, current_owner=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_GPU_UNAVAILABLE") from exc
    try:
        os.fchmod(descriptor, 0o600)
        lock_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(lock_metadata.st_mode) != 0o600
        ):
            raise ProviderError("LOCAL_IMAGE_GPU_UNAVAILABLE")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProviderError("LOCAL_IMAGE_GPU_UNAVAILABLE") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def load_json_object(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    _require_regular_file(path, maximum_bytes=maximum_bytes)

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ProviderError("LOCAL_IMAGE_INPUT_INVALID")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ProviderError("LOCAL_IMAGE_INPUT_INVALID")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderError("LOCAL_IMAGE_INPUT_INVALID") from exc
    if not isinstance(value, dict):
        raise ProviderError("LOCAL_IMAGE_INPUT_INVALID")
    return value


def verify_model_revision(
    model_store_root: Path,
    pointer: object,
) -> tuple[LocalImageModelManifest, Path]:
    from eom_image_contracts import LocalImageModelPointer

    if not isinstance(pointer, LocalImageModelPointer):
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    _require_absolute_no_symlink_components(model_store_root)
    store_metadata = _require_directory(model_store_root, mode=0o750)
    logical_model = model_store_root / pointer.model_id
    logical_metadata = _require_directory(logical_model, mode=0o750)
    revision = logical_model / pointer.model_revision_id
    _require_beneath(model_store_root, revision)
    revision_metadata = _require_directory(revision, mode=0o750)
    expected_identity = (store_metadata.st_uid, store_metadata.st_gid)
    if (logical_metadata.st_uid, logical_metadata.st_gid) != expected_identity or (
        revision_metadata.st_uid,
        revision_metadata.st_gid,
    ) != expected_identity:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    manifest_path = revision / "manifest.json"
    manifest_metadata = _require_regular_file(manifest_path, maximum_bytes=256 * 1024)
    if (
        stat.S_IMODE(manifest_metadata.st_mode) != 0o640
        or (manifest_metadata.st_uid, manifest_metadata.st_gid) != expected_identity
    ):
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    manifest_value = load_json_object(manifest_path, maximum_bytes=256 * 1024)
    try:
        validate_contract("model-manifest", manifest_value)
        manifest = LocalImageModelManifest.model_validate(manifest_value)
    except Exception as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_HASH_MISMATCH") from exc
    if (
        manifest.model_id != pointer.model_id
        or manifest.model_revision_id != pointer.model_revision_id
        or manifest.manifest_sha256 != pointer.manifest_sha256
        or manifest.provider_family != pointer.provider_family
        or manifest.runtime_contract_version != pointer.runtime_contract_version
    ):
        raise ProviderError("LOCAL_IMAGE_MODEL_HASH_MISMATCH")
    model_directory = revision / "files"
    model_metadata = _require_directory(model_directory, mode=0o750)
    if (model_metadata.st_uid, model_metadata.st_gid) != expected_identity:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    expected = {item.relative_path: item for item in manifest.files}
    observed: set[str] = set()
    for root, directories, files in os.walk(model_directory, followlinks=False):
        root_path = Path(root)
        for name in directories:
            directory_metadata = _require_directory(root_path / name, mode=0o750)
            if (directory_metadata.st_uid, directory_metadata.st_gid) != expected_identity:
                raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
        for name in files:
            path = root_path / name
            relative = path.relative_to(model_directory).as_posix()
            entry = expected.get(relative)
            if entry is None:
                raise ProviderError("LOCAL_IMAGE_MODEL_HASH_MISMATCH")
            metadata = _require_regular_file(path, maximum_bytes=MODEL_FILE_MAX_BYTES)
            if (
                stat.S_IMODE(metadata.st_mode) != 0o640
                or (metadata.st_uid, metadata.st_gid) != expected_identity
                or metadata.st_size != entry.size_bytes
                or _sha256_file(path) != entry.sha256
            ):
                raise ProviderError("LOCAL_IMAGE_MODEL_HASH_MISMATCH")
            observed.add(relative)
    if observed != set(expected):
        raise ProviderError("LOCAL_IMAGE_MODEL_HASH_MISMATCH")
    return manifest, model_directory


def generate_background(
    *,
    model_store_root: Path,
    workspace: Path,
    request: LocalImageGenerationRequest,
    backend: ImageBackend,
) -> LocalImageGenerationReceipt:
    _require_absolute_no_symlink_components(workspace)
    _require_directory(workspace, mode=0o700, current_owner=True)
    return _generate_background(
        model_store_root=model_store_root,
        workspace=workspace,
        request=request,
        backend=backend,
        output_mode=0o600,
    )


def generate_composite_handoff(
    *,
    model_store_root: Path,
    workspace: Path,
    request: LocalImageCompositeRequest,
    backend: ImageBackend,
) -> LocalImageCompositeReceipt:
    """Generate once and compose a manager-readable result in one trusted handoff."""

    _require_absolute_no_symlink_components(workspace)
    _require_handoff_directory(workspace)
    completed = _completed_composite(workspace, request)
    if completed is not None:
        return completed
    output_paths = (
        workspace / request.generation.output_member,
        workspace / "generation-receipt.json",
        workspace / request.final_output_member,
        workspace / "composite-receipt.json",
    )
    if any(path.exists() or path.is_symlink() for path in output_paths):
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID")
    overlay_path = workspace / request.overlay.member_path
    _require_handoff_input(overlay_path, request.overlay.size_bytes, request.overlay.sha256)
    started_clock = time.monotonic_ns()
    generation = _generate_background(
        model_store_root=model_store_root,
        workspace=workspace,
        request=request.generation,
        backend=backend,
        output_mode=0o640,
    )
    background_path = workspace / generation.output.member_path
    final_bytes = _compose_png(background_path, overlay_path)
    final_path = workspace / request.final_output_member
    _write_exclusive(final_path, final_bytes, mode=0o640)
    output = LocalImageFinalOutput(
        size_bytes=len(final_bytes),
        sha256="sha256:" + hashlib.sha256(final_bytes).hexdigest(),
    )
    completed_at = datetime.now(UTC)
    duration_ms = max(1, (time.monotonic_ns() - started_clock) // 1_000_000)
    body = {
        "schema_version": "local-image-composite-receipt/1.0",
        "composite_request_sha256": request.composite_request_sha256,
        "generation": generation.model_dump(mode="json"),
        "overlay": request.overlay.model_dump(mode="json"),
        "output": output.model_dump(mode="json"),
        "compositor": LocalImageCompositorRuntime(
            pillow_version=metadata.version("Pillow")
        ).model_dump(mode="json"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "duration_ms": duration_ms,
    }
    receipt = LocalImageCompositeReceipt.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )
    receipt_value = receipt.model_dump(mode="json")
    validate_contract("composite-receipt", receipt_value)
    receipt_bytes = (
        json.dumps(receipt_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _write_exclusive(workspace / "composite-receipt.json", receipt_bytes, mode=0o640)
    return receipt


def reuse_composite_handoff(
    *,
    workspace: Path,
    request: LocalImageCompositeRequest,
) -> LocalImageCompositeReceipt | None:
    """Return an exact completed handoff without acquiring the physical GPU."""

    _require_absolute_no_symlink_components(workspace)
    _require_handoff_directory(workspace)
    return _completed_composite(workspace, request)


def _generate_background(
    *,
    model_store_root: Path,
    workspace: Path,
    request: LocalImageGenerationRequest,
    backend: ImageBackend,
    output_mode: int,
) -> LocalImageGenerationReceipt:
    manifest, model_directory = verify_model_revision(model_store_root, request.model)
    if manifest.state != "APPROVED":
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    output_path = workspace / request.output_member
    receipt_path = workspace / "generation-receipt.json"
    if (
        output_path.exists()
        or output_path.is_symlink()
        or receipt_path.exists()
        or receipt_path.is_symlink()
    ):
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID")
    started = datetime.now(UTC)
    started_clock = time.monotonic_ns()
    generated = backend.generate(model_directory=model_directory, request=request)
    completed = datetime.now(UTC)
    duration_ms = max(1, (time.monotonic_ns() - started_clock) // 1_000_000)
    if duration_ms > request.timeout_seconds * 1000:
        raise ProviderError("LOCAL_IMAGE_PROVIDER_TIMEOUT")
    _validate_png(generated.png_bytes)
    _write_exclusive(output_path, generated.png_bytes, mode=output_mode)
    output = LocalImageOutput(
        size_bytes=len(generated.png_bytes),
        sha256="sha256:" + hashlib.sha256(generated.png_bytes).hexdigest(),
    )
    body = {
        "schema_version": "local-image-generation-receipt/1.0",
        "request_id": request.request_id,
        "request_sha256": request.request_sha256,
        "model": request.model.model_dump(mode="json"),
        "prompt_sha256": request.prompt_sha256,
        "negative_prompt_sha256": request.negative_prompt_sha256,
        "seed": request.seed,
        "sampler": request.sampler.model_dump(mode="json"),
        "output": output.model_dump(mode="json"),
        "runtime": generated.runtime.model_dump(mode="json"),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "completed_at": completed.isoformat().replace("+00:00", "Z"),
        "duration_ms": duration_ms,
    }
    receipt = LocalImageGenerationReceipt.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )
    receipt_value = receipt.model_dump(mode="json")
    validate_contract("generation-receipt", receipt_value)
    receipt_bytes = (
        json.dumps(receipt_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _write_exclusive(receipt_path, receipt_bytes, mode=output_mode)
    return receipt


def _require_handoff_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_HANDOFF_INVALID") from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o1730
        or metadata.st_gid != os.getegid()
        or metadata.st_gid not in os.getgroups()
    ):
        raise ProviderError("LOCAL_IMAGE_HANDOFF_INVALID")


def _require_handoff_input(path: Path, size_bytes: int, sha256: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_HANDOFF_INVALID") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o440
        or metadata.st_gid != os.getegid()
        or metadata.st_size != size_bytes
        or _sha256_file(path) != sha256
    ):
        raise ProviderError("LOCAL_IMAGE_HANDOFF_INVALID")


def _require_handoff_output(path: Path, *, sha256: str | None = None) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o640
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or not 0 < metadata.st_size <= PNG_MAX_BYTES
        or (sha256 is not None and _sha256_file(path) != sha256)
    ):
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID")


def _completed_composite(
    workspace: Path, request: LocalImageCompositeRequest
) -> LocalImageCompositeReceipt | None:
    receipt_path = workspace / "composite-receipt.json"
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return None
    _require_handoff_output(receipt_path)
    value = load_json_object(receipt_path, maximum_bytes=256 * 1024)
    try:
        validate_contract("composite-receipt", value)
        receipt = LocalImageCompositeReceipt.model_validate(value)
    except Exception as exc:
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    generation_receipt_path = workspace / "generation-receipt.json"
    _require_handoff_output(generation_receipt_path)
    generation_value = load_json_object(generation_receipt_path, maximum_bytes=256 * 1024)
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
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID")
    _require_handoff_input(
        workspace / request.overlay.member_path,
        request.overlay.size_bytes,
        request.overlay.sha256,
    )
    _require_handoff_output(
        workspace / receipt.generation.output.member_path,
        sha256=receipt.generation.output.sha256,
    )
    _require_handoff_output(
        workspace / receipt.output.member_path,
        sha256=receipt.output.sha256,
    )
    return receipt


def _compose_png(background_path: Path, overlay_path: Path) -> bytes:
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(background_path) as background_source:
            background_source.load()
            if background_source.format != "PNG" or background_source.size != (800, 500):
                raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID")
            background = background_source.convert("RGBA")
        with Image.open(overlay_path) as overlay_source:
            overlay_source.load()
            if (
                overlay_source.format != "PNG"
                or overlay_source.size != (800, 500)
                or overlay_source.mode != "RGBA"
            ):
                raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID")
            overlay = overlay_source.copy()
        composed = Image.alpha_composite(background, overlay).convert("RGB")
        target = io.BytesIO()
        composed.save(target, format="PNG", optimize=False, compress_level=9)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    payload = target.getvalue()
    _validate_png(payload)
    return payload


def _require_beneath(root: Path, child: Path) -> None:
    try:
        child.relative_to(root)
    except ValueError as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
    current = root
    _reject_symlink(current)
    for part in child.relative_to(root).parts:
        current = current / part
        _reject_symlink(current)


def _require_absolute_no_symlink_components(path: Path) -> None:
    if not path.is_absolute():
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        _reject_symlink(current)


def _reject_symlink(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")


def _require_directory(
    path: Path,
    *,
    mode: int | None,
    current_owner: bool = False,
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    actual_mode = stat.S_IMODE(metadata.st_mode)
    if mode is not None and actual_mode != mode:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    if current_owner and metadata.st_uid != os.geteuid():
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    if actual_mode & 0o022:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    return metadata


def _require_regular_file(path: Path, *, maximum_bytes: int) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > maximum_bytes
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
    return metadata


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
    return "sha256:" + digest.hexdigest()


def _validate_png(payload: bytes) -> None:
    if (
        not 32 <= len(payload) <= PNG_MAX_BYTES
        or payload[:8] != PNG_SIGNATURE
        or payload[12:16] != b"IHDR"
        or struct.unpack(">II", payload[16:24]) != (800, 500)
        or payload[24:26] != b"\x08\x02"
        or payload[-12:-8] != b"\x00\x00\x00\x00"
        or payload[-8:-4] != b"IEND"
    ):
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID")


def _write_exclusive(path: Path, payload: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, mode)
    except OSError as exc:
        raise ProviderError("LOCAL_IMAGE_OUTPUT_INVALID") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)
