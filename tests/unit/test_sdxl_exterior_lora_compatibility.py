"""Explicit successor admission and replay; synthetic backend does not load a model."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import content_json_bytes, validate_contract
from eom_image_contracts.sdxl_native_evaluation import LocalImageSdxlNativeEvaluationCommand
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommand,
    LocalImageSdxlNativeLoraCommandV2,
    native_lora_command_protocol,
)
from eom_image_contracts.sdxl_native_lora_sources import (
    parse_sdxl_native_lora_sources,
    sdxl_native_lora_metadata_member_path,
)
from eom_image_contracts.validation import SCHEMA_SHA256
from eom_image_trainer import diffusers_backend as numerical
from eom_image_trainer import sdxl_native_lora_runner as runner
from eom_image_trainer.sdxl_lora_backend import SdxlNativeLoraBackend
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_evaluation import _fixture as _evaluation_fixture
from tests.unit.test_sdxl_native_lora_contracts import _seal_command
from tests.unit.test_sdxl_native_lora_runner import _Backend, _run, _stage
from tests.unit.test_sdxl_native_lora_sources import _fixture, _staged_metadata


def test_explicit_mixed_target_batches_have_one_closed_metadata_graph(monkeypatch):
    command, records, _pixels, *_ = _fixture(monkeypatch, exterior_batch=True)
    assert isinstance(command, LocalImageSdxlNativeLoraCommandV2)
    protocol = native_lora_command_protocol(command.schema_version)
    validate_contract(protocol.contract, command.model_dump(mode="json"))
    assert [b.command.schema_ref.rsplit("/", 1)[1] for b in command.target_batches] == [
        "1.2",
        "1.3",
    ]
    sources = parse_sdxl_native_lora_sources(command, _staged_metadata(records))
    assert len(sources.targets) == 12 and len(sources.metadata_pointers) == len(records)
    assert sources.batches[0].sources.review is sources.batches[1].sources.review
    assert sources.batches[1].command.schema_version.endswith("/1.3")
    assert sources.batches[1].result.schema_version.endswith("/1.3")


@pytest.mark.parametrize("fault", ["old_training", "crossed_pair", "unknown_target", "hash"])
def test_successor_rejects_version_or_identity_guessing(monkeypatch, fault):
    command, records, _pixels, *_ = _fixture(monkeypatch, exterior_batch=True)
    value = command.model_dump(mode="json")
    if fault == "old_training":
        value["schema_version"] = "local-image-sdxl-native-lora-command/1.0"
        value = _seal_command(value)
        with pytest.raises(ValidationError):
            LocalImageSdxlNativeLoraCommand.model_validate(value)
        with pytest.raises(SchemaValidationError):
            validate_contract("sdxl-native-lora-command", value)
    elif fault in ("crossed_pair", "unknown_target"):
        version = "1.2" if fault == "crossed_pair" else "99.0"
        value["target_batches"][1]["result"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-sdxl-training-target-result/" + version
        )
        value = _seal_command(value)
        with pytest.raises(ValidationError):
            LocalImageSdxlNativeLoraCommandV2.model_validate(value)
        with pytest.raises(SchemaValidationError):
            validate_contract("sdxl-native-lora-command-v2", value)
    else:
        staged = _staged_metadata(records)
        member = sdxl_native_lora_metadata_member_path(command.target_batches[1].command)
        staged[member] += b"\n"
        with pytest.raises(ValueError):
            parse_sdxl_native_lora_sources(command, staged)


def test_successor_worker_preserves_inputs_and_terminal_replay(monkeypatch, tmp_path):
    root, command = _stage(monkeypatch, tmp_path, exterior_batch=True)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    backend = _Backend()
    result = _run(monkeypatch, root, command, backend)
    assert result.status == "SUCCEEDED" and backend.calls == 1
    assert result.schema_version == "local-image-sdxl-native-lora-result/1.0"
    assert result.command_sha256 == command.command_sha256
    assert result.adapter_manifest.activation_policy == "FORBIDDEN"
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert runner.load_sdxl_native_lora_command(root, root / "command.json") == command
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(runner, "_tensor_samples", lambda *_a: pytest.fail("replay materialized"))
    monkeypatch.setattr(
        runner, "resolve_sdxl_stack", lambda *_a: pytest.fail("replay opened model")
    )
    assert _run_without_patch(root, command, backend) == result
    assert backend.calls == 1
    assert all(p.read_bytes() == raw for p, raw in after.items())


def _run_without_patch(root, command, backend):
    return runner.run_sdxl_native_lora_command(
        workspace=root,
        command=command,
        backend=backend,
        model_store_root=Path("/fixture/model-store"),
    )


@pytest.mark.parametrize("raw", [b"[]", b"null", b"1", b"{", b'{"schema_version":"unsupported"}'])
def test_loader_has_stable_malformed_command_error(tmp_path, raw):
    root = tmp_path / "malformed"
    root.mkdir(mode=0o700)
    _write(root / "command.json", raw)
    with pytest.raises(runner.SdxlNativeLoraRunnerError, match="IMAGE_TRAINING_DOCUMENT_INVALID"):
        runner.load_sdxl_native_lora_command(root, root / "command.json")


def test_successor_schema_is_canonical_pinned_and_in_release(monkeypatch):
    command, *_ = _fixture(monkeypatch, exterior_batch=True)
    assert (
        LocalImageSdxlNativeLoraCommandV2.model_validate_json(
            content_json_bytes(command.model_dump(mode="json"))
        )
        == command
    )
    repo = Path(__file__).resolve().parents[2]
    filename = "local-image-sdxl-native-lora-command-v2.schema.json"
    raw = (repo / "schemas/image-provider" / filename).read_bytes()
    assert (
        "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256["sdxl-native-lora-command-v2"]
    )
    assert (
        raw
        == (repo / "packages/image_contracts/eom_image_contracts/schemas" / filename).read_bytes()
    )
    assert filename in (repo / "scripts/image_trainer/build_release.sh").read_text()


def test_released_evaluation_does_not_guess_successor_training_version():
    command, _ = _evaluation_fixture()
    value = command.model_dump(mode="json")
    value["evaluation"]["training_command"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-native-lora-command/1.1"
    )
    with pytest.raises(ValidationError, match="metadata pointer contract mismatch"):
        LocalImageSdxlNativeEvaluationCommand.model_validate(value)


def test_successor_numerical_adapter_preserves_native_recipe(monkeypatch, tmp_path):
    command, *_ = _fixture(monkeypatch, exterior_batch=True)
    samples = tuple(
        numerical.LoraTensorSample(
            s.training_caption_en, tmp_path / s.staged_member_path, *s.width_height
        )
        for s in command.training_samples
    )
    stack = SimpleNamespace(
        manifest=command.base_model,
        component_roots={"BASE": tmp_path / "base", "VAE": tmp_path / "vae"},
    )
    captured = {}
    sentinel = object()

    def train(_self, **kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(numerical.DiffusersUnetLoraBackend, "train", train)
    assert (
        SdxlNativeLoraBackend().train(
            stack=stack, samples=samples, command=command, output_root=tmp_path / "adapter"
        )
        is sentinel
    )
    assert captured["samples"] == samples and captured["checkpoint_policy"] is None
    assert captured["recipe"] == numerical.LoraTrainingRecipe(
        command.dependencies, command.hyperparameters, command.seed
    )
    assert captured["vae_source"] == numerical.VaeWeightLocation(tmp_path / "vae", None, None)
