"""New terminal-adapter fixture; the historical probe owns the identical kernel."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any


def _legacy_fixture() -> ModuleType:
    if __package__:
        from tests.integration import test_sdxl_source_band_denoising

        return test_sdxl_source_band_denoising
    # The owner stages an exact trusted test, not executable uploaded input.
    from eom_image_provider.staged_file_io import read_staged_member, verified_directory

    path = Path(__file__).absolute().parent
    with verified_directory(path, expected_owner_uid=0) as root:
        read_staged_member(
            root,
            "historical-fixture.py",
            maximum_bytes=32 * 1024,
            expected_owner_uid=0,
            expected_sha256=os.environ["EOM_SOURCE_BAND_FIXTURE_SHA256"],
        )
    spec = importlib.util.spec_from_file_location(
        "source_band_fixture", path / "historical-fixture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_legacy = _legacy_fixture()

if TYPE_CHECKING:
    from tests.integration.test_sdxl_source_band_denoising import (
        InstalledSourceBandDenoising as _Probe,
    )
else:
    _Probe = _legacy.InstalledSourceBandDenoising


def validate_completed_training(command_raw: bytes, result_raw: bytes) -> tuple[Any, Any]:
    """Exact schema/canonical/terminal lineage before resolving pixels or weights."""
    from eom_image_contracts import content_json_bytes, validate_contract
    from eom_image_contracts.sdxl_native_lora import (
        LocalImageSdxlNativeLoraCommandV4,
        LocalImageSdxlNativeLoraResult,
        validate_sdxl_native_lora_result,
    )

    validate_contract("sdxl-native-lora-command-v4", json.loads(command_raw))
    validate_contract("sdxl-native-lora-result", json.loads(result_raw))
    command = LocalImageSdxlNativeLoraCommandV4.model_validate_json(command_raw)
    result = LocalImageSdxlNativeLoraResult.model_validate_json(result_raw)
    if command_raw != content_json_bytes(
        command.model_dump(mode="json")
    ) or result_raw != content_json_bytes(result.model_dump(mode="json")):
        raise ValueError("SOURCE_BAND_DOCUMENT_NOT_CANONICAL")
    validate_sdxl_native_lora_result(command, result)
    if result.status != "SUCCEEDED" or result.adapter_manifest is None:
        raise ValueError("SOURCE_BAND_TRAINING_NOT_SUCCEEDED")
    return command, result


@unittest.skipUnless(
    os.environ.get("EOM_RUN_SDXL_CONTOUR_SOURCE_BAND_DENOISING") == "1",
    "explicit owner-admitted terminal-adapter diagnostic opt-in required",
)
class InstalledContourSourceBandDenoising(_Probe):
    # Only input admission differs; do not copy the numerical recipe.
    __unittest_skip__ = False

    def load_admitted_inputs(self) -> tuple[Any, Any, list[Any], list[Any], Any, str]:
        from eom_image_contracts.sdxl_native_lora_sources import (
            SdxlNativeLoraMetadataAdmission,
            sdxl_native_lora_metadata_member_path,
        )
        from eom_image_contracts.sdxl_photo_style_execution import parse_photo_style_command
        from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
        from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
        from eom_image_provider.sdxl_photo_style_sources import read_sdxl_photo_style_sources
        from eom_image_provider.staged_file_io import read_staged_member, verified_directory
        from eom_image_trainer.diffusers_backend import LoraTensorSample
        from PIL import Image

        input_root = Path(os.environ["EOM_SOURCE_BAND_INPUT_ROOT"])
        prior_root = Path(os.environ["EOM_SOURCE_BAND_METADATA_ROOT"])
        native_root = Path(os.environ["EOM_SOURCE_BAND_NATIVE_METADATA_ROOT"])
        with verified_directory(input_root, expected_owner_uid=0) as root:
            command_raw = read_staged_member(
                root,
                "training-command.json",
                maximum_bytes=2 * 1024**2,
                expected_owner_uid=0,
                expected_sha256="sha256:fdf230a6f836c16094f3c0cfb602b3e68b5c2743e3df3bb80fccdc21c00f47d0",
            )
            result_raw = read_staged_member(
                root,
                "training-result.json",
                maximum_bytes=2 * 1024**2,
                expected_owner_uid=0,
                expected_sha256="sha256:85c0d9a59f06d89b13cce4d543e006f6917cbcac5af1e718beb88a8a8237de4f",
            )
        training, completed = validate_completed_training(command_raw, result_raw)
        admission = SdxlNativeLoraMetadataAdmission(training)
        with verified_directory(native_root, expected_owner_uid=os.geteuid()) as root:
            while pending := admission.pending_pointers():
                for pin in pending:
                    admission.admit(
                        pin,
                        read_staged_member(
                            root,
                            sdxl_native_lora_metadata_member_path(pin),
                            maximum_bytes=2 * 1024**2,
                            expected_sha256=pin.sha256,
                        ),
                    )
            admitted = admission.validated_sources()
        self.assertEqual(len(admitted.targets), 100)
        # Resolve the same authenticated BASE revision, not the previous adapter.
        with verified_directory(prior_root, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(
                root,
                "command.json",
                maximum_bytes=128 * 1024,
                expected_sha256=os.environ["EOM_SOURCE_BAND_COMMAND_SHA256"],
            )
            reference = parse_photo_style_command(json.loads(raw))
            sources = read_sdxl_photo_style_sources(root, reference)
        baseline = sources.configuration_sources.spatial_sources.targets.lora.baseline.model
        self.assertEqual(training.base_model, baseline)
        self.assertEqual(
            training.training_samples,
            sources.configuration_sources.native.training_command.training_samples,
        )
        samples = {sample.sample_id: sample for sample in training.training_samples}
        tensors, masks = [], []
        with verified_directory(input_root, expected_owner_uid=0) as root:
            material = load_sdxl_lora_material(root, completed.adapter_manifest, strength=1.0)
            for sample_id, sha in _legacy.SAMPLES:
                sample = samples[sample_id]
                self.assertEqual(sample.source_image.sha256, "sha256:" + sha)
                raw = read_staged_member(
                    root,
                    sample_id + ".png",
                    maximum_bytes=8 * 1024**2,
                    expected_owner_uid=0,
                    expected_sha256=sample.source_image.sha256,
                )
                with Image.open(io.BytesIO(raw)) as image:
                    self.assertEqual(
                        (image.format, image.mode, image.size), ("PNG", "RGB", sample.width_height)
                    )
                    masks.append(
                        _legacy.source_cell_bands(tuple(image.convert("L").getdata()), *image.size)
                    )
                tensors.append(
                    LoraTensorSample(
                        sample.training_caption_en,
                        input_root / (sample_id + ".png"),
                        *sample.width_height,
                    )
                )
        stack = resolve_sdxl_stack(Path(os.environ["EOM_SDXL_MODEL_STORE_ROOT"]), baseline)
        return material, training, tensors, masks, stack, reference.command_sha256


# Pytest/unittest discover imported TestCase aliases as additional test suites.
# Keep only this fixture's declared class in the entrypoint namespace.
if not TYPE_CHECKING:
    del _Probe

if __name__ == "__main__":
    unittest.main()
