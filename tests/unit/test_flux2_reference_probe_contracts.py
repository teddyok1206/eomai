from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from eom_image_contracts import (
    Flux2ReferenceProbeCase,
    LocalImageFlux2ReferenceProbeCommand,
    LocalImageFlux2ReferenceProbePlan,
    LocalImageFlux2ReferenceProbeResult,
    LocalImageModelCandidateManifest,
    content_sha256,
    load_schema,
    text_sha256,
    validate_contract,
    validate_flux2_probe_command,
    validate_flux2_probe_result,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


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
        "visual_reference": {
            "artifact_id": f"artifact_{ordinal:032x}",
            "artifact_revision_id": f"rev_{ordinal:032x}",
            "member_path": "references/primary.png",
            "schema_ref": "eom://schemas/image-provider/normalized-visual-reference/1.0",
            "media_type": "image/png",
            "sha256": "sha256:" + f"{ordinal:02x}" * 32,
            "size_bytes": 1000 + ordinal,
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
        "generation_height_px": 504,
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
                    "size_bytes": 2345,
                    "sha256": "sha256:" + "55" * 32,
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
