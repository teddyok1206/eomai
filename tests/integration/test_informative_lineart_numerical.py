"""Opt-in real CPU tensors and public acquisition; no GPU, corpus images or pytest dependency.

Run with the explicit eom-image-trainer interpreter and an empty owner-only staging directory:
EOM_RUN_INFORMATIVE_LINEART_NUMERICAL=1 EOM_INFORMATIVE_LINEART_ACQUISITION_ROOT=<path>
python -m unittest tests.integration.test_informative_lineart_numerical -v
"""

from __future__ import annotations

import hashlib
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("EOM_RUN_INFORMATIVE_LINEART_NUMERICAL") == "1",
    "explicit informative lineart acquisition/numerical opt-in required",
)
class InformativeLineartNumericalAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import torch
        from eom_image_contracts import InformativeLineartUpstream
        from eom_image_provider.informative_lineart_acquisition import (
            acquire_informative_lineart_model,
        )
        from eom_image_provider.informative_lineart_download import fetch_informative_lineart_member
        from eom_image_provider.informative_lineart_model import (
            informative_lineart_generator,
            load_informative_lineart_safetensors,
        )
        from eom_image_provider.staged_file_io import read_staged_member, verified_directory

        cls.torch = torch
        torch.set_num_threads(2)
        cls.cuda_guard = patch.object(
            torch.cuda, "_lazy_init", side_effect=AssertionError("CPU gate used CUDA")
        )
        cls.cuda_guard.start()
        cls.addClassCleanup(cls.cuda_guard.stop)
        cls.upstream = InformativeLineartUpstream.pinned()
        cls.original_weight_bytes = b""
        cls.staging = Path(os.environ["EOM_INFORMATIVE_LINEART_ACQUISITION_ROOT"])

        def fetch(name, maximum):
            payload = fetch_informative_lineart_member(name, maximum)
            if name == cls.upstream.weight_filename:
                cls.original_weight_bytes = payload
            return payload

        original_loader = torch.load
        calls = []

        def restricted_load(*args, **kwargs):
            if kwargs != {"map_location": "cpu", "weights_only": True}:
                raise AssertionError("loader weakened CPU weights-only boundary")
            calls.append(kwargs)
            return original_loader(*args, **kwargs)

        with patch.object(torch, "load", side_effect=restricted_load):
            cls.acquired = acquire_informative_lineart_model(
                cls.staging, created_by="eom.internal.cpu-numerical-acceptance", fetch=fetch
            )
        if len(calls) != 1:
            raise AssertionError("conversion did not use exactly one restricted original loader")
        cls.original_state = original_loader(
            io.BytesIO(cls.original_weight_bytes), map_location="cpu", weights_only=True
        )
        cls.original_model = informative_lineart_generator(torch)
        cls.original_model.load_state_dict(cls.original_state, strict=True)
        member = {file.relative_path: file for file in cls.acquired.manifest.files}[
            "model.safetensors"
        ]
        with verified_directory(cls.staging / "model", expected_owner_uid=os.geteuid()) as root:
            cls.safe_bytes = read_staged_member(
                root,
                "model.safetensors",
                maximum_bytes=member.size_bytes,
                expected_sha256=member.sha256,
                expected_owner_uid=os.geteuid(),
            )
        cls.safe_model = load_informative_lineart_safetensors(cls.safe_bytes, torch=torch)
        print(f"NUMERICAL_SOURCE_SHA256={cls.upstream.weight_sha256}")
        print(f"NUMERICAL_MANIFEST_SHA256={cls.acquired.manifest.manifest_sha256}")
        print(f"NUMERICAL_TORCH={torch.__version__} DEVICE=cpu")
        print(
            f"NUMERICAL_TENSORS={cls.acquired.tensor_count} "
            f"PARAMETERS={cls.acquired.parameter_count}"
        )

    def test_all_converted_tensors_are_bit_identical_to_restricted_original(self) -> None:
        recovered = self.safe_model.state_dict()
        self.assertEqual(set(recovered), set(self.original_state))
        for name, original in self.original_state.items():
            with self.subTest(name=name):
                self.assertTrue(self.torch.equal(recovered[name], original))
                self.assertEqual(recovered[name].device.type, "cpu")
                self.assertEqual(recovered[name].dtype, self.torch.float32)

    def test_synthetic_forward_is_bit_identical_finite_and_bounded(self) -> None:
        torch = self.torch
        values = torch.linspace(0, 1, 3 * 32 * 32, dtype=torch.float32).reshape(1, 3, 32, 32)
        with torch.inference_mode():
            original = self.original_model(values)
            converted = self.safe_model(values)
        self.assertEqual(tuple(converted.shape), (1, 1, 32, 32))
        self.assertTrue(torch.equal(converted, original))
        self.assertTrue(bool(torch.isfinite(converted).all()))
        self.assertGreaterEqual(float(converted.min()), 0)
        self.assertLessEqual(float(converted.max()), 1)

    def test_fixed_architecture_is_frozen_and_preserves_original_state_names(self) -> None:
        model, torch = self.safe_model, self.torch
        self.assertFalse(model.training)
        self.assertTrue(all(not parameter.requires_grad for parameter in model.parameters()))
        self.assertEqual(len(model.model2), 3)
        self.assertEqual(model.model0[1].in_channels, 3)
        self.assertEqual(model.model4[1].out_channels, 1)
        self.assertIsInstance(model.model4[2], torch.nn.Sigmoid)
        self.assertEqual(
            sum(isinstance(layer, torch.nn.InstanceNorm2d) for layer in model.modules()), 11
        )
        self.assertIn("model2.2.conv_block.5.bias", model.state_dict())
        self.assertEqual(
            self.acquired.parameter_count,
            sum(tensor.numel() for tensor in self.original_state.values()),
        )

    def test_conversion_bytes_are_deterministic_and_only_safe_runtime_files_are_written(
        self,
    ) -> None:
        from eom_image_provider.informative_lineart_model import convert_informative_lineart_weights

        replay = convert_informative_lineart_weights(self.original_weight_bytes, self.upstream)
        self.assertEqual(replay.safetensors_bytes, self.safe_bytes)
        self.assertEqual(
            set(path.name for path in (self.staging / "model").iterdir()),
            {"LICENSE", "config.json", "model.safetensors", "upstream.json", "manifest.json"},
        )
        self.assertEqual(self.acquired.manifest.activation_policy, "FORBIDDEN")
        self.assertEqual(
            "sha256:" + hashlib.sha256(self.original_weight_bytes).hexdigest(),
            self.upstream.weight_sha256,
        )

    def test_tensor_validation_rejects_bad_keys_shape_dtype_layout_device_and_nonfinite(
        self,
    ) -> None:
        from eom_image_provider.informative_lineart_model import (
            validate_informative_lineart_tensors,
        )
        from eom_image_provider.provider import ProviderError

        torch = self.torch
        name = "model0.1.weight"
        original = self.original_state[name]
        for fault in (
            "missing",
            "extra",
            "shape",
            "float64",
            "nan",
            "inf",
            "parameter",
            "sparse",
            "meta",
        ):
            with self.subTest(fault=fault):
                values = dict(self.original_state)
                if fault == "missing":
                    values.pop(name)
                elif fault == "extra":
                    values["unexpected"] = torch.zeros(1)
                elif fault == "shape":
                    values[name] = original[:1]
                elif fault == "float64":
                    values[name] = original.double()
                elif fault in {"nan", "inf"}:
                    values[name] = original.clone()
                    values[name].reshape(-1)[0] = float(fault)
                elif fault == "parameter":
                    values[name] = torch.nn.Parameter(original)
                elif fault == "sparse":
                    values[name] = original.to_sparse()
                else:
                    values[name] = torch.empty_like(original, device="meta")
                with self.assertRaisesRegex(ProviderError, "MODEL_INVALID"):
                    validate_informative_lineart_tensors(values, model=self.safe_model, torch=torch)

    def test_bad_safetensor_payload_has_stable_failure(self) -> None:
        from eom_image_provider.informative_lineart_model import (
            load_informative_lineart_safetensors,
        )
        from eom_image_provider.provider import ProviderError

        for payload in (b"", b"invalid-safe-tensor-file", self.safe_bytes[:-1]):
            with (
                self.subTest(size=len(payload)),
                self.assertRaisesRegex(ProviderError, "MODEL_INVALID"),
            ):
                load_informative_lineart_safetensors(payload, torch=self.torch)

    def test_bad_original_bytes_are_rejected_before_deserialization(self) -> None:
        from eom_image_provider.informative_lineart_model import convert_informative_lineart_weights
        from eom_image_provider.provider import ProviderError

        for payload in (b"bad", b"x" * self.upstream.weight_bytes):
            with (
                self.subTest(size=len(payload)),
                patch.object(
                    self.torch, "load", side_effect=AssertionError("unsafe loader called")
                ),
                self.assertRaises(ProviderError),
            ):
                convert_informative_lineart_weights(payload, self.upstream)


@unittest.skipUnless(
    os.environ.get("EOM_RUN_INFORMATIVE_LINEART_NUMERICAL") == "1",
    "explicit informative lineart numerical opt-in required",
)
class InformativeLineartCpuConstruction(unittest.TestCase):
    def test_generator_remains_cpu_with_a_non_cpu_default_device(self) -> None:
        import torch
        from eom_image_provider.informative_lineart_model import informative_lineart_generator

        with (
            patch.object(torch.cuda, "_lazy_init", side_effect=AssertionError("used CUDA")),
            torch.device("meta"),
        ):
            model = informative_lineart_generator(torch)
        self.assertTrue(all(tensor.device.type == "cpu" for tensor in model.state_dict().values()))
        self.assertTrue(
            all(tensor.dtype == torch.float32 for tensor in model.state_dict().values())
        )


if __name__ == "__main__":
    unittest.main()
