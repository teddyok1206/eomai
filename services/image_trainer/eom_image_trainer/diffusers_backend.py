"""Shared numerical UNet LoRA adapter with an unchanged SSD checkpoint boundary."""

from __future__ import annotations

import gc
import math
import os
import platform
import random
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

from eom_image_contracts import (
    LocalImageLoraHyperparameters,
    LocalImageLoraMicroHyperparameters,
    LocalImageLoraTrainingCommand,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainerDependencies,
    LocalImageTrainingDatasetManifest,
)
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraHyperparameters
from eom_image_contracts.sdxl_native_training_targets import NATIVE_TARGET_CANVASES

from eom_image_trainer.checkpoints import load_latest_checkpoint, save_checkpoint
from eom_image_trainer.runner import (
    TrainingBackendFailure,
    TrainingBackendResult,
)

TARGET_MODULES = ("to_k", "to_out.0", "to_q", "to_v")
DETERMINISTIC_CUBLAS_WORKSPACE_CONFIG = ":4096:8"
LoraHyperparameters = (
    LocalImageLoraHyperparameters
    | LocalImageLoraMicroHyperparameters
    | SdxlNativeLoraHyperparameters
)
_ADMITTED_CANVASES = frozenset({(768, 512), *NATIVE_TARGET_CANVASES.values()})


@dataclass(frozen=True, slots=True)
class LoraTensorSample:
    caption_en: str
    image_path: Path
    width_px: int = 768
    height_px: int = 512

    def __post_init__(self) -> None:
        if (self.width_px, self.height_px) not in _ADMITTED_CANVASES:
            raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")

    @property
    def sdxl_time_ids(self) -> tuple[int, int, int, int, int, int]:
        # The prepared canvas is the exact encoded image; no training crop/resize occurs.
        return (self.height_px, self.width_px, 0, 0, self.height_px, self.width_px)


@dataclass(frozen=True, slots=True)
class VaeWeightLocation:
    directory: Path
    subfolder: str | None
    variant: str | None


@dataclass(frozen=True, slots=True)
class LoraTrainingRecipe:
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LoraHyperparameters
    seed: int


@dataclass(frozen=True, slots=True)
class LoraTrainingBudget:
    maximum_duration_ms: int
    maximum_peak_gpu_memory_bytes: int


@dataclass(frozen=True, slots=True)
class LoraCheckpointProgress:
    completed_steps: int
    micro_steps: int


class LoraCheckpointPolicy(Protocol):
    def load(self, *, model: Any, optimizer: Any, torch: Any) -> LoraCheckpointProgress | None: ...

    def save(
        self, *, model: Any, optimizer: Any, completed_steps: int, micro_steps: int, torch: Any
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _SsdCheckpointPolicy:
    command: LocalImageLoraTrainingCommand
    root: Path

    def load(self, *, model: Any, optimizer: Any, torch: Any) -> LoraCheckpointProgress | None:
        restored = load_latest_checkpoint(
            root=self.root, command=self.command, model=model, optimizer=optimizer, torch=torch
        )
        return (
            LoraCheckpointProgress(restored.completed_steps, restored.micro_steps)
            if restored is not None
            else None
        )

    def save(
        self, *, model: Any, optimizer: Any, completed_steps: int, micro_steps: int, torch: Any
    ) -> None:
        save_checkpoint(
            root=self.root,
            command=self.command,
            model=model,
            optimizer=optimizer,
            completed_steps=completed_steps,
            micro_steps=micro_steps,
            torch=torch,
        )


class Ssd1bLoraBackend:
    """Retain the released SSD command and its pinned checkpoint semantics."""

    def train(
        self,
        *,
        model_directory: Path,
        dataset: LocalImageTrainingDatasetManifest,
        dataset_root: Path,
        command: LocalImageLoraTrainingCommand,
        output_root: Path,
        checkpoint_root: Path,
    ) -> TrainingBackendResult:
        plan = command.training_plan
        return DiffusersUnetLoraBackend().train(
            model_directory=model_directory,
            vae_source=VaeWeightLocation(model_directory, "vae", "fp16"),
            samples=tuple(
                LoraTensorSample(sample.caption_en, dataset_root / sample.crop_member.member_path)
                for sample in dataset.samples
            ),
            recipe=LoraTrainingRecipe(plan.dependencies, plan.hyperparameters, plan.seed),
            output_root=output_root,
            checkpoint_policy=_SsdCheckpointPolicy(command, checkpoint_root),
        )


def _require_training_budget(
    *, budget: LoraTrainingBudget | None, started: float, torch: Any
) -> None:
    if budget is not None and (
        (time.monotonic() - started) * 1000 > budget.maximum_duration_ms
        or torch.cuda.max_memory_allocated(0) > budget.maximum_peak_gpu_memory_bytes
    ):
        raise TrainingBackendFailure("IMAGE_TRAINING_RESOURCE_BUDGET_EXCEEDED")


def _require_deterministic_runtime() -> None:
    """Fail before model work when CUDA determinism cannot be honored."""

    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != DETERMINISTIC_CUBLAS_WORKSPACE_CONFIG:
        raise TrainingBackendFailure("IMAGE_TRAINING_RUNTIME_DRIFT")


def _sample_order(*, epoch: int, count: int, seed: int) -> tuple[int, ...]:
    values = list(range(count))
    random.Random(seed + epoch).shuffle(values)
    return tuple(values)


def _versions() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "torch_version": metadata.version("torch"),
        "diffusers_version": metadata.version("diffusers"),
        "transformers_version": metadata.version("transformers"),
        "accelerate_version": metadata.version("accelerate"),
        "peft_version": metadata.version("peft"),
        "bitsandbytes_version": metadata.version("bitsandbytes"),
    }


def _runtime_snapshot(*, versions: dict[str, str], torch: Any) -> LocalImageLoraTrainingRuntime:
    capability = torch.cuda.get_device_capability(0)
    cuda_version = torch.version.cuda
    if not isinstance(cuda_version, str):
        raise TrainingBackendFailure("IMAGE_TRAINING_GPU_UNAVAILABLE")
    return LocalImageLoraTrainingRuntime.model_validate(
        {
            **versions,
            "cuda_version": cuda_version,
            "gpu_name": torch.cuda.get_device_name(0),
            "compute_capability": f"{capability[0]}.{capability[1]}",
            "peak_gpu_memory_bytes": max(1, torch.cuda.max_memory_allocated(0)),
        }
    )


def _canonical_config(
    hyperparameters: LoraHyperparameters,
) -> bytes:
    import json

    value = {
        "base_model_name_or_path": "PINNED_LOCAL_MODEL_REVISION",
        "bias": "none",
        "inference_mode": True,
        "lora_alpha": hyperparameters.alpha,
        "peft_type": "LORA",
        "r": hyperparameters.rank,
        "target_modules": list(TARGET_MODULES),
        "task_type": None,
    }
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _write_config(path: Path, payload: bytes) -> None:
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


def _save_final_adapter(
    *,
    model: Any,
    hyperparameters: LoraHyperparameters,
    output_root: Path,
) -> None:
    from peft.utils import get_peft_model_state_dict  # type: ignore[import-not-found]
    from safetensors.torch import save_file  # type: ignore[import-not-found]

    temporary = output_root.parent / f".{output_root.name}-tmp-{os.getpid()}"
    if output_root.exists() or output_root.is_symlink():
        raise TrainingBackendFailure("IMAGE_TRAINING_OUTPUT_EXISTS")
    if temporary.exists() or temporary.is_symlink():
        raise TrainingBackendFailure("IMAGE_TRAINING_OUTPUT_EXISTS")
    temporary.mkdir(mode=0o700)
    try:
        adapter_state = {
            name: tensor.detach().to("cpu").contiguous()
            for name, tensor in get_peft_model_state_dict(
                model,
                adapter_name="default",
            ).items()
        }
        if not adapter_state:
            raise TrainingBackendFailure("IMAGE_TRAINING_ADAPTER_INVALID")
        if any(not bool(tensor.isfinite().all().item()) for tensor in adapter_state.values()):
            raise TrainingBackendFailure("IMAGE_TRAINING_ADAPTER_NONFINITE")
        weights = temporary / "adapter_model.safetensors"
        save_file(adapter_state, weights)
        weights.chmod(0o600)
        _write_config(temporary / "adapter_config.json", _canonical_config(hyperparameters))
        os.rename(temporary, output_root)
        parent_descriptor = os.open(output_root.parent, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except TrainingBackendFailure:
        raise
    except Exception as exc:
        raise TrainingBackendFailure("IMAGE_TRAINING_ADAPTER_WRITE_FAILED") from exc


def _prompt_embeddings(
    *,
    model_directory: Path,
    captions: tuple[str, ...],
    torch: Any,
) -> tuple[tuple[Any, Any], ...]:
    from transformers import (  # type: ignore[import-not-found]
        AutoTokenizer,
        CLIPTextModel,
        CLIPTextModelWithProjection,
    )

    tokenizers = (
        AutoTokenizer.from_pretrained(
            model_directory,
            subfolder="tokenizer",
            local_files_only=True,
            use_fast=False,
        ),
        AutoTokenizer.from_pretrained(
            model_directory,
            subfolder="tokenizer_2",
            local_files_only=True,
            use_fast=False,
        ),
    )
    encoders = (
        CLIPTextModel.from_pretrained(
            model_directory,
            subfolder="text_encoder",
            variant="fp16",
            torch_dtype=torch.float16,
            local_files_only=True,
            use_safetensors=True,
        ),
        CLIPTextModelWithProjection.from_pretrained(
            model_directory,
            subfolder="text_encoder_2",
            variant="fp16",
            torch_dtype=torch.float16,
            local_files_only=True,
            use_safetensors=True,
        ),
    )
    for encoder in encoders:
        encoder.requires_grad_(False)
        encoder.eval()
        encoder.to("cuda")
    values: list[tuple[Any, Any]] = []
    try:
        with torch.no_grad():
            for caption in captions:
                hidden_states = []
                pooled = None
                for tokenizer, encoder in zip(tokenizers, encoders, strict=True):
                    input_ids = tokenizer(
                        caption,
                        padding="max_length",
                        max_length=tokenizer.model_max_length,
                        truncation=False,
                        return_tensors="pt",
                    ).input_ids
                    if input_ids.shape[-1] > tokenizer.model_max_length:
                        raise TrainingBackendFailure("IMAGE_TRAINING_CAPTION_TOO_LONG")
                    encoded = encoder(input_ids.to("cuda"), output_hidden_states=True)
                    hidden_states.append(encoded.hidden_states[-2])
                    pooled = encoded[0]
                assert pooled is not None
                values.append(
                    (
                        torch.cat(hidden_states, dim=-1).to("cpu"),
                        pooled.to("cpu"),
                    )
                )
    finally:
        for encoder in encoders:
            encoder.to("cpu")
        del encoders
        gc.collect()
        torch.cuda.empty_cache()
    return tuple(values)


def _latents(
    *,
    vae_source: VaeWeightLocation,
    samples: tuple[LoraTensorSample, ...],
    seed: int,
    torch: Any,
) -> tuple[Any, ...]:
    from diffusers import AutoencoderKL  # type: ignore[import-not-found]
    from PIL import Image

    location: dict[str, str] = {}
    if vae_source.subfolder is not None:
        location["subfolder"] = vae_source.subfolder
    if vae_source.variant is not None:
        location["variant"] = vae_source.variant
    vae = AutoencoderKL.from_pretrained(
        vae_source.directory,
        **location,
        torch_dtype=torch.float16,
        local_files_only=True,
        use_safetensors=True,
    )
    vae.requires_grad_(False)
    vae.eval()
    vae.to("cuda")
    generator = torch.Generator(device="cuda").manual_seed(seed)
    values: list[Any] = []
    try:
        with torch.no_grad():
            for sample in samples:
                with Image.open(sample.image_path) as source:
                    source.load()
                    if source.format != "PNG" or source.size != (
                        sample.width_px,
                        sample.height_px,
                    ):
                        raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
                    if source.size != (768, 512) and source.mode != "RGB":
                        raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
                    rgb = source if source.mode == "RGB" else source.convert("RGB")
                    payload = bytearray(rgb.tobytes())
                image = torch.frombuffer(payload, dtype=torch.uint8).reshape(
                    sample.height_px, sample.width_px, 3
                )
                image = image.permute(2, 0, 1).unsqueeze(0).to("cuda", dtype=torch.float16)
                image = image.div(127.5).sub(1.0)
                latent = vae.encode(image).latent_dist.sample(generator=generator)
                if not bool(torch.isfinite(latent).all().item()):
                    raise TrainingBackendFailure("IMAGE_TRAINING_LATENT_NONFINITE")
                latent = latent.mul(vae.config.scaling_factor).to("cpu")
                values.append(latent)
    finally:
        vae.to("cpu")
        del vae
        gc.collect()
        torch.cuda.empty_cache()
    return tuple(values)


class DiffusersUnetLoraBackend:
    """Train only UNet LoRA parameters with frozen precomputed conditioning."""

    def train(
        self,
        *,
        model_directory: Path,
        vae_source: VaeWeightLocation,
        samples: tuple[LoraTensorSample, ...],
        recipe: LoraTrainingRecipe,
        output_root: Path,
        checkpoint_policy: LoraCheckpointPolicy | None,
        budget: LoraTrainingBudget | None = None,
    ) -> TrainingBackendResult:
        started = time.monotonic()
        hyperparameters = recipe.hyperparameters
        runtime: LocalImageLoraTrainingRuntime | None = None
        versions: dict[str, str] | None = None
        completed_steps = 0
        final_loss: float | None = None
        unet: Any | None = None
        if checkpoint_policy is not None and hyperparameters.checkpointing_steps == 0:
            raise TrainingBackendFailure("IMAGE_TRAINING_CHECKPOINT_POLICY_INVALID")
        try:
            import bitsandbytes as bnb  # type: ignore[import-not-found]
            import torch  # type: ignore[import-not-found]
            import torch.nn.functional as functional  # type: ignore[import-not-found]
            from accelerate import Accelerator  # type: ignore[import-not-found]
            from diffusers import (
                DDPMScheduler,
                UNet2DConditionModel,
            )
            from peft import LoraConfig  # type: ignore[import-not-found]
        except ImportError as exc:
            raise TrainingBackendFailure("IMAGE_TRAINING_DEPENDENCY_MISSING") from exc
        except KeyboardInterrupt as exc:
            raise TrainingBackendFailure(
                "IMAGE_TRAINING_CANCELLED",
                cancelled=True,
            ) from exc
        try:
            if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) != (12, 0):
                raise TrainingBackendFailure("IMAGE_TRAINING_GPU_UNAVAILABLE")
            _require_deterministic_runtime()
            versions = _versions()
            expected = recipe.dependencies.model_dump(mode="json")
            if versions != expected:
                raise TrainingBackendFailure("IMAGE_TRAINING_RUNTIME_DRIFT")
            torch.manual_seed(recipe.seed)
            torch.cuda.manual_seed_all(recipe.seed)
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            torch.use_deterministic_algorithms(True)
            torch.cuda.reset_peak_memory_stats(0)

            if not samples:
                raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
            captions = tuple(sample.caption_en for sample in samples)
            prompts = _prompt_embeddings(
                model_directory=model_directory,
                captions=captions,
                torch=torch,
            )
            latent_values = _latents(
                vae_source=vae_source,
                samples=samples,
                seed=recipe.seed,
                torch=torch,
            )
            _require_training_budget(budget=budget, started=started, torch=torch)
            scheduler = DDPMScheduler.from_pretrained(
                model_directory,
                subfolder="scheduler",
                local_files_only=True,
            )
            unet = UNet2DConditionModel.from_pretrained(
                model_directory,
                subfolder="unet",
                variant="fp16",
                torch_dtype=torch.float16,
                local_files_only=True,
                use_safetensors=True,
            )
            unet.requires_grad_(False)
            unet.add_adapter(
                LoraConfig(
                    r=hyperparameters.rank,
                    lora_alpha=hyperparameters.alpha,
                    init_lora_weights="gaussian",
                    target_modules=list(TARGET_MODULES),
                )
            )
            if hyperparameters.gradient_checkpointing:
                unet.enable_gradient_checkpointing()
            trainable = tuple(
                parameter for parameter in unet.parameters() if parameter.requires_grad
            )
            if not trainable:
                raise TrainingBackendFailure("IMAGE_TRAINING_ADAPTER_INVALID")
            for parameter in trainable:
                parameter.data = parameter.data.to(torch.float32)
            optimizer = bnb.optim.AdamW8bit(
                trainable,
                lr=float(hyperparameters.learning_rate),
            )
            accelerator = Accelerator(
                gradient_accumulation_steps=hyperparameters.gradient_accumulation_steps,
                mixed_precision=hyperparameters.mixed_precision,
            )
            unet, optimizer = accelerator.prepare(unet, optimizer)
            if accelerator.num_processes != 1:
                raise TrainingBackendFailure("IMAGE_TRAINING_PROCESS_COUNT_INVALID")
            unet.train()
            # At most four immutable canvases; avoid allocation on every micro-step.
            time_ids_by_geometry = {
                geometry: torch.tensor([geometry], dtype=torch.float16, device=accelerator.device)
                for geometry in dict.fromkeys(sample.sdxl_time_ids for sample in samples)
            }
            restored = (
                checkpoint_policy.load(
                    model=accelerator.unwrap_model(unet), optimizer=optimizer, torch=torch
                )
                if checkpoint_policy is not None
                else None
            )
            if restored is None:
                micro_step = 0
            else:
                completed_steps = restored.completed_steps
                micro_step = restored.micro_steps
            current_epoch = -1
            order: tuple[int, ...] = ()
            while completed_steps < hyperparameters.max_train_steps:
                _require_training_budget(budget=budget, started=started, torch=torch)
                epoch, offset = divmod(micro_step, len(samples))
                if epoch != current_epoch:
                    order = _sample_order(
                        epoch=epoch,
                        count=len(samples),
                        seed=recipe.seed,
                    )
                    current_epoch = epoch
                index = order[offset]
                latent = latent_values[index].to(accelerator.device, dtype=torch.float16)
                prompt_embeds, pooled = prompts[index]
                prompt_embeds = prompt_embeds.to(accelerator.device, dtype=torch.float16)
                pooled = pooled.to(accelerator.device, dtype=torch.float16)
                noise = torch.randn_like(latent)
                timestep = torch.randint(
                    0,
                    scheduler.config.num_train_timesteps,
                    (latent.shape[0],),
                    device=accelerator.device,
                    dtype=torch.long,
                )
                noisy = scheduler.add_noise(latent, noise, timestep)
                if scheduler.config.prediction_type == "epsilon":
                    target = noise
                elif scheduler.config.prediction_type == "v_prediction":
                    target = scheduler.get_velocity(latent, noise, timestep)
                else:
                    raise TrainingBackendFailure(
                        "IMAGE_TRAINING_SCHEDULER_UNSUPPORTED",
                        completed_steps=completed_steps,
                    )
                with accelerator.accumulate(unet):
                    prediction = unet(
                        noisy,
                        timestep,
                        prompt_embeds,
                        added_cond_kwargs={
                            "text_embeds": pooled,
                            "time_ids": time_ids_by_geometry[samples[index].sdxl_time_ids],
                        },
                    ).sample
                    loss = functional.mse_loss(prediction.float(), target.float())
                    if not bool(torch.isfinite(loss).item()):
                        raise TrainingBackendFailure(
                            "IMAGE_TRAINING_LOSS_NONFINITE",
                            completed_steps=completed_steps,
                        )
                    accelerator.backward(loss)
                    if accelerator.sync_gradients:
                        gradient_norm = accelerator.clip_grad_norm_(trainable, 1.0)
                        if not bool(torch.isfinite(gradient_norm).all().item()):
                            raise TrainingBackendFailure(
                                "IMAGE_TRAINING_GRADIENT_NONFINITE",
                                completed_steps=completed_steps,
                            )
                    optimizer.step()
                    optimizer.zero_grad(set_to_none=True)
                if accelerator.sync_gradients:
                    completed_steps += 1
                    final_loss = float(loss.detach().item())
                micro_step += 1
                if (
                    accelerator.sync_gradients
                    and checkpoint_policy is not None
                    and completed_steps < hyperparameters.max_train_steps
                    and completed_steps % hyperparameters.checkpointing_steps == 0
                ):
                    checkpoint_policy.save(
                        model=accelerator.unwrap_model(unet),
                        optimizer=optimizer,
                        completed_steps=completed_steps,
                        micro_steps=micro_step,
                        torch=torch,
                    )
            _require_training_budget(budget=budget, started=started, torch=torch)
            accelerator.wait_for_everyone()
            if accelerator.is_main_process:
                unwrapped = accelerator.unwrap_model(unet)
                _save_final_adapter(
                    model=unwrapped,
                    hyperparameters=hyperparameters,
                    output_root=output_root,
                )
            accelerator.wait_for_everyone()
            _require_training_budget(budget=budget, started=started, torch=torch)
            runtime = _runtime_snapshot(versions=versions, torch=torch)
            assert final_loss is not None and math.isfinite(final_loss)
            return TrainingBackendResult(
                runtime=runtime,
                completed_steps=completed_steps,
                final_loss=final_loss,
            )
        except TrainingBackendFailure as exc:
            if runtime is None and versions is not None:
                try:
                    runtime = _runtime_snapshot(versions=versions, torch=torch)
                except Exception:
                    runtime = None
            raise TrainingBackendFailure(
                exc.code,
                runtime=exc.runtime or runtime,
                completed_steps=max(exc.completed_steps, completed_steps),
                final_loss=exc.final_loss if exc.final_loss is not None else final_loss,
                cancelled=exc.cancelled,
            ) from exc
        except KeyboardInterrupt as exc:
            raise TrainingBackendFailure(
                "IMAGE_TRAINING_CANCELLED",
                runtime=runtime,
                completed_steps=completed_steps,
                final_loss=final_loss,
                cancelled=True,
            ) from exc
        except Exception as exc:
            try:
                import torch

                if isinstance(exc, torch.cuda.OutOfMemoryError):
                    raise TrainingBackendFailure(
                        "IMAGE_TRAINING_CUDA_OOM",
                        runtime=runtime,
                        completed_steps=completed_steps,
                        final_loss=final_loss,
                    ) from exc
            except ImportError:
                pass
            raise TrainingBackendFailure(
                "IMAGE_TRAINING_EXEC_FAILED",
                runtime=runtime,
                completed_steps=completed_steps,
                final_loss=final_loss,
            ) from exc
        finally:
            if unet is not None:
                del unet
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
