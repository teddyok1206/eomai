from __future__ import annotations

import binascii
import hashlib
import json
import os
import struct
import zlib
from pathlib import Path

import pytest
from eom_catalog_service.local_image_adapter import (
    LocalImageAdapterError,
    _build_request,
    load_local_image_provider_binding,
)
from eom_image_contracts import LocalImageProviderBinding, content_sha256
from eom_workflow.models import GeneratedVectorDrawingV5, GeneratedVectorDrawingV6


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))


def _overlay_png() -> bytes:
    rows = b"".join(b"\x00" + b"\x00\x00\x00\x00" * 800 for _ in range(500))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", 800, 500, 8, 6, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(rows, level=9)),
            _chunk(b"IEND", b""),
        )
    )


def _binding_value() -> dict[str, object]:
    body = {
        "schema_version": "local-image-provider-binding/1.0",
        "state": "ENABLED",
        "route_contract": "eom-local-generative-background/1.0",
        "model": {
            "model_id": "imgmodel_" + "1" * 32,
            "model_revision_id": "imgmodelrev_" + "2" * 32,
            "manifest_sha256": "sha256:" + "3" * 64,
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        },
        "sampler": {
            "contract": "euler-discrete/ssd-1b-v1",
            "inference_steps": 20,
            "guidance_scale": 7.5,
            "dtype": "float16",
        },
        "timeout_seconds": 900,
    }
    return {**body, "binding_sha256": content_sha256(body)}


def _drawing() -> GeneratedVectorDrawingV5:
    return GeneratedVectorDrawingV5.model_validate(
        {
            "kind": "natural_scene",
            "production_route": "LOCAL_GENERATIVE_BACKGROUND",
            "background_style": "PAPER",
            "block_id": "block_image",
            "alt_text": "방형구에서 식물 분포를 조사하는 장면",
            "scene_description": "방형구 안 식물과 조사자를 나타낸다.",
            "scientific_constraints": ["방형구는 정사각형이다."],
            "required_labels": ["방형구"],
            "generation_prompt": "muted natural grass background without text",
            "negative_prompt": "people, tools",
            "width_px": 800,
            "height_px": 500,
            "svg_overlay": (
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
                'viewBox="0 0 800 500"><rect fill="none" height="240" '
                'stroke="#000000" stroke-width="4" width="300" x="250" y="130"></rect>'
                '<text fill="#000000" font-family="Droid Sans Fallback" font-size="20" '
                'x="350" y="410">방형구</text></svg>'
            ),
        }
    )


def _hybrid_drawing() -> GeneratedVectorDrawingV6:
    value = _drawing().model_dump(mode="json")
    value.update(
        {
            "production_route": "HYBRID_LOCAL_GENERATIVE",
            "route_reason": "HUMAN_OR_ANIMAL_REQUIRED",
            "generation_prompt": "one student observing plants inside a quadrat",
            "negative_prompt": "extra people, decorative objects",
        }
    )
    return GeneratedVectorDrawingV6.model_validate(value)


def test_binding_loader_pins_root_controlled_bytes(tmp_path: Path) -> None:
    path = tmp_path / "binding.json"
    value = _binding_value()
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o644)

    binding = load_local_image_provider_binding(
        path,
        trusted_owner_uid=os.geteuid(),
        trusted_group_gid=os.getegid(),
    )

    assert binding.binding_sha256 == value["binding_sha256"]
    changed = dict(value)
    changed["timeout_seconds"] = 899
    path.write_text(json.dumps(changed), encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(LocalImageAdapterError, match="LOCAL_IMAGE_ROUTE_UNDEPLOYED"):
        load_local_image_provider_binding(
            path,
            trusted_owner_uid=os.geteuid(),
            trusted_group_gid=os.getegid(),
        )


@pytest.mark.parametrize("mode", (0o640, 0o664))
def test_binding_loader_rejects_noncanonical_mode(tmp_path: Path, mode: int) -> None:
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(_binding_value()), encoding="utf-8")
    path.chmod(mode)

    with pytest.raises(LocalImageAdapterError, match="LOCAL_IMAGE_ROUTE_UNDEPLOYED"):
        load_local_image_provider_binding(
            path,
            trusted_owner_uid=os.geteuid(),
            trusted_group_gid=os.getegid(),
        )


def test_binding_loader_rejects_wrong_group(tmp_path: Path) -> None:
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(_binding_value()), encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(LocalImageAdapterError, match="LOCAL_IMAGE_ROUTE_UNDEPLOYED"):
        load_local_image_provider_binding(
            path,
            trusted_owner_uid=os.geteuid(),
            trusted_group_gid=os.getegid() + 1,
        )


def test_composite_request_is_deterministic_and_input_pinned(tmp_path: Path) -> None:
    overlay = _overlay_png()
    path = tmp_path / "generated-overlay.png"
    path.write_bytes(overlay)
    path.chmod(0o640)
    binding = LocalImageProviderBinding.model_validate(_binding_value())
    drawing = _drawing()
    drawing_hash = content_sha256(drawing.model_dump(mode="json"))

    first = _build_request(
        workflow_id="workflow_" + "4" * 32,
        result_revision_id="rev_" + "5" * 32,
        drawing_hash=drawing_hash,
        drawing=drawing,
        binding=binding,
        overlay_path=path,
    )
    second = _build_request(
        workflow_id="workflow_" + "4" * 32,
        result_revision_id="rev_" + "5" * 32,
        drawing_hash=drawing_hash,
        drawing=drawing,
        binding=binding,
        overlay_path=path,
    )

    assert first == second
    assert first.overlay.sha256 == "sha256:" + hashlib.sha256(overlay).hexdigest()
    assert first.generation.model == binding.model
    assert first.generation.prompt.startswith("Non-authoritative background layer only.")
    assert "no text" in first.generation.prompt
    assert first.generation.request_id.startswith("imgreq_")

    changed = drawing.model_copy(update={"generation_prompt": "different natural background"})
    changed_request = _build_request(
        workflow_id="workflow_" + "4" * 32,
        result_revision_id="rev_" + "5" * 32,
        drawing_hash=content_sha256(changed.model_dump(mode="json")),
        drawing=changed,
        binding=binding,
        overlay_path=path,
    )
    assert changed_request.generation.request_id != first.generation.request_id


def test_binding_loader_rejects_symlink(tmp_path: Path) -> None:
    actual = tmp_path / "actual.json"
    actual.write_text(json.dumps(_binding_value()), encoding="utf-8")
    actual.chmod(0o644)
    link = tmp_path / "binding.json"
    link.symlink_to(actual)
    with pytest.raises(LocalImageAdapterError, match="LOCAL_IMAGE_ROUTE_UNDEPLOYED"):
        load_local_image_provider_binding(
            link,
            trusted_owner_uid=os.geteuid(),
            trusted_group_gid=os.getegid(),
        )


def test_v6_hybrid_request_describes_a_semantic_raster_not_a_background(tmp_path: Path) -> None:
    path = tmp_path / "generated-overlay.png"
    path.write_bytes(_overlay_png())
    path.chmod(0o640)
    drawing = _hybrid_drawing()

    request = _build_request(
        workflow_id="workflow_" + "6" * 32,
        result_revision_id="rev_" + "7" * 32,
        drawing_hash=content_sha256(drawing.model_dump(mode="json")),
        drawing=drawing,
        binding=LocalImageProviderBinding.model_validate(_binding_value()),
        overlay_path=path,
    )

    assert request.generation.prompt.startswith("Semantic raster layer")
    assert "one student" in request.generation.prompt
    assert "background layer only" not in request.generation.prompt
    assert "text" in request.generation.negative_prompt
