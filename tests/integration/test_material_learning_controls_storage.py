"""Actual control lifecycle/concurrent replay in marker-guarded PostgreSQL, no inference."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.material_learning_controls import release_material_learning_controls
from eom_orchestrator.settings import Settings
from sqlalchemy import select

from tests.integration.test_knowledge_analysis_service import OPERATOR_ID
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def material_control_arguments(baseline):
    return dict(
        baseline_revision_id=baseline.preset_revision_id,
        platform_payload=b"# Synthetic material platform\n",
        learning_payload=b"# Synthetic material extraction\n",
        document_payload=b"# Synthetic material knowledge\n",
        operator_id=OPERATOR_ID,
        source_commit="a" * 40,
        authorize=Mock(),
        reviewed_at=datetime(2026, 11, 6, tzinfo=UTC),
    )


def test_material_release_concurrent_replay_preserves_baseline_and_shares_host(controls):
    engine, catalog, baseline = controls
    sessions = build_session_factory(engine)
    publisher = ControlArtifactPublisher(
        engine,
        Settings(staging_root=catalog.staging_root, nas_artifact_root=catalog.nas_artifact_root),
    )
    with sessions() as session:
        before = session.get(
            ExecutionPresetRevisionRecord, baseline.preset_revision_id
        ).canonical_document
    arguments = material_control_arguments(baseline)
    barrier = Barrier(2)

    def release(_):
        barrier.wait(timeout=10)
        return release_material_learning_controls(sessions, publisher, **arguments)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(release, range(2))
    assert first == second
    assert first.capacity.purpose == "UPLOADED_MATERIAL_LEARNING"
    assert first.capacity.max_active_codex == 4
    assert first.capacity.max_active_knowledge_analysis == 4
    assert first.capacity.pools[0].slot_keys == ("slot03", "slot04", "slot05", "slot06")
    assert first.learning.general_knowledge_policy == "DENY"
    assert first.item.role_policies == first.solution.role_policies
    assert first.item.compatible_workflow_protocols == ("workflow-role/1.4.0",)
    assert first.solution.compatible_workflow_protocols == ("workflow-role/1.35.0",)
    with sessions() as session:
        assert (
            session.get(
                ExecutionPresetRevisionRecord, baseline.preset_revision_id
            ).canonical_document
            == before
        )
        assert (
            len(
                tuple(
                    session.scalars(
                        select(ExecutionPresetRecord).where(
                            ExecutionPresetRecord.preset_key.in_(
                                (
                                    "material-learning",
                                    "material-item-analysis",
                                    "material-item-solution",
                                    "material-knowledge-analysis",
                                )
                            )
                        )
                    )
                )
            )
            == 4
        )
