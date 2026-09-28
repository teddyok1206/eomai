from __future__ import annotations

import copy
from argparse import Namespace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    LocalImageModelPointer,
    LocalImageScienceCampaignLoraMicroEvaluationCommandV3,
    LocalImageScienceCampaignLoraMicroEvaluationResultV3,
    LocalImageScienceCampaignLoraMicroProbeCommandV3,
    LocalImageScienceCampaignLoraMicroProbePlanV3,
    LocalImageScienceCampaignLoraMicroProbeWorkerResultV3,
    LocalImageScienceObjectLineArtCropSet,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_science_campaign_micro_evaluation_command_v3,
    validate_science_campaign_micro_evaluation_result_v3,
    validate_science_campaign_micro_probe_plan_sources_v3,
    validate_science_campaign_micro_probe_worker_result_v3,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from scripts.image_trainer import stage_science_campaign_micro_evaluation as stage_evaluation
from scripts.image_trainer import stage_science_campaign_micro_probe as stage
from tests.unit.test_science_campaign_micro_training_contracts import _plan_value
from tests.unit.test_science_corpus_visual_contracts import _object_line_art_values, _pointer, _sha


def _crop_set_value() -> dict[str, object]:
    return copy.deepcopy(_object_line_art_values()[-1])


def _line_art_plan_value() -> dict[str, object]:
    value = copy.deepcopy(_plan_value())
    crop_set = _crop_set_value()
    members = crop_set["members"]
    assert isinstance(members, list)
    value["schema_version"] = "local-image-science-campaign-lora-micro-probe-plan/1.2"
    value["crop_set"] = _pointer(
        "8",
        member_path="manifests/science-object-line-art-crop-set.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0"
        ),
        sha256=content_sha256(crop_set),
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
    value["trainer_contract"] = "eom-local-image-science-campaign-lora-micro-trainer/1.2"
    value["purpose"] = "EVALUATION_ONLY_SCIENCE_OBJECT_LINE_ART_PROBE"
    body = {key: item for key, item in value.items() if key not in {"probe_id", "plan_sha256"}}
    value["probe_id"] = (
        "imgscicampaignmicroprobe_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def _line_art_command_value() -> dict[str, object]:
    plan = _line_art_plan_value()
    pointer = _pointer(
        "7",
        member_path="manifests/science-campaign-micro-probe-plan.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-campaign-lora-micro-probe-plan/1.2"
        ),
    )
    identity = content_sha256(
        {
            "probe_plan_pointer": pointer,
            "probe_plan_sha256": plan["plan_sha256"],
            "attempt": 1,
        }
    ).removeprefix("sha256:")
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-probe-command/1.2",
        "training_run_id": "imgscicampaignmicrotrainrun_" + identity[:32],
        "probe_plan_pointer": pointer,
        "probe_plan_sha256": plan["plan_sha256"],
        "probe_plan": plan,
        "attempt": 1,
        "staged_plan_member": "inputs/science-campaign-micro-probe-plan.json",
        "staged_crop_set_member": "inputs/science-object-line-art-crop-set.json",
        "staged_crops_root": "inputs/crops",
        "runtime_dataset_root": "runtime-dataset",
        "output_root_member": "outputs",
        "checkpoint_root_member": "checkpoints",
        "timeout_seconds": 7200,
    }
    return {**body, "command_sha256": content_sha256(body)}


def _line_art_result_value() -> dict[str, object]:
    command = _line_art_command_value()
    plan = command["probe_plan"]
    assert isinstance(plan, dict)
    crop_members = _crop_set_value()["members"]
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
        "schema_version": "local-image-science-campaign-lora-micro-adapter-manifest/1.2",
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
        "created_at": "2026-09-28T13:10:00Z",
    }
    adapter = {**adapter_body, "manifest_sha256": content_sha256(adapter_body)}
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-probe-worker-result/1.2",
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
        "started_at": "2026-09-28T13:02:00Z",
        "completed_at": "2026-09-28T13:10:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _line_art_evaluation_command_value() -> dict[str, object]:
    plan = _line_art_plan_value()
    training = _line_art_command_value()
    result = _line_art_result_value()
    members = _crop_set_value()["members"]
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
            "seed": 20260928 + index,
        }
        for index, sample_id in enumerate(holdout_ids)
    ]
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-evaluation-command/1.2",
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


def _line_art_evaluation_result_value() -> dict[str, object]:
    command = _line_art_evaluation_command_value()
    cases = command["cases"]
    assert isinstance(cases, list)
    outputs = []
    for index, case in enumerate(cases):
        assert isinstance(case, dict)
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
        "schema_version": "local-image-science-campaign-lora-micro-evaluation-result/1.2",
        "evaluation_run_id": command["evaluation_run_id"],
        "command_sha256": command["command_sha256"],
        "training_result_sha256": command["training_result_sha256"],
        "adapter_manifest_sha256": adapter["manifest_sha256"],
        "status": "SUCCEEDED",
        "outputs": outputs,
        "error_code": None,
        "started_at": "2026-09-28T13:11:00Z",
        "completed_at": "2026-09-28T13:12:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def test_object_line_art_training_contracts_bind_16_4_4_and_paired_holdouts() -> None:
    crop_value = _crop_set_value()
    plan_value = _line_art_plan_value()
    command_value = _line_art_command_value()
    result_value = _line_art_result_value()
    evaluation_command_value = _line_art_evaluation_command_value()
    evaluation_result_value = _line_art_evaluation_result_value()
    for contract, value in (
        ("science-object-line-art-crop-set", crop_value),
        ("science-campaign-lora-micro-probe-plan-v3", plan_value),
        ("science-campaign-lora-micro-probe-command-v3", command_value),
        ("science-campaign-lora-micro-probe-worker-result-v3", result_value),
        ("science-campaign-lora-micro-evaluation-command-v3", evaluation_command_value),
        ("science-campaign-lora-micro-evaluation-result-v3", evaluation_result_value),
    ):
        validate_contract(contract, value)

    crop_set = LocalImageScienceObjectLineArtCropSet.model_validate(crop_value)
    plan = LocalImageScienceCampaignLoraMicroProbePlanV3.model_validate(plan_value)
    command = LocalImageScienceCampaignLoraMicroProbeCommandV3.model_validate(command_value)
    result = LocalImageScienceCampaignLoraMicroProbeWorkerResultV3.model_validate(result_value)
    evaluation_command = LocalImageScienceCampaignLoraMicroEvaluationCommandV3.model_validate(
        evaluation_command_value
    )
    evaluation_result = LocalImageScienceCampaignLoraMicroEvaluationResultV3.model_validate(
        evaluation_result_value
    )
    validate_science_campaign_micro_probe_plan_sources_v3(plan, crop_set)
    validate_science_campaign_micro_probe_worker_result_v3(command, result)
    validate_science_campaign_micro_evaluation_command_v3(
        plan,
        crop_set,
        result,
        evaluation_command,
    )
    validate_science_campaign_micro_evaluation_result_v3(
        evaluation_command,
        evaluation_result,
    )
    assert (
        len(plan.training_member_ids),
        len(plan.validation_member_ids),
        len(plan.holdout_member_ids),
        len(evaluation_result.outputs),
    ) == (16, 4, 4, 8)


def test_object_line_art_plan_rejects_legacy_campaign_crop_identity() -> None:
    value = _line_art_plan_value()
    members = value["training_member_ids"]
    assert isinstance(members, list)
    members[0] = "imgsciviscampaigncrop_" + "1" * 32
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("science-campaign-lora-micro-probe-plan-v3", value)
    with pytest.raises(ValueError, match="sorted and unique"):
        LocalImageScienceCampaignLoraMicroProbePlanV3.model_validate(value)


def test_object_line_art_stage_builds_exact_v3_plan_and_command(monkeypatch) -> None:
    crop_set = LocalImageScienceObjectLineArtCropSet.model_validate(_crop_set_value())
    pointer = stage.ImageEvaluationArtifactMember.model_validate(
        _pointer(
            "8",
            member_path="manifests/science-object-line-art-crop-set.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0"
            ),
            sha256=content_sha256(_crop_set_value()),
        )
    )
    model = LocalImageModelPointer.model_validate(_line_art_plan_value()["base_model"])
    monkeypatch.setattr(
        stage.CatalogSettings,
        "from_environment",
        classmethod(lambda _cls: SimpleNamespace(local_image_provider_binding="unused")),
    )
    monkeypatch.setattr(
        stage,
        "load_local_image_provider_binding",
        lambda _path: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(
        stage,
        "_trainer_dependencies",
        lambda: _line_art_plan_value()["dependencies"],
    )
    arguments = Namespace(
        authorization_reference_sha256=crop_set.training_authorization.sha256,
        authorized_at=datetime(2026, 9, 28, 12, 10, tzinfo=UTC),
        authorized_by="operator_eom",
        created_at=datetime(2026, 9, 28, 12, 11, tzinfo=UTC),
        created_by="orchestrator_line_art_probe",
        seed=20260928,
        source_commit="f" * 40,
    )

    plan = stage._build_plan(
        args=arguments,
        crop_set_pointer=pointer,
        crop_set=crop_set,
    )
    plan_pointer = stage.ImageEvaluationArtifactMember.model_validate(
        _pointer(
            "7",
            member_path="manifests/science-campaign-micro-probe-plan.json",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-campaign-lora-micro-probe-plan/1.2"
            ),
            sha256=content_sha256(plan.model_dump(mode="json")),
        )
    )
    command = stage._build_command(plan=plan, plan_pointer=plan_pointer)

    assert isinstance(plan, LocalImageScienceCampaignLoraMicroProbePlanV3)
    assert isinstance(command, LocalImageScienceCampaignLoraMicroProbeCommandV3)
    assert plan.activation_policy == "FORBIDDEN"
    assert plan.purpose == "EVALUATION_ONLY_SCIENCE_OBJECT_LINE_ART_PROBE"
    assert (
        len(plan.training_member_ids),
        len(plan.validation_member_ids),
        len(plan.holdout_member_ids),
    ) == (
        16,
        4,
        4,
    )
    assert command.staged_crop_set_member == "inputs/science-object-line-art-crop-set.json"


def test_object_line_art_evaluation_stage_preserves_human_subjects_and_builds_pairs() -> None:
    training = LocalImageScienceCampaignLoraMicroProbeCommandV3.model_validate(
        _line_art_command_value()
    )
    result = LocalImageScienceCampaignLoraMicroProbeWorkerResultV3.model_validate(
        _line_art_result_value()
    )
    crop_set = LocalImageScienceObjectLineArtCropSet.model_validate(_crop_set_value())
    cases = stage_evaluation._cases(training.probe_plan, crop_set)
    command = stage_evaluation._build_command(
        training=training,
        result=result,
        plan=training.probe_plan,
        crop_set=crop_set,
        cases=cases,
        source_commit="f" * 40,
    )

    assert isinstance(command, LocalImageScienceCampaignLoraMicroEvaluationCommandV3)
    assert len(command.cases) == 4
    assert all("people" not in case.negative_prompt for case in command.cases)
    assert all("cropped subject" in case.negative_prompt for case in command.cases)
