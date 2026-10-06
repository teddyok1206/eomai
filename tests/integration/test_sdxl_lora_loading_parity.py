"""Opt-in real installed LoRA loader CPU parity; not diffusion or training.

Uses one already completed immutable comparison workspace as read-only input.
The owner admits its exact canonical command/metadata before staging this test.
No dataset PNG, VAE/text encoder, GPU, optimizer, DB/NAS or network access.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

MAX_SECONDS = 360


def _base_parameter_digests(unet: Any, torch: Any) -> dict[str, str]:
    result = {}
    for name, tensor in unet.named_parameters():
        if ".lora_A." in name or ".lora_B." in name:
            continue
        canonical = name.replace(".base_layer.", ".")
        if canonical in result:
            raise ValueError("LORA_PARITY_DUPLICATE_BASE_PARAMETER")
        data = tensor.detach().contiguous().view(torch.uint8).numpy()
        result[canonical] = hashlib.sha256(memoryview(data)).hexdigest()
    return result


@unittest.skipUnless(
    os.environ.get("EOM_RUN_SDXL_LORA_LOADING_PARITY") == "1",
    "explicit installed-model CPU LoRA loading opt-in required",
)
class InstalledNativeLoraLoadingParity(unittest.TestCase):
    evidence: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        import torch  # type: ignore[import-not-found]
        from diffusers import UNet2DConditionModel  # type: ignore[import-not-found]
        from eom_image_contracts import content_json_bytes
        from eom_image_contracts.sdxl_native_canny_reference import sdxl_reference_adapter
        from eom_image_contracts.sdxl_photo_style_execution import parse_photo_style_command
        from eom_image_provider.sdxl_lora_material import apply_sdxl_lora, load_sdxl_lora_material
        from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
        from eom_image_provider.sdxl_photo_style_sources import read_sdxl_photo_style_sources
        from eom_image_provider.staged_file_io import read_staged_member, verified_directory
        from peft.utils import get_peft_model_state_dict  # type: ignore[import-not-found]
        from safetensors.torch import load  # type: ignore[import-not-found]

        started = time.monotonic()
        torch.set_num_threads(2)
        if torch.cuda.is_initialized():
            raise RuntimeError("LORA_PARITY_CUDA_ALREADY_INITIALIZED")
        workspace = Path(os.environ["EOM_SDXL_LORA_PARITY_INPUT_ROOT"])
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(
                root,
                "command.json",
                maximum_bytes=128 * 1024,
                expected_owner_uid=0,
                expected_sha256=os.environ["EOM_SDXL_LORA_PARITY_COMMAND_SHA256"],
            )
            command = parse_photo_style_command(json.loads(raw))
            if raw != content_json_bytes(command.model_dump(mode="json")):
                raise ValueError("LORA_PARITY_NONCANONICAL_COMMAND")
            sources = read_sdxl_photo_style_sources(root, command)
            spatial = sources.configuration_sources.spatial_sources
            selected = sdxl_reference_adapter(sources.configuration_sources)
            material = load_sdxl_lora_material(root, selected.manifest, strength=selected.strength)
        if material.strength != 1.0:
            raise ValueError("LORA_PARITY_EXPECTED_FROZEN_STRENGTH")
        stack = resolve_sdxl_stack(
            Path(os.environ["EOM_SDXL_MODEL_STORE_ROOT"]), spatial.targets.lora.baseline.model
        )
        state = load(material.weights)
        with patch.object(torch.cuda, "_lazy_init", side_effect=AssertionError("LORA_PARITY_CUDA")):
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
            )
            before = _base_parameter_digests(unet, torch)
            apply_sdxl_lora(unet, material)
            unet.requires_grad_(False).eval()
            loaded = get_peft_model_state_dict(unet, adapter_name="exam_style")
            if set(loaded) != set(state):
                raise ValueError("LORA_PARITY_LOADED_KEYS_MISMATCH")
            mismatched = [
                key
                for key, value in loaded.items()
                if not torch.equal(value, state[key].to(dtype=value.dtype))
            ]
            if mismatched:
                raise ValueError("LORA_PARITY_LOADED_VALUES_MISMATCH")
            after = _base_parameter_digests(unet, torch)
            if before != after:
                raise ValueError("LORA_PARITY_BASE_PARAMETER_CHANGED")
            modules = {
                name: module
                for name, module in unet.named_modules()
                if hasattr(module, "lora_A") and "exam_style" in module.lora_A
            }
            if len(modules) * 2 != len(state):
                raise ValueError("LORA_PARITY_MODULE_COVERAGE_MISMATCH")
            if any(module.scaling["exam_style"] != 1.0 for module in modules.values()):
                raise ValueError("LORA_PARITY_ALPHA_RANK_SCALE_MISMATCH")
            b_tensors = [value for key, value in state.items() if key.endswith(".lora_B.weight")]
            nonzero_b = sum(bool(torch.count_nonzero(value)) for value in b_tensors)
            if nonzero_b != len(b_tensors) or not all(
                bool(torch.isfinite(v).all()) for v in state.values()
            ):
                raise ValueError("LORA_PARITY_LEARNED_TENSORS_INVALID")
            projections = []
            generator = torch.Generator(device="cpu").manual_seed(20261006)
            chosen = tuple(
                next(name for name in sorted(modules) if name.endswith(suffix))
                for suffix in ("attn1.to_q", "attn2.to_k", "attn2.to_out.0")
            )
            with torch.no_grad():
                for name in chosen:
                    if time.monotonic() - started > MAX_SECONDS:
                        raise RuntimeError("LORA_PARITY_DURATION_EXCEEDED")
                    module = modules[name]
                    x = torch.randn(
                        (1, 4, module.in_features),
                        generator=generator,
                        dtype=module.base_layer.weight.dtype,
                    )
                    base = module.base_layer(x)
                    a, b = module.lora_A["exam_style"], module.lora_B["exam_style"]
                    delta = b(a(x.to(a.weight.dtype))) * module.scaling["exam_style"]
                    expected = (base + delta).to(base.dtype)
                    actual = module(x)
                    error = float((actual.float() - expected.float()).abs().max())
                    if not torch.allclose(actual, expected, atol=1e-3, rtol=2e-3):
                        raise ValueError("LORA_PARITY_PROJECTION_MISMATCH")
                    unet.disable_adapters()
                    disabled = module(x)
                    unet.enable_adapters()
                    if not torch.equal(disabled, base):
                        raise ValueError("LORA_PARITY_DISABLED_NOT_BASE")
                    projections.append(
                        dict(
                            module=name,
                            shape=list(actual.shape),
                            maximum_error=error,
                            learned_delta_rms=float(delta.float().square().mean().sqrt()),
                            actual_vs_base_rms=float(
                                (actual.float() - base.float()).square().mean().sqrt()
                            ),
                        )
                    )
            if not any(row["actual_vs_base_rms"] > 0 for row in projections):
                raise ValueError("LORA_PARITY_NO_REAL_EFFECT")
        cls.evidence = dict(
            status="INSTALLED_LORA_LOADING_CPU_PARITY_PASS",
            command_sha256=command.command_sha256,
            model=spatial.targets.lora.baseline.model.model_dump(mode="json"),
            adapter_id=material.manifest.adapter_id,
            adapter_revision_id=material.manifest.adapter_revision_id,
            adapter_manifest_sha256=material.manifest.manifest_sha256,
            strength=material.strength,
            exported_tensors=len(state),
            loaded_modules=len(modules),
            nonzero_learned_b_tensors=nonzero_b,
            unchanged_base_parameters=len(before),
            projections=projections,
            duration_seconds=time.monotonic() - started,
            cuda_initialized=torch.cuda.is_initialized(),
            gpu_calls=0,
            generation_calls=0,
            training_updates=0,
            optimizer_loads=0,
            dataset_png_reads=0,
            cpu_unet_loads=1,
            cpu_adapter_loads=1,
            quality_acceptance="NOT_EVALUATED",
            generalization="NOT_EVALUATED",
        )
        print("SDXL_LORA_LOADING_PARITY=" + json.dumps(cls.evidence, sort_keys=True), flush=True)

    def test_actual_export_and_scaling(self) -> None:
        self.assertEqual(self.evidence["exported_tensors"], 2 * self.evidence["loaded_modules"])
        self.assertEqual(
            self.evidence["nonzero_learned_b_tensors"], self.evidence["loaded_modules"]
        )

    def test_actual_enabled_disabled_projections(self) -> None:
        self.assertEqual(len(self.evidence["projections"]), 3)
        self.assertTrue(any(row["actual_vs_base_rms"] > 0 for row in self.evidence["projections"]))

    def test_cpu_only_bounded_execution(self) -> None:
        self.assertFalse(self.evidence["cuda_initialized"])
        self.assertLess(self.evidence["duration_seconds"], MAX_SECONDS)
        self.assertGreater(self.evidence["unchanged_base_parameters"], 0)


if __name__ == "__main__":
    unittest.main()
