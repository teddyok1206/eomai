"""Source bitmap selection is explicit and does not reinterpret whole-image history."""

import hashlib
import json
from pathlib import Path

import pytest
from eom_catalog_contracts.creative_bitmap_presentation import (
    BITMAP_PRESENTATION_SCHEMA_REF,
    CreativeBitmapPresentationManifest,
    RecoveredBitmapVisual,
    SelectedSourceBitmap,
    read_visual_presentation_manifest,
)
from eom_catalog_contracts.creative_visual_derivation import derive_creative_visual_content
from eom_catalog_contracts.creative_visual_presentation import CreativeVisualPresentationManifest
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.creative_visual_presentation_publication import (
    publish_creative_visual_presentation,
)

from tests.unit.test_creative_visual_presentation import fixture, read_fixture
from tests.unit.test_creative_visual_presentation_publication import publication_fixture


def as_bitmap_manifest(manifest):
    value = manifest.model_dump(mode="json")
    value.pop("manifest_sha256")
    value.update(
        schema_version="creative-visual-presentation/1.1", profile="HANCOM_SOURCE_BITMAP_REGIONS_V1"
    )
    for visual in value["visuals"]:
        visual["source_image_crops"] = 1
        for source in visual["source_images"]:
            source.update(pixel_box=[20, 10, 1900, 950], selection="MAIN_BODY_VIEWPORT")
    return CreativeBitmapPresentationManifest.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )


def test_source_bitmap_schema_and_nonvisual_content_are_exact():
    canonical, old, displayed = fixture()
    manifest = as_bitmap_manifest(old)
    assert (
        read_visual_presentation_manifest(
            manifest.model_dump(mode="json"), BITMAP_PRESENTATION_SCHEMA_REF
        )
        == manifest
    )
    result = derive_creative_visual_content(
        canonical,
        manifest,
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
    )
    assert result == displayed
    with pytest.raises(ValueError):
        CreativeVisualPresentationManifest.model_validate(manifest.model_dump(mode="json"))


@pytest.mark.parametrize(
    "box",
    [
        (-1, 0, 5, 5),
        (0, 0, 2001, 10),
        (0, 9, 2, 9),
        (0, 0, 2, 1001),
        (True, 0, 9, 9),
        (0.5, 0, 9, 9),
    ],
)
def test_invalid_pixel_regions_never_coerce_or_clip(box):
    _, manifest, _ = fixture()
    value = manifest.visuals[0].source_images[0].model_dump(mode="json")
    with pytest.raises(ValueError):
        SelectedSourceBitmap.model_validate(
            {**value, "pixel_box": box, "selection": "MAIN_BODY_VIEWPORT"}
        )


@pytest.mark.parametrize(
    "defect", ["crop_count", "whole_claim", "reference", "capture", "duplicate"]
)
def test_false_selection_receipts_are_rejected(defect):
    _, old, _ = fixture()
    visual = as_bitmap_manifest(old).visuals[0].model_dump(mode="json")
    if defect == "crop_count":
        visual["source_image_crops"] = 0
    elif defect == "whole_claim":
        visual["source_images"][0]["selection"] = "WHOLE_IMAGE"
    elif defect == "reference":
        visual["reference_original_used"] = True
    elif defect == "capture":
        visual["page_captures"] = 1
    else:
        visual["source_images"].append(visual["source_images"][0])
    with pytest.raises(ValueError):
        RecoveredBitmapVisual.model_validate(visual)


def test_source_regions_use_the_same_nas_publication_owner(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    arguments = publication_fixture(tmp_path)
    arguments["manifest"] = as_bitmap_manifest(arguments["manifest"])

    def commit(**request):
        manifest = next(v for v in request["members"] if v.file_name == "visual-presentation.json")
        assert manifest.schema_ref == BITMAP_PRESENTATION_SCHEMA_REF
        parsed = read_visual_presentation_manifest(
            json.loads(manifest.source.read_bytes()), manifest.schema_ref
        )
        assert parsed == arguments["manifest"]
        assert request["manifest_version"] == "creative-visual-presentation/1.1"
        return "committed"

    publisher = SimpleNamespace(
        settings=SimpleNamespace(staging_root=tmp_path), publish_identified=Mock(side_effect=commit)
    )
    assert publish_creative_visual_presentation(publisher, **arguments) == "committed"
    assert arguments["authorize"].call_count == 3


def test_catalog_reads_exact_new_manifest_without_replacing_item_history(monkeypatch, tmp_path):
    from eom_orchestrator.models import ArtifactRevisionRecord

    service, session, view, bodies = read_fixture(monkeypatch, tmp_path)
    manifest = as_bitmap_manifest(
        CreativeVisualPresentationManifest.model_validate_json(bodies["visual-presentation.json"])
    )
    bodies["visual-presentation.json"] = canonical_json_bytes(manifest.model_dump(mode="json"))
    entry = session.records[ArtifactRevisionRecord].manifest["files"][0]
    entry.update(
        schema_ref=BITMAP_PRESENTATION_SCHEMA_REF,
        sha256=content_sha256(manifest.model_dump(mode="json")),
    )
    actual = service.read(view.item_revision_id)
    assert actual.source_content == view.source_content
    assert actual.display_content == view.display_content
    assert actual.recovery_manifest.schema_ref == BITMAP_PRESENTATION_SCHEMA_REF
    assert actual.content == view.content


def test_released_v1_schema_bytes_are_preserved():
    root = Path(__file__).resolve().parents[2]
    path = root / "schemas/external-item/creative-visual-presentation-v1.schema.json"
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest()
        == "732b287e9d212bc1da1301f990d9d5f7fb8089fce4fad10290030517b4a6afc0"
    )
