"""File entry-point routing must share the closed command codecs' version support."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyComparisonBudget
from eom_image_contracts.sdxl_canny_reference import SdxlCannyReferenceInitialization
from eom_image_contracts.sdxl_native_canny_reference import parse_reference_command
from eom_image_contracts.sdxl_photo_style_execution import parse_photo_style_command
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command


def _pin(family: str, version: str = "1.0") -> dict[str, str]:
    return dict(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="manifests/" + family + ".json",
        schema_ref="eom://schemas/image-provider/local-image-" + family + "/" + version,
        media_type="application/json",
        sha256="sha256:" + "c" * 64,
    )


def _seal(value: dict, prefix: str) -> dict:
    value["run_id"] = prefix + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _photo(version: str) -> dict:
    return _seal(
        dict(
            schema_version="local-image-sdxl-photo-style-command/" + version,
            source_commit="a" * 40,
            created_at="2026-10-06T00:00:00Z",
            purpose="EVALUATION_ONLY_PHOTO_TO_EXAM_STYLE",
            activation_policy="FORBIDDEN",
            plan=_pin("sdxl-photo-style-plan", version),
            plan_id="imgsdxlphotoplan_" + "d" * 32,
            plan_sha256="sha256:" + "e" * 64,
        ),
        "imgsdxlvalcmprun_",
    )


def _reference(version: str) -> dict:
    value = dict(
        schema_version="local-image-sdxl-canny-reference-command/" + version,
        source_commit="a" * 40,
        created_at="2026-10-06T00:00:00Z",
        purpose="EVALUATION_ONLY_MATCHED_CANNY_SOURCE_INITIALIZATION",
        activation_policy="FORBIDDEN",
        spatial_command=_pin("sdxl-canny-comparison-command"),
        spatial_result=_pin("sdxl-canny-comparison-result"),
        initialization=SdxlCannyReferenceInitialization().model_dump(mode="json"),
        budget=SdxlCannyComparisonBudget(
            maximum_duration_ms=180_000, maximum_peak_gpu_memory_bytes=16_000_000_000
        ).model_dump(mode="json"),
    )
    if version != "1.0":
        value.update(
            native_evaluation_command=_pin(
                "sdxl-lora-evaluation-command",
                {"1.1": "1.2", "1.2": "1.4", "1.3": "1.5"}[version],
            ),
            case_relation="REVIEWED_TRAIN_REFERENCE_NOT_HOLDOUT",
        )
    return _seal(value, "imgsdxlcannyrefrun_")


def _stage(root: Path, raw: bytes) -> Path:
    root.mkdir(mode=0o700)
    path = root / "command.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"])
def test_photo_file_route_preserves_exact_codec_version(tmp_path, version):
    expected = parse_photo_style_command(_photo(version))
    raw = content_json_bytes(expected.model_dump(mode="json"))
    root = tmp_path / "workspace"
    path = _stage(root, raw)
    actual = load_sdxl_comparison_command(root, path)
    assert type(actual) is type(expected)
    assert actual == expected
    assert path.read_bytes() == raw


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2", "1.3"])
def test_reference_file_route_preserves_exact_codec_version(tmp_path, version):
    expected = parse_reference_command(_reference(version))
    raw = content_json_bytes(expected.model_dump(mode="json"))
    root = tmp_path / "workspace"
    path = _stage(root, raw)
    actual = load_sdxl_comparison_command(root, path)
    assert type(actual) is type(expected)
    assert actual == expected
    assert path.read_bytes() == raw


@pytest.mark.parametrize(
    "schema",
    [
        None,
        [],
        {},
        5,
        "local-image-sdxl-photo-style-command/99.0",
        "local-image-sdxl-photo-style-result/1.5",
        "local-image-sdxl-canny-reference-command/99.0",
    ],
)
def test_unknown_file_route_fails_closed_without_latest_fallback(tmp_path, schema):
    value = _photo("1.5")
    value["schema_version"] = schema
    root = tmp_path / "workspace"
    path = _stage(root, content_json_bytes(value))
    with pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"):
        load_sdxl_comparison_command(root, path)


@pytest.mark.parametrize(
    "fault", ["noncanonical", "hash", "plan-version", "reference-version", "path"]
)
def test_known_file_route_still_validates_identity_and_canonical_input(tmp_path, fault):
    value = _reference("1.3") if fault == "reference-version" else _photo("1.5")
    if fault == "hash":
        value["command_sha256"] = "sha256:" + "0" * 64
    elif fault in {"plan-version", "reference-version"}:
        key = "plan" if fault == "plan-version" else "native_evaluation_command"
        value[key]["schema_ref"] = value[key]["schema_ref"].rsplit("/", 1)[0] + "/1.4"
        value.pop("run_id")
        value.pop("command_sha256")
        _seal(value, "imgsdxlvalcmprun_" if fault == "plan-version" else "imgsdxlcannyrefrun_")
    raw = (
        json.dumps(value, indent=2).encode()
        if fault == "noncanonical"
        else content_json_bytes(value)
    )
    root = tmp_path / "workspace"
    path = _stage(root, raw)
    if fault == "path":
        path = root / "other.json"
    with pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"):
        load_sdxl_comparison_command(root, path)
