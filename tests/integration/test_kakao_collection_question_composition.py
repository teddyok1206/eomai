"""Production composition reuses accepted capture authority over disposable PostgreSQL."""

from uuid import uuid4

import pytest
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_collection_source_composition import (
    build_configured_kakao_collection_attempts,
)
from eom_catalog_service.kakao_question_composition import build_kakao_question_application

from tests.integration.test_kakao_collection_source_access import (
    accepted_access,
    counts,
    expire_session,
    publish_source,
)
from tests.integration.test_kakao_collection_source_access import attempt as attempt
from tests.integration.test_kakao_collection_source_access import browser as browser
from tests.integration.test_kakao_collection_source_access import cap as cap
from tests.integration.test_kakao_collection_source_access import collection as collection
from tests.integration.test_kakao_collection_source_access import h as h
from tests.integration.test_kakao_collection_source_access import intake as intake

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def configured(attempt, monkeypatch, **change):
    from eom_catalog_service import artifacts

    monkeypatch.setattr(artifacts, "CatalogArtifactService", lambda _engine: attempt.artifacts)
    return build_configured_kakao_collection_attempts(
        attempt.engine,
        {
            "EOM_KAKAO_PROFILE_ID": attempt.service.profile_id,
            "EOM_KAKAO_COLLECTION_ADAPTER_SHA256": attempt.service.adapter_sha256,
        }
        | change,
    )


def test_actual_configured_owner_survives_restart_logout_and_keeps_order_uncertain(
    attempt, monkeypatch
):
    data, _access = accepted_access(attempt)
    app = build_kakao_question_application(
        attempt.engine, collection_attempts=configured(attempt, monkeypatch)
    )
    assert app.collection_attempts is not None
    assert app.collection_attempts.artifacts is attempt.artifacts
    expire_session(attempt, "logout")
    before = counts(attempt)
    access = app.collection_attempts.accepted_source_access(data.reserved.attempt_id)
    key = "configured-admission-" + uuid4().hex
    saved = publish_source(attempt, data, access, key=key, service=app.collection_attempts)
    assert counts(attempt)[0] == before[0]  # No new/extended HTTP session.
    with pytest.raises(KakaoArchiveError, match="SOURCE_ORDER_UNVERIFIED"):
        app.questions.create_source_candidates(
            access,
            data.reserved.source_binding_id,
            data.reserved.room_id,
            source_revision_id=saved.resolution.source_revision_id,
        )
    restarted = build_kakao_question_application(
        attempt.engine, collection_attempts=configured(attempt, monkeypatch)
    )
    assert restarted.collection_attempts is not None
    reread = restarted.collection_attempts.accepted_source_access(data.reserved.attempt_id)
    before = counts(attempt)
    replay = publish_source(
        attempt,
        data,
        reread,
        key=key,
        service=restarted.collection_attempts,
        read=lambda _member: pytest.fail("completed source replay must not reread local files"),
    )
    assert replay.replayed and replay.resolution == saved.resolution
    assert counts(attempt) == before
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        restarted.collection_attempts.sources.get_source(
            attempt.actor,
            data.reserved.source_binding_id,
            data.reserved.room_id,
            source_revision_id=saved.resolution.source_revision_id,
        )


def test_different_configured_profile_cannot_acquire_the_accepted_run(attempt, monkeypatch):
    data, _access = accepted_access(attempt)
    owner = configured(attempt, monkeypatch, EOM_KAKAO_PROFILE_ID="kakaoprofile_" + uuid4().hex)
    assert owner is not None
    before = counts(attempt)
    with pytest.raises(KakaoArchiveError, match="ADMISSION_AUTHORITY_REQUIRED"):
        owner.accepted_source_access(data.reserved.attempt_id)
    assert counts(attempt) == before


def test_changed_configured_adapter_cannot_publish_from_the_original_run(attempt, monkeypatch):
    data, _access = accepted_access(attempt)
    owner = configured(
        attempt,
        monkeypatch,
        EOM_KAKAO_COLLECTION_ADAPTER_SHA256="sha256:" + "b" * 64,
    )
    assert owner is not None
    access = owner.accepted_source_access(data.reserved.attempt_id)
    before = counts(attempt)
    with pytest.raises(KakaoArchiveError, match="COLLECTION_ADAPTER_CHANGED"):
        publish_source(
            attempt,
            data,
            access,
            key="wrong-adapter-" + uuid4().hex,
            service=owner,
            read=lambda _member: pytest.fail("wrong release must fail before reading payload"),
        )
    assert counts(attempt) == before
