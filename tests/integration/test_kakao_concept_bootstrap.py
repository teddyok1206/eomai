"""Existing Control publication on disposable DB/local Artifacts, no model or production auth."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from eom_orchestrator import kakao_concept_bootstrap as module
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_orchestrator.settings import Settings
from eom_workflow import ExecutionPresetRevision
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_kakao_concept_task_storage import (
    concept_execution_store as concept_execution_store,
)
from tests.integration.test_kakao_concept_task_storage import (
    concept_store as concept_store,
)
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def bootstrap_store(concept_execution_store, monkeypatch):
    value = concept_execution_store
    # Scope only the new logical key so retained synthetic histories are not overwritten.
    # The production constant is fixed; the actual definition/source/adapters are unchanged.
    assert module.PRESET_KEY == "kakao-concepts"
    key = "concept-bootstrap-fixture-" + uuid4().hex
    monkeypatch.setattr(module, "PRESET_KEY", key)
    source = (
        module.Path(__file__).resolve().parents[2]
        / "config/control-plane/kakao-concepts-v1/instructions/kakao-concepts.md"
    )
    with Session(value.engine) as session:
        base = session.get(ExecutionPresetRevisionRecord, value.pinned.preset_revision_id)
        identity = base.preset_revision_id, base.content_sha256
    options = dict(
        instruction_path=source,
        source_commit="a" * 40,
        actor_id="disposable-bootstrap",
        created_at=datetime(2026, 11, 17, 16, tzinfo=UTC),
        base_preset_revision_id=identity[0],
        base_preset_sha256=identity[1],
        settings=Settings(
            staging_root=value.service.artifacts.settings.staging_root,
            nas_artifact_root=value.service.artifacts.settings.nas_artifact_root,
        ),
    )
    return value, key, options


def counts(engine):
    with Session(engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                ArtifactRevisionRecord,
                CodexAuthBindingRecord,
                WorkerCapacityPolicyRevisionRecord,
            )
        )


def test_publication_replay_reuses_role_platform_and_capacity_without_claims(bootstrap_store):
    value, key, options = bootstrap_store
    before = counts(value.engine)
    first = module.bootstrap_kakao_concepts(value.engine, **options)
    after = counts(value.engine)
    assert after[1:] == before[1:] and after[0] > before[0]
    assert module.bootstrap_kakao_concepts(value.engine, **options) == first
    assert counts(value.engine) == after
    with Session(value.engine) as session:
        logical = session.scalar(
            select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == key)
        )
        released = session.get(ExecutionPresetRevisionRecord, first.preset_revision_id)
        base = session.get(ExecutionPresetRevisionRecord, options["base_preset_revision_id"])
        preset = ExecutionPresetRevision.model_validate(released.canonical_document)
        baseline = ExecutionPresetRevision.model_validate(base.canonical_document)
        assert (
            logical.current_revision_id == preset.preset_revision_id and preset.state == "RELEASED"
        )
        assert preset.capacity_policy_revision_id == baseline.capacity_policy_revision_id
        assert (
            preset.general_knowledge_policy == "DENY"
            and preset.compatible_workflow_protocols == ("workflow-role/1.41.0",)
        )
        assert (
            preset.role_policies[0].model_candidates == baseline.role_policies[0].model_candidates
        )
        assert preset.role_policies[0].worker_pool_key == "support"
        assert (
            preset.role_policies[0].instruction_bundle
            != baseline.role_policies[0].instruction_bundle
        )


def test_independent_publishers_adopt_one_release_and_evidence(bootstrap_store):
    value, _key, options = bootstrap_store
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = tuple(
            pool.map(lambda _: module.bootstrap_kakao_concepts(value.engine, **options), range(2))
        )
    assert result[0] == result[1]
    with Session(value.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetRevisionRecord)
                .where(ExecutionPresetRevisionRecord.preset_id == result[0].preset_id)
            )
            == 2
        )


def test_stale_baseline_hash_refuses_before_artifact_publication(bootstrap_store):
    value, _key, options = bootstrap_store
    before = counts(value.engine)
    with pytest.raises(ControlPlaneError, match="baseline changed"):
        module.bootstrap_kakao_concepts(
            value.engine, **{**options, "base_preset_sha256": "sha256:" + "f" * 64}
        )
    assert counts(value.engine) == before


def test_changed_role_does_not_overwrite_an_existing_purpose(bootstrap_store, tmp_path):
    value, _key, options = bootstrap_store
    original = module.bootstrap_kakao_concepts(value.engine, **options)
    changed = tmp_path / "changed.md"
    changed.write_text("Changed role fixture", encoding="utf-8")
    with pytest.raises(ControlPlaneError):
        module.bootstrap_kakao_concepts(value.engine, **{**options, "instruction_path": changed})
    with Session(value.engine) as session:
        row = session.get(ExecutionPresetRecord, original.preset_id)
        assert row.current_revision_id == original.preset_revision_id


@pytest.mark.parametrize("kind", ["naive", "non-utc", "bad-source"])
def test_publication_identity_errors_have_no_artifact_writes(bootstrap_store, kind):
    value, _key, options = bootstrap_store
    before = counts(value.engine)
    if kind == "naive":
        options = {**options, "created_at": datetime(2026, 11, 17)}
    elif kind == "non-utc":
        options = {
            **options,
            "created_at": datetime(2026, 11, 17, tzinfo=timezone(timedelta(hours=9))),
        }
    else:
        options = {**options, "source_commit": "not-a-commit"}
    with pytest.raises(ControlPlaneError):
        module.bootstrap_kakao_concepts(value.engine, **options)
    assert counts(value.engine) == before
