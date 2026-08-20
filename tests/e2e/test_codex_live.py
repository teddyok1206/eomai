from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from eom_identifiers import sha256_file
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.live_preflight import run_live_worker_preflight
from eom_orchestrator.models import ArtifactRevisionRecord, JobEventRecord, JobRecord
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.settings import Settings
from eom_protocol import ArtifactManifest, WorkerResult, validate_message
from sqlalchemy import select

pytestmark = [pytest.mark.integration, pytest.mark.codex_live]


def test_real_codex_job_committed_to_nas() -> None:
    if os.environ.get("EOM_RUN_CODEX_LIVE") != "1":
        pytest.skip("set EOM_RUN_CODEX_LIVE=1 to run the live Codex E2E test")

    engine = build_engine()
    job_id = os.environ.get("EOM_LIVE_JOB_ID")
    if job_id is None:
        settings = Settings.from_environment()
        preflight = run_live_worker_preflight(settings)
        assert preflight.ready, {
            "failed_codes": preflight.failed_codes,
            "checks": [check.as_dict() for check in preflight.checks],
        }
        submitted_job = Orchestrator(engine, settings).submit("EOM_PLATFORM_SMOKE_TEST")
        job_id = submitted_job.job_id

    sessions = build_session_factory(engine)
    with sessions() as session:
        job_record = session.get(JobRecord, job_id)
        assert job_record is not None
        revision = session.get(ArtifactRevisionRecord, job_record.revision_id)
        assert revision is not None
        events = list(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        assert job_record.status == "SUCCEEDED"
        assert job_record.worker_slot_id == "01"
        assert job_record.worker_exit_code == 0
        assert [event.to_state for event in events] == [
            "CREATED",
            "VALIDATED",
            "QUEUED",
            "CLAIMED",
            "RUNNING",
            "VALIDATING_RESULT",
            "COMMITTING",
            "SUCCEEDED",
        ]
        final = Path(revision.nas_path)
        result = json.loads((final / "result.json").read_text(encoding="utf-8"))
        manifest = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        validate_message("worker-result", result)
        validate_message("artifact-manifest", manifest)
        assert sha256_file(final / "result.json") == revision.content_hash
        assert sha256_file(final / "manifest.json") == revision.manifest_hash
        assert WorkerResult.model_validate(revision.result) == WorkerResult.model_validate(result)
        assert ArtifactManifest.model_validate(
            revision.manifest
        ) == ArtifactManifest.model_validate(manifest)
    engine.dispose()
