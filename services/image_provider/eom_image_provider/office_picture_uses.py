"""Whole Office rasters and source-native use catalog, only in a local sandbox."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog, UnresolvedPictureReason

from eom_image_provider.office_embedded_images import (
    OfficeEmbeddedImageError,
    _extract_office_image_payload,
    read_verified_office_source,
)
from eom_image_provider.office_picture_records import read_hwp_picture_uses
from eom_image_provider.office_picture_views import render_office_picture_views
from eom_image_provider.office_picture_xml import read_hwpx_picture_uses


def extract_office_picture_uses(
    source: Path, *, expected_sha256: str, workspace: Path
) -> OfficePictureUseCatalog:
    """Materialize once, parse in isolation, retain whole members plus exact uses.

    The caller, not this adapter, owns source authorization and NAS publication.
    Missing/native/grouped content remains explicit and does not become a crop.
    """
    if not source.is_absolute() or not workspace.is_absolute() or os.path.lexists(workspace):
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_WORKSPACE_INVALID")
    payload = read_verified_office_source(source, expected_sha256=expected_sha256)
    embedded = _extract_office_image_payload(
        payload, expected_sha256=expected_sha256, workspace=workspace
    )
    grayscale_uses: set[str] = set()
    if embedded.source_format == "HWP5":
        uses, objects = read_hwp_picture_uses(
            payload, source_sha256=expected_sha256, grayscale_uses=grayscale_uses
        )
    else:
        uses, objects = read_hwpx_picture_uses(
            payload, source_sha256=expected_sha256, grayscale_uses=grayscale_uses
        )
    images = {image.source_member for image in embedded.images}
    unsupported = set(embedded.unsupported_members)
    checked = []
    for use in uses:
        reasons: set[UnresolvedPictureReason] = set(use.unresolved_reasons)
        if use.source_member is not None and use.source_member not in images:
            reasons.add(
                "UNSUPPORTED_IMAGE" if use.source_member in unsupported else "MISSING_IMAGE"
            )
        checked.append(use.model_copy(update={"unresolved_reasons": tuple(sorted(reasons))}))
    value = {
        "schema_version": "office-picture-use-catalog/1.0",
        "extractor_profile": "HANCOM_NATIVE_PICTURE_USES_V1",
        "embedded_images": embedded.model_dump(mode="json"),
        "picture_uses": [use.model_dump(mode="json") for use in checked],
        "rendered_uses": [
            view.model_dump(mode="json")
            for view in render_office_picture_views(
                embedded, checked, workspace=workspace, grayscale_uses=frozenset(grayscale_uses)
            )
        ],
        "native_objects": [obj.model_dump(mode="json") for obj in objects],
    }
    result = OfficePictureUseCatalog.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    with (workspace / "picture-use-catalog.json").open("xb") as stream:
        stream.write(content_json_bytes(result.model_dump(mode="json")))
    return result


def main() -> int:
    """Binary pipe boundary for the existing eom-image document sandbox."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha256", required=True)
    arguments = parser.parse_args()
    payload = sys.stdin.buffer.read(256 * 1024 * 1024 + 1)
    if not 0 < len(payload) <= 256 * 1024 * 1024:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_SOURCE_INVALID")
    with tempfile.TemporaryDirectory(prefix="office-uses-") as temporary:
        root = Path(temporary)
        source = root / "source.office"
        with source.open("xb") as stream:
            stream.write(payload)
        result = extract_office_picture_uses(
            source, expected_sha256=arguments.source_sha256, workspace=root / "output"
        )
        members = {"picture-use-catalog.json"}
        members.update(image.member_path for image in result.embedded_images.images)
        members.update(view.member_path for view in result.rendered_uses)
        # Bound combined stdout before opening the pipe. Whole members and
        # distinct transformed views each have separate decoded-size budgets.
        if sum((root / "output" / member).stat().st_size for member in members) > 500 * 1024 * 1024:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_VIEW_OUTPUT_LIMIT")
        # Fixed names and ordering, no filenames or paths supplied by a model.
        with zipfile.ZipFile(sys.stdout.buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            for member in sorted(members):
                info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o100600 << 16
                archive.writestr(info, (root / "output" / member).read_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
