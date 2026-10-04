from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageInformativeLineartExtractionCommand,
    LocalImageInformativeLineartExtractionResult,
    LocalImageInformativeLineartManifest,
    content_json_bytes,
    content_sha256,
    select_informative_lineart_cases,
    validate_contract,
    validate_informative_lineart_extraction_result,
)
from pydantic import ValidationError

from tests.unit.test_informative_lineart_contracts import _manifest
from tests.unit.test_sdxl_probe_inputs import _fixture


def _sha(payload):
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _seal_command(value):
    body = {key: item for key, item in value.items() if key not in {"run_id", "command_sha256"}}
    body["run_id"] = "imglineartextractrun_" + content_sha256(body)[7:39]
    return {**body, "command_sha256": content_sha256(body)}


def _command():
    baseline, _, records = _fixture()
    manifest = LocalImageInformativeLineartManifest.model_validate(_manifest())

    def pointer(artifact, revision, member, schema, payload):
        return {
            "artifact_id": "artifact_" + artifact * 32,
            "artifact_revision_id": "rev_" + revision * 32,
            "member_path": member,
            "schema_ref": "eom://schemas/image-provider/" + schema,
            "media_type": "application/json",
            "sha256": _sha(payload),
        }

    value = _seal_command(
        {
            "schema_version": "local-image-informative-lineart-extraction-command/1.0",
            "source_commit": "1" * 40,
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
            "extractor_manifest": pointer(
                "1",
                "2",
                "manifests/informative-lineart-manifest.json",
                "local-image-informative-lineart-manifest/1.0",
                content_json_bytes(manifest.model_dump(mode="json")),
            ),
            "baseline_command": pointer(
                "3",
                "4",
                "manifests/sdxl-lineart-probe-command.json",
                "local-image-sdxl-lineart-probe-command/1.0",
                content_json_bytes(baseline.model_dump(mode="json")),
            ),
            "case_ids": [case.case_id for case in baseline.cases],
            "preprocessing_policy": "FIT_RGB_EXTRACT_INVERT_832X512/1.0",
            "budget": {"maximum_duration_ms": 30000, "maximum_peak_gpu_memory_bytes": 2**30},
        }
    )
    return (
        LocalImageInformativeLineartExtractionCommand.model_validate(value),
        baseline,
        manifest,
        records,
    )


def _runtime():
    return {
        "provider_version": "eom-informative-lineart-extractor/1.0",
        "torch_version": "2.7.1+cu128",
        "safetensors_version": "0.6.2",
        "pillow_version": "11.3.0",
        "cuda_version": "12.8",
        "compute_capability": "12.0",
        "dtype": "float32",
        "gpu_name": "fake-unit-GPU-not-actual-runtime",
    }


def _seal_result(value):
    body = {key: item for key, item in value.items() if key != "result_sha256"}
    return {**body, "result_sha256": content_sha256(body)}


def _result(command, baseline):
    return _seal_result(
        {
            "schema_version": "local-image-informative-lineart-extraction-result/1.0",
            "run_id": command.run_id,
            "command_sha256": command.command_sha256,
            "extractor": command.extractor.model_dump(mode="json"),
            "preprocessing_policy": command.preprocessing_policy,
            "status": "SUCCEEDED",
            "error_code": None,
            "runtime": _runtime(),
            "outputs": [
                {
                    "case_id": case.case_id,
                    "reference_sha256": case.reference_image.sha256,
                    "lineart_member_path": f"outputs/lineart/{case.case_id}.png",
                    "lineart_sha256": _sha(b"fake-L"),
                    "lineart_size_bytes": 10,
                    "conditioning_member_path": f"outputs/conditioning/{case.case_id}.png",
                    "conditioning_sha256": _sha(b"fake-RGB"),
                    "conditioning_size_bytes": 10,
                    "width_px": 832,
                    "height_px": 512,
                    "lineart_mode": "L",
                    "conditioning_mode": "RGB",
                    "duration_ms": 10,
                    "peak_gpu_memory_bytes": 100,
                }
                for case in select_informative_lineart_cases(command, baseline)
            ],
            "started_at": "2026-10-04T00:00:01Z",
            "completed_at": "2026-10-04T00:00:02Z",
            "duration_ms": 1000,
            "peak_gpu_memory_bytes": 100,
        }
    )


def test_additive_command_result_schema_identity_and_exact_original_coverage():
    command, baseline, _, _ = _command()
    value = _result(command, baseline)
    result = LocalImageInformativeLineartExtractionResult.model_validate(value)
    validate_contract("informative-lineart-extraction-command", command.model_dump(mode="json"))
    validate_contract("informative-lineart-extraction-result", value)
    validate_informative_lineart_extraction_result(command, baseline, result)
    assert command.case_ids == tuple(case.case_id for case in baseline.cases)
    assert "prompt_en" not in command.model_dump_json()
    assert baseline.conditioning_policy == "FIT_GRAYSCALE_INVERT_832X512/1.0"


@pytest.mark.parametrize(
    "fault",
    ["run", "hash", "duplicate", "order", "activation", "schema", "media", "too-many", "utc"],
)
def test_invalid_command_identity_scope_selection_and_source_contract(fault):
    command, _, _, _ = _command()
    value = command.model_dump(mode="json")
    if fault == "duplicate":
        value["case_ids"][1] = value["case_ids"][0]
    elif fault == "order":
        value["case_ids"].reverse()
    elif fault == "activation":
        value["activation_policy"] = "AUTOMATIC"
    elif fault == "schema":
        value["baseline_command"]["schema_ref"] = "eom://schemas/image-provider/wrong/1.0"
    elif fault == "media":
        value["extractor_manifest"]["media_type"] = "image/png"
    elif fault == "too-many":
        value["case_ids"] = ["imgsdxlcase_" + f"{index:032x}" for index in range(7)]
    elif fault == "utc":
        value["created_at"] = "2026-10-04T09:00:00+09:00"
    value = _seal_command(value)
    if fault == "run":
        value["run_id"] = "imglineartextractrun_" + "f" * 32
    elif fault == "hash":
        value["command_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        LocalImageInformativeLineartExtractionCommand.model_validate(value)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "duplicate",
        "order",
        "reference",
        "run",
        "model",
        "time-budget",
        "memory-budget",
    ],
)
def test_result_requires_complete_original_case_hashes_and_budgets(fault):
    command, baseline, _, _ = _command()
    value = _result(command, baseline)
    if fault == "missing":
        value["outputs"].pop()
    elif fault == "extra":
        value["outputs"].append(copy.deepcopy(value["outputs"][-1]))
    elif fault == "duplicate":
        value["outputs"][1] = copy.deepcopy(value["outputs"][0])
    elif fault == "order":
        value["outputs"].reverse()
    elif fault == "reference":
        value["outputs"][0]["reference_sha256"] = "sha256:" + "f" * 64
    elif fault == "run":
        value["run_id"] = "imglineartextractrun_" + "f" * 32
    elif fault == "model":
        value["extractor"]["manifest_sha256"] = "sha256:" + "f" * 64
    elif fault == "time-budget":
        value["duration_ms"] = command.budget.maximum_duration_ms + 1
    else:
        value["peak_gpu_memory_bytes"] = command.budget.maximum_peak_gpu_memory_bytes + 1
    with pytest.raises(ValueError):
        result = LocalImageInformativeLineartExtractionResult.model_validate(_seal_result(value))
        validate_informative_lineart_extraction_result(command, baseline, result)


def test_terminal_failure_is_an_execution_prefix_not_an_arbitrary_subset():
    command, baseline, _, _ = _command()
    value = _result(command, baseline)
    value.update(status="FAILED", error_code="LINEART_EXTRACTION_EXEC_FAILED")
    value["outputs"] = value["outputs"][:1]
    result = LocalImageInformativeLineartExtractionResult.model_validate(_seal_result(value))
    validate_informative_lineart_extraction_result(command, baseline, result)
    value["outputs"] = _result(command, baseline)["outputs"][1:]
    result = LocalImageInformativeLineartExtractionResult.model_validate(_seal_result(value))
    with pytest.raises(ValueError, match="prefix"):
        validate_informative_lineart_extraction_result(command, baseline, result)


@pytest.mark.parametrize("fault", ["missing", "future"])
def test_original_selection_never_substitutes_latest(fault):
    command, baseline, _, _ = _command()
    changes = (
        {"case_ids": ("imgsdxlcase_" + "f" * 32,)}
        if fault == "missing"
        else {"created_at": "2026-10-02T00:00:00Z"}
    )
    command = LocalImageInformativeLineartExtractionCommand.model_validate(
        _seal_command({**command.model_dump(mode="json"), **changes})
    )
    with pytest.raises(ValueError, match="baseline mismatch"):
        select_informative_lineart_cases(command, baseline)


def test_canonical_and_packaged_extraction_schemas_are_identical():
    root = Path(__file__).resolve().parents[2]
    for family in ("command", "result"):
        filename = f"local-image-informative-lineart-extraction-{family}-v1.schema.json"
        assert (root / "schemas/image-provider" / filename).read_bytes() == (
            root / "packages/image_contracts/eom_image_contracts/schemas" / filename
        ).read_bytes()
