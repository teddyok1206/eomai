"""Validate and run one isolated LoRA worker command without NAS access."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from eom_image_contracts import (
    LocalImageLoraAdapterManifest,
    LocalImageLoraTrainingCommand,
    LocalImageLoraTrainingPlan,
    LocalImageLoraTrainingRuntime,
    LocalImageLoraTrainingWorkerResult,
    LocalImageTrainingDatasetManifest,
    content_sha256,
    validate_contract,
    validate_lora_training_plan,
    validate_lora_training_worker_result,
)

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ADAPTER_BYTES = 1024 * 1024 * 1024
MAX_SAFETENSORS_HEADER_BYTES = 1024 * 1024


class TrainingRunnerError(RuntimeError):
    """Stable worker-boundary error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TrainingBackendFailure(RuntimeError):
    """Terminal backend outcome that can be represented by a typed result."""

    def __init__(
        self,
        code: str,
        *,
        runtime: LocalImageLoraTrainingRuntime | None = None,
        completed_steps: int = 0,
        final_loss: float | None = None,
        cancelled: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.runtime = runtime
        self.completed_steps = completed_steps
        self.final_loss = final_loss
        self.cancelled = cancelled


@dataclass(frozen=True, slots=True)
class TrainingBackendResult:
    runtime: LocalImageLoraTrainingRuntime
    completed_steps: int
    final_loss: float


class TrainingBackend(Protocol):
    def train(
        self,
        *,
        model_directory: Path,
        dataset: LocalImageTrainingDatasetManifest,
        dataset_root: Path,
        command: LocalImageLoraTrainingCommand,
        output_root: Path,
        checkpoint_root: Path,
    ) -> TrainingBackendResult: ...


class ModelResolver(Protocol):
    def __call__(self, model_store_root: Path, pointer: object) -> tuple[object, Path]: ...


def load_training_command(path: Path) -> LocalImageLoraTrainingCommand:
    """Load one bounded command file through both contract validation layers."""

    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        validate_contract("lora-training-command", value)
        return LocalImageLoraTrainingCommand.model_validate(value)
    except Exception as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_COMMAND_INVALID") from exc


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


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise TrainingRunnerError("IMAGE_TRAINING_JSON_INVALID")
        value[key] = item
    return value


def _read_regular(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_INPUT_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise TrainingRunnerError("IMAGE_TRAINING_INPUT_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise TrainingRunnerError("IMAGE_TRAINING_INPUT_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise TrainingRunnerError("IMAGE_TRAINING_INPUT_CHANGED")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _parse_json(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                TrainingRunnerError("IMAGE_TRAINING_JSON_INVALID")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise TrainingRunnerError("IMAGE_TRAINING_JSON_INVALID")
    return value


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_OUTPUT_EXISTS") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _require_workspace(workspace: Path) -> None:
    if not workspace.is_absolute():
        raise TrainingRunnerError("IMAGE_TRAINING_WORKSPACE_INVALID")
    try:
        metadata = workspace.lstat()
    except OSError as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_WORKSPACE_INVALID") from exc
    if (
        workspace.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise TrainingRunnerError("IMAGE_TRAINING_WORKSPACE_INVALID")


def _require_member(root: Path, member_path: str) -> Path:
    relative = PurePosixPath(member_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise TrainingRunnerError("IMAGE_TRAINING_MEMBER_PATH_INVALID")
    target = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise TrainingRunnerError("IMAGE_TRAINING_INPUT_MISSING") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise TrainingRunnerError("IMAGE_TRAINING_INPUT_INVALID")
    return target


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _load_inputs(
    workspace: Path,
    command: LocalImageLoraTrainingCommand,
) -> tuple[LocalImageLoraTrainingPlan, LocalImageTrainingDatasetManifest, Path]:
    plan_path = _require_member(workspace, command.staged_plan_member)
    plan_payload = _read_regular(plan_path, maximum_bytes=MAX_JSON_BYTES)
    if _sha256(plan_payload) != command.training_plan_pointer.sha256:
        raise TrainingRunnerError("IMAGE_TRAINING_PLAN_ARTIFACT_HASH_MISMATCH")
    plan_value = _parse_json(plan_payload)
    try:
        validate_contract("lora-training-plan", plan_value)
        plan = LocalImageLoraTrainingPlan.model_validate(plan_value)
    except Exception as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_PLAN_INVALID") from exc
    if plan != command.training_plan or plan.plan_sha256 != command.training_plan_sha256:
        raise TrainingRunnerError("IMAGE_TRAINING_PLAN_MISMATCH")

    dataset_root = _require_member(workspace, command.staged_dataset_root)
    dataset_path = _require_member(dataset_root, "manifests/training-dataset.json")
    dataset_payload = _read_regular(dataset_path, maximum_bytes=MAX_JSON_BYTES)
    if _sha256(dataset_payload) != plan.dataset_manifest.sha256:
        raise TrainingRunnerError("IMAGE_TRAINING_DATASET_ARTIFACT_HASH_MISMATCH")
    dataset_value = _parse_json(dataset_payload)
    try:
        validate_contract("training-dataset-manifest", dataset_value)
        dataset = LocalImageTrainingDatasetManifest.model_validate(dataset_value)
        validate_lora_training_plan(plan, dataset)
    except Exception as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_DATASET_INVALID") from exc
    for sample in dataset.samples:
        sample_path = _require_member(dataset_root, sample.crop_member.member_path)
        payload = _read_regular(sample_path, maximum_bytes=8 * 1024 * 1024)
        if (
            len(payload) != sample.crop_member.size_bytes
            or _sha256(payload) != sample.crop_member.sha256
        ):
            raise TrainingRunnerError("IMAGE_TRAINING_SAMPLE_HASH_MISMATCH")
    return plan, dataset, dataset_root


def _validate_safetensors(payload: bytes) -> None:
    if len(payload) < 16:
        raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
    header_length = int.from_bytes(payload[:8], "little")
    if not 2 <= header_length <= MAX_SAFETENSORS_HEADER_BYTES:
        raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
    header_end = 8 + header_length
    if header_end >= len(payload):
        raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
    try:
        header = json.loads(payload[8:header_end], object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID") from exc
    if not isinstance(header, dict):
        raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
    tensors = {key: value for key, value in header.items() if key != "__metadata__"}
    if not tensors:
        raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
    data_length = len(payload) - header_end
    for value in tensors.values():
        if not isinstance(value, dict):
            raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
        offsets = value.get("data_offsets")
        shape = value.get("shape")
        dtype = value.get("dtype")
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(item, int) for item in offsets)
            or offsets[0] < 0
            or offsets[0] >= offsets[1]
            or offsets[1] > data_length
            or not isinstance(shape, list)
            or not all(isinstance(item, int) and item >= 0 for item in shape)
            or not isinstance(dtype, str)
        ):
            raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")


def validate_adapter_files(output_root: Path) -> tuple[dict[str, object], ...]:
    """Validate the exact bounded LoRA adapter file set in one worker output."""

    values: list[dict[str, object]] = []
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        path = _require_member(output_root, name)
        payload = _read_regular(path, maximum_bytes=MAX_ADAPTER_BYTES)
        if name == "adapter_config.json":
            value = _parse_json(payload)
            if (
                value.get("peft_type") != "LORA"
                or value.get("r") != 8
                or value.get("lora_alpha") != 8
            ):
                raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
        else:
            _validate_safetensors(payload)
        values.append(
            {
                "relative_path": name,
                "size_bytes": len(payload),
                "sha256": _sha256(payload),
            }
        )
    return tuple(values)


def _runtime_matches_plan(
    runtime: LocalImageLoraTrainingRuntime,
    plan: LocalImageLoraTrainingPlan,
) -> None:
    expected = plan.dependencies
    for name in type(expected).model_fields:
        if getattr(runtime, name) != getattr(expected, name):
            raise TrainingRunnerError("IMAGE_TRAINING_RUNTIME_DRIFT")


def _worker_result(
    *,
    command: LocalImageLoraTrainingCommand,
    status: str,
    adapter_manifest: LocalImageLoraAdapterManifest | None,
    error_code: str | None,
    runtime: LocalImageLoraTrainingRuntime | None,
    completed_steps: int,
    final_loss: float | None,
    started_at: datetime,
    completed_at: datetime,
) -> LocalImageLoraTrainingWorkerResult:
    body = {
        "schema_version": "local-image-lora-training-worker-result/1.0",
        "training_run_id": command.training_run_id,
        "training_plan_pointer": command.training_plan_pointer.model_dump(mode="json"),
        "training_plan_sha256": command.training_plan_sha256,
        "attempt": command.attempt,
        "status": status,
        "adapter_manifest": (
            None if adapter_manifest is None else adapter_manifest.model_dump(mode="json")
        ),
        "error_code": error_code,
        "runtime": None if runtime is None else runtime.model_dump(mode="json"),
        "completed_steps": completed_steps,
        "final_loss": final_loss,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("lora-training-worker-result", value)
    result = LocalImageLoraTrainingWorkerResult.model_validate(value)
    validate_lora_training_worker_result(command, result)
    return result


def run_training_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageLoraTrainingCommand,
    backend: TrainingBackend,
    model_resolver: ModelResolver,
) -> LocalImageLoraTrainingWorkerResult:
    """Run one exact command and write one terminal local worker result."""

    _require_workspace(workspace)
    if (workspace / "result.json").exists() or (workspace / "result.json").is_symlink():
        raise TrainingRunnerError("IMAGE_TRAINING_RESULT_EXISTS")
    plan, dataset, dataset_root = _load_inputs(workspace, command)
    try:
        _, model_directory = model_resolver(model_store_root, plan.base_model)
    except Exception as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_MODEL_INVALID") from exc
    output_root = workspace / command.output_root_member
    checkpoint_root = workspace / command.checkpoint_root_member
    if output_root.exists() or output_root.is_symlink():
        raise TrainingRunnerError("IMAGE_TRAINING_OUTPUT_EXISTS")
    if checkpoint_root.exists() or checkpoint_root.is_symlink():
        _require_workspace(checkpoint_root)
    else:
        checkpoint_root.mkdir(mode=0o700)
    started_at = datetime.now(UTC)
    backend_result: TrainingBackendResult | None = None
    try:
        backend_result = backend.train(
            model_directory=model_directory,
            dataset=dataset,
            dataset_root=dataset_root,
            command=command,
            output_root=output_root,
            checkpoint_root=checkpoint_root,
        )
        _runtime_matches_plan(backend_result.runtime, plan)
        if backend_result.completed_steps != plan.hyperparameters.max_train_steps:
            raise TrainingRunnerError("IMAGE_TRAINING_STEP_COUNT_INVALID")
        files = validate_adapter_files(output_root)
        adapter_identity = content_sha256(
            {
                "training_plan": command.training_plan_pointer.model_dump(mode="json"),
                "training_run_id": command.training_run_id,
            }
        ).removeprefix("sha256:")
        revision_identity = content_sha256(
            {"adapter_identity": adapter_identity, "files": files}
        ).removeprefix("sha256:")
        manifest_body = {
            "schema_version": "local-image-lora-adapter-manifest/1.0",
            "adapter_id": "imgadapter_" + adapter_identity[:32],
            "adapter_revision_id": "imgadapterrev_" + revision_identity[:32],
            "state": "CANDIDATE",
            "base_model": plan.base_model.model_dump(mode="json"),
            "dataset_manifest": plan.dataset_manifest.model_dump(mode="json"),
            "training_plan": command.training_plan_pointer.model_dump(mode="json"),
            "files": list(files),
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        manifest_value = {
            **manifest_body,
            "manifest_sha256": content_sha256(manifest_body),
        }
        validate_contract("lora-adapter-manifest", manifest_value)
        adapter = LocalImageLoraAdapterManifest.model_validate(manifest_value)
        manifest_root = output_root / "manifests"
        manifest_root.mkdir(mode=0o700)
        _write_exclusive(
            manifest_root / "adapter-manifest.json",
            _canonical_json(manifest_value),
        )
        result = _worker_result(
            command=command,
            status="SUCCEEDED",
            adapter_manifest=adapter,
            error_code=None,
            runtime=backend_result.runtime,
            completed_steps=backend_result.completed_steps,
            final_loss=backend_result.final_loss,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
    except TrainingBackendFailure as exc:
        result = _worker_result(
            command=command,
            status="CANCELLED" if exc.cancelled else "FAILED",
            adapter_manifest=None,
            error_code=exc.code,
            runtime=exc.runtime,
            completed_steps=exc.completed_steps,
            final_loss=exc.final_loss,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
    except TrainingRunnerError as exc:
        result = _worker_result(
            command=command,
            status="FAILED",
            adapter_manifest=None,
            error_code=exc.code,
            runtime=None if backend_result is None else backend_result.runtime,
            completed_steps=(0 if backend_result is None else backend_result.completed_steps),
            final_loss=None if backend_result is None else backend_result.final_loss,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
    _write_exclusive(workspace / "result.json", _canonical_json(result.model_dump(mode="json")))
    return result
