"""Run one bounded base-versus-adapter image evaluation without NAS access."""

from __future__ import annotations

import gc
import io
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from eom_image_contracts import (
    LocalImageLoraMicroEvaluationCommand,
    LocalImageLoraMicroEvaluationOutput,
    LocalImageLoraMicroEvaluationResult,
    content_sha256,
    validate_contract,
    validate_micro_evaluation_result,
)
from PIL import Image, UnidentifiedImageError

from eom_image_trainer.diffusers_backend import (
    DETERMINISTIC_CUBLAS_WORKSPACE_CONFIG,
    TARGET_MODULES,
)
from eom_image_trainer.runner import (
    MAX_JSON_BYTES,
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


class MicroEvaluationRunnerError(RuntimeError):
    """Stable error at the isolated micro-evaluation boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class GeneratedEvaluationImage:
    sample_id: str
    variant: Literal["ADAPTER", "BASE"]
    png_bytes: bytes


class EvaluationBackend(Protocol):
    def generate_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageLoraMicroEvaluationCommand,
    ) -> tuple[GeneratedEvaluationImage, ...]: ...


def load_micro_evaluation_command(path: Path) -> LocalImageLoraMicroEvaluationCommand:
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        validate_contract("lora-micro-evaluation-command", value)
        return LocalImageLoraMicroEvaluationCommand.model_validate(value)
    except Exception as exc:
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_COMMAND_INVALID") from exc


def _validate_adapter(
    workspace: Path,
    command: LocalImageLoraMicroEvaluationCommand,
) -> Path:
    adapter_root = cast(Path, _require_member(workspace, command.staged_adapter_root))
    try:
        actual = validate_adapter_files(adapter_root)
    except TrainingRunnerError as exc:
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_ADAPTER_INVALID") from exc
    expected = tuple(value.model_dump(mode="json") for value in command.adapter_manifest.files)
    if actual != expected:
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_ADAPTER_HASH_MISMATCH")
    return adapter_root


def _output(
    *,
    command: LocalImageLoraMicroEvaluationCommand,
    generated: GeneratedEvaluationImage,
    workspace: Path,
) -> LocalImageLoraMicroEvaluationOutput:
    if generated.variant not in {"ADAPTER", "BASE"}:
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID")
    member_path = (
        f"{command.output_root_member}/{generated.sample_id}-{generated.variant.lower()}.png"
    )
    if not 64 <= len(generated.png_bytes) <= 64 * 1024 * 1024:
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID")
    try:
        with Image.open(io.BytesIO(generated.png_bytes)) as image:
            image.load()
            if image.format != "PNG" or image.size != (
                command.delivery_width,
                command.delivery_height,
            ):
                raise MicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID")
    except (OSError, UnidentifiedImageError) as exc:
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID") from exc
    try:
        output_root = _require_member(workspace, command.output_root_member)
        _write_exclusive(output_root / Path(member_path).name, generated.png_bytes)
    except TrainingRunnerError as exc:
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID") from exc
    return LocalImageLoraMicroEvaluationOutput(
        sample_id=generated.sample_id,
        variant=generated.variant,
        member_path=member_path,
        sha256=_sha256(generated.png_bytes),
        size_bytes=len(generated.png_bytes),
        width_px=command.delivery_width,
        height_px=command.delivery_height,
    )


def _result(
    *,
    command: LocalImageLoraMicroEvaluationCommand,
    status: str,
    outputs: tuple[LocalImageLoraMicroEvaluationOutput, ...],
    error_code: str | None,
    started_at: datetime,
) -> LocalImageLoraMicroEvaluationResult:
    body = {
        "schema_version": "local-image-lora-micro-evaluation-result/1.0",
        "evaluation_run_id": command.evaluation_run_id,
        "command_sha256": command.command_sha256,
        "training_result_sha256": command.training_result_sha256,
        "adapter_manifest_sha256": command.adapter_manifest.manifest_sha256,
        "status": status,
        "outputs": [value.model_dump(mode="json") for value in outputs],
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("lora-micro-evaluation-result", value)
    result = LocalImageLoraMicroEvaluationResult.model_validate(value)
    validate_micro_evaluation_result(command, result)
    return result


def run_micro_evaluation_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageLoraMicroEvaluationCommand,
    backend: EvaluationBackend,
    model_resolver: Any,
) -> LocalImageLoraMicroEvaluationResult:
    """Generate exact paired outputs and persist one terminal typed result."""

    _require_workspace(workspace)
    result_path = workspace / "result.json"
    if result_path.exists() or result_path.is_symlink():
        raise MicroEvaluationRunnerError("IMAGE_EVALUATION_RESULT_EXISTS")
    started_at = datetime.now(UTC)
    outputs: tuple[LocalImageLoraMicroEvaluationOutput, ...] = ()
    try:
        adapter_root = _validate_adapter(workspace, command)
        _manifest, model_directory = model_resolver(
            model_store_root,
            command.adapter_manifest.base_model,
        )
        output_root = workspace / command.output_root_member
        if output_root.exists() or output_root.is_symlink():
            raise MicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_EXISTS")
        output_root.mkdir(mode=0o700)
        generated = backend.generate_pairs(
            model_directory=model_directory,
            adapter_root=adapter_root,
            command=command,
        )
        values = tuple(
            sorted(
                (
                    _output(command=command, generated=value, workspace=workspace)
                    for value in generated
                ),
                key=lambda value: (value.sample_id, value.variant),
            )
        )
        outputs = values
        result = _result(
            command=command,
            status="SUCCEEDED",
            outputs=outputs,
            error_code=None,
            started_at=started_at,
        )
    except MicroEvaluationRunnerError as exc:
        result = _result(
            command=command,
            status="FAILED",
            outputs=outputs,
            error_code=exc.code,
            started_at=started_at,
        )
    _write_exclusive(result_path, _canonical_json(result.model_dump(mode="json")))
    return result


class Ssd1bMicroEvaluationBackend:
    """Use one immutable SSD-1B pipeline for paired base/LoRA generation."""

    def generate_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageLoraMicroEvaluationCommand,
    ) -> tuple[GeneratedEvaluationImage, ...]:
        try:
            import torch
            from diffusers import DiffusionPipeline
            from peft import LoraConfig
            from peft.utils import set_peft_model_state_dict
            from safetensors.torch import load_file
        except ImportError as exc:
            raise MicroEvaluationRunnerError("IMAGE_EVALUATION_DEPENDENCY_MISSING") from exc
        if (
            not torch.cuda.is_available()
            or torch.cuda.get_device_capability(0) != (12, 0)
            or os.environ.get("CUBLAS_WORKSPACE_CONFIG") != DETERMINISTIC_CUBLAS_WORKSPACE_CONFIG
        ):
            raise MicroEvaluationRunnerError("IMAGE_EVALUATION_RUNTIME_DRIFT")
        pipeline: Any | None = None
        try:
            torch.manual_seed(0)
            torch.cuda.manual_seed_all(0)
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            torch.use_deterministic_algorithms(True)
            pipeline = DiffusionPipeline.from_pretrained(
                str(model_directory),
                torch_dtype=torch.float16,
                variant="fp16",
                local_files_only=True,
                use_safetensors=True,
            )
            if (
                pipeline.scheduler.__class__.__name__ != "EulerDiscreteScheduler"
                or getattr(getattr(pipeline, "unet", None), "dtype", None) != torch.float16
            ):
                raise MicroEvaluationRunnerError("IMAGE_EVALUATION_MODEL_INVALID")
            _require_untruncated_prompts(pipeline, command)
            pipeline.set_progress_bar_config(disable=True)
            pipeline.to("cuda")
            values = _generate_variant(pipeline, command, "BASE", torch)
            pipeline.unet.add_adapter(
                LoraConfig(
                    r=8,
                    lora_alpha=8,
                    init_lora_weights="gaussian",
                    target_modules=list(TARGET_MODULES),
                ),
                adapter_name="micro_probe",
            )
            state = load_file(adapter_root / "adapter_model.safetensors")
            incompatible = set_peft_model_state_dict(
                pipeline.unet,
                state,
                adapter_name="micro_probe",
            )
            missing_adapter = [key for key in incompatible.missing_keys if "lora_" in key]
            if missing_adapter or incompatible.unexpected_keys:
                raise MicroEvaluationRunnerError("IMAGE_EVALUATION_ADAPTER_INVALID")
            pipeline.unet.set_adapter("micro_probe")
            values += _generate_variant(pipeline, command, "ADAPTER", torch)
            return tuple(sorted(values, key=lambda value: (value.sample_id, value.variant)))
        except MicroEvaluationRunnerError:
            raise
        except torch.cuda.OutOfMemoryError as exc:
            raise MicroEvaluationRunnerError("IMAGE_EVALUATION_OOM") from exc
        except Exception as exc:
            raise MicroEvaluationRunnerError("IMAGE_EVALUATION_EXEC_FAILED") from exc
        finally:
            if pipeline is not None:
                pipeline.to("cpu")
                del pipeline
            gc.collect()
            torch.cuda.empty_cache()


def _generate_variant(
    pipeline: Any,
    command: LocalImageLoraMicroEvaluationCommand,
    variant: Literal["ADAPTER", "BASE"],
    torch: Any,
) -> tuple[GeneratedEvaluationImage, ...]:
    values = []
    for case in command.cases:
        generator = torch.Generator(device="cuda").manual_seed(case.seed)
        response = pipeline(
            prompt=case.positive_prompt,
            negative_prompt=case.negative_prompt,
            width=command.generation_width,
            height=command.generation_height,
            num_inference_steps=command.inference_steps,
            guidance_scale=command.guidance_scale,
            generator=generator,
        )
        torch.cuda.synchronize(0)
        image = response.images[0].convert("RGB").crop((0, 2, 800, 502))
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=False, compress_level=9)
        values.append(
            GeneratedEvaluationImage(
                sample_id=case.sample_id,
                variant=variant,
                png_bytes=output.getvalue(),
            )
        )
    return tuple(values)


def _require_untruncated_prompts(
    pipeline: Any,
    command: LocalImageLoraMicroEvaluationCommand,
) -> None:
    for name in ("tokenizer", "tokenizer_2"):
        tokenizer = getattr(pipeline, name, None)
        maximum = getattr(tokenizer, "model_max_length", None)
        if tokenizer is None or not isinstance(maximum, int) or not 1 <= maximum <= 512:
            raise MicroEvaluationRunnerError("IMAGE_EVALUATION_MODEL_INVALID")
        for case in command.cases:
            for prompt in (case.positive_prompt, case.negative_prompt):
                try:
                    encoded = tokenizer(
                        prompt,
                        add_special_tokens=True,
                        padding=False,
                        truncation=False,
                        return_attention_mask=False,
                    )["input_ids"]
                except Exception as exc:
                    raise MicroEvaluationRunnerError("IMAGE_EVALUATION_MODEL_INVALID") from exc
                if (
                    not isinstance(encoded, list)
                    or not encoded
                    or isinstance(encoded[0], list)
                    or len(encoded) > maximum
                ):
                    raise MicroEvaluationRunnerError("IMAGE_EVALUATION_PROMPT_TOO_LONG")
