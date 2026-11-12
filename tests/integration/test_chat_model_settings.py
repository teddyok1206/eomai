"""Concurrent administrator changes and exact replay in the disposable DB only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from eom_orchestrator import general_chat_model_selection as settings
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_model_settings_store import (
    ChatModelSettingsRecord,
    ChatModelSettingsRevisionRecord,
)
from eom_workflow.control_plane import ModelCandidate
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def model_settings(guarded_engine, monkeypatch):
    monkeypatch.setattr(
        settings,
        "chat_model_candidates",
        lambda session, **_: (
            ModelCandidate(model="synthetic-model", reasoning_effort="medium"),
            ModelCandidate(model="synthetic-other", reasoning_effort="high"),
        ),
    )
    return guarded_engine


def current_version(engine):
    with Session(engine) as db:
        return db.get(ChatModelSettingsRecord, "general-chat").resource_version


def change(engine, version, key, *, model="synthetic-model", effort="medium"):
    with Session(engine) as db, db.begin():
        return settings.change_chat_model_settings(
            db,
            model=model,
            reasoning_effort=effort,
            expected_version=version,
            requested_by="operator_" + "c" * 32,
            request_key=key,
            requested_at=datetime.now(UTC),
        )


def test_exact_replay_does_not_create_revision_and_old_replay_survives_new_settings(model_settings):
    version = current_version(model_settings)
    key = uuid4().hex
    first = change(model_settings, version, key)
    assert change(model_settings, version, key) == first
    second = change(
        model_settings, version + 1, uuid4().hex, model="synthetic-other", effort="high"
    )
    assert second.revision_number == version + 2
    assert change(model_settings, version, key) == first
    with Session(model_settings) as db:
        assert settings.current_chat_model_settings(db) == second
        assert (
            db.scalar(
                select(func.count())
                .select_from(ChatModelSettingsRevisionRecord)
                .where(ChatModelSettingsRevisionRecord.revision_number > version)
            )
            == 2
        )
    with pytest.raises(ControlPlaneError) as captured:
        change(model_settings, version, key, model="synthetic-other", effort="high")
    assert captured.value.code == "CONTROL_CHAT_MODEL_REPLAY_CONFLICT"


def test_two_administrators_same_version_have_one_winner(model_settings):
    version = current_version(model_settings)
    gate = Barrier(2)

    def submit(_):
        gate.wait(timeout=15)
        try:
            return change(model_settings, version, uuid4().hex)
        except ControlPlaneError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(submit, range(2)))
    assert sum(not isinstance(value, str) for value in results) == 1
    assert "CONTROL_CHAT_MODEL_VERSION_STALE" in results
    assert current_version(model_settings) == version + 1


def test_same_command_concurrent_replay_has_one_revision(model_settings):
    version = current_version(model_settings)
    key = uuid4().hex
    gate = Barrier(4)

    def submit(_):
        gate.wait(timeout=15)
        return change(model_settings, version, key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = tuple(pool.map(submit, range(4)))
    assert len({value.revision_id for value in results}) == 1
    assert current_version(model_settings) == version + 1


@pytest.mark.parametrize(
    "model,effort", (("synthetic-model", "xhigh"), ("unknown-model", "medium"))
)
def test_unverified_model_effort_cannot_be_saved(model_settings, model, effort):
    version = current_version(model_settings)
    with pytest.raises(ControlPlaneError) as captured:
        change(model_settings, version, uuid4().hex, model=model, effort=effort)
    assert captured.value.code == "CONTROL_CHAT_MODEL_UNAVAILABLE"
    assert current_version(model_settings) == version


def test_revision_is_immutable_small_metadata_not_worker_auth_or_payload(model_settings):
    version = current_version(model_settings)
    value = change(model_settings, version, uuid4().hex)
    with Session(model_settings) as db, db.begin():
        row = db.get(ChatModelSettingsRevisionRecord, value.revision_id)
        assert len(str(row.canonical_document)) < 1200
        assert (
            not {"auth", "prompt", "result", "image", "password", "worker_path"}
            & row.canonical_document.keys()
        )
        row.sha256 = "sha256:" + "0" * 64
        with pytest.raises(DBAPIError, match="immutable"):
            db.flush()
        db.rollback()
