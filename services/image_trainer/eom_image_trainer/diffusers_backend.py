"""Pinned SSD-1B/SDXL UNet LoRA training backend for the isolated trainer."""

from __future__ import annotations

import gc
import math
import os
import platform
import random
from importlib import metadata
from pathlib import Path
from typing import Any

from eom_image_contracts import (
    LocalImageLoraTrainingCommand,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainingDatasetManifest,
)

from eom_image_trainer.checkpoints import load_latest_checkpoint, save_checkpoint
from eom_image_trainer.runner import (
    TrainingBackendFailure,
    TrainingBackendResult,
)

TARGET_MODULES = ("to_k", "to_out.0", "to_q", "to_v")


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


def _canonical_config(command: LocalImageLoraTrainingCommand) -> bytes:
    import json

    plan = command.training_plan
    value = {
        "base_model_name_or_path": "PINNED_LOCAL_MODEL_REVISION",
        "bias": "none",
        "inference_mode": True,
        "lora_alpha": plan.hyperparameters.alpha,
        "peft_type": "LORA",
        "r": plan.hyperparameters.rank,
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
    command: LocalImageLoraTrainingCommand,
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
        weights = temporary / "adapter_model.safetensors"
        save_file(adapter_state, weights)
        weights.chmod(0o600)
        _write_config(temporary / "adapter_config.json", _canonical_config(command))
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
    model_directory: Path,
    dataset: LocalImageTrainingDatasetManifest,
    dataset_root: Path,
    seed: int,
    torch: Any,
) -> tuple[Any, ...]:
    from diffusers import AutoencoderKL  # type: ignore[import-not-found]
    from PIL import Image

    vae = AutoencoderKL.from_pretrained(
        model_directory,
        subfolder="vae",
        variant="fp16",
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
            for sample in dataset.samples:
                path = dataset_root / sample.crop_member.member_path
                with Image.open(path) as source:
                    source.load()
                    if source.format != "PNG" or source.size != (768, 512):
                        raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
                    payload = bytearray(source.convert("RGB").tobytes())
                image = torch.frombuffer(payload, dtype=torch.uint8).reshape(512, 768, 3)
                image = image.permute(2, 0, 1).unsqueeze(0).to("cuda", dtype=torch.float16)
                image = image.div(127.5).sub(1.0)
                latent = vae.encode(image).latent_dist.sample(generator=generator)
                latent = latent.mul(vae.config.scaling_factor).to("cpu")
                values.append(latent)
    finally:
        vae.to("cpu")
        del vae
        gc.collect()
        torch.cuda.empty_cache()
    return tuple(values)


class Ssd1bLoraBackend:
    """Train only UNet LoRA parameters with frozen precomputed conditioning."""

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
        runtime: LocalImageLoraTrainingRuntime | None = None
        versions: dict[str, str] | None = None
        completed_steps = 0
        final_loss: float | None = None
        unet: Any | None = None
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
            versions = _versions()
            expected = plan.dependencies.model_dump(mode="json")
            if versions != expected:
                raise TrainingBackendFailure("IMAGE_TRAINING_RUNTIME_DRIFT")
            torch.manual_seed(plan.seed)
            torch.cuda.manual_seed_all(plan.seed)
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            torch.use_deterministic_algorithms(True)
            torch.cuda.reset_peak_memory_stats(0)

            captions = tuple(sample.caption_en for sample in dataset.samples)
            prompts = _prompt_embeddings(
                model_directory=model_directory,
                captions=captions,
                torch=torch,
            )
            latent_values = _latents(
                model_directory=model_directory,
                dataset=dataset,
                dataset_root=dataset_root,
                seed=plan.seed,
                torch=torch,
            )
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
                    r=plan.hyperparameters.rank,
                    lora_alpha=plan.hyperparameters.alpha,
                    init_lora_weights="gaussian",
                    target_modules=list(TARGET_MODULES),
                )
            )
            if plan.hyperparameters.gradient_checkpointing:
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
                lr=float(plan.hyperparameters.learning_rate),
            )
            accelerator = Accelerator(
                gradient_accumulation_steps=(plan.hyperparameters.gradient_accumulation_steps),
                mixed_precision=plan.hyperparameters.mixed_precision,
            )
            unet, optimizer = accelerator.prepare(unet, optimizer)
            if accelerator.num_processes != 1:
                raise TrainingBackendFailure("IMAGE_TRAINING_PROCESS_COUNT_INVALID")
            unet.train()
            time_ids = torch.tensor(
                [[512, 768, 0, 0, 512, 768]],
                dtype=torch.float16,
                device=accelerator.device,
            )
            restored = load_latest_checkpoint(
                root=checkpoint_root,
                command=command,
                model=accelerator.unwrap_model(unet),
                optimizer=optimizer,
                torch=torch,
            )
            if restored is None:
                micro_step = 0
            else:
                completed_steps = restored.completed_steps
                micro_step = restored.micro_steps
            current_epoch = -1
            order: tuple[int, ...] = ()
            while completed_steps < plan.hyperparameters.max_train_steps:
                epoch, offset = divmod(micro_step, len(dataset.samples))
                if epoch != current_epoch:
                    order = _sample_order(
                        epoch=epoch,
                        count=len(dataset.samples),
                        seed=plan.seed,
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
                        added_cond_kwargs={"text_embeds": pooled, "time_ids": time_ids},
                    ).sample
                    loss = functional.mse_loss(prediction.float(), target.float())
                    if not bool(torch.isfinite(loss).item()):
                        raise TrainingBackendFailure(
                            "IMAGE_TRAINING_LOSS_NONFINITE",
                            completed_steps=completed_steps,
                        )
                    accelerator.backward(loss)
                    if accelerator.sync_gradients:
                        accelerator.clip_grad_norm_(trainable, 1.0)
                    optimizer.step()
                    optimizer.zero_grad(set_to_none=True)
                if accelerator.sync_gradients:
                    completed_steps += 1
                    final_loss = float(loss.detach().item())
                micro_step += 1
                if (
                    accelerator.sync_gradients
                    and completed_steps < plan.hyperparameters.max_train_steps
                    and completed_steps % plan.hyperparameters.checkpointing_steps == 0
                ):
                    save_checkpoint(
                        root=checkpoint_root,
                        command=command,
                        model=accelerator.unwrap_model(unet),
                        optimizer=optimizer,
                        completed_steps=completed_steps,
                        micro_steps=micro_step,
                        torch=torch,
                    )
            accelerator.wait_for_everyone()
            if accelerator.is_main_process:
                unwrapped = accelerator.unwrap_model(unet)
                _save_final_adapter(
                    model=unwrapped,
                    command=command,
                    output_root=output_root,
                )
            accelerator.wait_for_everyone()
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
