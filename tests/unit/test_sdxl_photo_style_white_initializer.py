"""Constant-white successor keeps licensed source authority and historical photo replay."""

from __future__ import annotations

import copy
import hashlib
import io
import os
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_photo_style import (
    SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256,
    LocalImageSdxlPhotoStyleWhitePlan,
    SdxlPhotoStyleWhiteInitialization,
    parse_photo_style_plan_value,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleWhiteCommand,
    LocalImageSdxlPhotoStyleWhiteResult,
    parse_photo_style_command,
    parse_photo_style_plan,
    parse_photo_style_result,
    validate_photo_style_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_photo_style as worker
from eom_image_provider import sdxl_reference_pixels as pixels
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_photo_style_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import ValidationError as SchemaError
from PIL import Image
from pydantic import ValidationError

from tests.unit import test_sdxl_photo_style_execution as legacy
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_learned_comparison import _Backend
from tests.unit.test_sdxl_micro_runner import _write

_OLD_FIXTURE = legacy._fixture


def _plan_seal(value):
    value = copy.deepcopy(value)
    value.pop("plan_id", None)
    value.pop("plan_sha256", None)
    value["plan_id"] = "imgsdxlphotoplan_" + content_sha256(value)[7:39]
    value["plan_sha256"] = content_sha256(value)
    return value


def _fixture(tmp_path, monkeypatch):
    old, reader, events = _OLD_FIXTURE(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(old, reader.records[old.plan])
    value = plan.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-photo-style-plan/1.1"
    value["initialization"]["policy"] = "CONSTANT_WHITE_RGB_832X512/1.0"
    white = parse_photo_style_plan_value(_plan_seal(value))
    raw = content_json_bytes(white.model_dump(mode="json"))
    pointer = ImageEvaluationArtifactMember.model_validate(
        {
            **old.plan.model_dump(mode="json"),
            "artifact_revision_id": "rev_" + "1" * 32,
            "schema_ref": "eom://schemas/image-provider/" + white.schema_version,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    reader.records[pointer] = raw
    body = old.model_dump(mode="json")
    body.update(
        schema_version="local-image-sdxl-photo-style-command/1.1",
        plan=pointer.model_dump(mode="json"),
        plan_id=white.plan_id,
        plan_sha256=white.plan_sha256,
    )
    return parse_photo_style_command(legacy._seal(body)), reader, events


def _stage(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "_fixture", _fixture)
    return legacy._stage(tmp_path, monkeypatch)


def test_successor_schema_bytes_and_canonical_pointer_publication(tmp_path, monkeypatch):
    command, reader, _ = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    assert isinstance(command, LocalImageSdxlPhotoStyleWhiteCommand)
    assert isinstance(plan, LocalImageSdxlPhotoStyleWhitePlan)
    root = Path(__file__).resolve().parents[2]
    for family in ("plan", "command", "result"):
        for suffix in ("", "-v2"):
            key = "sdxl-photo-style-" + family + suffix
            raw = (root / "schemas/image-provider" / SCHEMA_FILES[key]).read_bytes()
            assert (
                raw
                == (
                    root
                    / "packages/image_contracts/eom_image_contracts/schemas"
                    / SCHEMA_FILES[key]
                ).read_bytes()
            )
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[key]
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    for value, commit in (
        (plan, publisher.commit_sdxl_photo_style_plan),
        (command, publisher.commit_sdxl_photo_style_command),
    ):
        pin = commit(value)
        assert pin.schema_ref == "eom://schemas/image-provider/" + value.schema_version
        assert (
            pin.sha256
            == "sha256:"
            + hashlib.sha256(content_json_bytes(value.model_dump(mode="json"))).hexdigest()
        )


@pytest.mark.parametrize("fault", ["policy", "strength", "steps", "version", "extra", "duplicate"])
def test_white_plan_is_closed_without_reinterpreting_old_recipe(tmp_path, monkeypatch, fault):
    command, reader, _ = _fixture(tmp_path, monkeypatch)
    value = parse_photo_style_plan(command, reader.records[command.plan]).model_dump(mode="json")
    if fault == "policy":
        value["initialization"]["policy"] = "FIT_GRAYSCALE_WHITE_RGB_832X512/1.0"
    if fault == "strength":
        value["initialization"]["denoising_strength"] = 0.8
    if fault == "steps":
        value["initialization"]["effective_denoising_steps"] = 30
    if fault == "version":
        value["schema_version"] = "local-image-sdxl-photo-style-plan/9.9"
    if fault == "extra":
        value["allow_activation"] = True
    if fault == "duplicate":
        value["cases"] *= 2
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parse_photo_style_plan_value(_plan_seal(value))


@pytest.mark.parametrize("version", ["1.0", "9.9"])
def test_cross_version_plan_pointer_and_unknown_command_rejected(tmp_path, monkeypatch, version):
    command, _, _ = _fixture(tmp_path, monkeypatch)
    body = command.model_dump(mode="json")
    body["schema_version"] = "local-image-sdxl-photo-style-command/" + version
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parse_photo_style_command(legacy._seal(body))


def test_constant_initializer_does_not_copy_photo_tone_and_gray_default_preserved():
    policy = SdxlPhotoStyleWhiteInitialization(
        policy="CONSTANT_WHITE_RGB_832X512/1.0",
        denoising_strength=0.7,
        scheduler_steps=30,
        effective_denoising_steps=21,
        pillow_version="11.3.0",
    )
    black = Image.new("L", (832, 512), 0)
    white = pixels.sdxl_reference_initializer(black, initialization=policy)
    assert (
        white.mode == "RGB" and white.size == black.size and white.getextrema() == ((255, 255),) * 3
    )
    assert (
        "sha256:" + hashlib.sha256(white.tobytes()).hexdigest()
        == SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256
    )
    assert pixels.sdxl_reference_initializer(black).getextrema() == ((0, 0),) * 3
    with pytest.raises(ValueError, match="dimensions"):
        pixels.sdxl_reference_initializer(Image.new("L", (32, 32)), initialization=policy)
    with pytest.raises(ValueError, match="unsupported"):
        pixels.sdxl_reference_initializer(black, initialization=object())


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_white_pair_measures_prefix_and_replays_without_transforms_models_writes(
    tmp_path, monkeypatch, fault
):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    backend = _Backend(fault=fault)
    observed = []

    def factory(controller, control, initialization, inputs):
        assert isinstance(initialization, SdxlPhotoStyleWhiteInitialization)
        assert (
            initialization.denoising_strength == 0.7
            and initialization.effective_denoising_steps == 21
        )
        assert all(v.canvas_rgb == bytes([255]) * (832 * 512 * 3) for v in inputs.values())
        observed.append(inputs)
        return backend

    result = worker.run_sdxl_photo_style(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend_factory=factory,
    )
    assert isinstance(result, LocalImageSdxlPhotoStyleWhiteResult)
    assert all(
        trace.initialization_rgb_sha256 == SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256
        for trace in result.inputs
    )
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert len(observed) == 1 and leases == ["ENTER", "EXIT"]
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}

    def blocked(*args, **kwargs):
        raise AssertionError("REPLAY_SIDE_EFFECT")

    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "prepare_sdxl_reference_pixels",
        "create_sdxl_pair_directories",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, blocked)
    assert legacy._run(prepared, root, backend) == result
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("fault", ["white-hash", "policy", "family", "coverage", "activation"])
def test_rehashed_white_results_cannot_change_recipe_or_lineage(tmp_path, monkeypatch, fault):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    value = result.model_dump(mode="json", exclude={"result_sha256"})
    if fault == "white-hash":
        value["inputs"][0]["initialization_rgb_sha256"] = "sha256:" + "0" * 64
    if fault == "policy":
        value["initialization"]["policy"] = "FIT_GRAYSCALE_WHITE_RGB_832X512/1.0"
    if fault == "family":
        value["schema_version"] = "local-image-sdxl-photo-style-result/1.0"
    if fault == "coverage":
        value["outputs"] = value["outputs"][1:]
    if fault == "activation":
        value["activation_policy"] = "ALLOWED"
    with pytest.raises((ValueError, ValidationError, SchemaError)):
        parsed = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
        validate_photo_style_result(prepared.command, prepared.metadata.sources, parsed)


def test_white_cpu_transform_verifier_is_readonly_and_rejects_changed_initializer(
    tmp_path, monkeypatch
):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert worker.verify_sdxl_photo_style_transforms(root) == result
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        worker, "sdxl_reference_initializer", lambda *a, **k: Image.new("RGB", (832, 512), "black")
    )
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        worker.verify_sdxl_photo_style_transforms(root)


def test_nonwhite_staged_png_rejected_even_with_rehashed_result(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    out = io.BytesIO()
    Image.new("RGB", (832, 512), "gray").save(out, format="PNG")
    _write(root / "initializers" / (result.inputs[0].case_id + ".png"), out.getvalue())
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        legacy._run(prepared, root, _Backend())


def test_white_handoff_still_metadata_first_and_old_command_still_parses(tmp_path, monkeypatch):
    old_root, white_root = tmp_path / "old", tmp_path / "white"
    old_root.mkdir(mode=0o700)
    white_root.mkdir(mode=0o700)
    old, reader, _ = _OLD_FIXTURE(old_root, monkeypatch)
    assert parse_photo_style_command(old.model_dump(mode="json")) == old
    command, reader, _ = _fixture(white_root, monkeypatch)
    metadata = admission.resolve_sdxl_photo_style_execution_metadata(object(), command)
    assert all(pointer.media_type == "application/json" for pointer in reader.calls)
    assert metadata.sources.plan.initialization.policy == "CONSTANT_WHITE_RGB_832X512/1.0"


@pytest.mark.parametrize("fault", [None, "pointer-version", "canonical", "transform", "input"])
def test_successor_publication_uses_existing_commit_owner_and_exact_recipe(
    tmp_path, monkeypatch, fault
):
    from scripts.image_trainer import sdxl_validation_publication as publication

    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    command_raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pointer = prepared.command.plan.model_copy(
        update={
            "member_path": "manifests/sdxl-photo-style-command.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-photo-style-command/"
            + ("1.0" if fault == "pointer-version" else "1.1"),
            "sha256": "sha256:" + hashlib.sha256(command_raw).hexdigest(),
        }
    )
    events = []
    monkeypatch.setattr(publication, "resolve_control_artifact_member", lambda *a, **k: command_raw)

    def readmit(*args):
        events.append("CANONICAL_READMIT")
        if fault == "canonical":
            raise ValueError("canonical source invalid")
        return prepared

    def verify(workspace, expected):
        events.append("CPU_WHITE_TRANSFORMS")
        if fault == "transform":
            raise ValueError("white initializer invalid")
        assert (
            content_json_bytes(
                worker.verify_sdxl_photo_style_transforms(workspace).model_dump(mode="json")
            )
            == expected
        )

    class Publisher:
        def __init__(self, engine):
            pass

        def publish(self, **kwargs):
            events.append("ARTIFACT_COMMIT")
            assert len(kwargs["members"]) == 7
            assert kwargs["manifest_version"] == "sdxl-photo-style-result-artifact/1.1"
            primary = next(m for m in kwargs["members"] if m.file_name == kwargs["primary_file"])
            assert (
                primary.schema_ref
                == "eom://schemas/image-provider/local-image-sdxl-photo-style-result/1.1"
            )
            assert not any(m.file_name.startswith("inputs/") for m in kwargs["members"])
            return kwargs

    monkeypatch.setattr(publication, "prepare_sdxl_photo_style_inputs", readmit)
    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)
    if fault == "input":
        _write(root / prepared.metadata.sources.plan.cases[0].case.staged_member_path, b"broken")

    def call():
        return publication.publish_sdxl_photo_style_comparison(
            object(),
            prepared.command,
            command_pointer=pointer,
            workspace=root,
            worker_uid=os.getuid(),
            source_commit=prepared.command.source_commit,
            created_at=result.completed_at + timedelta(seconds=1),
        )

    if fault is None:
        call()
        assert events == ["CANONICAL_READMIT", "CPU_WHITE_TRANSFORMS", "ARTIFACT_COMMIT"]
    else:
        with pytest.raises((ValueError, ProviderError)):
            call()
        assert "ARTIFACT_COMMIT" not in events
