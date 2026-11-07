"""Current preview generations never fall back to a legacy renderer or rerun a replay."""

from io import BytesIO
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
    ExternalItemPreviewUnavailable,
    _idempotency_key,
)
from eom_catalog_service.office_conversion_profiles import (
    CHOICE_LAYOUT_OFFICE_PROFILE,
    EQUATION_OFFICE_PROFILE,
    LEGACY_OFFICE_PROFILE,
    OfficeConversionProfile,
    require_supported_office_profile,
)

QUERY = ExternalItemDocumentMediaQuery(
    source_id="extitem_" + "1" * 32,
    source_revision_id="extitemrev_" + "2" * 32,
    edition=3,
)


def test_exact_legacy_key_and_distinct_current_generation() -> None:
    legacy = "external-item-preview-v1:" + QUERY.source_revision_id + ":3"
    assert _idempotency_key(QUERY) == legacy
    assert _idempotency_key(QUERY, LEGACY_OFFICE_PROFILE) == legacy
    assert _idempotency_key(QUERY, EQUATION_OFFICE_PROFILE) == (
        legacy + ":equations-v2:" + EQUATION_OFFICE_PROFILE.h2orestart_sha256
    )
    assert LEGACY_OFFICE_PROFILE.h2orestart_bundle != EQUATION_OFFICE_PROFILE.h2orestart_bundle
    assert _idempotency_key(QUERY, CHOICE_LAYOUT_OFFICE_PROFILE) == (
        legacy + ":choice-layout-v3:" + CHOICE_LAYOUT_OFFICE_PROFILE.h2orestart_sha256
    )
    assert (
        len(
            {
                _idempotency_key(QUERY, profile)
                for profile in (
                    LEGACY_OFFICE_PROFILE,
                    EQUATION_OFFICE_PROFILE,
                    CHOICE_LAYOUT_OFFICE_PROFILE,
                )
            }
        )
        == 3
    )


def test_arbitrary_converter_profile_is_not_an_execution_grant() -> None:
    profile = OfficeConversionProfile(
        key="equations-v2",
        unit_template="other@{instance}.service",
        h2orestart_bundle=EQUATION_OFFICE_PROFILE.h2orestart_bundle,
        h2orestart_sha256=EQUATION_OFFICE_PROFILE.h2orestart_sha256,
    )
    with pytest.raises(ValueError, match="PROFILE_UNSUPPORTED"):
        require_supported_office_profile(profile)


def _owner() -> ExternalItemPreviewProjectionService:
    owner = object.__new__(ExternalItemPreviewProjectionService)
    owner.engine = SimpleNamespace(dialect=SimpleNamespace(name="fixture"))
    owner._render_lock = RLock()
    owner.profile = EQUATION_OFFICE_PROFILE
    return owner


def test_completed_prepare_replays_without_converter() -> None:
    owner = _owner()
    completed = SimpleNamespace(member=SimpleNamespace(stream=BytesIO(b"")))
    publication = object()
    owner.open = Mock(return_value=completed)
    owner._build_once = Mock()
    owner._read_existing_publication = Mock(return_value=publication)
    assert owner.build(QUERY) is publication
    owner._build_once.assert_not_called()
    owner._read_existing_publication.assert_called_once_with(completed)
    assert completed.member.stream.closed


def test_not_ready_builds_only_requested_generation_once() -> None:
    owner = _owner()
    owner.open = Mock(side_effect=ExternalItemPreviewUnavailable("EXTERNAL_ITEM_PREVIEW_NOT_READY"))
    artifact = object()
    owner._build_once = Mock(return_value=artifact)
    assert owner.build(QUERY) is artifact
    owner._build_once.assert_called_once_with(QUERY)
    owner.open.assert_called_once_with(QUERY)


@pytest.mark.parametrize(
    "code", ["EXTERNAL_ITEM_PREVIEW_POINTER_INVALID", "EXTERNAL_ITEM_PREVIEW_SOURCE_STALE"]
)
def test_invalid_current_pointer_does_not_rebuild_or_fall_back(code: str) -> None:
    owner = _owner()
    owner.open = Mock(side_effect=ExternalItemPreviewUnavailable(code))
    owner._build_once = Mock()
    with pytest.raises(ExternalItemPreviewUnavailable, match=code):
        owner.build(QUERY)
    owner._build_once.assert_not_called()
