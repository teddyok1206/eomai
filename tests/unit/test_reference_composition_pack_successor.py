from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.local_image_prompt_policy import (
    LOCAL_GPU_REFERENCE_PROMPT_POLICY_REVISION,
    compose_local_gpu_prompt_plan,
)
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _local_image_prompt_contract,
    _uses_v1_reference_conditioning,
)
from eom_identifiers import sha256_file
from eom_image_contracts import LocalImageProviderBinding
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord

from tests.unit.test_local_image_adapter import _binding_value
from tests.unit.test_visual_reference_receipts import _receipt
from tests.unit.test_workflow_catalog_generated import (
    AUTHORING_V12,
    IMAGE_V12,
    _content_team_authoring_result_v12,
    _content_team_image_result_v12,
    _service,
    _workflow,
)

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.2"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.3"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_reference_composition_pack_is_an_immutable_compatible_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)
    assert predecessor.manifest.pack.version == "1.20.2"
    assert pack.manifest.pack.version == "1.20.3"
    assert pack.manifest.compatibility == predecessor.manifest.compatibility
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.3", request
    )


def test_successor_changes_only_image_profile_and_prompt() -> None:
    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(PACK)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-stimulus-drawing.yaml"),
        Path("prompt-templates/image.md"),
    }
    prompt = (PACK / "prompt-templates/image.md").read_text(encoding="utf-8")
    for requirement in (
        "정확한 bytes",
        "좌우 반전",
        "`facing right`",
        "text-to-image로 조용히 대체하지 말고",
    ):
        assert requirement in prompt


def test_pack_selects_reference_composition_and_orientation_lock() -> None:
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {"content_pack": {"version": "1.20.3"}}
    binding = LocalImageProviderBinding.model_validate(_binding_value())
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
    assert _uses_v1_reference_conditioning(workflow, binding)

    plan = compose_local_gpu_prompt_plan(
        subject="one compact passenger car in side view facing right with its full body visible",
        production_route="HYBRID_LOCAL_GENERATIVE",
        prompt_contract="ASSESSMENT_REFERENCE_COMPOSITION_V3",
    )
    assert plan.policy_revision == LOCAL_GPU_REFERENCE_PROMPT_POLICY_REVISION
    assert "front of subject on right side" in plan.positive_prompt
    assert "mirrored orientation, facing left" in plan.negative_prompt

    predecessor = WorkflowInstanceRecord()
    predecessor.runtime_context = {"content_pack": {"version": "1.20.2"}}
    assert not _uses_v1_reference_conditioning(predecessor, binding)


def test_v1_binding_consumes_exact_published_reference_and_commits_receipt(
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
            "alt_text": "one compact passenger car in side view facing right",
            "scene_description": "오른쪽을 향한 승용차 한 대",
            "scientific_constraints": ["승용차는 오른쪽을 향한다."],
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
    reference_payload = b"bounded-exact-reference-png"

    class _References:
        def resolve(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["visual_ordinal"] == 0
            return SimpleNamespace(
                pointer=reference,
                payload=reference_payload,
                publication_receipt_sha256=reference_receipt.receipt_sha256,
            )

    service.visual_reference_receipts = cast(Any, _References())
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
        assert kwargs["prompt_contract"] == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
        return SimpleNamespace(
            svg_path=svg,
            background_path=raster,
            png_path=png,
            receipt_path=receipt_file,
            receipt=SimpleNamespace(receipt_sha256="sha256:" + "1" * 64),
            request_sha256="sha256:" + "2" * 64,
            unit_name="eom-image-reference-provider@imgreq_" + "3" * 32 + ".service",
            renderer_contract="eom-safe-svg-compositor/1.1",
            renderer_version="rsvg-convert version 2.58.0",
            renderer_sha256="sha256:" + "a" * 64,
            font_sha256="sha256:" + "b" * 64,
            font_manifest_sha256="sha256:" + "c" * 64,
            prompt_policy_revision=LOCAL_GPU_REFERENCE_PROMPT_POLICY_REVISION,
        )

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_reference_stimulus", render
    )
    binding = _binding_value()
    pointers = service.materialize_content_team_stimuli(
        workflow=_workflow(
            {
                "local_image_provider": binding,
                "content_pack": {"version": "1.20.3"},
            }
        ),
        artifacts=(AUTHORING_V12, IMAGE_V12),
    )

    assert len(pointers) == 1
    committed = artifacts.commits[0]
    assert committed["manifest_version"] == "generated-item-stimulus-file-set/4.1"
    assert committed["result"]["visual_reference_publication_receipt_sha256"] == (
        reference_receipt.receipt_sha256
    )
    assert committed["result"]["visual_reference_bundle_revision_id"] == (
        reference.bundle_revision_id
    )
    assert committed["file_metadata"]["local-image-receipt.json"]["schema_ref"].endswith("/1.0")
    assert committed["expected_file_sha256"]["generated-stimulus.png"] == sha256_file(png)
    assert binding["binding_sha256"] in committed["idempotency_key"]
    assert "sha256:" + "2" * 64 in committed["idempotency_key"]
    serialized_result = json.dumps(committed["result"]).casefold()
    assert "generation_prompt" not in serialized_result
    assert 'illustration_prompt"' not in serialized_result
