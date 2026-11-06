"""Bounded renewal scope preserves ownership and the original failure, without live IO."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from eom_catalog_service import material_claim_renewal as owner
from eom_catalog_service.material_learning_store import (
    MaterialLearningStorageError,
    MaterialRunClaim,
)


def claim():
    return MaterialRunClaim(
        "materialrun_" + "1" * 32, "owner", "2" * 32, datetime.now(UTC) + timedelta(minutes=15)
    )


def sessions():
    session = Mock()
    session.get_bind.return_value.dialect.name = "postgresql"
    factory = Mock()

    @contextmanager
    def begin():
        yield session

    factory.begin.side_effect = begin
    return factory, session


def test_renewal_rechecks_the_original_token_and_stops_before_final_fence(monkeypatch):
    factory, session = sessions()
    renewed = Event()
    renew = Mock(side_effect=lambda *args, **kwargs: renewed.set())
    fence = Mock()
    monkeypatch.setattr(owner, "renew_material_claim", renew)
    monkeypatch.setattr(owner, "lock_material_run", fence)
    identity = claim()
    with owner.maintain_material_claim(
        factory, identity, lease_duration=timedelta(minutes=15), heartbeat_seconds=0.01
    ):
        renewed.clear()
        assert renewed.wait(2)
    count = renew.call_count
    assert count >= 2
    assert all(call.args == (session, identity) for call in renew.call_args_list)
    fence.assert_called_once()
    assert fence.call_args.args == (session, identity)
    Event().wait(0.03)
    assert renew.call_count == count


def test_lost_renewal_cannot_report_success(monkeypatch):
    factory, _session = sessions()
    lost = Event()

    def renew(*args, **kwargs):
        if lost.is_set():
            raise MaterialLearningStorageError("MATERIAL_LEARNING_COORDINATOR_LEASE_STALE")
        lost.set()

    monkeypatch.setattr(owner, "renew_material_claim", renew)
    fence = Mock()
    monkeypatch.setattr(owner, "lock_material_run", fence)
    with (
        pytest.raises(MaterialLearningStorageError, match="LEASE_STALE"),
        owner.maintain_material_claim(
            factory, claim(), lease_duration=timedelta(minutes=15), heartbeat_seconds=0.01
        ),
    ):
        Event().wait(0.08)
    fence.assert_not_called()


def test_body_failure_is_not_hidden_by_renewal_failure(monkeypatch):
    factory, _session = sessions()
    renew = Mock(side_effect=[None, RuntimeError("synthetic renewal failure")])
    monkeypatch.setattr(owner, "renew_material_claim", renew)
    with (
        pytest.raises(ValueError, match="original source failure"),
        owner.maintain_material_claim(
            factory, claim(), lease_duration=timedelta(minutes=15), heartbeat_seconds=0.01
        ),
    ):
        Event().wait(0.08)
        raise ValueError("original source failure")


@pytest.mark.parametrize("interval", [0, -1, True, float("inf"), float("nan"), 301])
def test_invalid_interval_is_refused_before_database_access(interval):
    factory, _session = sessions()
    with (
        pytest.raises(ValueError, match="HEARTBEAT_INTERVAL_INVALID"),
        owner.maintain_material_claim(
            factory, claim(), lease_duration=timedelta(minutes=15), heartbeat_seconds=interval
        ),
    ):
        pytest.fail("invalid heartbeat entered publication")
    factory.begin.assert_not_called()
