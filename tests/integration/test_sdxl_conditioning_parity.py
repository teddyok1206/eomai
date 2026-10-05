"""Opt-in installed-model CPU parity, not generation or CUDA training parity.

The owner admits a pinned native TRAIN command and stages only that command and
this test. Actual trainer caption encoding is compared with the installed T2I
pipeline's encode_prompt, routing device requests to CPU only for this test.
No UNet/VAE/LoRA tensors, optimizer, dataset pixels, GPU, database or NAS access.
"""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("EOM_RUN_SDXL_CONDITIONING_PARITY") == "1",
    "explicit installed-model CPU conditioning opt-in required",
)
class SdxlConditioningParity(unittest.TestCase):
    rows: ClassVar[list[dict[str, Any]]]
    time_rows: ClassVar[list[dict[str, Any]]]
    encoder_checks: ClassVar[list[dict[str, Any]]]

    @classmethod
    def setUpClass(cls) -> None:
        import torch  # type: ignore[import-not-found]
        from diffusers import StableDiffusionXLAdapterPipeline  # type: ignore[import-not-found]
        from eom_image_contracts import content_json_bytes, text_sha256, validate_contract
        from eom_image_contracts.sdxl_native_lora import native_lora_command_protocol
        from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
        from eom_image_provider.staged_file_io import read_staged_member, verified_directory
        from eom_image_trainer.diffusers_backend import LoraTensorSample, _prompt_embeddings
        from transformers import (  # type: ignore[import-not-found]
            AutoTokenizer,
            CLIPTextModel,
            CLIPTextModelWithProjection,
        )

        torch.set_num_threads(2)
        cls.rows, cls.time_rows = [], []
        root = Path(os.environ["EOM_SDXL_CONDITIONING_INPUT_ROOT"])
        with verified_directory(root, expected_owner_uid=os.geteuid()) as descriptor:
            raw = read_staged_member(
                descriptor,
                "command.json",
                maximum_bytes=256 * 1024,
                expected_owner_uid=os.geteuid(),
                expected_sha256=os.environ["EOM_SDXL_CONDITIONING_COMMAND_SHA256"],
            )
        value = json.loads(raw)
        protocol = native_lora_command_protocol(value["schema_version"])
        validate_contract(protocol.contract, value)
        command = protocol.model.model_validate(value)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise ValueError("NONCANONICAL_NATIVE_CONDITIONING_INPUT")
        captions = tuple(sample.training_caption_en for sample in command.training_samples)
        if any(
            text_sha256(caption) != sample.training_caption_sha256
            for caption, sample in zip(captions, command.training_samples, strict=True)
        ):
            raise ValueError("CONDITIONING_CAPTION_HASH_MISMATCH")
        stack = resolve_sdxl_stack(
            Path(os.environ["EOM_SDXL_MODEL_STORE_ROOT"]),
            command.base_model,
        )
        base = stack.component_roots["BASE"]
        tokenizers: list[Any] = []
        encoders: list[Any] = []
        real_tokenizer = AutoTokenizer.from_pretrained
        real_small = CLIPTextModel.from_pretrained
        real_large = CLIPTextModelWithProjection.from_pretrained
        real_module_to, real_tensor_to = torch.nn.Module.to, torch.Tensor.to

        def tokenizer(*args: Any, **kwargs: Any) -> Any:
            result = real_tokenizer(*args, **kwargs)
            tokenizers.append(result)
            return result

        def small(*args: Any, **kwargs: Any) -> Any:
            result = real_small(*args, **kwargs)
            encoders.append(result)
            return result

        def large(*args: Any, **kwargs: Any) -> Any:
            result = real_large(*args, **kwargs)
            encoders.append(result)
            return result

        def cpu_args(args: tuple[Any, ...]) -> tuple[Any, ...]:
            if args and isinstance(args[0], (str, torch.device)):
                device = str(args[0])
                if device.startswith("cuda"):
                    return ("cpu", *args[1:])
            return args

        def module_to(module: Any, *args: Any, **kwargs: Any) -> Any:
            return real_module_to(module, *cpu_args(args), **kwargs)

        def tensor_to(tensor: Any, *args: Any, **kwargs: Any) -> Any:
            return real_tensor_to(tensor, *cpu_args(args), **kwargs)

        # Device routing only: never patch embedding/pooling/tokenizer computation.
        with (
            patch.object(
                torch.cuda, "_lazy_init", side_effect=AssertionError("CONDITIONING_TEST_USED_CUDA")
            ),
            patch.object(torch.nn.Module, "to", module_to),
            patch.object(torch.Tensor, "to", tensor_to),
            patch.object(AutoTokenizer, "from_pretrained", tokenizer),
            patch.object(CLIPTextModel, "from_pretrained", small),
            patch.object(CLIPTextModelWithProjection, "from_pretrained", large),
        ):
            actual = _prompt_embeddings(model_directory=base, captions=captions, torch=torch)
        if len(encoders) != 2 or len(tokenizers) != 2:
            raise ValueError("CONDITIONING_ENCODER_CLOSURE_INVALID")
        pipeline = StableDiffusionXLAdapterPipeline(
            vae=None,
            text_encoder=encoders[0],
            text_encoder_2=encoders[1],
            tokenizer=tokenizers[0],
            tokenizer_2=tokenizers[1],
            unet=None,
            adapter=None,
            scheduler=None,
        )
        with (
            patch.object(
                torch.cuda, "_lazy_init", side_effect=AssertionError("CONDITIONING_TEST_USED_CUDA")
            ),
            torch.no_grad(),
        ):
            for sample, caption, (hidden, pooled) in zip(
                command.training_samples,
                captions,
                actual,
                strict=True,
            ):
                expected, _, expected_pooled, _ = pipeline.encode_prompt(
                    prompt=caption,
                    device=torch.device("cpu"),
                    num_images_per_prompt=1,
                    do_classifier_free_guidance=False,
                    lora_scale=None,
                    clip_skip=None,
                )
                lengths = [len(t(caption, truncation=False).input_ids) for t in tokenizers]
                cls.rows.append(
                    dict(
                        sample_id=sample.sample_id,
                        caption_sha256=sample.training_caption_sha256,
                        token_lengths=lengths,
                        maximum_lengths=[t.model_max_length for t in tokenizers],
                        hidden_shape=list(hidden.shape),
                        pooled_shape=list(pooled.shape),
                        hidden_byte_equal=bool(torch.equal(hidden, expected)),
                        pooled_byte_equal=bool(torch.equal(pooled, expected_pooled)),
                        maximum_hidden_delta=float((hidden - expected).abs().max()),
                        maximum_pooled_delta=float((pooled - expected_pooled).abs().max()),
                        finite=bool(torch.isfinite(hidden).all() and torch.isfinite(pooled).all()),
                        dtype=str(hidden.dtype),
                        device=str(hidden.device),
                    )
                )
            # Real pipeline time-ID method, with admitted UNet configuration only.
            config_raw = (base / "unet/config.json").read_bytes()
            config = json.loads(config_raw)
            configuration_only = SimpleNamespace(
                unet=SimpleNamespace(
                    config=SimpleNamespace(
                        addition_time_embed_dim=config["addition_time_embed_dim"]
                    ),
                    add_embedding=SimpleNamespace(
                        linear_1=SimpleNamespace(
                            in_features=config["projection_class_embeddings_input_dim"],
                        )
                    ),
                )
            )
            for width, height in dict.fromkeys(s.width_height for s in command.training_samples):
                target = LoraTensorSample("configuration-only", root / "unused.png", width, height)
                expected_ids = StableDiffusionXLAdapterPipeline._get_add_time_ids(
                    configuration_only,
                    (height, width),
                    (0, 0),
                    (height, width),
                    dtype=torch.float16,
                    text_encoder_projection_dim=encoders[1].config.projection_dim,
                )
                cls.time_rows.append(
                    dict(
                        canvas=[width, height],
                        training_time_ids=list(target.sdxl_time_ids),
                        pipeline_time_ids=expected_ids[0].to(torch.int64).tolist(),
                        unet_config_sha256=hashlib.sha256(config_raw).hexdigest(),
                    )
                )
        cls.encoder_checks = [
            dict(
                frozen=all(not p.requires_grad for p in e.parameters()),
                eval=not e.training,
                cpu=all(p.device.type == "cpu" for p in e.parameters()),
                fp16=all(p.dtype == torch.float16 for p in e.parameters()),
            )
            for e in encoders
        ]
        print(
            "SDXL_CONDITIONING_CPU_DIAGNOSTIC="
            + json.dumps(
                dict(
                    scope="CPU_FP16_TEXT_ENCODING_NOT_CUDA_TRAINING_OR_QUALITY",
                    command_sha256=command.command_sha256,
                    model=command.base_model.model_dump(mode="json"),
                    samples=len(cls.rows),
                    rows=cls.rows,
                    time_rows=cls.time_rows,
                    encoders=cls.encoder_checks,
                    gpu_calls=0,
                    generation_calls=0,
                    training_updates=0,
                    source_png_reads=0,
                    reserved_reads=0,
                    text_encoder_model_loads=2,
                    unet_vae_lora_model_loads=0,
                ),
                sort_keys=True,
            ),
            flush=True,
        )

    def test_actual_training_and_inference_hidden_and_pooled_embeddings_match(self) -> None:
        self.assertGreater(len(self.rows), 0)
        for row in self.rows:
            with self.subTest(sample_id=row["sample_id"]):
                self.assertTrue(row["hidden_byte_equal"])
                self.assertTrue(row["pooled_byte_equal"])
                self.assertEqual(row["hidden_shape"], [1, 77, 2048])
                self.assertEqual(row["pooled_shape"], [1, 1280])
                self.assertEqual(row["maximum_hidden_delta"], 0)
                self.assertEqual(row["maximum_pooled_delta"], 0)
                self.assertTrue(row["finite"])

    def test_exact_captions_fit_both_tokenizers_without_truncation(self) -> None:
        for row in self.rows:
            with self.subTest(sample_id=row["sample_id"]):
                self.assertTrue(
                    all(
                        n <= maximum
                        for n, maximum in zip(
                            row["token_lengths"],
                            row["maximum_lengths"],
                            strict=True,
                        )
                    )
                )

    def test_all_realized_native_geometries_match_pipeline_time_ids(self) -> None:
        self.assertGreater(len(self.time_rows), 0)
        for row in self.time_rows:
            self.assertEqual(row["training_time_ids"], row["pipeline_time_ids"])

    def test_encoders_are_frozen_cpu_fp16_and_no_cuda_tensor_was_used(self) -> None:
        self.assertEqual(len(self.encoder_checks), 2)
        self.assertTrue(all(all(row.values()) for row in self.encoder_checks))
        self.assertTrue(
            all(row["dtype"] == "torch.float16" and row["device"] == "cpu" for row in self.rows)
        )


if __name__ == "__main__":
    unittest.main()
