"""Run one evaluation-only LoRA micro probe without PostgreSQL or NAS access."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from eom_image_contracts import (
    LocalImageLoraMicroAdapterManifest,
    LocalImageLoraMicroProbeCommand,
    LocalImageLoraMicroProbePlan,
    LocalImageLoraMicroProbeWorkerResult,
    LocalImageLoraMicroRealizedSample,
    LocalImageLoraTrainingCommand,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCropProposalSet,
    LocalImageTrainingDatasetManifest,
    content_sha256,
    validate_contract,
    validate_micro_probe_plan_sources,
    validate_micro_probe_worker_result,
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

MAX_PAGE_BYTES = 64 * 1024 * 1024


class MicroProbeRunnerError(RuntimeError):
    """Stable worker error for the micro-probe boundary."""

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


def load_micro_probe_command(path: Path) -> LocalImageLoraMicroProbeCommand:
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        validate_contract("lora-micro-probe-command", value)
        return LocalImageLoraMicroProbeCommand.model_validate(value)
    except Exception as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_COMMAND_INVALID") from exc


def _load_plan(
    workspace: Path,
    command: LocalImageLoraMicroProbeCommand,
) -> LocalImageLoraMicroProbePlan:
    payload = _read_regular(
        _require_member(workspace, command.staged_plan_member),
        maximum_bytes=MAX_JSON_BYTES,
    )
    if _sha256(payload) != command.probe_plan_pointer.sha256:
        raise MicroProbeRunnerError("IMAGE_TRAINING_PLAN_ARTIFACT_HASH_MISMATCH")
    try:
        value = _parse_json(payload)
        validate_contract("lora-micro-probe-plan", value)
        plan = LocalImageLoraMicroProbePlan.model_validate(value)
    except Exception as exc:
        raise MicroProbeRunnerError("IMAGE_TRAINING_PLAN_INVALID") from exc
    if plan != command.probe_plan or plan.plan_sha256 != command.probe_plan_sha256:
        raise MicroProbeRunnerError("IMAGE_TRAINING_PLAN_MISMATCH")
    return plan


def _load_proposal_set(
    workspace: Path,
    command: LocalImageLoraMicroProbeCommand,
) -> LocalImageTrainingCropProposalSet:
    payload = _read_regular(
        _require_member(workspace, command.staged_proposal_set_member),
        maximum_bytes=MAX_JSON_BYTES,
    )
    if _sha256(payload) != command.probe_plan.crop_proposal_set.sha256:
        raise MicroProbeRunnerError("IMAGE_TRAINING_PROPOSAL_SET_HASH_MISMATCH")
    try:
        value = _parse_json(payload)
        validate_contract("training-crop-proposal-set", value)
        return LocalImageTrainingCropProposalSet.model_validate(value)
    except Exception as exc:
        raise MicroProbeRunnerError("IMAGE_TRAINING_PROPOSAL_SET_INVALID") from exc


def _load_authorization(
    workspace: Path,
    command: LocalImageLoraMicroProbeCommand,
) -> LocalImageTrainingAuthorization:
    payload = _read_regular(
        _require_member(workspace, command.staged_authorization_member),
        maximum_bytes=MAX_JSON_BYTES,
    )
    if _sha256(payload) != command.probe_plan.training_authorization.sha256:
        raise MicroProbeRunnerError("IMAGE_TRAINING_AUTHORIZATION_HASH_MISMATCH")
    try:
        value = _parse_json(payload)
        validate_contract("training-authorization", value)
        return LocalImageTrainingAuthorization.model_validate(value)
    except Exception as exc:
        raise MicroProbeRunnerError("IMAGE_TRAINING_AUTHORIZATION_INVALID") from exc


def _read_source_page(workspace: Path, sha256: str) -> bytes:
    page = _require_member(workspace, f"inputs/pages/{sha256.removeprefix('sha256:')}.png")
    payload = _read_regular(page, maximum_bytes=MAX_PAGE_BYTES)
    if _sha256(payload) != sha256:
        raise MicroProbeRunnerError("IMAGE_TRAINING_SOURCE_PAGE_HASH_MISMATCH")
    return payload


def _materialize_samples(
    *,
    workspace: Path,
    command: LocalImageLoraMicroProbeCommand,
    proposal_set: LocalImageTrainingCropProposalSet,
) -> tuple[
    Path,
    _RuntimeDataset,
    tuple[LocalImageLoraMicroRealizedSample, ...],
    str,
]:
    dataset_root = workspace / command.runtime_dataset_root
    if dataset_root.exists() or dataset_root.is_symlink():
        raise MicroProbeRunnerError("IMAGE_TRAINING_RUNTIME_DATASET_EXISTS")
    samples_root = dataset_root / "samples"
    dataset_root.mkdir(mode=0o700)
    samples_root.mkdir(mode=0o700)
    proposals = {value.crop_proposal_id: value for value in proposal_set.proposals}
    exact_hashes: set[str] = set()
    perceptual = PerceptualIndex()
    decoded_pages: dict[str, Image.Image] = {}
    values: list[tuple[LocalImageLoraMicroRealizedSample, _RuntimeSample]] = []
    try:
        for selection in command.probe_plan.selections:
            proposal = proposals[selection.crop_proposal_id]
            page_sha256 = proposal.source_page_image.sha256
            source = decoded_pages.get(page_sha256)
            if source is None:
                source = decode_png(_read_source_page(workspace, page_sha256))
                decoded_pages[page_sha256] = source
            image = materialize_training_crop(
                source,
                crop_box=proposal.crop_bounding_box,
                redaction_boxes=proposal.redaction_boxes,
            )
            payload = png_bytes(image)
            crop_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
            perceptual_hash, perceptual_value = average_hash(image)
            if crop_sha256 in exact_hashes or perceptual.contains_near_duplicate(perceptual_value):
                continue
            identity = content_sha256(
                {
                    "probe_id": command.probe_plan.probe_id,
                    "crop_proposal_id": proposal.crop_proposal_id,
                    "crop_sha256": crop_sha256,
                    "caption_sha256": selection.caption_sha256,
                }
            ).removeprefix("sha256:")
            sample_id = "imgtrainsample_" + identity[:32]
            member_path = f"samples/{sample_id}.png"
            _write_exclusive(dataset_root / member_path, payload)
            realized = LocalImageLoraMicroRealizedSample(
                source_anchor_id=proposal.source_anchor_id,
                crop_proposal_id=proposal.crop_proposal_id,
                training_sample_id=sample_id,
                crop_sha256=crop_sha256,
                caption_sha256=selection.caption_sha256,
                perceptual_hash=perceptual_hash,
            )
            values.append(
                (
                    realized,
                    _RuntimeSample(
                        caption_en=selection.caption_en,
                        crop_member=_RuntimeCropMember(member_path=member_path),
                    ),
                )
            )
            exact_hashes.add(crop_sha256)
            perceptual.add(perceptual_value)
        if len(values) < 12:
            raise MicroProbeRunnerError("IMAGE_TRAINING_MICRO_DATASET_TOO_SMALL")
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


def _runtime_matches_plan(runtime: object, plan: LocalImageLoraMicroProbePlan) -> None:
    for name in type(plan.dependencies).model_fields:
        if getattr(runtime, name) != getattr(plan.dependencies, name):
            raise MicroProbeRunnerError("IMAGE_TRAINING_RUNTIME_DRIFT")


def _result(
    *,
    command: LocalImageLoraMicroProbeCommand,
    status: str,
    adapter_manifest: LocalImageLoraMicroAdapterManifest | None,
    realized_samples: tuple[LocalImageLoraMicroRealizedSample, ...],
    sample_set_sha256: str | None,
    error_code: str | None,
    runtime: LocalImageLoraTrainingRuntime | None,
    completed_steps: int,
    final_loss: float | None,
    started_at: datetime,
    completed_at: datetime,
) -> LocalImageLoraMicroProbeWorkerResult:
    body = {
        "schema_version": "local-image-lora-micro-probe-worker-result/1.0",
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
    validate_contract("lora-micro-probe-worker-result", value)
    result = LocalImageLoraMicroProbeWorkerResult.model_validate(value)
    validate_micro_probe_worker_result(command, result)
    return result


def run_micro_probe_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageLoraMicroProbeCommand,
    backend: TrainingBackend,
    model_resolver: ModelResolver,
) -> LocalImageLoraMicroProbeWorkerResult:
    """Materialize redacted samples and run one exact evaluation-only probe."""

    _require_workspace(workspace)
    if (workspace / "result.json").exists() or (workspace / "result.json").is_symlink():
        raise TrainingRunnerError("IMAGE_TRAINING_RESULT_EXISTS")
    plan = _load_plan(workspace, command)
    proposal_set = _load_proposal_set(workspace, command)
    authorization = _load_authorization(workspace, command)
    try:
        validate_micro_probe_plan_sources(plan, proposal_set, authorization)
    except ValueError as exc:
        raise MicroProbeRunnerError("IMAGE_TRAINING_MICRO_PLAN_SOURCE_INVALID") from exc
    try:
        _manifest, model_directory = model_resolver(model_store_root, plan.base_model)
    except Exception as exc:
        raise MicroProbeRunnerError("IMAGE_TRAINING_MODEL_INVALID") from exc
    output_root = workspace / command.output_root_member
    checkpoint_root = workspace / command.checkpoint_root_member
    if output_root.exists() or output_root.is_symlink():
        raise TrainingRunnerError("IMAGE_TRAINING_OUTPUT_EXISTS")
    if checkpoint_root.exists() or checkpoint_root.is_symlink():
        _require_workspace(checkpoint_root)
    else:
        checkpoint_root.mkdir(mode=0o700)
    started_at = datetime.now(UTC)
    realized_samples: tuple[LocalImageLoraMicroRealizedSample, ...] = ()
    sample_set_sha256: str | None = None
    backend_result = None
    try:
        dataset_root, runtime_dataset, realized_samples, sample_set_sha256 = _materialize_samples(
            workspace=workspace,
            command=command,
            proposal_set=proposal_set,
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
            raise MicroProbeRunnerError("IMAGE_TRAINING_STEP_COUNT_INVALID")
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
            "schema_version": "local-image-lora-micro-adapter-manifest/1.0",
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
        validate_contract("lora-micro-adapter-manifest", manifest_value)
        adapter = LocalImageLoraMicroAdapterManifest.model_validate(manifest_value)
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
    except (CropProcessingError, MicroProbeRunnerError, TrainingRunnerError) as exc:
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
