"""Real disposable PostgreSQL claims/renewal; no model, NAS publication or production DB."""

from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from eom_catalog_service.material_claim_renewal import maintain_material_claim
from eom_catalog_service.material_learning_models import MaterialLearningRunRecord
from eom_catalog_service.material_learning_store import (
    MaterialLearningStorageError,
    claim_next_material_run,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy.orm import Session

from tests.integration.test_material_learning_coordinator_storage import (
    coordinator_case as coordinator_case,
)
from tests.integration.test_material_learning_intake_storage import (
    material_intake as material_intake,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_long_publication_renewal_keeps_the_same_claim_from_a_competing_owner(
    creative_engine, coordinator_case
):
    accepted, _settings, _restart = coordinator_case
    start = datetime.now(UTC)
    with Session(creative_engine) as session, session.begin():
        claim = claim_next_material_run(
            session,
            lease_owner="slow-material-publication",
            now=start - timedelta(seconds=9),
            lease_duration=timedelta(seconds=10),
        )
        assert claim is not None and claim.run_id == accepted.run_id
    with maintain_material_claim(
        build_session_factory(creative_engine),
        claim,
        lease_duration=timedelta(seconds=10),
        heartbeat_seconds=0.05,
    ):
        Event().wait(1.2)
        with Session(creative_engine) as session, session.begin():
            row = session.get(MaterialLearningRunRecord, accepted.run_id)
            assert row.lease_token == claim.lease_token
            assert row.lease_expires_at > start + timedelta(seconds=11)
            assert (
                claim_next_material_run(
                    session,
                    lease_owner="competing-material-owner",
                    now=start + timedelta(seconds=10.2),
                    lease_duration=timedelta(seconds=10),
                )
                is None
            )


def test_stolen_or_expired_claim_cannot_be_revived_by_a_late_heartbeat(
    creative_engine, coordinator_case
):
    accepted, _settings, _restart = coordinator_case
    now = datetime.now(UTC)
    with Session(creative_engine) as session, session.begin():
        old = claim_next_material_run(
            session,
            lease_owner="expired-material-owner",
            now=now - timedelta(seconds=20),
            lease_duration=timedelta(seconds=10),
        )
    with Session(creative_engine) as session, session.begin():
        current = claim_next_material_run(
            session,
            lease_owner="replacement-material-owner",
            now=now,
            lease_duration=timedelta(minutes=15),
        )
    assert old is not None and current is not None
    assert old.run_id == current.run_id == accepted.run_id
    assert old.lease_token != current.lease_token
    with (
        pytest.raises(MaterialLearningStorageError, match="LEASE_STALE"),
        maintain_material_claim(
            build_session_factory(creative_engine), old, lease_duration=timedelta(minutes=15)
        ),
    ):
        pytest.fail("the replaced claim entered Graph publication")
    with Session(creative_engine) as session:
        row = session.get(MaterialLearningRunRecord, accepted.run_id)
        assert row.lease_token == current.lease_token
        assert row.lease_expires_at == current.lease_expires_at
