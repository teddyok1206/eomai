"""Opt-in native GPU photometric check, not an authoring/training worker protocol.

The developer owner admits exactly two canonical TRAIN targets before staging.
This test uses the installed encoder and one existing physical GPU lease. No UNet,
LoRA, optimizer, image generation, reserved data, network, database or NAS access.
Run only with EOM_RUN_SDXL_VAE_NATIVE_PRECISION=1 and the pinned model/input roots.
"""

from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar

CANVASES = ((1024, 1024), (768, 1024), (1024, 768))
REAL_INPUTS = (
    (
        "fan",
        (768, 1024),
        "eac5b9a59b1c80484e2583f592b6f4e66b10c599b6b768c627d971e6718a7bbe",
    ),
    (
        "beaker",
        (1024, 1024),
        "b40af4ba97bfb67f83ac4d7034b80c509af9fb1c71e99917b022e3d1ba339d30",
    ),
)
SEED = 20261005
MAX_DURATION_SECONDS = 180
MAX_GPU_BYTES = 14 * 1024**3


@unittest.skipUnless(
    os.environ.get("EOM_RUN_SDXL_VAE_NATIVE_PRECISION") == "1",
    "explicit pinned-model native GPU precision opt-in required",
)
class NativeVaePrecisionDiagnostic(unittest.TestCase):
    rows: ClassVar[list[dict[str, Any]]]
    latents_match: ClassVar[bool]
    input_hashes_unchanged: ClassVar[bool]
    duration_seconds: ClassVar[float]
    peak_gpu_bytes: ClassVar[int]

    @classmethod
    def setUpClass(cls) -> None:
        import numpy as np
        import torch  # type: ignore[import-not-found]
        from diffusers import AutoencoderKL  # type: ignore[import-not-found]
        from diffusers.image_processor import VaeImageProcessor  # type: ignore[import-not-found]
        from eom_image_contracts import SdxlLineartStackPointer
        from eom_image_provider.provider import acquire_gpu_lease
        from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
        from eom_image_provider.staged_file_io import read_staged_member
        from eom_image_trainer import diffusers_backend as actual  # type: ignore[import-not-found]
        from PIL import Image

        root = Path(os.environ["EOM_SDXL_NATIVE_VAE_INPUT_ROOT"])
        pointer = SdxlLineartStackPointer.model_validate_json(os.environ["EOM_SDXL_STACK_POINTER"])
        stack = resolve_sdxl_stack(Path(os.environ["EOM_SDXL_MODEL_STORE_ROOT"]), pointer)
        processor = VaeImageProcessor(vae_scale_factor=8)
        cls.rows = []
        # One test-local materialization boundary; only six synthetic fixtures are written.
        with tempfile.TemporaryDirectory(prefix="native-vae-", dir=root) as directory:
            cases: list[tuple[str, Path, Any]] = []
            for width, height in CANVASES:
                white: np.ndarray[Any, np.dtype[np.uint8]] = np.full(
                    (height, width, 3), 255, dtype=np.uint8
                )
                contour = white.copy()
                x0, x1, y0, y1 = width // 4, 3 * width // 4, height // 4, 3 * height // 4
                contour[y0:y1, x0 : x0 + 8] = 0
                contour[y0:y1, x1 - 8 : x1] = 0
                contour[y0 : y0 + 8, x0:x1] = 0
                contour[y1 - 8 : y1, x0:x1] = 0
                for kind, pixels in (("white", white), ("contour", contour)):
                    name = f"{kind}-{width}x{height}"
                    path = Path(directory) / (name + ".png")
                    Image.fromarray(pixels).save(path, format="PNG")
                    path.chmod(0o600)
                    cases.append((name, path, pixels))
            for name, size, sha in REAL_INPUTS:
                raw = read_staged_member(
                    root,
                    name + ".png",
                    maximum_bytes=2 * 1024**2,
                    expected_sha256="sha256:" + sha,
                )
                with Image.open(io.BytesIO(raw)) as image:
                    image.load()
                    if image.format != "PNG" or image.mode != "RGB" or image.size != size:
                        raise ValueError("NATIVE_VAE_DIAGNOSTIC_INPUT_INVALID")
                    pixels = np.asarray(image).copy()
                cases.append((name, root / (name + ".png"), pixels))
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for _, path, _ in cases}
            # Read-only admission precedes lease acquisition/model tensor loads.
            with acquire_gpu_lease(Path("/var/lib/eom-image/gpu0.lock")):
                started = time.monotonic()
                torch.set_num_threads(2)
                torch.cuda.reset_peak_memory_stats(0)
                torch.backends.cuda.matmul.allow_tf32 = False
                torch.backends.cudnn.allow_tf32 = False
                torch.backends.cudnn.benchmark = False
                torch.use_deterministic_algorithms(True)
                means: dict[str, Any] = {}
                decoded: dict[str, Any] = {}
                normalization: dict[str, float] = {}
                manual_sampled = []
                for dtype in (torch.float32, torch.float16):
                    vae = (
                        AutoencoderKL.from_pretrained(
                            str(stack.component_roots["VAE"]),
                            torch_dtype=dtype,
                            local_files_only=True,
                            use_safetensors=True,
                        )
                        .requires_grad_(False)
                        .eval()
                        .to("cuda")
                    )
                    generator = torch.Generator(device="cuda").manual_seed(SEED)
                    try:
                        with torch.no_grad():
                            for name, _, pixels in cases:
                                if time.monotonic() - started > MAX_DURATION_SECONDS:
                                    raise RuntimeError("NATIVE_VAE_DIAGNOSTIC_DURATION_EXCEEDED")
                                height, width = pixels.shape[:2]
                                tensor = torch.frombuffer(
                                    bytearray(pixels.tobytes()), dtype=torch.uint8
                                ).reshape(height, width, 3)
                                tensor = (
                                    tensor.permute(2, 0, 1).unsqueeze(0).to("cuda", dtype=dtype)
                                )
                                tensor = tensor.div(127.5).sub(1.0)
                                expected = processor.preprocess(Image.fromarray(pixels))
                                error = float((tensor.float().cpu() - expected).abs().max())
                                posterior = vae.encode(tensor).latent_dist
                                mean = posterior.mean
                                if not bool(torch.isfinite(mean).all()):
                                    raise RuntimeError("NATIVE_VAE_DIAGNOSTIC_NONFINITE")
                                if dtype == torch.float16:
                                    normalization[name] = error
                                    manual_sampled.append(
                                        posterior.sample(generator=generator)
                                        .mul(vae.config.scaling_factor)
                                        .to("cpu")
                                    )
                                reconstruction = vae.decode(mean, return_dict=False)[0]
                                if torch.cuda.max_memory_allocated(0) > MAX_GPU_BYTES:
                                    raise RuntimeError("NATIVE_VAE_DIAGNOSTIC_MEMORY_EXCEEDED")
                                if not bool(torch.isfinite(reconstruction).all()):
                                    raise RuntimeError("NATIVE_VAE_DIAGNOSTIC_NONFINITE")
                                output = (reconstruction.float() / 2 + 0.5).clamp(0, 1).cpu()
                                if dtype == torch.float32:
                                    means[name] = mean.float().cpu()
                                    decoded[name] = output
                                else:
                                    reference = means[name]
                                    latent_error = float(
                                        (mean.float().cpu() - reference).square().mean().sqrt()
                                        / reference.square().mean().sqrt().clamp_min(1e-6)
                                    )
                                    mae = float((output - decoded[name]).abs().mean())
                                    paper = float(output[:, :, :24, :24].mean())
                                    polarity: float | None = None
                                    if name.startswith("contour-"):
                                        x, y = width // 4, height // 4
                                        stroke = float(
                                            output[:, :, y : 3 * height // 4, x : x + 8].mean()
                                        )
                                        polarity = paper - stroke
                                    cls.rows.append(
                                        {
                                            "case": name,
                                            "width": width,
                                            "height": height,
                                            "latent_shape": list(mean.shape),
                                            "normalization_max_error": normalization[name],
                                            "latent_mean_nrmse": latent_error,
                                            "decoded_mae": mae,
                                            "decoded_paper_mean": paper,
                                            "contour_polarity": polarity,
                                        }
                                    )
                                del posterior, mean, reconstruction, tensor, output
                    finally:
                        vae.to("cpu")
                        del vae
                        gc.collect()
                        torch.cuda.empty_cache()
                # Exercise the actual installed training encoder, not a rewritten replacement.
                if time.monotonic() - started > MAX_DURATION_SECONDS:
                    raise RuntimeError("NATIVE_VAE_DIAGNOSTIC_DURATION_EXCEEDED")
                samples = tuple(
                    actual.LoraTensorSample(
                        "Diagnostic input, not an authoring prompt",
                        path,
                        pixels.shape[1],
                        pixels.shape[0],
                    )
                    for _, path, pixels in cases
                )
                result = actual._latents(
                    vae_source=actual.VaeWeightLocation(stack.component_roots["VAE"], None, None),
                    samples=samples,
                    seed=SEED,
                    torch=torch,
                )
                cls.latents_match = len(result) == len(manual_sampled) and all(
                    torch.equal(value, expected)
                    for value, expected in zip(result, manual_sampled, strict=True)
                )
                cls.duration_seconds = time.monotonic() - started
                cls.peak_gpu_bytes = int(torch.cuda.max_memory_allocated(0))
            after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for _, path, _ in cases}
            cls.input_hashes_unchanged = before == after
        print(
            "SDXL_VAE_NATIVE_PRECISION="
            + json.dumps(
                {
                    "model_id": pointer.model_id,
                    "model_revision_id": pointer.model_revision_id,
                    "manifest_sha256": pointer.manifest_sha256,
                    "cases": cls.rows,
                    "actual_installed_fp16_latents_bitwise_match": cls.latents_match,
                    "input_hashes_unchanged": cls.input_hashes_unchanged,
                    "duration_seconds": cls.duration_seconds,
                    "peak_gpu_bytes": cls.peak_gpu_bytes,
                    "vae_loads": 3,
                    "generations": 0,
                    "training_updates": 0,
                    "limitations": "TRAIN_PHOTOMETRIC_PARITY_NOT_UNET_OR_LORA_QUALITY",
                },
                sort_keys=True,
            ),
            flush=True,
        )

    def test_exact_native_case_coverage(self) -> None:
        self.assertEqual(len(self.rows), 8)
        self.assertEqual({(r["width"], r["height"]) for r in self.rows}, set(CANVASES))
        for row in self.rows:
            self.assertEqual(row["latent_shape"], [1, 4, row["height"] // 8, row["width"] // 8])

    def test_normalization_matches_diffusers_with_fp16_roundoff(self) -> None:
        for row in self.rows:
            self.assertLessEqual(row["normalization_max_error"], 0.001, row["case"])

    def test_fp16_and_fp32_posterior_means_are_close(self) -> None:
        for row in self.rows:
            self.assertLessEqual(row["latent_mean_nrmse"], 0.02, row["case"])

    def test_fp16_and_fp32_roundtrip_pixels_are_close(self) -> None:
        for row in self.rows:
            self.assertLessEqual(row["decoded_mae"], 0.01, row["case"])

    def test_white_paper_does_not_collapse_to_midgray(self) -> None:
        for row in self.rows:
            self.assertGreater(row["decoded_paper_mean"], 0.9, row["case"])

    def test_black_contours_preserve_polarity(self) -> None:
        for row in self.rows:
            if row["contour_polarity"] is not None:
                self.assertGreater(row["contour_polarity"], 0.3, row["case"])

    def test_actual_training_encoder_matches_and_does_not_mutate_inputs(self) -> None:
        self.assertTrue(self.latents_match)
        self.assertTrue(self.input_hashes_unchanged)

    def test_frozen_numerical_budget(self) -> None:
        self.assertLessEqual(self.duration_seconds, MAX_DURATION_SECONDS)
        self.assertLessEqual(self.peak_gpu_bytes, MAX_GPU_BYTES)


if __name__ == "__main__":
    unittest.main()
