"""Synthetic exact BASE reuse; no live GPU/model/image-quality acceptance."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    content_json_bytes,
    content_sha256,
    validate_contract,
)
from eom_image_contracts.sdxl_evaluation_codec import (
    parse_sdxl_evaluation_command,
    parse_sdxl_evaluation_result,
)
from eom_image_contracts.sdxl_geometry_baseline_reuse import (
    LocalImageSdxlReusedGeometryCommand,
    parse_reused_geometry_baseline,
)
from eom_image_contracts.sdxl_native_evaluation import parse_sdxl_native_evaluation_sources
from eom_image_contracts.sdxl_native_geometry import geometry_dimensions
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommandV3,
    LocalImageSdxlNativeLoraCommandV4,
    LocalImageSdxlNativeLoraResult,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, load_schema
from eom_image_provider import sdxl_native_geometry as worker
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit import test_sdxl_native_evaluation as native_tests
from tests.unit import test_sdxl_native_geometry as geometry_tests
from tests.unit.test_native_contour_loss_contracts import _weighted_value
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal
from tests.unit.test_sdxl_native_evaluation import _payloads, _prepare
from tests.unit.test_sdxl_native_geometry import _Backend
from tests.unit.test_sdxl_native_lora_contracts import _result_value, _seal_command, _seal_result
from tests.unit.test_sdxl_probe_workspace import _operator
from tests.unit.test_style_exposure_consumers import _balanced_geometry_fixture


def _pin(model, family, identity):
    raw = content_json_bytes(model.model_dump(mode="json"))
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + identity * 32,
        artifact_revision_id="rev_" + identity * 32,
        member_path="manifests/" + family + ".json",
        schema_ref="eom://schemas/image-provider/" + model.schema_version,
        media_type="application/json",
        sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
    ), raw


def _fixture():
    weighted = LocalImageSdxlNativeLoraCommandV4.model_validate(_weighted_value())
    predecessor_value = weighted.model_dump(mode="json")
    predecessor_value.update(schema_version="local-image-sdxl-native-lora-command/1.2")
    del predecessor_value["loss_policy"], predecessor_value["objective_evidence"]
    predecessor = LocalImageSdxlNativeLoraCommandV3.model_validate(_seal_command(predecessor_value))
    prior, records, prior_sources = _balanced_geometry_fixture((predecessor, {}))
    outputs = []
    for arm in prior.generated_arms():
        for case in prior.cases:
            for canvas in ("LEGACY_832X512", case.native_canvas):
                width, height = geometry_dimensions(canvas)
                outputs.append(
                    dict(
                        sample_id=case.sample_id,
                        arm=arm,
                        canvas=canvas,
                        width_px=width,
                        height_px=height,
                        prompt_sha256=case.training_caption_sha256,
                        negative_prompt_sha256=prior.negative_prompt_sha256,
                        member_path=f"outputs/raw/{case.sample_id}-{canvas.lower()}-{arm.lower()}.png",
                        sha256="sha256:" + "f" * 64,
                        size_bytes=1,
                        duration_ms=1,
                    )
                )
    deps = prior_sources.training_command.dependencies.model_dump(mode="json")
    # Fake prior terminal metadata; no prior pixels are supplied or needed for staging.
    old_result_value = dict(
        schema_version="local-image-sdxl-lora-evaluation-result/1.5",
        run_id=prior.run_id,
        command_sha256=prior.command_sha256,
        evaluation=prior.evaluation.model_dump(mode="json"),
        baseline_command_sha256=prior_sources.baseline.command_sha256,
        model=prior_sources.baseline.model.model_dump(mode="json"),
        case_relation=prior.case_relation,
        conditioning_policy=prior.conditioning_policy,
        numerics=prior.numerics.model_dump(mode="json"),
        status="SUCCEEDED",
        error_code=None,
        runtime={
            k: deps[k]
            for k in (
                "python_version",
                "torch_version",
                "diffusers_version",
                "transformers_version",
            )
        },
        generation_calls=8,
        outputs=outputs,
        started_at=prior.created_at.isoformat().replace("+00:00", "Z"),
        completed_at=(prior.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        duration_ms=1,
    )
    old_result_value["runtime"].update(
        cuda_version="12.8",
        gpu_name="synthetic GPU",
        compute_capability="12.0",
        peak_gpu_memory_bytes=1024,
    )
    old_result_value["runtime"] = LocalImageRuntime.model_validate(
        old_result_value["runtime"]
    ).model_dump(mode="json")
    old_result_value["result_sha256"] = content_sha256(old_result_value)
    old_result = parse_sdxl_evaluation_result(old_result_value)
    prior_pin, prior_raw = _pin(prior, "sdxl-lora-evaluation-command", "8")
    result_pin, result_raw = _pin(old_result, "sdxl-lora-evaluation-result", "9")
    records.update({prior_pin: prior_raw, result_pin: result_raw})
    training_result_value = _result_value(weighted)
    training_result_value["adapter_manifest"]["files"] = prior_sources.manifest.model_dump(
        mode="json"
    )["files"]
    training_result = LocalImageSdxlNativeLoraResult.model_validate(
        _seal_result(training_result_value)
    )
    value = prior.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-lora-evaluation-command/1.6",
        created_at=(old_result.completed_at + timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
        baseline_reuse=dict(
            prior_command=prior_pin.model_dump(mode="json"),
            prior_result=result_pin.model_dump(mode="json"),
        ),
    )
    value["budget"]["maximum_generations"] = 4
    for field, model, family, identity in (
        ("training_command", weighted, "sdxl-native-lora-command", "6"),
        ("training_result", training_result, "sdxl-native-lora-result", "7"),
        (
            "adapter_manifest",
            training_result.adapter_manifest,
            "sdxl-native-lora-adapter-manifest",
            "7",
        ),
    ):
        pointer, raw = _pin(model, family, identity)
        value["evaluation"][field] = pointer.model_dump(mode="json")
        records[pointer] = raw
    for file in training_result.adapter_manifest.files:
        previous = next(p for p in records if p.member_path == "adapter/" + file.relative_path)
        pointer = previous.model_copy(
            update=dict(artifact_id="artifact_" + "7" * 32, artifact_revision_id="rev_" + "7" * 32)
        )
        records[pointer] = records[previous]
    manifest = training_result.adapter_manifest
    value["evaluation"].update(
        adapter_id=manifest.adapter_id,
        adapter_revision_id=manifest.adapter_revision_id,
        adapter_manifest_sha256=manifest.manifest_sha256,
    )
    command = LocalImageSdxlReusedGeometryCommand.model_validate(_seal(value))
    sources = parse_sdxl_native_evaluation_sources(command, **_payloads(command, records))
    return command, records, sources


def test_schema_codec_package_build_and_frozen_predecessors():
    command, _, _ = _fixture()
    assert parse_sdxl_evaluation_command(command.model_dump(mode="json")) == command
    for kind in ("command", "result"):
        name = "sdxl-lora-evaluation-" + kind + "-v7"
        Draft202012Validator.check_schema(load_schema(name))
        repo = Path(__file__).resolve().parents[2]
        filename = SCHEMA_FILES[name]
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[name]
        assert filename in (repo / "scripts/image_trainer/build_release.sh").read_text()
    with pytest.raises(SchemaError):
        validate_contract("sdxl-lora-evaluation-command-v6", command.model_dump(mode="json"))
    assert (
        SCHEMA_SHA256["sdxl-lora-evaluation-command-v6"]
        == "sha256:8c393fdd9eb15892fb7ddc5029e4345efe3b6a4a2c0eff282cf97d4082eb95b4"
    )
    assert (
        SCHEMA_SHA256["sdxl-lora-evaluation-result-v6"]
        == "sha256:bbe0dc5ee65367d5edd01d253713a5ec8be465dbe7a2fb7870c44f0a0c834fff"
    )


def test_exact_reuse_admission_stages_only_small_metadata_and_new_weights(monkeypatch, tmp_path):
    command, records, sources = _fixture()
    reuse = command.baseline_reuse
    baseline = parse_reused_geometry_baseline(
        command,
        sources,
        prior_command_payload=records[reuse.prior_command],
        prior_result_payload=records[reuse.prior_result],
    )
    assert len(baseline.base_outputs) == 4
    prepared, reader = _prepare(monkeypatch, command, records)
    assert len(prepared.files) == 9
    assert not any(p.media_type == "image/png" for p in reader.calls)
    assert not any(file.member_path.endswith(".png") for file in prepared.files)
    parent, identity, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_lora_evaluation_inputs(
        prepared, workspace_parent=parent, worker=identity
    )
    assert len(tuple(staged.workspace.rglob("*.png"))) == 0
    assert (staged.workspace / "inputs/reuse-result.json").is_file()


@pytest.mark.parametrize(
    "fault",
    [
        "budget",
        "training_version",
        "missing_reuse",
        "pointer_media",
        "pointer_member",
        "pointer_schema",
        "activation",
    ],
)
def test_closed_command_rejects_old_or_unbounded_semantics(fault):
    command, _, _ = _fixture()
    value = command.model_dump(mode="json")
    if fault == "budget":
        value["budget"]["maximum_generations"] = 8
    elif fault == "training_version":
        value["evaluation"]["training_command"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-sdxl-native-lora-command/1.2"
        )
    elif fault == "missing_reuse":
        del value["baseline_reuse"]
    elif fault == "activation":
        value["activation_policy"] = "ALLOW"
    else:
        field, bad = {
            "pointer_media": ("media_type", "image/png"),
            "pointer_member": ("member_path", "latest.json"),
            "pointer_schema": (
                "schema_ref",
                "eom://schemas/image-provider/local-image-sdxl-lora-evaluation-result/1.4",
            ),
        }[fault]
        value["baseline_reuse"]["prior_result"][field] = bad
    value = _seal(value)
    with pytest.raises((ValueError, ValidationError)):
        LocalImageSdxlReusedGeometryCommand.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("sdxl-lora-evaluation-command-v7", value)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "hash",
        "future",
        "case",
        "negative",
        "numerics",
        "model",
        "failed",
        "result_identity",
        "duplicate",
        "base_caption",
    ],
)
def test_bad_reuse_fails_before_adapter_binary_reads(monkeypatch, fault):
    original_reader = native_tests._Reader

    class MetadataOnlyReader(original_reader):
        def __call__(self, engine, pointer, **kwargs):
            assert pointer.media_type == "application/json", "binary read before reuse rejection"
            return super().__call__(engine, pointer, **kwargs)

    monkeypatch.setattr(native_tests, "_Reader", MetadataOnlyReader)
    command, records, _ = _fixture()
    reuse = command.baseline_reuse
    if fault == "missing":
        del records[reuse.prior_result]
    elif fault == "hash":
        records[reuse.prior_result] += b" "
    else:
        from json import loads

        value = loads(records[reuse.prior_result])
        if fault == "future":
            value["completed_at"] = (
                (command.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
            )
        elif fault == "case":
            value["outputs"][0]["sample_id"] = "imgsourcecrop_" + "0" * 32
            value["outputs"][0]["member_path"] = value["outputs"][0]["member_path"].replace(
                command.cases[0].sample_id, value["outputs"][0]["sample_id"]
            )
        elif fault == "negative":
            value["outputs"][0]["negative_prompt_sha256"] = "sha256:" + "0" * 64
        elif fault == "numerics":
            value["numerics"]["seed"] = 123
        elif fault == "model":
            value["model"]["model_revision_id"] = "imgmodelrev_" + "0" * 32
        elif fault == "failed":
            value.update(status="FAILED", error_code="SDXL_PROBE_EXEC_FAILED")
        elif fault == "result_identity":
            value["command_sha256"] = "sha256:" + "0" * 64
        elif fault == "duplicate":
            value["outputs"][1] = value["outputs"][0]
        else:
            value["outputs"][0]["prompt_sha256"] = "sha256:" + "0" * 64
        value["result_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "result_sha256"}
        )
        raw = content_json_bytes(value)
        pointer = reuse.prior_result.model_copy(
            update=dict(sha256="sha256:" + hashlib.sha256(raw).hexdigest())
        )
        records[pointer] = raw
        value = command.model_dump(mode="json")
        value["baseline_reuse"]["prior_result"] = pointer.model_dump(mode="json")
        command = LocalImageSdxlReusedGeometryCommand.model_validate(_seal(value))
    with pytest.raises((ValueError, ControlArtifactResolutionError, SchemaError)):
        _prepare(monkeypatch, command, records)


@pytest.mark.parametrize("fault", [None, "second", "unknown", "shape", "memory"])
def test_only_lora_calls_and_installed_style_terminal_replay(monkeypatch, tmp_path, fault):
    monkeypatch.setattr(geometry_tests, "_geometry_fixture", _fixture)
    prepared, sources = geometry_tests._stage(monkeypatch, tmp_path)
    backend = _Backend(sources, fault)
    args = dict(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused.lock",
        backend=backend,
    )
    result = worker.run_sdxl_native_geometry(**args)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert result.schema_version.endswith("/1.6")
    assert backend.arms == ["LORA"]
    assert len(backend.calls) <= 4 and all(output.arm == "LORA" for output in result.outputs)
    if fault is None:
        assert result.generation_calls == 4 and len(result.outputs) == 4
    assert result.baseline_reuse == prepared.command.baseline_reuse
    assert parse_sdxl_evaluation_result(result.model_dump(mode="json")) == result
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    for name in (
        "resolve_sdxl_stack",
        "acquire_gpu_lease",
        "load_sdxl_lora_material",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, lambda *_a, **_kw: pytest.fail("replay side effect"))
    assert worker.run_sdxl_native_geometry(**args) == result
    assert len(backend.calls) == result.generation_calls
    assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in before}


def test_result_cannot_claim_new_base_or_change_reuse_lineage(monkeypatch, tmp_path):
    monkeypatch.setattr(geometry_tests, "_geometry_fixture", _fixture)
    prepared, sources = geometry_tests._stage(monkeypatch, tmp_path)
    result = worker.run_sdxl_native_geometry(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused.lock",
        backend=_Backend(sources),
    )
    value = result.model_dump(mode="json")
    value["outputs"][0]["arm"] = "BASE"
    value["outputs"][0]["member_path"] = value["outputs"][0]["member_path"].replace(
        "-lora.png", "-base.png"
    )
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises((ValueError, SchemaError)):
        parse_sdxl_evaluation_result(value)
    value = result.model_dump(mode="json")
    value["baseline_reuse"]["prior_result"]["sha256"] = "sha256:" + "0" * 64
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    from eom_image_contracts.sdxl_native_geometry import validate_sdxl_native_geometry_result

    with pytest.raises(ValueError, match="BASELINE_REUSE_MISMATCH"):
        validate_sdxl_native_geometry_result(
            prepared.command, sources, parse_sdxl_evaluation_result(value)
        )
