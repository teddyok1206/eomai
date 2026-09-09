from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import eom_orchestrator.control_artifacts as control_artifacts
import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.artifacts import stage_file_set_artifact as real_stage_file_set_artifact
from eom_orchestrator.control_artifacts import (
    CONTROL_ARTIFACT_PROTOCOL,
    LEGACY_CONTROL_ARTIFACT_PROTOCOL,
    ControlArtifactPublisher,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import transaction
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    Base,
    JobEventRecord,
    JobRecord,
    ProtocolVersionRecord,
    WorkerSlotRecord,
)
from eom_orchestrator.repository import (
    create_artifact_records as real_create_artifact_records,
)
from eom_orchestrator.repository import (
    submit_structured_job,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import BigInteger, Engine, Table, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type: JSONB, _compiler: object, **_kwargs: object) -> str:
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_big_integer_for_sqlite(_type: BigInteger, _compiler: object, **_kwargs: object) -> str:
    return "INTEGER"


CREATED_AT = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)
PAYLOAD = b'{"schema_version":"test/1.0","value":"exact"}'
IDEMPOTENCY_KEY = "control-artifact-test:exact"


def _publisher(tmp_path: Path) -> tuple[ControlArtifactPublisher, Engine]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'control.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            cast(Table, ProtocolVersionRecord.__table__),
            cast(Table, WorkerSlotRecord.__table__),
            cast(Table, JobRecord.__table__),
            cast(Table, JobEventRecord.__table__),
            cast(Table, ArtifactRecord.__table__),
            cast(Table, ArtifactRevisionRecord.__table__),
        ],
    )
    staging = tmp_path / "staging"
    nas = tmp_path / "nas"
    nas.mkdir()
    return (
        ControlArtifactPublisher(
            engine,
            Settings(staging_root=staging, nas_artifact_root=nas),
        ),
        engine,
    )


def _publication_arguments(
    *,
    payload: bytes = PAYLOAD,
    source_commit: str = "a" * 40,
) -> dict[str, Any]:
    return {
        "payload": payload,
        "logical_name": "control-test.json",
        "schema_ref": "eom://schemas/test/control-test/1.0",
        "media_type": "application/json",
        "artifact_type": "control_test",
        "idempotency_key": IDEMPOTENCY_KEY,
        "created_at": CREATED_AT,
        "source_commit": source_commit,
    }


def _request(payload: bytes = PAYLOAD) -> dict[str, str | int]:
    return {
        "logical_name": "control-test.json",
        "schema_ref": "eom://schemas/test/control-test/1.0",
        "media_type": "application/json",
        "artifact_type": "control_test",
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
        "source_commit": "a" * 40,
        "created_at_utc": "2026-09-09T00:00:00Z",
    }


def _job(engine: Engine) -> JobRecord:
    with Session(engine) as session:
        return session.scalars(select(JobRecord)).one()


def test_publication_replays_created_job_after_staging_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, engine = _publisher(tmp_path)
    calls = 0

    def interrupted_stage(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated process interruption")
        return real_stage_file_set_artifact(**kwargs)

    monkeypatch.setattr(control_artifacts, "stage_file_set_artifact", interrupted_stage)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        publisher.publish_bytes(**_publication_arguments())
    interrupted_job = _job(engine)
    assert interrupted_job.status == JobState.CREATED.value

    result = publisher.publish_bytes(
        **{
            **_publication_arguments(),
            "created_at": datetime(2026, 9, 9, 0, 0, 1, tzinfo=UTC),
        }
    )

    assert result.job_id == interrupted_job.job_id
    assert _job(engine).status == JobState.SUCCEEDED.value


@pytest.mark.parametrize(
    "resume_state",
    [
        JobState.VALIDATED,
        JobState.QUEUED,
        JobState.CLAIMED,
        JobState.RUNNING,
        JobState.VALIDATING_RESULT,
    ],
)
def test_publication_resumes_every_intermediate_state(
    tmp_path: Path,
    resume_state: JobState,
) -> None:
    publisher, engine = _publisher(tmp_path)
    job, created = publisher._load_or_create_job(
        idempotency_key=IDEMPOTENCY_KEY,
        artifact_type="control_test",
        request=_request(),
    )
    assert created
    with transaction(publisher.sessions) as session:
        current = JobState.CREATED
        while current != resume_state:
            target, event = control_artifacts._PUBLICATION_TRANSITIONS[current]
            transition_job(session, job.job_id, target, event)
            current = target

    result = publisher.publish_bytes(**_publication_arguments())

    assert result.job_id == job.job_id
    assert _job(engine).status == JobState.SUCCEEDED.value


def test_publication_reconciles_nas_commit_before_database_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, engine = _publisher(tmp_path)
    calls = 0

    def interrupted_create(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        real_create_artifact_records(*args, **kwargs)
        if calls == 1:
            raise RuntimeError("simulated database commit loss")

    monkeypatch.setattr(control_artifacts, "create_artifact_records", interrupted_create)
    with pytest.raises(RuntimeError, match="simulated database commit loss"):
        publisher.publish_bytes(**_publication_arguments())
    interrupted_job = _job(engine)
    assert interrupted_job.status == JobState.COMMITTING.value
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 0
    assert len(list(publisher.settings.nas_artifact_root.glob("artifact_*/rev_*"))) == 1

    result = publisher.publish_bytes(**_publication_arguments())

    assert result.job_id == interrupted_job.job_id
    assert _job(engine).status == JobState.SUCCEEDED.value


def test_concurrent_same_key_publication_creates_one_identity(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    start = threading.Barrier(2)

    def publish() -> object:
        start.wait(timeout=5)
        return publisher.publish_bytes(**_publication_arguments())

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(publish), executor.submit(publish))
        first, second = (future.result(timeout=10) for future in futures)

    assert first == second
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1


def test_successful_publication_reuses_identity_across_source_release(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)

    first = publisher.publish_bytes(**_publication_arguments())
    replay = publisher.publish_bytes(
        **_publication_arguments(source_commit="b" * 40),
    )

    assert replay == first


def test_successful_publication_reuses_persisted_manifest_timestamp(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    expected = publisher.publish_bytes(**_publication_arguments())

    replay = publisher.publish_bytes(
        **{
            **_publication_arguments(),
            "created_at": datetime(2026, 9, 9, 0, 0, 1, tzinfo=UTC),
        }
    )

    assert replay == expected


def test_successful_replay_rejects_self_consistent_manifest_timestamp_drift(
    tmp_path: Path,
) -> None:
    publisher, _engine = _publisher(tmp_path)
    publisher.publish_bytes(**_publication_arguments())
    with transaction(publisher.sessions) as session:
        revision = session.execute(select(ArtifactRevisionRecord).with_for_update()).scalar_one()
        revision.manifest = {
            **revision.manifest,
            "created_at": "2026-09-09T00:00:01Z",
        }
        revision.manifest_hash = content_sha256(revision.manifest)

    with pytest.raises(ControlPlaneError) as captured:
        publisher.publish_bytes(**_publication_arguments())

    assert captured.value.code == "CONTROL_ARTIFACT_CONFLICT"


def test_publication_rejects_same_key_with_different_content(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    publisher.publish_bytes(**_publication_arguments())

    with pytest.raises(ControlPlaneError) as captured:
        publisher.publish_bytes(**_publication_arguments(payload=b'{"value":"drift"}'))

    assert captured.value.code == "CONTROL_ARTIFACT_CONFLICT"


def test_publication_rejects_terminal_job_without_side_effect(tmp_path: Path) -> None:
    publisher, engine = _publisher(tmp_path)
    job, created = publisher._load_or_create_job(
        idempotency_key=IDEMPOTENCY_KEY,
        artifact_type="control_test",
        request=_request(),
    )
    assert created
    with transaction(publisher.sessions) as session:
        transition_job(session, job.job_id, JobState.FAILED, "SIMULATED_TERMINAL_FAILURE")

    with pytest.raises(ControlPlaneError) as captured:
        publisher.publish_bytes(**_publication_arguments())

    assert captured.value.code == "CONTROL_ARTIFACT_TERMINAL"
    assert _job(engine).status == JobState.FAILED.value
    assert not list(publisher.settings.nas_artifact_root.iterdir())


def test_successful_replay_rejects_self_consistent_manifest_member_drift(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    published = publisher.publish_bytes(**_publication_arguments())
    with transaction(publisher.sessions) as session:
        revision = session.execute(select(ArtifactRevisionRecord).with_for_update()).scalar_one()
        revision.manifest = {
            **revision.manifest,
            "files": [*revision.manifest["files"], {"unexpected": True}],
        }
        revision.manifest_hash = content_sha256(revision.manifest)

    with pytest.raises(ControlPlaneError) as captured:
        publisher.publish_bytes(**_publication_arguments())

    assert published.job_id == _job(publisher.engine).job_id
    assert captured.value.code == "CONTROL_ARTIFACT_CONFLICT"


def test_successful_replay_rejects_self_consistent_job_request_drift(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    publisher.publish_bytes(**_publication_arguments())
    with transaction(publisher.sessions) as session:
        job = session.execute(select(JobRecord).with_for_update()).scalar_one()
        job.request = {**job.request, "schema_ref": "eom://schemas/test/drift/1.0"}
        job.request_hash = content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
        revision = session.execute(select(ArtifactRevisionRecord).with_for_update()).scalar_one()
        revision.result = {
            "schema_version": "control-artifact-result/1.0",
            **job.request,
        }

    with pytest.raises(ControlPlaneError) as captured:
        publisher.publish_bytes(**_publication_arguments())

    assert captured.value.code == "CONTROL_ARTIFACT_CONFLICT"


def test_successful_replay_rejects_protocol_schema_drift(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    publisher.publish_bytes(**_publication_arguments())
    with transaction(publisher.sessions) as session:
        protocol = session.get(ProtocolVersionRecord, CONTROL_ARTIFACT_PROTOCOL)
        assert protocol is not None
        protocol.schema_sha256 = "sha256:" + "f" * 64

    with pytest.raises(RuntimeError, match=r"protocol version .* schema hash mismatch"):
        publisher.publish_bytes(**_publication_arguments())


@pytest.mark.parametrize("logical_name", ["nested//value.json", "nested/value.json/"])
def test_publication_rejects_noncanonical_member_path(
    tmp_path: Path,
    logical_name: str,
) -> None:
    publisher, _engine = _publisher(tmp_path)

    with pytest.raises(ControlPlaneError) as captured:
        publisher.publish_bytes(**{**_publication_arguments(), "logical_name": logical_name})

    assert captured.value.code == "CONTROL_ARTIFACT_INVALID"
    assert not list(publisher.settings.nas_artifact_root.iterdir())


def test_publication_request_persists_recovery_timestamp(tmp_path: Path) -> None:
    publisher, engine = _publisher(tmp_path)

    publisher.publish_bytes(**_publication_arguments())

    job = _job(engine)
    assert job.protocol_version == CONTROL_ARTIFACT_PROTOCOL
    assert job.request["created_at_utc"] == "2026-09-09T00:00:00Z"
    assert job.request_hash == content_sha256(
        {
            "protocol_version": job.protocol_version,
            "task_type": job.task_type,
            "request": job.request,
        }
    )


def test_successful_legacy_publication_remains_replayable(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    expected = publisher.publish_bytes(**_publication_arguments())
    with transaction(publisher.sessions) as session:
        job = session.execute(select(JobRecord).with_for_update()).scalar_one()
        legacy_request = {
            key: value for key, value in job.request.items() if key != "created_at_utc"
        }
        session.add(
            ProtocolVersionRecord(
                version=LEGACY_CONTROL_ARTIFACT_PROTOCOL,
                schema_sha256=content_sha256(
                    {
                        "protocol": LEGACY_CONTROL_ARTIFACT_PROTOCOL,
                        "contract": (
                            "one approved immutable member with schema, media type, and SHA-256"
                        ),
                    }
                ),
            )
        )
        job.protocol_version = LEGACY_CONTROL_ARTIFACT_PROTOCOL
        job.request = legacy_request
        job.request_hash = content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": legacy_request,
            }
        )
        revision = session.execute(select(ArtifactRevisionRecord).with_for_update()).scalar_one()
        revision.result = {
            "schema_version": "control-artifact-result/1.0",
            **legacy_request,
        }

    replay = publisher.publish_bytes(**_publication_arguments(source_commit="b" * 40))

    assert replay == expected


def test_nonterminal_legacy_publication_is_not_resumed(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    legacy_request = {key: value for key, value in _request().items() if key != "created_at_utc"}
    with transaction(publisher.sessions) as session:
        session.add(
            ProtocolVersionRecord(
                version=LEGACY_CONTROL_ARTIFACT_PROTOCOL,
                schema_sha256="sha256:" + "0" * 64,
            )
        )
        job, created = submit_structured_job(
            session,
            job_id="job_" + "1" * 32,
            protocol_version=LEGACY_CONTROL_ARTIFACT_PROTOCOL,
            idempotency_key=IDEMPOTENCY_KEY,
            task_type="control_test",
            request=legacy_request,
            logical_artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
        )
        assert created

    with pytest.raises(ControlPlaneError) as captured:
        publisher.publish_bytes(**_publication_arguments())

    assert captured.value.code == "CONTROL_ARTIFACT_CONFLICT"
    assert job.status == JobState.CREATED.value
