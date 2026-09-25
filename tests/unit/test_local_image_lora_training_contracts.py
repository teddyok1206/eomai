from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageLoraAdapterManifest,
    LocalImageLoraCheckpointManifest,
    LocalImageLoraTrainingCommand,
    LocalImageLoraTrainingPlan,
    LocalImageLoraTrainingReceipt,
    LocalImageLoraTrainingWorkerResult,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCandidateInventory,
    LocalImageTrainingDatasetManifest,
    LocalImageTrainingEligibilityReview,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_lora_checkpoint_manifest,
    validate_lora_training_plan,
    validate_lora_training_receipt,
    validate_lora_training_worker_result,
    validate_training_dataset_authorization,
    validate_training_dataset_inventory,
    validate_training_inventory_review,
)
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _pointer(
    character: str,
    *,
    member_path: str,
    schema_ref: str,
    media_type: str = "application/json",
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + character * 32,
        "artifact_revision_id": "rev_" + character * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": _sha(character),
    }


def _model_pointer() -> dict[str, object]:
    return {
        "model_id": "imgmodel_" + "1" * 32,
        "model_revision_id": "imgmodelrev_" + "2" * 32,
        "manifest_sha256": _sha("3"),
        "provider_family": "diffusers-ssd-1b",
        "runtime_contract_version": "eom-local-image-provider/1.0",
    }


def _source_snapshot() -> dict[str, object]:
    return {
        "graph_revision_id": "graphrev_" + "4" * 32,
        "graph_snapshot_sha256": _sha("5"),
        "graph_manifest_sha256": _sha("6"),
        "target_count": 520,
        "target_set_sha256": _sha("7"),
    }


def _rights_policy() -> dict[str, object]:
    return {
        "rights_policy_id": "rightspolicy_" + "8" * 32,
        "rights_policy_revision_id": "rightspolicyrev_" + "9" * 32,
        "rights_policy_sha256": _sha("a"),
    }


def _authorization_value() -> dict[str, object]:
    body = {
        "schema_version": "local-image-training-authorization/1.0",
        "authorization_id": "imgtrainauth_" + "b" * 32,
        "authorization_revision_id": "imgtrainauthrev_" + "c" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "source_snapshot": _source_snapshot(),
        "rights_policies": [_rights_policy()],
        "permitted_use": "INTERNAL_LORA_TRAINING",
        "derivative_output": "LORA_ADAPTER_ONLY",
        "state": "APPROVED",
        "approved_at": "2026-09-25T02:00:00Z",
        "approved_by": "operator_test",
    }
    return {**body, "authorization_sha256": content_sha256(body)}


def _sample(index: int) -> dict[str, object]:
    identity = f"{index + 1000:032x}"
    caption = f"Side view of one nonhuman fossil specimen number {index}."
    crop_sha = "sha256:" + hashlib.sha256(f"crop-{index}".encode()).hexdigest()
    return {
        "training_sample_id": "imgtrainsample_" + identity,
        "item_revision_id": "itemrev_" + f"{index + 2000:032x}",
        "extraction_result": _pointer(
            f"{(index % 15) + 1:x}",
            member_path=f"extraction/{identity}.json",
            schema_ref="eom://schemas/catalog/legacy-item-extraction-result/1.0",
        ),
        "source_anchor_id": "assessmentanchor_" + f"{index + 3000:032x}",
        "visual_pattern_ids": ["visualpattern_" + f"{index + 4000:032x}"],
        "source_page_image": _pointer(
            f"{((index + 1) % 15) + 1:x}",
            member_path=f"pages/{identity}.png",
            schema_ref="eom://schemas/catalog/assessment-page-image/1.0",
            media_type="image/png",
        ),
        "bounding_box": {"left": 100, "top": 200, "right": 9000, "bottom": 8000},
        "rights_policy": _rights_policy(),
        "representation_kind": "PHOTOGRAPH",
        "rendering_mode": "RASTER",
        "crop_member": {
            "member_path": f"samples/imgtrainsample_{identity}.png",
            "media_type": "image/png",
            "width_px": 768,
            "height_px": 512,
            "size_bytes": 1024 + index,
            "sha256": crop_sha,
        },
        "caption_en": caption,
        "caption_sha256": text_sha256(caption),
        "perceptual_hash": f"{index:016x}",
    }


def _candidate(index: int) -> dict[str, object]:
    sample = _sample(index)
    return {
        "candidate_id": "imgtraincandidate_" + f"{index + 1000:032x}",
        "item_revision_id": sample["item_revision_id"],
        "extraction_result": sample["extraction_result"],
        "source_anchor_id": sample["source_anchor_id"],
        "visual_pattern_ids": sample["visual_pattern_ids"],
        "source_page_image": sample["source_page_image"],
        "physical_page": index + 1,
        "bounding_box": sample["bounding_box"],
        "rights_policy": sample["rights_policy"],
        "representation_kind": sample["representation_kind"],
        "rendering_mode": sample["rendering_mode"],
        "caption_en": sample["caption_en"],
        "caption_sha256": sample["caption_sha256"],
    }


def _inventory_value() -> dict[str, object]:
    body = {
        "schema_version": "local-image-training-candidate-inventory/1.0",
        "inventory_id": "imgtraininventory_" + "a" * 32,
        "source_snapshot": _source_snapshot(),
        "holdout_evaluation_plan": _pointer(
            "c",
            member_path="manifests/evaluation-plan.json",
            schema_ref=("eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"),
        ),
        "holdout_sample_ids": ["imgsample_" + f"{index + 5000:032x}" for index in range(12)],
        "holdout_source_anchor_ids": [
            "assessmentanchor_" + f"{index + 6000:032x}" for index in range(12)
        ],
        "candidates": [_candidate(index) for index in range(100)],
        "created_at": "2026-09-25T02:03:00Z",
        "created_by": "operator_test",
    }
    return {**body, "inventory_sha256": content_sha256(body)}


def _eligibility_review_value() -> dict[str, object]:
    candidates = [_candidate(index) for index in range(100)]
    entries = [
        {
            **candidate,
            "decision": "ELIGIBLE",
            "exclusion_reasons": [],
        }
        for candidate in candidates
    ]
    body = {
        "schema_version": "local-image-training-eligibility-review/1.0",
        "review_id": "imgtrainreview_" + "b" * 32,
        "review_state": "FINAL",
        "source_snapshot": _source_snapshot(),
        "holdout_evaluation_plan": _inventory_value()["holdout_evaluation_plan"],
        "holdout_sample_ids": _inventory_value()["holdout_sample_ids"],
        "holdout_source_anchor_ids": _inventory_value()["holdout_source_anchor_ids"],
        "selection_query_revision": "local-image-lora-candidate-query/1.0",
        "eligibility_policy_revision": "local-image-lora-eligibility/1.0",
        "entries": entries,
        "projection_omissions": [],
        "eligible_candidate_set_sha256": content_sha256(candidates),
        "reviewed_at": "2026-09-25T02:04:00Z",
        "reviewed_by": "operator_test",
    }
    return {**body, "review_sha256": content_sha256(body)}


def _dataset_value() -> dict[str, object]:
    samples = [_sample(index) for index in range(100)]
    holdout_samples = ["imgsample_" + f"{index + 5000:032x}" for index in range(12)]
    holdout_anchors = ["assessmentanchor_" + f"{index + 6000:032x}" for index in range(12)]
    body = {
        "schema_version": "local-image-training-dataset-manifest/1.0",
        "dataset_id": "imgdataset_" + "d" * 32,
        "dataset_revision_id": "imgdatasetrev_" + "e" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "source_snapshot": _source_snapshot(),
        "training_authorization": _pointer(
            "b",
            member_path="manifests/training-authorization.json",
            schema_ref=("eom://schemas/image-provider/local-image-training-authorization/1.0"),
        ),
        "eligibility_review": _pointer(
            "9",
            member_path="manifests/eligibility-review.json",
            schema_ref=("eom://schemas/image-provider/local-image-training-eligibility-review/1.0"),
        ),
        "candidate_inventory": _pointer(
            "a",
            member_path="manifests/training-candidates.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-training-candidate-inventory/1.0"
            ),
        ),
        "base_model": _model_pointer(),
        "eligibility_policy_revision": "local-image-lora-eligibility/1.0",
        "holdout_evaluation_plan": _pointer(
            "c",
            member_path="manifests/evaluation-plan.json",
            schema_ref=("eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"),
        ),
        "holdout_sample_ids": holdout_samples,
        "holdout_source_anchor_ids": holdout_anchors,
        "samples": samples,
        "sample_set_sha256": content_sha256(samples),
        "created_at": "2026-09-25T02:05:00Z",
        "created_by": "operator_test",
    }
    return {**body, "dataset_sha256": content_sha256(body)}


def _plan_value() -> dict[str, object]:
    body = {
        "schema_version": "local-image-lora-training-plan/1.0",
        "training_plan_id": "imgtrainplan_" + "f" * 32,
        "dataset_manifest": _pointer(
            "d",
            member_path="manifests/training-dataset.json",
            schema_ref=("eom://schemas/image-provider/local-image-training-dataset-manifest/1.0"),
        ),
        "base_model": _model_pointer(),
        "trainer_contract": "eom-local-image-lora-trainer/1.0",
        "dependencies": {
            "python_version": "3.11.13",
            "torch_version": "2.7.1+cu128",
            "diffusers_version": "0.35.2",
            "transformers_version": "4.56.2",
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
            "max_train_steps": 800,
            "checkpointing_steps": 200,
            "random_flip": False,
            "train_text_encoders": False,
            "train_vae": False,
        },
        "seed": 20260925,
        "created_at": "2026-09-25T02:10:00Z",
        "created_by": "operator_test",
    }
    return {**body, "plan_sha256": content_sha256(body)}


def _adapter_value() -> dict[str, object]:
    body = {
        "schema_version": "local-image-lora-adapter-manifest/1.0",
        "adapter_id": "imgadapter_" + "1" * 32,
        "adapter_revision_id": "imgadapterrev_" + "2" * 32,
        "state": "CANDIDATE",
        "base_model": _model_pointer(),
        "dataset_manifest": _plan_value()["dataset_manifest"],
        "training_plan": _pointer(
            "f",
            member_path="manifests/training-plan.json",
            schema_ref=("eom://schemas/image-provider/local-image-lora-training-plan/1.0"),
        ),
        "files": [
            {
                "relative_path": "adapter_config.json",
                "size_bytes": 256,
                "sha256": _sha("1"),
            },
            {
                "relative_path": "adapter_model.safetensors",
                "size_bytes": 65536,
                "sha256": _sha("2"),
            },
        ],
        "created_at": "2026-09-25T02:30:00Z",
    }
    return {**body, "manifest_sha256": content_sha256(body)}


def _receipt_value() -> dict[str, object]:
    body = {
        "schema_version": "local-image-lora-training-receipt/1.0",
        "training_run_id": "imgtrainrun_" + "3" * 32,
        "training_plan": _adapter_value()["training_plan"],
        "attempt": 1,
        "status": "SUCCEEDED",
        "adapter_manifest": _pointer(
            "1",
            member_path="manifests/adapter-manifest.json",
            schema_ref=("eom://schemas/image-provider/local-image-lora-adapter-manifest/1.0"),
        ),
        "error_code": None,
        "runtime": {
            **_plan_value()["dependencies"],
            "cuda_version": "12.8",
            "gpu_name": "NVIDIA GeForce RTX 5080",
            "compute_capability": "12.0",
            "peak_gpu_memory_bytes": 12_000_000_000,
        },
        "completed_steps": 800,
        "final_loss": 0.081,
        "started_at": "2026-09-25T02:15:00Z",
        "completed_at": "2026-09-25T02:30:00Z",
    }
    return {**body, "receipt_sha256": content_sha256(body)}


def _command_value() -> dict[str, object]:
    plan = _plan_value()
    body = {
        "schema_version": "local-image-lora-training-command/1.0",
        "training_run_id": "imgtrainrun_" + "3" * 32,
        "training_plan_pointer": _adapter_value()["training_plan"],
        "training_plan_sha256": plan["plan_sha256"],
        "training_plan": plan,
        "attempt": 1,
        "staged_plan_member": "inputs/training-plan.json",
        "staged_dataset_root": "inputs/dataset",
        "output_root_member": "outputs",
        "checkpoint_root_member": "checkpoints",
        "timeout_seconds": 3600,
    }
    return {**body, "command_sha256": content_sha256(body)}


def _worker_result_value() -> dict[str, object]:
    command = _command_value()
    body = {
        "schema_version": "local-image-lora-training-worker-result/1.0",
        "training_run_id": command["training_run_id"],
        "training_plan_pointer": command["training_plan_pointer"],
        "training_plan_sha256": command["training_plan_sha256"],
        "attempt": command["attempt"],
        "status": "SUCCEEDED",
        "adapter_manifest": _adapter_value(),
        "error_code": None,
        "runtime": _receipt_value()["runtime"],
        "completed_steps": 800,
        "final_loss": 0.081,
        "started_at": "2026-09-25T02:15:00Z",
        "completed_at": "2026-09-25T02:30:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _checkpoint_value() -> dict[str, object]:
    command = _command_value()
    body = {
        "schema_version": "local-image-lora-checkpoint-manifest/1.0",
        "training_run_id": command["training_run_id"],
        "training_plan_sha256": command["training_plan_sha256"],
        "attempt": command["attempt"],
        "completed_steps": 200,
        "micro_steps": 800,
        "files": [
            {
                "relative_path": "adapter_model.safetensors",
                "size_bytes": 65536,
                "sha256": _sha("4"),
            },
            {
                "relative_path": "optimizer-rng-state.pt",
                "size_bytes": 131072,
                "sha256": _sha("5"),
            },
        ],
        "created_at": "2026-09-25T02:20:00Z",
    }
    return {**body, "manifest_sha256": content_sha256(body)}


def test_training_schema_resources_are_canonical_mirrors() -> None:
    names = (
        "local-image-training-authorization-v1.schema.json",
        "local-image-training-candidate-inventory-v1.schema.json",
        "local-image-training-dataset-manifest-v1.schema.json",
        "local-image-training-eligibility-review-v1.schema.json",
        "local-image-lora-training-plan-v1.schema.json",
        "local-image-lora-adapter-manifest-v1.schema.json",
        "local-image-lora-checkpoint-manifest-v1.schema.json",
        "local-image-lora-training-receipt-v1.schema.json",
        "local-image-lora-training-command-v1.schema.json",
        "local-image-lora-training-worker-result-v1.schema.json",
    )
    for name in names:
        canonical = REPOSITORY_ROOT / "schemas/image-provider" / name
        packaged = REPOSITORY_ROOT / "packages/image_contracts/eom_image_contracts/schemas" / name
        assert canonical.read_bytes() == packaged.read_bytes()
        json.loads(canonical.read_text(encoding="utf-8"))


def test_training_json_schema_and_pydantic_top_level_required_fields_match() -> None:
    pairs = (
        (
            "local-image-training-authorization-v1.schema.json",
            LocalImageTrainingAuthorization,
        ),
        (
            "local-image-training-candidate-inventory-v1.schema.json",
            LocalImageTrainingCandidateInventory,
        ),
        (
            "local-image-training-dataset-manifest-v1.schema.json",
            LocalImageTrainingDatasetManifest,
        ),
        (
            "local-image-training-eligibility-review-v1.schema.json",
            LocalImageTrainingEligibilityReview,
        ),
        ("local-image-lora-training-plan-v1.schema.json", LocalImageLoraTrainingPlan),
        (
            "local-image-lora-adapter-manifest-v1.schema.json",
            LocalImageLoraAdapterManifest,
        ),
        (
            "local-image-lora-checkpoint-manifest-v1.schema.json",
            LocalImageLoraCheckpointManifest,
        ),
        (
            "local-image-lora-training-receipt-v1.schema.json",
            LocalImageLoraTrainingReceipt,
        ),
        (
            "local-image-lora-training-command-v1.schema.json",
            LocalImageLoraTrainingCommand,
        ),
        (
            "local-image-lora-training-worker-result-v1.schema.json",
            LocalImageLoraTrainingWorkerResult,
        ),
    )
    for filename, model in pairs:
        canonical = json.loads(
            (REPOSITORY_ROOT / "schemas/image-provider" / filename).read_text(encoding="utf-8")
        )
        assert set(canonical["required"]) == set(model.model_json_schema()["required"])


def test_training_contracts_validate_and_bind_exact_inputs() -> None:
    authorization_value = _authorization_value()
    inventory_value = _inventory_value()
    dataset_value = _dataset_value()
    eligibility_review_value = _eligibility_review_value()
    plan_value = _plan_value()
    adapter_value = _adapter_value()
    checkpoint_value = _checkpoint_value()
    receipt_value = _receipt_value()
    command_value = _command_value()
    worker_result_value = _worker_result_value()
    for name, value in (
        ("training-authorization", authorization_value),
        ("training-candidate-inventory", inventory_value),
        ("training-dataset-manifest", dataset_value),
        ("training-eligibility-review", eligibility_review_value),
        ("lora-training-plan", plan_value),
        ("lora-adapter-manifest", adapter_value),
        ("lora-checkpoint-manifest", checkpoint_value),
        ("lora-training-receipt", receipt_value),
        ("lora-training-command", command_value),
        ("lora-training-worker-result", worker_result_value),
    ):
        validate_contract(name, value)
    authorization = LocalImageTrainingAuthorization.model_validate(authorization_value)
    inventory = LocalImageTrainingCandidateInventory.model_validate(inventory_value)
    dataset = LocalImageTrainingDatasetManifest.model_validate(dataset_value)
    eligibility_review = LocalImageTrainingEligibilityReview.model_validate(
        eligibility_review_value
    )
    plan = LocalImageLoraTrainingPlan.model_validate(plan_value)
    adapter = LocalImageLoraAdapterManifest.model_validate(adapter_value)
    checkpoint = LocalImageLoraCheckpointManifest.model_validate(checkpoint_value)
    receipt = LocalImageLoraTrainingReceipt.model_validate(receipt_value)
    command = LocalImageLoraTrainingCommand.model_validate(command_value)
    worker_result = LocalImageLoraTrainingWorkerResult.model_validate(worker_result_value)
    validate_training_dataset_authorization(dataset, authorization)
    validate_training_dataset_inventory(dataset, inventory)
    validate_training_inventory_review(inventory, eligibility_review)
    validate_lora_training_plan(plan, dataset)
    validate_lora_training_receipt(receipt, plan, adapter)
    validate_lora_training_worker_result(command, worker_result)
    validate_lora_checkpoint_manifest(checkpoint, command)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("authorization_hash", "authorization hash mismatch"),
        ("dataset_hash", "dataset hash mismatch"),
        ("caption_hash", "caption hash mismatch"),
        ("crop_path", "crop path does not bind"),
        ("holdout_leak", "contains a holdout source anchor"),
        ("duplicate_crop", "duplicate crop bytes"),
    ),
)
def test_training_contracts_fail_closed_on_tampering(mutation: str, message: str) -> None:
    if mutation == "authorization_hash":
        value = _authorization_value()
        value["approved_by"] = "changed"
        with pytest.raises(ValidationError, match=message):
            LocalImageTrainingAuthorization.model_validate(value)
        return
    value = _dataset_value()
    samples = value["samples"]
    assert isinstance(samples, list)
    if mutation == "dataset_hash":
        value["created_by"] = "changed"
    elif mutation == "caption_hash":
        samples[0]["caption_en"] = "Changed caption."
    elif mutation == "crop_path":
        samples[0]["crop_member"]["member_path"] = samples[1]["crop_member"]["member_path"]
    elif mutation == "holdout_leak":
        anchors = value["holdout_source_anchor_ids"]
        assert isinstance(anchors, list)
        samples[0]["source_anchor_id"] = anchors[0]
    elif mutation == "duplicate_crop":
        samples[0]["crop_member"]["sha256"] = samples[1]["crop_member"]["sha256"]
    with pytest.raises(ValidationError, match=message):
        LocalImageTrainingDatasetManifest.model_validate(value)


def test_dataset_authorization_rejects_rights_drift() -> None:
    authorization = LocalImageTrainingAuthorization.model_validate(_authorization_value())
    value = _dataset_value()
    samples = value["samples"]
    assert isinstance(samples, list)
    samples[0]["rights_policy"]["rights_policy_sha256"] = _sha("f")
    value["sample_set_sha256"] = content_sha256(samples)
    body = copy.deepcopy(value)
    body.pop("dataset_sha256")
    value["dataset_sha256"] = content_sha256(body)
    dataset = LocalImageTrainingDatasetManifest.model_validate(value)
    with pytest.raises(ValueError, match="lacks an exact authorized rights policy"):
        validate_training_dataset_authorization(dataset, authorization)


def test_dataset_inventory_rejects_candidate_drift() -> None:
    inventory = LocalImageTrainingCandidateInventory.model_validate(_inventory_value())
    value = _dataset_value()
    samples = value["samples"]
    assert isinstance(samples, list)
    samples[0]["caption_en"] = "Different but internally valid caption."
    samples[0]["caption_sha256"] = text_sha256(samples[0]["caption_en"])
    value["sample_set_sha256"] = content_sha256(samples)
    body = copy.deepcopy(value)
    body.pop("dataset_sha256")
    value["dataset_sha256"] = content_sha256(body)
    dataset = LocalImageTrainingDatasetManifest.model_validate(value)
    with pytest.raises(ValueError, match="drifts from its candidate inventory"):
        validate_training_dataset_inventory(dataset, inventory)


def test_inventory_review_rejects_unreviewed_candidate() -> None:
    inventory = LocalImageTrainingCandidateInventory.model_validate(_inventory_value())
    value = _eligibility_review_value()
    entries = value["entries"]
    assert isinstance(entries, list)
    entries[0]["decision"] = "EXCLUDED"
    entries[0]["exclusion_reasons"] = ["HUMAN_SUBJECT"]
    entries[0]["caption_en"] = None
    entries[0]["caption_sha256"] = None
    eligible = [
        {key: item for key, item in entry.items() if key not in {"decision", "exclusion_reasons"}}
        for entry in entries
        if entry["decision"] == "ELIGIBLE"
    ]
    value["eligible_candidate_set_sha256"] = content_sha256(eligible)
    body = copy.deepcopy(value)
    body.pop("review_sha256")
    value["review_sha256"] = content_sha256(body)
    review = LocalImageTrainingEligibilityReview.model_validate(value)
    with pytest.raises(ValueError, match="does not match its eligibility review"):
        validate_training_inventory_review(inventory, review)


def test_training_receipt_rejects_nonterminal_shape() -> None:
    value = _receipt_value()
    value["status"] = "FAILED"
    with pytest.raises(ValidationError, match="requires only an error code"):
        LocalImageLoraTrainingReceipt.model_validate(value)


def test_training_worker_result_rejects_command_drift() -> None:
    command = LocalImageLoraTrainingCommand.model_validate(_command_value())
    result = LocalImageLoraTrainingWorkerResult.model_validate(_worker_result_value())
    changed = result.model_copy(update={"attempt": 2})
    with pytest.raises(ValueError, match="does not bind the exact command"):
        validate_lora_training_worker_result(command, changed)


def test_training_checkpoint_rejects_nonboundary_and_attempt_drift() -> None:
    command = LocalImageLoraTrainingCommand.model_validate(_command_value())
    checkpoint = LocalImageLoraCheckpointManifest.model_validate(_checkpoint_value())
    changed = checkpoint.model_copy(update={"completed_steps": 300, "micro_steps": 1200})
    with pytest.raises(ValueError, match="does not bind the exact resumable command state"):
        validate_lora_checkpoint_manifest(changed, command)
    changed = checkpoint.model_copy(update={"attempt": 2})
    with pytest.raises(ValueError, match="does not bind the exact resumable command state"):
        validate_lora_checkpoint_manifest(changed, command)
