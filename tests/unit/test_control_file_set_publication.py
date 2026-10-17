from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from eom_identifiers import sha256_file
from eom_orchestrator import file_set_control_artifacts as publication
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
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


def test_first_observation_allocates_real_time_once_without_relaxing_fixed_replay(
    tmp_path: Path,
) -> None:
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path)
    arguments.pop("created_at")
    before = datetime.now(UTC)
    first = publisher.publish_first_observation(**arguments)
    after = datetime.now(UTC)
    assert publisher.publish_first_observation(**arguments) == first
    with publisher.sessions() as session:
        job = session.get(JobRecord, first.job_id)
        original_time = datetime.fromisoformat(job.request["created_at_utc"].replace("Z", "+00:00"))
        assert before <= original_time <= after
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
    assert publisher.publish(**arguments, created_at=original_time) == first
    with pytest.raises(ControlPlaneError):
        publisher.publish(**arguments, created_at=before)
    with pytest.raises(ControlPlaneError):
        publisher.publish_first_observation(**(arguments | {"source_commit": "c" * 40}))


@pytest.mark.parametrize("identified", [False, True])
def test_fixed_time_publication_none_never_selects_first_observation(tmp_path, identified):
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path) | {"created_at": None}
    with pytest.raises((ControlPlaneError, AttributeError, TypeError)):
        if identified:
            publisher.publish_identified(
                identity=ControlFileSetIdentity(
                    "job_" + "c" * 32, "artifact_" + "d" * 32, "rev_" + "e" * 32
                ),
                **arguments,
            )
        else:
            publisher.publish(**arguments)
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_identified_publication_preserves_allocation_and_legacy_replay(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    identity = ControlFileSetIdentity("job_" + "c" * 32, "artifact_" + "d" * 32, "rev_" + "e" * 32)
    arguments = _arguments(tmp_path)
    first = publisher.publish_identified(identity=identity, **arguments)
    assert (first.job_id, first.artifact_id, first.artifact_revision_id) == (
        identity.job_id,
        identity.artifact_id,
        identity.artifact_revision_id,
    )
    assert publisher.publish_identified(identity=identity, **arguments) == first
    assert publisher.publish(**arguments) == first
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1


@pytest.mark.parametrize("field", ["job_id", "artifact_id", "artifact_revision_id"])
def test_identified_publication_conflict_never_overwrites_allocation(
    tmp_path: Path, field: str
) -> None:
    publisher, _engine = _publisher(tmp_path)
    arguments = _arguments(tmp_path)
    first = publisher.publish(**arguments)
    values = {
        "job_id": first.job_id,
        "artifact_id": first.artifact_id,
        "artifact_revision_id": first.artifact_revision_id,
    }
    values[field] = values[field].split("_")[0] + "_" + "f" * 32
    with pytest.raises(ControlPlaneError, match="existing allocation differs"):
        publisher.publish_identified(identity=ControlFileSetIdentity(**values), **arguments)
    assert publisher.publish(**arguments) == first


@pytest.mark.parametrize("value", ["job_latest", "job_" + "A" * 32, "job_" + "a" * 31, True])
def test_identified_publication_requires_typed_immutable_identity(value: object) -> None:
    with pytest.raises(ControlPlaneError, match="publication identity is invalid"):
        ControlFileSetIdentity(value, "artifact_" + "d" * 32, "rev_" + "e" * 32)  # type: ignore[arg-type]


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


@pytest.mark.parametrize(
    "reference,accepted",
    (
        ("eom://schemas/test/value/1.0", True),
        ("eom://schemas/test/value/1.0#/$defs/value", True),
        ("eom://schemas/test/value/1.0#/$defs/workerResult_1", True),
        ("eom://schemas/test/value/1.0#/$defs/", False),
        ("eom://schemas/test/value/1.0#/properties/value", False),
        ("eom://schemas/test/value/1.0#/$defs/value/nested", False),
        ("eom://schemas/test/value/1.0#/$defs/a#/$defs/b", False),
        ("eom://schemas/test/value/1.0#/$defs/%76alue", False),
        ("https://example.test/schema#/$defs/value", False),
        ("eom://schemas/test/value/1.0#/$defs/value\n", False),
        ("eom://schemas/" + "x" * 220 + "#/$defs/" + "x" * 64, False),
    ),
)
def test_file_set_accepts_only_bounded_local_named_definition_fragments(
    tmp_path: Path, reference: str, accepted: bool
) -> None:
    publisher, engine = _publisher(tmp_path)
    source = tmp_path / "result.json"
    source.write_bytes(b"{}")
    source.chmod(0o600)
    member = ControlFileSetMember(
        "result.json", source, sha256_file(source), 2, reference, "application/json"
    )
    parameters = dict(
        members=(member,),
        primary_file="result.json",
        artifact_type="control_test_file_set",
        manifest_version="test-file-set/1.0",
        idempotency_key="synthetic-schema-fragment",
        source_commit="b" * 40,
        created_at=datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
    )
    if accepted:
        receipt = publisher.publish(**parameters)
        assert publisher.publish(**parameters) == receipt
    else:
        with pytest.raises(ControlPlaneError, match="file-set member is invalid"):
            publisher.publish(**parameters)
        with publisher.sessions() as session:
            assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
    engine.dispose()


def test_control_file_set_accepts_bounded_visual_output_scale(tmp_path: Path) -> None:
    publisher, _engine = _publisher(tmp_path)
    source_root = tmp_path / "visual-output-sources"
    source_root.mkdir()
    result = source_root / "result.json"
    result.write_bytes(b'{"status":"SUCCEEDED"}')
    result.chmod(0o600)
    image = source_root / "page.png"
    image.write_bytes(b"bounded-png-placeholder")
    image.chmod(0o600)
    members = [
        ControlFileSetMember(
            file_name="manifests/visual-pilot-result.json",
            source=result,
            sha256=sha256_file(result),
            bytes=result.stat().st_size,
            schema_ref="eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0",
            media_type="application/json",
        )
    ]
    for index in range(64):
        members.append(
            ControlFileSetMember(
                file_name=f"pages/document-{index:03d}/page-1.png",
                source=image,
                sha256=sha256_file(image),
                bytes=image.stat().st_size,
                schema_ref="eom://schemas/image-provider/local-image-science-corpus-visual-pilot-page-image/1.0",
                media_type="image/png",
            )
        )
    published = publisher.publish(
        members=tuple(sorted(members, key=lambda member: member.file_name)),
        primary_file="manifests/visual-pilot-result.json",
        artifact_type="control_local_image_science_visual_pilot_output",
        manifest_version="local-image-science-corpus-visual-pilot-files/1.0",
        idempotency_key="science-visual-pilot-result:" + "c" * 64,
        source_commit="d" * 40,
        created_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
    )

    manifest = Path(published.nas_path, "manifest.json")
    assert manifest.is_file()
    assert len(list(Path(published.nas_path, "pages").rglob("*.png"))) == 64
