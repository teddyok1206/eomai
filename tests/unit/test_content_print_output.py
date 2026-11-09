"""Optional print output is explicit, pinned, and read from one committed publication."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.content_planning_rpc import (
    ContentPlanningPrintRequest,
    parse_content_planning_request,
)
from eom_catalog_contracts.content_print_commands import (
    RecordContentPrintWithOutput,
    parse_content_print_command,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.curated_output_publication import read_curated_committed_output
from eom_hwpx_contracts.curated_mixed import CuratedMixedRenderResult
from eom_identifiers import content_sha256
from eom_web_gui.content_planning_contracts import PrintCommand
from jsonschema import ValidationError as SchemaError
from pydantic import TypeAdapter
from sqlalchemy.dialects import postgresql

from tests.unit.content_planning_fixtures import SHA, TIME, identifier
from tests.unit.test_content_planning_read_contracts import print_example
from tests.unit.test_curated_hwpx_build import build_inputs, build_manifest


def test_explicit_output_successor_preserves_old_closed_command_and_roundtrips():
    old, _ = print_example()
    value = {
        **old.model_dump(mode="json"),
        "command_kind": "RECORD_PRINT_WITH_OUTPUT",
        "output_build_id": identifier("hwpxbuild"),
        "output_sha256": SHA,
    }
    parsed = parse_content_print_command(value)
    assert isinstance(parsed, RecordContentPrintWithOutput)
    assert TypeAdapter(PrintCommand).validate_python(value).model_dump(mode="json") == value
    with pytest.raises(SchemaError):
        validate_contract("content-print-command-v1", value)
    assert parse_content_print_command(old.model_dump(mode="json")) == old
    request = ContentPlanningPrintRequest(
        actor_id=identifier("operator"),
        session_id=identifier("apisession"),
        request_id="print-output-test",
        authentication_time=TIME,
        idempotency_key="print-output-test-key",
        command=parsed,
    )
    assert parse_content_planning_request(request.model_dump(mode="json")) == request
    with pytest.raises(SchemaError):
        validate_contract("catalog-content-planning-request-v1", request.model_dump(mode="json"))


def publication():
    inputs = build_inputs(build_manifest())
    build_id = identifier("hwpxbuild")
    job = SimpleNamespace(
        job_id=identifier("job"),
        logical_artifact_id=identifier("artifact"),
        revision_id=identifier("rev"),
        task_type="hwpx-curated-build",
        status="SUCCEEDED",
        protocol_version="hwpx-curated/1.0",
        request=inputs.model_dump(mode="json"),
    )
    job.request_hash = content_sha256(
        {
            "protocol_version": job.protocol_version,
            "task_type": job.task_type,
            "request": job.request,
        }
    )
    result = CuratedMixedRenderResult(
        build_id=build_id,
        assembly_revision_id=inputs.assembly_revision_id,
        assembly_manifest_sha256=inputs.assembly_manifest_sha256,
        input_plan_sha256=content_sha256(job.request),
        request_sha256=SHA,
        status="SUCCEEDED",
        source_sha256=(SHA,) * len(inputs.placements),
        segment_sha256=(SHA,) * len(inputs.placements),
        section_source_positions=tuple(range(1, len(inputs.placements) + 1)),
        binary_count=1,
        native_equation_count=1,
        native_table_count=1,
        output_sha256=SHA,
        output_size_bytes=17,
        warnings=(),
        converter_bundle_sha256=None,
        failure_code=None,
    )
    manifest = {
        "job_id": job.job_id,
        "logical_artifact_id": job.logical_artifact_id,
        "revision_id": job.revision_id,
        "primary_file": "assembled.hwpx",
        "files": [
            {
                "file_name": "assembled.hwpx",
                "sha256": SHA,
                "bytes": 17,
                "schema_ref": "eom://schemas/hwpx/curated-editable-document/1.0",
                "media_type": "application/hwp+zip",
            }
        ],
    }
    artifact = SimpleNamespace(
        approved=True,
        logical_artifact_id=job.logical_artifact_id,
        artifact_type="hwpx-curated-build",
    )
    revision = SimpleNamespace(
        approved=True,
        logical_artifact_id=job.logical_artifact_id,
        revision_id=job.revision_id,
        manifest=manifest,
        manifest_hash=content_sha256(manifest),
        content_hash=SHA,
        content_bytes=17,
        result=result.model_dump(mode="json"),
    )
    session = Mock()
    session.execute.return_value.one_or_none.return_value = (job, artifact, revision)
    return SimpleNamespace(
        session=session, build_id=build_id, job=job, artifact=artifact, revision=revision
    )


def test_committed_output_uses_unique_job_key_and_never_materializes_bytes():
    value = publication()
    before = deepcopy(value.revision.manifest)
    result = read_curated_committed_output(value.session, value.build_id)
    assert result.build_id == value.build_id
    assert result.output_sha256 == result.artifact_sha256 == SHA
    assert value.revision.manifest == before
    statement = value.session.execute.call_args.args[0]
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert f"jobs.idempotency_key = 'hwpx-curated:{value.build_id}'" in sql
    assert len(value.session.mock_calls) == 2


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "job_failed",
        "revoked",
        "wrong_build",
        "hash",
        "media",
        "scope",
        "duplicate_member",
        "request_hash",
        "schema",
    ],
)
def test_committed_output_rejects_missing_revoked_stale_or_unrelated_publication(defect):
    value = publication()
    if defect == "missing":
        value.session.execute.return_value.one_or_none.return_value = None
    elif defect == "job_failed":
        value.job.status = "FAILED"
    elif defect == "revoked":
        value.revision.approved = False
    elif defect == "wrong_build":
        value.revision.result["build_id"] = identifier("hwpxbuild", 2)
    elif defect == "hash":
        value.revision.content_hash = "sha256:" + "f" * 64
    elif defect == "media":
        value.revision.manifest["files"][0]["media_type"] = "image/png"
        value.revision.manifest_hash = content_sha256(value.revision.manifest)
    elif defect == "scope":
        value.revision.result["assembly_revision_id"] = identifier("assemblyrev", 2)
    elif defect == "duplicate_member":
        value.revision.manifest["files"] *= 2
        value.revision.manifest_hash = content_sha256(value.revision.manifest)
    elif defect == "request_hash":
        value.job.request_hash = "sha256:" + "f" * 64
    elif defect == "schema":
        value.revision.result["schema_version"] = "unsupported/9.0"
    with pytest.raises(ValueError):
        read_curated_committed_output(value.session, value.build_id)
