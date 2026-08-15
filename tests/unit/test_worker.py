from datetime import UTC, datetime

from eom_orchestrator.settings import Settings
from eom_orchestrator.worker import CodexWorkerAdapter, worker_output_schema
from eom_orchestrator.worker_registry import WorkerSlot
from eom_protocol import ArtifactSpec, SmokePayload, WorkerInput


def test_worker_output_schema_constrains_all_input_identifiers() -> None:
    worker_input = WorkerInput(
        job_id="job_0123456789abcdef0123456789abcdef",
        payload=SmokePayload(message="EOM_PLATFORM_SMOKE_TEST"),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_0123456789abcdef0123456789abcdef",
            revision_id="rev_0123456789abcdef0123456789abcdef",
        ),
        submitted_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    schema = worker_output_schema(worker_input)
    properties = schema["properties"]
    assert properties["job_id"]["const"] == worker_input.job_id
    artifact = properties["artifact"]["properties"]
    assert artifact["logical_artifact_id"]["const"] == worker_input.artifact.logical_artifact_id
    assert artifact["revision_id"]["const"] == worker_input.artifact.revision_id


def test_worker_command_confines_orchestrator_owned_paths() -> None:
    settings = Settings()
    adapter = CodexWorkerAdapter(settings)
    argv = adapter._argv(
        workspace=settings.workspace_root / "eom-cdx-01" / "job_test",
        schema_path=settings.workspace_root / "schema.json",
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        unit_name="eom-worker-test",
    )
    for path in (
        "/mnt/nas",
        "/var/run/docker.sock",
        "/home/eom/EOM",
        "/etc/eom",
        "/srv/eom/staging",
    ):
        assert f"--property=InaccessiblePaths={path}" in argv
    assert "--sandbox" in argv
    assert "read-only" in argv
