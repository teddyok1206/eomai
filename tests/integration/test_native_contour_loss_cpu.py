"""Opt-in real CPU tensor arithmetic/gradients; zero models, CUDA or institution data."""

from __future__ import annotations

import os
import unittest
from typing import Any, ClassVar
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("EOM_RUN_NATIVE_CONTOUR_LOSS_CPU") == "1",
    "explicit installed-torch CPU numerical opt-in required",
)
class NativeContourLossCpu(unittest.TestCase):
    torch: ClassVar[Any]
    policy: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        import torch  # type: ignore[import-not-found]
        from eom_image_contracts.sdxl_native_lora import SdxlNativeContourLossPolicy

        if torch.cuda.is_initialized():
            raise AssertionError("CONTOUR_LOSS_CPU_CUDA_ALREADY_INITIALIZED")
        cls.torch = torch
        torch.set_num_threads(2)
        cls.policy = SdxlNativeContourLossPolicy(
            policy_version="SOURCE_DARK_CELL_WEIGHT_2_1/1.0",
            source_cell_size_px=8,
            dark_luminance_threshold=96,
            dark_cell_weight=2,
            other_cell_weight=1,
            normalization="BROADCAST_WEIGHT_SUM",
        )

    def setUp(self) -> None:
        self.guard = patch.object(
            self.torch.cuda, "_lazy_init", side_effect=AssertionError("CUDA_FORBIDDEN")
        )
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_known_weighted_mse_and_gradient(self) -> None:
        from eom_image_trainer.native_contour_loss import native_contour_weighted_mse

        torch = self.torch
        prediction = torch.tensor([[[[1.0, 3.0]]] * 4], requires_grad=True)
        weights = torch.tensor([[[[2.0, 1.0]]]])
        loss = native_contour_weighted_mse(
            prediction=prediction, target=torch.zeros_like(prediction), weights=weights, torch=torch
        )
        self.assertAlmostEqual(float(loss.detach()), 11 / 3, places=6)
        loss.backward()
        expected = torch.tensor([[[[1 / 3, 0.5]]] * 4])
        torch.testing.assert_close(prediction.grad, expected)
        self.assertTrue(bool(torch.isfinite(prediction.grad).all()))

    def test_uniform_weights_match_original_mse_and_gradient(self) -> None:
        from eom_image_trainer.native_contour_loss import native_contour_weighted_mse

        torch = self.torch
        generator = torch.Generator(device="cpu").manual_seed(104729)
        target = torch.randn((1, 4, 12, 16), generator=generator)
        original = torch.randn(target.shape, generator=generator, requires_grad=True)
        weighted = original.detach().clone().requires_grad_(True)
        expected = torch.nn.functional.mse_loss(original, target)
        actual = native_contour_weighted_mse(
            prediction=weighted, target=target, weights=torch.ones((1, 1, 12, 16)), torch=torch
        )
        torch.testing.assert_close(actual, expected)
        actual.backward()
        expected.backward()
        torch.testing.assert_close(weighted.grad, original.grad)

    def test_float32_reduction_avoids_half_squared_overflow(self) -> None:
        from eom_image_trainer.native_contour_loss import native_contour_weighted_mse

        torch = self.torch
        prediction = torch.full((1, 4, 2, 3), 1000, dtype=torch.float16, requires_grad=True)
        loss = native_contour_weighted_mse(
            prediction=prediction,
            target=torch.zeros_like(prediction),
            weights=torch.ones((1, 1, 2, 3)),
            torch=torch,
        )
        self.assertEqual(loss.dtype, torch.float32)
        self.assertEqual(float(loss.detach()), 1_000_000)
        loss.backward()
        self.assertTrue(bool(torch.isfinite(prediction.grad).all()))

    def test_weighted_half_gradients_match_float32_reference(self) -> None:
        from eom_image_trainer.native_contour_loss import native_contour_weighted_mse

        torch = self.torch
        half = torch.tensor([[[[1.0, 3.0]]] * 4], dtype=torch.float16, requires_grad=True)
        full = half.detach().float().requires_grad_(True)
        weights = torch.tensor([[[[2.0, 1.0]]]])
        for tensor in (half, full):
            native_contour_weighted_mse(
                prediction=tensor, target=torch.zeros_like(tensor), weights=weights, torch=torch
            ).backward()
        torch.testing.assert_close(half.grad.float(), full.grad, atol=1e-3, rtol=1e-3)

    def test_pixel_threshold_cell_order_and_dark_precedence(self) -> None:
        from eom_image_trainer.native_contour_loss import source_cell_weights

        pixels = bytearray([245] * (16 * 16))
        pixels[0], pixels[7], pixels[8], pixels[8 * 16] = 96, 95, 96, 244
        before = bytes(pixels)
        result = source_cell_weights(
            luminance=before, width=16, height=16, policy=self.policy, torch=self.torch
        )
        self.assertEqual(result.tolist(), [[[[2.0, 1.0], [1.0, 1.0]]]])
        self.assertEqual(bytes(pixels), before)
        self.assertEqual(result.dtype, self.torch.float32)
        self.assertFalse(result.requires_grad)

    def test_absent_dark_pixels_keep_gray_white_and_all_cells(self) -> None:
        from eom_image_trainer.native_contour_loss import source_cell_weights

        for value in (96, 120, 244, 245, 255):
            with self.subTest(luminance=value):
                result = source_cell_weights(
                    luminance=bytes([value] * 128),
                    width=16,
                    height=8,
                    policy=self.policy,
                    torch=self.torch,
                )
                self.assertEqual(result.tolist(), [[[[1.0, 1.0]]]])

    def test_shape_pixel_length_and_empty_input_are_rejected(self) -> None:
        from eom_image_trainer.native_contour_loss import source_cell_weights
        from eom_image_trainer.runner import TrainingBackendFailure

        for raw, width, height in ((b"", 0, 0), (b"a" * 64, 7, 8), (b"a" * 63, 8, 8)):
            with self.assertRaises(TrainingBackendFailure):
                source_cell_weights(
                    luminance=raw, width=width, height=height, policy=self.policy, torch=self.torch
                )

    def test_bad_weight_values_dtype_or_grad_are_rejected(self) -> None:
        from eom_image_trainer.native_contour_loss import native_contour_weighted_mse
        from eom_image_trainer.runner import TrainingBackendFailure

        torch = self.torch
        prediction = torch.ones((1, 4, 1, 2))
        cases = [
            torch.tensor([[[[value, 1.0]]]]) for value in (0, -1, 3, float("nan"), float("inf"))
        ]
        cases += [
            torch.ones((1, 1, 1, 2), dtype=torch.float16),
            torch.ones((1, 1, 1, 2), requires_grad=True),
        ]
        for weights in cases:
            with self.assertRaises(TrainingBackendFailure):
                native_contour_weighted_mse(
                    prediction=prediction, target=prediction, weights=weights, torch=torch
                )

    def test_wrong_channel_batch_or_broadcast_shape_rejected(self) -> None:
        from eom_image_trainer.native_contour_loss import native_contour_weighted_mse
        from eom_image_trainer.runner import TrainingBackendFailure

        torch = self.torch
        for shape, weight_shape in (
            ((2, 4, 2, 3), (1, 1, 2, 3)),
            ((1, 3, 2, 3), (1, 1, 2, 3)),
            ((1, 4, 2, 3), (1, 4, 2, 3)),
        ):
            tensor = torch.ones(shape)
            with self.assertRaises(TrainingBackendFailure):
                native_contour_weighted_mse(
                    prediction=tensor, target=tensor, weights=torch.ones(weight_shape), torch=torch
                )
        with self.assertRaises(TrainingBackendFailure):
            native_contour_weighted_mse(
                prediction=torch.ones((1, 4, 2, 3)),
                target=torch.ones((1, 4, 1, 3)),
                weights=torch.ones((1, 1, 2, 3)),
                torch=torch,
            )

    def test_cpu_only_and_no_torch_model_weights(self) -> None:
        self.assertFalse(self.torch.cuda.is_initialized())


if __name__ == "__main__":
    unittest.main()
