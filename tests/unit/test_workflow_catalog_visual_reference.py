from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identifiers import sha256_file

from tests.unit.test_local_image_adapter import (
    _binding_v2_value,
    _binding_v3_value,
    _binding_v4_value,
    _binding_v5_value,
    _binding_v6_value,
)
from tests.unit.test_visual_reference_receipts import _receipt
from tests.unit.test_workflow_catalog_generated import (
    AUTHORING_V12,
    IMAGE_V12,
    _content_team_authoring_result_v12,
    _content_team_image_result_v12,
    _service,
    _workflow,
)


def test_latest_content_team_hybrid_uses_style_and_exact_visual_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifacts = _service(tmp_path)
    authoring = _content_team_authoring_result_v12()
    image = _content_team_image_result_v12()
    authoring_draft = cast(dict[str, Any], cast(dict[str, Any], authoring["output"])["draft"])
    authoring_draft["visuals"] = [{"kind": "IMAGE", "label": ""}]
    authoring_draft["visual_layout"] = "IMAGE_ONLY"
    image_output = cast(dict[str, Any], image["output"])
    image_output["drawings"] = image_output["drawings"][:1]
    drawing_entry = cast(dict[str, Any], image_output["drawings"][0])
    drawing_entry["label"] = ""
    drawing = cast(dict[str, Any], drawing_entry["drawing"])
    drawing.update(
        {
            "kind": "natural_scene",
            "production_route": "HYBRID_LOCAL_GENERATIVE",
            "route_reason": "ORGANIC_OBJECT_REQUIRED",
            "alt_text": "one stag beetle in side view isolated on white",
            "scene_description": "사슴벌레 한 마리의 옆모습",
            "scientific_constraints": ["사슴벌레는 한 마리이다."],
            "required_labels": [],
            "generation_prompt": drawing_entry["illustration_prompt"],
            "negative_prompt": None,
        }
    )
    artifacts.values[AUTHORING_V12.revision_id] = authoring
    artifacts.values[IMAGE_V12.revision_id] = image
    service.local_image = cast(Any, object())
    reference_receipt = _receipt(IMAGE_V12)
    reference = reference_receipt.entries[0].visual_reference
    reference_payload = b"bounded-normalized-reference-png"

    class _References:
        def resolve(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["visual_ordinal"] == 0
            return SimpleNamespace(
                pointer=reference,
                payload=reference_payload,
                publication_receipt_sha256=reference_receipt.receipt_sha256,
            )

    service.visual_reference_receipts = _References()
    svg = tmp_path / "reference.svg"
    raster = tmp_path / "reference-raster.png"
    png = tmp_path / "reference-final.png"
    receipt_file = tmp_path / "reference-receipt.json"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")
    raster.write_bytes(b"bounded-reference-conditioned-raster")
    png.write_bytes(b"bounded-reference-conditioned-final")
    receipt_file.write_text("{}\n", encoding="utf-8")

    def render(*_args: object, **kwargs: object) -> SimpleNamespace:
        assert kwargs["visual_reference"] == reference
        assert kwargs["reference_bytes"] == reference_payload
        return SimpleNamespace(
            svg_path=svg,
            background_path=raster,
            png_path=png,
            receipt_path=receipt_file,
            receipt=SimpleNamespace(receipt_sha256="sha256:" + "1" * 64),
            request_sha256="sha256:" + "2" * 64,
            unit_name="eom-image-reference-style-provider@imgreq_" + "3" * 32 + ".service",
            renderer_contract="eom-safe-svg-compositor/1.1",
            renderer_version="rsvg-convert version 2.58.0",
            renderer_sha256="sha256:" + "a" * 64,
            font_sha256="sha256:" + "b" * 64,
            font_manifest_sha256="sha256:" + "c" * 64,
            prompt_policy_revision="local-gpu-image-prompt-policy/1.4",
        )

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_style_reference_stimulus",
        render,
    )
    binding = _binding_v2_value()
    pointers = service.materialize_content_team_stimuli(
        workflow=_workflow({"local_image_provider": binding}),
        artifacts=(AUTHORING_V12, IMAGE_V12),
    )

    assert len(pointers) == 1
    committed = artifacts.commits[0]
    assert committed["manifest_version"] == "generated-item-stimulus-file-set/5.0"
    assert committed["result"]["visual_reference_publication_receipt_sha256"] == (
        reference_receipt.receipt_sha256
    )
    assert committed["result"]["visual_reference_bundle_revision_id"] == (
        reference.bundle_revision_id
    )
    assert (
        committed["result"]["style_adapter_release_sha256"]
        == binding["style_adapter"]["release_sha256"]
    )
    assert committed["file_metadata"]["local-image-receipt.json"]["schema_ref"].endswith("/2.0")
    assert committed["expected_file_sha256"]["generated-stimulus.png"] == sha256_file(png)
    assert binding["binding_sha256"] in committed["idempotency_key"]
    serialized_result = json.dumps(committed["result"]).casefold()
    assert "generation_prompt" not in serialized_result
    assert 'illustration_prompt"' not in serialized_result


def test_simplified_reference_binding_commits_exact_conditioning_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifacts = _service(tmp_path)
    authoring = _content_team_authoring_result_v12()
    image = _content_team_image_result_v12()
    authoring_draft = cast(dict[str, Any], cast(dict[str, Any], authoring["output"])["draft"])
    authoring_draft["visuals"] = [{"kind": "IMAGE", "label": ""}]
    authoring_draft["visual_layout"] = "IMAGE_ONLY"
    image_output = cast(dict[str, Any], image["output"])
    image_output["drawings"] = image_output["drawings"][:1]
    drawing_entry = cast(dict[str, Any], image_output["drawings"][0])
    drawing_entry["label"] = ""
    drawing = cast(dict[str, Any], drawing_entry["drawing"])
    drawing.update(
        {
            "kind": "natural_scene",
            "production_route": "HYBRID_LOCAL_GENERATIVE",
            "route_reason": "ORGANIC_OBJECT_REQUIRED",
            "alt_text": "one stag beetle in side view isolated on white",
            "scene_description": "사슴벌레 한 마리의 옆모습",
            "scientific_constraints": ["사슴벌레는 한 마리이다."],
            "required_labels": [],
            "generation_prompt": drawing_entry["illustration_prompt"],
            "negative_prompt": None,
        }
    )
    artifacts.values[AUTHORING_V12.revision_id] = authoring
    artifacts.values[IMAGE_V12.revision_id] = image
    service.local_image = cast(Any, object())
    reference_receipt = _receipt(IMAGE_V12)
    reference = reference_receipt.entries[0].visual_reference

    class _References:
        def resolve(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                pointer=reference,
                payload=b"bounded-normalized-reference-png",
                publication_receipt_sha256=reference_receipt.receipt_sha256,
            )

    service.visual_reference_receipts = _References()
    files = {
        "svg_path": tmp_path / "reference-v3.svg",
        "background_path": tmp_path / "reference-v3-raster.png",
        "png_path": tmp_path / "reference-v3-final.png",
        "conditioning_path": tmp_path / "reference-v3-conditioning.png",
        "receipt_path": tmp_path / "reference-v3-receipt.json",
    }
    for key, path in files.items():
        path.write_bytes(("bounded-" + key).encode())

    class _RenderedV3:
        def __init__(self) -> None:
            for key, path in files.items():
                setattr(self, key, path)
            self.receipt = SimpleNamespace(receipt_sha256="sha256:" + "1" * 64)
            self.request_sha256 = "sha256:" + "2" * 64
            self.prompt_policy_revision = "local-gpu-image-prompt-policy/1.8"

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.RenderedSimplifiedStyleReferenceStimulus",
        _RenderedV3,
    )
    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_simplified_style_reference_stimulus",
        lambda *_args, **_kwargs: _RenderedV3(),
    )
    binding = _binding_v3_value()
    pointers = service.materialize_content_team_stimuli(
        workflow=_workflow({"local_image_provider": binding}),
        artifacts=(AUTHORING_V12, IMAGE_V12),
    )

    assert len(pointers) == 1
    committed = artifacts.commits[0]
    assert committed["manifest_version"] == "generated-item-stimulus-file-set/6.0"
    assert committed["file_metadata"]["reference-conditioning.png"] == {
        "schema_ref": "eom://schemas/image-provider/simplified-reference-conditioning/1.0",
        "media_type": "image/png",
    }
    assert committed["expected_file_sha256"]["reference-conditioning.png"] == sha256_file(
        files["conditioning_path"]
    )
    assert committed["file_metadata"]["local-image-receipt.json"]["schema_ref"].endswith("/3.0")
    assert binding["binding_sha256"] in committed["idempotency_key"]


@pytest.mark.parametrize(
    ("binding_factory", "receipt_version", "manifest_version"),
    (
        (_binding_v4_value, "4.0", "generated-item-stimulus-file-set/7.0"),
        (_binding_v5_value, "5.0", "generated-item-stimulus-file-set/8.0"),
        (_binding_v6_value, "6.0", "generated-item-stimulus-file-set/9.0"),
    ),
)
def test_base_only_reference_binding_commits_without_style_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_factory: Any,
    receipt_version: str,
    manifest_version: str,
) -> None:
    service, artifacts = _service(tmp_path)
    authoring = _content_team_authoring_result_v12()
    image = _content_team_image_result_v12()
    authoring_draft = cast(dict[str, Any], cast(dict[str, Any], authoring["output"])["draft"])
    authoring_draft["visuals"] = [{"kind": "IMAGE", "label": ""}]
    authoring_draft["visual_layout"] = "IMAGE_ONLY"
    image_output = cast(dict[str, Any], image["output"])
    image_output["drawings"] = image_output["drawings"][:1]
    drawing_entry = cast(dict[str, Any], image_output["drawings"][0])
    drawing_entry["label"] = ""
    drawing = cast(dict[str, Any], drawing_entry["drawing"])
    drawing.update(
        {
            "kind": "natural_scene",
            "production_route": "HYBRID_LOCAL_GENERATIVE",
            "route_reason": "ORGANIC_OBJECT_REQUIRED",
            "alt_text": "one trilobite fossil isolated on white",
            "scene_description": "삼엽충 화석 한 개의 윗면",
            "scientific_constraints": ["삼엽충 화석은 한 개이다."],
            "required_labels": [],
            "generation_prompt": drawing_entry["illustration_prompt"],
            "negative_prompt": None,
        }
    )
    artifacts.values[AUTHORING_V12.revision_id] = authoring
    artifacts.values[IMAGE_V12.revision_id] = image
    service.local_image = cast(Any, object())
    reference_receipt = _receipt(IMAGE_V12)
    reference = reference_receipt.entries[0].visual_reference

    class _References:
        def resolve(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                pointer=reference,
                payload=b"bounded-normalized-reference-png",
                publication_receipt_sha256=reference_receipt.receipt_sha256,
            )

    service.visual_reference_receipts = _References()
    files = {
        "svg_path": tmp_path / "reference-v4.svg",
        "background_path": tmp_path / "reference-v4-raster.png",
        "png_path": tmp_path / "reference-v4-final.png",
        "conditioning_path": tmp_path / "reference-v4-conditioning.png",
        "receipt_path": tmp_path / "reference-v4-receipt.json",
    }
    for key, path in files.items():
        path.write_bytes(("bounded-" + key).encode())

    class _RenderedV4:
        def __init__(self) -> None:
            for key, path in files.items():
                setattr(self, key, path)
            self.receipt = SimpleNamespace(receipt_sha256="sha256:" + "1" * 64)
            self.request_sha256 = "sha256:" + "2" * 64
            self.prompt_policy_revision = "local-gpu-image-prompt-policy/1.8.1"

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.RenderedSimplifiedBaseReferenceStimulus",
        _RenderedV4,
    )
    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_simplified_base_reference_stimulus",
        lambda *_args, **_kwargs: _RenderedV4(),
    )
    binding = binding_factory()
    pointers = service.materialize_content_team_stimuli(
        workflow=_workflow({"local_image_provider": binding}),
        artifacts=(AUTHORING_V12, IMAGE_V12),
    )

    assert len(pointers) == 1
    committed = artifacts.commits[0]
    assert committed["manifest_version"] == manifest_version
    assert committed["file_metadata"]["local-image-receipt.json"]["schema_ref"].endswith(
        f"/{receipt_version}"
    )
    assert committed["expected_file_sha256"]["reference-conditioning.png"] == sha256_file(
        files["conditioning_path"]
    )
    assert "style_adapter_release_sha256" not in committed["result"]
    assert binding["binding_sha256"] in committed["idempotency_key"]
