"""Safe local checkpoint materialization for one pinned LoRA training attempt."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_image_contracts import (
    LocalImageLoraCheckpointManifest,
    LocalImageLoraTrainingCommand,
    content_sha256,
    validate_contract,
    validate_lora_checkpoint_manifest,
)

from eom_image_trainer.runner import TrainingBackendFailure

CHECKPOINT_DIRECTORY = re.compile(r"^checkpoint-([0-9]{8})$")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ADAPTER_BYTES = 1024 * 1024 * 1024
MAX_STATE_BYTES = 512 * 1024 * 1024
MAX_STATE_NODES = 200_000


@dataclass(frozen=True, slots=True)
class RestoredCheckpoint:
    completed_steps: int
    micro_steps: int


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


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _read_regular(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o077
        ):
            raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_WRITE_FAILED") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _require_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID") from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")


def _validate_state_shape(value: object) -> None:
    pending = [value]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > MAX_STATE_NODES:
            raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
        if current is None or isinstance(current, bool | int | float | str):
            continue
        if hasattr(current, "shape") and hasattr(current, "dtype"):
            continue
        if isinstance(current, dict):
            if not all(isinstance(key, str | int) for key in current):
                raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
            pending.extend(current.values())
            continue
        if isinstance(current, list | tuple):
            pending.extend(current)
            continue
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")


def _checkpoint_directories(root: Path) -> tuple[tuple[int, Path], ...]:
    _require_directory(root)
    checkpoints: list[tuple[int, Path]] = []
    for child in root.iterdir():
        match = CHECKPOINT_DIRECTORY.fullmatch(child.name)
        if match is None:
            if child.name.startswith(".checkpoint-tmp-"):
                _require_directory(child)
                continue
            raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
        _require_directory(child)
        checkpoints.append((int(match.group(1)), child))
    checkpoints.sort(key=lambda item: item[0])
    if len({step for step, _path in checkpoints}) != len(checkpoints):
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
    return tuple(checkpoints)


def _load_manifest(
    directory: Path,
    command: LocalImageLoraTrainingCommand,
) -> LocalImageLoraCheckpointManifest:
    payload = _read_regular(
        directory / "checkpoint-manifest.json",
        maximum_bytes=MAX_MANIFEST_BYTES,
    )
    try:
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("checkpoint manifest must be an object")
        validate_contract("lora-checkpoint-manifest", value)
        manifest = LocalImageLoraCheckpointManifest.model_validate(value)
        validate_lora_checkpoint_manifest(manifest, command)
    except Exception as exc:
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID") from exc
    return manifest


def load_latest_checkpoint(
    *,
    root: Path,
    command: LocalImageLoraTrainingCommand,
    model: Any,
    optimizer: Any,
    torch: Any,
) -> RestoredCheckpoint | None:
    """Load only the highest complete, hash-verified checkpoint for this exact command."""

    checkpoints = _checkpoint_directories(root)
    if not checkpoints:
        return None
    directory_step, directory = checkpoints[-1]
    manifest = _load_manifest(directory, command)
    if directory_step != manifest.completed_steps:
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID")
    file_by_name = {item.relative_path: item for item in manifest.files}
    adapter_payload = _read_regular(
        directory / "adapter_model.safetensors",
        maximum_bytes=MAX_ADAPTER_BYTES,
    )
    state_payload = _read_regular(
        directory / "optimizer-rng-state.pt",
        maximum_bytes=MAX_STATE_BYTES,
    )
    if (
        _sha256(adapter_payload) != file_by_name["adapter_model.safetensors"].sha256
        or len(adapter_payload) != file_by_name["adapter_model.safetensors"].size_bytes
        or _sha256(state_payload) != file_by_name["optimizer-rng-state.pt"].sha256
        or len(state_payload) != file_by_name["optimizer-rng-state.pt"].size_bytes
    ):
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_HASH_MISMATCH")
    try:
        from peft.utils import set_peft_model_state_dict  # type: ignore[import-not-found]
        from safetensors.torch import load as load_safetensors  # type: ignore[import-not-found]

        adapter_state = load_safetensors(adapter_payload)
        state = torch.load(
            io.BytesIO(state_payload),
            map_location="cpu",
            weights_only=True,
        )
        _validate_state_shape(adapter_state)
        _validate_state_shape(state)
        if (
            not isinstance(state, dict)
            or state.get("completed_steps") != manifest.completed_steps
            or state.get("micro_steps") != manifest.micro_steps
            or not isinstance(state.get("optimizer"), dict)
            or not hasattr(state.get("cpu_rng_state"), "shape")
            or not isinstance(state.get("cuda_rng_state_all"), list)
        ):
            raise ValueError("checkpoint state shape mismatch")
        load_result = set_peft_model_state_dict(
            model,
            adapter_state,
            adapter_name="default",
        )
        if getattr(load_result, "unexpected_keys", ()):
            raise ValueError("checkpoint adapter has unexpected keys")
        optimizer.load_state_dict(state["optimizer"])
        torch.set_rng_state(state["cpu_rng_state"])
        torch.cuda.set_rng_state_all(state["cuda_rng_state_all"])
    except TrainingBackendFailure:
        raise
    except Exception as exc:
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_INVALID") from exc
    return RestoredCheckpoint(
        completed_steps=manifest.completed_steps,
        micro_steps=manifest.micro_steps,
    )


def save_checkpoint(
    *,
    root: Path,
    command: LocalImageLoraTrainingCommand,
    model: Any,
    optimizer: Any,
    completed_steps: int,
    micro_steps: int,
    torch: Any,
) -> LocalImageLoraCheckpointManifest:
    """Atomically publish one local resumable checkpoint at an optimizer boundary."""

    _require_directory(root)
    final = root / f"checkpoint-{completed_steps:08d}"
    temporary = root / f".checkpoint-tmp-{completed_steps:08d}-{os.getpid()}"
    if final.exists() or final.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_EXISTS")
    temporary.mkdir(mode=0o700)
    try:
        from peft.utils import get_peft_model_state_dict
        from safetensors.torch import save as save_safetensors

        adapter_state = {
            name: tensor.detach().to("cpu").contiguous()
            for name, tensor in get_peft_model_state_dict(
                model,
                adapter_name="default",
            ).items()
        }
        _validate_state_shape(adapter_state)
        adapter_payload = save_safetensors(adapter_state)
        state = {
            "completed_steps": completed_steps,
            "micro_steps": micro_steps,
            "optimizer": optimizer.state_dict(),
            "cpu_rng_state": torch.get_rng_state(),
            "cuda_rng_state_all": torch.cuda.get_rng_state_all(),
        }
        _validate_state_shape(state)
        state_buffer = io.BytesIO()
        torch.save(state, state_buffer)
        state_payload = state_buffer.getvalue()
        if len(adapter_payload) > MAX_ADAPTER_BYTES or len(state_payload) > MAX_STATE_BYTES:
            raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_TOO_LARGE")
        _write_exclusive(temporary / "adapter_model.safetensors", adapter_payload)
        _write_exclusive(temporary / "optimizer-rng-state.pt", state_payload)
        body = {
            "schema_version": "local-image-lora-checkpoint-manifest/1.0",
            "training_run_id": command.training_run_id,
            "training_plan_sha256": command.training_plan_sha256,
            "attempt": command.attempt,
            "completed_steps": completed_steps,
            "micro_steps": micro_steps,
            "files": [
                {
                    "relative_path": "adapter_model.safetensors",
                    "size_bytes": len(adapter_payload),
                    "sha256": _sha256(adapter_payload),
                },
                {
                    "relative_path": "optimizer-rng-state.pt",
                    "size_bytes": len(state_payload),
                    "sha256": _sha256(state_payload),
                },
            ],
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        value = {**body, "manifest_sha256": content_sha256(body)}
        validate_contract("lora-checkpoint-manifest", value)
        manifest = LocalImageLoraCheckpointManifest.model_validate(value)
        validate_lora_checkpoint_manifest(manifest, command)
        _write_exclusive(
            temporary / "checkpoint-manifest.json",
            _canonical_json(value),
        )
        os.rename(temporary, final)
        root_descriptor = os.open(root, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
        return manifest
    except TrainingBackendFailure:
        raise
    except Exception as exc:
        raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_WRITE_FAILED") from exc
