"""Real disposable DB/local Artifact publication and opt-in installed rendering.

Native bytes and independent acceptance are exercised by tests/hwpx. Here the
focus is immutable planned IDs, one dispatch, crash recovery and FD download.
The separate opt-in case uses actual mixed render bytes and independent acceptance.
No model, GPU, production database or production NAS is used.
"""

import os
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_hwpx_contracts.curated_build import (
    CuratedArtifactMember,
    CuratedHwpxBuildInput,
    CuratedNativeDocumentInput,
)
from eom_hwpx_contracts.curated_mixed import (
    CuratedMixedRenderRequest,
    CuratedMixedRenderResult,
    CuratedNativeSegment,
)
from eom_hwpx_manager.curated_application_service import CuratedBuildPending
from eom_hwpx_manager.curated_materialization import CuratedMaterialization
from eom_hwpx_manager.curated_output_acceptance import CuratedOutputAcceptance
from eom_hwpx_manager.curated_service import CuratedHwpxService
from eom_hwpx_manager.errors import HwpxManagerError
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import func, select

from tests.integration.test_catalog_artifact_created_recovery import _settings
from tests.unit.test_curated_hwpx_build import build_record

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


class _Crash(BaseException):
    pass


@pytest.fixture
def publication(creative_engine, tmp_path, monkeypatch):
    suffix = uuid4().hex
    record = build_record()
    record.build_id = "hwpxbuild_" + suffix
    record.planned_job_id = "job_" + suffix
    record.planned_artifact_id = "artifact_" + suffix
    record.planned_artifact_revision_id = "rev_" + suffix
    source = b"local-renderer-test-port-source"
    sha = sha256_bytes(source)
    inputs = CuratedHwpxBuildInput(
        assembly_id=record.assembly_id,
        assembly_revision_id=record.assembly_revision_id,
        assembly_manifest_sha256=record.assembly_manifest_sha256,
        handoff=None,
        converter=None,
        placements=(
            CuratedNativeDocumentInput(
                position=1,
                source_format="HWPX",
                size_bytes=len(source),
                document=CuratedArtifactMember(
                    artifact_id="artifact_" + "a" * 32,
                    artifact_revision_id="rev_" + "b" * 32,
                    member_path="source.hwpx",
                    schema_ref="eom://schemas/content-intake/source-file/1.0",
                    media_type="application/vnd.hancom.hwpx",
                    sha256=sha,
                ),
            ),
        ),
    )
    record.input_plan = inputs.model_dump(mode="json")
    record.input_plan_sha256 = content_sha256(record.input_plan)
    record.output_filename = "test-assembly.hwpx"
    request = CuratedMixedRenderRequest(
        build_id=record.build_id,
        assembly_revision_id=record.assembly_revision_id,
        assembly_manifest_sha256=record.assembly_manifest_sha256,
        input_plan_sha256=record.input_plan_sha256,
        segments=(
            CuratedNativeSegment(
                position=1,
                local_file="inputs/001.hwpx",
                source_format="HWPX",
                sha256=sha,
                size_bytes=len(source),
            ),
        ),
        handoff=None,
        converter=None,
    )
    workspace = tmp_path / record.build_id
    workspace.mkdir()
    output = workspace / "output/assembled.hwpx"
    payload = b"local-renderer-test-port-output"
    result = CuratedMixedRenderResult(
        build_id=record.build_id,
        assembly_revision_id=record.assembly_revision_id,
        assembly_manifest_sha256=record.assembly_manifest_sha256,
        input_plan_sha256=record.input_plan_sha256,
        request_sha256=content_sha256(request.model_dump(mode="json")),
        status="SUCCEEDED",
        source_sha256=(sha,),
        segment_sha256=(sha,),
        section_source_positions=(1,),
        binary_count=0,
        native_equation_count=1,
        native_table_count=1,
        output_sha256=sha256_bytes(payload),
        output_size_bytes=len(payload),
        warnings=(),
        converter_bundle_sha256=None,
        failure_code=None,
    )
    adapter = Mock()
    adapter.operation = "render-curated"
    adapter.build_may_be_active.return_value = False
    adapter.open_workspace.return_value = workspace

    def write_json(_workspace, name, value):
        path = _workspace / name
        path.write_bytes(canonical_json_bytes(value) + b"\n")
        return path

    adapter.write_json.side_effect = write_json

    def render(*_args):
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(payload)
        write_json(workspace, "result.json", result.model_dump(mode="json"))
        return SimpleNamespace(exit_code=0)

    adapter.run.side_effect = render
    materializer = Mock()
    materializer.stage.return_value = CuratedMaterialization(request, (), ())
    acceptance = Mock(
        return_value=CuratedOutputAcceptance(result.output_sha256, len(payload), 1, 0, 1, 1)
    )
    monkeypatch.setattr("eom_hwpx_manager.curated_service.verify_curated_output", acceptance)
    artifacts = CatalogArtifactService(creative_engine, _settings(tmp_path))
    service = CuratedHwpxService(
        creative_engine,
        pins=Mock(),
        adapter=adapter,
        materializer=materializer,
        artifacts=artifacts,
    )
    yield SimpleNamespace(
        engine=creative_engine,
        service=service,
        record=record,
        inputs=inputs,
        result=result,
        payload=payload,
        workspace=workspace,
        adapter=adapter,
        materializer=materializer,
        acceptance=acceptance,
        artifacts=artifacts,
    )


def test_publication_uses_planned_ids_once_and_downloads_verified_fd(publication):
    p = publication
    validated = Mock()
    first = p.service.finish(p.record, p.inputs, validated=validated)
    second = p.service.finish(p.record, p.inputs, validated=validated)
    assert first == second
    assert (first.job_id, first.artifact_id, first.artifact_revision_id) == (
        p.record.planned_job_id,
        p.record.planned_artifact_id,
        p.record.planned_artifact_revision_id,
    )
    assert p.adapter.run.call_count == p.materializer.stage.call_count == 1
    assert validated.call_count == 2
    downloaded = p.service.secure_download(p.record)
    assert b"".join(downloaded.iter_chunks()) == p.payload
    assert downloaded.sha256 == sha256_bytes(p.payload)
    with build_session_factory(p.engine)() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == first.job_id)
            )
            == 1
        )


def test_shared_print_output_read_reuses_successful_publication_without_render(publication):
    from eom_catalog_service.curated_output_publication import read_curated_committed_output

    p = publication
    receipt = p.service.finish(p.record, p.inputs, validated=Mock())
    with build_session_factory(p.engine)() as session:
        output = read_curated_committed_output(session, p.record.build_id)
        repeated = read_curated_committed_output(session, p.record.build_id)
    assert output == repeated
    assert output.artifact_revision_id == receipt.artifact_revision_id
    assert output.output_sha256 == receipt.output_sha256
    assert output.assembly_revision_id == p.record.assembly_revision_id
    assert p.adapter.run.call_count == p.materializer.stage.call_count == 1


def test_crash_after_render_reuses_local_result_without_second_dispatch(publication):
    p = publication
    with pytest.raises(_Crash):
        p.service.finish(p.record, p.inputs, validated=Mock(side_effect=_Crash()))
    receipt = p.service.finish(p.record, p.inputs, validated=Mock())
    assert receipt.job_id == p.record.planned_job_id
    assert p.adapter.run.call_count == 1


def test_crash_after_commit_recovers_receipt_without_restaging(publication, monkeypatch):
    p = publication
    completed = p.service._completed
    monkeypatch.setattr(p.service, "_completed", Mock(side_effect=_Crash()))
    with pytest.raises(_Crash):
        p.service.finish(p.record, p.inputs, validated=Mock())
    monkeypatch.setattr(p.service, "_completed", completed)
    assert p.service.finish(p.record, p.inputs, validated=Mock()).job_id == p.record.planned_job_id
    assert p.adapter.run.call_count == p.materializer.stage.call_count == 1


def test_live_handle_is_observed_without_dispatch_or_staging(publication):
    p = publication
    p.adapter.build_may_be_active.return_value = True
    with pytest.raises(CuratedBuildPending):
        p.service.finish(p.record, p.inputs, validated=Mock())
    p.materializer.stage.assert_not_called()
    p.adapter.run.assert_not_called()


def test_publication_storage_error_recovers_without_recalculation(publication, monkeypatch):
    p = publication
    commit = p.artifacts.commit_file_set
    monkeypatch.setattr(
        p.artifacts, "commit_file_set", Mock(side_effect=OSError("temporary store unavailable"))
    )
    with pytest.raises(CuratedBuildPending):
        p.service.finish(p.record, p.inputs, validated=Mock())
    monkeypatch.setattr(p.artifacts, "commit_file_set", commit)
    assert p.service.finish(p.record, p.inputs, validated=Mock()).job_id == p.record.planned_job_id
    assert p.adapter.run.call_count == 1


def test_invalid_output_never_commits_and_failure_is_not_retried(publication):
    p = publication
    p.acceptance.side_effect = ValueError("synthetic independent acceptance rejection")
    with pytest.raises(ValueError):
        p.service.finish(p.record, p.inputs, validated=Mock())
    with pytest.raises(HwpxManagerError):
        p.service.finish(p.record, p.inputs, validated=Mock())
    assert p.adapter.run.call_count == 1
    with build_session_factory(p.engine)() as session:
        assert session.get(JobRecord, p.record.planned_job_id).status == "FAILED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == p.record.planned_job_id)
            )
            == 0
        )


def test_dispatch_without_result_does_not_blindly_run_again(publication):
    p = publication
    p.service._reserve(p.record)
    assert p.service._claim_dispatch(p.record)
    with pytest.raises(HwpxManagerError):
        p.service.finish(p.record, p.inputs, validated=Mock())
    p.adapter.run.assert_not_called()


def test_changed_input_plan_is_rejected_before_dispatch(publication):
    p = publication
    p.record.input_plan_sha256 = "sha256:" + "0" * 64
    with pytest.raises(HwpxManagerError):
        p.service.finish(p.record, p.inputs, validated=Mock())
    p.adapter.run.assert_not_called()


@pytest.mark.skipif(
    os.environ.get("EOM_RUN_CURATED_REAL_RENDER_INTEGRATION") != "1",
    reason="Opt-in disposable DB and separately installed Builder are required",
)
def test_real_mixed_renderer_independent_acceptance_commit_and_download(
    publication, tmp_path, monkeypatch
):
    """Close the real bytes boundary, not just a renderer-success test port.

    Native, variable canonical and content-team 2/3 inputs are synthetic local
    fixtures. Only the existing guarded disposable database and local Artifact
    store are used; no production source, model, GPU or NAS is touched.
    """
    from eom_hwpx_builder.content_team_handoff import inspect_content_team_handoff
    from eom_hwpx_manager.curated_output_acceptance import verify_curated_output

    from tests.hwpx.test_curated_materialization import cohort
    from tests.hwpx.test_curated_mixed_renderer import HANDOFF

    p = publication
    builder = Path("/srv/eom/conda/envs/eom-hwpx/bin/python")
    assert builder.is_file() and HANDOFF.is_file()
    evidence = inspect_content_team_handoff(HANDOFF)
    template = next(row for row in evidence.members if row.purpose == "automation-template")
    with zipfile.ZipFile(HANDOFF) as archive:
        handoff = HANDOFF.read_bytes(), archive.read(template.archive_member)
    case = tmp_path / "real-render"
    case.mkdir()
    materializer, inputs, workspace, _canonical = cohort(case, handoff)
    p.record.assembly_id = inputs.assembly_id
    p.record.assembly_revision_id = inputs.assembly_revision_id
    p.record.assembly_manifest_sha256 = inputs.assembly_manifest_sha256
    p.record.input_plan = inputs.model_dump(mode="json")
    p.record.input_plan_sha256 = content_sha256(p.record.input_plan)
    p.service.materializer = materializer
    p.adapter.open_workspace.return_value = workspace

    def render(_workspace, operation, arguments, _log_root):
        assert _workspace == workspace and operation == "render-curated"
        run = subprocess.run(
            [str(builder), "-I", "-B", "-m", "eom_hwpx_builder", operation, *arguments],
            cwd=workspace,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"},
            capture_output=True,
            timeout=90,
            check=False,
        )
        assert run.returncode == 0, "installed Builder must produce a successful real document"
        return SimpleNamespace(exit_code=run.returncode)

    p.adapter.run.side_effect = render
    monkeypatch.setattr(
        "eom_hwpx_manager.curated_service.verify_curated_output", verify_curated_output
    )
    first = p.service.finish(p.record, inputs, validated=Mock())
    again = p.service.finish(p.record, inputs, validated=Mock())
    assert again == first and p.adapter.run.call_count == 1
    assert first.section_count == 5
    assert (
        first.binary_count > 0 and first.native_table_count > 0 and first.native_equation_count > 0
    )
    output = (workspace / "output/assembled.hwpx").read_bytes()
    downloaded = p.service.secure_download(p.record)
    assert b"".join(downloaded.iter_chunks()) == output
    assert downloaded.sha256 == first.output_sha256 == sha256_bytes(output)
    with build_session_factory(p.engine)() as session:
        assert session.get(JobRecord, first.job_id).status == "SUCCEEDED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == first.job_id)
            )
            == 1
        )
