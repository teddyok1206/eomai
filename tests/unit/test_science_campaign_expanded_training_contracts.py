from __future__ import annotations

import copy

import pytest
from eom_image_contracts import (
    LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    LocalImageScienceCampaignLoraMicroEvaluationResultV2,
    LocalImageScienceCampaignLoraMicroProbeCommandV2,
    LocalImageScienceCampaignLoraMicroProbePlanV2,
    LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
    LocalImageScienceVisualCampaignCropSetV2,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_science_campaign_micro_evaluation_command_v2,
    validate_science_campaign_micro_evaluation_result_v2,
    validate_science_campaign_micro_probe_plan_sources_v2,
    validate_science_campaign_micro_probe_worker_result_v2,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from tests.unit.test_science_campaign_micro_training_contracts import _plan_value
from tests.unit.test_science_corpus_visual_contracts import (
    _campaign_crop_successor_values,
    _sha,
)


def _rebind_member(value: dict[str, object]) -> None:
    body = {key: item for key, item in value.items() if key not in {"sample_id", "member_path"}}
    identity = content_sha256(body).removeprefix("sha256:")
    value["sample_id"] = "imgsciviscampaigncrop_" + identity[:32]
    value["member_path"] = f"crops/{value['sample_id']}.png"


def _clone_member(
    source: dict[str, object],
    *,
    suffix: int,
    document_id: str,
    exam_group_sha256: str,
) -> dict[str, object]:
    value = copy.deepcopy(source)
    value["parent_candidate_id"] = f"imgsciviscandidate_{suffix:032x}"
    value["parent_candidate_sha256"] = f"sha256:{suffix + 100:064x}"
    value["document_id"] = document_id
    value["exam_group_sha256"] = exam_group_sha256
    value["sha256"] = f"sha256:{suffix + 200:064x}"
    value["size_bytes"] = 2048 + suffix
    value["perceptual_hash"] = f"{suffix + 300:016x}"
    if value["source_kind"] == "REFINED":
        value["refinement_id"] = f"imgsciviscampaignrefine_{suffix:032x}"
    _rebind_member(value)
    return value


def _expanded_crop_set_value() -> dict[str, object]:
    value = copy.deepcopy(_campaign_crop_successor_values()[-1])
    members = value["members"]
    assert isinstance(members, list)
    by_partition = {
        partition: [member for member in members if member["partition"] == partition]
        for partition in ("TRAIN", "VALIDATION", "HOLDOUT")
    }
    train_first = by_partition["TRAIN"][0]
    train_second = by_partition["TRAIN"][1]
    validation = by_partition["VALIDATION"][0]
    holdout = by_partition["HOLDOUT"][0]
    additions = [
        _clone_member(
            train_first,
            suffix=1001 + index,
            document_id=str(source["document_id"]),
            exam_group_sha256=str(source["exam_group_sha256"]),
        )
        for index, source in enumerate((train_first, train_first, train_second, train_second))
    ]
    additions.extend(
        _clone_member(
            validation,
            suffix=1101 + index,
            document_id=(str(validation["document_id"]) if index < 2 else "sciencedoc_" + "e" * 32),
            exam_group_sha256=str(validation["exam_group_sha256"]),
        )
        for index in range(3)
    )
    additions.extend(
        _clone_member(
            holdout,
            suffix=1201 + index,
            document_id=str(holdout["document_id"]),
            exam_group_sha256=str(holdout["exam_group_sha256"]),
        )
        for index in range(2)
    )
    members.extend(additions)
    members.sort(key=lambda member: str(member["sample_id"]))
    value["schema_version"] = "local-image-science-visual-campaign-crop-set/1.1"
    value["member_policy"] = {
        "partition_policy": "PINNED_SOURCE_GROUP_V1",
        "max_members_per_document": 3,
        "max_members_per_exam_group": 4,
    }
    body = {
        key: item for key, item in value.items() if key not in {"crop_set_id", "crop_set_sha256"}
    }
    value["crop_set_id"] = (
        "imgsciviscampaigncropset_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    value["crop_set_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "crop_set_sha256"}
    )
    return value


def _expanded_plan_value() -> dict[str, object]:
    value = copy.deepcopy(_plan_value())
    crop_set = _expanded_crop_set_value()
    members = crop_set["members"]
    assert isinstance(members, list)
    value["schema_version"] = "local-image-science-campaign-lora-micro-probe-plan/1.1"
    crop_pointer = value["crop_set"]
    assert isinstance(crop_pointer, dict)
    crop_pointer["schema_ref"] = (
        "eom://schemas/image-provider/local-image-science-visual-campaign-crop-set/1.1"
    )
    value["crop_set_sha256"] = crop_set["crop_set_sha256"]
    for partition, field in (
        ("TRAIN", "training_member_ids"),
        ("VALIDATION", "validation_member_ids"),
        ("HOLDOUT", "holdout_member_ids"),
    ):
        value[field] = sorted(
            str(member["sample_id"]) for member in members if member["partition"] == partition
        )
    value["trainer_contract"] = "eom-local-image-science-campaign-lora-micro-trainer/1.1"
    value["purpose"] = "EVALUATION_ONLY_SCIENCE_CAMPAIGN_EXPANDED_PROBE"
    body = {key: item for key, item in value.items() if key not in {"probe_id", "plan_sha256"}}
    value["probe_id"] = (
        "imgscicampaignmicroprobe_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def _expanded_command_value() -> dict[str, object]:
    plan = _expanded_plan_value()
    pointer = {
        "artifact_id": "artifact_" + "7" * 32,
        "artifact_revision_id": "rev_" + "7" * 32,
        "member_path": "manifests/science-campaign-micro-probe-plan.json",
        "media_type": "application/json",
        "schema_ref": (
            "eom://schemas/image-provider/local-image-science-campaign-lora-micro-probe-plan/1.1"
        ),
        "sha256": _sha("7"),
    }
    identity = content_sha256(
        {
            "probe_plan_pointer": pointer,
            "probe_plan_sha256": plan["plan_sha256"],
            "attempt": 1,
        }
    ).removeprefix("sha256:")
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-probe-command/1.1",
        "training_run_id": "imgscicampaignmicrotrainrun_" + identity[:32],
        "probe_plan_pointer": pointer,
        "probe_plan_sha256": plan["plan_sha256"],
        "probe_plan": plan,
        "attempt": 1,
        "staged_plan_member": "inputs/science-campaign-micro-probe-plan.json",
        "staged_crop_set_member": "inputs/science-visual-campaign-crop-set.json",
        "staged_crops_root": "inputs/crops",
        "runtime_dataset_root": "runtime-dataset",
        "output_root_member": "outputs",
        "checkpoint_root_member": "checkpoints",
        "timeout_seconds": 7200,
    }
    return {**body, "command_sha256": content_sha256(body)}


def _expanded_result_value() -> dict[str, object]:
    command = _expanded_command_value()
    plan = command["probe_plan"]
    assert isinstance(plan, dict)
    crop_members = _expanded_crop_set_value()["members"]
    assert isinstance(crop_members, list)
    members = {str(member["sample_id"]): member for member in crop_members}
    training_ids = plan["training_member_ids"]
    assert isinstance(training_ids, list)
    realized = [
        {
            "sample_id": sample_id,
            "parent_candidate_id": members[sample_id]["parent_candidate_id"],
            "document_id": members[sample_id]["document_id"],
            "exam_group_sha256": members[sample_id]["exam_group_sha256"],
            "training_sample_id": f"imgtrainsample_{index + 1:032x}",
            "source_crop_sha256": members[sample_id]["sha256"],
            "realized_crop_sha256": f"sha256:{index + 100:064x}",
            "caption_sha256": members[sample_id]["caption_sha256"],
            "perceptual_hash": f"{index + 1000:016x}",
        }
        for index, sample_id in enumerate(training_ids)
    ]
    realized.sort(key=lambda sample: str(sample["training_sample_id"]))
    sample_set_sha256 = content_sha256(realized)
    adapter_body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-adapter-manifest/1.1",
        "adapter_id": "imgadapter_" + "8" * 32,
        "adapter_revision_id": "imgadapterrev_" + "9" * 32,
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "base_model": plan["base_model"],
        "probe_plan": command["probe_plan_pointer"],
        "sample_set_sha256": sample_set_sha256,
        "files": [
            {"relative_path": "adapter_config.json", "size_bytes": 128, "sha256": _sha("4")},
            {
                "relative_path": "adapter_model.safetensors",
                "size_bytes": 1024,
                "sha256": _sha("5"),
            },
        ],
        "created_at": "2026-09-26T19:10:00Z",
    }
    adapter = {**adapter_body, "manifest_sha256": content_sha256(adapter_body)}
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-probe-worker-result/1.1",
        "training_run_id": command["training_run_id"],
        "probe_plan_pointer": command["probe_plan_pointer"],
        "probe_plan_sha256": command["probe_plan_sha256"],
        "command_sha256": command["command_sha256"],
        "attempt": 1,
        "status": "SUCCEEDED",
        "adapter_manifest": adapter,
        "realized_samples": realized,
        "sample_set_sha256": sample_set_sha256,
        "error_code": None,
        "runtime": {
            **plan["dependencies"],
            "cuda_version": "13.0",
            "gpu_name": "NVIDIA RTX PRO 6000 Blackwell",
            "compute_capability": "12.0",
            "peak_gpu_memory_bytes": 1024,
        },
        "completed_steps": 200,
        "final_loss": 0.1,
        "started_at": "2026-09-26T19:02:00Z",
        "completed_at": "2026-09-26T19:10:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _expanded_evaluation_command_value() -> dict[str, object]:
    plan = _expanded_plan_value()
    training = _expanded_command_value()
    result = _expanded_result_value()
    crop_set = _expanded_crop_set_value()
    members = crop_set["members"]
    assert isinstance(members, list)
    member_map = {str(member["sample_id"]): member for member in members}
    holdout_ids = plan["holdout_member_ids"]
    assert isinstance(holdout_ids, list)
    negative = "text, labels, arrows, borders, answer marks, decorative layout"
    cases = [
        {
            "sample_id": sample_id,
            "parent_candidate_id": member_map[sample_id]["parent_candidate_id"],
            "document_id": member_map[sample_id]["document_id"],
            "exam_group_sha256": member_map[sample_id]["exam_group_sha256"],
            "positive_prompt": member_map[sample_id]["caption_en"],
            "positive_prompt_sha256": member_map[sample_id]["caption_sha256"],
            "negative_prompt": negative,
            "negative_prompt_sha256": text_sha256(negative),
            "seed": 20260926 + index,
        }
        for index, sample_id in enumerate(holdout_ids)
    ]
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-evaluation-command/1.1",
        "training_run_id": training["training_run_id"],
        "probe_plan_pointer": training["probe_plan_pointer"],
        "probe_plan_sha256": training["probe_plan_sha256"],
        "crop_set": plan["crop_set"],
        "crop_set_sha256": plan["crop_set_sha256"],
        "training_result_sha256": result["result_sha256"],
        "adapter_manifest": result["adapter_manifest"],
        "cases": cases,
        "inference_steps": 20,
        "guidance_scale": 7.5,
        "generation_width": 800,
        "generation_height": 504,
        "delivery_width": 800,
        "delivery_height": 500,
        "staged_adapter_root": "inputs/adapter",
        "output_root_member": "outputs",
        "source_commit": "f" * 40,
        "timeout_seconds": 1800,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "evaluation_run_id": "imgscicampaignmicroevalrun_" + identity[:32]}
    return {**with_id, "command_sha256": content_sha256(with_id)}


def _expanded_evaluation_result_value() -> dict[str, object]:
    command = _expanded_evaluation_command_value()
    cases = command["cases"]
    assert isinstance(cases, list)
    outputs = []
    for index, case in enumerate(cases):
        for variant in ("ADAPTER", "BASE"):
            sample_id = str(case["sample_id"])
            outputs.append(
                {
                    "sample_id": sample_id,
                    "variant": variant,
                    "member_path": f"outputs/{sample_id}-{variant.lower()}.png",
                    "sha256": f"sha256:{index * 2 + (variant == 'BASE') + 1:064x}",
                    "size_bytes": 1024,
                    "width_px": 800,
                    "height_px": 500,
                }
            )
    outputs.sort(key=lambda output: (str(output["sample_id"]), str(output["variant"])))
    adapter = command["adapter_manifest"]
    assert isinstance(adapter, dict)
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-evaluation-result/1.1",
        "evaluation_run_id": command["evaluation_run_id"],
        "command_sha256": command["command_sha256"],
        "training_result_sha256": command["training_result_sha256"],
        "adapter_manifest_sha256": adapter["manifest_sha256"],
        "status": "SUCCEEDED",
        "outputs": outputs,
        "error_code": None,
        "started_at": "2026-09-26T19:11:00Z",
        "completed_at": "2026-09-26T19:12:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def test_expanded_campaign_contracts_bind_16_4_4_and_allow_bounded_groups() -> None:
    crop_value = _expanded_crop_set_value()
    plan_value = _expanded_plan_value()
    command_value = _expanded_command_value()
    result_value = _expanded_result_value()
    for contract, value in (
        ("science-visual-campaign-crop-set-v2", crop_value),
        ("science-campaign-lora-micro-probe-plan-v2", plan_value),
        ("science-campaign-lora-micro-probe-command-v2", command_value),
        ("science-campaign-lora-micro-probe-worker-result-v2", result_value),
    ):
        validate_contract(contract, value)
    crop_set = LocalImageScienceVisualCampaignCropSetV2.model_validate(crop_value)
    plan = LocalImageScienceCampaignLoraMicroProbePlanV2.model_validate(plan_value)
    command = LocalImageScienceCampaignLoraMicroProbeCommandV2.model_validate(command_value)
    result = LocalImageScienceCampaignLoraMicroProbeWorkerResultV2.model_validate(result_value)
    validate_science_campaign_micro_probe_plan_sources_v2(plan, crop_set)
    validate_science_campaign_micro_probe_worker_result_v2(command, result)
    assert (
        len(plan.training_member_ids),
        len(plan.validation_member_ids),
        len(plan.holdout_member_ids),
    ) == (
        16,
        4,
        4,
    )
    assert len(result.realized_samples) == 16


def test_expanded_campaign_crop_set_rejects_group_partition_leakage() -> None:
    value = _expanded_crop_set_value()
    members = value["members"]
    assert isinstance(members, list)
    train = next(member for member in members if member["partition"] == "TRAIN")
    validation = next(member for member in members if member["partition"] == "VALIDATION")
    validation["exam_group_sha256"] = train["exam_group_sha256"]
    _rebind_member(validation)
    members.sort(key=lambda member: str(member["sample_id"]))
    body = {
        key: item for key, item in value.items() if key not in {"crop_set_id", "crop_set_sha256"}
    }
    value["crop_set_id"] = (
        "imgsciviscampaigncropset_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    value["crop_set_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "crop_set_sha256"}
    )
    with pytest.raises(ValueError, match="crosses an exam-group partition"):
        LocalImageScienceVisualCampaignCropSetV2.model_validate(value)


def test_expanded_campaign_evaluation_requires_four_paired_holdouts() -> None:
    command_value = _expanded_evaluation_command_value()
    result_value = _expanded_evaluation_result_value()
    validate_contract("science-campaign-lora-micro-evaluation-command-v2", command_value)
    validate_contract("science-campaign-lora-micro-evaluation-result-v2", result_value)
    command = LocalImageScienceCampaignLoraMicroEvaluationCommandV2.model_validate(command_value)
    result = LocalImageScienceCampaignLoraMicroEvaluationResultV2.model_validate(result_value)
    validate_science_campaign_micro_evaluation_command_v2(
        LocalImageScienceCampaignLoraMicroProbePlanV2.model_validate(_expanded_plan_value()),
        LocalImageScienceVisualCampaignCropSetV2.model_validate(_expanded_crop_set_value()),
        LocalImageScienceCampaignLoraMicroProbeWorkerResultV2.model_validate(
            _expanded_result_value()
        ),
        command,
    )
    validate_science_campaign_micro_evaluation_result_v2(command, result)
    assert len(result.outputs) == 8

    invalid = copy.deepcopy(result_value)
    outputs = invalid["outputs"]
    assert isinstance(outputs, list)
    outputs.pop()
    invalid["result_sha256"] = content_sha256(
        {key: item for key, item in invalid.items() if key != "result_sha256"}
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("science-campaign-lora-micro-evaluation-result-v2", invalid)
    with pytest.raises(ValueError, match="incomplete"):
        LocalImageScienceCampaignLoraMicroEvaluationResultV2.model_validate(invalid)
