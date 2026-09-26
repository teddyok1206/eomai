"""Run one evaluation-only science-crop LoRA micro probe without DB or NAS access."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from eom_image_contracts import (
    ImageEvaluationBoundingBox,
    LocalImageLoraTrainingCommand,
    LocalImageLoraTrainingRuntime,
    LocalImageScienceLoraMicroAdapterManifest,
    LocalImageScienceLoraMicroProbeCommand,
    LocalImageScienceLoraMicroProbePlan,
    LocalImageScienceLoraMicroProbeWorkerResult,
    LocalImageScienceLoraMicroRealizedSample,
    LocalImageScienceVisualCropSet,
    LocalImageTrainingDatasetManifest,
    content_sha256,
    validate_contract,
    validate_science_micro_probe_plan_sources,
    validate_science_micro_probe_worker_result,
)
from PIL import Image

from eom_image_trainer.crop_processing import (
    CropProcessingError,
    PerceptualIndex,
    average_hash,
    decode_png,
    materialize_training_crop,
    png_bytes,
)
from eom_image_trainer.runner import (
    MAX_JSON_BYTES,
    TrainingBackend,
    TrainingBackendFailure,
    TrainingRunnerError,
    _canonical_json,
    _parse_json,
    _read_regular,
    _require_member,
    _require_workspace,
    _sha256,
    _write_exclusive,
    validate_adapter_files,
)

MAX_CROP_BYTES = 64 * 1024 * 1024
_FULL_CROP = ImageEvaluationBoundingBox(left=0, top=0, right=10_000, bottom=10_000)


class ScienceMicroProbeRunnerError(RuntimeError):
    """Stable worker error for the science micro-probe boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ModelResolver(Protocol):
    def __call__(self, model_store_root: Path, pointer: object) -> tuple[object, Path]: ...


@dataclass(frozen=True, slots=True)
class _RuntimeCropMember:
    member_path: str


@dataclass(frozen=True, slots=True)
class _RuntimeSample:
    caption_en: str
    crop_member: _RuntimeCropMember


@dataclass(frozen=True, slots=True)
class _RuntimeDataset:
    samples: tuple[_RuntimeSample, ...]


def load_science_micro_probe_command(path: Path) -> LocalImageScienceLoraMicroProbeCommand:
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        validate_contract("science-lora-micro-probe-command", value)
        return LocalImageScienceLoraMicroProbeCommand.model_validate(value)
    except Exception as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_COMMAND_INVALID") from exc


def _load_plan(
    workspace: Path,
    command: LocalImageScienceLoraMicroProbeCommand,
) -> LocalImageScienceLoraMicroProbePlan:
    payload = _read_regular(
        _require_member(workspace, command.staged_plan_member),
        maximum_bytes=MAX_JSON_BYTES,
    )
    if _sha256(payload) != command.probe_plan_pointer.sha256:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_PLAN_ARTIFACT_HASH_MISMATCH")
    try:
        value = _parse_json(payload)
        validate_contract("science-lora-micro-probe-plan", value)
        plan = LocalImageScienceLoraMicroProbePlan.model_validate(value)
    except Exception as exc:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_PLAN_INVALID") from exc
    if plan != command.probe_plan or plan.plan_sha256 != command.probe_plan_sha256:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_PLAN_MISMATCH")
    return plan


def _load_crop_set(
    workspace: Path,
    command: LocalImageScienceLoraMicroProbeCommand,
) -> LocalImageScienceVisualCropSet:
    payload = _read_regular(
        _require_member(workspace, command.staged_crop_set_member),
        maximum_bytes=MAX_JSON_BYTES,
    )
    if _sha256(payload) != command.probe_plan.crop_set.sha256:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_CROP_SET_HASH_MISMATCH")
    try:
        value = _parse_json(payload)
        validate_contract("science-visual-crop-set", value)
        crop_set = LocalImageScienceVisualCropSet.model_validate(value)
        validate_science_micro_probe_plan_sources(command.probe_plan, crop_set)
        return crop_set
    except Exception as exc:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_CROP_SET_INVALID") from exc


def _read_source_crop(
    workspace: Path,
    command: LocalImageScienceLoraMicroProbeCommand,
    *,
    candidate_id: str,
    expected_sha256: str,
) -> bytes:
    member = f"{command.staged_crops_root}/{candidate_id}.png"
    payload = _read_regular(_require_member(workspace, member), maximum_bytes=MAX_CROP_BYTES)
    if _sha256(payload) != expected_sha256:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_SOURCE_CROP_HASH_MISMATCH")
    return cast(bytes, payload)


def _materialize_samples(
    *,
    workspace: Path,
    command: LocalImageScienceLoraMicroProbeCommand,
    crop_set: LocalImageScienceVisualCropSet,
) -> tuple[
    Path,
    _RuntimeDataset,
    tuple[LocalImageScienceLoraMicroRealizedSample, ...],
    str,
]:
    dataset_root = workspace / command.runtime_dataset_root
    if dataset_root.exists() or dataset_root.is_symlink():
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_RUNTIME_DATASET_EXISTS")
    samples_root = dataset_root / "samples"
    dataset_root.mkdir(mode=0o700)
    samples_root.mkdir(mode=0o700)
    members = {value.candidate_id: value for value in crop_set.members}
    exact_hashes: set[str] = set()
    perceptual = PerceptualIndex()
    decoded: dict[str, Image.Image] = {}
    values: list[tuple[LocalImageScienceLoraMicroRealizedSample, _RuntimeSample]] = []
    try:
        for candidate_id in command.probe_plan.training_member_ids:
            member = members[candidate_id]
            source = decoded.get(candidate_id)
            if source is None:
                source = decode_png(
                    _read_source_crop(
                        workspace,
                        command,
                        candidate_id=candidate_id,
                        expected_sha256=member.sha256,
                    )
                )
                decoded[candidate_id] = source
            image = materialize_training_crop(source, crop_box=_FULL_CROP)
            payload = png_bytes(image)
            realized_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
            perceptual_hash, perceptual_value = average_hash(image)
            if realized_sha256 in exact_hashes or perceptual.contains_near_duplicate(
                perceptual_value
            ):
                raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_MICRO_DATASET_DUPLICATE")
            identity = content_sha256(
                {
                    "probe_id": command.probe_plan.probe_id,
                    "candidate_id": candidate_id,
                    "realized_crop_sha256": realized_sha256,
                    "caption_sha256": member.caption_sha256,
                }
            ).removeprefix("sha256:")
            sample_id = "imgtrainsample_" + identity[:32]
            member_path = f"samples/{sample_id}.png"
            _write_exclusive(dataset_root / member_path, payload)
            realized = LocalImageScienceLoraMicroRealizedSample(
                candidate_id=candidate_id,
                document_id=member.document_id,
                exam_group_sha256=member.exam_group_sha256,
                training_sample_id=sample_id,
                source_crop_sha256=member.sha256,
                realized_crop_sha256=realized_sha256,
                caption_sha256=member.caption_sha256,
                perceptual_hash=perceptual_hash,
            )
            values.append(
                (
                    realized,
                    _RuntimeSample(
                        caption_en=member.caption_en,
                        crop_member=_RuntimeCropMember(member_path=member_path),
                    ),
                )
            )
            exact_hashes.add(realized_sha256)
            perceptual.add(perceptual_value)
        if len(values) != 12:
            raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_MICRO_DATASET_TOO_SMALL")
        values.sort(key=lambda value: value[0].training_sample_id)
        realized_samples = tuple(value[0] for value in values)
        runtime_dataset = _RuntimeDataset(samples=tuple(value[1] for value in values))
        sample_set_sha256 = content_sha256(
            [value.model_dump(mode="json") for value in realized_samples]
        )
        return dataset_root, runtime_dataset, realized_samples, sample_set_sha256
    except Exception:
        if dataset_root.exists() and not dataset_root.is_symlink():
            shutil.rmtree(dataset_root)
        raise


def _runtime_matches_plan(
    runtime: object,
    plan: LocalImageScienceLoraMicroProbePlan,
) -> None:
    for name in type(plan.dependencies).model_fields:
        if getattr(runtime, name) != getattr(plan.dependencies, name):
            raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_RUNTIME_DRIFT")


def _result(
    *,
    command: LocalImageScienceLoraMicroProbeCommand,
    status: str,
    adapter_manifest: LocalImageScienceLoraMicroAdapterManifest | None,
    realized_samples: tuple[LocalImageScienceLoraMicroRealizedSample, ...],
    sample_set_sha256: str | None,
    error_code: str | None,
    runtime: LocalImageLoraTrainingRuntime | None,
    completed_steps: int,
    final_loss: float | None,
    started_at: datetime,
    completed_at: datetime,
) -> LocalImageScienceLoraMicroProbeWorkerResult:
    body = {
        "schema_version": "local-image-science-lora-micro-probe-worker-result/1.0",
        "training_run_id": command.training_run_id,
        "probe_plan_pointer": command.probe_plan_pointer.model_dump(mode="json"),
        "probe_plan_sha256": command.probe_plan_sha256,
        "command_sha256": command.command_sha256,
        "attempt": command.attempt,
        "status": status,
        "adapter_manifest": (
            None if adapter_manifest is None else adapter_manifest.model_dump(mode="json")
        ),
        "realized_samples": [value.model_dump(mode="json") for value in realized_samples],
        "sample_set_sha256": sample_set_sha256,
        "error_code": error_code,
        "runtime": None if runtime is None else runtime.model_dump(mode="json"),
        "completed_steps": completed_steps,
        "final_loss": final_loss,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("science-lora-micro-probe-worker-result", value)
    result = LocalImageScienceLoraMicroProbeWorkerResult.model_validate(value)
    validate_science_micro_probe_worker_result(command, result)
    return result


def run_science_micro_probe_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageScienceLoraMicroProbeCommand,
    backend: TrainingBackend,
    model_resolver: ModelResolver,
) -> LocalImageScienceLoraMicroProbeWorkerResult:
    """Materialize exact reviewed science crops and run one bounded probe."""

    _require_workspace(workspace)
    if (workspace / "result.json").exists() or (workspace / "result.json").is_symlink():
        raise TrainingRunnerError("IMAGE_TRAINING_RESULT_EXISTS")
    plan = _load_plan(workspace, command)
    crop_set = _load_crop_set(workspace, command)
    try:
        validate_science_micro_probe_plan_sources(plan, crop_set)
        _manifest, model_directory = model_resolver(model_store_root, plan.base_model)
    except ValueError as exc:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_MICRO_PLAN_SOURCE_INVALID") from exc
    except Exception as exc:
        raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_MODEL_INVALID") from exc
    output_root = workspace / command.output_root_member
    checkpoint_root = workspace / command.checkpoint_root_member
    if output_root.exists() or output_root.is_symlink():
        raise TrainingRunnerError("IMAGE_TRAINING_OUTPUT_EXISTS")
    if checkpoint_root.exists() or checkpoint_root.is_symlink():
        _require_workspace(checkpoint_root)
    else:
        checkpoint_root.mkdir(mode=0o700)
    started_at = datetime.now(UTC)
    realized_samples: tuple[LocalImageScienceLoraMicroRealizedSample, ...] = ()
    sample_set_sha256: str | None = None
    backend_result = None
    try:
        dataset_root, runtime_dataset, realized_samples, sample_set_sha256 = _materialize_samples(
            workspace=workspace,
            command=command,
            crop_set=crop_set,
        )
        backend_result = backend.train(
            model_directory=model_directory,
            dataset=cast(LocalImageTrainingDatasetManifest, runtime_dataset),
            dataset_root=dataset_root,
            command=cast(LocalImageLoraTrainingCommand, command),
            output_root=output_root,
            checkpoint_root=checkpoint_root,
        )
        _runtime_matches_plan(backend_result.runtime, plan)
        if backend_result.completed_steps != 200:
            raise ScienceMicroProbeRunnerError("IMAGE_TRAINING_STEP_COUNT_INVALID")
        files = validate_adapter_files(output_root)
        adapter_identity = content_sha256(
            {
                "probe_plan": command.probe_plan_pointer.model_dump(mode="json"),
                "training_run_id": command.training_run_id,
            }
        ).removeprefix("sha256:")
        revision_identity = content_sha256(
            {"adapter_identity": adapter_identity, "files": files}
        ).removeprefix("sha256:")
        manifest_body = {
            "schema_version": "local-image-science-lora-micro-adapter-manifest/1.0",
            "adapter_id": "imgadapter_" + adapter_identity[:32],
            "adapter_revision_id": "imgadapterrev_" + revision_identity[:32],
            "state": "EVALUATION_ONLY",
            "activation_policy": "FORBIDDEN",
            "base_model": plan.base_model.model_dump(mode="json"),
            "probe_plan": command.probe_plan_pointer.model_dump(mode="json"),
            "sample_set_sha256": sample_set_sha256,
            "files": list(files),
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        manifest_value = {
            **manifest_body,
            "manifest_sha256": content_sha256(manifest_body),
        }
        validate_contract("science-lora-micro-adapter-manifest", manifest_value)
        adapter = LocalImageScienceLoraMicroAdapterManifest.model_validate(manifest_value)
        manifest_root = output_root / "manifests"
        manifest_root.mkdir(mode=0o700)
        _write_exclusive(
            manifest_root / "adapter-manifest.json",
            _canonical_json(manifest_value),
        )
        result = _result(
            command=command,
            status="SUCCEEDED",
            adapter_manifest=adapter,
            realized_samples=realized_samples,
            sample_set_sha256=sample_set_sha256,
            error_code=None,
            runtime=backend_result.runtime,
            completed_steps=backend_result.completed_steps,
            final_loss=backend_result.final_loss,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
    except (CropProcessingError, ScienceMicroProbeRunnerError, TrainingRunnerError) as exc:
        result = _result(
            command=command,
            status="FAILED",
            adapter_manifest=None,
            realized_samples=realized_samples,
            sample_set_sha256=sample_set_sha256,
            error_code=exc.code,
            runtime=None if backend_result is None else backend_result.runtime,
            completed_steps=0 if backend_result is None else backend_result.completed_steps,
            final_loss=None if backend_result is None else backend_result.final_loss,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
    except TrainingBackendFailure as exc:
        result = _result(
            command=command,
            status="CANCELLED" if exc.cancelled else "FAILED",
            adapter_manifest=None,
            realized_samples=realized_samples,
            sample_set_sha256=sample_set_sha256,
            error_code=exc.code,
            runtime=exc.runtime,
            completed_steps=exc.completed_steps,
            final_loss=exc.final_loss,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
    _write_exclusive(workspace / "result.json", _canonical_json(result.model_dump(mode="json")))
    return result
