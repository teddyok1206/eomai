"""Genuine disposable control lifecycle/locking/publication, no worker/model calls.

Run LAST after ordinary Material fixture consumers. This intentional upgrade
leaves the logical preset at1.39; the preserved INITIAL1.37 bootstrap must not be
used to reset that state. The extra test opt-in prevents broad discovery from
changing a shared disposable fixture's baseline midway through another suite.
Operator authorization is an explicit fixture callback, not HTTP login evidence.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.material_learning_controls import release_material_learning_controls
from eom_orchestrator.material_learning_coverage_controls import (
    require_material_learning_coverage_successor,
    upgrade_material_learning_coverage_preset,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.preset_model_selection import (
    current_model_preset,
    non_live_invocation_cases,
    require_model_only_successor,
    validated_preset,
)
from eom_orchestrator.preset_policy import execution_preset_policy_sha256
from eom_orchestrator.settings import Settings
from eom_workflow import ExecutionPresetEvaluationReport
from sqlalchemy import select

from tests.integration.test_knowledge_analysis_service import OPERATOR_ID
from tests.integration.test_material_learning_controls_storage import material_control_arguments
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_item_solution_application import controls as controls

pytestmark = [
    pytest.mark.integration,
    pytest.mark.api_integration,
    pytest.mark.skipif(
        os.environ.get("EOM_RUN_MATERIAL_COVERAGE_UPGRADE_TESTS") != "1",
        reason="run explicitly LAST in the marker-guarded disposable Material DB",
    ),
]


def _select_fixture_model(sessions, publisher, base, *, effort):
    """Real existing lifecycle with synthetic NON_LIVE report, never fake DB rows."""
    now = datetime.now(UTC)
    policies = [policy.model_dump(mode="json") for policy in base.role_policies]
    policies[0]["model_candidates"][0]["reasoning_effort"] = effort
    with sessions.begin() as session:
        draft_row = create_execution_preset_draft(
            session,
            preset_key="material-learning",
            display_name=base.display_name,
            description=base.description,
            role_policies=policies,
            capacity_policy_revision_id=base.capacity_policy_revision_id,
            general_knowledge_policy=base.general_knowledge_policy,
            compatible_workflow_protocols=list(base.compatible_workflow_protocols),
            created_by=OPERATOR_ID,
            created_at=now,
        )
        draft = validated_preset(draft_row)
    require_model_only_successor(base, draft)
    cases = non_live_invocation_cases(draft)
    body = dict(
        schema_version="execution-preset-evaluation-report/1.0",
        evaluated_preset_revision_id=draft.preset_revision_id,
        evaluated_policy_sha256=execution_preset_policy_sha256(draft),
        scope="NON_LIVE",
        outcome="PASS",
        summary_code="CONTRACT_VALIDATION",
        cases_total=len(cases),
        cases_passed=len(cases),
        quality_score_permille=None,
        completed_at=now.isoformat().replace("+00:00", "Z"),
    )
    report = ExecutionPresetEvaluationReport.model_validate(
        {**body, "report_sha256": content_sha256(body)}
    )
    artifact = publisher.publish_bytes(
        payload=canonical_json_bytes(report.model_dump(mode="json")) + b"\n",
        logical_name="fixture-material-model-evaluation.json",
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        artifact_type="control_preset_evaluation",
        idempotency_key="fixture-material-model:" + report.report_sha256[7:],
        created_at=now,
        source_commit="a" * 40,
    )
    with sessions.begin() as session:
        record_execution_preset_evaluation(
            session,
            document=report.model_dump(mode="json"),
            report_artifact=artifact.pointer,
            created_by=OPERATOR_ID,
        )
        return validated_preset(
            release_execution_preset(
                session,
                draft_revision_id=draft.preset_revision_id,
                released_by=OPERATOR_ID,
                released_at=now,
            )
        )


def test_upgrade_real_concurrency_parent_cas_lost_response_and_current_model_preservation(controls):
    engine, catalog, knowledge_baseline = controls
    sessions = build_session_factory(engine)
    publisher = ControlArtifactPublisher(
        engine,
        Settings(
            staging_root=catalog.staging_root,
            nas_artifact_root=catalog.nas_artifact_root,
        ),
    )
    initial = release_material_learning_controls(
        sessions, publisher, **material_control_arguments(knowledge_baseline)
    )
    with sessions() as session:
        others = {
            row.preset_id: (
                row.current_revision_id,
                deepcopy(
                    session.get(
                        ExecutionPresetRevisionRecord, row.current_revision_id
                    ).canonical_document
                ),
            )
            for row in session.scalars(
                select(ExecutionPresetRecord).where(
                    ExecutionPresetRecord.preset_key.in_(
                        (
                            "material-item-analysis",
                            "material-item-solution",
                            "material-knowledge-analysis",
                        )
                    )
                )
            )
        }
        original_rows = {
            row.preset_revision_id: deepcopy(row.canonical_document)
            for row in session.scalars(
                select(ExecutionPresetRevisionRecord).where(
                    ExecutionPresetRevisionRecord.preset_id.in_(
                        (initial.learning.preset_id, *others)
                    )
                )
            )
        }
    selected = _select_fixture_model(sessions, publisher, initial.learning, effort="medium")
    assert selected.role_policies[0].model_candidates[0].reasoning_effort == "medium"
    authorized = []

    def authorize(actor):
        assert actor == OPERATOR_ID
        authorized.append(actor)

    def arguments(base):
        return dict(
            expected_current_revision_id=base.preset_revision_id,
            expected_current_sha256=base.content_sha256,
            operator_id=OPERATOR_ID,
            source_commit="a" * 40,
            authorize=authorize,
            reviewed_at=datetime.now(UTC),
        )

    # Actual separate transaction changes current while the upgrade has released
    # its draft lock to publish. The final expected-parent fence must catch it.
    changed = []

    class RacingPublisher:
        def publish_bytes(self, **request):
            artifact = publisher.publish_bytes(**request)
            changed.append(_select_fixture_model(sessions, publisher, selected, effort="high"))
            return artifact

    with pytest.raises(ControlPlaneError) as failure:
        upgrade_material_learning_coverage_preset(
            sessions, RacingPublisher(), **arguments(selected)
        )
    assert failure.value.code == "CONTROL_PRESET_BASE_STALE"
    latest = changed[0]
    with sessions() as session:
        logical = session.get(ExecutionPresetRecord, selected.preset_id)
        assert logical.current_revision_id == latest.preset_revision_id
        assert not tuple(
            session.scalars(
                select(ExecutionPresetRevisionRecord).where(
                    ExecutionPresetRevisionRecord.preset_id == selected.preset_id,
                    ExecutionPresetRevisionRecord.state == "RELEASED",
                    ExecutionPresetRevisionRecord.compatible_workflow_protocols
                    == ["workflow-role/1.39.0"],
                )
            )
        )

    # Commit a REAL evaluation Artifact and then lose only its caller response.
    # No error is translated into success, no Job/Artifact state is fabricated.
    lost_calls = []

    class LostResponsePublisher:
        def publish_bytes(self, **request):
            artifact = publisher.publish_bytes(**request)
            lost_calls.append((request, artifact))
            raise ControlPlaneError(
                "TEST_LOST_PUBLICATION_RESPONSE", "test response lost after commit"
            )

    exact_arguments = arguments(latest)
    with pytest.raises(ControlPlaneError) as failure:
        upgrade_material_learning_coverage_preset(
            sessions, LostResponsePublisher(), **exact_arguments
        )
    assert failure.value.code == "TEST_LOST_PUBLICATION_RESPONSE" and len(lost_calls) == 1
    with sessions() as session:
        assert (
            session.get(ExecutionPresetRecord, latest.preset_id).current_revision_id
            == latest.preset_revision_id
        )
        artifact_job = session.scalar(
            select(JobRecord).where(
                JobRecord.idempotency_key == lost_calls[0][0]["idempotency_key"]
            )
        )
        assert artifact_job.status == "SUCCEEDED"
        assert not tuple(
            session.scalars(
                select(ExecutionPresetEvaluationRecord).where(
                    ExecutionPresetEvaluationRecord.report_artifact_revision_id
                    == lost_calls[0][1].pointer.artifact_revision_id,
                )
            )
        )

    barrier = Barrier(2)

    def concurrent_upgrade(_):
        barrier.wait(timeout=10)
        return upgrade_material_learning_coverage_preset(sessions, publisher, **exact_arguments)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(concurrent_upgrade, range(2))
    assert first == second
    require_material_learning_coverage_successor(latest, first)
    assert first.preset_id == latest.preset_id and first.role_policies == latest.role_policies
    assert first.general_knowledge_policy == "DENY"
    assert first.capacity_policy_revision_id == latest.capacity_policy_revision_id
    assert first.compatible_workflow_protocols == ("workflow-role/1.39.0",)
    assert (
        upgrade_material_learning_coverage_preset(
            sessions,
            publisher,
            **(exact_arguments | {"reviewed_at": datetime.now(UTC) + timedelta(seconds=1)}),
        )
        == first
    )
    with sessions() as session:
        released = tuple(
            session.scalars(
                select(ExecutionPresetRevisionRecord).where(
                    ExecutionPresetRevisionRecord.preset_id == latest.preset_id,
                    ExecutionPresetRevisionRecord.state == "RELEASED",
                    ExecutionPresetRevisionRecord.compatible_workflow_protocols
                    == ["workflow-role/1.39.0"],
                )
            )
        )
        assert len(released) == 1 and released[0].preset_revision_id == first.preset_revision_id
        evaluations = tuple(
            session.scalars(
                select(ExecutionPresetEvaluationRecord).where(
                    ExecutionPresetEvaluationRecord.report_artifact_revision_id
                    == lost_calls[0][1].pointer.artifact_revision_id,
                )
            )
        )
        assert len(evaluations) == 1
        assert evaluations[0].evaluated_policy_sha256 == execution_preset_policy_sha256(first)
        jobs = tuple(
            session.scalars(
                select(JobRecord).where(JobRecord.idempotency_key.like("material-coverage-eval:%"))
            )
        )
        assert len(jobs) == 2 and all(job.status == "SUCCEEDED" for job in jobs)

    # Same logical1.39 preset still uses the ordinary model-only owner. The old
    # upgrade command must not overwrite this later administrator selection.
    current = _select_fixture_model(sessions, publisher, first, effort="low")
    with sessions() as session:
        assert current_model_preset(session, first) == current
    with pytest.raises(ControlPlaneError) as failure:
        upgrade_material_learning_coverage_preset(sessions, publisher, **exact_arguments)
    assert failure.value.code == "CONTROL_PRESET_BASE_STALE"
    with sessions() as session:
        assert (
            session.get(ExecutionPresetRecord, first.preset_id).current_revision_id
            == current.preset_revision_id
        )
        for preset_id, (revision_id, document) in others.items():
            assert session.get(ExecutionPresetRecord, preset_id).current_revision_id == revision_id
            assert (
                session.get(ExecutionPresetRevisionRecord, revision_id).canonical_document
                == document
            )
        for revision_id, document in original_rows.items():
            assert (
                session.get(ExecutionPresetRevisionRecord, revision_id).canonical_document
                == document
            )
    assert len(authorized) >= 10
