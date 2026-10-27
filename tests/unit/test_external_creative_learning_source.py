"""Creative learning source resolution compares the exact archive and PDF pointers."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.external_item_preview import ExternalItemPreviewManifest
from eom_catalog_service.artifacts import VerifiedArtifactMemberStream
from eom_catalog_service.external_creative_learning_source import (
    ExternalCreativeLearningSourceError,
    read_external_creative_learning_input,
    resolve_external_creative_learning_source,
)
from eom_catalog_service.external_creative_learning_targets import ExternalCreativeLearningTarget
from eom_catalog_service.external_item_preview_projection import ResolvedExternalItemPreview

from tests.unit.test_external_item_learning_page_render import _pdf, _source_for_pdf
from tests.unit.test_external_item_learning_source_contract import _source


def _fixtures() -> tuple[ExternalCreativeLearningTarget, ResolvedExternalItemPreview]:
    value = _source()
    manifest = ExternalItemPreviewManifest.model_validate(value["preview_manifest"])
    target = ExternalCreativeLearningTarget(
        import_id=str(value["import_id"]),
        source_namespace=str(value["source_namespace"]),
        source_id=manifest.source_id,
        source_revision_id=manifest.source_revision_id,
        external_number=str(value["external_number"]),
        origin_kind="PAST_EXAM_VARIATION",
        observation_sha256=str(value["observation_sha256"]),
        selected_edition=manifest.edition,
        source_file_id=manifest.source_file_id,
        artifact_id=manifest.source_artifact_id,
        artifact_revision_id=manifest.source_artifact_revision_id,
        document_sha256=manifest.source_sha256,
        document_media_type=manifest.source_media_type,
        document_size_bytes=manifest.source_bytes,
    )
    resolved = ResolvedExternalItemPreview(
        member=VerifiedArtifactMemberStream(
            stream=BytesIO(), content_length=manifest.pdf_bytes, sha256=manifest.pdf_sha256
        ),
        manifest=manifest,
        artifact_id=str(value["preview_artifact_id"]),
        artifact_revision_id=str(value["preview_artifact_revision_id"]),
    )
    return target, resolved


def test_source_resolution_keeps_exact_original_and_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, resolved = _fixtures()
    lookup = Mock(return_value=target)
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source.get_external_creative_learning_target",
        lookup,
    )
    preview = Mock()
    preview.open.return_value = resolved
    source = resolve_external_creative_learning_source(
        Mock(), preview, import_id=target.import_id, external_number=target.external_number
    )
    assert source.input_sha256.startswith("sha256:")
    assert source.preview_artifact_id == resolved.artifact_id
    assert source.preview_manifest.source_sha256 == target.document_sha256
    lookup.assert_called_once()
    assert resolved.member.stream.closed


def test_source_resolution_rejects_cross_revision_pointer_and_closes_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, resolved = _fixtures()
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source.get_external_creative_learning_target",
        Mock(return_value=target),
    )
    preview = Mock()
    preview.open.return_value = ResolvedExternalItemPreview(
        member=resolved.member,
        manifest=resolved.manifest.model_copy(
            update={"source_artifact_revision_id": "rev_" + "e" * 32}
        ),
        artifact_id=resolved.artifact_id,
        artifact_revision_id=resolved.artifact_revision_id,
    )
    with pytest.raises(ExternalCreativeLearningSourceError) as captured:
        resolve_external_creative_learning_source(
            Mock(), preview, import_id=target.import_id, external_number=target.external_number
        )
    assert captured.value.code == "EXTERNAL_CREATIVE_SOURCE_POINTER_MISMATCH"
    assert resolved.member.stream.closed


@pytest.mark.parametrize("change", ["none", "truncated", "different_hash"])
def test_source_pdf_materialization_is_exact_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    target, _ = _fixtures()
    original = _pdf()
    source = _source_for_pdf(original)
    payload = (
        original[:-1]
        if change == "truncated"
        else original[:-1] + b"!"
        if change == "different_hash"
        else original
    )
    stream = BytesIO(payload)
    preview = Mock()
    preview.open.return_value = ResolvedExternalItemPreview(
        member=VerifiedArtifactMemberStream(
            stream=stream,
            content_length=source.preview_manifest.pdf_bytes,
            sha256=source.preview_manifest.pdf_sha256,
        ),
        manifest=source.preview_manifest,
        artifact_id=source.preview_artifact_id,
        artifact_revision_id=source.preview_artifact_revision_id,
    )
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source.get_external_creative_learning_target",
        Mock(return_value=target),
    )
    if change == "none":
        result = read_external_creative_learning_input(
            Mock(), preview, import_id=target.import_id, external_number=target.external_number
        )
        assert result.pdf_bytes == original
        assert result.source.preview_manifest.pdf_sha256 == source.preview_manifest.pdf_sha256
    else:
        with pytest.raises(ExternalCreativeLearningSourceError) as captured:
            read_external_creative_learning_input(
                Mock(), preview, import_id=target.import_id, external_number=target.external_number
            )
        assert captured.value.code == "EXTERNAL_CREATIVE_SOURCE_PDF_INVALID"
    assert stream.closed
