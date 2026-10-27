"""Creative learning source resolution compares the exact archive and PDF pointers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
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
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey

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


def _authorized_session(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ActorContext, Mock, SimpleNamespace, SimpleNamespace, Mock]:
    now = datetime.now(UTC)
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id="operator_" + "a" * 32,
        session_id="apisession_" + "b" * 32,
        request_id="extlearn-test-request",
        authentication_time=now - timedelta(minutes=2),
        permissions=frozenset(),  # copied API permissions are deliberately untrusted
        source=ActorSource.APPLICATION_API,
    )
    operator = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    api_session = SimpleNamespace(
        operator_id=actor.operator_id,
        revoked_at=None,
        authenticated_at=actor.authentication_time,
        absolute_expires_at=now + timedelta(hours=1),
        idle_expires_at=now + timedelta(minutes=15),
    )
    session = Mock()
    session.get.side_effect = lambda model, _identity: (
        operator if model is OperatorRecord else api_session if model is ApiSessionRecord else None
    )
    permissions = Mock(
        return_value=frozenset(
            {
                PermissionKey.CONTENT_INTAKE_READ,
                PermissionKey.WORKFLOW_START,
                PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
            }
        )
    )
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source.effective_permissions",
        permissions,
    )
    return actor, session, operator, api_session, permissions


def test_source_resolution_keeps_exact_original_and_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, resolved = _fixtures()
    actor, session, _, _, permissions = _authorized_session(monkeypatch)
    lookup = Mock(return_value=target)
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source.get_external_creative_learning_target",
        lookup,
    )
    preview = Mock()
    preview.open.return_value = resolved
    source = resolve_external_creative_learning_source(
        session,
        preview,
        actor=actor,
        import_id=target.import_id,
        external_number=target.external_number,
        expected_source_revision_id=target.source_revision_id,
        expected_observation_sha256=target.observation_sha256,
        expected_edition=target.selected_edition,
    )
    assert source.input_sha256.startswith("sha256:")
    assert source.preview_artifact_id == resolved.artifact_id
    assert source.preview_manifest.source_sha256 == target.document_sha256
    lookup.assert_called_once()
    assert resolved.member.stream.closed
    permissions.assert_called_once_with(session, actor.operator_id)


def test_source_resolution_rejects_cross_revision_pointer_and_closes_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, resolved = _fixtures()
    actor, session, _, _, _ = _authorized_session(monkeypatch)
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
            session,
            preview,
            actor=actor,
            import_id=target.import_id,
            external_number=target.external_number,
            expected_source_revision_id=target.source_revision_id,
            expected_observation_sha256=target.observation_sha256,
            expected_edition=target.selected_edition,
        )
    assert captured.value.code == "EXTERNAL_CREATIVE_SOURCE_POINTER_MISMATCH"
    assert resolved.member.stream.closed


@pytest.mark.parametrize("change", ["none", "truncated", "different_hash"])
def test_source_pdf_materialization_is_exact_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    target, _ = _fixtures()
    actor, session, _, _, _ = _authorized_session(monkeypatch)
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
            session,
            preview,
            actor=actor,
            import_id=target.import_id,
            external_number=target.external_number,
            expected_source_revision_id=target.source_revision_id,
            expected_observation_sha256=target.observation_sha256,
            expected_edition=target.selected_edition,
        )
        assert result.pdf_bytes == original
        assert result.source.preview_manifest.pdf_sha256 == source.preview_manifest.pdf_sha256
    else:
        with pytest.raises(ExternalCreativeLearningSourceError) as captured:
            read_external_creative_learning_input(
                session,
                preview,
                actor=actor,
                import_id=target.import_id,
                external_number=target.external_number,
                expected_source_revision_id=target.source_revision_id,
                expected_observation_sha256=target.observation_sha256,
                expected_edition=target.selected_edition,
            )
        assert captured.value.code == "EXTERNAL_CREATIVE_SOURCE_PDF_INVALID"
    assert stream.closed


@pytest.mark.parametrize(
    "invalid_state",
    ["revoked", "expired", "disabled", "password_change", "missing_permission", "wrong_session"],
)
def test_source_cannot_open_before_current_operator_admission(
    monkeypatch: pytest.MonkeyPatch, invalid_state: str
) -> None:
    target, _ = _fixtures()
    actor, session, operator, api_session, permissions = _authorized_session(monkeypatch)
    if invalid_state == "revoked":
        api_session.revoked_at = datetime.now(UTC)
    elif invalid_state == "expired":
        api_session.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif invalid_state == "disabled":
        operator.status = "DISABLED"
    elif invalid_state == "password_change":
        operator.must_change_password = True
    elif invalid_state == "missing_permission":
        permissions.return_value = frozenset({PermissionKey.CONTENT_INTAKE_READ})
    else:
        api_session.operator_id = "operator_" + "f" * 32
    preview = Mock()
    with pytest.raises(ExternalCreativeLearningSourceError) as captured:
        read_external_creative_learning_input(
            session,
            preview,
            actor=actor,
            import_id=target.import_id,
            external_number=target.external_number,
            expected_source_revision_id=target.source_revision_id,
            expected_observation_sha256=target.observation_sha256,
            expected_edition=target.selected_edition,
        )
    assert captured.value.code == "EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED"
    preview.open.assert_not_called()


@pytest.mark.parametrize("changed_pin", ["revision", "observation", "edition"])
def test_source_rejects_stale_selection_before_opening_pdf(
    monkeypatch: pytest.MonkeyPatch, changed_pin: str
) -> None:
    target, _ = _fixtures()
    actor, session, _, _, _ = _authorized_session(monkeypatch)
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source.get_external_creative_learning_target",
        Mock(return_value=target),
    )
    preview = Mock()
    revision = "extitemrev_" + "f" * 32 if changed_pin == "revision" else target.source_revision_id
    observation = (
        "sha256:" + "f" * 64 if changed_pin == "observation" else target.observation_sha256
    )
    edition = 2 if changed_pin == "edition" and target.selected_edition == 3 else 3
    if changed_pin != "edition":
        edition = target.selected_edition
    with pytest.raises(ExternalCreativeLearningSourceError) as captured:
        read_external_creative_learning_input(
            session,
            preview,
            actor=actor,
            import_id=target.import_id,
            external_number=target.external_number,
            expected_source_revision_id=revision,
            expected_observation_sha256=observation,
            expected_edition=edition,
        )
    assert captured.value.code == "EXTERNAL_CREATIVE_SOURCE_STALE"
    preview.open.assert_not_called()
