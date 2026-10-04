from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    LEARNED_COMPARISON_ARMS,
    LocalImageInformativeLineartExtractionCommand,
    LocalImageInformativeLineartExtractionResult,
    LocalImageInformativeLineartManifest,
    LocalImageSdxlLearnedComparisonCommand,
    LocalImageSdxlLearnedComparisonResult,
    LocalImageSdxlLoraEvaluationCommand,
    content_json_bytes,
    content_sha256,
    parse_sdxl_learned_comparison_sources,
    validate_contract,
    validate_sdxl_learned_comparison_result,
    validate_sdxl_learned_comparison_sources,
)
from pydantic import ValidationError

from tests.unit.test_informative_lineart_contracts import _manifest
from tests.unit.test_informative_lineart_extraction_contracts import _result
from tests.unit.test_informative_lineart_extraction_contracts import (
    _seal_command as _seal_extraction,
)
from tests.unit.test_sdxl_lora_evaluation_contracts import _fixture as _lora_fixture


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal(value, *, result=False):
    if result:
        body = {key: item for key, item in value.items() if key != "result_sha256"}
        return {**body, "result_sha256": content_sha256(body)}
    body = {key: item for key, item in value.items() if key not in {"run_id", "command_sha256"}}
    body["run_id"] = "imgsdxllearnedrun_" + content_sha256(body)[7:39]
    return {**body, "command_sha256": content_sha256(body)}


def _fixture():
    lora_value, baseline, training, training_result, adapter = _lora_fixture()
    lora_command = LocalImageSdxlLoraEvaluationCommand.model_validate(lora_value)
    manifest = LocalImageInformativeLineartManifest.model_validate(_manifest())

    def pointer(model, family, identity):
        return {
            "artifact_id": "artifact_" + identity * 32,
            "artifact_revision_id": "rev_" + identity * 32,
            "member_path": "manifests/" + family + ".json",
            "schema_ref": "eom://schemas/image-provider/local-image-" + family + "/1.0",
            "media_type": "application/json",
            "sha256": _sha(content_json_bytes(model.model_dump(mode="json"))),
        }

    extraction = LocalImageInformativeLineartExtractionCommand.model_validate(
        _seal_extraction(
            {
                "schema_version": "local-image-informative-lineart-extraction-command/1.0",
                "source_commit": "a" * 40,
                "created_at": "2026-10-04T00:00:00Z",
                "purpose": "EVALUATION_ONLY_LEARNED_LINEART_PREPROCESSING",
                "activation_policy": "FORBIDDEN",
                "extractor": manifest.model_dump(
                    include={
                        "extractor_id",
                        "extractor_revision_id",
                        "manifest_sha256",
                        "provider_family",
                        "runtime_contract_version",
                    }
                ),
                "extractor_manifest": pointer(manifest, "informative-lineart-manifest", "1"),
                "baseline_command": lora_command.evaluation.baseline_command.model_dump(
                    mode="json"
                ),
                "case_ids": [case.case_id for case in baseline.cases],
                "preprocessing_policy": "FIT_RGB_EXTRACT_INVERT_832X512/1.0",
                "budget": {"maximum_duration_ms": 30000, "maximum_peak_gpu_memory_bytes": 2**30},
            }
        )
    )
    extraction_result = LocalImageInformativeLineartExtractionResult.model_validate(
        _result(extraction, baseline)
    )
    command = LocalImageSdxlLearnedComparisonCommand.model_validate(
        _seal(
            {
                "schema_version": "local-image-sdxl-learned-comparison-command/1.0",
                "source_commit": "b" * 40,
                "created_at": "2026-10-04T00:00:03Z",
                "purpose": "EVALUATION_ONLY_MATCHED_LEARNED_CONDITIONING",
                "activation_policy": "FORBIDDEN",
                "baseline_command": lora_command.evaluation.baseline_command.model_dump(
                    mode="json"
                ),
                "extraction_command": pointer(
                    extraction, "informative-lineart-extraction-command", "2"
                ),
                "extraction_result": pointer(
                    extraction_result, "informative-lineart-extraction-result", "3"
                ),
                "lora_evaluation_command": pointer(
                    lora_command, "sdxl-lora-evaluation-command", "4"
                ),
                "conditioning_policy": "PINNED_LEARNED_FINE_INVERTED/1.0",
                "case_ids": [case.case_id for case in baseline.cases],
                "seed": baseline.cases[0].seeds[0],
                "budget": {"maximum_duration_ms": 60000, "maximum_peak_gpu_memory_bytes": 2**30},
            }
        )
    )
    payloads = {
        name: content_json_bytes(model.model_dump(mode="json"))
        for name, model in (
            ("baseline_payload", baseline),
            ("extraction_command_payload", extraction),
            ("extraction_result_payload", extraction_result),
            ("lora_evaluation_command_payload", lora_command),
            ("training_command_payload", training),
            ("training_result_payload", training_result),
            ("adapter_manifest_payload", adapter),
        )
    }
    return command, parse_sdxl_learned_comparison_sources(command, **payloads), payloads


def _result_value(command, sources):
    original = {case.case_id: case for case in sources.baseline.cases}
    extracted = {output.case_id: output for output in sources.extraction_result.outputs}
    return _seal(
        {
            "schema_version": "local-image-sdxl-learned-comparison-result/1.0",
            "run_id": command.run_id,
            "command_sha256": command.command_sha256,
            "baseline_command_sha256": sources.baseline.command_sha256,
            "extraction_result_sha256": sources.extraction_result.result_sha256,
            "model": sources.baseline.model.model_dump(mode="json"),
            "conditioning_policy": command.conditioning_policy,
            "status": "SUCCEEDED",
            "error_code": None,
            "runtime": {
                "python_version": "3.11.15",
                "provider_version": "eom-local-image-provider/1.0",
                "torch_version": "2.7.1+cu128",
                "diffusers_version": "0.35.2",
                "transformers_version": "4.56.2",
                "cuda_version": "12.8",
                "gpu_name": "fake-unit-GPU",
                "compute_capability": "12.0",
                "peak_gpu_memory_bytes": 100,
            },
            "outputs": [
                {
                    "arm": arm,
                    "case_id": case_id,
                    "seed": command.seed,
                    "reference_sha256": original[case_id].reference_image.sha256,
                    "conditioning_sha256": extracted[case_id].conditioning_sha256,
                    "member_path": f"outputs/{arm.lower()}/final/{case_id}-{command.seed:010d}.png",
                    "sha256": _sha(b"fake-final"),
                    "size_bytes": 10,
                    "raw_member_path": (
                        f"outputs/{arm.lower()}/raw/{case_id}-{command.seed:010d}.png"
                    ),
                    "raw_sha256": _sha(b"fake-raw"),
                    "raw_size_bytes": 10,
                    "width_px": 800,
                    "height_px": 500,
                    "duration_ms": 10,
                    "peak_gpu_memory_bytes": 100,
                }
                for arm in LEARNED_COMPARISON_ARMS
                for case_id in command.case_ids
            ],
            "started_at": "2026-10-04T00:00:04Z",
            "completed_at": "2026-10-04T00:00:05Z",
            "duration_ms": 1000,
        },
        result=True,
    )


def test_additive_contract_and_parser_keep_original_seed_prompt_and_conditioning_identity():
    command, sources, _ = _fixture()
    validate_contract("sdxl-learned-comparison-command", command.model_dump(mode="json"))
    value = _result_value(command, sources)
    validate_contract("sdxl-learned-comparison-result", value)
    result = LocalImageSdxlLearnedComparisonResult.model_validate(value)
    validate_sdxl_learned_comparison_result(command, sources, result)
    assert sources.baseline.conditioning_policy == "FIT_GRAYSCALE_INVERT_832X512/1.0"
    assert "prompt_en" not in command.model_dump_json()
    assert tuple(output.arm for output in result.outputs) == ("BASE", "LORA")


@pytest.mark.parametrize(
    "fault",
    [
        "activation",
        "policy",
        "pointer",
        "member",
        "media",
        "duplicate",
        "too-many",
        "seed",
        "hash",
        "run",
        "utc",
    ],
)
def test_bad_command_scope_pointer_identity_and_seed(fault):
    command, sources, _ = _fixture()
    value = command.model_dump(mode="json")
    if fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "policy":
        value["conditioning_policy"] = "FIT_GRAYSCALE_INVERT_832X512/1.0"
    elif fault == "pointer":
        value["extraction_result"]["schema_ref"] = value["baseline_command"]["schema_ref"]
    elif fault == "member":
        value["extraction_result"]["member_path"] = "manifests/other.json"
    elif fault == "media":
        value["baseline_command"]["media_type"] = "image/png"
    elif fault == "duplicate":
        value["case_ids"] *= 2
    elif fault == "too-many":
        value["case_ids"] = ["imgsdxlcase_" + f"{index:032x}" for index in range(4)]
    elif fault == "seed":
        value["seed"] = 999
    elif fault == "utc":
        value["created_at"] = "2026-10-04T09:00:03+09:00"
    value = _seal(value)
    if fault in {"hash", "run"}:
        value["command_sha256" if fault == "hash" else "run_id"] = (
            "sha256:" + "f" * 64 if fault == "hash" else "imgsdxllearnedrun_" + "f" * 32
        )
    with pytest.raises((ValueError, ValidationError)):
        parsed = LocalImageSdxlLearnedComparisonCommand.model_validate(value)
        validate_sdxl_learned_comparison_sources(parsed, sources)


@pytest.mark.parametrize(
    "name",
    [
        "baseline_payload",
        "extraction_command_payload",
        "extraction_result_payload",
        "lora_evaluation_command_payload",
        "training_command_payload",
        "training_result_payload",
        "adapter_manifest_payload",
    ],
)
def test_each_pinned_document_rejects_changed_bytes(name):
    command, _, payloads = _fixture()
    payloads[name] += b"\n"
    with pytest.raises(ValueError):
        parse_sdxl_learned_comparison_sources(command, **payloads)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "order",
        "seed",
        "reference",
        "conditioning",
        "model",
        "baseline",
        "extraction",
        "time-budget",
        "memory-budget",
        "path",
    ],
)
def test_result_coverage_source_and_resource_guards(fault):
    command, sources, _ = _fixture()
    value = _result_value(command, sources)
    if fault == "missing":
        value["outputs"].pop()
    elif fault == "duplicate":
        value["outputs"].append(value["outputs"][0])
    elif fault == "order":
        value["outputs"].reverse()
    elif fault == "seed":
        value["outputs"][0]["seed"] = 999
    elif fault in {"reference", "conditioning"}:
        value["outputs"][0][fault + "_sha256"] = "sha256:" + "f" * 64
    elif fault == "model":
        value["model"]["manifest_sha256"] = "sha256:" + "f" * 64
    elif fault in {"baseline", "extraction"}:
        value[fault + "_command_sha256" if fault == "baseline" else "extraction_result_sha256"] = (
            "sha256:" + "f" * 64
        )
    elif fault == "time-budget":
        value["duration_ms"] = command.budget.maximum_duration_ms + 1
    elif fault == "memory-budget":
        value["runtime"]["peak_gpu_memory_bytes"] = command.budget.maximum_peak_gpu_memory_bytes + 1
    else:
        value["outputs"][0]["member_path"] = value["outputs"][1]["member_path"]
    with pytest.raises((ValueError, ValidationError)):
        result = LocalImageSdxlLearnedComparisonResult.model_validate(_seal(value, result=True))
        validate_sdxl_learned_comparison_result(command, sources, result)


def test_partial_failure_must_be_a_prefix_of_base_then_lora_execution():
    command, sources, _ = _fixture()
    value = _result_value(command, sources)
    value.update(status="FAILED", error_code="SDXL_PROBE_OOM")
    value["outputs"] = value["outputs"][:1]
    result = LocalImageSdxlLearnedComparisonResult.model_validate(_seal(value, result=True))
    validate_sdxl_learned_comparison_result(command, sources, result)
    value["outputs"] = _result_value(command, sources)["outputs"][1:]
    result = LocalImageSdxlLearnedComparisonResult.model_validate(_seal(value, result=True))
    with pytest.raises(ValueError, match="prefix"):
        validate_sdxl_learned_comparison_result(command, sources, result)


def test_canonical_and_packaged_schema_bytes_match_and_are_pinned():
    root = Path(__file__).parents[2]
    for family in ("command", "result"):
        filename = f"local-image-sdxl-learned-comparison-{family}-v1.schema.json"
        assert (root / "schemas/image-provider" / filename).read_bytes() == (
            root / "packages/image_contracts/eom_image_contracts/schemas" / filename
        ).read_bytes()
