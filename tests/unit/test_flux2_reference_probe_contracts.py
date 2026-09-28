from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eom_image_contracts import (
    Flux2ReferenceProbeCase,
    LocalImageFlux2ReferenceProbeCommand,
    LocalImageFlux2ReferenceProbeCommandV2,
    LocalImageFlux2ReferenceProbePlan,
    LocalImageFlux2ReferenceProbePlanV2,
    LocalImageFlux2ReferenceProbeResult,
    LocalImageFlux2ReferenceProbeResultV2,
    LocalImageModelCandidateManifest,
    content_sha256,
    load_schema,
    text_sha256,
    validate_contract,
    validate_flux2_probe_command,
    validate_flux2_probe_result,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name",
    (
        "local-image-flux2-reference-probe-command-v1.schema.json",
        "local-image-flux2-reference-probe-command-v2.schema.json",
        "local-image-flux2-reference-probe-plan-v1.schema.json",
        "local-image-flux2-reference-probe-plan-v2.schema.json",
        "local-image-flux2-reference-probe-result-v1.schema.json",
        "local-image-flux2-reference-probe-result-v2.schema.json",
        "local-image-model-candidate-manifest-v1.schema.json",
    ),
)
def test_flux2_contract_canonical_and_package_schema_bytes_match(name: str) -> None:
    canonical = REPOSITORY_ROOT / "schemas/image-provider" / name
    packaged = REPOSITORY_ROOT / "packages/image_contracts/eom_image_contracts/schemas" / name

    assert canonical.read_bytes() == packaged.read_bytes()


def _manifest_value() -> dict[str, Any]:
    upstream = {
        "repo_id": "black-forest-labs/FLUX.2-klein-base-4B",
        "revision": "a3b4f4849157f664bdbc776fd7453c2783562f4d",
        "source_url": "https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B",
        "license_id": "Apache-2.0",
    }
    files = [
        {
            "relative_path": "model_index.json",
            "size_bytes": 321,
            "sha256": "sha256:" + "11" * 32,
        }
    ]
    value: dict[str, Any] = {
        "schema_version": "local-image-model-candidate-manifest/1.0",
        "model_id": "imgmodel_" + content_sha256(upstream["repo_id"])[7:39],
        "model_revision_id": "imgmodelrev_"
        + content_sha256({"upstream": upstream, "files": files})[7:39],
        "provider_family": "diffusers-flux2-klein-base-4b",
        "runtime_contract_version": "eom-local-image-candidate-runner/1.0",
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "upstream": upstream,
        "files": files,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "created_by": "operator_bakeoff",
    }
    value["manifest_sha256"] = content_sha256(value)
    return value


def _case_value(ordinal: int) -> dict[str, Any]:
    prompt = (
        "Preserve the exact specimen silhouette and viewpoint. Render sparse black assessment "
        f"line art on white for subject {ordinal}; no text, labels, border, or background scene."
    )
    value: dict[str, Any] = {
        "subject_key": f"NATURAL_SPECIMEN_{ordinal}",
        "source_crop": {
            "artifact_id": f"artifact_{ordinal + 32:032x}",
            "artifact_revision_id": f"rev_{ordinal + 32:032x}",
            "member_path": f"crops/imgsciviscandidate_{ordinal:032x}.png",
            "schema_ref": (
                "eom://schemas/image-provider/"
                "local-image-science-corpus-visual-pilot-candidate-image/1.0"
            ),
            "media_type": "image/png",
            "sha256": "sha256:" + f"{ordinal + 32:02x}" * 32,
        },
        "visual_reference": {
            "artifact_id": f"artifact_{ordinal:032x}",
            "artifact_revision_id": f"rev_{ordinal:032x}",
            "member_path": "references/primary.png",
            "schema_ref": "eom://schemas/image-provider/normalized-visual-reference/1.0",
            "media_type": "image/png",
            "sha256": "sha256:" + f"{ordinal:02x}" * 32,
            "size_bytes": 1000 + ordinal,
        },
        "conditioning": {
            "member_path": "reference-conditioning.png",
            "media_type": "image/png",
            "sha256": "sha256:" + f"{ordinal + 16:02x}" * 32,
            "size_bytes": 2000 + ordinal,
            "width_px": 800,
            "height_px": 504,
        },
        "simplification_metrics": {
            "source_foreground_ratio": 0.25,
            "conditioning_foreground_ratio": 0.2,
            "border_foreground_ratio": 0.0,
            "source_edge_density": 0.1,
            "conditioning_edge_density": 0.05,
            "edge_density_ratio": 0.5,
        },
        "simplifier_runtime": {
            "contract": "local-image-reference-simplifier/1.0",
            "pillow_version": "11.3.0",
        },
        "prompt_en": prompt,
        "prompt_sha256": text_sha256(prompt),
        "seed": ordinal,
    }
    value["case_id"] = "imgflux2case_" + content_sha256(value)[7:39]
    return value


def _plan_value(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = sorted(
        (_case_value(index) for index in range(1, 4)),
        key=lambda value: value["case_id"],
    )
    value: dict[str, Any] = {
        "schema_version": "local-image-flux2-reference-probe-plan/1.0",
        "candidate_model_manifest": {
            "artifact_id": "artifact_" + "aa" * 16,
            "artifact_revision_id": "rev_" + "bb" * 16,
            "member_path": "manifests/model-candidate.json",
            "schema_ref": "eom://schemas/image-provider/local-image-model-candidate-manifest/1.0",
            "media_type": "application/json",
            "sha256": content_sha256(manifest),
        },
        "candidate_model_manifest_sha256": content_sha256(manifest),
        "activation_policy": "FORBIDDEN",
        "generation_width_px": 800,
        "generation_height_px": 512,
        "delivery_width_px": 800,
        "delivery_height_px": 500,
        "inference_steps": 50,
        "guidance_scale_milli": 4000,
        "dtype": "bfloat16",
        "cpu_offload": True,
        "simplification": {
            "contract": "local-image-reference-simplification/1.1",
            "output_member": "reference-conditioning.png",
            "color_policy": "GRAYSCALE_WHITE_BACKGROUND",
            "denoise_policy": "MAX_5_MEDIAN_7_GAUSSIAN_2_0",
            "tone_policy": "SIX_LEVEL_LIGHT_TONE_CONTOUR",
            "foreground_luma_threshold": 245,
            "border_width_px": 24,
            "foreground_ratio_min": 0.005,
            "foreground_ratio_max": 0.8,
            "border_foreground_ratio_max": 0.12,
        },
        "cases": cases,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "created_by": "operator_bakeoff",
    }
    identity_body = {
        key: field for key, field in value.items() if key not in {"created_at", "created_by"}
    }
    identity = content_sha256(identity_body)[7:39]
    value["plan_id"] = f"imgflux2probe_{identity}"
    value["plan_sha256"] = content_sha256(value)
    return value


def _command_value(plan: dict[str, Any]) -> dict[str, Any]:
    inputs = sorted(
        (
            {
                "case_id": case["case_id"],
                "relative_path": f"inputs/references/{case['case_id']}.png",
                "sha256": case["visual_reference"]["sha256"],
                "size_bytes": case["visual_reference"]["size_bytes"],
                "conditioning_relative_path": (
                    f"inputs/references/{case['case_id']}-conditioning.png"
                ),
                "conditioning_sha256": case["conditioning"]["sha256"],
                "conditioning_size_bytes": case["conditioning"]["size_bytes"],
            }
            for case in plan["cases"]
        ),
        key=lambda value: value["case_id"],
    )
    value: dict[str, Any] = {
        "schema_version": "local-image-flux2-reference-probe-command/1.0",
        "plan": {
            "artifact_id": "artifact_" + "cc" * 16,
            "artifact_revision_id": "rev_" + "dd" * 16,
            "member_path": "manifests/flux2-reference-probe-plan.json",
            "schema_ref": "eom://schemas/image-provider/local-image-flux2-reference-probe-plan/1.0",
            "media_type": "application/json",
            "sha256": content_sha256(plan),
        },
        "plan_sha256": content_sha256(plan),
        "staged_plan_path": "inputs/probe-plan.json",
        "staged_model_manifest_path": "inputs/model-manifest.json",
        "model_root": "/opt/eom-evaluation-models/flux2-klein-base-4b",
        "inputs": inputs,
        "output_directory": "outputs",
        "source_commit": "1" * 40,
        "timeout_seconds": 7200,
    }
    identity = content_sha256(value)[7:39]
    value["run_id"] = f"imgflux2proberun_{identity}"
    value["command_sha256"] = content_sha256(value)
    return value


def _result_value(
    manifest: dict[str, Any], plan: dict[str, Any], command: dict[str, Any]
) -> dict[str, Any]:
    outputs = []
    measurements = []
    for case in plan["cases"]:
        case_id = case["case_id"]
        outputs.extend(
            [
                {
                    "case_id": case_id,
                    "kind": "CANDIDATE",
                    "relative_path": f"outputs/{case_id}-candidate.png",
                    "media_type": "image/png",
                    "size_bytes": 12345,
                    "sha256": "sha256:" + "44" * 32,
                    "width_px": 800,
                    "height_px": 500,
                },
                {
                    "case_id": case_id,
                    "kind": "CONDITIONING",
                    "relative_path": f"outputs/{case_id}-conditioning.png",
                    "media_type": "image/png",
                    "size_bytes": case["conditioning"]["size_bytes"],
                    "sha256": case["conditioning"]["sha256"],
                    "width_px": 800,
                    "height_px": 504,
                },
            ]
        )
        measurements.append(
            {
                "case_id": case_id,
                "elapsed_milliseconds": 1000,
                "peak_gpu_memory_bytes": 13_000_000_000,
            }
        )
    outputs.sort(key=lambda value: (value["case_id"], value["kind"]))
    measurements.sort(key=lambda value: value["case_id"])
    value: dict[str, Any] = {
        "schema_version": "local-image-flux2-reference-probe-result/1.0",
        "run_id": command["run_id"],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "command_sha256": command["command_sha256"],
        "model_revision_id": manifest["model_revision_id"],
        "activation_policy": "FORBIDDEN",
        "status": "SUCCEEDED",
        "error_code": None,
        "outputs": outputs,
        "measurements": measurements,
        "runtime": {
            "python_version": "3.12.11",
            "torch_version": "2.7.1",
            "diffusers_version": "0.40.0",
            "transformers_version": "4.57.0",
            "cuda_version": "12.8",
            "gpu_name": "NVIDIA GeForce RTX 5080",
            "compute_capability": "12.0",
        },
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "completed_at": NOW.replace(minute=1).isoformat().replace("+00:00", "Z"),
    }
    value["result_sha256"] = content_sha256(value)
    return value


def test_flux2_probe_contract_family_round_trips_schema_and_pydantic() -> None:
    manifest_value = _manifest_value()
    plan_value = _plan_value(manifest_value)
    command_value = _command_value(plan_value)
    result_value = _result_value(manifest_value, plan_value, command_value)

    for contract, value, model in (
        ("model-candidate-manifest", manifest_value, LocalImageModelCandidateManifest),
        ("flux2-reference-probe-plan", plan_value, LocalImageFlux2ReferenceProbePlan),
        ("flux2-reference-probe-command", command_value, LocalImageFlux2ReferenceProbeCommand),
        ("flux2-reference-probe-result", result_value, LocalImageFlux2ReferenceProbeResult),
    ):
        validate_contract(contract, value)
        parsed = model.model_validate(value)
        assert parsed.model_dump(mode="json") == value
        assert set(load_schema(contract)["required"]) == set(
            model.model_json_schema(mode="validation")["required"]
        )

    manifest = LocalImageModelCandidateManifest.model_validate(manifest_value)
    plan = LocalImageFlux2ReferenceProbePlan.model_validate(plan_value)
    command = LocalImageFlux2ReferenceProbeCommand.model_validate(command_value)
    result = LocalImageFlux2ReferenceProbeResult.model_validate(result_value)
    validate_flux2_probe_command(manifest, plan, command)
    validate_flux2_probe_result(plan, command, manifest, result)


def _layout_locked_values() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    manifest = _manifest_value()
    plan = _plan_value(manifest)
    plan["schema_version"] = "local-image-flux2-reference-probe-plan/1.1"
    plan["layout_lock"] = {
        "contract": "local-image-reference-layout-lock/1.0",
        "foreground_luma_threshold": 245,
        "source_canvas_width_px": 800,
        "source_canvas_height_px": 504,
        "delivery_canvas_width_px": 800,
        "delivery_canvas_height_px": 500,
        "source_to_delivery_y_policy": "SCALE_HALF_OPEN_OUTWARD",
        "candidate_crop_policy": "TIGHT_FOREGROUND_BBOX",
        "placement_policy": "EXACT_REFERENCE_BBOX",
        "resize_filter": "LANCZOS",
        "background_policy": "WHITE",
        "empty_foreground_policy": "FAIL_CLOSED",
    }
    plan_identity = {
        key: field
        for key, field in plan.items()
        if key not in {"plan_id", "created_at", "created_by", "plan_sha256"}
    }
    plan["plan_id"] = "imgflux2probe_" + content_sha256(plan_identity)[7:39]
    plan["plan_sha256"] = content_sha256(
        {key: field for key, field in plan.items() if key != "plan_sha256"}
    )

    command = _command_value(plan)
    command["schema_version"] = "local-image-flux2-reference-probe-command/1.1"
    command["plan"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-flux2-reference-probe-plan/1.1"
    )
    command["plan"]["sha256"] = content_sha256(plan)
    command["plan_sha256"] = content_sha256(plan)
    command_identity = {
        key: field for key, field in command.items() if key not in {"run_id", "command_sha256"}
    }
    command["run_id"] = "imgflux2proberun_" + content_sha256(command_identity)[7:39]
    command["command_sha256"] = content_sha256(
        {key: field for key, field in command.items() if key != "command_sha256"}
    )

    outputs: list[dict[str, Any]] = []
    measurements: list[dict[str, Any]] = []
    for case in plan["cases"]:
        case_id = case["case_id"]
        for kind, suffix, height in (
            ("RAW_CANDIDATE", "raw-candidate", 500),
            ("LOCKED_CANDIDATE", "locked-candidate", 500),
            ("CONDITIONING", "conditioning", 504),
        ):
            outputs.append(
                {
                    "case_id": case_id,
                    "kind": kind,
                    "relative_path": f"outputs/{case_id}-{suffix}.png",
                    "media_type": "image/png",
                    "size_bytes": (
                        case["conditioning"]["size_bytes"] if kind == "CONDITIONING" else 12345
                    ),
                    "sha256": (
                        case["conditioning"]["sha256"]
                        if kind == "CONDITIONING"
                        else "sha256:" + ("55" if kind == "RAW_CANDIDATE" else "66") * 32
                    ),
                    "width_px": 800,
                    "height_px": height,
                }
            )
        bbox = {"x_min": 120, "y_min": 100, "x_max": 420, "y_max": 300}
        measurements.append(
            {
                "case_id": case_id,
                "elapsed_milliseconds": 1000,
                "peak_gpu_memory_bytes": 13_000_000_000,
                "reference_bbox": dict(bbox),
                "raw_candidate_bbox": {"x_min": 20, "y_min": 10, "x_max": 700, "y_max": 480},
                "locked_candidate_bbox": dict(bbox),
                "raw_area_ratio_milli": 5440,
                "locked_area_ratio_milli": 1000,
                "raw_center_distance_milli": 180,
                "locked_center_distance_milli": 0,
                "layout_status": "PASS",
            }
        )
    outputs.sort(key=lambda value: (value["case_id"], value["kind"]))
    measurements.sort(key=lambda value: value["case_id"])
    result: dict[str, Any] = {
        "schema_version": "local-image-flux2-reference-probe-result/1.1",
        "run_id": command["run_id"],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "command_sha256": command["command_sha256"],
        "model_revision_id": manifest["model_revision_id"],
        "activation_policy": "FORBIDDEN",
        "status": "SUCCEEDED",
        "error_code": None,
        "outputs": outputs,
        "measurements": measurements,
        "runtime": {
            "python_version": "3.12.11",
            "torch_version": "2.7.1",
            "diffusers_version": "0.40.0",
            "transformers_version": "4.57.0",
            "cuda_version": "12.8",
            "gpu_name": "NVIDIA GeForce RTX 5080",
            "compute_capability": "12.0",
        },
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "completed_at": NOW.replace(minute=1).isoformat().replace("+00:00", "Z"),
    }
    result["result_sha256"] = content_sha256(result)
    return manifest, plan, command, result


def test_flux2_layout_lock_contract_family_round_trips_schema_and_pydantic() -> None:
    _, plan, command, result = _layout_locked_values()
    for name, value, model in (
        ("flux2-reference-probe-plan-v2", plan, LocalImageFlux2ReferenceProbePlanV2),
        ("flux2-reference-probe-command-v2", command, LocalImageFlux2ReferenceProbeCommandV2),
        ("flux2-reference-probe-result-v2", result, LocalImageFlux2ReferenceProbeResultV2),
    ):
        validate_contract(name, value)
        parsed = model.model_validate(value)
        assert parsed.model_dump(mode="json") == value
        assert set(load_schema(name)["required"]) == set(
            model.model_json_schema(mode="validation")["required"]
        )


def test_flux2_layout_lock_result_rejects_nonmatching_locked_bounds() -> None:
    _, _, _, result = _layout_locked_values()
    broken = deepcopy(result)
    broken["measurements"][0]["locked_candidate_bbox"]["x_max"] -= 1
    broken["result_sha256"] = content_sha256(
        {key: value for key, value in broken.items() if key != "result_sha256"}
    )
    with pytest.raises(ValidationError, match="does not match reference bounds"):
        LocalImageFlux2ReferenceProbeResultV2.model_validate(broken)


def test_flux2_probe_rejects_path_escape_manifest_drift_and_partial_success() -> None:
    manifest = _manifest_value()
    bad_path = deepcopy(manifest)
    bad_path["files"][0]["relative_path"] = "../model.safetensors"
    bad_path["manifest_sha256"] = content_sha256(
        {key: value for key, value in bad_path.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="relative_path"):
        LocalImageModelCandidateManifest.model_validate(bad_path)

    plan = _plan_value(manifest)
    command = _command_value(plan)
    result = _result_value(manifest, plan, command)
    result["outputs"].pop()
    result["result_sha256"] = content_sha256(
        {key: value for key, value in result.items() if key != "result_sha256"}
    )
    with pytest.raises(ValidationError, match="exact case outputs"):
        LocalImageFlux2ReferenceProbeResult.model_validate(result)


def test_flux2_case_identity_and_prompt_hash_are_fail_closed() -> None:
    value = _case_value(1)
    value["prompt_en"] += " changed"
    with pytest.raises(ValidationError, match="prompt hash"):
        Flux2ReferenceProbeCase.model_validate(value)


def test_flux2_case_requires_exact_source_crop_pointer() -> None:
    value = _case_value(1)
    value["source_crop"]["schema_ref"] = "eom://schemas/image-provider/wrong/1.0"

    with pytest.raises(JsonSchemaValidationError):
        validate_contract(
            "flux2-reference-probe-plan",
            _plan_value(_manifest_value()) | {"cases": [value, _case_value(2), _case_value(3)]},
        )
    with pytest.raises(ValidationError, match="source crop pointer"):
        Flux2ReferenceProbeCase.model_validate(value)
