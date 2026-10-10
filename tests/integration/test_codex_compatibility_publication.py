"""Synthetic execution proofs published only in a guarded disposable DB/local store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.codex_compatibility_policy import (
    COMPATIBILITY_ARTIFACT_TYPE,
    COMPATIBILITY_MANIFEST_VERSION,
    COMPATIBILITY_REPORT_SCHEMA,
    COMPATIBILITY_REQUEST_SCHEMA,
    COMPATIBILITY_RESULT_SCHEMA,
    load_committed_compatibility_report,
)
from eom_orchestrator.codex_compatibility_probe import synthetic_probe_png
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.codex_compatibility import (
    CodexCompatibilityCase,
    CodexCompatibilityCaseResult,
    CodexCompatibilityProbeResult,
    CodexCompatibilityReport,
    CodexCompatibilityRequest,
    CodexCompatibilityRuntime,
    compatibility_contract_sha256,
    compatibility_request_sha256,
    load_compatibility_report,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = pytest.mark.integration


def test_real_postgresql_publication_resolves_exact_canonical_compatibility_proofs(
    guarded_engine: Engine, tmp_path: Path
) -> None:
    # No worker, model, systemd, or production/NAS adapter is invoked: these are
    # synthetic proof bytes exercising the actual DB publication/read boundary.
    now = datetime.now(UTC).replace(microsecond=0)
    request = CodexCompatibilityRequest(
        run_id="codexcompat_" + uuid4().hex,
        source_commit="f" * 40,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        max_model_calls=2,
        cases=tuple(
            CodexCompatibilityCase(
                case_id="compatcase_" + uuid4().hex,
                slot_id=slot,
                binding_id="authbinding_" + uuid4().hex,
                assignment_revision_id=None,
                expected_resource_version=7,
                model="synthetic-model",
                reasoning_effort="medium",
            )
            for slot in ("01", "02")
        ),
    )
    request_hash = compatibility_request_sha256(request)
    image_hash = sha256_bytes(synthetic_probe_png())
    files: dict[str, tuple[bytes, str]] = {
        "request.json": (
            canonical_json_bytes(request.model_dump(mode="json")),
            COMPATIBILITY_REQUEST_SCHEMA,
        )
    }
    results = []
    for case in request.cases:
        execution_id = "job_" + uuid4().hex
        invocation_hash = content_sha256(
            {
                "schema_version": "codex-compatibility-invocation/1.0",
                "run_id": request.run_id,
                "case_id": case.case_id,
                "request_sha256": request_hash,
                "job_id": execution_id,
                "model": case.model,
                "reasoning_effort": case.reasoning_effort,
                "image_sha256": image_hash,
            }
        )
        output = CodexCompatibilityProbeResult(
            run_id=request.run_id,
            case_id=case.case_id,
            request_sha256=request_hash,
            arithmetic_sum=43,
            rectangle_count=1,
            outline_circle_count=1,
            left_shape="square",
            right_shape="circle",
        )
        payload = canonical_json_bytes(output.model_dump(mode="json"))
        files[f"{case.case_id}.output.json"] = (payload, COMPATIBILITY_RESULT_SCHEMA)
        results.append(
            CodexCompatibilityCaseResult(
                **case.model_dump(),
                job_id=execution_id,
                status="PASS",
                error_code=None,
                invocation_sha256=invocation_hash,
                result_sha256=sha256_bytes(payload),
                elapsed_ms=100,
            )
        )
    report = CodexCompatibilityReport(
        request=request,
        request_sha256=request_hash,
        started_at=now + timedelta(seconds=1),
        completed_at=now + timedelta(seconds=2),
        runtime=CodexCompatibilityRuntime(
            cli_version="0.160.0",
            cli_launcher_sha256="sha256:" + "a" * 64,
            cli_binary_sha256="sha256:" + "b" * 64,
            worker_exec_sha256="sha256:" + "c" * 64,
            contract_sha256=compatibility_contract_sha256(),
        ),
        model_calls=2,
        cases=tuple(results),
    )
    report_document = report.model_dump(mode="json")
    assert load_compatibility_report(report_document) == report
    files["report.json"] = (canonical_json_bytes(report_document), COMPATIBILITY_REPORT_SCHEMA)
    sources = tmp_path / "sources"
    sources.mkdir()
    members = []
    for name, (payload, schema) in sorted(files.items()):
        path = sources / name
        path.write_bytes(payload)
        path.chmod(0o600)
        members.append(
            ControlFileSetMember(
                name, path, sha256_bytes(payload), len(payload), schema, "application/json"
            )
        )
    local_store = tmp_path / "artifacts"
    local_store.mkdir()
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(staging_root=tmp_path / "staging", nas_artifact_root=local_store),
    )
    publication_arguments = {
        "members": tuple(members),
        "primary_file": "report.json",
        "artifact_type": COMPATIBILITY_ARTIFACT_TYPE,
        "manifest_version": COMPATIBILITY_MANIFEST_VERSION,
        "idempotency_key": request.run_id,
        "source_commit": request.source_commit,
        "created_at": report.completed_at,
    }
    published = publisher.publish(**publication_arguments)
    assert publisher.publish(**publication_arguments) == published
    assert Path(published.nas_path).is_relative_to(local_store)
    pointer = ArtifactMemberPointer(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path="report.json",
        schema_ref=COMPATIBILITY_REPORT_SCHEMA,
        media_type="application/json",
        sha256=published.primary_sha256,
    )
    # This uses PostgreSQL JSONB, real read-only transactions, full manifest
    # checks, and the real batch file resolver; no SQLite/resolver adaptation.
    assert load_committed_compatibility_report(guarded_engine, pointer) == report
    with Session(guarded_engine) as session:
        job = session.get(JobRecord, published.job_id)
        artifact = session.get(ArtifactRecord, published.artifact_id)
        revision = session.get(ArtifactRevisionRecord, published.artifact_revision_id)
        assert job is not None and artifact is not None and revision is not None
        assert job.status == "SUCCEEDED"
        assert artifact.approved and revision.approved
        assert job.request["members"] == revision.manifest["files"]
        assert revision.result == {"schema_version": "control-file-set-result/1.0", **job.request}
        assert revision.content_hash == pointer.sha256
        assert content_sha256(revision.manifest) == published.manifest_sha256
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == request.run_id)
            )
            == 1
        )
        # Binary/image/model output bytes remain in the local canonical store,
        # not in database metadata or a second serialized model-output payload.
        assert "arithmetic_sum" not in canonical_json_bytes(job.request).decode()
        assert "arithmetic_sum" not in canonical_json_bytes(revision.result).decode()
