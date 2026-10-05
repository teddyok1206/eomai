"""An explicit control-window factor, with unchanged legacy recipes and commit owner."""

from __future__ import annotations

import copy
import hashlib
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_lineart_probe import LocalImageSdxlLineartProbeCommand
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStyleControlWindowPlan,
    SdxlPhotoStyleControlWindow,
    parse_photo_style_plan_value,
    photo_style_control_parameters,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleControlWindowCommand,
    LocalImageSdxlPhotoStyleControlWindowResult,
    parse_photo_style_command,
    parse_photo_style_plan,
    parse_photo_style_result,
    validate_photo_style_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_canny_backend as backend_module
from eom_image_provider import sdxl_photo_style as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit import test_sdxl_photo_style_execution as legacy
from tests.unit import test_sdxl_photo_style_full_denoising as full
from tests.unit import test_sdxl_photo_style_white_initializer as white
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_learned_comparison import _Backend


def _fixture(tmp_path, monkeypatch):
    old, reader, events, _ = full._fixture(tmp_path, monkeypatch)
    prior = parse_photo_style_plan(old, reader.records[old.plan])
    value = prior.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-photo-style-plan/1.3",
        control_window=dict(
            conditioning_scale=1.0,
            guidance_start=0.0,
            guidance_end=0.65,
            resource_profile="ALL_GPU_FP16_NO_OFFLOAD",
        ),
    )
    plan = parse_photo_style_plan_value(white._plan_seal(value))
    raw = content_json_bytes(plan.model_dump(mode="json"))
    pin = ImageEvaluationArtifactMember.model_validate(
        {
            **old.plan.model_dump(mode="json"),
            "artifact_revision_id": "rev_" + "3" * 32,
            "schema_ref": "eom://schemas/image-provider/" + plan.schema_version,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    reader.records[pin] = raw
    body = old.model_dump(mode="json")
    body.update(
        schema_version="local-image-sdxl-photo-style-command/1.3",
        plan=pin.model_dump(mode="json"),
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
    )
    return parse_photo_style_command(legacy._seal(body)), reader, events, prior


def _stage(tmp_path, monkeypatch):
    def fixture(path, patch):
        command, reader, events, _ = _fixture(path, patch)
        return command, reader, events

    monkeypatch.setattr(legacy, "_fixture", fixture)
    return legacy._stage(tmp_path, monkeypatch)


def test_closed_schema_resources_identity_and_original_full_control(tmp_path, monkeypatch):
    command, reader, _, prior = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    assert isinstance(plan, LocalImageSdxlPhotoStyleControlWindowPlan)
    assert isinstance(command, LocalImageSdxlPhotoStyleControlWindowCommand)
    assert plan.initialization == prior.initialization and plan.cases == prior.cases
    assert plan.seed == prior.seed and plan.configuration_anchor == prior.configuration_anchor
    assert plan.budget == prior.budget
    inherited = SdxlCannyControlParameters()
    assert photo_style_control_parameters(prior, inherited) is inherited
    assert photo_style_control_parameters(plan, inherited) is plan.control_window
    assert plan.control_window.model_dump(exclude={"guidance_end"}) == inherited.model_dump(
        exclude={"guidance_end"}
    )
    root = Path(__file__).resolve().parents[2]
    for family in ("plan", "command", "result"):
        for suffix in ("", "-v2", "-v3", "-v4"):
            key = "sdxl-photo-style-" + family + suffix
            name = SCHEMA_FILES[key]
            raw = (root / "schemas/image-provider" / name).read_bytes()
            assert (
                raw
                == (
                    root / "packages/image_contracts/eom_image_contracts/schemas" / name
                ).read_bytes()
            )
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[key]
    assert SCHEMA_SHA256["sdxl-photo-style-plan-v3"] == (
        "sha256:cddf2fabadcf4490b3559dd640df2eea1247e4e5831e7955f6c3be22c49ee7a4"
    )
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    for obj, commit in (
        (plan, publisher.commit_sdxl_photo_style_plan),
        (command, publisher.commit_sdxl_photo_style_command),
    ):
        pin = commit(obj)
        assert pin.schema_ref == "eom://schemas/image-provider/" + obj.schema_version
        assert (
            pin.sha256
            == "sha256:"
            + hashlib.sha256(content_json_bytes(obj.model_dump(mode="json"))).hexdigest()
        )


@pytest.mark.parametrize("end", [0.25, 0.65, 1.0])
def test_declared_window_range_is_not_an_automatic_runtime_search(end):
    window = SdxlPhotoStyleControlWindow(guidance_end=end)
    assert window.guidance_end == end and window.conditioning_scale == 1.0
    with pytest.raises(ValidationError):
        window.guidance_end = 0.5
    with pytest.raises(ValidationError):
        SdxlCannyControlParameters(guidance_end=0.65)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "lower",
        "upper",
        "bool",
        "string",
        "scale",
        "start",
        "profile",
        "extra",
        "family",
        "initializer",
        "activation",
        "retry",
    ],
)
def test_invalid_or_undeclared_control_factor_rejected(tmp_path, monkeypatch, fault):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    value = parse_photo_style_plan(command, reader.records[command.plan]).model_dump(mode="json")
    window = value["control_window"]
    if fault == "missing":
        del value["control_window"]
    elif fault in {"lower", "upper", "bool", "string"}:
        window["guidance_end"] = {"lower": 0.0, "upper": 1.1, "bool": True, "string": "0.65"}[fault]
    elif fault == "scale":
        window["conditioning_scale"] = 0.65
    elif fault == "start":
        window["guidance_start"] = 0.1
    elif fault == "profile":
        window["resource_profile"] = "AUTO_OFFLOAD"
    elif fault == "extra":
        window["automatic_search"] = True
    elif fault == "family":
        value["schema_version"] = "local-image-sdxl-photo-style-plan/1.2"
    elif fault == "initializer":
        value["initialization"]["denoising_strength"] = 0.7
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    else:
        value["budget"]["automatic_retry"] = True
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parse_photo_style_plan_value(white._plan_seal(value))


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2", "9.9"])
def test_cross_version_pointer_is_not_implicitly_upgraded(tmp_path, monkeypatch, version):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    value["plan"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-photo-style-plan/" + version
    )
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parse_photo_style_command(legacy._seal(value))


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_window_reaches_existing_pair_result_and_readonly_terminal_replay(
    tmp_path, monkeypatch, fault
):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    backend = _Backend(fault=fault)
    observed = []

    def factory(controller, control, initialization, inputs):
        assert isinstance(control, SdxlPhotoStyleControlWindow)
        assert control.guidance_end == 0.65 and control.guidance_start == 0.0
        assert initialization.denoising_strength == 1.0
        assert all(v.canvas_rgb == bytes([255]) * (832 * 512 * 3) for v in inputs.values())
        observed.append(control)
        return backend

    result = worker.run_sdxl_photo_style(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend_factory=factory,
    )
    assert isinstance(result, LocalImageSdxlPhotoStyleControlWindowResult)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert result.control_window == prepared.metadata.sources.plan.control_window
    assert len(result.outputs) == {None: 2, "second": 1, "oom": 0, "unexpected": 0}[fault]
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


@pytest.mark.parametrize("fault", ["window", "missing", "family", "source", "quality"])
def test_resealed_result_cannot_change_declared_window_or_lineage(tmp_path, monkeypatch, fault):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    value = copy.deepcopy(result.model_dump(mode="json", exclude={"result_sha256"}))
    if fault == "window":
        value["control_window"]["guidance_end"] = 0.75
    elif fault == "missing":
        del value["control_window"]
    elif fault == "family":
        value["schema_version"] = "local-image-sdxl-photo-style-result/1.2"
    elif fault == "source":
        value["inputs"][0]["source_sha256"] = "sha256:" + "0" * 64
    else:
        value["quality_acceptance"] = "PASS"
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parsed = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
        validate_photo_style_result(prepared.command, prepared.metadata.sources, parsed)


def test_actual_shared_pipeline_receives_declared_control_end(monkeypatch):
    import numpy as np

    from tests.unit.test_sdxl_lineart_probe import _command

    command = LocalImageSdxlLineartProbeCommand.model_validate(_command())
    calls = []

    class Tokenizer:
        model_max_length = 77

        def __call__(self, prompt, **kwargs):
            return {"input_ids": [1, 2, 3]}

    class Pipeline:
        tokenizer = Tokenizer()
        tokenizer_2 = Tokenizer()

        def __call__(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(images=np.ones((1, 512, 832, 3), dtype=np.float32))

    cuda = SimpleNamespace(
        synchronize=lambda device: None,
        get_device_capability=lambda device: (12, 0),
        get_device_name=lambda device: "test GPU",
        max_memory_allocated=lambda device: 128,
    )
    torch = SimpleNamespace(
        Generator=lambda **kwargs: SimpleNamespace(manual_seed=lambda seed: seed),
        cuda=cuda,
        version=SimpleNamespace(cuda="12.8"),
        __version__="2.7.1+cu128",
        OutOfMemoryError=RuntimeError,
    )
    monkeypatch.setattr(
        backend_module.metadata,
        "version",
        lambda name: "0.35.2" if name == "diffusers" else "4.56.2",
    )
    backend_module.generate_sdxl_canny_background(
        Pipeline(),
        torch,
        SdxlPhotoStyleControlWindow(guidance_end=0.65),
        image_arguments={"image": object()},
        prompt="black ink",
        negative_prompt="gray pencil",
        seed=104729,
        command=command,
    )
    assert len(calls) == 1
    assert calls[0]["controlnet_conditioning_scale"] == 1.0
    assert calls[0]["control_guidance_start"] == 0.0
    assert calls[0]["control_guidance_end"] == 0.65


def test_cpu_verifier_is_readonly_and_uses_same_pixel_owner(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert worker.verify_sdxl_photo_style_transforms(root) == result
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fault", [None, "pointer", "transform"])
def test_publication_still_has_one_validated_commit_owner(tmp_path, monkeypatch, fault):
    from scripts.image_trainer import sdxl_validation_publication as publication

    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pin = prepared.command.plan.model_copy(
        update={
            "member_path": "manifests/sdxl-photo-style-command.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-photo-style-command/"
            + ("1.2" if fault == "pointer" else "1.3"),
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    monkeypatch.setattr(publication, "resolve_control_artifact_member", lambda *args, **kwargs: raw)
    monkeypatch.setattr(publication, "prepare_sdxl_photo_style_inputs", lambda *args: prepared)
    events = []

    def verify(workspace, expected):
        events.append("CPU")
        if fault == "transform":
            raise ValueError("invalid transforms")
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
            events.append("COMMIT")
            assert kwargs["manifest_version"] == "sdxl-photo-style-result-artifact/1.3"
            assert len(kwargs["members"]) == 7
            return kwargs

    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)

    def call():
        return publication.publish_sdxl_photo_style_comparison(
            object(),
            prepared.command,
            command_pointer=pin,
            workspace=root,
            worker_uid=os.getuid(),
            source_commit=prepared.command.source_commit,
            created_at=result.completed_at + timedelta(seconds=1),
        )

    if fault is None:
        call()
        assert events == ["CPU", "COMMIT"]
    else:
        with pytest.raises((ValueError, ProviderError)):
            call()
        assert "COMMIT" not in events
