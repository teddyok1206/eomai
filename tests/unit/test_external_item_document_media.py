"""Pinned legacy source media preserves original links without path authority."""

from __future__ import annotations

from contextlib import nullcontext
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    ExternalItemDocumentMediaQuery,
    ExternalItemDocumentMediaResponse,
    validate_contract,
)
from eom_catalog_service.external_item_document_media import (
    ExternalItemDocumentMediaError,
    ExternalItemDocumentMediaService,
    _effective_filename,
)

SOURCE_ID = "extitem_" + "1" * 32
REVISION_ID = "extitemrev_" + "2" * 32
SOURCE_FILE_ID = "source_" + "3" * 32
CONTENT_SHA = "sha256:" + "4" * 64


def test_media_schema_and_filename_follow_detected_hwpx_bytes() -> None:
    query = ExternalItemDocumentMediaQuery(
        source_id=SOURCE_ID, source_revision_id=REVISION_ID, edition=3
    )
    validate_contract(
        "catalog-external-item-document-media-request", query.model_dump(mode="json")
    )
    assert _effective_filename("문항_12345.hwp", "application/vnd.hancom.hwpx") == (
        "문항_12345.hwpx"
    )
    response = ExternalItemDocumentMediaResponse(
        status="OK",
        media_type="application/vnd.hancom.hwpx",
        content_length=8,
        sha256=CONTENT_SHA,
        filename="문항_12345.hwpx",
    )
    validate_contract(
        "catalog-external-item-document-media-response",
        response.model_dump(mode="json", exclude_none=True),
    )
    with pytest.raises(ValueError):
        ExternalItemDocumentMediaResponse(
            status="OK",
            media_type="application/vnd.hancom.hwpx",
            content_length=8,
            sha256=CONTENT_SHA,
            filename="../bad.hwpx",
        )


def _service(row):
    session = SimpleNamespace(execute=Mock(return_value=SimpleNamespace(one_or_none=lambda: row)))
    service = object.__new__(ExternalItemDocumentMediaService)
    service.sessions = lambda: nullcontext(session)
    service.artifacts = SimpleNamespace(
        open_verified_member=Mock(
            return_value=SimpleNamespace(
                stream=BytesIO(b"test-hwp"), content_length=8, sha256=CONTENT_SHA
            )
        )
    )
    return service


def _row():
    return (
        SimpleNamespace(
            source_id=SOURCE_ID, source_namespace="notion-integrated-science",
            external_number="12345",
        ),
        SimpleNamespace(source_id=SOURCE_ID, external_number="12345"),
        SimpleNamespace(source_namespace="notion-integrated-science", state="COMPLETED"),
        SimpleNamespace(source_file_id=SOURCE_FILE_ID, document_sha256=CONTENT_SHA),
        SimpleNamespace(
            source_file_id=SOURCE_FILE_ID,
            sha256=CONTENT_SHA,
            declared_role="DATA",
            media_type="application/vnd.hancom.hwpx",
            size_bytes=8,
            original_filename="문항_12345.hwp",
            artifact_id="artifact_" + "5" * 32,
            artifact_revision_id="rev_" + "6" * 32,
            relative_path="source/문항_12345.hwpx",
        ),
        SimpleNamespace(state="ANALYSIS_PENDING"),
    )


def test_only_published_pinned_edition_can_open_its_artifact() -> None:
    service = _service(_row())
    value = service.open(
        ExternalItemDocumentMediaQuery(
            source_id=SOURCE_ID, source_revision_id=REVISION_ID, edition=3
        )
    )
    assert value.filename == "문항_12345.hwpx"
    assert value.media_type == "application/vnd.hancom.hwpx"
    service.artifacts.open_verified_member.assert_called_once()

    stale = _service(None)
    with pytest.raises(ExternalItemDocumentMediaError) as captured:
        stale.open(
            ExternalItemDocumentMediaQuery(
                source_id=SOURCE_ID, source_revision_id=REVISION_ID, edition=3
            )
        )
    assert captured.value.code == "EXTERNAL_ITEM_DOCUMENT_UNAVAILABLE"
    stale.artifacts.open_verified_member.assert_not_called()


def test_source_file_hash_mismatch_fails_before_artifact_open() -> None:
    row = list(_row())
    row[3] = SimpleNamespace(source_file_id=SOURCE_FILE_ID, document_sha256="sha256:" + "7" * 64)
    service = _service(tuple(row))
    with pytest.raises(ExternalItemDocumentMediaError) as captured:
        service.open(
            ExternalItemDocumentMediaQuery(
                source_id=SOURCE_ID, source_revision_id=REVISION_ID, edition=3
            )
        )
    assert captured.value.code == "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID"
    service.artifacts.open_verified_member.assert_not_called()


def test_nonadmitted_intake_state_fails_closed_before_artifact_open() -> None:
    row = list(_row())
    row[5] = SimpleNamespace(state="RECEIVED")
    service = _service(tuple(row))
    with pytest.raises(ExternalItemDocumentMediaError) as captured:
        service.open(
            ExternalItemDocumentMediaQuery(
                source_id=SOURCE_ID, source_revision_id=REVISION_ID, edition=3
            )
        )
    assert captured.value.code == "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID"
    service.artifacts.open_verified_member.assert_not_called()
