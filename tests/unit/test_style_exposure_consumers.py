"""Balanced adapters need exact successor consumers; synthetic evidence is not quality PASS."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import content_json_bytes, validate_contract
from eom_image_contracts.sdxl_evaluation_codec import (
    parse_sdxl_evaluation_command,
    parse_sdxl_evaluation_result,
)
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    LocalImageSdxlNativeCannyReferenceCommandV3,
    native_reference_evaluation,
    parse_reference_command,
    reference_protocol,
)
from eom_image_contracts.sdxl_native_geometry import (
    LocalImageSdxlNativeGeometryCommandV2,
    LocalImageSdxlNativeGeometryCommandV3,
    validate_sdxl_native_geometry_result,
)
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommandV3,
    LocalImageSdxlNativeLoraResult,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStyleBalancedExposurePlan,
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
    parse_photo_style_plan_value,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleBalancedExposureCommand,
    parse_photo_style_command,
    parse_photo_style_plan,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, load_schema
from eom_image_provider import sdxl_native_geometry as geometry_worker
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit import test_sdxl_native_geometry as geometry_tests
from tests.unit import test_sdxl_photo_style_execution as photo_tests
from tests.unit import test_sdxl_photo_style_white_initializer as white_tests
from tests.unit.test_native_style_exposure import _balanced_value
from tests.unit.test_sdxl_canny_reference import _seal as seal_reference
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal as seal_evaluation
from tests.unit.test_sdxl_native_canny_reference_successor import _fixture as reference_fixture
from tests.unit.test_sdxl_native_evaluation import _payloads, _prepare
from tests.unit.test_sdxl_native_geometry import _Backend
from tests.unit.test_sdxl_native_geometry_successor import _successor_fixture
from tests.unit.test_sdxl_native_lora_contracts import _result_value, _seal_result
from tests.unit.test_sdxl_photo_style_retained_region import _fixture as retained_photo_fixture


def _balanced_geometry_fixture():
    old, records, old_sources = _successor_fixture()
    training = LocalImageSdxlNativeLoraCommandV3.model_validate(_balanced_value())
    result_value = _result_value(training)
    result_value["adapter_manifest"]["files"] = old_sources.manifest.model_dump(mode="json")[
        "files"
    ]
    result = LocalImageSdxlNativeLoraResult.model_validate(_seal_result(result_value))
    manifest = result.adapter_manifest
    value = old.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-lora-evaluation-command/1.5"
    value["cases"] = [
        dict(
            sample_id=s.sample_id,
            native_canvas=s.canvas,
            training_caption_sha256=s.training_caption_sha256,
        )
        for s in training.training_samples[:2]
    ]
    pin = value["evaluation"]
    for field, model, version, identity in (
        ("training_command", training, "1.2", "d"),
        ("training_result", result, "1.0", "e"),
        ("adapter_manifest", manifest, "1.0", "e"),
    ):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = getattr(old.evaluation, field).model_copy(
            update={
                "artifact_id": "artifact_" + identity * 32,
                "artifact_revision_id": "rev_" + identity * 32,
                "schema_ref": getattr(old.evaluation, field).schema_ref.rsplit("/", 1)[0]
                + "/"
                + version,
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
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
                "artifact_id": "artifact_" + "e" * 32,
                "artifact_revision_id": "rev_" + "e" * 32,
            }
        )
        records[pointer] = records[previous]
    command = LocalImageSdxlNativeGeometryCommandV3.model_validate(seal_evaluation(value))
    sources = geometry_worker.parse_sdxl_native_evaluation_sources(
        command, **_payloads(command, records)
    )
    return command, records, sources


def _balanced_reference(tmp_path, monkeypatch):
    old, reader, trace, leases = reference_fixture(tmp_path, monkeypatch)
    evaluation, records, sources = _balanced_geometry_fixture()
    reader.records.update(records)
    raw = content_json_bytes(evaluation.model_dump(mode="json"))
    pin = old.native_evaluation_command.model_copy(
        update={
            "artifact_revision_id": "rev_" + "d" * 32,
            "schema_ref": "eom://schemas/image-provider/" + evaluation.schema_version,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    reader.records[pin] = raw
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-canny-reference-command/1.3",
        native_evaluation_command=pin.model_dump(mode="json"),
    )
    return parse_reference_command(seal_reference(value)), reader, sources, trace, leases


@pytest.mark.parametrize("fault", [None, "second", "unknown", "shape", "memory"])
def test_geometry_admission_real_executor_and_terminal_replay_use_exact_training12(
    monkeypatch, tmp_path, fault
):
    command, records, sources = _balanced_geometry_fixture()
    validate_contract("sdxl-lora-evaluation-command-v6", command.model_dump(mode="json"))
    assert parse_sdxl_evaluation_command(command.model_dump(mode="json")) == command
    assert len(sources.training_command.training_samples) == 100
    prepared, reader = _prepare(monkeypatch, command, records)
    assert len(prepared.files) == 7 and not any(p.media_type == "image/png" for p in reader.calls)
    monkeypatch.setattr(geometry_tests, "_geometry_fixture", _balanced_geometry_fixture)
    prepared, sources = geometry_tests._stage(monkeypatch, tmp_path)
    backend = _Backend(sources, fault)
    result = geometry_worker.run_sdxl_native_geometry(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused.lock",
        backend=backend,
    )
    assert result.schema_version.endswith("/1.5")
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    validate_sdxl_native_geometry_result(command, sources, result)
    assert parse_sdxl_evaluation_result(result.model_dump(mode="json")) == result
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    for name in (
        "resolve_sdxl_stack",
        "acquire_gpu_lease",
        "load_sdxl_lora_material",
        "write_staged_member",
    ):
        monkeypatch.setattr(
            geometry_worker, name, lambda *_a, **_kw: pytest.fail("replay side effect")
        )
    assert (
        geometry_worker.run_sdxl_native_geometry(
            command=command,
            workspace=tmp_path,
            model_store_root=tmp_path,
            gpu_lock=tmp_path / "unused.lock",
            backend=backend,
        )
        == result
    )
    assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in before}


@pytest.mark.parametrize("version", ["1.0", "1.1", "99.0"])
def test_training12_pin_rejects_crossed_versions_in_schema_and_model(version):
    command, *_ = _balanced_geometry_fixture()
    value = command.model_dump(mode="json")
    value["evaluation"]["training_command"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-native-lora-command/" + version
    )
    with pytest.raises(SchemaError):
        validate_contract("sdxl-lora-evaluation-command-v6", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeGeometryCommandV3.model_validate(seal_evaluation(value))


def test_previous_geometry_and_reference_contracts_cannot_alias_balanced_lineage(
    tmp_path, monkeypatch
):
    command, *_ = _balanced_geometry_fixture()
    value = command.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-lora-evaluation-command/1.4"
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeGeometryCommandV2.model_validate(seal_evaluation(value))
    reference, reader, *_ = _balanced_reference(tmp_path, monkeypatch)
    assert type(reference) is LocalImageSdxlNativeCannyReferenceCommandV3
    protocol = reference_protocol(reference)
    validate_contract(protocol.command_contract, reference.model_dump(mode="json"))
    assert (
        native_reference_evaluation(reference, reader.records[reference.native_evaluation_command])
        == command
    )
    value = reference.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-canny-reference-command/1.2"
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeCannyReferenceCommandV2.model_validate(seal_reference(value))


def test_photo_plan_and_command_use_new_anchor_but_identical_visual_recipe(tmp_path, monkeypatch):
    old, reader, _, _ = retained_photo_fixture(tmp_path, monkeypatch)
    prior = parse_photo_style_plan(old, reader.records[old.plan])
    reference_root = tmp_path / "separate-reference-fixture"
    reference_root.mkdir(mode=0o700)
    reference, _, *_ = _balanced_reference(reference_root, monkeypatch)
    raw = content_json_bytes(reference.model_dump(mode="json"))
    anchor = prior.configuration_anchor.model_copy(
        update={
            "artifact_revision_id": "rev_" + "d" * 32,
            "schema_ref": "eom://schemas/image-provider/" + reference.schema_version,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    value = prior.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-photo-style-plan/1.5",
        configuration_anchor=anchor.model_dump(mode="json"),
    )
    plan = parse_photo_style_plan_value(white_tests._plan_seal(value))
    assert type(plan) is LocalImageSdxlPhotoStyleBalancedExposurePlan
    assert plan.cases == prior.cases and plan.initialization == prior.initialization
    assert plan.control == prior.control and plan.region_reviews == prior.region_reviews
    assert plan.seed == prior.seed and plan.budget == prior.budget
    raw = content_json_bytes(plan.model_dump(mode="json"))
    pin = old.plan.model_copy(
        update={
            "schema_ref": "eom://schemas/image-provider/" + plan.schema_version,
            "artifact_revision_id": "rev_" + "d" * 32,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-photo-style-command/1.5",
        plan=pin.model_dump(mode="json"),
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
    )
    command = parse_photo_style_command(photo_tests._seal(value))
    assert type(command) is LocalImageSdxlPhotoStyleBalancedExposureCommand
    assert parse_photo_style_plan(command, raw) == plan
    value = plan.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-photo-style-plan/1.4"
    with pytest.raises(ValidationError):
        LocalImageSdxlPhotoStyleRetainedRegionPlan.model_validate(white_tests._plan_seal(value))
    with pytest.raises(SchemaError):
        validate_contract("sdxl-photo-style-plan-v5", value)


@pytest.mark.parametrize(
    "key",
    [
        "sdxl-lora-evaluation-command-v6",
        "sdxl-lora-evaluation-result-v6",
        "sdxl-canny-reference-command-v4",
        "sdxl-canny-reference-result-v4",
        "sdxl-photo-style-plan-v6",
        "sdxl-photo-style-command-v6",
        "sdxl-photo-style-result-v6",
    ],
)
def test_successor_schemas_are_wheel_owned_pinned_and_structurally_valid(key):
    Draft202012Validator.check_schema(load_schema(key))
    repo = Path(__file__).resolve().parents[2]
    filename = SCHEMA_FILES[key]
    raw = (repo / "schemas/image-provider" / filename).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[key]
    assert (
        raw
        == (repo / "packages/image_contracts/eom_image_contracts/schemas" / filename).read_bytes()
    )
    for script in ("image_provider", "image_trainer"):
        assert filename in (repo / "scripts" / script / "build_release.sh").read_text()
