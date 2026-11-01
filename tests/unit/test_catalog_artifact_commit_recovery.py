"""Interrupt the actual owner before/after NAS publication and replay the same Job."""

from pathlib import Path

import pytest
from eom_catalog_service import artifacts as publication
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256, sha256_file
from eom_orchestrator.database import transaction
from eom_orchestrator.models import ArtifactRevisionRecord, JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, record_job_observation, transition_job
from eom_protocol.artifact_commit_intent import CatalogArtifactRecoveryBasis
from sqlalchemy import func, select

from tests.unit.test_control_file_set_publication import _publisher


@pytest.fixture
def catalog_service(tmp_path):
    publisher, engine = _publisher(tmp_path)
    return CatalogArtifactService(
        engine,
        CatalogSettings(
            staging_root=tmp_path / "catalog-staging",
            nas_artifact_root=publisher.settings.nas_artifact_root,
        ),
    )


def arguments(tmp_path):
    source = tmp_path / "payload.json"
    source.write_bytes(b'{"status":"ok"}')
    return dict(
        files={"payload.json": source},
        primary_file="payload.json",
        artifact_type="catalog-commit-recovery-test",
        idempotency_key="recovery:" + content_sha256({"fixture_root": str(tmp_path)}),
        request={"source_sha256": sha256_file(source)},
        result={"status": "ok"},
        file_metadata={
            "payload.json": {
                "schema_ref": "eom://schemas/test/recovery/1.0",
                "media_type": "application/json",
            }
        },
        expected_file_sha256={"payload.json": sha256_file(source)},
    )


def basis(_session, _job):
    return CatalogArtifactRecoveryBasis(
        kind="PINNED_KNOWLEDGE_ACCEPTANCE",
        actor_id="operator_" + "a" * 32,
        source_basis_sha256="sha256:" + "b" * 64,
    )


def interrupt(service, args, monkeypatch, *, after_nas=False):
    original = (
        publication.create_artifact_records if after_nas else publication.commit_file_set_artifact
    )
    name = "create_artifact_records" if after_nas else "commit_file_set_artifact"

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic publication interruption")

    with monkeypatch.context() as patch:
        patch.setattr(publication, name, fail)
        with pytest.raises(RuntimeError, match="synthetic publication interruption"):
            service.commit_file_set(**args)
    assert getattr(publication, name) is original
    with service.sessions() as session:
        job = session.scalar(
            select(JobRecord).where(JobRecord.idempotency_key == args["idempotency_key"])
        )
        assert job.status == "COMMITTING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == job.job_id)
            )
            == 0
        )
        return job


@pytest.mark.parametrize("after_nas", [False, True])
def test_original_sealed_job_replays_after_interruption(
    catalog_service, tmp_path, monkeypatch, after_nas
):
    service = catalog_service
    args = arguments(tmp_path)
    job = interrupt(service, args, monkeypatch, after_nas=after_nas)
    with service.sessions() as session:
        before = service._commit_intent(session, job.job_id)
        original_events = tuple(
            (e.sequence, e.event, e.from_state, e.to_state, e.data)
            for e in session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
    assert before is not None
    saved = service.commit_file_set(**args)
    assert service.commit_file_set(**args) == saved
    assert (saved.job_id, saved.artifact_id, saved.revision_id) == (
        job.job_id,
        job.logical_artifact_id,
        job.revision_id,
    )
    assert saved.manifest_hash == before.manifest_sha256
    assert saved.manifest["created_at"] == before.manifest_created_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert Path(saved.nas_path, "payload.json").read_bytes() == b'{"status":"ok"}'
    with service.sessions() as session:
        events = tuple(
            (e.sequence, e.event, e.from_state, e.to_state, e.data)
            for e in session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        assert events[:-1] == original_events
        assert events[-1][1] == "CATALOG_ARTIFACT_COMMITTED"
        assert session.get(JobRecord, job.job_id).status == "SUCCEEDED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == args["idempotency_key"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == job.job_id)
            )
            == 1
        )
    assert not tuple((service.settings.staging_root / job.job_id).iterdir())


@pytest.mark.parametrize("change", ["bytes", "result", "schema", "expected_hash"])
def test_sealed_recovery_rejects_changed_material(catalog_service, tmp_path, monkeypatch, change):
    args = arguments(tmp_path)
    job = interrupt(catalog_service, args, monkeypatch)
    if change == "bytes":
        args["files"]["payload.json"].write_bytes(b"different")
        args["expected_file_sha256"] = {"payload.json": sha256_file(args["files"]["payload.json"])}
    elif change == "result":
        args["result"] = {"status": "different"}
    elif change == "schema":
        args["file_metadata"]["payload.json"]["schema_ref"] = "eom://schemas/test/recovery/2.0"
    else:
        args["expected_file_sha256"] = {"payload.json": "sha256:" + "0" * 64}
    with pytest.raises(ValueError):
        catalog_service.commit_file_set(**args)
    assert not (
        catalog_service.settings.nas_artifact_root / job.logical_artifact_id / job.revision_id
    ).exists()
    with catalog_service.sessions() as session:
        assert session.get(JobRecord, job.job_id).status == "COMMITTING"


def unseal_fixture(service, job):
    # Only disposable fixture setup simulates the pre-upgrade, empty COMMITTING event.
    with service.sessions.begin() as session:
        event = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == job.job_id,
                JobEventRecord.event == "CATALOG_ARTIFACT_COMMITTING",
            )
        )
        event.data = {}


def test_legacy_absent_destination_requires_current_owner_proof(
    catalog_service, tmp_path, monkeypatch
):
    args = arguments(tmp_path)
    job = interrupt(catalog_service, args, monkeypatch)
    unseal_fixture(catalog_service, job)
    with pytest.raises(RuntimeError, match="AUTHORITY_REQUIRED"):
        catalog_service.commit_file_set(**args)
    saved = catalog_service.commit_file_set(**args, recovery_authorizer=basis)
    assert saved.job_id == job.job_id and saved.revision_id == job.revision_id
    with catalog_service.sessions() as session:
        intent = catalog_service._commit_intent(session, job.job_id)
        assert intent.recovery_basis == basis(None, None)
        event = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == job.job_id,
                JobEventRecord.event == "CATALOG_ARTIFACT_COMMIT_RECONSTRUCTED",
            )
        )
        assert event.from_state == event.to_state == "COMMITTING"


def test_unsealed_existing_nas_is_never_adopted(catalog_service, tmp_path, monkeypatch):
    args = arguments(tmp_path)
    job = interrupt(catalog_service, args, monkeypatch, after_nas=True)
    unseal_fixture(catalog_service, job)
    with pytest.raises(RuntimeError, match="EXISTING_UNSEALED_DESTINATION"):
        catalog_service.commit_file_set(**args, recovery_authorizer=basis)
    with catalog_service.sessions() as session:
        assert session.get(JobRecord, job.job_id).status == "COMMITTING"
        assert catalog_service._commit_intent(session, job.job_id) is None


def test_authority_withdrawal_after_nas_does_not_promote_revision(
    catalog_service, tmp_path, monkeypatch
):
    args = arguments(tmp_path)
    job = interrupt(catalog_service, args, monkeypatch)
    unseal_fixture(catalog_service, job)
    original = publication.commit_file_set_artifact
    revoked = False

    def commit_then_revoke(*values):
        nonlocal revoked
        final = original(*values)
        revoked = True
        return final

    def authorize(session, row):
        if revoked:
            raise RuntimeError("owner proof revoked")
        return basis(session, row)

    with monkeypatch.context() as patch:
        patch.setattr(publication, "commit_file_set_artifact", commit_then_revoke)
        with pytest.raises(RuntimeError, match="owner proof revoked"):
            catalog_service.commit_file_set(**args, recovery_authorizer=authorize)
    with catalog_service.sessions() as session:
        assert session.get(JobRecord, job.job_id).status == "COMMITTING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == job.job_id)
            )
            == 0
        )
        assert catalog_service._commit_intent(session, job.job_id).recovery_basis == basis(
            None, None
        )
    with pytest.raises(RuntimeError, match="AUTHORITY_REQUIRED"):
        catalog_service.commit_file_set(**args)
    assert catalog_service.commit_file_set(**args, recovery_authorizer=basis).job_id == job.job_id


def test_observation_requires_current_expected_state(catalog_service, tmp_path):
    args = arguments(tmp_path)
    saved = catalog_service.commit_file_set(**args)
    with (
        pytest.raises(RuntimeError, match="JOB_OBSERVATION_STATE_CHANGED"),
        transaction(catalog_service.sessions) as session,
    ):
        record_job_observation(
            session, saved.job_id, "SHOULD_NOT_APPEND", expected_state=JobState.COMMITTING, data={}
        )
    with catalog_service.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == saved.job_id,
                    JobEventRecord.event == "SHOULD_NOT_APPEND",
                )
            )
            == 0
        )


def test_committed_intent_must_match_registry_and_result(catalog_service, tmp_path):
    args = arguments(tmp_path)
    saved = catalog_service.commit_file_set(**args)
    with pytest.raises(ValueError, match="INTENT_MISMATCH"):
        catalog_service.commit_file_set(**(args | {"result": {"different": True}}))
    with catalog_service.sessions.begin() as session:
        revision = session.get(ArtifactRevisionRecord, saved.revision_id)
        revision.result = {"different": True}
    with pytest.raises(ValueError, match="INTENT_MISMATCH"):
        catalog_service.commit_file_set(**args)


@pytest.mark.parametrize("state", [JobState.FAILED, JobState.CANCELLED, JobState.VALIDATED])
def test_other_states_and_terminal_history_are_never_reinterpreted(
    catalog_service, tmp_path, state
):
    args = arguments(tmp_path)
    wrong = {"payload.json": "sha256:" + "0" * 64}
    with pytest.raises(ValueError):
        catalog_service.commit_file_set(**(args | {"expected_file_sha256": wrong}))
    with catalog_service.sessions.begin() as session:
        job = session.scalar(
            select(JobRecord).where(JobRecord.idempotency_key == args["idempotency_key"])
        )
        transition_job(session, job.job_id, state, "SYNTHETIC_PRIOR_HISTORY")
        job_id = job.job_id
    with pytest.raises(RuntimeError, match="job is incomplete"):
        catalog_service.commit_file_set(**args, recovery_authorizer=basis)
    with catalog_service.sessions() as session:
        assert session.get(JobRecord, job_id).status == state.value
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == job_id)
            )
            == 0
        )
