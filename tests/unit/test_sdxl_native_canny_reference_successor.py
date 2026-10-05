"""Native1.1 source-initialized comparison uses the existing closed admission and worker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    LocalImageSdxlNativeCannyReferenceResultV2,
    native_reference_evaluation,
    parse_reference_command,
    parse_reference_result,
    validate_reference_result,
)
from eom_image_contracts.sdxl_native_geometry import LocalImageSdxlNativeGeometryCommandV2
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, validate_contract
from eom_image_provider import sdxl_canny_reference as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_canny_reference_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_canny_reference import _run, _seal, _sha
from tests.unit.test_sdxl_learned_comparison import _Backend as FakeBackend
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal as _seal_evaluation
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_canny_reference import _fixture as _native_reference_fixture
from tests.unit.test_sdxl_native_geometry_successor import _successor_fixture
from tests.unit.test_sdxl_probe_workspace import _operator


def _fixture(tmp_path, monkeypatch, *, lineage_fault=None):
    old, reader, trace, leases = _native_reference_fixture(
        tmp_path, monkeypatch, lineage_fault=lineage_fault
    )
    evaluation, records, _ = _successor_fixture()
    reader.records.update(records)
    raw = content_json_bytes(evaluation.model_dump(mode="json"))
    pin = old.native_evaluation_command.model_copy(
        update={
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-lora-evaluation-command/1.4",
            "sha256": _sha(raw),
        }
    )
    reader.records[pin] = raw
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-canny-reference-command/1.2",
        native_evaluation_command=pin.model_dump(mode="json"),
    )
    command = LocalImageSdxlNativeCannyReferenceCommandV2.model_validate(_seal(value))
    return command, reader, trace, leases


def _stage(tmp_path, monkeypatch):
    command, reader, trace, leases = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert trace == ["LINEAGE", "NATIVE_LINEAGE", "PIXELS", "PIXELS"]
    assert prepared.sources.native.training_command.schema_version.endswith("/1.1")
    assert prepared.sources.evaluation.schema_version.endswith("/1.4")
    root = tmp_path / "native-successor-reference"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    monkeypatch.setattr(worker, "resolve_sdxl_canny_controller", lambda *a, **k: object())
    monkeypatch.setattr(worker.metadata, "version", lambda name: "11.3.0")
    return prepared, root, reader, leases


def _resign_result(value):
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return value


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_successor_pair_exact_inputs_native_adapter_and_no_write_replay(
    tmp_path, monkeypatch, fault
):
    prepared, root, reader, leases = _stage(tmp_path, monkeypatch)
    loaded = []
    original_loader = worker.load_sdxl_lora_material

    def load_material(root, manifest, *, strength):
        loaded.append((manifest, strength))
        return original_loader(root, manifest, strength=strength)

    monkeypatch.setattr(worker, "load_sdxl_lora_material", load_material)
    result = _run(prepared, root, FakeBackend(fault))
    assert type(result) is LocalImageSdxlNativeCannyReferenceResultV2
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    validate_reference_result(prepared.command, prepared.sources, result)
    assert result.initialization == prepared.command.initialization
    assert result.native_evaluation_command_sha256 == prepared.sources.evaluation.command_sha256
    assert result.native_adapter_manifest_sha256 == prepared.sources.native.manifest.manifest_sha256
    assert loaded == [(prepared.sources.native.manifest, 1.0)]
    assert result.quality_acceptance == "NOT_REVIEWED"
    assert result.activation_policy == "FORBIDDEN"
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    assert admission.sdxl_canny_reference_input_hashes(prepared) == {
        file.member_path: file.sha256 for file in prepared.files
    }
    adapter_reads = [p for p in reader.calls if p.member_path.startswith("adapter/")]
    assert len(adapter_reads) == 2
    assert all(
        pin.artifact_revision_id
        == prepared.sources.evaluation.evaluation.training_result.artifact_revision_id
        for pin in adapter_reads
    )
    assert not any(
        file.member_path.startswith(("inputs/targets/", "inputs/metadata/"))
        for file in prepared.files
    )
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "sdxl_canny_source_canvas",
        "create_sdxl_pair_directories",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, lambda *a, **k: pytest.fail("replay side effect"))
    assert _run(prepared, root, FakeBackend()) == result
    assert leases == ["ENTER", "EXIT"]
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2", "1.3", "99.0"])
def test_successor_exact_evaluation_pin_schema_model_agreement(tmp_path, monkeypatch, version):
    command, _, trace, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    pin = value["native_evaluation_command"]
    pin["schema_ref"] = pin["schema_ref"].rsplit("/", 1)[0] + "/" + version
    value = _seal(value)
    with pytest.raises(SchemaError):
        validate_contract("sdxl-canny-reference-command-v3", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeCannyReferenceCommandV2.model_validate(value)
    assert "PIXELS" not in trace


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "noncanonical", "stale", "member", "media", "permission"]
)
def test_successor_pointer_error_before_media_without_latest_fallback(tmp_path, monkeypatch, fault):
    command, reader, trace, _ = _fixture(tmp_path, monkeypatch)
    pin = command.native_evaluation_command
    value = command.model_dump(mode="json")
    if fault == "missing":
        del reader.records[pin]
    elif fault == "hash":
        reader.records[pin] += b" "
    elif fault == "noncanonical":
        raw = json.dumps(json.loads(reader.records[pin]), indent=2).encode()
        new = pin.model_copy(update={"sha256": _sha(raw)})
        reader.records[new] = raw
        value["native_evaluation_command"] = new.model_dump(mode="json")
    elif fault == "stale":
        value["native_evaluation_command"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif fault == "member":
        value["native_evaluation_command"]["member_path"] = "manifests/wrong.json"
    elif fault == "media":
        value["native_evaluation_command"]["media_type"] = "image/png"
    else:
        original = admission.resolve_control_artifact_member

        def denied(engine, pointer, **kwargs):
            if pointer == pin:
                raise PermissionError("denied")
            return original(engine, pointer, **kwargs)

        monkeypatch.setattr(admission, "resolve_control_artifact_member", denied)
    with pytest.raises((ValueError, KeyError, RuntimeError, SchemaError, PermissionError)):
        command = parse_reference_command(_seal(value))
        admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert "PIXELS" not in trace


@pytest.mark.parametrize("fault", ["caption", "canvas", "negative", "sample", "training_pin"])
def test_successor_validates_geometry_provenance_before_pixels(tmp_path, monkeypatch, fault):
    command, reader, trace, _ = _fixture(tmp_path, monkeypatch)
    pin = command.native_evaluation_command
    value = json.loads(reader.records[pin])
    if fault == "caption":
        value["cases"][0]["training_caption_sha256"] = "sha256:" + "0" * 64
    elif fault == "canvas":
        current = value["cases"][0]["native_canvas"]
        value["cases"][0]["native_canvas"] = (
            "SQUARE_1024" if current != "SQUARE_1024" else "PORTRAIT_768X1024"
        )
    elif fault == "negative":
        value["negative_prompt_sha256"] = "sha256:" + "0" * 64
    elif fault == "sample":
        value["cases"][0]["sample_id"] = "imgsourcecrop_" + "0" * 32
    else:
        value["evaluation"]["training_command"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-sdxl-native-lora-command/1.0"
        )
    raw = content_json_bytes(_seal_evaluation(value))
    new = pin.model_copy(update={"sha256": _sha(raw)})
    reader.records[new] = raw
    value = command.model_dump(mode="json")
    value["native_evaluation_command"] = new.model_dump(mode="json")
    with pytest.raises((ValueError, SchemaError)):
        command = parse_reference_command(_seal(value))
        admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert "PIXELS" not in trace


@pytest.mark.parametrize("fault", ["missing", "basis"])
def test_successor_full_native_closure_before_media(tmp_path, monkeypatch, fault):
    command, _, trace, _ = _fixture(tmp_path, monkeypatch, lineage_fault=fault)
    with pytest.raises(ValueError):
        admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert "PIXELS" not in trace


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_successor_rejects_rehashed_crossed_result_family(tmp_path, monkeypatch, version):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    value = _run(prepared, root, FakeBackend()).model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-canny-reference-result/" + version
    if version == "1.0":
        for field in (
            "case_relation",
            "native_evaluation_command_sha256",
            "native_adapter_manifest_sha256",
        ):
            del value[field]
    result = parse_reference_result(_resign_result(value))
    with pytest.raises(ValueError, match="family"):
        validate_reference_result(prepared.command, prepared.sources, result)


@pytest.mark.parametrize(
    "field", ["native_evaluation_command_sha256", "native_adapter_manifest_sha256"]
)
def test_successor_rejects_rehashed_wrong_identity(tmp_path, monkeypatch, field):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    value = _run(prepared, root, FakeBackend()).model_dump(mode="json")
    value[field] = "sha256:" + "0" * 64
    result = parse_reference_result(_resign_result(value))
    with pytest.raises(ValueError, match="adapter identity"):
        validate_reference_result(prepared.command, prepared.sources, result)


def test_successor_handoff_publication_packaging_and_preserved_schema_hashes(tmp_path, monkeypatch):
    prepared, _, reader, _ = _stage(tmp_path, monkeypatch)
    command = prepared.command
    assert parse_reference_command(command.model_dump(mode="json")) == command
    assert isinstance(
        native_reference_evaluation(command, reader.records[command.native_evaluation_command]),
        LocalImageSdxlNativeGeometryCommandV2,
    )
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_canny_reference_inputs(
        prepared, workspace_parent=parent, worker=owner
    )
    assert staged.systemd_unit.startswith("eom-image-sdxl-learned-comparison@")
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_canny_reference_inputs(prepared, workspace_parent=parent, worker=owner)
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    assert publisher.commit_sdxl_canny_reference_command(command).schema_ref.endswith("/1.2")
    for name in ("sdxl-canny-reference-command", "sdxl-canny-reference-command-v2"):
        with pytest.raises(SchemaError):
            validate_contract(name, command.model_dump(mode="json"))
    repo = Path(__file__).resolve().parents[2]
    for family in ("command", "result"):
        name = "sdxl-canny-reference-" + family + "-v3"
        filename = SCHEMA_FILES[name]
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        Draft202012Validator.check_schema(json.loads(raw))
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[name]
        for script in ("image_provider", "image_trainer"):
            assert filename in (repo / "scripts" / script / "build_release.sh").read_text()
    for name, expected in (
        (
            "sdxl-canny-reference-command",
            "7f9e33c0e91e614b781227bae3b086e5cf9f64e4987c1b8415f9d0dc4ce8cda4",
        ),
        (
            "sdxl-canny-reference-result",
            "7f66e5633422784dbd1f0d717713b3d12134405c263b2fcc5852ccec6cd82e5e",
        ),
        (
            "sdxl-canny-reference-command-v2",
            "de0ecc73b97755ecfd3ae8d07edd167b9682ccb96fc8b744e93dc2ce269de25b",
        ),
        (
            "sdxl-canny-reference-result-v2",
            "6a5f53168cdda1de73c13d46c16895b4cb1611b827daf32f1bd065220d4d9213",
        ),
    ):
        raw = (repo / "schemas/image-provider" / SCHEMA_FILES[name]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        assert SCHEMA_SHA256[name] == "sha256:" + expected


def test_successor_staged_metadata_tamper_before_model(tmp_path, monkeypatch):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    (root / "inputs/native-training-command.json").write_bytes(b"{}")
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("model reached"))
    with pytest.raises(ProviderError):
        _run(prepared, root, FakeBackend())


def test_released_native_command_cannot_reinterpret_successor_lineage(tmp_path, monkeypatch):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-canny-reference-command/1.1"
    with pytest.raises(ValueError, match="explicit native evaluation lineage"):
        parse_reference_command(_seal(value))


def test_released_native_result_cannot_accept_successor_wire(tmp_path, monkeypatch):
    from tests.unit.test_sdxl_native_canny_reference import _stage as _old_stage

    prepared, root, _, _ = _old_stage(tmp_path, monkeypatch)
    value = _run(prepared, root, FakeBackend()).model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-canny-reference-result/1.2"
    result = parse_reference_result(_resign_result(value))
    with pytest.raises(ValueError, match="family"):
        validate_reference_result(prepared.command, prepared.sources, result)
