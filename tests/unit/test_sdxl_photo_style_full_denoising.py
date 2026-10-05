"""Single numerical factor, not style acceptance or an implicit old-recipe upgrade."""

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
    SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256,
    LocalImageSdxlPhotoStyleFullDenoisingPlan,
    SdxlPhotoStyleFullDenoisingInitialization,
    parse_photo_style_plan_value,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleFullDenoisingCommand,
    LocalImageSdxlPhotoStyleFullDenoisingResult,
    parse_photo_style_command,
    parse_photo_style_plan,
    parse_photo_style_result,
    validate_photo_style_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_canny_reference_backend as reference_backend
from eom_image_provider import sdxl_photo_style as worker
from eom_image_provider import sdxl_reference_pixels as pixels
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import ValidationError as SchemaError
from PIL import Image
from pydantic import ValidationError

from tests.unit import test_sdxl_photo_style_execution as legacy
from tests.unit import test_sdxl_photo_style_white_initializer as white
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_learned_comparison import _Backend


def _fixture(tmp_path, monkeypatch):
    old, reader, events = white._fixture(tmp_path, monkeypatch)
    prior = parse_photo_style_plan(old, reader.records[old.plan])
    value = prior.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-photo-style-plan/1.2"
    value["initialization"].update(
        policy="CONSTANT_WHITE_RGB_832X512_FULL_DENOISE/1.0",
        denoising_strength=1.0,
        effective_denoising_steps=30,
    )
    plan = parse_photo_style_plan_value(white._plan_seal(value))
    raw = content_json_bytes(plan.model_dump(mode="json"))
    pin = ImageEvaluationArtifactMember.model_validate(
        {
            **old.plan.model_dump(mode="json"),
            "artifact_revision_id": "rev_" + "2" * 32,
            "schema_ref": "eom://schemas/image-provider/" + plan.schema_version,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    reader.records[pin] = raw
    body = old.model_dump(mode="json")
    body.update(
        schema_version="local-image-sdxl-photo-style-command/1.2",
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


def test_schema_bytes_old_family_preserved_and_new_pointers_canonical(tmp_path, monkeypatch):
    command, reader, _, prior = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    assert isinstance(plan, LocalImageSdxlPhotoStyleFullDenoisingPlan)
    assert isinstance(command, LocalImageSdxlPhotoStyleFullDenoisingCommand)
    assert plan.cases == prior.cases and plan.configuration_anchor == prior.configuration_anchor
    assert plan.seed == prior.seed and plan.budget == prior.budget
    assert plan.initialization.model_dump(
        exclude={"policy", "denoising_strength", "effective_denoising_steps"}
    ) == prior.initialization.model_dump(
        exclude={"policy", "denoising_strength", "effective_denoising_steps"}
    )
    root = Path(__file__).resolve().parents[2]
    for family in ("plan", "command", "result"):
        for suffix in ("", "-v2", "-v3"):
            key = "sdxl-photo-style-" + family + suffix
            filename = SCHEMA_FILES[key]
            raw = (root / "schemas/image-provider" / filename).read_bytes()
            assert (
                raw
                == (
                    root / "packages/image_contracts/eom_image_contracts/schemas" / filename
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


@pytest.mark.parametrize(
    "fault",
    [
        "policy",
        "strength",
        "string",
        "bool",
        "effective",
        "scheduled",
        "region",
        "activation",
        "retry",
        "family",
    ],
)
def test_new_plan_rejects_undeclared_factors(tmp_path, monkeypatch, fault):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    value = parse_photo_style_plan(command, reader.records[command.plan]).model_dump(mode="json")
    if fault == "policy":
        value["initialization"]["policy"] = "CONSTANT_WHITE_RGB_832X512/1.0"
    elif fault == "strength":
        value["initialization"]["denoising_strength"] = 0.7
    elif fault == "string":
        value["initialization"]["denoising_strength"] = "1.0"
    elif fault == "bool":
        value["initialization"]["denoising_strength"] = True
    elif fault == "effective":
        value["initialization"]["effective_denoising_steps"] = 21
    elif fault == "scheduled":
        value["initialization"]["scheduler_steps"] = 40
    elif fault == "region":
        value["retained_region"] = [0, 0, 832, 512]
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "retry":
        value["budget"]["automatic_retry"] = True
    else:
        value["schema_version"] = "local-image-sdxl-photo-style-plan/1.1"
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parse_photo_style_plan_value(white._plan_seal(value))


@pytest.mark.parametrize("version", ["1.0", "1.1", "9.9"])
def test_command_cannot_resolve_another_version_or_implicit_latest(tmp_path, monkeypatch, version):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    value["plan"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-photo-style-plan/" + version
    )
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parse_photo_style_command(legacy._seal(value))


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_single_factor_reaches_pair_and_terminal_replay_is_readonly(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    backend = _Backend(fault=fault)
    observed = []

    def factory(controller, control, initialization, inputs):
        assert isinstance(initialization, SdxlPhotoStyleFullDenoisingInitialization)
        assert initialization.denoising_strength == 1.0
        assert initialization.scheduler_steps == initialization.effective_denoising_steps == 30
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
    assert isinstance(result, LocalImageSdxlPhotoStyleFullDenoisingResult)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert len(result.outputs) == {None: 2, "second": 1, "oom": 0, "unexpected": 0}[fault]
    assert len(observed) == 1 and leases == ["ENTER", "EXIT"]
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    assert all(
        t.initialization_rgb_sha256 == SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256
        for t in result.inputs
    )
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}

    def forbidden(*a, **k):
        raise AssertionError("REPLAY_SIDE_EFFECT")

    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "prepare_sdxl_reference_pixels",
        "create_sdxl_pair_directories",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    assert legacy._run(prepared, root, backend) == result
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "fault", ["effective", "strength", "white-hash", "family", "source", "coverage", "quality"]
)
def test_rehashed_result_cannot_forge_recipe_lineage_or_quality(tmp_path, monkeypatch, fault):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    value = copy.deepcopy(result.model_dump(mode="json", exclude={"result_sha256"}))
    if fault == "effective":
        value["initialization"]["effective_denoising_steps"] = 21
    elif fault == "strength":
        value["initialization"]["denoising_strength"] = 0.7
    elif fault == "white-hash":
        value["inputs"][0]["initialization_rgb_sha256"] = "sha256:" + "0" * 64
    elif fault == "family":
        value["schema_version"] = "local-image-sdxl-photo-style-result/1.1"
    elif fault == "source":
        value["inputs"][0]["source_sha256"] = "sha256:" + "0" * 64
    elif fault == "coverage":
        value["outputs"] = value["outputs"][1:]
    else:
        value["quality_acceptance"] = "PASS"
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parsed = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
        validate_photo_style_result(prepared.command, prepared.metadata.sources, parsed)


def test_cpu_transform_verifier_uses_same_white_pixels_without_writes(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert worker.verify_sdxl_photo_style_transforms(root) == result
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    initialization = prepared.metadata.sources.plan.initialization
    white_canvas = pixels.sdxl_reference_initializer(
        Image.new("L", (832, 512), 0), initialization=initialization
    )
    assert (
        "sha256:" + hashlib.sha256(white_canvas.tobytes()).hexdigest()
        == SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256
    )


@pytest.mark.parametrize("observed_steps", [21, 30])
def test_real_backend_contract_receives_full_strength_and_checks_timesteps(
    monkeypatch, observed_steps
):
    from tests.unit.test_sdxl_lineart_probe import _command, _png

    value = _command()
    value["inference_steps"] = 30
    value["command_sha256"] = content_sha256(
        {key: entry for key, entry in value.items() if key != "command_sha256"}
    )
    command = LocalImageSdxlLineartProbeCommand.model_validate(value)
    source = _png(size=(800, 504))
    initializer = SdxlPhotoStyleFullDenoisingInitialization(
        policy="CONSTANT_WHITE_RGB_832X512_FULL_DENOISE/1.0",
        denoising_strength=1.0,
        scheduler_steps=30,
        effective_denoising_steps=30,
        pillow_version="11.3.0",
    )
    inputs = {
        "sha256:" + hashlib.sha256(source).hexdigest(): reference_backend.SdxlCannyReferencePixels(
            bytes([255]) * (832 * 512 * 3), _png(size=(832, 512))
        )
    }
    session = reference_backend.SdxlCannyReferenceSession(
        SimpleNamespace(num_timesteps=observed_steps),
        object(),
        SdxlCannyControlParameters(),
        initializer,
        inputs,
    )
    calls = []
    marker = object()

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return marker

    monkeypatch.setattr(reference_backend, "generate_sdxl_canny_background", generate)

    def call():
        return session.generate(
            conditioning=source,
            prompt="line art",
            negative_prompt="color",
            seed=104729,
            command=command,
        )

    if observed_steps == 30:
        assert call() is marker
    else:
        with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
            call()
    assert len(calls) == 1 and calls[0]["image_arguments"]["strength"] == 1.0
    assert calls[0]["image_arguments"]["image"].tobytes() == bytes([255]) * (832 * 512 * 3)


@pytest.mark.parametrize("fault", [None, "pointer-version", "transform"])
def test_publication_reuses_commit_owner_with_exact_new_family(tmp_path, monkeypatch, fault):
    from scripts.image_trainer import sdxl_validation_publication as publication

    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    command_raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pointer = prepared.command.plan.model_copy(
        update={
            "member_path": "manifests/sdxl-photo-style-command.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-photo-style-command/"
            + ("1.1" if fault == "pointer-version" else "1.2"),
            "sha256": "sha256:" + hashlib.sha256(command_raw).hexdigest(),
        }
    )
    events = []
    monkeypatch.setattr(publication, "resolve_control_artifact_member", lambda *a, **k: command_raw)
    monkeypatch.setattr(publication, "prepare_sdxl_photo_style_inputs", lambda *a: prepared)

    def verify(workspace, expected):
        events.append("CPU_TRANSFORMS")
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
            assert kwargs["manifest_version"] == "sdxl-photo-style-result-artifact/1.2"
            assert len(kwargs["members"]) == 7
            primary = next(m for m in kwargs["members"] if m.file_name == kwargs["primary_file"])
            assert (
                primary.schema_ref
                == "eom://schemas/image-provider/local-image-sdxl-photo-style-result/1.2"
            )
            return kwargs

    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)

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
        assert events == ["CPU_TRANSFORMS", "COMMIT"]
    else:
        with pytest.raises((ValueError, ProviderError)):
            call()
        assert "COMMIT" not in events
