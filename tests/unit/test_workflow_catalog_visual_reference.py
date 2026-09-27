from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identifiers import sha256_file

from tests.unit.test_local_image_adapter import _binding_v2_value
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
