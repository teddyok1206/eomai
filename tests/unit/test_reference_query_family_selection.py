"""Exact cohost routing and optional protected selection, not installed activation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV2,
    ReferenceQueryPrepareRequestV2,
    parse_supported_reference_query_prepare_reply,
    parse_supported_reference_query_prepare_request,
)
from eom_identifiers import content_sha256
from eom_workflow_runner import reference_query_owner_entry as entry
from eom_workflow_runner.reference_query_family_selection import ReferenceQueryFamilyPreparation

from tests.unit.test_reference_query_prepare_contracts import reply_body, request_body


def _request(version: str):
    body = request_body(
        consumer_purpose="ITEM_REVIEW" if version == "1.1" else "PAST_EXAM_VARIATION"
    )
    if version == "2.0":
        body |= {
            "schema_version": "system-rag-reference-query-prepare-request/2.0",
            "consumer_purpose": "PAST_EXAM_VARIATION",
        }
        body["request_sha256"] = content_sha256(
            {key: value for key, value in body.items() if key != "request_sha256"}
        )
    return parse_supported_reference_query_prepare_request(body)


def _reply(request):
    body = reply_body(request)
    if isinstance(request, ReferenceQueryPrepareRequestV2):
        body["schema_version"] = "system-rag-reference-query-prepare-reply/2.0"
    return parse_supported_reference_query_prepare_reply(body)


@pytest.mark.parametrize("version", ["1.0", "1.1", "2.0"])
def test_only_exact_family_factory_is_constructed(version: str) -> None:
    request = _request(version)
    reply = _reply(request)
    primary = Mock(return_value=SimpleNamespace(prepare=Mock(return_value=reply)))
    mixed = Mock(return_value=SimpleNamespace(prepare=Mock(return_value=reply)))
    service = ReferenceQueryFamilyPreparation(primary, mixed)
    assert service.prepare(request) == reply
    chosen, unchosen = (mixed, primary) if version == "2.0" else (primary, mixed)
    chosen.assert_called_once_with()
    unchosen.assert_not_called()
    chosen.return_value.prepare.assert_called_once_with(request)


def test_optional_mixed_absence_never_falls_back_to_primary() -> None:
    primary = Mock()
    with pytest.raises(ValueError, match="REFERENCE_QUERY_PREPARE_UNAVAILABLE"):
        ReferenceQueryFamilyPreparation(primary, None).prepare(_request("2.0"))
    primary.assert_not_called()


def test_wrong_family_reply_has_no_fallback_or_replacement_request() -> None:
    request = _request("2.0")
    wrong = parse_supported_reference_query_prepare_reply(reply_body(request))
    primary, mixed = Mock(), Mock(return_value=SimpleNamespace(prepare=Mock(return_value=wrong)))
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        ReferenceQueryFamilyPreparation(primary, mixed).prepare(request)
    primary.assert_not_called()
    mixed.assert_called_once()
    mixed.return_value.prepare.assert_called_once_with(request)


def test_replay_reenters_selected_owner_instead_of_caching_authority() -> None:
    request = _request("2.0")
    reply = _reply(request)
    assert isinstance(reply, ReferenceQueryPrepareReplyV2)
    mixed = Mock(return_value=SimpleNamespace(prepare=Mock(return_value=reply)))
    service = ReferenceQueryFamilyPreparation(Mock(), mixed)
    assert service.prepare(request) == service.prepare(request) == reply
    assert mixed.call_count == mixed.return_value.prepare.call_count == 2


def test_copied_request_extras_fail_before_either_owner() -> None:
    primary, mixed = Mock(), Mock()
    with pytest.raises(ValueError):
        ReferenceQueryFamilyPreparation(primary, mixed).prepare(
            _request("2.0").model_copy(update={"unexpected": True})
        )
    primary.assert_not_called()
    mixed.assert_not_called()


def test_optional_configuration_absence_does_not_touch_any_file(monkeypatch) -> None:
    monkeypatch.delenv("EOM_MIXED_REFERENCE_QUERY_CONFIGURATION_SHA256", raising=False)
    assert entry._mixed_configuration_bytes() is None


@pytest.mark.parametrize("value", ["", "latest", "a" * 64, "sha256:" + "A" * 64])
def test_selected_invalid_optional_configuration_is_not_silently_disabled(
    monkeypatch, value
) -> None:
    monkeypatch.setenv("EOM_MIXED_REFERENCE_QUERY_CONFIGURATION_SHA256", value)
    with pytest.raises(ValueError, match="REFERENCE_QUERY_MIXED_CONFIGURATION_UNAVAILABLE"):
        entry._mixed_configuration_bytes()


def test_optional_configuration_uses_its_own_fixed_protected_file(monkeypatch) -> None:
    from eom_catalog_service import embedding_runtime_files

    sha = "sha256:" + "a" * 64
    monkeypatch.setenv("EOM_MIXED_REFERENCE_QUERY_CONFIGURATION_SHA256", sha)
    snapshot = Mock()
    snapshot.read.return_value = b"synthetic"
    factory = Mock(return_value=snapshot)
    monkeypatch.setattr(embedding_runtime_files, "NumericalRuntimeFileSnapshots", factory)
    assert entry._mixed_configuration_bytes() == b"synthetic"
    factory.assert_called_once_with()
    snapshot.read.assert_called_once_with(entry._MIXED_CONFIGURATION, sha256=sha, maximum=64 * 1024)
    assert entry._MIXED_CONFIGURATION != entry._CONFIGURATION != entry._PRIVATE_CONFIGURATION
