from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageModelPointer,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCandidateInventory,
    content_sha256,
    text_sha256,
    validate_contract,
)
from eom_image_trainer import DatasetBuildError, StagedPageImage, build_training_dataset
from PIL import Image


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _pointer(
    serial: int,
    *,
    member_path: str,
    schema_ref: str,
    media_type: str,
    sha256: str,
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + f"{serial:032x}",
        "artifact_revision_id": "rev_" + f"{serial + 1000:032x}",
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": sha256,
    }


def _source_snapshot() -> dict[str, object]:
    return {
        "graph_revision_id": "graphrev_" + "1" * 32,
        "graph_snapshot_sha256": _sha("2"),
        "graph_manifest_sha256": _sha("3"),
        "target_count": 520,
        "target_set_sha256": _sha("4"),
    }


def _rights() -> dict[str, object]:
    return {
        "rights_policy_id": "rightspolicy_" + "5" * 32,
        "rights_policy_revision_id": "rightspolicyrev_" + "6" * 32,
        "rights_policy_sha256": _sha("7"),
    }


def _authorization() -> LocalImageTrainingAuthorization:
    body = {
        "schema_version": "local-image-training-authorization/1.0",
        "authorization_id": "imgtrainauth_" + "8" * 32,
        "authorization_revision_id": "imgtrainauthrev_" + "9" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "source_snapshot": _source_snapshot(),
        "rights_policies": [_rights()],
        "permitted_use": "INTERNAL_LORA_TRAINING",
        "derivative_output": "LORA_ADAPTER_ONLY",
        "state": "APPROVED",
        "approved_at": "2026-09-25T03:00:00Z",
        "approved_by": "operator_test",
    }
    value = {**body, "authorization_sha256": content_sha256(body)}
    validate_contract("training-authorization", value)
    return LocalImageTrainingAuthorization.model_validate(value)


def _pattern_png(index: int) -> bytes:
    digest = hashlib.sha256(f"training-source-{index}".encode()).digest()
    value = int.from_bytes(digest[:8], "big")
    image = Image.new("L", (80, 80), 255)
    pixels = image.load()
    assert pixels is not None
    for row in range(8):
        for column in range(8):
            shade = 0 if value & (1 << (row * 8 + column)) else 255
            for y in range(row * 10, row * 10 + 10):
                for x in range(column * 10, column * 10 + 10):
                    pixels[x, y] = shade
    target = io.BytesIO()
    image.convert("RGB").save(target, format="PNG", compress_level=9)
    return target.getvalue()


def _inventory_and_pages(
    staged_root: Path,
) -> tuple[LocalImageTrainingCandidateInventory, tuple[StagedPageImage, ...]]:
    pages_root = staged_root / "pages"
    pages_root.mkdir(parents=True, mode=0o700)
    candidates: list[dict[str, object]] = []
    staged_pages: list[StagedPageImage] = []
    for index in range(101):
        payload = _pattern_png(index)
        source_sha = "sha256:" + hashlib.sha256(payload).hexdigest()
        source_pointer = _pointer(
            index + 1,
            member_path=f"pages/page-{index + 1:04d}.png",
            schema_ref="eom://schemas/catalog/assessment-page-image/1.0",
            media_type="image/png",
            sha256=source_sha,
        )
        pointer = ImageEvaluationArtifactMember.model_validate(source_pointer)
        target = pages_root / (source_sha.removeprefix("sha256:") + ".png")
        target.write_bytes(payload)
        target.chmod(0o600)
        staged_pages.append(StagedPageImage(pointer=pointer))
        caption = f"Side view of one nonhuman science specimen number {index}."
        candidates.append(
            {
                "candidate_id": "imgtraincandidate_" + f"{index + 1000:032x}",
                "item_revision_id": "itemrev_" + f"{index + 2000:032x}",
                "extraction_result": _pointer(
                    index + 200,
                    member_path=f"extraction/result-{index + 1:04d}.json",
                    schema_ref="eom://schemas/catalog/legacy-item-extraction-result/1.0",
                    media_type="application/json",
                    sha256="sha256:" + hashlib.sha256(f"extraction-{index}".encode()).hexdigest(),
                ),
                "source_anchor_id": "assessmentanchor_" + f"{index + 3000:032x}",
                "source_page_image": source_pointer,
                "physical_page": index + 1,
                "bounding_box": {"left": 0, "top": 0, "right": 10000, "bottom": 10000},
                "rights_policy": _rights(),
                "representation_kind": "PHOTOGRAPH",
                "rendering_mode": "RASTER",
                "caption_en": caption,
                "caption_sha256": text_sha256(caption),
            }
        )
    holdout_anchors = [candidates[0]["source_anchor_id"]]
    holdout_anchors.extend("assessmentanchor_" + f"{index + 9000:032x}" for index in range(11))
    body = {
        "schema_version": "local-image-training-candidate-inventory/1.0",
        "inventory_id": "imgtraininventory_" + "a" * 32,
        "source_snapshot": _source_snapshot(),
        "holdout_evaluation_plan": _pointer(
            800,
            member_path="manifests/evaluation-plan.json",
            schema_ref=("eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"),
            media_type="application/json",
            sha256=_sha("b"),
        ),
        "holdout_sample_ids": ["imgsample_" + f"{index + 8000:032x}" for index in range(12)],
        "holdout_source_anchor_ids": sorted(holdout_anchors),
        "candidates": candidates,
        "created_at": "2026-09-25T03:01:00Z",
        "created_by": "operator_test",
    }
    value = {**body, "inventory_sha256": content_sha256(body)}
    validate_contract("training-candidate-inventory", value)
    inventory = LocalImageTrainingCandidateInventory.model_validate(value)
    return inventory, tuple(sorted(staged_pages, key=lambda page: page.key))


def _artifact_pointer(
    serial: int,
    *,
    member_path: str,
    schema_ref: str,
    sha256: str,
) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember.model_validate(
        _pointer(
            serial,
            member_path=member_path,
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=sha256,
        )
    )


def _model() -> LocalImageModelPointer:
    return LocalImageModelPointer.model_validate(
        {
            "model_id": "imgmodel_" + "c" * 32,
            "model_revision_id": "imgmodelrev_" + "d" * 32,
            "manifest_sha256": _sha("e"),
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        }
    )


def _build(tmp_path: Path):
    staged_root = tmp_path / "staged"
    inventory, staged_pages = _inventory_and_pages(staged_root)
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    authorization = _authorization()
    dataset = build_training_dataset(
        inventory=inventory,
        inventory_pointer=_artifact_pointer(
            900,
            member_path="manifests/training-candidates.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-training-candidate-inventory/1.0"
            ),
            sha256=inventory.inventory_sha256,
        ),
        authorization=authorization,
        authorization_pointer=_artifact_pointer(
            901,
            member_path="manifests/training-authorization.json",
            schema_ref=("eom://schemas/image-provider/local-image-training-authorization/1.0"),
            sha256=authorization.authorization_sha256,
        ),
        base_model=_model(),
        staged_root=staged_root,
        staged_pages=staged_pages,
        output_root=output_root,
        created_at=datetime(2026, 9, 25, 3, 2, tzinfo=UTC),
        created_by="operator_test",
    )
    return dataset, output_root, staged_root, inventory, staged_pages


def test_dataset_builder_writes_one_atomic_valid_dataset(tmp_path: Path) -> None:
    dataset, output_root, _, inventory, _ = _build(tmp_path)
    assert len(dataset.samples) == 100
    assert not set(sample.source_anchor_id for sample in dataset.samples) & set(
        inventory.holdout_source_anchor_ids
    )
    dataset_root = output_root / "dataset"
    assert (dataset_root / "manifests/training-dataset.json").is_file()
    assert len(tuple((dataset_root / "samples").glob("*.png"))) == 100
    for sample in dataset.samples:
        target = dataset_root / sample.crop_member.member_path
        assert target.stat().st_mode & 0o777 == 0o600
        assert "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() == (
            sample.crop_member.sha256
        )


def test_dataset_builder_rejects_replay_without_overwrite(tmp_path: Path) -> None:
    _, output_root, staged_root, inventory, staged_pages = _build(tmp_path)
    authorization = _authorization()
    with pytest.raises(DatasetBuildError, match="IMAGE_TRAINING_DATASET_ALREADY_EXISTS"):
        build_training_dataset(
            inventory=inventory,
            inventory_pointer=_artifact_pointer(
                900,
                member_path="manifests/training-candidates.json",
                schema_ref=(
                    "eom://schemas/image-provider/local-image-training-candidate-inventory/1.0"
                ),
                sha256=inventory.inventory_sha256,
            ),
            authorization=authorization,
            authorization_pointer=_artifact_pointer(
                901,
                member_path="manifests/training-authorization.json",
                schema_ref=("eom://schemas/image-provider/local-image-training-authorization/1.0"),
                sha256=authorization.authorization_sha256,
            ),
            base_model=_model(),
            staged_root=staged_root,
            staged_pages=staged_pages,
            output_root=output_root,
            created_at=datetime(2026, 9, 25, 3, 2, tzinfo=UTC),
            created_by="operator_test",
        )


def test_dataset_builder_rejects_hash_drift_without_partial_output(tmp_path: Path) -> None:
    staged_root = tmp_path / "staged"
    inventory, staged_pages = _inventory_and_pages(staged_root)
    page = staged_pages[1]
    target = staged_root / "pages" / page.filename
    target.write_bytes(target.read_bytes() + b"changed")
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    authorization = _authorization()
    with pytest.raises(DatasetBuildError, match="IMAGE_TRAINING_SOURCE_PAGE_HASH_MISMATCH"):
        build_training_dataset(
            inventory=inventory,
            inventory_pointer=_artifact_pointer(
                900,
                member_path="manifests/training-candidates.json",
                schema_ref=(
                    "eom://schemas/image-provider/local-image-training-candidate-inventory/1.0"
                ),
                sha256=inventory.inventory_sha256,
            ),
            authorization=authorization,
            authorization_pointer=_artifact_pointer(
                901,
                member_path="manifests/training-authorization.json",
                schema_ref=("eom://schemas/image-provider/local-image-training-authorization/1.0"),
                sha256=authorization.authorization_sha256,
            ),
            base_model=_model(),
            staged_root=staged_root,
            staged_pages=staged_pages,
            output_root=output_root,
            created_at=datetime(2026, 9, 25, 3, 2, tzinfo=UTC),
            created_by="operator_test",
        )
    assert not (output_root / "dataset").exists()
    assert not tuple(output_root.glob(".dataset-building-*"))
