from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eom_hwpx_contracts import KordocExpectedStructure, KordocSourcePointer
from eom_hwpx_manager.adapter import BuilderRun, HwpxBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError
from eom_hwpx_manager.kordoc_service import KordocHwpxService
from eom_hwpx_manager.models import HwpxBuildRecord, HwpxTemplateRevisionRecord
from eom_hwpx_manager.repository import (
    add_template_revision,
    add_validation,
    create_build,
    get_or_create_template,
    transition_build,
)
from eom_hwpx_manager.service import HwpxService
from eom_hwpx_manager.settings import HwpxSettings
from eom_hwpx_manager.state_machine import HwpxBuildState
from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
    sha256_bytes,
    sha256_file,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration


def _artifact_job(
    session: Session,
    key: str,
    *,
    nas_path: str | None = None,
    content_hash: str = "sha256:" + "a" * 64,
    manifest: dict[str, Any] | None = None,
) -> JobRecord:
    ensure_protocol_version(session, "hwpx-test/1.0", "sha256:" + "f" * 64)
    job, _ = submit_structured_job(
        session,
        job_id=new_job_id(),
        protocol_version="hwpx-test/1.0",
        idempotency_key=key,
        task_type="hwpx-test",
        request={"placeholder": True},
        logical_artifact_id=new_logical_artifact_id(),
        revision_id=new_revision_id(),
    )
    for state in (
        JobState.VALIDATED,
        JobState.QUEUED,
        JobState.CLAIMED,
        JobState.RUNNING,
        JobState.VALIDATING_RESULT,
        JobState.COMMITTING,
    ):
        transition_job(session, job.job_id, state, f"TEST_{state.value}")
    create_artifact_records(
        session,
        job=job,
        content_hash=content_hash,
        manifest_hash="sha256:" + "b" * 64,
        content_bytes=10,
        nas_path=nas_path or f"/tmp/{job.logical_artifact_id}/{job.revision_id}",
        manifest=manifest or {"placeholder": True},
        result={"placeholder": True},
    )
    transition_job(session, job.job_id, JobState.SUCCEEDED, "TEST_COMMITTED")
    session.flush()
    return job


class _FakeBuilderAdapter(HwpxBuilderAdapter):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.run_count = 0

    def create_workspace(self, workspace_id: str) -> Path:
        workspace = self.root / workspace_id
        workspace.mkdir()
        return workspace

    def stage_file(self, workspace: Path, relative_path: str, source: Path) -> Path:
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target

    def write_json(self, workspace: Path, relative_path: str, value: dict[str, Any]) -> Path:
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding="utf-8")
        return target

    def run(
        self, workspace: Path, operation: str, arguments: list[str], log_root: Path
    ) -> BuilderRun:
        assert operation == "render"
        assert arguments == ["--request", "request.json", "--result", "result.json"]
        self.run_count += 1
        request = json.loads((workspace / "request.json").read_text())
        document = json.loads((workspace / "input/document.json").read_text())
        output_root = workspace / "output"
        output_root.mkdir()
        output = output_root / "placeholder_item_combined.hwpx"
        output.write_bytes(b"SYNTHETIC_INTEGRATION_HWPX")
        for name, value in (
            ("package-manifest.json", {"manifest_version": "1.0"}),
            ("structural-validation.json", {"status": "PASS"}),
            ("semantic-validation.json", {"status": "PASS"}),
        ):
            (output_root / name).write_text(json.dumps(value), encoding="utf-8")
        result = {
            "schema_version": "1.0",
            "build_id": request["build_id"],
            "template_id": request["template_id"],
            "template_revision_id": request["template_revision_id"],
            "input_sha256": content_sha256(document),
            "renderer_version": "0.1.0",
            "status": "PENDING_MANUAL_HANCOM_VALIDATION",
            "output_file": "output/placeholder_item_combined.hwpx",
            "output_sha256": sha256_file(output),
            "package_manifest_file": "output/package-manifest.json",
            "validation_report_file": "output/structural-validation.json",
            "semantic_report_file": "output/semantic-validation.json",
            "warnings": [],
            "errors": [],
            "started_at": "2026-08-15T00:00:00Z",
            "completed_at": "2026-08-15T00:00:01Z",
        }
        (workspace / "result.json").write_text(json.dumps(result), encoding="utf-8")
        log_root.mkdir(parents=True, exist_ok=True)
        stdout = log_root / "stdout.log"
        stderr = log_root / "stderr.log"
        stdout.write_bytes(b"")
        stderr.write_bytes(b"")
        return BuilderRun(0, workspace, stdout, stderr, "fake-hwpx-builder")

    load_json = staticmethod(HwpxBuilderAdapter.load_json)


class _FakeKordocBuilderAdapter(_FakeBuilderAdapter):
    def run(
        self, workspace: Path, operation: str, arguments: list[str], log_root: Path
    ) -> BuilderRun:
        assert operation == "render-kordoc"
        assert arguments == ["--request", "request.json", "--result", "result.json"]
        self.run_count += 1
        request = json.loads((workspace / "request.json").read_text())
        output_root = workspace / "output"
        output_root.mkdir()
        output = output_root / "kordoc_document.hwpx"
        output.write_bytes(b"SYNTHETIC_KORDOC_HWPX")
        for name, value in (
            ("package-manifest.json", {"manifest_version": "1.0"}),
            ("structural-validation.json", {"status": "PASS"}),
            ("kordoc-validation.json", {"validation_ok": True, "parse_success": True}),
        ):
            (output_root / name).write_text(json.dumps(value), encoding="utf-8")
        expected = request["expected_structure"]
        result = {
            "schema_version": "1.0",
            "renderer_profile": "kordoc-markdown-v1",
            "build_id": request["build_id"],
            "source_artifact_id": request["source"]["artifact_id"],
            "source_artifact_revision_id": request["source"]["artifact_revision_id"],
            "source_sha256": request["source"]["sha256"],
            "renderer_version": "0.1.0",
            "kordoc_version": "4.9.0",
            "status": "PENDING_MANUAL_HANCOM_VALIDATION",
            "output_file": "output/kordoc_document.hwpx",
            "output_sha256": sha256_file(output),
            "package_manifest_file": "output/package-manifest.json",
            "validation_report_file": "output/structural-validation.json",
            "renderer_report_file": "output/kordoc-validation.json",
            "native_equation_count": expected["display_equation_count"],
            "native_table_count": expected["table_count"],
            "warnings": [],
            "errors": [],
            "started_at": "2026-08-21T00:00:00Z",
            "completed_at": "2026-08-21T00:00:01Z",
        }
        (workspace / "result.json").write_text(json.dumps(result), encoding="utf-8")
        log_root.mkdir(parents=True, exist_ok=True)
        stdout = log_root / "stdout.log"
        stderr = log_root / "stderr.log"
        stdout.write_bytes(b"")
        stderr.write_bytes(b"")
        return BuilderRun(0, workspace, stdout, stderr, "fake-kordoc-builder")


def test_hwpx_template_build_idempotency_transition_validation_and_immutability(
    db_session: Session,
) -> None:
    source_job = _artifact_job(db_session, "hwpx-template-artifact-test")
    template = get_or_create_template(
        db_session,
        template_id="hwpxtpl_" + "1" * 32,
        logical_name="placeholder-item-integration",
        description="PLACEHOLDER template",
    )
    revision = add_template_revision(
        db_session,
        template_revision_id="hwpxrev_" + "2" * 32,
        template=template,
        source_artifact_id=source_job.logical_artifact_id,
        source_artifact_revision_id=source_job.revision_id,
        source_sha256="sha256:" + "a" * 64,
        binding_manifest_sha256="sha256:" + "c" * 64,
        owpml_version="synthetic-poc",
        hancom_version="TEST_ONLY",
        package_profile={"synthetic": True},
        analysis_summary={"entries": 1},
    )
    build_job = _artifact_job(db_session, "hwpx-build-artifact-test")
    build, created = create_build(
        db_session,
        build_id="hwpxbuild_" + "3" * 32,
        template_revision_id=revision.template_revision_id,
        platform_job_id=build_job.job_id,
        input_payload={"schema_version": "1.0", "placeholder": True},
        renderer_version="0.1.0",
        idempotency_key="hwpx-integration-idempotency",
    )
    assert created
    duplicate, duplicate_created = create_build(
        db_session,
        build_id="hwpxbuild_" + "4" * 32,
        template_revision_id=revision.template_revision_id,
        platform_job_id=build_job.job_id,
        input_payload={"schema_version": "1.0", "placeholder": True},
        renderer_version="0.1.0",
        idempotency_key="hwpx-integration-idempotency",
    )
    assert not duplicate_created
    assert duplicate.build_id == build.build_id
    with pytest.raises(HwpxManagerError, match="conflicts"):
        create_build(
            db_session,
            build_id="hwpxbuild_" + "5" * 32,
            template_revision_id=revision.template_revision_id,
            platform_job_id=build_job.job_id,
            input_payload={"schema_version": "1.0", "placeholder": False},
            renderer_version="0.1.0",
            idempotency_key="hwpx-integration-idempotency",
        )

    for target in (
        HwpxBuildState.VALIDATING_INPUT,
        HwpxBuildState.STAGING,
        HwpxBuildState.RENDERING,
        HwpxBuildState.PACKAGING,
        HwpxBuildState.VALIDATING_OUTPUT,
        HwpxBuildState.COMMITTING,
        HwpxBuildState.PENDING_MANUAL_VALIDATION,
    ):
        transition_build(db_session, build, target)
    validation = add_validation(
        db_session,
        build_id=build.build_id,
        validation_type="STRUCTURAL",
        status="PASS",
        validator_version="0.1.0",
        artifact_id=source_job.logical_artifact_id,
        revision_id=source_job.revision_id,
    )
    assert validation.status == "PASS"
    assert build.completed_at is not None

    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        stored = db_session.get(HwpxTemplateRevisionRecord, revision.template_revision_id)
        assert stored is not None
        stored.hancom_version_declared = "MUTATED"
        db_session.flush()


def test_hwpx_build_failure_transition_records_terminal_timestamp(db_session: Session) -> None:
    source_job = _artifact_job(db_session, "hwpx-template-failure-artifact-test")
    template = get_or_create_template(
        db_session,
        template_id="hwpxtpl_" + "6" * 32,
        logical_name="placeholder-item-failure",
        description="PLACEHOLDER template",
    )
    revision = add_template_revision(
        db_session,
        template_revision_id="hwpxrev_" + "7" * 32,
        template=template,
        source_artifact_id=source_job.logical_artifact_id,
        source_artifact_revision_id=source_job.revision_id,
        source_sha256="sha256:" + "d" * 64,
        binding_manifest_sha256="sha256:" + "e" * 64,
        owpml_version="synthetic-poc",
        hancom_version="TEST_ONLY",
        package_profile={},
        analysis_summary={},
    )
    build_job = _artifact_job(db_session, "hwpx-build-failure-job-test")
    build, _ = create_build(
        db_session,
        build_id="hwpxbuild_" + "8" * 32,
        template_revision_id=revision.template_revision_id,
        platform_job_id=build_job.job_id,
        input_payload={"placeholder": True},
        renderer_version="0.1.0",
        idempotency_key="hwpx-failure-idempotency",
    )
    transition_build(db_session, build, HwpxBuildState.FAILED)
    assert build.status == "FAILED"
    assert build.completed_at is not None
    assert build.completed_at <= datetime.now(UTC)


def test_hwpx_service_build_validates_commits_and_reuses_idempotent_result(
    db_session: Session, integration_engine: Engine, tmp_path: Path
) -> None:
    template_root = tmp_path / "template-artifact"
    template_root.mkdir()
    (template_root / "template.hwpx").write_bytes(b"SYNTHETIC_TEMPLATE")
    (template_root / "template-bindings.json").write_text("{}", encoding="utf-8")
    source_job = _artifact_job(
        db_session,
        "hwpx-service-template-artifact-test",
        nas_path=str(template_root),
        content_hash=sha256_file(template_root / "template.hwpx"),
    )
    source_revision = db_session.get(ArtifactRevisionRecord, source_job.revision_id)
    assert source_revision is not None
    template = get_or_create_template(
        db_session,
        template_id="hwpxtpl_" + "9" * 32,
        logical_name="placeholder-item-service",
        description="PLACEHOLDER template",
    )
    revision = add_template_revision(
        db_session,
        template_revision_id="hwpxrev_" + "a" * 32,
        template=template,
        source_artifact_id=source_job.logical_artifact_id,
        source_artifact_revision_id=source_job.revision_id,
        source_sha256=source_revision.content_hash,
        binding_manifest_sha256="sha256:" + "b" * 64,
        owpml_version="synthetic-poc",
        hancom_version="TEST_ONLY",
        package_profile={"synthetic": True},
        analysis_summary={},
    )
    image = tmp_path / "eom-placeholder-image-output.png"
    image.write_bytes(b"SYNTHETIC_PNG_BYTES")
    document = {
        "schema_version": "1.0",
        "document_id": "placeholder-document-v1",
        "document_title": "PLACEHOLDER DOCUMENT",
        "item": {
            "item_number": "1",
            "upper_stem": "PLACEHOLDER UPPER STEM",
            "lower_stem": "PLACEHOLDER LOWER STEM",
            "table": {
                "rows": [
                    ["PLACEHOLDER R1C1", "PLACEHOLDER R1C2", "PLACEHOLDER R1C3"],
                    ["PLACEHOLDER R2C1", "PLACEHOLDER R2C2", "PLACEHOLDER R2C3"],
                ]
            },
            "image": {
                "source_path": image.name,
                "media_type": "image/png",
                "sha256": sha256_bytes(image.read_bytes()),
                "expected_width_px": 800,
                "expected_height_px": 500,
            },
            "equation": {"source_format": "hancom-equation-script", "source": "x+y=z"},
            "statements": {
                "giyeok": "PLACEHOLDER STATEMENT GIYEOK",
                "nieun": "PLACEHOLDER STATEMENT NIEUN",
                "digeut": "PLACEHOLDER STATEMENT DIGEUT",
            },
            "choices": [f"PLACEHOLDER CHOICE {index}" for index in range(1, 6)],
            "points": "2",
        },
        "solution": {
            "answer": "1",
            "authoring_intent": "PLACEHOLDER AUTHORING INTENT",
            "overview": "PLACEHOLDER SOLUTION OVERVIEW",
            "statement_explanations": {
                "giyeok": "PLACEHOLDER EXPLANATION GIYEOK",
                "nieun": "PLACEHOLDER EXPLANATION NIEUN",
                "digeut": "PLACEHOLDER EXPLANATION DIGEUT",
            },
        },
    }
    document_path = tmp_path / "document.json"
    document_path.write_text(json.dumps(document), encoding="utf-8")
    nas_root = tmp_path / "nas"
    nas_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    staging_root = tmp_path / "staging"
    settings = HwpxSettings(
        workspace_root=workspace_root,
        staging_root=staging_root,
        nas_artifact_root=nas_root,
    )
    adapter = _FakeBuilderAdapter(workspace_root)
    service = HwpxService(integration_engine, settings, adapter=adapter)
    service.sessions = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    build = service.build(revision.template_revision_id, document_path, "hwpx-service-build-key")
    assert build.status == "PENDING_MANUAL_VALIDATION"
    assert build.output_sha256 == sha256_bytes(b"SYNTHETIC_INTEGRATION_HWPX")
    assert build.output_artifact_id is not None
    final = nas_root / build.output_artifact_id / str(build.output_artifact_revision_id)
    assert (final / "placeholder_item_combined.hwpx").is_file()
    assert (final / "structural-validation.json").is_file()
    assert len(service.build_validations(build.build_id)) == 2
    duplicate = service.build(
        revision.template_revision_id, document_path, "hwpx-service-build-key"
    )
    assert duplicate.build_id == build.build_id
    assert adapter.run_count == 1

    (template_root / "template-bindings.json").unlink()
    with pytest.raises(OSError):
        service.build(revision.template_revision_id, document_path, "hwpx-staging-failure-key")
    failed = db_session.scalar(
        select(HwpxBuildRecord).where(HwpxBuildRecord.idempotency_key == "hwpx-staging-failure-key")
    )
    assert failed is not None
    assert failed.status == "FAILED"
    assert failed.failure_code == "HWPX_BUILDER_FAILED"
    failed_job = db_session.get(JobRecord, failed.platform_job_id)
    assert failed_job is not None
    assert failed_job.status == "FAILED"


def test_kordoc_service_pins_source_and_reuses_immutable_result(
    db_session: Session, integration_engine: Engine, tmp_path: Path
) -> None:
    source_root = tmp_path / "markdown-artifact"
    source_root.mkdir()
    source_path = source_root / "document.md"
    source_path.write_text("# 문항\n\n$$E=mc^2$$\n", encoding="utf-8")
    source_hash = sha256_file(source_path)
    source_job = _artifact_job(
        db_session,
        "kordoc-source-artifact-test",
        nas_path=str(source_root),
        content_hash=source_hash,
        manifest={"primary_file": "document.md"},
    )
    pointer = KordocSourcePointer(
        artifact_id=source_job.logical_artifact_id,
        artifact_revision_id=source_job.revision_id,
        sha256=source_hash,
    )
    nas_root = tmp_path / "kordoc-nas"
    nas_root.mkdir()
    workspace_root = tmp_path / "kordoc-workspaces"
    workspace_root.mkdir()
    staging_root = tmp_path / "kordoc-staging"
    settings = HwpxSettings(
        workspace_root=workspace_root,
        staging_root=staging_root,
        nas_artifact_root=nas_root,
    )
    adapter = _FakeKordocBuilderAdapter(workspace_root)
    service = KordocHwpxService(integration_engine, settings, adapter=adapter)
    service.sessions = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    expected = KordocExpectedStructure(display_equation_count=1, table_count=0)

    receipt = service.build(
        source_path,
        pointer,
        expected,
        idempotency_key="kordoc-service-build-key",
    )
    duplicate = service.build(
        source_path,
        pointer,
        expected,
        idempotency_key="kordoc-service-build-key",
    )

    assert receipt == duplicate
    assert receipt.status == "SUCCEEDED"
    assert receipt.output_sha256 == sha256_bytes(b"SYNTHETIC_KORDOC_HWPX")
    assert adapter.run_count == 1
    final = nas_root / receipt.artifact_id / receipt.artifact_revision_id
    assert (final / "kordoc_document.hwpx").read_bytes() == b"SYNTHETIC_KORDOC_HWPX"
    revision = db_session.get(ArtifactRevisionRecord, receipt.artifact_revision_id)
    assert revision is not None
    assert revision.content_bytes == len(b"SYNTHETIC_KORDOC_HWPX")
    assert "SYNTHETIC_KORDOC_HWPX" not in json.dumps(revision.result)
