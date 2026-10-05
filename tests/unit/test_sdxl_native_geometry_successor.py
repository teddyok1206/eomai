"""Explicit training1.1 consumer; synthetic inference does not establish image quality."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import ImageEvaluationArtifactMember, content_json_bytes, validate_contract
from eom_image_contracts.models import text_sha256
from eom_image_contracts.sdxl_evaluation_codec import (
    parse_sdxl_evaluation_command,
    parse_sdxl_evaluation_result,
)
from eom_image_contracts.sdxl_native_geometry import (
    LocalImageSdxlNativeGeometryCommand,
    LocalImageSdxlNativeGeometryCommandV2,
    validate_sdxl_native_geometry_result,
)
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommandV2,
    LocalImageSdxlNativeLoraResult,
    SdxlNativeLoraConditioning,
)
from eom_image_contracts.validation import SCHEMA_SHA256
from eom_image_provider import sdxl_native_geometry as worker
from eom_image_provider.provider import ProviderError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit import test_sdxl_native_evaluation as evaluation_tests
from tests.unit import test_sdxl_native_geometry as geometry_tests
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal
from tests.unit.test_sdxl_native_evaluation import _payloads, _prepare
from tests.unit.test_sdxl_native_geometry import _Backend, _geometry_fixture, _stage
from tests.unit.test_sdxl_native_lora_contracts import (
    _command_value,
    _result_value,
    _seal_command,
    _seal_result,
)
from tests.unit.test_sdxl_probe_inputs import _Reader


def _successor_fixture():
    old, records, sources = _geometry_fixture()
    value = sources.training_command.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-native-lora-command/1.1"
    training = LocalImageSdxlNativeLoraCommandV2.model_validate(_seal_command(value))
    result_value = _result_value(training)
    result_value["adapter_manifest"]["files"] = sources.manifest.model_dump(mode="json")["files"]
    result = LocalImageSdxlNativeLoraResult.model_validate(_seal_result(result_value))
    manifest = result.adapter_manifest
    value = old.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-lora-evaluation-command/1.4"
    pin = value["evaluation"]
    for field, model, family, version, identity in (
        ("training_command", training, "command", "1.1", "6"),
        ("training_result", result, "result", "1.0", "7"),
        ("adapter_manifest", manifest, "adapter-manifest", "1.0", "7"),
    ):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + identity * 32,
            artifact_revision_id="rev_" + identity * 32,
            member_path="manifests/sdxl-native-lora-" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-sdxl-native-lora-"
            + family
            + "/"
            + version,
            media_type="application/json",
            sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        )
        records[pointer] = raw
        pin[field] = pointer.model_dump(mode="json")
    pin.update(
        adapter_id=manifest.adapter_id,
        adapter_revision_id=manifest.adapter_revision_id,
        adapter_manifest_sha256=manifest.manifest_sha256,
    )
    for file in manifest.files:
        previous = next(p for p in records if p.member_path == "adapter/" + file.relative_path)
        pointer = previous.model_copy(
            update={
                "artifact_id": "artifact_" + "7" * 32,
                "artifact_revision_id": "rev_" + "7" * 32,
            }
        )
        records[pointer] = records[previous]
    command = LocalImageSdxlNativeGeometryCommandV2.model_validate(_seal(value))
    sources = worker.parse_sdxl_native_evaluation_sources(command, **_payloads(command, records))
    return command, records, sources


def test_successor_wire_metadata_admission_publication_and_resource_pins(monkeypatch):
    command, records, sources = _successor_fixture()
    assert parse_sdxl_evaluation_command(command.model_dump(mode="json")) == command
    assert sources.training_command.schema_version.endswith("/1.1")
    assert sources.training_result.schema_version.endswith("/1.0")
    prepared, reader = _prepare(monkeypatch, command, records)
    assert len(prepared.files) == 7 and prepared.manifest == sources.manifest
    assert not any(p.media_type == "image/png" for p in reader.calls)
    publisher = _Publisher()
    owner = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit=command.source_commit
    )
    pointer = owner.commit_sdxl_lora_evaluation_command(command)
    assert pointer.schema_ref.endswith("evaluation-command/1.4")
    repo = Path(__file__).resolve().parents[2]
    for family in ("command", "result"):
        name = "sdxl-lora-evaluation-" + family + "-v5"
        filename = "local-image-" + name + ".schema.json"
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[name]
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        for script in ("image_provider", "image_trainer"):
            assert filename in (repo / "scripts" / script / "build_release.sh").read_text()


@pytest.mark.parametrize(
    "field,version",
    [
        ("training_command", "1.0"),
        ("training_command", "99.0"),
        ("training_result", "1.1"),
        ("adapter_manifest", "1.1"),
        ("baseline_command", "1.1"),
    ],
)
def test_successor_schema_and_model_reject_crossed_role_versions(field, version):
    command, *_ = _successor_fixture()
    value = command.model_dump(mode="json")
    previous = value["evaluation"][field]["schema_ref"]
    value["evaluation"][field]["schema_ref"] = previous.rsplit("/", 1)[0] + "/" + version
    with pytest.raises(SchemaError):
        validate_contract("sdxl-lora-evaluation-command-v5", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeGeometryCommandV2.model_validate(_seal(value))


def test_released_geometry_cannot_alias_successor():
    command, *_ = _successor_fixture()
    value = command.model_dump(mode="json")
    with pytest.raises(SchemaError):
        validate_contract("sdxl-lora-evaluation-command-v4", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeGeometryCommand.model_validate(value)


@pytest.mark.parametrize("fault", [None, "second", "unknown", "shape", "memory"])
def test_successor_actual_executor_failure_and_no_side_effect_replay(monkeypatch, tmp_path, fault):
    monkeypatch.setattr(geometry_tests, "_geometry_fixture", _successor_fixture)
    prepared, sources = _stage(monkeypatch, tmp_path)
    backend = _Backend(sources, fault)
    result = worker.run_sdxl_native_geometry(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused.lock",
        backend=backend,
    )
    assert result.schema_version.endswith("/1.4")
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert len(result.outputs) == (8 if fault is None else 1 if fault == "second" else 0)
    assert result.generation_calls == len(backend.calls)
    assert parse_sdxl_evaluation_result(result.model_dump(mode="json")) == result
    validate_sdxl_native_geometry_result(prepared.command, sources, result)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    for name in (
        "resolve_sdxl_stack",
        "acquire_gpu_lease",
        "load_sdxl_lora_material",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, lambda *_a, **_kw: pytest.fail("replay side effect"))
    replay = worker.run_sdxl_native_geometry(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused.lock",
        backend=backend,
    )
    assert replay == result and before == {p: p.read_bytes() for p in before}


@pytest.mark.parametrize("fault", ["training_hash", "command_schema", "result_schema"])
def test_successor_preflight_failure_never_opens_model(monkeypatch, tmp_path, fault):
    monkeypatch.setattr(geometry_tests, "_geometry_fixture", _successor_fixture)
    prepared, _ = _stage(monkeypatch, tmp_path)
    if fault == "training_hash":
        path = tmp_path / "inputs/training-command.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        command = prepared.command.model_dump(mode="json")
        field = "training_command" if fault == "command_schema" else "training_result"
        command["evaluation"][field]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-sdxl-native-lora-"
            + ("command/1.0" if fault == "command_schema" else "result/1.1")
        )
    monkeypatch.setattr(
        worker, "resolve_sdxl_stack", lambda *_a, **_kw: pytest.fail("model opened")
    )
    if fault != "training_hash":
        with pytest.raises((ValueError, ValidationError, SchemaError)):
            parse_sdxl_evaluation_command(command)
    else:
        with pytest.raises(ProviderError):
            worker.run_sdxl_native_geometry(
                command=prepared.command,
                workspace=tmp_path,
                model_store_root=tmp_path,
                gpu_lock=tmp_path / "unused.lock",
                backend=_Backend(None),
            )


@pytest.mark.parametrize("fault", ["lineage", "basis"])
def test_successor_source_rejection_precedes_adapter_bytes(monkeypatch, fault):
    command, records, _ = _successor_fixture()
    readers = []

    def reader_factory(value):
        reader = _Reader(value)
        readers.append(reader)
        return reader

    monkeypatch.setattr(evaluation_tests, "_Reader", reader_factory)
    with pytest.raises(ValueError):
        _prepare(monkeypatch, command, records, fault=fault)
    assert readers and all(
        p.media_type == "application/json" and not p.member_path.startswith("adapter/")
        for reader in readers
        for p in reader.calls
    )


def test_training_result_from_another_command_cannot_be_rebound_by_rehashing():
    command, records, sources = _successor_fixture()
    previous = command.evaluation.training_result
    value = sources.training_command.model_dump(mode="json")
    value["created_by"] = "different.operator"
    other_training = LocalImageSdxlNativeLoraCommandV2.model_validate(_seal_command(value))
    value = _result_value(other_training)
    value["adapter_manifest"]["files"] = sources.manifest.model_dump(mode="json")["files"]
    result = LocalImageSdxlNativeLoraResult.model_validate(_seal_result(value))
    raw = content_json_bytes(result.model_dump(mode="json"))
    pointer = previous.model_copy(update={"sha256": "sha256:" + hashlib.sha256(raw).hexdigest()})
    records[pointer] = raw
    value = command.model_dump(mode="json")
    value["evaluation"]["training_result"] = pointer.model_dump(mode="json")
    changed = LocalImageSdxlNativeGeometryCommandV2.model_validate(_seal(value))
    with pytest.raises(ValueError):
        worker.parse_sdxl_native_evaluation_sources(changed, **_payloads(changed, records))


def test_full200_maximum_caption_command_stays_within_evaluation_metadata_bound():
    value = _command_value(count=200, profile="FULL_STYLE_TRAINING")
    value["schema_version"] = "local-image-sdxl-native-lora-command/1.1"
    value["created_by"] = value["reviewed_by"] = "a" * 128
    for sample in value["training_samples"]:
        sample["conditioning"]["literal_subject"] = "a" * 256
        conditioning = SdxlNativeLoraConditioning.model_validate(sample["conditioning"])
        sample["training_caption_sha256"] = text_sha256(conditioning.training_caption_en)
    training = LocalImageSdxlNativeLoraCommandV2.model_validate(_seal_command(value))
    raw = content_json_bytes(training.model_dump(mode="json"))
    assert len(raw) == 258038 and len(raw) < 256 * 1024


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "extra", "schema", "order", "raw_geometry", "calls"]
)
def test_successor_corrupt_terminal_output_is_not_regenerated(monkeypatch, tmp_path, fault):
    monkeypatch.setattr(geometry_tests, "_geometry_fixture", _successor_fixture)
    geometry_tests.test_terminal_tampering_is_not_repaired_or_regenerated(
        monkeypatch, tmp_path, fault
    )


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED"])
def test_successor_uses_existing_workspace_and_cli_route(monkeypatch, tmp_path, capsys, outcome):
    monkeypatch.setattr(geometry_tests, "_geometry_fixture", _successor_fixture)
    geometry_tests.test_shared_workspace_and_cli_replay_do_not_need_gpu_lease(
        monkeypatch, tmp_path, capsys, outcome
    )
