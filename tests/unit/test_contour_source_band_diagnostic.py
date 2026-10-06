"""Terminal contour admission and kernel sharing; model-free, no live fixture."""

from __future__ import annotations

import json
import sys

import pytest
from eom_image_contracts import content_json_bytes
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommandV4
from jsonschema.exceptions import ValidationError as SchemaError

from tests.integration import test_sdxl_contour_source_band_denoising as contour
from tests.integration import test_sdxl_source_band_denoising as original
from tests.unit.test_native_contour_loss_contracts import _weighted_value
from tests.unit.test_sdxl_native_lora_contracts import _result_value, _seal_result


def _documents():
    command = LocalImageSdxlNativeLoraCommandV4.model_validate(_weighted_value())
    return command, _result_value(command)


def test_terminal_admission_and_same_numerical_kernel():
    command, result = _documents()
    parsed, completed = contour.validate_completed_training(
        content_json_bytes(command.model_dump(mode="json")), content_json_bytes(result)
    )
    assert parsed == command and completed.status == "SUCCEEDED"
    assert (
        contour.InstalledContourSourceBandDenoising.test_frozen_paired_noise_prediction
        is original.InstalledSourceBandDenoising.test_frozen_paired_noise_prediction
    )
    assert contour.InstalledContourSourceBandDenoising.__unittest_skip__ is True
    assert "torch" not in sys.modules


@pytest.mark.parametrize("document", ["command", "result"])
def test_noncanonical_inputs_rejected(document):
    command, result = _documents()
    raw_command, raw_result = (
        content_json_bytes(command.model_dump(mode="json")),
        content_json_bytes(result),
    )
    if document == "command":
        raw_command = json.dumps(command.model_dump(mode="json"), indent=2).encode()
    else:
        raw_result = json.dumps(result, indent=2).encode()
    with pytest.raises(ValueError, match="NOT_CANONICAL"):
        contour.validate_completed_training(raw_command, raw_result)


@pytest.mark.parametrize(
    "fault", ["command_hash", "manifest_hash", "realized_hash", "missing_manifest"]
)
def test_rehashed_lineage_mismatch_fails_closed(fault):
    command, result = _documents()
    if fault == "command_hash":
        result["command_sha256"] = "sha256:" + "f" * 64
    elif fault == "manifest_hash":
        result["adapter_manifest"]["training_command_sha256"] = "sha256:" + "f" * 64
    elif fault == "realized_hash":
        result["realized_samples"][0]["target_png_sha256"] = "sha256:" + "f" * 64
    else:
        result["adapter_manifest"] = None
    result = _seal_result(result)
    with pytest.raises((ValueError, SchemaError)):
        contour.validate_completed_training(
            content_json_bytes(command.model_dump(mode="json")), content_json_bytes(result)
        )


def test_old_fixture_remains_exact_not_aliased_to_new_training():
    import inspect

    old = inspect.getsource(original.InstalledSourceBandDenoising.load_admitted_inputs)
    assert "LocalImageSdxlNativeLoraCommandV3" in old
    assert "283200c091348bb8c0098aefca6f33e024cddcc3c78457969d0ce7809bd17d54" in old
    new = inspect.getsource(contour.InstalledContourSourceBandDenoising.load_admitted_inputs)
    assert "fdf230a6f836c16094f3c0cfb602b3e68b5c2743e3df3bb80fccdc21c00f47d0" in new
    assert "admission.validated_sources()" in new
    assert new.index("admission.validated_sources()") < new.index("load_sdxl_lora_material(root")
