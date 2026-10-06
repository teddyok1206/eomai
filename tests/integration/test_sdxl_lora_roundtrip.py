"""Opt-in CPU roundtrip of a pinned native adapter, not a quality evaluation.

The Orchestrator first admits the existing native evaluation's complete lineage.
This diagnostic reads its immutable staged inputs; it does not dispatch that
evaluation again. One actual UNet and the saved adapter compare training-style
PEFT loading with the provider loader on synthetic CPU conditioning. No text
encoders, VAE, scheduler, dataset pixels, GPU, images, optimizer, database or NAS.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("EOM_RUN_SDXL_LORA_ROUNDTRIP") == "1",
    "explicit pinned-adapter CPU roundtrip opt-in required",
)
class SdxlLoraRoundtrip(unittest.TestCase):
    report: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        import torch  # type: ignore[import-not-found]
        from diffusers import UNet2DConditionModel  # type: ignore[import-not-found]
        from eom_image_contracts import content_json_bytes
        from eom_image_contracts.sdxl_evaluation_codec import parse_sdxl_evaluation_command
        from eom_image_contracts.sdxl_native_evaluation import (
            parse_sdxl_native_evaluation_sources,
        )
        from eom_image_contracts.sdxl_native_geometry import (
            LocalImageSdxlNativeGeometryCommand,
            validate_sdxl_native_geometry_sources,
        )
        from eom_image_provider.sdxl_lora_material import (
            apply_sdxl_lora,
            load_sdxl_lora_material,
        )
        from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
        from eom_image_provider.staged_file_io import read_staged_member, verified_directory
        from eom_image_trainer.diffusers_backend import TARGET_MODULES
        from peft import LoraConfig  # type: ignore[import-not-found]
        from peft.utils import (  # type: ignore[import-not-found]
            get_peft_model_state_dict,
            set_peft_model_state_dict,
        )
        from safetensors.torch import load  # type: ignore[import-not-found]

        root = Path(os.environ["EOM_SDXL_LORA_ROUNDTRIP_INPUT_ROOT"])
        with verified_directory(root, expected_owner_uid=os.geteuid()) as descriptor:
            raw = read_staged_member(
                descriptor,
                "command.json",
                maximum_bytes=256 * 1024,
                expected_sha256=os.environ["EOM_SDXL_LORA_ROUNDTRIP_COMMAND_SHA256"],
            )
            command = parse_sdxl_evaluation_command(json.loads(raw))
            if not isinstance(command, LocalImageSdxlNativeGeometryCommand):
                raise ValueError("ROUNDTRIP_NATIVE_EVALUATION_REQUIRED")
            if raw != content_json_bytes(command.model_dump(mode="json")):
                raise ValueError("ROUNDTRIP_NONCANONICAL_COMMAND")
            pin = command.evaluation
            payloads = {
                name: read_staged_member(
                    descriptor,
                    "inputs/" + name + ".json",
                    maximum_bytes=256 * 1024,
                    expected_sha256=pointer.sha256,
                )
                for name, pointer in (
                    ("baseline-command", pin.baseline_command),
                    ("training-command", pin.training_command),
                    ("training-result", pin.training_result),
                    ("adapter-manifest", pin.adapter_manifest),
                )
            }
            sources = parse_sdxl_native_evaluation_sources(
                command,
                baseline_payload=payloads["baseline-command"],
                training_command_payload=payloads["training-command"],
                training_result_payload=payloads["training-result"],
                manifest_payload=payloads["adapter-manifest"],
            )
            validate_sdxl_native_geometry_sources(command, sources)
            material = load_sdxl_lora_material(descriptor, sources.manifest, strength=1.0)
        stack = resolve_sdxl_stack(
            Path(os.environ["EOM_SDXL_MODEL_STORE_ROOT"]), sources.baseline.model
        )
        state = load(material.weights)
        started = time.monotonic()
        torch.set_num_threads(2)
        torch.manual_seed(20261006)
        torch.use_deterministic_algorithms(True)
        cls.report = {
            "scope": "CPU_FP32_UNET_ADAPTER_ROUNDTRIP_NOT_CUDA_OR_QUALITY",
            "command_sha256": command.command_sha256,
            "training_command": pin.training_command.model_dump(mode="json"),
            "training_result": pin.training_result.model_dump(mode="json"),
            "adapter_manifest": pin.adapter_manifest.model_dump(mode="json"),
            "adapter_weights_sha256": "sha256:" + hashlib.sha256(material.weights).hexdigest(),
            "training_samples": len(sources.training_command.training_samples),
            "saved_tensor_count": len(state),
            "gpu_calls": 0,
            "image_generations": 0,
            "training_updates": 0,
            "source_png_reads": 0,
            "reserved_reads": 0,
            "unet_model_loads": 1,
            "text_encoder_vae_scheduler_model_loads": 0,
        }

        with (
            patch.object(
                torch.cuda, "_lazy_init", side_effect=AssertionError("ROUNDTRIP_USED_CUDA")
            ),
            torch.no_grad(),
        ):
            unet = (
                UNet2DConditionModel.from_pretrained(
                    stack.component_roots["BASE"],
                    subfolder="unet",
                    variant="fp16",
                    torch_dtype=torch.float32,
                    local_files_only=True,
                    use_safetensors=True,
                )
                .requires_grad_(False)
                .eval()
            )
            base_versions = {id(p): p._version for p in unet.parameters()}
            latent = torch.randn(1, 4, 8, 8)
            hidden = torch.randn(1, 77, unet.config.cross_attention_dim)
            pooled = torch.randn(1, 1280)
            time_ids = torch.tensor([[1024, 768, 0, 0, 1024, 768]], dtype=torch.float32)

            def forward() -> Any:
                if time.monotonic() - started > 600:
                    raise RuntimeError("ROUNDTRIP_CPU_DURATION_EXCEEDED")
                result = unet(
                    latent,
                    torch.tensor([500], dtype=torch.int64),
                    hidden,
                    added_cond_kwargs={"text_embeds": pooled, "time_ids": time_ids},
                ).sample
                if not bool(torch.isfinite(result).all()):
                    raise RuntimeError("ROUNDTRIP_NONFINITE_PREDICTION")
                return result.clone()

            base = forward()
            unet.add_adapter(
                LoraConfig(
                    r=8,
                    lora_alpha=8,
                    init_lora_weights="gaussian",
                    target_modules=list(TARGET_MODULES),
                )
            )
            for parameter in unet.parameters():
                if parameter.requires_grad:
                    parameter.data = parameter.data.to(torch.float32)
            incompatible = set_peft_model_state_dict(unet, state, adapter_name="default")
            if incompatible.unexpected_keys or any(
                "lora_" in key for key in incompatible.missing_keys
            ):
                raise ValueError("ROUNDTRIP_TRAINING_STATE_MISMATCH")
            training_state = get_peft_model_state_dict(unet, adapter_name="default")
            cls.report["training_loader_exact_weights"] = set(training_state) == set(state) and all(
                torch.equal(state[key], training_state[key]) for key in state
            )
            training = forward()
            unet.delete_adapters("default")
            apply_sdxl_lora(unet, material)
            inference_state = get_peft_model_state_dict(unet, adapter_name="exam_style")
            cls.report["provider_loader_exact_weights"] = set(inference_state) == set(
                state
            ) and all(torch.equal(state[key], inference_state[key]) for key in state)
            inference = forward()
            cls.report["prediction_byte_equal"] = bool(torch.equal(training, inference))
            cls.report["maximum_prediction_delta"] = float((training - inference).abs().max())
            cls.report["base_to_adapter_maximum_delta"] = float((base - inference).abs().max())
            layers = [m for m in unet.modules() if hasattr(m, "lora_A") and m.lora_A]
            cls.report["adapter_layer_count"] = len(layers)
            cls.report["unit_scale_exact"] = all(m.scaling["exam_style"] == 1.0 for m in layers)
            unet.set_adapters("exam_style", weights=0.5)
            cls.report["half_scale_exact"] = all(m.scaling["exam_style"] == 0.5 for m in layers)
            cls.report["scaling_does_not_change_weights"] = all(
                torch.equal(state[key], value)
                for key, value in get_peft_model_state_dict(unet, adapter_name="exam_style").items()
            )
            unet.disable_adapters()
            restored = forward()
            cls.report["disabled_adapter_restores_base"] = bool(torch.equal(base, restored))
            observed_versions = {
                id(p): p._version for p in unet.parameters() if id(p) in base_versions
            }
            cls.report["base_parameter_versions_unchanged"] = base_versions == observed_versions
            cls.report["all_parameters_cpu"] = all(
                p.device.type == "cpu" for p in unet.parameters()
            )
            cls.report["synthetic_unet_forward_calls"] = 4
            cls.report["duration_seconds"] = time.monotonic() - started
            cls.report["maximum_resident_bytes"] = (
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            )
        print(
            "SDXL_LORA_ROUNDTRIP_DIAGNOSTIC=" + json.dumps(cls.report, sort_keys=True), flush=True
        )

    def test_both_loaders_preserve_every_saved_tensor(self) -> None:
        self.assertGreater(self.report["saved_tensor_count"], 0)
        self.assertTrue(self.report["training_loader_exact_weights"])
        self.assertTrue(self.report["provider_loader_exact_weights"])

    def test_training_style_and_provider_predictions_are_identical(self) -> None:
        self.assertTrue(self.report["prediction_byte_equal"])
        self.assertEqual(self.report["maximum_prediction_delta"], 0.0)
        self.assertGreater(self.report["base_to_adapter_maximum_delta"], 0.0)

    def test_adapter_strength_is_explicit_without_mutating_weights(self) -> None:
        self.assertEqual(self.report["adapter_layer_count"] * 2, self.report["saved_tensor_count"])
        self.assertTrue(self.report["unit_scale_exact"])
        self.assertTrue(self.report["half_scale_exact"])
        self.assertTrue(self.report["scaling_does_not_change_weights"])

    def test_base_is_unchanged_and_adapter_is_reversible(self) -> None:
        self.assertTrue(self.report["base_parameter_versions_unchanged"])
        self.assertTrue(self.report["disabled_adapter_restores_base"])

    def test_cpu_diagnostic_stays_bounded_and_is_not_generation(self) -> None:
        self.assertTrue(self.report["all_parameters_cpu"])
        self.assertLessEqual(self.report["duration_seconds"], 600)
        self.assertLessEqual(self.report["maximum_resident_bytes"], 16 * 1024**3)
        self.assertEqual(self.report["image_generations"], 0)
        self.assertEqual(self.report["training_updates"], 0)
        self.assertEqual(self.report["gpu_calls"], 0)


if __name__ == "__main__":
    unittest.main()
