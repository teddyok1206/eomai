"""Original control owner under concurrent common-policy publication, disposable PG only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.private_chat_query_execution_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicyV2,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_private_chat_public_query_execution import execution_case
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_execution import execution_case as legacy_execution_case

pytestmark = pytest.mark.integration


@pytest.fixture
def controls(guarded_engine, tmp_path):
    assert guarded_engine.dialect.name == "postgresql"
    settings = Settings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "local-artifacts",
        workspace_root=tmp_path / "workspaces",
    )
    settings.nas_artifact_root.mkdir(mode=0o700)
    settings.workspace_root.mkdir(mode=0o700)
    return LocalEmbeddingControlArtifactPublisher(
        ControlFileSetPublisher(guarded_engine, settings), source_commit="a" * 40
    )


def test_concurrent_common_policy_publishers_commit_one_original_revision_and_replay(controls):
    policy = execution_case()[1]
    key = "private-common-policy:" + uuid4().hex
    barrier = Barrier(3)

    def publish(_index):
        barrier.wait(timeout=15)
        return controls.publish_private_chat_public_query_policy(
            policy, idempotency_key=key, created_at=NOW
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        saved = tuple(pool.map(publish, range(3)))
    assert saved[0] == saved[1] == saved[2]
    result = saved[0]
    assert (
        controls.publish_private_chat_public_query_policy(
            policy, idempotency_key=key, created_at=NOW
        )
        == result
    )
    assert result.member.schema_ref == PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF
    with Session(controls.publisher.engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
            )
            == 1
        )
        job = session.get(JobRecord, result.owner_job_id)
        assert job.status == "SUCCEEDED" and TEXT.encode() not in canonical_json_bytes(job.request)
        revision = session.get(ArtifactRevisionRecord, result.member.artifact_revision_id)
        assert revision.job_id == job.job_id
        assert TEXT.encode() not in canonical_json_bytes(revision.result)


def test_conflicting_policy_same_key_preserves_committed_original(controls):
    policy = execution_case()[1]
    key = "private-common-policy:" + uuid4().hex
    saved = controls.publish_private_chat_public_query_policy(
        policy, idempotency_key=key, created_at=NOW
    )
    changed = PrivateChatQueryExecutionPolicyV2.model_validate(
        seal(
            policy.model_copy(
                update={"created_at": policy.created_at + timedelta(seconds=1)}
            ).model_dump(mode="json"),
            "policy_sha256",
        )
    )
    with pytest.raises(ControlPlaneError) as error:
        controls.publish_private_chat_public_query_policy(
            changed, idempotency_key=key, created_at=NOW
        )
    assert error.value.code == "CONTROL_FILE_SET_CONFLICT"
    assert (
        controls.publish_private_chat_public_query_policy(
            policy, idempotency_key=key, created_at=NOW
        )
        == saved
    )


@pytest.mark.parametrize("fault", ["legacy", "extra"])
def test_wrong_policy_family_and_private_extra_never_create_job(controls, fault):
    key = "invalid-private-common-policy:" + uuid4().hex
    policy = (
        legacy_execution_case()[1]
        if fault == "legacy"
        else execution_case()[1].model_copy(update={"question": "DO_NOT_DISCLOSE"})
    )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CONTROL_INVALID") as error:
        controls.publish_private_chat_public_query_policy(
            policy, idempotency_key=key, created_at=NOW
        )
    assert "DO_NOT_DISCLOSE" not in str(error.value)
    with Session(controls.publisher.engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
            )
            == 0
        )
