from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from eom_image_contracts import (
    LocalImageCompositeReceipt,
    LocalImageCompositeRequest,
    LocalImageCompositorRuntime,
    LocalImageFinalOutput,
    LocalImageGenerationReceipt,
    LocalImageGenerationRequest,
    LocalImageModelPointer,
    LocalImageMorphologyConditioning,
    LocalImageOutput,
    LocalImageOverlayInput,
    LocalImageProductionStyleAdapterRelease,
    LocalImageProviderBindingV2,
    LocalImageProviderBindingV3,
    LocalImageReferenceConditionedCompositeReceipt,
    LocalImageReferenceConditionedCompositeReceiptV2,
    LocalImageReferenceConditionedCompositeReceiptV3,
    LocalImageReferenceConditionedCompositeRequest,
    LocalImageReferenceConditionedCompositeRequestV2,
    LocalImageReferenceConditionedCompositeRequestV3,
    LocalImageReferenceConditioning,
    LocalImageRuntime,
    LocalImageVisualReferenceAcquisitionCommand,
    LocalImageVisualReferenceAcquisitionResult,
    LocalImageVisualReferenceBundle,
    LocalImageVisualReferenceIntent,
    LocalImageVisualReferencePointer,
    LocalImageVisualReferencePolicy,
    LocalImageVisualReferencePolicyV2,
    LocalImageVisualReferencePublicationReceipt,
    ProductionStyleAdapterEvaluationPointer,
    ProductionStyleAdapterFile,
    ProductionStyleAdapterSourceManifestPointer,
    SamplerContract,
    VisualReferenceAcquisitionOutputFile,
    VisualReferenceBundleManifestPointer,
    VisualReferenceImageResultArtifactPointer,
    VisualReferencePngArtifactPointer,
    VisualReferencePublicationEntry,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_reference_conditioned_receipt,
    validate_reference_conditioned_receipt_v2,
    validate_reference_conditioned_receipt_v3,
    validate_visual_reference_acquisition,
)
from pydantic import ValidationError as PydanticValidationError


def _sha(value: int) -> str:
    return "sha256:" + f"{value:064x}"


def _intent() -> LocalImageVisualReferenceIntent:
    body = {
        "schema_version": "local-image-visual-reference-intent/1.0",
        "intent_id": "imgrefintent_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "image_step_run_id": "steprun_" + "3" * 32,
        "image_job_id": "job_" + "4" * 32,
        "visual_ordinal": 0,
        "drawing_sha256": _sha(5),
        "subject": "one compact car in side view isolated on white",
        "query_terms": ["compact car", "side view"],
        "candidates": [
            {
                "rank": 1,
                "provider": "WIKIMEDIA_COMMONS",
                "page_id": 101,
                "file_title": "File:Compact car side view.jpg",
                "canonical_page_url": (
                    "https://commons.wikimedia.org/wiki/File:Compact_car_side_view.jpg"
                ),
                "selection_rationale": "Clear side profile and visible wheel proportions.",
                "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                "license_expectation": "PUBLIC_DOMAIN_OR_CC0",
            },
            {
                "rank": 2,
                "provider": "WIKIMEDIA_COMMONS",
                "page_id": 102,
                "file_title": "File:Small automobile profile.png",
                "canonical_page_url": (
                    "https://commons.wikimedia.org/wiki/File:Small_automobile_profile.png"
                ),
                "selection_rationale": "Alternate silhouette with an unobstructed body outline.",
                "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                "license_expectation": "PUBLIC_DOMAIN_OR_CC0",
            },
        ],
        "primary_candidate_page_id": 101,
    }
    return LocalImageVisualReferenceIntent.model_validate(
        {**body, "intent_sha256": content_sha256(body)}
    )


def _bundle() -> LocalImageVisualReferenceBundle:
    body = {
        "schema_version": "local-image-visual-reference-bundle/1.0",
        "bundle_id": "imgrefbundle_" + "5" * 32,
        "bundle_revision_id": "imgrefbundlerev_" + "6" * 32,
        "state": "APPROVED",
        "intent": {
            "artifact_id": "artifact_" + "7" * 32,
            "artifact_revision_id": "rev_" + "8" * 32,
            "member_path": "manifests/visual-reference-intent.json",
            "schema_ref": ("eom://schemas/image-provider/local-image-visual-reference-intent/1.0"),
            "media_type": "application/json",
            "sha256": _sha(9),
            "size_bytes": 2048,
        },
        "subject": "one compact car in side view isolated on white",
        "provider_api_revision": "wikimedia-commons-api/1.0",
        "observed_at": "2026-09-27T12:00:00Z",
        "sources": [
            {
                "reference_id": "imgref_" + "a" * 32,
                "rank": 1,
                "provider": "WIKIMEDIA_COMMONS",
                "page_id": 101,
                "page_revision_id": 1001,
                "file_title": "File:Compact car side view.jpg",
                "canonical_page_url": (
                    "https://commons.wikimedia.org/wiki/File:Compact_car_side_view.jpg"
                ),
                "original_file_url": (
                    "https://upload.wikimedia.org/wikipedia/commons/a/ab/Compact_car.jpg"
                ),
                "original_media_type": "image/jpeg",
                "original_size_bytes": 100_000,
                "original_sha256": _sha(10),
                "original_width_px": 1200,
                "original_height_px": 800,
                "license_id": "CC0-1.0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "license_short_name": "CC0 1.0",
                "attribution_required": False,
                "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                "disposition": "PRIMARY_CONDITIONING",
            },
            {
                "reference_id": "imgref_" + "b" * 32,
                "rank": 2,
                "provider": "WIKIMEDIA_COMMONS",
                "page_id": 102,
                "page_revision_id": 1002,
                "file_title": "File:Small automobile profile.png",
                "canonical_page_url": (
                    "https://commons.wikimedia.org/wiki/File:Small_automobile_profile.png"
                ),
                "original_file_url": (
                    "https://upload.wikimedia.org/wikipedia/commons/b/bc/Automobile.png"
                ),
                "original_media_type": "image/png",
                "original_size_bytes": 80_000,
                "original_sha256": _sha(11),
                "original_width_px": 1000,
                "original_height_px": 700,
                "license_id": "PUBLIC-DOMAIN",
                "license_url": ("https://commons.wikimedia.org/wiki/Commons:Public_domain"),
                "license_short_name": "Public domain",
                "attribution_required": False,
                "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                "disposition": "VERIFIED_ALTERNATE",
            },
        ],
        "primary_reference_id": "imgref_" + "a" * 32,
        "normalization_policy": "reference-raster-normalization/1.0",
        "normalized_member": {
            "member_path": "references/primary.png",
            "schema_ref": "eom://schemas/image-provider/normalized-visual-reference/1.0",
            "media_type": "image/png",
            "width_px": 800,
            "height_px": 504,
            "mode": "RGB",
            "size_bytes": 30_000,
            "sha256": _sha(12),
        },
    }
    return LocalImageVisualReferenceBundle.model_validate(
        {**body, "bundle_sha256": content_sha256(body)}
    )


def _composite_request() -> LocalImageCompositeRequest:
    model = LocalImageModelPointer(
        model_id="imgmodel_" + "1" * 32,
        model_revision_id="imgmodelrev_" + "2" * 32,
        manifest_sha256=_sha(13),
    )
    prompt = "black-and-white assessment figure: one compact car in side view"
    negative = "color, text, human"
    generation_body = {
        "schema_version": "local-image-generation-request/1.0",
        "request_id": "imgreq_" + "3" * 32,
        "idempotency_key": "local-image:" + "4" * 64,
        "model": model.model_dump(mode="json"),
        "prompt": prompt,
        "prompt_sha256": text_sha256(prompt),
        "negative_prompt": negative,
        "negative_prompt_sha256": text_sha256(negative),
        "seed": 100,
        "sampler": SamplerContract(
            inference_steps=20,
            guidance_scale=5.0,
        ).model_dump(mode="json"),
        "generation_canvas": {"width_px": 800, "height_px": 504},
        "delivery_canvas": {"width_px": 800, "height_px": 500},
        "output_member": "generated-background.png",
        "timeout_seconds": 300,
    }
    generation = LocalImageGenerationRequest.model_validate(
        {**generation_body, "request_sha256": content_sha256(generation_body)}
    )
    overlay = LocalImageOverlayInput(
        size_bytes=20_000,
        sha256=_sha(14),
    )
    body = {
        "schema_version": "local-image-composite-request/1.0",
        "generation": generation.model_dump(mode="json"),
        "overlay": overlay.model_dump(mode="json"),
        "final_output_member": "generated-stimulus.png",
    }
    return LocalImageCompositeRequest.model_validate(
        {**body, "composite_request_sha256": content_sha256(body)}
    )


def _reference_pointer() -> LocalImageVisualReferencePointer:
    artifact_id = "artifact_" + "c" * 32
    revision_id = "rev_" + "d" * 32
    return LocalImageVisualReferencePointer(
        bundle_id="imgrefbundle_" + "5" * 32,
        bundle_revision_id="imgrefbundlerev_" + "6" * 32,
        bundle_manifest=VisualReferenceBundleManifestPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            sha256=_sha(15),
            size_bytes=10_000,
        ),
        primary_reference_id="imgref_" + "a" * 32,
        reference_member=VisualReferencePngArtifactPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            sha256=_sha(12),
            size_bytes=30_000,
        ),
    )


def _conditioned_request() -> LocalImageReferenceConditionedCompositeRequest:
    body = {
        "schema_version": "local-image-reference-conditioned-composite-request/1.0",
        "composite_request": _composite_request().model_dump(mode="json"),
        "visual_reference": _reference_pointer().model_dump(mode="json"),
        "conditioning": LocalImageReferenceConditioning().model_dump(mode="json"),
    }
    return LocalImageReferenceConditionedCompositeRequest.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )


def _style_adapter_release() -> LocalImageProductionStyleAdapterRelease:
    model = _composite_request().generation.model
    body = {
        "schema_version": "local-image-style-adapter-release/1.0",
        "release_id": "imgstylerelease_" + "1" * 32,
        "release_revision_id": "imgstylereleaserev_" + "2" * 32,
        "state": "RELEASED",
        "adapter_contract": "eom-assessment-style-lora/1.0",
        "adapter_id": "imgadapter_" + "3" * 32,
        "adapter_revision_id": "imgadapterrev_" + "4" * 32,
        "base_model": model.model_dump(mode="json"),
        "source_adapter_manifest": ProductionStyleAdapterSourceManifestPointer(
            artifact_id="artifact_" + "5" * 32,
            artifact_revision_id="rev_" + "6" * 32,
            sha256=_sha(30),
            size_bytes=5000,
        ).model_dump(mode="json"),
        "evaluation_result": ProductionStyleAdapterEvaluationPointer(
            artifact_id="artifact_" + "7" * 32,
            artifact_revision_id="rev_" + "8" * 32,
            sha256=_sha(31),
            size_bytes=6000,
        ).model_dump(mode="json"),
        "files": [
            ProductionStyleAdapterFile(
                relative_path="adapter_config.json",
                size_bytes=1000,
                sha256=_sha(32),
            ).model_dump(mode="json"),
            ProductionStyleAdapterFile(
                relative_path="adapter_model.safetensors",
                size_bytes=200_000,
                sha256=_sha(33),
            ).model_dump(mode="json"),
        ],
        "lora_scale": 0.8,
        "approved_at": "2026-09-27T13:00:00Z",
        "approved_by": "operator_test",
    }
    return LocalImageProductionStyleAdapterRelease.model_validate(
        {**body, "release_sha256": content_sha256(body)}
    )


def _conditioned_request_v2() -> LocalImageReferenceConditionedCompositeRequestV2:
    body = {
        "schema_version": "local-image-reference-conditioned-composite-request/2.0",
        "composite_request": _composite_request().model_dump(mode="json"),
        "visual_reference": _reference_pointer().model_dump(mode="json"),
        "conditioning": LocalImageReferenceConditioning().model_dump(mode="json"),
        "style_adapter": _style_adapter_release().model_dump(mode="json"),
    }
    return LocalImageReferenceConditionedCompositeRequestV2.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )


def _conditioned_request_v3() -> LocalImageReferenceConditionedCompositeRequestV3:
    body = {
        "schema_version": "local-image-reference-conditioned-composite-request/3.0",
        "composite_request": _composite_request().model_dump(mode="json"),
        "visual_reference": _reference_pointer().model_dump(mode="json"),
        "conditioning": LocalImageMorphologyConditioning().model_dump(mode="json"),
        "style_adapter": _style_adapter_release().model_dump(mode="json"),
    }
    return LocalImageReferenceConditionedCompositeRequestV3.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )


def _acquisition_command() -> LocalImageVisualReferenceAcquisitionCommand:
    body = {
        "schema_version": "local-image-visual-reference-acquisition-command/1.0",
        "command_id": "imgrefcmd_" + "1" * 32,
        "attempt_id": "imgrefattempt_" + "2" * 32,
        "intent": _bundle().intent.model_dump(mode="json"),
        "intent_member_path": "input/visual-reference-intent.json",
        "observed_at": "2026-09-27T12:00:00Z",
        "max_original_bytes": 16_777_216,
        "timeout_seconds": 120,
    }
    return LocalImageVisualReferenceAcquisitionCommand.model_validate(
        {**body, "command_sha256": content_sha256(body)}
    )


def _acquisition_result(
    command: LocalImageVisualReferenceAcquisitionCommand,
) -> LocalImageVisualReferenceAcquisitionResult:
    bundle = _bundle()
    outputs = (
        VisualReferenceAcquisitionOutputFile(
            member_path="manifests/visual-reference-bundle.json",
            schema_ref=("eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"),
            media_type="application/json",
            size_bytes=12_000,
            sha256=_sha(18),
        ),
        VisualReferenceAcquisitionOutputFile(
            member_path="references/primary.png",
            schema_ref="eom://schemas/image-provider/normalized-visual-reference/1.0",
            media_type="image/png",
            size_bytes=bundle.normalized_member.size_bytes,
            sha256=bundle.normalized_member.sha256,
        ),
    )
    body = {
        "schema_version": "local-image-visual-reference-acquisition-result/1.0",
        "command_id": command.command_id,
        "attempt_id": command.attempt_id,
        "command_sha256": command.command_sha256,
        "status": "SUCCEEDED",
        "bundle": bundle.model_dump(mode="json"),
        "output_files": [value.model_dump(mode="json") for value in outputs],
        "error_code": None,
        "started_at": "2026-09-27T12:00:00Z",
        "completed_at": "2026-09-27T12:00:01Z",
        "duration_ms": 1000,
    }
    return LocalImageVisualReferenceAcquisitionResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )


def _conditioned_receipt(
    request: LocalImageReferenceConditionedCompositeRequest,
) -> LocalImageReferenceConditionedCompositeReceipt:
    started = datetime(2026, 9, 27, 12, 1, tzinfo=UTC)
    completed = started + timedelta(seconds=2)
    generation_request = request.composite_request.generation
    generation_body = {
        "schema_version": "local-image-generation-receipt/1.0",
        "request_id": generation_request.request_id,
        "request_sha256": generation_request.request_sha256,
        "model": generation_request.model.model_dump(mode="json"),
        "prompt_sha256": generation_request.prompt_sha256,
        "negative_prompt_sha256": generation_request.negative_prompt_sha256,
        "seed": generation_request.seed,
        "sampler": generation_request.sampler.model_dump(mode="json"),
        "output": LocalImageOutput(size_bytes=25_000, sha256=_sha(16)).model_dump(mode="json"),
        "runtime": LocalImageRuntime(
            python_version="3.12.12",
            torch_version="2.7.1",
            diffusers_version="0.35.2",
            transformers_version="4.56.2",
            cuda_version="12.8",
            gpu_name="test-gpu",
            compute_capability="12.0",
            peak_gpu_memory_bytes=1024,
        ).model_dump(mode="json"),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "completed_at": completed.isoformat().replace("+00:00", "Z"),
        "duration_ms": 2000,
    }
    generation = LocalImageGenerationReceipt.model_validate(
        {**generation_body, "receipt_sha256": content_sha256(generation_body)}
    )
    composite_body = {
        "schema_version": "local-image-composite-receipt/1.0",
        "composite_request_sha256": request.composite_request.composite_request_sha256,
        "generation": generation.model_dump(mode="json"),
        "overlay": request.composite_request.overlay.model_dump(mode="json"),
        "output": LocalImageFinalOutput(size_bytes=30_000, sha256=_sha(17)).model_dump(mode="json"),
        "compositor": LocalImageCompositorRuntime(pillow_version="11.3.0").model_dump(mode="json"),
        "completed_at": (completed + timedelta(milliseconds=50)).isoformat().replace("+00:00", "Z"),
        "duration_ms": 2050,
    }
    composite = LocalImageCompositeReceipt.model_validate(
        {**composite_body, "receipt_sha256": content_sha256(composite_body)}
    )
    body = {
        "schema_version": "local-image-reference-conditioned-composite-receipt/1.0",
        "request_sha256": request.request_sha256,
        "composite_receipt": composite.model_dump(mode="json"),
        "visual_reference": request.visual_reference.model_dump(mode="json"),
        "conditioning": request.conditioning.model_dump(mode="json"),
        "completed_at": (completed + timedelta(milliseconds=100))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    return LocalImageReferenceConditionedCompositeReceipt.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )


def test_visual_reference_intent_passes_json_schema_and_pydantic() -> None:
    intent = _intent()
    validate_contract("visual-reference-intent", intent.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("primary_candidate_page_id", 102, "rank one"),
        ("intent_sha256", _sha(999), "hash mismatch"),
    ),
)
def test_visual_reference_intent_rejects_semantic_drift(
    field: str, value: object, match: str
) -> None:
    payload = _intent().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(PydanticValidationError, match=match):
        LocalImageVisualReferenceIntent.model_validate(payload)


def test_visual_reference_intent_rejects_unreviewed_host() -> None:
    payload = _intent().model_dump(mode="json")
    payload["candidates"][0]["canonical_page_url"] = "https://example.com/wiki/File:Compact_car.jpg"
    with pytest.raises(PydanticValidationError, match="reviewed boundary"):
        LocalImageVisualReferenceIntent.model_validate(payload)


def test_visual_reference_bundle_passes_json_schema_and_pydantic() -> None:
    bundle = _bundle()
    validate_contract("visual-reference-bundle", bundle.model_dump(mode="json"))
    assert bundle.sources[0].disposition == "PRIMARY_CONDITIONING"


def test_visual_reference_bundle_rejects_duplicate_original_hash() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["sources"][1]["original_sha256"] = payload["sources"][0]["original_sha256"]
    body = {key: value for key, value in payload.items() if key != "bundle_sha256"}
    payload["bundle_sha256"] = content_sha256(body)
    with pytest.raises(PydanticValidationError, match="original hashes must be unique"):
        LocalImageVisualReferenceBundle.model_validate(payload)


def test_conditioned_request_and_receipt_pass_both_contract_layers() -> None:
    request = _conditioned_request()
    receipt = _conditioned_receipt(request)
    validate_contract(
        "reference-conditioned-composite-request",
        request.model_dump(mode="json"),
    )
    validate_contract(
        "reference-conditioned-composite-receipt",
        receipt.model_dump(mode="json"),
    )
    validate_reference_conditioned_receipt(request, receipt)


def test_style_reference_v2_contracts_pin_adapter_reference_and_unchanged_prompt() -> None:
    request = _conditioned_request_v2()
    v1_request = LocalImageReferenceConditionedCompositeRequest.model_validate(
        {
            "schema_version": "local-image-reference-conditioned-composite-request/1.0",
            "composite_request": request.composite_request.model_dump(mode="json"),
            "visual_reference": request.visual_reference.model_dump(mode="json"),
            "conditioning": request.conditioning.model_dump(mode="json"),
            "request_sha256": content_sha256(
                {
                    "schema_version": ("local-image-reference-conditioned-composite-request/1.0"),
                    "composite_request": request.composite_request.model_dump(mode="json"),
                    "visual_reference": request.visual_reference.model_dump(mode="json"),
                    "conditioning": request.conditioning.model_dump(mode="json"),
                }
            ),
        }
    )
    composite_receipt = _conditioned_receipt(v1_request).composite_receipt
    receipt_body = {
        "schema_version": "local-image-reference-conditioned-composite-receipt/2.0",
        "request_sha256": request.request_sha256,
        "composite_receipt": composite_receipt.model_dump(mode="json"),
        "visual_reference": request.visual_reference.model_dump(mode="json"),
        "conditioning": request.conditioning.model_dump(mode="json"),
        "style_adapter": request.style_adapter.model_dump(mode="json"),
        "completed_at": "2026-09-27T13:01:00Z",
    }
    receipt = LocalImageReferenceConditionedCompositeReceiptV2.model_validate(
        {**receipt_body, "receipt_sha256": content_sha256(receipt_body)}
    )
    binding_body = {
        "schema_version": "local-image-provider-binding/2.0",
        "state": "ENABLED",
        "route_contract": "eom-local-reference-conditioned-background/2.0",
        "model": request.composite_request.generation.model.model_dump(mode="json"),
        "style_adapter": request.style_adapter.model_dump(mode="json"),
        "reference_policy": LocalImageVisualReferencePolicy().model_dump(mode="json"),
        "sampler": request.composite_request.generation.sampler.model_dump(mode="json"),
        "timeout_seconds": 300,
    }
    binding = LocalImageProviderBindingV2.model_validate(
        {**binding_body, "binding_sha256": content_sha256(binding_body)}
    )

    for name, value in (
        ("style-adapter-release", request.style_adapter.model_dump(mode="json")),
        ("provider-binding-v2", binding.model_dump(mode="json")),
        ("reference-conditioned-composite-request-v2", request.model_dump(mode="json")),
        ("reference-conditioned-composite-receipt-v2", receipt.model_dump(mode="json")),
    ):
        validate_contract(name, value)
    validate_reference_conditioned_receipt_v2(request, receipt)
    assert request.composite_request.generation.prompt == _composite_request().generation.prompt


def test_simplified_morphology_v3_contracts_pin_conditioning_bytes_and_metrics() -> None:
    request = _conditioned_request_v3()
    v1_body = {
        "schema_version": "local-image-reference-conditioned-composite-request/1.0",
        "composite_request": request.composite_request.model_dump(mode="json"),
        "visual_reference": request.visual_reference.model_dump(mode="json"),
        "conditioning": LocalImageReferenceConditioning().model_dump(mode="json"),
    }
    v1_request = LocalImageReferenceConditionedCompositeRequest.model_validate(
        {**v1_body, "request_sha256": content_sha256(v1_body)}
    )
    composite_receipt = _conditioned_receipt(v1_request).composite_receipt
    receipt_body = {
        "schema_version": "local-image-reference-conditioned-composite-receipt/3.0",
        "request_sha256": request.request_sha256,
        "composite_receipt": composite_receipt.model_dump(mode="json"),
        "visual_reference": request.visual_reference.model_dump(mode="json"),
        "conditioning": request.conditioning.model_dump(mode="json"),
        "style_adapter": request.style_adapter.model_dump(mode="json"),
        "conditioning_output": {
            "member_path": "reference-conditioning.png",
            "media_type": "image/png",
            "sha256": _sha(31),
            "size_bytes": 12_000,
            "width_px": 800,
            "height_px": 504,
        },
        "simplification_metrics": {
            "source_foreground_ratio": 0.32,
            "conditioning_foreground_ratio": 0.28,
            "border_foreground_ratio": 0.01,
            "source_edge_density": 0.14,
            "conditioning_edge_density": 0.06,
            "edge_density_ratio": 0.42857143,
        },
        "simplifier_runtime": {
            "contract": "local-image-reference-simplifier/1.0",
            "pillow_version": "11.3.0",
        },
        "completed_at": "2026-09-27T13:01:00Z",
    }
    receipt = LocalImageReferenceConditionedCompositeReceiptV3.model_validate(
        {**receipt_body, "receipt_sha256": content_sha256(receipt_body)}
    )
    binding_body = {
        "schema_version": "local-image-provider-binding/3.0",
        "state": "ENABLED",
        "route_contract": "eom-local-morphology-conditioned-line-art/3.0",
        "model": request.composite_request.generation.model.model_dump(mode="json"),
        "style_adapter": request.style_adapter.model_dump(mode="json"),
        "reference_policy": LocalImageVisualReferencePolicyV2().model_dump(mode="json"),
        "sampler": request.composite_request.generation.sampler.model_dump(mode="json"),
        "timeout_seconds": 300,
    }
    binding = LocalImageProviderBindingV3.model_validate(
        {**binding_body, "binding_sha256": content_sha256(binding_body)}
    )

    for name, value in (
        ("provider-binding-v3", binding.model_dump(mode="json")),
        ("reference-conditioned-composite-request-v3", request.model_dump(mode="json")),
        ("reference-conditioned-composite-receipt-v3", receipt.model_dump(mode="json")),
    ):
        validate_contract(name, value)
    validate_reference_conditioned_receipt_v3(request, receipt)


def test_simplified_morphology_v3_rejects_metrics_outside_pinned_policy() -> None:
    request = _conditioned_request_v3()
    payload = {
        "schema_version": "local-image-reference-conditioned-composite-receipt/3.0",
        "request_sha256": request.request_sha256,
        "composite_receipt": _conditioned_receipt(
            _conditioned_request()
        ).composite_receipt.model_dump(mode="json"),
        "visual_reference": request.visual_reference.model_dump(mode="json"),
        "conditioning": request.conditioning.model_dump(mode="json"),
        "style_adapter": request.style_adapter.model_dump(mode="json"),
        "conditioning_output": {
            "sha256": _sha(31),
            "size_bytes": 12_000,
        },
        "simplification_metrics": {
            "source_foreground_ratio": 0.32,
            "conditioning_foreground_ratio": 0.28,
            "border_foreground_ratio": 0.13,
            "source_edge_density": 0.14,
            "conditioning_edge_density": 0.06,
            "edge_density_ratio": 0.42857143,
        },
        "simplifier_runtime": {"pillow_version": "11.3.0"},
        "completed_at": "2026-09-27T13:01:00Z",
    }
    payload["receipt_sha256"] = content_sha256(payload)
    with pytest.raises(PydanticValidationError, match="border ratio"):
        LocalImageReferenceConditionedCompositeReceiptV3.model_validate(payload)


def test_style_reference_v2_rejects_adapter_for_another_base_model() -> None:
    payload = _style_adapter_release().model_dump(mode="json")
    payload["base_model"]["model_revision_id"] = "imgmodelrev_" + "f" * 32
    body = {key: value for key, value in payload.items() if key != "release_sha256"}
    payload["release_sha256"] = content_sha256(body)
    adapter = LocalImageProductionStyleAdapterRelease.model_validate(payload)
    request_payload = _conditioned_request_v2().model_dump(mode="json")
    request_payload["style_adapter"] = adapter.model_dump(mode="json")
    body = {key: value for key, value in request_payload.items() if key != "request_sha256"}
    request_payload["request_sha256"] = content_sha256(body)
    with pytest.raises(PydanticValidationError, match="base model differs"):
        LocalImageReferenceConditionedCompositeRequestV2.model_validate(request_payload)


def test_conditioned_pointer_rejects_cross_revision_members() -> None:
    payload = _reference_pointer().model_dump(mode="json")
    payload["reference_member"]["artifact_revision_id"] = "rev_" + "e" * 32
    with pytest.raises(PydanticValidationError, match="one Artifact Revision"):
        LocalImageVisualReferencePointer.model_validate(payload)


def test_conditioned_receipt_rejects_another_reference_pointer() -> None:
    request = _conditioned_request()
    receipt = _conditioned_receipt(request)
    other_reference = request.visual_reference.model_copy(
        update={"primary_reference_id": "imgref_" + "f" * 32}
    )
    other = receipt.model_copy(update={"visual_reference": other_reference})
    with pytest.raises(ValueError, match="differs from its request"):
        validate_reference_conditioned_receipt(request, other)


def test_visual_reference_acquisition_passes_schema_and_cross_contract_validation() -> None:
    command = _acquisition_command()
    intent = _intent()
    result = _acquisition_result(command)
    validate_contract(
        "visual-reference-acquisition-command",
        command.model_dump(mode="json"),
    )
    validate_contract(
        "visual-reference-acquisition-result",
        result.model_dump(mode="json"),
    )
    validate_visual_reference_acquisition(command, intent, result)


def test_visual_reference_publication_receipt_binds_image_result_and_all_handoffs() -> None:
    entry = VisualReferencePublicationEntry(
        visual_ordinal=0,
        drawing_sha256=_sha(40),
        subject_sha256=_sha(41),
        discovery_command_sha256=_sha(42),
        discovery_result_sha256=_sha(43),
        intent_sha256=_sha(44),
        acquisition_command_sha256=_sha(45),
        acquisition_result_sha256=_sha(46),
        visual_reference=_reference_pointer(),
    )
    body = {
        "schema_version": "local-image-visual-reference-publication-receipt/1.0",
        "image_result_artifact": VisualReferenceImageResultArtifactPointer(
            logical_artifact_id="artifact_" + "1" * 32,
            revision_id="rev_" + "2" * 32,
            content_hash=_sha(47),
        ).model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json")],
        "published_at": "2026-09-27T15:30:00Z",
    }
    receipt = LocalImageVisualReferencePublicationReceipt.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )

    validate_contract("visual-reference-publication-receipt", receipt.model_dump(mode="json"))
    assert receipt.entries[0].visual_reference == _reference_pointer()


def test_visual_reference_publication_receipt_rejects_duplicate_ordinals() -> None:
    entry = VisualReferencePublicationEntry(
        visual_ordinal=0,
        drawing_sha256=_sha(40),
        subject_sha256=_sha(41),
        discovery_command_sha256=_sha(42),
        discovery_result_sha256=_sha(43),
        intent_sha256=_sha(44),
        acquisition_command_sha256=_sha(45),
        acquisition_result_sha256=_sha(46),
        visual_reference=_reference_pointer(),
    )
    body = {
        "schema_version": "local-image-visual-reference-publication-receipt/1.0",
        "image_result_artifact": VisualReferenceImageResultArtifactPointer(
            logical_artifact_id="artifact_" + "1" * 32,
            revision_id="rev_" + "2" * 32,
            content_hash=_sha(47),
        ).model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json"), entry.model_dump(mode="json")],
        "published_at": "2026-09-27T15:30:00Z",
    }
    with pytest.raises(PydanticValidationError, match="ordinals must be sorted and unique"):
        LocalImageVisualReferencePublicationReceipt.model_validate(
            {**body, "receipt_sha256": content_sha256(body)}
        )


def test_visual_reference_acquisition_rejects_candidate_population_drift() -> None:
    command = _acquisition_command()
    intent_payload = _intent().model_dump(mode="json")
    intent_payload["candidates"][1]["page_id"] = 999
    body = {key: value for key, value in intent_payload.items() if key != "intent_sha256"}
    intent_payload["intent_sha256"] = content_sha256(body)
    intent = LocalImageVisualReferenceIntent.model_validate(intent_payload)
    with pytest.raises(ValueError, match="verified source differs"):
        validate_visual_reference_acquisition(command, intent, _acquisition_result(command))


def test_failed_visual_reference_acquisition_carries_no_outputs() -> None:
    command = _acquisition_command()
    body = {
        "schema_version": "local-image-visual-reference-acquisition-result/1.0",
        "command_id": command.command_id,
        "attempt_id": command.attempt_id,
        "command_sha256": command.command_sha256,
        "status": "FAILED",
        "bundle": None,
        "output_files": [],
        "error_code": "VISUAL_REFERENCE_LICENSE_REJECTED",
        "started_at": "2026-09-27T12:00:00Z",
        "completed_at": "2026-09-27T12:00:01Z",
        "duration_ms": 1000,
    }
    result = LocalImageVisualReferenceAcquisitionResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )
    validate_contract("visual-reference-acquisition-result", result.model_dump(mode="json"))
    validate_visual_reference_acquisition(command, _intent(), result)
