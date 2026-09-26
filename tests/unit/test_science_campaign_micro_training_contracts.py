from __future__ import annotations

import copy
from argparse import Namespace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    LocalImageModelPointer,
    LocalImageScienceCampaignLoraMicroEvaluationCommand,
    LocalImageScienceCampaignLoraMicroEvaluationResult,
    LocalImageScienceCampaignLoraMicroProbeCommand,
    LocalImageScienceCampaignLoraMicroProbePlan,
    LocalImageScienceCampaignLoraMicroProbeWorkerResult,
    LocalImageScienceVisualCampaignCropSet,
    content_sha256,
    validate_contract,
    validate_science_campaign_micro_evaluation_command,
    validate_science_campaign_micro_evaluation_result,
    validate_science_campaign_micro_probe_plan_sources,
    validate_science_campaign_micro_probe_worker_result,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from scripts.image_trainer import stage_science_campaign_micro_evaluation as stage_evaluation
from scripts.image_trainer import stage_science_campaign_micro_probe as stage
from tests.unit.test_science_corpus_visual_contracts import (
    _campaign_crop_successor_values,
    _pointer,
    _sha,
)


def _plan_value() -> dict[str, object]:
    crop_set = _campaign_crop_successor_values()[-1]
    members = crop_set["members"]
    assert isinstance(members, list)
    by_partition = {
        partition: sorted(
            str(value["sample_id"]) for value in members if value["partition"] == partition
        )
        for partition in ("TRAIN", "VALIDATION", "HOLDOUT")
    }
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-probe-plan/1.0",
        "crop_set": _pointer(
            "8",
            member_path="manifests/science-visual-campaign-crop-set.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-campaign-crop-set/1.0"
            ),
        ),
        "crop_set_sha256": crop_set["crop_set_sha256"],
        "base_model": {
            "model_id": "imgmodel_" + "b" * 32,
            "model_revision_id": "imgmodelrev_" + "c" * 32,
            "manifest_sha256": _sha("d"),
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        },
        "training_member_ids": by_partition["TRAIN"],
        "validation_member_ids": by_partition["VALIDATION"],
        "holdout_member_ids": by_partition["HOLDOUT"],
        "preprocessing_revision": "local-image-science-crop-preprocess/1.0",
        "trainer_contract": "eom-local-image-science-campaign-lora-micro-trainer/1.0",
        "dependencies": {
            "python_version": "3.11.13",
            "torch_version": "2.8.0",
            "diffusers_version": "0.35.1",
            "transformers_version": "4.56.1",
            "accelerate_version": "1.10.1",
            "peft_version": "0.17.1",
            "bitsandbytes_version": "0.47.0",
        },
        "hyperparameters": {
            "adapter_type": "UNET_LORA",
            "rank": 8,
            "alpha": 8,
            "resolution_width": 768,
            "resolution_height": 512,
            "train_batch_size": 1,
            "gradient_accumulation_steps": 4,
            "gradient_checkpointing": True,
            "mixed_precision": "fp16",
            "optimizer": "adamw_8bit",
            "learning_rate": "1e-4",
            "max_train_steps": 200,
            "checkpointing_steps": 200,
            "random_flip": False,
            "train_text_encoders": False,
            "train_vae": False,
        },
        "seed": 20260926,
        "purpose": "EVALUATION_ONLY_SCIENCE_CAMPAIGN_MICRO_PROBE",
        "activation_policy": "FORBIDDEN",
        "authorized_at": "2026-09-26T18:00:00Z",
        "authorized_by": "operator_eom",
        "authorization_reference_sha256": _sha("e"),
        "created_at": "2026-09-26T18:01:00Z",
        "created_by": "orchestrator_campaign_probe",
        "source_commit": "f" * 40,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "probe_id": "imgscicampaignmicroprobe_" + identity[:32]}
    return {**with_id, "plan_sha256": content_sha256(with_id)}


def _command_value() -> dict[str, object]:
    plan = _plan_value()
    pointer = _pointer(
        "7",
        member_path="manifests/science-campaign-micro-probe-plan.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-campaign-lora-micro-probe-plan/1.0"
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
        "schema_version": "local-image-science-campaign-lora-micro-probe-command/1.0",
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


def _result_value() -> dict[str, object]:
    command = _command_value()
    plan = command["probe_plan"]
    assert isinstance(plan, dict)
    member_ids = plan["training_member_ids"]
    assert isinstance(member_ids, list)
    crop_members = _campaign_crop_successor_values()[-1]["members"]
    assert isinstance(crop_members, list)
    members = {str(value["sample_id"]): value for value in crop_members}
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
        for index, sample_id in enumerate(member_ids)
    ]
    realized.sort(key=lambda value: str(value["training_sample_id"]))
    sample_set_sha256 = content_sha256(realized)
    adapter_body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-adapter-manifest/1.0",
        "adapter_id": "imgadapter_" + "2" * 32,
        "adapter_revision_id": "imgadapterrev_" + "3" * 32,
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
        "created_at": "2026-09-26T18:10:00Z",
    }
    adapter = {**adapter_body, "manifest_sha256": content_sha256(adapter_body)}
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-probe-worker-result/1.0",
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
        "final_loss": 0.125,
        "started_at": "2026-09-26T18:02:00Z",
        "completed_at": "2026-09-26T18:10:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _evaluation_command_value() -> dict[str, object]:
    training = _command_value()
    result = _result_value()
    plan = LocalImageScienceCampaignLoraMicroProbePlan.model_validate(training["probe_plan"])
    crop_set = LocalImageScienceVisualCampaignCropSet.model_validate(
        _campaign_crop_successor_values()[-1]
    )
    cases = stage_evaluation._cases(plan, crop_set)
    return stage_evaluation._build_command(
        training=LocalImageScienceCampaignLoraMicroProbeCommand.model_validate(training),
        result=LocalImageScienceCampaignLoraMicroProbeWorkerResult.model_validate(result),
        plan=plan,
        crop_set=crop_set,
        cases=cases,
        source_commit="f" * 40,
    ).model_dump(mode="json")


def _evaluation_result_value() -> dict[str, object]:
    command = _evaluation_command_value()
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
    outputs.sort(key=lambda value: (str(value["sample_id"]), str(value["variant"])))
    adapter = command["adapter_manifest"]
    assert isinstance(adapter, dict)
    body: dict[str, object] = {
        "schema_version": "local-image-science-campaign-lora-micro-evaluation-result/1.0",
        "evaluation_run_id": command["evaluation_run_id"],
        "command_sha256": command["command_sha256"],
        "training_result_sha256": command["training_result_sha256"],
        "adapter_manifest_sha256": adapter["manifest_sha256"],
        "status": "SUCCEEDED",
        "outputs": outputs,
        "error_code": None,
        "started_at": "2026-09-26T18:11:00Z",
        "completed_at": "2026-09-26T18:12:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def test_campaign_micro_contracts_bind_exact_partitions_and_result() -> None:
    plan_value = _plan_value()
    command_value = _command_value()
    result_value = _result_value()
    for contract, value in (
        ("science-campaign-lora-micro-probe-plan", plan_value),
        ("science-campaign-lora-micro-probe-command", command_value),
        ("science-campaign-lora-micro-probe-worker-result", result_value),
    ):
        validate_contract(contract, value)
    plan = LocalImageScienceCampaignLoraMicroProbePlan.model_validate(plan_value)
    command = LocalImageScienceCampaignLoraMicroProbeCommand.model_validate(command_value)
    result = LocalImageScienceCampaignLoraMicroProbeWorkerResult.model_validate(result_value)
    crop_set = LocalImageScienceVisualCampaignCropSet.model_validate(
        _campaign_crop_successor_values()[-1]
    )
    validate_science_campaign_micro_probe_plan_sources(plan, crop_set)
    validate_science_campaign_micro_probe_worker_result(command, result)
    assert len(result.realized_samples) == 12
    assert result.adapter_manifest is not None
    assert result.adapter_manifest.activation_policy == "FORBIDDEN"


def test_campaign_micro_plan_rejects_partition_leakage() -> None:
    value = _plan_value()
    training = value["training_member_ids"]
    holdout = value["holdout_member_ids"]
    assert isinstance(training, list) and isinstance(holdout, list)
    training[0] = holdout[0]
    body = {key: item for key, item in value.items() if key not in {"probe_id", "plan_sha256"}}
    value["probe_id"] = (
        "imgscicampaignmicroprobe_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValueError, match="partitions overlap"):
        LocalImageScienceCampaignLoraMicroProbePlan.model_validate(value)


def test_campaign_micro_result_requires_parent_candidate_identity() -> None:
    value = _result_value()
    realized = value["realized_samples"]
    assert isinstance(realized, list)
    realized[0].pop("parent_candidate_id")
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("science-campaign-lora-micro-probe-worker-result", value)
    with pytest.raises(ValueError):
        LocalImageScienceCampaignLoraMicroProbeWorkerResult.model_validate(value)


def test_campaign_micro_contract_rejects_legacy_member_identity() -> None:
    value = copy.deepcopy(_plan_value())
    members = value["training_member_ids"]
    assert isinstance(members, list)
    members[0] = "imgsciviscandidate_" + "1" * 32
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("science-campaign-lora-micro-probe-plan", value)


def test_campaign_micro_stage_plan_binds_exact_authorization_and_partitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crop_set = LocalImageScienceVisualCampaignCropSet.model_validate(
        _campaign_crop_successor_values()[-1]
    )
    pointer = stage.ImageEvaluationArtifactMember.model_validate(
        _pointer(
            "8",
            member_path="manifests/science-visual-campaign-crop-set.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-campaign-crop-set/1.0"
            ),
        )
    )
    model = LocalImageModelPointer.model_validate(_plan_value()["base_model"])
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
        lambda: _plan_value()["dependencies"],
    )
    arguments = Namespace(
        authorization_reference_sha256=crop_set.training_authorization.sha256,
        authorized_at=datetime(2026, 9, 26, 18, 0, tzinfo=UTC),
        authorized_by="operator_eom",
        created_at=datetime(2026, 9, 26, 18, 1, tzinfo=UTC),
        created_by="orchestrator_campaign_probe",
        seed=20260926,
        source_commit="f" * 40,
    )

    plan = stage._build_plan(
        args=arguments,
        crop_set_pointer=pointer,
        crop_set=crop_set,
    )

    assert len(plan.training_member_ids) == 12
    assert len(plan.validation_member_ids) == 1
    assert len(plan.holdout_member_ids) == 2
    assert plan.activation_policy == "FORBIDDEN"
    arguments.authorization_reference_sha256 = _sha("0")
    with pytest.raises(
        stage.ScienceCampaignMicroProbeStageError,
        match="IMAGE_TRAINING_AUTHORIZATION_MISMATCH",
    ):
        stage._build_plan(
            args=arguments,
            crop_set_pointer=pointer,
            crop_set=crop_set,
        )


def test_campaign_evaluation_contracts_bind_exact_holdout_pairs() -> None:
    command_value = _evaluation_command_value()
    result_value = _evaluation_result_value()
    validate_contract("science-campaign-lora-micro-evaluation-command", command_value)
    validate_contract("science-campaign-lora-micro-evaluation-result", result_value)
    command = LocalImageScienceCampaignLoraMicroEvaluationCommand.model_validate(command_value)
    result = LocalImageScienceCampaignLoraMicroEvaluationResult.model_validate(result_value)
    training = LocalImageScienceCampaignLoraMicroProbeWorkerResult.model_validate(_result_value())
    plan = LocalImageScienceCampaignLoraMicroProbePlan.model_validate(_plan_value())
    crop_set = LocalImageScienceVisualCampaignCropSet.model_validate(
        _campaign_crop_successor_values()[-1]
    )
    validate_science_campaign_micro_evaluation_command(plan, crop_set, training, command)
    validate_science_campaign_micro_evaluation_result(command, result)
    assert {value.variant for value in result.outputs} == {"ADAPTER", "BASE"}
    assert {value.sample_id for value in result.outputs} == set(plan.holdout_member_ids)


def test_campaign_evaluation_rejects_training_member_leakage() -> None:
    value = _evaluation_command_value()
    cases = value["cases"]
    assert isinstance(cases, list)
    cases[0]["sample_id"] = str(_plan_value()["training_member_ids"][0])
    body = {
        key: item
        for key, item in value.items()
        if key not in {"evaluation_run_id", "command_sha256"}
    }
    identity = content_sha256(body).removeprefix("sha256:")
    value["evaluation_run_id"] = "imgscicampaignmicroevalrun_" + identity[:32]
    value["command_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "command_sha256"}
    )
    command = LocalImageScienceCampaignLoraMicroEvaluationCommand.model_validate(value)
    with pytest.raises(ValueError, match="exact holdout coverage"):
        validate_science_campaign_micro_evaluation_command(
            LocalImageScienceCampaignLoraMicroProbePlan.model_validate(_plan_value()),
            LocalImageScienceVisualCampaignCropSet.model_validate(
                _campaign_crop_successor_values()[-1]
            ),
            LocalImageScienceCampaignLoraMicroProbeWorkerResult.model_validate(_result_value()),
            command,
        )


def test_campaign_evaluation_result_rejects_missing_pair() -> None:
    value = _evaluation_result_value()
    outputs = value["outputs"]
    assert isinstance(outputs, list)
    outputs.pop()
    body = {key: item for key, item in value.items() if key != "result_sha256"}
    value["result_sha256"] = content_sha256(body)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("science-campaign-lora-micro-evaluation-result", value)
    with pytest.raises(ValueError, match="incomplete"):
        LocalImageScienceCampaignLoraMicroEvaluationResult.model_validate(value)
