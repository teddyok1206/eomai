"""Frozen TRAIN numerical probe, not image generation or a training recipe.

Default invocation is model-free. The owner pins/admit/stages three native PNGs
and this script; installed adapters own decoding, normalization and GPU lease.
Pixel bands are descriptive source statistics, never semantic masks or labels.
"""

from __future__ import annotations

import json
import math
import os
import time
import unittest
from importlib import metadata
from pathlib import Path
from typing import Any

BANDS = ("HAS_DARK_SOURCE_PIXEL", "NONWHITE_ONLY", "NEARWHITE_ONLY")
SAMPLES = (
    (
        "imgsourcecrop_007c95f669aa255b393c4b92e0e710b3",
        "09d4f2c63f949c686b5ad1a499a7d6fcd49248b2d2c5626e59635a51db49b955",
    ),
    (
        "imgsourcecrop_a1727135d4042a8fd67e86e05609ec9f",
        "cd650dc9b8b8e626c061223a206ff2ce590ae2280b893c0b2c088e85fd07e6f6",
    ),
    (
        "imgsourcecrop_4730ed28b9b4e0011d03d051e76c060f",
        "b25bca998edcdab2001037e6343683b6b693a25a6671e1d55919a561e93bd257",
    ),
)


def source_cell_bands(pixels: tuple[int, ...], width: int, height: int) -> tuple[int, ...]:
    """Single linear pass, one band/cell; dark takes precedence over nonwhite."""
    if width < 8 or height < 8 or width % 8 or height % 8 or len(pixels) != width * height:
        raise ValueError("SOURCE_BAND_GEOMETRY_INVALID")
    if any(type(value) is not int or not 0 <= value <= 255 for value in pixels):
        raise ValueError("SOURCE_BAND_LUMINANCE_INVALID")
    cells = [2] * (width // 8 * (height // 8))
    for offset, value in enumerate(pixels):
        cell = (offset // width // 8) * (width // 8) + offset % width // 8
        band = 0 if value < 96 else 1 if value < 245 else 2
        cells[cell] = min(cells[cell], band)
    return tuple(cells)


def regional_mse(
    cell_squared_error_sums: tuple[float, ...], bands: tuple[int, ...], channels: int
) -> dict[str, Any]:
    """Account by actual channel times cell count; empty bands are not fake zero."""
    if channels < 1 or not bands or len(bands) != len(cell_squared_error_sums):
        raise ValueError("SOURCE_BAND_ACCOUNTING_INVALID")
    counts, totals = [0] * 3, [0.0] * 3
    for error, band in zip(cell_squared_error_sums, bands, strict=True):
        if type(band) is not int or band not in (0, 1, 2) or not math.isfinite(error) or error < 0:
            raise ValueError("SOURCE_BAND_NONFINITE_OR_INVALID")
        counts[band] += channels
        totals[band] += error
    total_count = len(bands) * channels
    global_mse = math.fsum(cell_squared_error_sums) / total_count
    reconstructed = math.fsum(totals) / total_count
    if not math.isclose(global_mse, reconstructed, abs_tol=1e-10, rel_tol=1e-10):
        raise ValueError("SOURCE_BAND_RECONSTRUCTION_MISMATCH")
    return dict(
        global_mse=global_mse,
        reconstructed_global_mse=reconstructed,
        element_count=total_count,
        bands={
            name: dict(
                status="MEASURED" if counts[i] else "NOT_APPLICABLE",
                element_count=counts[i],
                mse=totals[i] / counts[i] if counts[i] else None,
            )
            for i, name in enumerate(BANDS)
        },
    )


class SourceBandAccounting(unittest.TestCase):
    def test_dark_pixel_precedence_and_cell_order(self) -> None:
        pixels = [255] * (16 * 16)
        pixels[0], pixels[7], pixels[8], pixels[8 * 16] = 100, 95, 244, 245
        self.assertEqual(source_cell_bands(tuple(pixels), 16, 16), (0, 1, 2, 2))

    def test_boundary_values(self) -> None:
        for pixel, expected in ((95, 0), (96, 1), (244, 1), (245, 2)):
            with self.subTest(pixel=pixel):
                self.assertEqual(source_cell_bands((pixel,) * 64, 8, 8), (expected,))

    def test_reconstruct_with_unequal_counts(self) -> None:
        result = regional_mse((4.0, 8.0, 12.0, 16.0), (0, 1, 2, 2), 4)
        self.assertEqual(result["global_mse"], 2.5)
        self.assertEqual(result["bands"][BANDS[2]]["mse"], 3.5)
        self.assertEqual(sum(row["element_count"] for row in result["bands"].values()), 16)

    def test_empty_band_is_not_applicable(self) -> None:
        row = regional_mse((0.0,), (0,), 4)["bands"][BANDS[2]]
        self.assertEqual(row, dict(status="NOT_APPLICABLE", element_count=0, mse=None))

    def test_bad_geometry_and_luminance(self) -> None:
        for pixels, width, height in (((255,) * 64, 7, 8), ((256,) * 64, 8, 8)):
            with self.assertRaises(ValueError):
                source_cell_bands(pixels, width, height)

    def test_invalid_measurements(self) -> None:
        for errors, bands, channels in (
            ((float("nan"),), (0,), 4),
            ((float("inf"),), (0,), 4),
            ((-1.0,), (0,), 4),
            ((1.0,), (3,), 4),
            ((1.0,), (0, 1), 4),
            ((1.0,), (0,), 0),
        ):
            with self.assertRaises(ValueError):
                regional_mse(errors, bands, channels)


@unittest.skipUnless(
    os.environ.get("EOM_RUN_SDXL_SOURCE_BAND_DENOISING") == "1",
    "explicit owner-admitted installed-GPU diagnostic opt-in required",
)
class InstalledSourceBandDenoising(unittest.TestCase):
    def load_admitted_inputs(self) -> tuple[Any, Any, list[Any], list[Any], Any, str]:
        """Historical1.2 fixture stays exact; successor overrides admission, not numerics."""
        import io

        from eom_image_contracts import content_json_bytes
        from eom_image_contracts.sdxl_native_canny_reference import sdxl_reference_adapter
        from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommandV3
        from eom_image_contracts.sdxl_photo_style_execution import parse_photo_style_command
        from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
        from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
        from eom_image_provider.sdxl_photo_style_sources import read_sdxl_photo_style_sources
        from eom_image_provider.staged_file_io import read_staged_member, verified_directory
        from eom_image_trainer.diffusers_backend import (
            LoraTensorSample,
        )
        from PIL import Image

        input_root = Path(os.environ["EOM_SOURCE_BAND_INPUT_ROOT"])
        prior_root = Path(os.environ["EOM_SOURCE_BAND_METADATA_ROOT"])
        with verified_directory(prior_root, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(
                root,
                "command.json",
                maximum_bytes=128 * 1024,
                expected_sha256=os.environ["EOM_SOURCE_BAND_COMMAND_SHA256"],
            )
            command = parse_photo_style_command(json.loads(raw))
            sources = read_sdxl_photo_style_sources(root, command)
            selected = sdxl_reference_adapter(sources.configuration_sources)
            material = load_sdxl_lora_material(root, selected.manifest, strength=selected.strength)
        self.assertEqual(material.strength, 1.0)
        with verified_directory(input_root, expected_owner_uid=0) as root:
            training_raw = read_staged_member(
                root,
                "training-command.json",
                maximum_bytes=2 * 1024**2,
                expected_owner_uid=0,
                expected_sha256="sha256:283200c091348bb8c0098aefca6f33e024cddcc3c78457969d0ce7809bd17d54",
            )
            training = LocalImageSdxlNativeLoraCommandV3.model_validate_json(training_raw)
            self.assertEqual(training_raw, content_json_bytes(training.model_dump(mode="json")))
            self.assertEqual(material.manifest.training_command_sha256, training.command_sha256)
            sample_map = {sample.sample_id: sample for sample in training.training_samples}
            self.assertEqual(len(sample_map), 100)
            tensors, masks = [], []
            for sample_id, sha in SAMPLES:
                sample = sample_map[sample_id]
                self.assertEqual(sample.source_image.sha256, "sha256:" + sha)
                name = sample_id + ".png"
                payload = read_staged_member(
                    root,
                    name,
                    maximum_bytes=8 * 1024**2,
                    expected_owner_uid=0,
                    expected_sha256=sample.source_image.sha256,
                )
                with Image.open(io.BytesIO(payload)) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.mode, "RGB")
                    self.assertEqual(image.size, sample.width_height)
                    masks.append(
                        source_cell_bands(tuple(image.convert("L").getdata()), *image.size)
                    )
                tensors.append(
                    LoraTensorSample(
                        caption_en=sample.training_caption_en,
                        image_path=input_root / name,
                        width_px=sample.width_height[0],
                        height_px=sample.width_height[1],
                    )
                )
        spatial = sources.configuration_sources.spatial_sources
        stack = resolve_sdxl_stack(
            Path(os.environ["EOM_SDXL_MODEL_STORE_ROOT"]), spatial.targets.lora.baseline.model
        )
        return material, training, tensors, masks, stack, command.command_sha256

    def test_frozen_paired_noise_prediction(self) -> None:
        started = time.monotonic()
        material, training, tensors, masks, stack, command_sha256 = self.load_admitted_inputs()
        import torch  # type: ignore[import-not-found]
        from diffusers import DDPMScheduler, UNet2DConditionModel  # type: ignore[import-not-found]
        from eom_image_provider.provider import acquire_gpu_lease
        from eom_image_provider.sdxl_lora_material import apply_sdxl_lora
        from eom_image_trainer.diffusers_backend import (
            VaeWeightLocation,
            _latents,
            _prompt_embeddings,
        )

        torch.set_num_threads(2)
        budget = 14 * 1024**3

        def guard() -> None:
            if time.monotonic() - started > 300 or torch.cuda.max_memory_allocated(0) > budget:
                raise RuntimeError("SOURCE_BAND_RESOURCE_BUDGET_EXCEEDED")

        rows = []
        with acquire_gpu_lease(Path("/var/lib/eom-image/gpu0.lock")), torch.no_grad():
            self.assertEqual(os.environ.get("CUBLAS_WORKSPACE_CONFIG"), ":4096:8")
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            torch.use_deterministic_algorithms(True)
            torch.cuda.reset_peak_memory_stats()
            embeddings = _prompt_embeddings(
                model_directory=stack.component_roots["BASE"],
                captions=tuple(sample.caption_en for sample in tensors),
                torch=torch,
            )
            guard()
            latents = _latents(
                vae_source=VaeWeightLocation(stack.component_roots["VAE"], None, None),
                samples=tuple(tensors),
                seed=104729,
                torch=torch,
            )
            guard()
            scheduler = DDPMScheduler.from_pretrained(
                stack.component_roots["BASE"], subfolder="scheduler", local_files_only=True
            )
            unet = (
                UNet2DConditionModel.from_pretrained(
                    stack.component_roots["BASE"],
                    subfolder="unet",
                    variant="fp16",
                    torch_dtype=torch.float16,
                    local_files_only=True,
                    use_safetensors=True,
                )
                .requires_grad_(False)
                .eval()
                .to("cuda")
            )
            apply_sdxl_lora(unet, material)
            unet.requires_grad_(False).eval()
            generator = torch.Generator(device="cuda").manual_seed(104729)
            for i, ((sample_id, _), latent_cpu, (prompt_cpu, pooled_cpu)) in enumerate(
                zip(SAMPLES, latents, embeddings, strict=True)
            ):
                latent = latent_cpu.to("cuda", dtype=torch.float16)
                self.assertEqual(len(masks[i]), latent.shape[-2] * latent.shape[-1])
                noise = torch.randn(
                    latent.shape, generator=generator, device="cuda", dtype=latent.dtype
                )
                for step in (250, 750):
                    timestep = torch.tensor([step], device="cuda", dtype=torch.long)
                    noisy = scheduler.add_noise(latent, noise, timestep)
                    target = (
                        noise
                        if scheduler.config.prediction_type == "epsilon"
                        else scheduler.get_velocity(latent, noise, timestep)
                    )
                    if scheduler.config.prediction_type not in ("epsilon", "v_prediction"):
                        raise ValueError("SOURCE_BAND_PREDICTION_TYPE_UNSUPPORTED")
                    for arm in ("BASE", "LORA"):
                        guard()
                        unet.disable_adapters() if arm == "BASE" else unet.enable_adapters()
                        predicted = unet(
                            noisy,
                            timestep,
                            prompt_cpu.to("cuda", dtype=torch.float16),
                            added_cond_kwargs={
                                "text_embeds": pooled_cpu.to("cuda", dtype=torch.float16),
                                "time_ids": torch.tensor(
                                    [tensors[i].sdxl_time_ids], device="cuda", dtype=torch.float16
                                ),
                            },
                        ).sample
                        squared = (predicted.float() - target.float()).square()
                        self.assertTrue(bool(torch.isfinite(squared).all()))
                        cell_errors = tuple(squared.sum(dim=1).flatten().cpu().tolist())
                        measured = regional_mse(cell_errors, masks[i], squared.shape[1])
                        self.assertTrue(
                            math.isclose(
                                measured["global_mse"], float(squared.mean()), rel_tol=1e-6
                            )
                        )
                        rows.append(dict(sample_id=sample_id, timestep=step, arm=arm, **measured))
                        del predicted, squared
                        guard()
            torch.cuda.synchronize()
            peak = torch.cuda.max_memory_allocated(0)
            guard()
        self.assertEqual(len(rows), 12)
        evidence = dict(
            status="INSTALLED_SOURCE_BAND_DENOISING_PASS_NOT_QUALITY_ACCEPTANCE",
            comparison_command_sha256=command_sha256,
            training_command_sha256=training.command_sha256,
            adapter_manifest_sha256=material.manifest.manifest_sha256,
            strength=material.strength,
            seed=104729,
            timesteps=[250, 750],
            rows=rows,
            elapsed_seconds=time.monotonic() - started,
            peak_gpu_memory_bytes=peak,
            full_unet_forward_calls=12,
            model_loads=dict(text_encoders=2, vae=1, unet=1, adapter=1),
            generation_calls=0,
            training_updates=0,
            optimizer_loads=0,
            holdout_reads=0,
            subset_posterior_is_original_training_replay=False,
            numerical_versions={
                name: metadata.version(name)
                for name in ("torch", "diffusers", "transformers", "peft", "Pillow")
            },
            quality_acceptance="NOT_EVALUATED",
        )
        print("SDXL_SOURCE_BAND_DENOISING=" + json.dumps(evidence, sort_keys=True), flush=True)


if __name__ == "__main__":
    unittest.main()
