"""Full synthetic TRAIN closure and CPU lifecycle, not actual GPU/style acceptance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    content_sha256,
    validate_contract,
)
from eom_image_contracts.sdxl_evaluation_codec import (
    parse_sdxl_evaluation_command,
    parse_sdxl_evaluation_result,
)
from eom_image_contracts.sdxl_learned_comparison import validate_inference_arms
from eom_image_contracts.sdxl_native_canny_reference import parse_reference_command
from eom_image_contracts.sdxl_native_geometry import geometry_dimensions
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommandV4,
    LocalImageSdxlNativeLoraResult,
)
from eom_image_contracts.sdxl_native_lora_sources import (
    parse_sdxl_native_lora_sources,
    sdxl_native_lora_metadata_member_path,
)
from eom_image_contracts.sdxl_photo_baseline_reuse import (
    parse_reused_photo_baseline,
    photo_baseline_reuse_metadata_members,
)
from eom_image_contracts.sdxl_photo_style import parse_photo_style_plan_value
from eom_image_contracts.sdxl_photo_style_execution import (
    parse_photo_style_command,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, load_schema
from eom_image_provider import sdxl_photo_style as worker
from eom_orchestrator import sdxl_canny_reference_inputs as reference_owner
from eom_orchestrator import sdxl_photo_style_inputs as owner
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.sdxl_native_lora_inputs import AdmittedSdxlNativeLoraSources
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit import test_sdxl_photo_object_support_execution as previous
from tests.unit import test_sdxl_photo_style_execution as lifecycle
from tests.unit.test_native_contour_loss_contracts import _weighted_value
from tests.unit.test_sdxl_canny_reference import _seal as seal_reference
from tests.unit.test_sdxl_geometry_baseline_reuse import _fixture as geometry_fixture
from tests.unit.test_sdxl_geometry_baseline_reuse import _pin
from tests.unit.test_sdxl_learned_comparison import _Backend
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal as seal_geometry
from tests.unit.test_sdxl_native_lora_contracts import _seal_command, _seal_result
from tests.unit.test_sdxl_photo_style import _seal_plan


def _fixture(tmp_path, monkeypatch):
    # The existing full synthetic100 source closure remains real admission code.
    prior_root = tmp_path / "prior"
    prior_root.mkdir()
    prepared, workspace, _ = previous._stage(prior_root, monkeypatch)
    old_result = lifecycle._run(prepared, workspace, _Backend())
    command6 = prepared.command
    old = prepared.metadata.sources
    # The canonical reader captured by the old fixture is the existing test adapter.
    reader = owner.resolve_control_artifact_member
    records = reader.records
    monkeypatch.setattr(reference_owner, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(
        owner,
        "resolve_control_artifact_members",
        lambda engine, reads: tuple(
            reader(engine, read.pointer, maximum_bytes=read.maximum_bytes) for read in reads
        ),
    )
    prior_geometry = old.configuration_sources.evaluation
    original = old.configuration_sources.native
    body = original.training_command.model_dump(mode="json")
    rationale = _weighted_value()
    body.update(
        schema_version="local-image-sdxl-native-lora-command/1.3",
        loss_policy=rationale["loss_policy"],
        objective_evidence=rationale["objective_evidence"],
    )
    training = LocalImageSdxlNativeLoraCommandV4.model_validate(_seal_command(body))
    result_value = original.training_result.model_dump(mode="json")
    result_value.update(
        training_run_id=training.training_run_id, command_sha256=training.command_sha256
    )
    result_value["adapter_manifest"]["training_command_sha256"] = training.command_sha256
    training_result = LocalImageSdxlNativeLoraResult.model_validate(_seal_result(result_value))
    manifest = training_result.adapter_manifest
    assert manifest is not None
    # Reuse an existing synthetic geometry-result template, never its pixels.
    template_command, template_records, _ = geometry_fixture()
    template = json.loads(template_records[template_command.baseline_reuse.prior_result])
    outputs = []
    for arm in ("BASE", "LORA"):
        for case in prior_geometry.cases:
            for canvas in ("LEGACY_832X512", case.native_canvas):
                width, height = geometry_dimensions(canvas)
                row = dict(template["outputs"][0])
                row.update(
                    sample_id=case.sample_id,
                    arm=arm,
                    canvas=canvas,
                    width_px=width,
                    height_px=height,
                    prompt_sha256=case.training_caption_sha256,
                    negative_prompt_sha256=prior_geometry.negative_prompt_sha256,
                    member_path=f"outputs/raw/{case.sample_id}-{canvas.lower()}-{arm.lower()}.png",
                )
                outputs.append(row)
    value = dict(template)
    value.update(
        run_id=prior_geometry.run_id,
        command_sha256=prior_geometry.command_sha256,
        evaluation=prior_geometry.evaluation.model_dump(mode="json"),
        baseline_command_sha256=original.baseline.command_sha256,
        model=original.baseline.model.model_dump(mode="json"),
        case_relation=prior_geometry.case_relation,
        conditioning_policy=prior_geometry.conditioning_policy,
        numerics=prior_geometry.numerics.model_dump(mode="json"),
        outputs=outputs,
        started_at=prior_geometry.created_at.isoformat().replace("+00:00", "Z"),
        completed_at=(prior_geometry.created_at + timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    old_geometry_result = parse_sdxl_evaluation_result(value)
    geometry_result_pin, raw = _pin(old_geometry_result, "sdxl-lora-evaluation-result", "2")
    records[geometry_result_pin] = raw
    evaluation_value = prior_geometry.model_dump(mode="json")
    evaluation_value.update(
        schema_version="local-image-sdxl-lora-evaluation-command/1.6",
        created_at=(old_result.completed_at + timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
        baseline_reuse=dict(
            prior_command=old.configuration.native_evaluation_command.model_dump(mode="json"),
            prior_result=geometry_result_pin.model_dump(mode="json"),
        ),
    )
    evaluation_value["budget"]["maximum_generations"] = 4
    for field, model, family, identity in (
        ("training_command", training, "sdxl-native-lora-command", "3"),
        ("training_result", training_result, "sdxl-native-lora-result", "4"),
        ("adapter_manifest", manifest, "sdxl-native-lora-adapter-manifest", "4"),
    ):
        pin, raw = _pin(model, family, identity)
        records[pin] = raw
        evaluation_value["evaluation"][field] = pin.model_dump(mode="json")
    evaluation_value["evaluation"].update(
        adapter_id=manifest.adapter_id,
        adapter_revision_id=manifest.adapter_revision_id,
        adapter_manifest_sha256=manifest.manifest_sha256,
    )
    for file in manifest.files:
        previous_pin = next(
            p
            for p in records
            if p.member_path == "adapter/" + file.relative_path and p.sha256 == file.sha256
        )
        pin = previous_pin.model_copy(
            update=dict(artifact_id="artifact_" + "4" * 32, artifact_revision_id="rev_" + "4" * 32)
        )
        records[pin] = records[previous_pin]
    evaluation = parse_sdxl_evaluation_command(seal_geometry(evaluation_value))
    evaluation_pin, raw = _pin(evaluation, "sdxl-lora-evaluation-command", "5")
    records[evaluation_pin] = raw
    config_value = old.configuration.model_dump(mode="json")
    config_value.update(
        schema_version="local-image-sdxl-canny-reference-command/1.4",
        native_evaluation_command=evaluation_pin.model_dump(mode="json"),
        created_at=(evaluation.created_at + timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )
    configuration = parse_reference_command(seal_reference(config_value))
    config_pin, raw = _pin(configuration, "sdxl-canny-reference-command", "6")
    records[config_pin] = raw
    result_pin, raw = _pin(old_result, "sdxl-photo-style-result", "1")
    records[result_pin] = raw
    body = old.plan.model_dump(mode="json")
    body.update(
        schema_version="local-image-sdxl-photo-style-plan/1.7",
        configuration_anchor=config_pin.model_dump(mode="json"),
        created_at=(configuration.created_at + timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
        comparison_policy="CHANGE_NATIVE_ADAPTER_ONLY_REUSE_OBJECT_SUPPORTED_BASE",
        baseline_reuse=dict(
            prior_plan=command6.plan.model_dump(mode="json"),
            prior_result=result_pin.model_dump(mode="json"),
            prior_configuration=old.plan.configuration_anchor.model_dump(mode="json"),
        ),
    )
    body["budget"]["maximum_outputs"] = 1
    plan = parse_photo_style_plan_value(_seal_plan(body))
    plan_pin, raw = _pin(plan, "sdxl-photo-style-plan", "7")
    records[plan_pin] = raw
    value = command6.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-photo-style-command/1.7",
        plan=plan_pin.model_dump(mode="json"),
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        created_at=(plan.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    )
    command = parse_photo_style_command(lifecycle._seal(value))
    pure_metadata = {
        sdxl_native_lora_metadata_member_path(p): records[p]
        for p in old.native_training_sources.metadata_pointers
    }
    objective = ImageEvaluationArtifactMember.model_validate(rationale["objective_evidence"])
    records[objective] = b"objective rationale"
    pure_metadata[sdxl_native_lora_metadata_member_path(objective)] = records[objective]
    native_sources = parse_sdxl_native_lora_sources(training, pure_metadata)
    admitted = AdmittedSdxlNativeLoraSources(
        training,
        native_sources,
        tuple(
            SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
            for path, raw in sorted(pure_metadata.items())
        ),
    )

    def native_admission(engine, selected):
        assert selected == training
        return admitted

    monkeypatch.setattr(reference_owner, "resolve_sdxl_native_lora_sources", native_admission)
    return command, reader, prepared, old_result


def test_schema_codec_and_three_small_pins_without_old_pixels(tmp_path, monkeypatch):
    command, _reader, _, _ = _fixture(tmp_path, monkeypatch)
    metadata = owner.resolve_sdxl_photo_style_execution_metadata(object(), command)
    plan = metadata.sources.plan
    assert plan.generated_arms() == ("LORA",) and plan.budget.maximum_outputs == 1
    assert len(photo_baseline_reuse_metadata_members(plan)) == 3
    assert len(metadata.sources.native_training_sources.targets) == 100
    assert all("outputs/" not in file.member_path for file in metadata.files)
    assert metadata.sources.baseline_reuse is not None
    for family in ("plan", "command", "result"):
        key = "sdxl-photo-style-" + family + "-v8"
        Draft202012Validator.check_schema(load_schema(key))
        repo = Path(__file__).resolve().parents[2]
        filename = SCHEMA_FILES[key]
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[key]
    with pytest.raises(SchemaError):
        validate_contract("sdxl-photo-style-plan-v7", plan.model_dump(mode="json"))
    assert parse_photo_style_command(command.model_dump(mode="json")) == command


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_current_lora_only_cpu_lifecycle_and_terminal_replay(tmp_path, monkeypatch, fault):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    successor = tmp_path / "successor"
    successor.mkdir()
    monkeypatch.setattr(lifecycle, "_fixture", lambda *_: (command, reader, []))
    prepared, root, leases = lifecycle._stage(successor, monkeypatch)
    monkeypatch.setattr(worker, "canny_conditioning_canvas_png", previous.retained._canny)
    backend = _Backend(fault)
    result = lifecycle._run(prepared, root, backend)
    succeeded = fault in (None, "second")
    assert result.status == ("SUCCEEDED" if succeeded else "FAILED")
    assert len(result.outputs) == (1 if succeeded else 0)
    assert backend.calls == 1 and backend.arms == ["LORA"]
    assert leases == ["ENTER", "EXIT"]
    assert not (root / "outputs/base").exists()
    assert owner.sdxl_photo_style_input_hashes(prepared) == {
        f.member_path: f.sha256 for f in prepared.files
    }
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, lambda *_a, **_k: pytest.fail("replay side effect"))
    assert lifecycle._run(prepared, root, backend) == result
    assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in before}


@pytest.mark.parametrize(
    "field", ["prior_plan", "prior_result", "prior_configuration", "prior_geometry"]
)
def test_borrowed_metadata_byte_mismatch_refused(tmp_path, monkeypatch, field):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    metadata = owner.resolve_sdxl_photo_style_execution_metadata(object(), command)
    sources = metadata.sources
    documents = replace(
        sources.baseline_reuse, **{field: getattr(sources.baseline_reuse, field) + b" "}
    )
    with pytest.raises(ValueError):
        parse_reused_photo_baseline(
            sources.plan, sources.configuration, sources.configuration_sources, documents
        )


@pytest.mark.parametrize("fault", ["missing", "hash", "denied"])
def test_reused_result_resolution_fails_before_binary_materialization(tmp_path, monkeypatch, fault):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan_value(json.loads(reader.records[command.plan]))
    pin = plan.baseline_reuse.prior_result
    reader.calls.clear()
    if fault == "missing":
        del reader.records[pin]
    elif fault == "hash":
        reader.records[pin] += b" "
    else:
        original = owner.resolve_control_artifact_members

        def denied(engine, reads):
            if any(read.pointer == pin for read in reads):
                raise ControlArtifactResolutionError("CONTROL_ARTIFACT_POINTER_INVALID")
            return original(engine, reads)

        monkeypatch.setattr(owner, "resolve_control_artifact_members", denied)
    with pytest.raises(ControlArtifactResolutionError):
        owner.prepare_sdxl_photo_style_inputs(object(), command)
    assert all(p.media_type not in ("image/png", "application/octet-stream") for p in reader.calls)
    assert all(not p.member_path.startswith("adapter/") for p in reader.calls)


@pytest.mark.parametrize("field", ["prompt", "seed", "budget", "support_parent"])
def test_rehashed_plan_cannot_change_the_borrowed_base_recipe(tmp_path, monkeypatch, field):
    command, _reader, _, _ = _fixture(tmp_path, monkeypatch)
    sources = owner.resolve_sdxl_photo_style_execution_metadata(object(), command).sources
    value = sources.plan.model_dump(mode="json")
    if field == "prompt":
        case = value["cases"][0]["case"]
        case["prompt_en"] += " changed"
        case["prompt_sha256"] = "sha256:" + hashlib.sha256(case["prompt_en"].encode()).hexdigest()
    elif field == "seed":
        value["seed"] += 1
        value["cases"][0]["case"]["seeds"] = [value["seed"]]
    elif field == "budget":
        value["budget"]["maximum_duration_ms"] -= 1
    else:
        value["support_parents"]["review"]["artifact_revision_id"] = "rev_" + "9" * 32
    if field in ("prompt", "seed"):
        case = value["cases"][0]["case"]
        case["case_id"] = (
            "imgsdxlcase_"
            + content_sha256(
                {k: v for k, v in case.items() if k not in ("case_id", "staged_member_path")}
            )[7:39]
        )
        case["staged_member_path"] = "inputs/" + case["case_id"] + ".png"
    changed = parse_photo_style_plan_value(_seal_plan(value))
    assert changed.plan_sha256 != sources.plan.plan_sha256
    with pytest.raises(ValueError, match="PHOTO_BASELINE_REUSE_INPUT_MISMATCH"):
        parse_reused_photo_baseline(
            changed, sources.configuration, sources.configuration_sources, sources.baseline_reuse
        )


def test_rehashed_result_cannot_claim_base_generation_or_another_baseline(tmp_path, monkeypatch):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    successor = tmp_path / "successor"
    successor.mkdir()
    monkeypatch.setattr(lifecycle, "_fixture", lambda *_: (command, reader, []))
    prepared, root, _ = lifecycle._stage(successor, monkeypatch)
    monkeypatch.setattr(worker, "canny_conditioning_canvas_png", previous.retained._canny)
    result = lifecycle._run(prepared, root, _Backend())
    value = result.model_dump(mode="json")
    value["outputs"][0]["arm"] = "BASE"
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises((ValueError, SchemaError)):
        lifecycle.parse_photo_style_result(value)
    changed = result.model_copy(
        update={
            "baseline_reuse": result.baseline_reuse.model_copy(
                update={
                    "prior_result": result.baseline_reuse.prior_result.model_copy(
                        update={"artifact_revision_id": "rev_" + "9" * 32}
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="PHOTO_BASELINE_REUSE_RESULT_MISMATCH"):
        lifecycle.validate_photo_style_result(prepared.command, prepared.metadata.sources, changed)
    (root / "outputs/base").mkdir(mode=0o700)
    with pytest.raises((ValueError, lifecycle.ProviderError)):
        lifecycle._run(prepared, root, _Backend())


@pytest.mark.parametrize("arms", [("BASE",), ("LORA", "BASE"), ("LORA", "LORA"), (), ["LORA"]])
def test_invalid_arm_selection_refused(arms):
    with pytest.raises(ValueError):
        validate_inference_arms(arms)
