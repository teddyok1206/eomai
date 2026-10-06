"""Pure wire/receipt and source relation checks; no real dispatch, GPU or image acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    LocalImageSdxlIpStyleComparisonPlan,
    content_json_bytes,
    content_sha256,
    select_sdxl_ip_style_sources,
)
from eom_image_contracts.models import ImageEvaluationArtifactMember
from eom_image_contracts.sdxl_ip_style_execution import (
    parse_sdxl_ip_style_command,
    parse_sdxl_ip_style_execution_plan,
    parse_sdxl_ip_style_result,
    validate_sdxl_ip_style_execution_result,
)
from eom_image_contracts.sdxl_photo_style_result import parse_photo_style_result
from eom_image_contracts.validation import (
    SCHEMA_FILES,
    SCHEMA_SHA256,
    load_schema,
    validate_contract,
)
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_ip_style_inputs as owner
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_sdxl_ip_style_comparison_plan import _seal as _seal_plan
from tests.unit.test_sdxl_ip_style_selection_metadata import source_values as _source_fixture


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal_command(raw):
    value = copy.deepcopy(raw)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxlipstylerun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _seal_result(value):
    return {
        **value,
        "result_sha256": content_sha256({k: v for k, v in value.items() if k != "result_sha256"}),
    }


@pytest.fixture(scope="module")
def source_values():
    return _source_fixture.__wrapped__()


@pytest.fixture
def execution_values(source_values):
    old_plan, metadata = source_values
    selected = select_sdxl_ip_style_sources(old_plan, **metadata)
    runtime = dict(
        provider_version="eom-local-image-provider/1.0",
        python_version="3.11.13",
        torch_version="2.7.1+cu128",
        diffusers_version="0.35.2",
        transformers_version="4.56.2",
        cuda_version="12.8",
        gpu_name="SYNTHETIC_NOT_ACTUAL_GPU",
        compute_capability="12.0",
        peak_gpu_memory_bytes=1024,
    )
    outputs = []
    for source in selected:
        filename = f"{source.selection.case_id}-0000000001.png"
        outputs.append(
            dict(
                arm="LORA",
                case_id=source.selection.case_id,
                seed=1,
                reference_sha256=source.photo.case.reference_image.sha256,
                conditioning_sha256=source.selection.conditioning_sha256,
                member_path="outputs/lora/final/" + filename,
                sha256="sha256:" + "a" * 64,
                size_bytes=100,
                raw_member_path="outputs/lora/raw/" + filename,
                raw_sha256="sha256:" + "b" * 64,
                raw_size_bytes=120,
                width_px=800,
                height_px=500,
                duration_ms=1000,
                peak_gpu_memory_bytes=1024,
            )
        )
    parent = parse_photo_style_result(
        _seal_result(
            dict(
                schema_version="local-image-sdxl-photo-style-result/1.5",
                run_id="imgsdxlvalcmprun_" + "a" * 32,
                command_sha256="sha256:" + "a" * 64,
                plan_sha256="sha256:" + "b" * 64,
                configuration_command_sha256="sha256:" + "c" * 64,
                native_evaluation_command_sha256="sha256:" + "d" * 64,
                native_adapter_manifest_sha256="sha256:" + "e" * 64,
                case_relation="LICENSED_PHOTO_REFERENCES_NOT_CORPUS_HOLDOUT",
                native_fit_policy="NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0",
                initialization=dict(
                    policy="CONSTANT_WHITE_RGB_832X512_FULL_DENOISE/1.0",
                    denoising_strength=1.0,
                    scheduler_steps=30,
                    effective_denoising_steps=30,
                    pillow_version="11.3.0",
                ),
                control=dict(
                    conditioning_scale=1.0,
                    guidance_start=0.0,
                    guidance_end=1.0,
                    resource_profile="ALL_GPU_FP16_NO_OFFLOAD",
                ),
                region_reviews_sha256="sha256:" + "1" * 64,
                quality_acceptance="NOT_REVIEWED",
                activation_policy="FORBIDDEN",
                training_steps=0,
                holdout_binary_reads=0,
                status="SUCCEEDED",
                error_code=None,
                runtime=runtime,
                inputs=[r.trace.model_dump(mode="json") for r in selected],
                outputs=outputs,
                started_at="2026-10-06T14:00:00Z",
                completed_at="2026-10-06T14:01:00Z",
                duration_ms=3000,
            )
        )
    )
    plan_value = old_plan.model_dump(mode="json")
    plan_value["photo_result"]["sha256"] = _sha(content_json_bytes(parent.model_dump(mode="json")))
    plan = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal_plan(plan_value))
    selected = select_sdxl_ip_style_sources(plan, **metadata)
    raw = content_json_bytes(plan.model_dump(mode="json"))
    pin = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "f" * 32,
        artifact_revision_id="rev_" + "f" * 32,
        member_path="manifests/sdxl-ip-style-comparison-plan.json",
        schema_ref="eom://schemas/image-provider/local-image-sdxl-ip-style-comparison-plan/1.0",
        media_type="application/json",
        sha256=_sha(raw),
    )
    command = parse_sdxl_ip_style_command(
        _seal_command(
            dict(
                schema_version="local-image-sdxl-ip-style-comparison-command/1.0",
                source_commit="a" * 40,
                created_at="2026-10-06T15:01:00Z",
                purpose="EVALUATION_ONLY_MATCHED_STYLE_REFERENCE",
                activation_policy="FORBIDDEN",
                plan=pin.model_dump(mode="json"),
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                encoder_policy="CPU_FLOAT32_EAGER_GLOBAL_CFG/1.0",
                maximum_peak_host_memory_bytes=1024**3,
            )
        )
    )
    inputs, outputs = [], []
    for i, source in enumerate(selected):
        trace = dict(
            case_id=source.selection.case_id,
            style_sample_id=source.selection.style_sample_id,
            style_source_sha256=source.style_sample.source_image.sha256,
            style_rgb_sha256=source.selection.style_rgb_sha256,
            encoder_input_sha256="sha256:" + f"{i + 10:064x}",
            cfg_embedding_sha256="sha256:" + f"{i + 20:064x}",
            reference_sha256=source.photo.case.reference_image.sha256,
            conditioning_sha256=source.selection.conditioning_sha256,
            initialization_rgb_sha256=source.selection.initialization_rgb_sha256,
            prompt_sha256=source.photo.case.prompt_sha256,
            negative_prompt_sha256=source.photo.case.negative_prompt_sha256,
            seed=1,
        )
        inputs.append(trace)
        for arm in ("OFF", "ON"):
            filename = f"{source.selection.case_id}-0000000001.png"
            outputs.append(
                dict(
                    arm=arm,
                    case_id=source.selection.case_id,
                    seed=1,
                    cfg_embedding_sha256=trace["cfg_embedding_sha256"],
                    initial_generator_state_sha256="sha256:" + "5" * 64,
                    prompt_sha256=trace["prompt_sha256"],
                    negative_prompt_sha256=trace["negative_prompt_sha256"],
                    member_path=f"outputs/{arm.lower()}/final/{filename}",
                    sha256="sha256:" + "a" * 64,
                    size_bytes=100,
                    raw_member_path=f"outputs/{arm.lower()}/raw/{filename}",
                    raw_sha256="sha256:" + "b" * 64,
                    raw_size_bytes=120,
                    width_px=800,
                    height_px=500,
                    duration_ms=1000,
                    peak_gpu_memory_bytes=1024,
                )
            )
    result = _seal_result(
        dict(
            schema_version="local-image-sdxl-ip-style-comparison-result/1.0",
            run_id=command.run_id,
            command_sha256=command.command_sha256,
            plan_sha256=plan.plan_sha256,
            photo_result_sha256=parent.result_sha256,
            native_adapter_manifest_sha256=parent.native_adapter_manifest_sha256,
            style_model=plan.style_model.model_dump(mode="json"),
            encoder_policy=command.encoder_policy,
            routing_policy=plan.routing.policy,
            quality_acceptance="NOT_REVIEWED",
            activation_policy="FORBIDDEN",
            holdout_binary_reads=0,
            training_steps=0,
            status="SUCCEEDED",
            error_code=None,
            runtime=runtime,
            peak_host_memory_bytes=1024,
            inputs=inputs,
            outputs=outputs,
            started_at="2026-10-06T15:02:00Z",
            completed_at="2026-10-06T15:03:00Z",
            duration_ms=8000,
        )
    )
    return command, plan, selected, parent, result


def _validate(values, raw=None):
    command, plan, selected, parent, default = values
    result = parse_sdxl_ip_style_result(default if raw is None else raw)
    validate_sdxl_ip_style_execution_result(command, plan, selected, parent, result)
    return result


def test_closed_contract_preserves_preparation_and_exact_ordered_receipt(execution_values):
    command, plan, *_ = execution_values
    assert (
        parse_sdxl_ip_style_execution_plan(
            command, content_json_bytes(plan.model_dump(mode="json"))
        )
        == plan
    )
    result = _validate(execution_values)
    assert plan.dispatch_policy == "PREPARATION_ONLY_NOT_A_WORKER_COMMAND"
    assert result.activation_policy == "FORBIDDEN" and result.quality_acceptance == "NOT_REVIEWED"
    assert result.holdout_binary_reads == result.training_steps == 0
    assert len(result.inputs) == 2 and len(result.outputs) == 4
    assert result.style_model == plan.style_model
    with pytest.raises(ValueError):
        result.status = "FAILED"


@pytest.mark.parametrize("inputs,outputs", [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (2, 3), (2, 4)])
def test_failed_result_keeps_actual_prefix_even_post_render_failure(
    execution_values, inputs, outputs
):
    raw = copy.deepcopy(execution_values[-1])
    raw.update(status="FAILED", error_code="SDXL_PROBE_EXEC_FAILED")
    raw["inputs"] = raw["inputs"][:inputs]
    raw["outputs"] = raw["outputs"][:outputs]
    if not outputs:
        raw["runtime"] = None
    assert _validate(execution_values, _seal_result(raw)).status == "FAILED"


@pytest.mark.parametrize(
    "field",
    [
        "cfg_embedding_sha256",
        "prompt_sha256",
        "negative_prompt_sha256",
        "initial_generator_state_sha256",
        "seed",
    ],
)
def test_resealed_unmatched_arms_are_rejected(execution_values, field):
    raw = copy.deepcopy(execution_values[-1])
    raw["outputs"][1][field] = 2 if field == "seed" else "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        _validate(execution_values, _seal_result(raw))


@pytest.mark.parametrize(
    "field",
    [
        "style_sample_id",
        "style_source_sha256",
        "style_rgb_sha256",
        "reference_sha256",
        "conditioning_sha256",
        "initialization_rgb_sha256",
        "prompt_sha256",
        "negative_prompt_sha256",
    ],
)
def test_resealed_wrong_source_or_prompt_is_rejected(execution_values, field):
    raw = copy.deepcopy(execution_values[-1])
    raw["inputs"][0][field] = (
        ("imgsourcecrop_" + "f" * 32) if field == "style_sample_id" else "sha256:" + "f" * 64
    )
    with pytest.raises(ValueError):
        _validate(execution_values, _seal_result(raw))


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "reorder",
        "skip-prefix",
        "runtime",
        "peak",
        "duration",
        "status",
        "time",
        "hash",
        "member",
        "raw-member",
        "host-budget",
        "gpu-budget",
        "time-budget",
    ],
)
def test_receipt_integrity_and_resource_failures(execution_values, fault):
    raw = copy.deepcopy(execution_values[-1])
    if fault == "missing":
        raw["outputs"].pop()
    elif fault == "duplicate":
        raw["outputs"][1] = raw["outputs"][0]
    elif fault == "reorder":
        raw["outputs"].reverse()
    elif fault == "skip-prefix":
        raw.update(status="FAILED", error_code="SDXL_PROBE_EXEC_FAILED")
        raw["outputs"] = raw["outputs"][1:]
    elif fault == "runtime":
        raw["runtime"] = None
    elif fault == "peak":
        raw["runtime"]["peak_gpu_memory_bytes"] = 1
    elif fault == "duration":
        raw["duration_ms"] = 1
    elif fault == "status":
        raw["error_code"] = "SDXL_PROBE_EXEC_FAILED"
    elif fault == "time":
        raw["started_at"] = "2026-10-06T14:59:00Z"
    elif fault == "hash":
        raw["result_sha256"] = "sha256:" + "f" * 64
    elif fault in {"member", "raw-member"}:
        raw["outputs"][0]["member_path" if fault == "member" else "raw_member_path"] = (
            "../../outside.png"
        )
    elif fault == "host-budget":
        raw["peak_host_memory_bytes"] = 2 * 1024**3
    elif fault == "gpu-budget":
        raw["runtime"]["peak_gpu_memory_bytes"] = 17 * 1024**3
    else:
        raw["duration_ms"] = 700000
    with pytest.raises((ValueError, SchemaError)):
        _validate(execution_values, raw if fault == "hash" else _seal_result(raw))


def test_over_host_ceiling_is_measured_not_clamped_and_failed(execution_values):
    raw = copy.deepcopy(execution_values[-1])
    raw.update(
        status="FAILED",
        error_code="SDXL_PROBE_BUDGET_EXCEEDED",
        peak_host_memory_bytes=65 * 1024**3,
    )
    assert _validate(execution_values, _seal_result(raw)).peak_host_memory_bytes == 65 * 1024**3


@pytest.mark.parametrize(
    "fault", ["plan-id", "semantic-hash", "future-plan", "raw-hash", "wrong-family", "noncanonical"]
)
def test_plan_is_exact_pinned_revision_not_a_latest_lookup(execution_values, fault):
    command, plan, *_ = execution_values
    value = command.model_dump(mode="json")
    raw = content_json_bytes(plan.model_dump(mode="json"))
    if fault == "plan-id":
        value["plan_id"] = "imgsdxlipstyleplan_" + "f" * 32
    elif fault == "semantic-hash":
        value["plan_sha256"] = "sha256:" + "f" * 64
    elif fault == "future-plan":
        value["created_at"] = "2026-10-06T14:00:00Z"
    elif fault == "raw-hash":
        value["plan"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "wrong-family":
        value["plan"]["schema_ref"] = value["plan"]["schema_ref"].replace("/1.0", "/9.0")
    else:
        raw = json.dumps(plan.model_dump(mode="json"), indent=2).encode()
        value["plan"]["sha256"] = _sha(raw)
    with pytest.raises(ValueError):
        parse_sdxl_ip_style_execution_plan(parse_sdxl_ip_style_command(_seal_command(value)), raw)


@pytest.mark.parametrize("contract", ["command", "result"])
def test_schema_202012_pinned_hash_offline_refs_and_no_extra_payload(execution_values, contract):
    name = "sdxl-ip-style-comparison-" + contract
    path = Path("packages/image_contracts/eom_image_contracts/schemas") / SCHEMA_FILES[name]
    assert _sha(path.read_bytes()) == SCHEMA_SHA256[name]
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"].endswith("2020-12/schema")
    raw = (
        execution_values[0].model_dump(mode="json")
        if contract == "command"
        else copy.deepcopy(execution_values[-1])
    )
    validate_contract(name, raw)
    raw["large_binary"] = "not allowed"
    with pytest.raises(SchemaError):
        validate_contract(name, raw)


@pytest.mark.parametrize("field", ["training_steps", "holdout_binary_reads"])
def test_boolean_cannot_impersonate_zero_receipt_counter(execution_values, field):
    raw = copy.deepcopy(execution_values[-1])
    raw[field] = False
    with pytest.raises(SchemaError):
        parse_sdxl_ip_style_result(_seal_result(raw))


def test_resource_breach_preserves_actual_first_oom_failure(execution_values):
    raw = copy.deepcopy(execution_values[-1])
    raw.update(status="FAILED", error_code="SDXL_PROBE_OOM", peak_host_memory_bytes=65 * 1024**3)
    assert _validate(execution_values, _seal_result(raw)).error_code == "SDXL_PROBE_OOM"


def test_shared_style_must_have_one_input_and_embedding_trace(execution_values):
    raw = copy.deepcopy(execution_values[-1])
    raw["inputs"][1]["style_sample_id"] = raw["inputs"][0]["style_sample_id"]
    with pytest.raises(ValueError, match="SHARED_STYLE_TRACE_CONFLICT"):
        parse_sdxl_ip_style_result(_seal_result(raw))


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "command_sha256",
        "plan_sha256",
        "photo_result_sha256",
        "native_adapter_manifest_sha256",
    ],
)
def test_resealed_wrong_execution_parent_cannot_be_accepted(execution_values, field):
    raw = copy.deepcopy(execution_values[-1])
    raw[field] = ("imgsdxlipstylerun_" + "f" * 32) if field == "run_id" else "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="PARENT_IDENTITY"):
        _validate(execution_values, _seal_result(raw))


def test_resealed_parent_result_must_match_original_raw_artifact_pin(execution_values):
    values = list(execution_values)
    raw = values[3].model_dump(mode="json")
    raw["native_adapter_manifest_sha256"] = "sha256:" + "f" * 64
    values[3] = parse_photo_style_result(_seal_result(raw))
    candidate = copy.deepcopy(values[-1])
    candidate["photo_result_sha256"] = values[3].result_sha256
    candidate["native_adapter_manifest_sha256"] = values[3].native_adapter_manifest_sha256
    with pytest.raises(ValueError, match="PARENT_IDENTITY"):
        _validate(values, _seal_result(candidate))


def test_execution_metadata_reads_one_bounded_plan_then_existing_owner(
    execution_values, monkeypatch
):
    command, plan, *_ = execution_values
    events = []
    selection = SimpleNamespace(plan=plan)

    def read(engine, reads):
        events.append("PLAN_READ")
        assert len(reads) == 1 and reads[0].pointer == command.plan
        assert reads[0].maximum_bytes == 64 * 1024
        return (content_json_bytes(plan.model_dump(mode="json")),)

    def resolve(engine, actual):
        events.append("EXISTING_SOURCE_OWNER")
        assert actual == plan
        return selection

    monkeypatch.setattr(owner, "resolve_control_artifact_members", read)
    monkeypatch.setattr(owner, "resolve_sdxl_ip_style_selection_metadata", resolve)
    result = owner.resolve_sdxl_ip_style_execution_metadata(object(), command)
    assert result.command == command and result.selection is selection
    assert events == ["PLAN_READ", "EXISTING_SOURCE_OWNER"]
    with pytest.raises(FrozenInstanceError):
        result.command = command


@pytest.mark.parametrize(
    "fault", ["permission", "hash", "missing", "noncanonical", "owner-mismatch"]
)
def test_execution_metadata_failure_never_dispatches_or_uses_latest(
    execution_values, monkeypatch, fault
):
    command, plan, *_ = execution_values
    events = []

    def read(_engine, _reads):
        if fault in {"permission", "missing"}:
            raise ValueError(fault)
        raw = content_json_bytes(plan.model_dump(mode="json"))
        if fault == "hash":
            raw += b"\n"
        if fault == "noncanonical":
            raw = json.dumps(plan.model_dump(mode="json"), indent=2).encode()
        return (raw,)

    def resolve(_engine, _plan):
        events.append("OWNER")
        return SimpleNamespace(plan=plan.model_copy(update={"activation_policy": "WRONG"}))

    monkeypatch.setattr(owner, "resolve_control_artifact_members", read)
    monkeypatch.setattr(owner, "resolve_sdxl_ip_style_selection_metadata", resolve)
    with pytest.raises(ValueError):
        owner.resolve_sdxl_ip_style_execution_metadata(object(), command)
    assert events == (["OWNER"] if fault == "owner-mismatch" else [])


def test_worker_cli_remains_closed_until_complete_numerical_owner_exists(
    execution_values, tmp_path
):
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    path = root / "command.json"
    raw = content_json_bytes(execution_values[0].model_dump(mode="json"))
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
        out.write(raw)
    with pytest.raises(ProviderError) as error:
        load_sdxl_comparison_command(root, path)
    assert error.value.code == "SDXL_PROBE_INPUT_INVALID"
