from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from eom_identifiers import sha256_file
from eom_orchestrator import file_set_control_artifacts as publication
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    Base,
    JobEventRecord,
    JobRecord,
    ProtocolVersionRecord,
    WorkerSlotRecord,
)
from eom_orchestrator.settings import Settings
from sqlalchemy import BigInteger, Table, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type: JSONB, _compiler: object, **_kwargs: object) -> str:
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_big_integer_for_sqlite(_type: BigInteger, _compiler: object, **_kwargs: object) -> str:
    return "INTEGER"


def _publisher(tmp_path: Path) -> tuple[ControlFileSetPublisher, object]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'file-set.sqlite'}")
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
    nas = tmp_path / "nas"
    nas.mkdir()
    return (
        ControlFileSetPublisher(
            engine,
            Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas),
        ),
        engine,
    )


def _arguments(tmp_path: Path) -> dict[str, object]:
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    primary = sources / "result.json"
    image = sources / "output.png"
    primary.write_bytes(b'{"status":"SUCCEEDED"}')
    image.write_bytes(b"bounded-png-placeholder")
    primary.chmod(0o600)
    image.chmod(0o600)
    return {
        "members": (
            ControlFileSetMember(
                file_name="outputs/output.png",
                source=image,
                sha256=sha256_file(image),
                bytes=image.stat().st_size,
                schema_ref="eom://schemas/image-provider/local-image-output/1.0",
                media_type="image/png",
            ),
            ControlFileSetMember(
                file_name="result.json",
                source=primary,
                sha256=sha256_file(primary),
                bytes=primary.stat().st_size,
                schema_ref="eom://schemas/image-provider/local-image-result/1.0",
                media_type="application/json",
            ),
        ),
        "primary_file": "result.json",
        "artifact_type": "control_local_image_micro_evaluation",
        "manifest_version": "local-image-micro-evaluation-files/1.0",
        "idempotency_key": "local-image-micro-evaluation:" + "a" * 32,
        "source_commit": "b" * 40,
        "created_at": datetime(2026, 9, 25, 14, 0, tzinfo=UTC),
    }


def test_control_file_set_publication_is_idempotent_and_exact(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path)
    members = cast(tuple[ControlFileSetMember, ...], arguments["members"])
    primary = members[1].source
    image = members[0].source

    first = publisher.publish(**arguments)
    second = publisher.publish(**arguments)

    assert second == first
    assert Path(first.nas_path, "result.json").read_bytes() == primary.read_bytes()
    assert Path(first.nas_path, "outputs/output.png").read_bytes() == image.read_bytes()
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
        job = session.scalar(select(JobRecord))
        revision = session.scalar(select(ArtifactRevisionRecord))
        assert job is not None and revision is not None
        assert not _contains_bytes(job.request)
        assert not _contains_bytes(revision.result)
        assert revision.content_bytes == primary.stat().st_size


def _contains_bytes(value: object) -> bool:
    if isinstance(value, bytes):
        return True
    if isinstance(value, dict):
        return any(_contains_bytes(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_bytes(item) for item in value)
    return False


def test_control_file_set_recovers_after_nas_commit_before_database_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path)
    original = publication.create_artifact_records
    calls = 0

    def fail_once(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated database interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(publication, "create_artifact_records", fail_once)
    with pytest.raises(RuntimeError, match="simulated database interruption"):
        publisher.publish(**arguments)

    recovered = publisher.publish(**arguments)
    assert recovered.primary_file == "result.json"
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1


def test_control_file_set_rejects_same_key_with_different_input(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path)
    publisher.publish(**arguments)
    members = list(cast(tuple[ControlFileSetMember, ...], arguments["members"]))
    changed = members[0].source
    changed.write_bytes(b"different-png-placeholder")
    changed.chmod(0o600)
    members[0] = ControlFileSetMember(
        file_name=members[0].file_name,
        source=changed,
        sha256=sha256_file(changed),
        bytes=changed.stat().st_size,
        schema_ref=members[0].schema_ref,
        media_type=members[0].media_type,
    )

    with pytest.raises(ControlPlaneError, match="replay differs"):
        publisher.publish(**{**arguments, "members": tuple(members)})


def test_control_file_set_replay_rejects_manifest_identity_tamper(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path)
    publisher.publish(**arguments)
    with publisher.sessions.begin() as session:
        revision = session.scalar(select(ArtifactRevisionRecord))
        assert revision is not None
        revision.manifest = {**revision.manifest, "job_id": "job_" + "f" * 32}

    with pytest.raises(ControlPlaneError, match="published file set differs"):
        publisher.publish(**arguments)


def test_control_file_set_rejects_mutable_source_permissions(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path)
    member = cast(tuple[ControlFileSetMember, ...], arguments["members"])[0]
    member.source.chmod(0o666)
    with pytest.raises(ControlPlaneError, match="file-set member is invalid"):
        publisher.publish(**arguments)


def test_control_file_set_rejects_hash_drift(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    source = tmp_path / "result.json"
    source.write_bytes(b"{}")
    member = ControlFileSetMember(
        file_name="result.json",
        source=source,
        sha256="sha256:" + "0" * 64,
        bytes=2,
        schema_ref="eom://schemas/test/result/1.0",
        media_type="application/json",
    )

    try:
        publisher.publish(
            members=(member,),
            primary_file="result.json",
            artifact_type="control_test_file_set",
            manifest_version="test-file-set/1.0",
            idempotency_key="control-test-file-set:" + "0" * 32,
            source_commit="b" * 40,
            created_at=datetime(2026, 9, 25, 14, 0, tzinfo=UTC),
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "CONTROL_FILE_SET_INVALID"
    else:
        raise AssertionError("hash drift was accepted")
