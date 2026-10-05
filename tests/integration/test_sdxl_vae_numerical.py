"""Opt-in CPU photometric diagnostic; no corpus, generation, training or GPU.

Run with the explicit image-trainer interpreter and installed packages:
EOM_RUN_SDXL_VAE_NUMERICAL=1 EOM_SDXL_MODEL_STORE_ROOT=<protected-root>
EOM_SDXL_STACK_POINTER=<pinned-pointer-json> python -I <this-file> -v

Only the existing resolver may admit the model. Synthetic white/contour tensors
are not new exam illustrations or evidence of trained LoRA quality.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("EOM_RUN_SDXL_VAE_NUMERICAL") == "1",
    "explicit pinned-model CPU numerical opt-in required",
)
class SdxlVaePhotometricDiagnostic(unittest.TestCase):
    torch: ClassVar[Any]
    np: ClassVar[Any]
    vae: ClassVar[Any]
    processor: ClassVar[Any]
    manual: ClassVar[Any]
    preprocessed: ClassVar[Any]
    scaled_latent: ClassVar[Any]
    decoded: ClassVar[Any]
    manual_pixels: ClassVar[Any]
    postprocessed: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        import numpy as np
        import torch
        from diffusers import AutoencoderKL
        from diffusers.image_processor import VaeImageProcessor
        from eom_image_contracts import SdxlLineartStackPointer
        from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
        from PIL import Image

        cls.torch, cls.np = torch, np
        torch.set_num_threads(2)
        guard = patch.object(
            torch.cuda, "_lazy_init", side_effect=AssertionError("CPU diagnostic used CUDA")
        )
        guard.start()
        cls.addClassCleanup(guard.stop)
        pointer = SdxlLineartStackPointer.model_validate_json(os.environ["EOM_SDXL_STACK_POINTER"])
        stack = resolve_sdxl_stack(Path(os.environ["EOM_SDXL_MODEL_STORE_ROOT"]), pointer)
        cls.vae = (
            AutoencoderKL.from_pretrained(
                str(stack.component_roots["VAE"]),
                torch_dtype=torch.float32,
                local_files_only=True,
                use_safetensors=True,
            )
            .requires_grad_(False)
            .eval()
        )
        cls.processor = VaeImageProcessor(vae_scale_factor=8)
        white = np.full((128, 128, 3), 255, dtype=np.uint8)
        contour = white.copy()
        contour[32:96, 32:36] = 0
        contour[32:96, 92:96] = 0
        contour[32:36, 32:96] = 0
        contour[92:96, 32:96] = 0
        pixels = (white, contour)
        images = tuple(Image.fromarray(value) for value in pixels)
        cls.manual = (
            torch.stack([torch.from_numpy(value.copy()).permute(2, 0, 1) for value in pixels])
            .float()
            .div(127.5)
            .sub(1.0)
        )
        cls.preprocessed = torch.cat([cls.processor.preprocess(image) for image in images])
        with torch.inference_mode():
            posterior = cls.vae.encode(cls.manual).latent_dist
            # Deterministic mean diagnoses encode/decode, not training posterior sampling.
            encoded = posterior.mean
            scale = float(cls.vae.config.scaling_factor)
            cls.scaled_latent = encoded * scale
            cls.decoded = cls.vae.decode(cls.scaled_latent / scale, return_dict=False)[0]
            cls.manual_pixels = (cls.decoded / 2 + 0.5).clamp(0, 1)
            cls.postprocessed = cls.processor.postprocess(cls.decoded, output_type="np")
        print(
            "SDXL_VAE_CPU_DIAGNOSTIC="
            + json.dumps(
                {
                    "model_id": pointer.model_id,
                    "model_revision_id": pointer.model_revision_id,
                    "manifest_sha256": pointer.manifest_sha256,
                    "torch": torch.__version__,
                    "dtype": "float32",
                    "device": "cpu",
                    "inputs": "SYNTHETIC_WHITE_AND_RECTANGLE_128X128",
                    "white_decoded_mean": float(cls.manual_pixels[0].mean()),
                    "white_decoded_min": float(cls.manual_pixels[0].min()),
                    "generation_count": 0,
                    "training_steps": 0,
                    "gpu_calls": 0,
                    "limitations": "NOT_FP16_GPU_PARITY_OR_NATIVE_GEOMETRY_QUALITY",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )

    def test_training_rgb_normalization_matches_actual_diffusers_preprocessing(self) -> None:
        torch = self.torch
        self.assertEqual(tuple(self.manual.shape), (2, 3, 128, 128))
        self.assertTrue(torch.allclose(self.manual, self.preprocessed, atol=1e-6, rtol=0))
        self.assertEqual(float(self.manual.min()), -1.0)
        self.assertEqual(float(self.manual.max()), 1.0)

    def test_latent_scaling_and_decode_remain_finite(self) -> None:
        torch = self.torch
        self.assertGreater(float(self.vae.config.scaling_factor), 0)
        self.assertEqual(tuple(self.scaled_latent.shape), (2, 4, 16, 16))
        self.assertEqual(tuple(self.decoded.shape), (2, 3, 128, 128))
        self.assertTrue(bool(torch.isfinite(self.scaled_latent).all()))
        self.assertTrue(bool(torch.isfinite(self.decoded).all()))

    def test_final_pixel_transform_matches_actual_diffusers_postprocessing(self) -> None:
        expected = self.manual_pixels.permute(0, 2, 3, 1).numpy()
        self.assertTrue(self.np.allclose(expected, self.postprocessed, atol=1e-7, rtol=0))
        self.assertGreaterEqual(float(self.postprocessed.min()), 0)
        self.assertLessEqual(float(self.postprocessed.max()), 1)

    def test_synthetic_white_can_decode_as_white_not_midgray(self) -> None:
        # A decoder capability check only, not an exam-background quality threshold.
        self.assertGreater(float(self.manual_pixels[0].mean()), 0.9)

    def test_synthetic_contour_preserves_photometric_polarity(self) -> None:
        image = self.manual_pixels[1]
        paper = float(image[:, 4:24, 4:24].mean())
        stroke = float(image[:, 32:96, 32:36].mean())
        self.assertGreater(paper - stroke, 0.3)

    def test_vae_is_frozen_cpu_only(self) -> None:
        self.assertFalse(self.vae.training)
        self.assertTrue(all(not p.requires_grad for p in self.vae.parameters()))
        self.assertTrue(all(p.device.type == "cpu" for p in self.vae.parameters()))
        self.assertTrue(all(p.dtype == self.torch.float32 for p in self.vae.parameters()))


if __name__ == "__main__":
    unittest.main()
