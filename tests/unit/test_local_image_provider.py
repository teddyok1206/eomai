from __future__ import annotations

import binascii
import hashlib
import io
import json
import os
import stat
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_service.local_image_training_evaluation import (
    TrainingEvaluationPlanError,
    align_training_holdout_plan,
)
from eom_image_contracts import (
    ImageEvaluationSourceSnapshot,
    LocalImageCompositeRequest,
    LocalImageGenerationRequest,
    LocalImageModelManifest,
    LocalImageProviderBinding,
    LocalImageQualityEvaluationPlan,
    LocalImageQualityEvaluationResult,
    LocalImageRuntime,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_quality_evaluation_result,
)
from eom_image_provider.model_manifest import SSD1B_REQUIRED_FILES, create_model_manifest
from eom_image_provider.provider import (
    GeneratedBackground,
    ProviderError,
    _compose_png,
    acquire_gpu_lease,
    generate_background,
    generate_composite_handoff,
    reuse_composite_handoff,
    verify_model_revision,
)
from PIL import Image  # type: ignore[import-not-found]

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "imgmodel_" + "1" * 32
MODEL_REVISION_ID = "imgmodelrev_" + "2" * 32
REQUEST_ID = "imgreq_" + "3" * 32


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))


def _png() -> bytes:
    width, height = 800, 500
    rows = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(rows, level=9)),
            _chunk(b"IEND", b""),
        )
    )


def _rgba_png() -> bytes:
    width, height = 800, 500
    transparent = b"\x00\x00\x00\x00"
    marker = b"\x00\x00\x00\xff"
    rows = []
    for y in range(height):
        row = bytearray(transparent * width)
        if 100 <= y < 120:
            row[100 * 4 : 700 * 4] = marker * 600
        rows.append(b"\x00" + bytes(row))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(b"".join(rows), level=9)),
            _chunk(b"IEND", b""),
        )
    )


def _store(tmp_path: Path) -> tuple[Path, LocalImageModelManifest]:
    root = tmp_path / "models"
    revision = root / MODEL_ID / MODEL_REVISION_ID
    files = revision / "files"
    files.mkdir(parents=True, mode=0o750)
    root.chmod(0o750)
    (root / MODEL_ID).chmod(0o750)
    revision.chmod(0o750)
    files.chmod(0o750)
    model_file = files / "model_index.json"
    model_file.write_text('{"_class_name":"StableDiffusionXLPipeline"}\n', encoding="utf-8")
    model_file.chmod(0o640)
    body = {
        "schema_version": "local-image-model-manifest/1.0",
        "model_id": MODEL_ID,
        "model_revision_id": MODEL_REVISION_ID,
        "provider_family": "diffusers-ssd-1b",
        "runtime_contract_version": "eom-local-image-provider/1.0",
        "state": "APPROVED",
        "upstream": {
            "repo_id": "segmind/SSD-1B",
            "revision": "60987f37e94cd59c36b1cba832b9f97b57395a10",
            "source_url": "https://huggingface.co/segmind/SSD-1B",
            "license_id": "Apache-2.0",
        },
        "files": [
            {
                "relative_path": "model_index.json",
                "size_bytes": model_file.stat().st_size,
                "sha256": "sha256:" + hashlib.sha256(model_file.read_bytes()).hexdigest(),
            }
        ],
        "created_at": "2026-09-01T00:00:00Z",
        "approved_at": "2026-09-01T00:00:01Z",
        "approved_by": "operator:test",
    }
    value = {**body, "manifest_sha256": content_sha256(body)}
    validate_contract("model-manifest", value)
    manifest = LocalImageModelManifest.model_validate(value)
    manifest_path = revision / "manifest.json"
    manifest_path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o640)
    return root, manifest


def _request(manifest: LocalImageModelManifest) -> LocalImageGenerationRequest:
    prompt = "neutral paper texture, muted pale blue and gray, no text, no labels"
    negative = "text, letters, numbers, labels, watermark, face"
    body = {
        "schema_version": "local-image-generation-request/1.0",
        "request_id": REQUEST_ID,
        "idempotency_key": "local-image-smoke:" + "4" * 32,
        "model": {
            "model_id": manifest.model_id,
            "model_revision_id": manifest.model_revision_id,
            "manifest_sha256": manifest.manifest_sha256,
            "provider_family": manifest.provider_family,
            "runtime_contract_version": manifest.runtime_contract_version,
        },
        "prompt": prompt,
        "prompt_sha256": text_sha256(prompt),
        "negative_prompt": negative,
        "negative_prompt_sha256": text_sha256(negative),
        "seed": 20260901,
        "sampler": {
            "contract": "euler-discrete/ssd-1b-v1",
            "inference_steps": 20,
            "guidance_scale": 7.5,
            "dtype": "float16",
        },
        "generation_canvas": {"width_px": 800, "height_px": 504},
        "delivery_canvas": {"width_px": 800, "height_px": 500},
        "output_member": "generated-background.png",
        "timeout_seconds": 600,
    }
    value = {**body, "request_sha256": content_sha256(body)}
    validate_contract("generation-request", value)
    return LocalImageGenerationRequest.model_validate(value)


class FakeBackend:
    def generate(
        self, *, model_directory: Path, request: LocalImageGenerationRequest
    ) -> GeneratedBackground:
        assert model_directory.name == "files"
        assert request.request_id == REQUEST_ID
        return GeneratedBackground(
            png_bytes=_png(),
            runtime=LocalImageRuntime(
                python_version="3.11.15",
                torch_version="2.7.1+cu128",
                diffusers_version="0.35.2",
                transformers_version="4.56.2",
                cuda_version="12.8",
                gpu_name="NVIDIA GeForce RTX 5080",
                compute_capability="12.0",
                peak_gpu_memory_bytes=1024,
            ),
        )


class QualityFakeBackend(FakeBackend):
    def generate(
        self, *, model_directory: Path, request: LocalImageGenerationRequest
    ) -> GeneratedBackground:
        assert model_directory.name == "files"
        assert request.request_id.startswith("imgreq_")
        return GeneratedBackground(
            png_bytes=_png(),
            runtime=LocalImageRuntime(
                python_version="3.11.15",
                torch_version="2.7.1+cu128",
                diffusers_version="0.35.2",
                transformers_version="4.56.2",
                cuda_version="12.8",
                gpu_name="NVIDIA GeForce RTX 5080",
                compute_capability="12.0",
                peak_gpu_memory_bytes=1024,
            ),
        )


def _composite_request(
    manifest: LocalImageModelManifest, overlay: bytes
) -> LocalImageCompositeRequest:
    generation = _request(manifest)
    body = {
        "schema_version": "local-image-composite-request/1.0",
        "generation": generation.model_dump(mode="json"),
        "overlay": {
            "member_path": "generated-overlay.png",
            "media_type": "image/png",
            "width_px": 800,
            "height_px": 500,
            "mode": "RGBA",
            "size_bytes": len(overlay),
            "sha256": "sha256:" + hashlib.sha256(overlay).hexdigest(),
        },
        "final_output_member": "generated-stimulus.png",
    }
    value = {**body, "composite_request_sha256": content_sha256(body)}
    validate_contract("composite-request", value)
    return LocalImageCompositeRequest.model_validate(value)


def test_contract_resources_are_canonical_mirrors() -> None:
    for name in (
        "local-image-model-manifest-v1.schema.json",
        "local-image-generation-request-v1.schema.json",
        "local-image-generation-receipt-v1.schema.json",
        "local-image-provider-binding-v1.schema.json",
        "local-image-composite-request-v1.schema.json",
        "local-image-composite-receipt-v1.schema.json",
        "local-image-quality-evaluation-plan-v1.schema.json",
        "local-image-quality-evaluation-result-v1.schema.json",
    ):
        canonical = REPOSITORY_ROOT / "schemas" / "image-provider" / name
        packaged = (
            REPOSITORY_ROOT
            / "packages"
            / "image_contracts"
            / "eom_image_contracts"
            / "schemas"
            / name
        )
        assert canonical.read_bytes() == packaged.read_bytes()


def _quality_plan(manifest: LocalImageModelManifest) -> LocalImageQualityEvaluationPlan:
    binding_body = {
        "schema_version": "local-image-provider-binding/1.0",
        "state": "ENABLED",
        "route_contract": "eom-local-generative-background/1.0",
        "model": {
            "model_id": manifest.model_id,
            "model_revision_id": manifest.model_revision_id,
            "manifest_sha256": manifest.manifest_sha256,
            "provider_family": manifest.provider_family,
            "runtime_contract_version": manifest.runtime_contract_version,
        },
        "sampler": {
            "contract": "euler-discrete/ssd-1b-v1",
            "inference_steps": 20,
            "guidance_scale": 7.5,
            "dtype": "float16",
        },
        "timeout_seconds": 600,
    }
    binding = LocalImageProviderBinding.model_validate(
        {**binding_body, "binding_sha256": content_sha256(binding_body)}
    )
    variants = (
        {
            "variant_id": "ASSESSMENT_STYLE_EN",
            "label": "assessment style",
            "policy_revision": "evaluation/assessment-style-en-v1",
        },
        {
            "variant_id": "CURRENT_KO",
            "label": "current Korean subject",
            "policy_revision": "local-gpu-image-prompt-policy/1.4",
        },
        {
            "variant_id": "ENGLISH_SUBJECT",
            "label": "English subject",
            "policy_revision": "evaluation/english-subject-v1",
        },
    )
    prompts = []
    for variant in variants:
        variant_id = variant["variant_id"]
        positive = f"monochrome: fossil sample, {variant_id.lower()}"
        negative = "color, text, labels, numbers"
        prompts.append(
            {
                "variant_id": variant_id,
                "positive_prompt": positive,
                "positive_prompt_sha256": text_sha256(positive),
                "negative_prompt": negative,
                "negative_prompt_sha256": text_sha256(negative),
            }
        )
    sample = {
        "sample_id": "imgsample_" + "5" * 32,
        "item_revision_id": "itemrev_" + "6" * 32,
        "extraction_result": {
            "artifact_id": "artifact_" + "7" * 32,
            "artifact_revision_id": "rev_" + "8" * 32,
            "member_path": "result.json",
            "schema_ref": "legacy-item-extraction-result/1.0",
            "media_type": "application/json",
            "sha256": "sha256:" + "9" * 64,
        },
        "visual_pattern": {
            "pattern_id": "visualpattern_" + "a" * 32,
            "representation_kind": "PHOTOGRAPH",
            "rendering_mode": "RASTER",
            "color_mode": "GRAYSCALE",
            "background": "WHITE",
            "panel_layout": "SINGLE",
            "features": ["LABELS"],
            "pedagogical_function": "CONTEXT",
            "composition_summary_sha256": "sha256:" + "b" * 64,
            "reconstruction_guidance_sha256": "sha256:" + "c" * 64,
        },
        "source_anchor_id": "assessmentanchor_" + "f" * 32,
        "source_page_image": {
            "artifact_id": "artifact_" + "d" * 32,
            "artifact_revision_id": "rev_" + "e" * 32,
            "member_path": "source/pages/assessmentpage_" + "f" * 32 + ".png",
            "schema_ref": "assessment-page-image/1.0",
            "media_type": "image/png",
            "sha256": "sha256:" + "1" * 64,
        },
        "physical_page": 3,
        "bounding_box": {"left": 100, "top": 200, "right": 9000, "bottom": 8000},
        "seed": 20260925,
        "prompts": prompts,
    }
    body = {
        "schema_version": "local-image-quality-evaluation-plan/1.0",
        "evaluation_id": "imageeval_" + "2" * 32,
        "created_at": "2026-09-25T00:00:00Z",
        "source_snapshot": {
            "graph_revision_id": "graphrev_" + "3" * 32,
            "graph_snapshot_sha256": "sha256:" + "4" * 64,
            "graph_manifest_sha256": "sha256:" + "5" * 64,
            "target_count": 520,
            "target_set_sha256": "sha256:" + "6" * 64,
        },
        "provider_binding": binding.model_dump(mode="json"),
        "selection_method": "STRATIFIED_DETERMINISTIC_V1",
        "population_pattern_count": 537,
        "variants": list(variants),
        "samples": [sample],
    }
    value = {**body, "plan_sha256": content_sha256(body)}
    validate_contract("quality-evaluation-plan", value)
    return LocalImageQualityEvaluationPlan.model_validate(value)


def test_training_holdout_alignment_preserves_samples_and_pins_canonical_snapshot(
    tmp_path: Path,
) -> None:
    _, manifest = _store(tmp_path)
    original = _quality_plan(manifest)
    samples = []
    for index in range(12):
        sample = original.samples[0].model_dump(mode="json")
        sample["sample_id"] = "imgsample_" + f"{index + 100:032x}"
        sample["source_anchor_id"] = "assessmentanchor_" + f"{index + 1000:032x}"
        samples.append(sample)
    template_body = original.model_dump(mode="json", exclude={"plan_sha256"})
    template_body["samples"] = samples
    template = LocalImageQualityEvaluationPlan.model_validate(
        {**template_body, "plan_sha256": content_sha256(template_body)}
    )
    canonical = ImageEvaluationSourceSnapshot(
        **{
            **template.source_snapshot.model_dump(mode="json"),
            "target_set_sha256": "sha256:" + "f" * 64,
        }
    )
    aligned = align_training_holdout_plan(
        template=template,
        source_snapshot=canonical,
        created_at=datetime(2026, 9, 25, 14, 0, tzinfo=UTC),
    )
    assert aligned.source_snapshot == canonical
    assert aligned.samples == template.samples
    assert aligned.provider_binding == template.provider_binding
    assert aligned.evaluation_id != template.evaluation_id
    mismatch = canonical.model_copy(update={"target_count": 519})
    with pytest.raises(
        TrainingEvaluationPlanError,
        match="IMAGE_TRAINING_HOLDOUT_SOURCE_MISMATCH",
    ):
        align_training_holdout_plan(
            template=template,
            source_snapshot=mismatch,
            created_at=datetime(2026, 9, 25, 14, 0, tzinfo=UTC),
        )


def test_quality_evaluation_plan_result_and_cross_validation(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    plan = _quality_plan(manifest)
    sample = plan.samples[0]
    outputs = []
    for index, prompt in enumerate(sample.prompts):
        body = {
            "schema_version": "local-image-generation-request/1.0",
            "request_id": "imgreq_" + f"{index + 10:032x}",
            "idempotency_key": f"image-quality-test:{index:032x}",
            "model": plan.provider_binding.model.model_dump(mode="json"),
            "prompt": prompt.positive_prompt,
            "prompt_sha256": prompt.positive_prompt_sha256,
            "negative_prompt": prompt.negative_prompt,
            "negative_prompt_sha256": prompt.negative_prompt_sha256,
            "seed": sample.seed,
            "sampler": plan.provider_binding.sampler.model_dump(mode="json"),
            "generation_canvas": {"width_px": 800, "height_px": 504},
            "delivery_canvas": {"width_px": 800, "height_px": 500},
            "output_member": "generated-background.png",
            "timeout_seconds": plan.provider_binding.timeout_seconds,
        }
        request = LocalImageGenerationRequest.model_validate(
            {**body, "request_sha256": content_sha256(body)}
        )
        workspace = tmp_path / f"quality-{index}"
        workspace.mkdir(mode=0o700)
        receipt = generate_background(
            model_store_root=root,
            workspace=workspace,
            request=request,
            backend=QualityFakeBackend(),
        )
        outputs.append(
            {
                "sample_id": sample.sample_id,
                "variant_id": prompt.variant_id,
                "request": request.model_dump(mode="json"),
                "receipt": receipt.model_dump(mode="json"),
                "metrics": {
                    "grayscale_fraction_milli": 1000,
                    "white_background_fraction_milli": 1000,
                    "dark_ink_fraction_milli": 0,
                    "edge_fraction_milli": 0,
                    "ink_bbox_coverage_milli": 0,
                    "ocr_glyph_count": 0,
                },
                "manual_review": None,
            }
        )
    body = {
        "schema_version": "local-image-quality-evaluation-result/1.0",
        "evaluation_id": plan.evaluation_id,
        "plan_sha256": plan.plan_sha256,
        "status": "AUTOMATED_COMPLETE",
        "completed_at": "2026-09-25T00:05:00Z",
        "outputs": outputs,
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("quality-evaluation-result", value)
    result = LocalImageQualityEvaluationResult.model_validate(value)
    validate_quality_evaluation_result(plan, result)


def test_quality_evaluation_rejects_plan_drift(tmp_path: Path) -> None:
    _, manifest = _store(tmp_path)
    plan = _quality_plan(manifest)
    changed = plan.model_copy(update={"population_pattern_count": 538})
    with pytest.raises(ValueError, match="plan hash mismatch"):
        LocalImageQualityEvaluationPlan.model_validate(changed.model_dump(mode="json"))


def test_model_manifest_request_and_receipt_are_pointer_pinned(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    request = _request(manifest)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    receipt = generate_background(
        model_store_root=root,
        workspace=workspace,
        request=request,
        backend=FakeBackend(),
    )

    assert receipt.model.model_revision_id == MODEL_REVISION_ID
    assert receipt.model.manifest_sha256 == manifest.manifest_sha256
    assert receipt.request_sha256 == request.request_sha256
    assert receipt.output.sha256 == "sha256:" + hashlib.sha256(_png()).hexdigest()
    assert receipt.output.width_px == 800
    assert receipt.output.height_px == 500
    assert stat.S_IMODE((workspace / "generated-background.png").stat().st_mode) == 0o600
    assert stat.S_IMODE((workspace / "generation-receipt.json").stat().st_mode) == 0o600
    validate_contract("generation-receipt", receipt.model_dump(mode="json"))


def test_model_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    model_file = root / MODEL_ID / MODEL_REVISION_ID / "files" / "model_index.json"
    model_file.write_text("changed\n", encoding="utf-8")
    model_file.chmod(0o640)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_MODEL_HASH_MISMATCH"):
        verify_model_revision(root, _request(manifest).model)


def test_model_symlink_fails_closed(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    model_file = root / MODEL_ID / MODEL_REVISION_ID / "files" / "model_index.json"
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    target.chmod(0o640)
    model_file.unlink()
    model_file.symlink_to(target)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_MODEL"):
        verify_model_revision(root, _request(manifest).model)


def test_prompt_and_request_hashes_cannot_be_replayed_with_changed_input(tmp_path: Path) -> None:
    _, manifest = _store(tmp_path)
    value = _request(manifest).model_dump(mode="json")
    value["prompt"] = "changed prompt"
    with pytest.raises(ValueError, match="prompt hash mismatch"):
        LocalImageGenerationRequest.model_validate(value)


def test_existing_output_prevents_an_implicit_regeneration(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "generated-background.png").write_bytes(_png())
    (workspace / "generated-background.png").chmod(0o600)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_OUTPUT_INVALID"):
        generate_background(
            model_store_root=root,
            workspace=workspace,
            request=_request(manifest),
            backend=FakeBackend(),
        )


def test_composite_handoff_is_idempotent_and_manager_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = _store(tmp_path)
    workspace = tmp_path / "handoff"
    workspace.mkdir(mode=0o1730)
    workspace.chmod(0o1730)
    overlay = _rgba_png()
    overlay_path = workspace / "generated-overlay.png"
    overlay_path.write_bytes(overlay)
    overlay_path.chmod(0o440)
    request = _composite_request(manifest, overlay)
    calls = 0

    class CountingBackend(FakeBackend):
        def generate(
            self, *, model_directory: Path, request: LocalImageGenerationRequest
        ) -> GeneratedBackground:
            nonlocal calls
            calls += 1
            return super().generate(model_directory=model_directory, request=request)

    monkeypatch.setattr(
        "eom_image_provider.provider._compose_png",
        lambda _background, _overlay: _png(),
    )
    monkeypatch.setattr("eom_image_provider.provider.metadata.version", lambda _name: "11.3.0")
    first = generate_composite_handoff(
        model_store_root=root,
        workspace=workspace,
        request=request,
        backend=CountingBackend(),
    )
    second = generate_composite_handoff(
        model_store_root=root,
        workspace=workspace,
        request=request,
        backend=CountingBackend(),
    )

    assert first == second
    assert calls == 1
    assert first.overlay.sha256 == request.overlay.sha256
    assert first.output.sha256 == "sha256:" + hashlib.sha256(_png()).hexdigest()
    for member in (
        "generated-background.png",
        "generation-receipt.json",
        "generated-stimulus.png",
        "composite-receipt.json",
    ):
        metadata = (workspace / member).stat()
        assert stat.S_IMODE(metadata.st_mode) == 0o640
        assert metadata.st_gid == os.getegid()
    validate_contract("composite-receipt", first.model_dump(mode="json"))

    lock_root = tmp_path / "locks"
    lock_root.mkdir(mode=0o700)
    lock_root.chmod(0o700)
    with acquire_gpu_lease(lock_root / "gpu0.lock"):
        assert reuse_composite_handoff(workspace=workspace, request=request) == first


def test_real_compositor_preserves_background_and_applies_authoritative_overlay(
    tmp_path: Path,
) -> None:
    background_path = tmp_path / "generated-background.png"
    overlay_path = tmp_path / "generated-overlay.png"
    background_path.write_bytes(_png())
    overlay_path.write_bytes(_rgba_png())

    payload = _compose_png(background_path, overlay_path)

    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (800, 500)
        assert image.getpixel((50, 50)) == (255, 255, 255)
        assert image.getpixel((200, 110)) == (0, 0, 0)
    assert payload != _png()


def test_composite_handoff_rejects_a_symlink_overlay(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    workspace = tmp_path / "handoff"
    workspace.mkdir(mode=0o1730)
    workspace.chmod(0o1730)
    overlay = _rgba_png()
    outside = tmp_path / "outside.png"
    outside.write_bytes(overlay)
    outside.chmod(0o440)
    (workspace / "generated-overlay.png").symlink_to(outside)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_HANDOFF_INVALID"):
        generate_composite_handoff(
            model_store_root=root,
            workspace=workspace,
            request=_composite_request(manifest, overlay),
            backend=FakeBackend(),
        )


def test_gpu_lease_denies_a_second_concurrent_owner(tmp_path: Path) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir(mode=0o700)
    lock_root.chmod(0o700)
    lock_path = lock_root / "gpu0.lock"
    with (
        acquire_gpu_lease(lock_path),
        pytest.raises(ProviderError, match="LOCAL_IMAGE_GPU_UNAVAILABLE"),
        acquire_gpu_lease(lock_path),
    ):
        raise AssertionError("unreachable")


def test_contract_timestamps_reject_non_utc_values(tmp_path: Path) -> None:
    _, manifest = _store(tmp_path)
    value = manifest.model_dump(mode="json")
    value["approved_at"] = datetime(2026, 9, 1, 9, 0, tzinfo=None).isoformat()
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    value["manifest_sha256"] = content_sha256(body)
    with pytest.raises(ValueError, match="timestamp must be UTC"):
        LocalImageModelManifest.model_validate(value)


def test_reviewed_ssd1b_file_set_creates_one_hash_pinned_manifest(tmp_path: Path) -> None:
    assert len(SSD1B_REQUIRED_FILES) == 19
    assert not any(path.endswith("added_tokens.json") for path in SSD1B_REQUIRED_FILES)
    revision = tmp_path / "revision"
    files_root = revision / "files"
    files_root.mkdir(parents=True, mode=0o750)
    revision.chmod(0o750)
    files_root.chmod(0o750)
    for relative in SSD1B_REQUIRED_FILES:
        target = files_root / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        target.parent.chmod(0o750)
        target.write_bytes((relative + "\n").encode())
        target.chmod(0o640)

    manifest = create_model_manifest(
        revision,
        model_id=MODEL_ID,
        model_revision_id=MODEL_REVISION_ID,
        approved_by="operator:test",
    )

    assert tuple(item.relative_path for item in manifest.files) == SSD1B_REQUIRED_FILES
    assert manifest.upstream.revision == "60987f37e94cd59c36b1cba832b9f97b57395a10"
    assert (revision / "manifest.json").is_file()
    assert stat.S_IMODE((revision / "manifest.json").stat().st_mode) == 0o640


def test_ssd1b_manifest_rejects_an_unreviewed_extra_file(tmp_path: Path) -> None:
    revision = tmp_path / "revision"
    files_root = revision / "files"
    files_root.mkdir(parents=True, mode=0o750)
    revision.chmod(0o750)
    files_root.chmod(0o750)
    extra = files_root / "unreviewed.bin"
    extra.write_bytes(b"untrusted\n")
    extra.chmod(0o640)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_MODEL_UNAVAILABLE"):
        create_model_manifest(
            revision,
            model_id=MODEL_ID,
            model_revision_id=MODEL_REVISION_ID,
            approved_by="operator:test",
        )
