"""Protocol-first wire draft, not implemented-consumer or model-quality acceptance."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommand,
)
from eom_image_contracts.validation import (
    SCHEMA_FILES,
    SCHEMA_SHA256,
    load_schema,
    validate_contract,
)
from eom_orchestrator.sdxl_validation_inputs import resolve_sdxl_validation_metadata
from jsonschema import Draft202012Validator, ValidationError
from pydantic import ValidationError as ModelValidationError

from tests.unit.test_sdxl_validation_comparison import _fixture, _result, _seal


def _command(tmp_path, monkeypatch):
    predecessor, _, _ = _fixture(tmp_path, monkeypatch)
    value = predecessor.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-validation-comparison-command/1.1"
    value["configuration_anchor"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-canny-reference-command/1.2"
    )
    return _seal(value), predecessor


@pytest.mark.parametrize("family", ["command", "result"])
def test_native_validation_schema_mirrors_and_legacy_bytes(family):
    root = Path(__file__).resolve().parents[2]
    for key in (
        "sdxl-validation-comparison-" + family,
        "sdxl-validation-comparison-" + family + "-v2",
    ):
        name = SCHEMA_FILES[key]
        raw = (root / "schemas/image-provider" / name).read_bytes()
        assert (
            raw
            == (root / "packages/image_contracts/eom_image_contracts/schemas" / name).read_bytes()
        )
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[key]
        Draft202012Validator.check_schema(load_schema(key))
    expected = {
        "command": "sha256:4b04fabb83392de22bf10818f985ac82e098a4bf8d2022f2a9cd6736ea64ea59",
        "result": "sha256:a459f022c4fec7e6a0108cd157bf842a684f189d2106b39cfcb0b000119ff22b",
    }
    assert SCHEMA_SHA256["sdxl-validation-comparison-" + family] == expected[family]


def test_native_wire_draft_has_no_implicit_legacy_consumer(tmp_path, monkeypatch):
    value, _ = _command(tmp_path, monkeypatch)
    validate_contract("sdxl-validation-comparison-command-v2", value)
    with pytest.raises(ValidationError):
        validate_contract("sdxl-validation-comparison-command", value)
    # Until the successor owner is implemented, do not reinterpret a native anchor
    # as a legacy micro adapter by making the old model permissive.
    with pytest.raises(ModelValidationError):
        LocalImageSdxlValidationComparisonCommand.model_validate(value)


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.3"])
def test_native_schema_requires_exact_reference12(tmp_path, monkeypatch, version):
    value, _ = _command(tmp_path, monkeypatch)
    value["configuration_anchor"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-canny-reference-command/" + version
    )
    with pytest.raises(ValidationError):
        validate_contract("sdxl-validation-comparison-command-v2", _seal(value))


@pytest.mark.parametrize("partition", ["TRAIN", "HOLDOUT"])
def test_native_schema_does_not_relax_reserved_partition(tmp_path, monkeypatch, partition):
    value, _ = _command(tmp_path, monkeypatch)
    value["experiment_partition"] = partition
    with pytest.raises(ValidationError):
        validate_contract("sdxl-validation-comparison-command-v2", _seal(value))


@pytest.mark.parametrize("count", [11, 17])
def test_native_schema_preserves_bounded_cases(tmp_path, monkeypatch, count):
    value, _ = _command(tmp_path, monkeypatch)
    value["cases"] = (
        value["cases"][:count]
        if count < 12
        else value["cases"] + (copy.deepcopy(value["cases"][:5]))
    )
    with pytest.raises(ValidationError):
        validate_contract("sdxl-validation-comparison-command-v2", _seal(value))


@pytest.mark.parametrize(
    "missing", [None, "native_evaluation_command_sha256", "native_adapter_manifest_sha256"]
)
def test_native_result_schema_requires_both_pinned_lineage_hashes(tmp_path, monkeypatch, missing):
    _, predecessor = _command(tmp_path, monkeypatch)
    admitted = resolve_sdxl_validation_metadata(object(), predecessor)
    value = _result(predecessor, admitted.sources).model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-validation-comparison-result/1.1",
        native_evaluation_command_sha256="sha256:" + "1" * 64,
        native_adapter_manifest_sha256="sha256:" + "2" * 64,
    )
    if missing is None:
        validate_contract("sdxl-validation-comparison-result-v2", value)
        with pytest.raises(ValidationError):
            validate_contract("sdxl-validation-comparison-result", value)
    else:
        value.pop(missing)
        with pytest.raises(ValidationError):
            validate_contract("sdxl-validation-comparison-result-v2", value)
