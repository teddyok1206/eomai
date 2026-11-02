"""Original-source rendition publication uses the existing file-set owner only."""

import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_visual_derivation import derive_creative_visual_content
from eom_catalog_contracts.creative_visual_presentation import (
    CreativeVisualPresentationManifest,
    visual_presentation_key,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.creative_visual_presentation_publication import (
    publish_creative_visual_presentation,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity

from tests.unit.test_creative_visual_presentation import fixture


def publication_fixture(tmp_path: Path, *, variant: str = "5"):
    canonical, manifest, _ = fixture()

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n" + b"".join(
        (
            chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 16, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00\x00\x00" * 32) * 16)),
            chunk(b"IEND", b""),
        )
    )
    target = tmp_path / "restored.png"
    target.write_bytes(png)
    value = manifest.model_dump(mode="json")
    value.pop("manifest_sha256")
    value["item_revision_id"] = "itemrev_" + variant * 32
    value["visuals"][0].update(
        sha256=sha256_bytes(png),
        member_path="images/" + sha256_bytes(png)[7:] + ".png",
        width_px=32,
        height_px=16,
        content_length=len(png),
    )
    manifest = CreativeVisualPresentationManifest.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    identity = ControlFileSetIdentity(
        job_id="job_" + variant * 32,
        artifact_id="artifact_" + variant * 32,
        artifact_revision_id="rev_" + variant * 32,
    )
    displayed = derive_creative_visual_content(
        canonical,
        manifest,
        artifact_id=identity.artifact_id,
        artifact_revision_id=identity.artifact_revision_id,
    )
    value["content_sha256"] = content_sha256(displayed.model_dump(mode="json"))
    manifest = CreativeVisualPresentationManifest.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    return dict(
        identity=identity,
        manifest=manifest,
        canonical=canonical,
        image_files={"block_image": target},
        source_commit="a" * 40,
        authorize=Mock(),
    )


def test_publication_contains_only_content_proof_and_the_selected_whole_images(tmp_path):
    arguments = publication_fixture(tmp_path)

    def publish(**request):
        assert request["primary_file"] == "assessment-item-content.json"
        assert request["idempotency_key"] == visual_presentation_key(
            arguments["manifest"].item_revision_id
        )
        members = {member.file_name: member for member in request["members"]}
        assert set(members) == {
            "assessment-item-content.json",
            "visual-presentation.json",
            arguments["manifest"].visuals[0].member_path,
        }
        for member in members.values():
            assert member.source.is_file()
            assert sha256_bytes(member.source.read_bytes()) == member.sha256
        return "published"

    publisher = SimpleNamespace(
        settings=SimpleNamespace(staging_root=tmp_path),
        publish_identified=Mock(side_effect=publish),
    )
    assert publish_creative_visual_presentation(publisher, **arguments) == "published"
    assert arguments["authorize"].call_count == 3
    assert not tuple(tmp_path.glob("creative-visual-presentation-*"))


@pytest.mark.parametrize("defect", ["hash", "dimensions", "symlink", "extra_image", "permission"])
def test_bad_or_unapproved_input_never_reaches_the_nas_publisher(tmp_path, defect):
    arguments = publication_fixture(tmp_path)
    source = arguments["image_files"]["block_image"]
    if defect == "hash":
        source.write_bytes(source.read_bytes()[:-1] + b"x")
    elif defect == "dimensions":
        value = arguments["manifest"].model_dump(mode="json")
        value.pop("manifest_sha256")
        value["visuals"][0]["width_px"] = 31
        arguments["manifest"] = CreativeVisualPresentationManifest.model_validate(
            {**value, "manifest_sha256": content_sha256(value)}
        )
    elif defect == "symlink":
        link = tmp_path / "link.png"
        link.symlink_to(source)
        arguments["image_files"] = {"block_image": link}
    elif defect == "extra_image":
        arguments["image_files"] = {"block_image": source, "reference_original": source}
    else:
        arguments["authorize"].side_effect = PermissionError("revoked")
    publisher = SimpleNamespace(
        settings=SimpleNamespace(staging_root=tmp_path), publish_identified=Mock()
    )
    with pytest.raises((ValueError, OSError, PermissionError)):
        publish_creative_visual_presentation(publisher, **arguments)
    publisher.publish_identified.assert_not_called()
