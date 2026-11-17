"""Explicit admission composition without process, API session or worker activation."""

import subprocess
import sys
from unittest.mock import Mock

import pytest
from eom_catalog_service import kakao_collection_source_composition as composition


def environment():
    return {
        "EOM_KAKAO_PROFILE_ID": "kakaoprofile_" + "1" * 32,
        "EOM_KAKAO_COLLECTION_ADAPTER_SHA256": "sha256:" + "2" * 64,
    }


def test_default_does_not_import_optional_worker_or_construct_an_owner():
    script = """
import importlib.abc, sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('eom_kakao_archive_contracts', 'eom_kakao_archive_collector',
                                'eom_catalog_service.kakao_collection_attempt_service',
                                'eom_orchestrator.kakao_capture_inputs')):
            raise ModuleNotFoundError('optional runtime deliberately absent')
sys.meta_path.insert(0, BlockOptional())
from eom_catalog_service.kakao_collection_source_composition import (
    build_configured_kakao_collection_attempts,
)
assert build_configured_kakao_collection_attempts(object(), {}) is None
assert build_configured_kakao_collection_attempts(object(), {
    'EOM_KAKAO_PROFILE_ID': 'not-a-pin',
    'EOM_KAKAO_BROWSER_DRIVER_SHA256': 'sha256:' + 'a' * 64,
}) is None
"""
    process = subprocess.run(
        [sys.executable, "-B", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize(
    "change",
    [
        {"EOM_KAKAO_PROFILE_ID": ""},
        {"EOM_KAKAO_PROFILE_ID": "channel-name"},
        {"EOM_KAKAO_PROFILE_ID": "kakaoprofile_" + "A" * 32},
        {"EOM_KAKAO_COLLECTION_ADAPTER_SHA256": ""},
        {"EOM_KAKAO_COLLECTION_ADAPTER_SHA256": "browser-driver"},
        {"EOM_KAKAO_COLLECTION_ADAPTER_SHA256": "sha256:" + "a" * 63},
        {"EOM_KAKAO_COLLECTION_ADAPTER_SHA256": "sha256:" + "A" * 64},
    ],
)
def test_explicit_invalid_configuration_is_not_silently_disabled(change):
    with pytest.raises(ValueError, match=r"^KAKAO_COLLECTION_CONFIGURATION_INVALID$"):
        composition.build_configured_kakao_collection_attempts(Mock(), environment() | change)


def test_exact_configuration_uses_existing_owner_and_does_not_launch(monkeypatch):
    from eom_catalog_service import artifacts, kakao_collection_attempt_service

    engine, store, owner = Mock(), Mock(), Mock()
    make_store = Mock(return_value=store)
    make_owner = Mock(return_value=owner)
    monkeypatch.setattr(artifacts, "CatalogArtifactService", make_store)
    monkeypatch.setattr(
        kakao_collection_attempt_service, "KakaoCollectionAttemptService", make_owner
    )
    assert composition.build_configured_kakao_collection_attempts(engine, environment()) is owner
    make_store.assert_called_once_with(engine)
    make_owner.assert_called_once_with(
        engine,
        artifacts=store,
        profile_id=environment()["EOM_KAKAO_PROFILE_ID"],
        adapter_release_sha256=environment()["EOM_KAKAO_COLLECTION_ADAPTER_SHA256"],
    )
    assert owner.mock_calls == [] and store.mock_calls == [] and engine.mock_calls == []


def test_question_read_edit_and_concepts_share_the_actual_source_owner(monkeypatch):
    from eom_catalog_service import kakao_question_composition as questions

    engine, owner = Mock(), Mock()
    names = (
        "CatalogArtifactService",
        "KakaoSourceService",
        "KakaoQuestionService",
        "KakaoConceptKnowledgeReader",
        "KakaoQuestionReads",
        "KakaoQuestionComposeService",
        "KakaoConceptTaskService",
    )
    constructors = {name: Mock() for name in names}
    for name, constructor in constructors.items():
        monkeypatch.setattr(questions, name, constructor)
    app = questions.build_kakao_question_application(engine, collection_attempts=owner)
    assert app.collection_attempts is owner and app.concept_coordinator is None
    constructors["CatalogArtifactService"].assert_not_called()
    constructors["KakaoSourceService"].assert_not_called()
    for name in (
        "KakaoQuestionService",
        "KakaoQuestionReads",
        "KakaoQuestionComposeService",
        "KakaoConceptTaskService",
    ):
        assert constructors[name].call_args.kwargs["sources"] is owner.sources
        assert constructors[name].call_args.kwargs["artifacts"] is owner.artifacts
    assert owner.method_calls == []


def test_question_default_still_has_no_admission_authority(monkeypatch):
    from eom_catalog_service import kakao_question_composition as questions
    from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError

    for name in (
        "CatalogArtifactService",
        "KakaoSourceService",
        "KakaoQuestionService",
        "KakaoConceptKnowledgeReader",
        "KakaoQuestionReads",
        "KakaoQuestionComposeService",
        "KakaoConceptTaskService",
    ):
        monkeypatch.setattr(questions, name, Mock())
    app = questions.build_kakao_question_application(Mock())
    assert app.collection_attempts is None
    deny = questions.KakaoSourceService.call_args.kwargs["authorize_capture"]
    with pytest.raises(KakaoArchiveError, match="ADMISSION_AUTHORITY_REQUIRED"):
        deny(Mock(), Mock(), Mock())
