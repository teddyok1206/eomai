"""Release acceptance resolves primary pointers and exact secondary manifest members."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.artifacts import stage_file_set_artifact
from eom_orchestrator.control_models import (
    ExecutionPresetRevisionRecord,
    ExecutionPresetValidationRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.preset_model_evidence import CASES_SCHEMA_REF
from eom_orchestrator.preset_model_release import require_current_model_acceptance
from eom_orchestrator.preset_model_validation import TASK_TYPE

from tests.unit.test_preset_model_selection import _self_hash
from tests.unit.test_preset_model_validation import _acceptance

REPORT_SCHEMA = "eom://schemas/workflow/execution-preset-evaluation-report/1.0"


@pytest.fixture
def acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    command, job, request, base, draft, report, cases = _acceptance()
    command.state = job.status = "SUCCEEDED"
    command.completed_at = job.completed_at = datetime.now(UTC)
    names = {"preset-evaluation.json": report, "acceptance-cases.json": cases}
    files = {}
    for name, document in names.items():
        target = tmp_path / name
        target.write_bytes(canonical_json_bytes(document) + b"\n")
        files[name] = target
    staged = stage_file_set_artifact(
        files=files,
        primary_file="preset-evaluation.json",
        job_id=job.job_id,
        logical_artifact_id=job.logical_artifact_id,
        revision_id=job.revision_id,
        artifact_type=TASK_TYPE,
        staging=tmp_path / "staged",
        created_at=request.requested_at,
        manifest_version="control-file-set/1.0",
        file_metadata={
            "preset-evaluation.json": {
                "schema_ref": REPORT_SCHEMA,
                "media_type": "application/json",
            },
            "acceptance-cases.json": {
                "schema_ref": CASES_SCHEMA_REF,
                "media_type": "application/json",
            },
        },
    )
    artifact = ArtifactRecord(logical_artifact_id=job.logical_artifact_id, approved=True)
    revision = ArtifactRevisionRecord(
        revision_id=job.revision_id,
        logical_artifact_id=job.logical_artifact_id,
        job_id=job.job_id,
        content_hash=staged.primary_hash,
        content_bytes=staged.primary_bytes,
        manifest_hash=staged.manifest_hash,
        manifest=staged.manifest,
        approved=True,
    )
    evaluation = SimpleNamespace(
        report_artifact_id=job.logical_artifact_id,
        report_artifact_revision_id=job.revision_id,
        report_document_sha256=report["report_sha256"],
        report_content_sha256=staged.primary_hash,
        evaluated_policy_sha256=request.preset_policy_sha256,
        cases_total=report["cases_total"],
        cases_passed=report["cases_passed"],
        scope="NON_LIVE",
        outcome="PASS",
    )
    logical = SimpleNamespace(current_revision_id=base.preset_revision_id)
    event = SimpleNamespace(data={"report": report, "cases": cases})
    freshness_calls: list[tuple[Any, ...]] = []

    def validate_fresh_models(session: Any, actual_base: Any, actual_draft: Any, **kw: Any) -> None:
        freshness_calls.append((session, actual_base, actual_draft, kw["observed_at"]))

    monkeypatch.setattr(
        "eom_orchestrator.preset_model_release.validate_model_selection", validate_fresh_models
    )
    lookups: list[tuple[type[Any], str]] = []

    class Session:
        def scalar(self, statement: Any) -> Any:
            entity = statement.column_descriptions[0]["entity"]
            assert entity in {JobRecord, JobEventRecord}
            return job if entity is JobRecord else event

        def get(self, model: type[Any], identity: str) -> Any:
            lookups.append((model, identity))
            records = {
                (ExecutionPresetValidationRecord, job.job_id): command,
                (ExecutionPresetRevisionRecord, base.preset_revision_id): base,
                (ArtifactRecord, job.logical_artifact_id): artifact,
                (ArtifactRevisionRecord, job.revision_id): revision,
            }
            return records.get((model, identity))

    return {
        "session": Session(),
        "command": command,
        "job": job,
        "base": base,
        "draft": draft,
        "report": report,
        "cases": cases,
        "artifact": artifact,
        "revision": revision,
        "evaluation": evaluation,
        "logical": logical,
        "event": event,
        "freshness_calls": freshness_calls,
        "lookups": lookups,
    }


def _require(acceptance: dict[str, Any]) -> None:
    require_current_model_acceptance(
        acceptance["session"],
        logical=acceptance["logical"],
        draft=acceptance["draft"],
        evaluation=acceptance["evaluation"],
        observed_at=datetime.now(UTC),
    )


def _rehash_manifest(acceptance: dict[str, Any]) -> None:
    revision = acceptance["revision"]
    revision.manifest_hash = content_sha256(revision.manifest)


def _cases_member(acceptance: dict[str, Any]) -> dict[str, Any]:
    return next(
        item
        for item in acceptance["revision"].manifest["files"]
        if item["file_name"] == "acceptance-cases.json"
    )


def test_release_accepts_real_file_set_without_reinterpreting_secondary_sha_as_primary(
    acceptance: dict[str, Any],
) -> None:
    secondary = _cases_member(acceptance)
    assert secondary["sha256"] != acceptance["revision"].content_hash
    _require(acceptance)
    assert len(acceptance["freshness_calls"]) == 1
    assert acceptance["lookups"].count((ArtifactRevisionRecord, acceptance["job"].revision_id)) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("report_artifact_id", "artifact_" + "7" * 32),
        ("report_artifact_revision_id", "rev_" + "7" * 32),
    ],
)
def test_release_rejects_evaluation_artifact_identity_drift(
    acceptance: dict[str, Any], field: str, value: str
) -> None:
    setattr(acceptance["evaluation"], field, value)
    with pytest.raises(ControlPlaneError) as failure:
        _require(acceptance)
    assert failure.value.code == "CONTROL_VALIDATION_EVIDENCE_MISMATCH"
    assert not acceptance["freshness_calls"]
    assert not any(model is ArtifactRevisionRecord for model, _identity in acceptance["lookups"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("logical_artifact_id", "artifact_" + "7" * 32),
        ("revision_id", "rev_" + "7" * 32),
        ("job_id", "job_" + "7" * 32),
        ("artifact_type", "not-preset-acceptance"),
        ("manifest_version", "other-file-set/1.0"),
        ("primary_file", "acceptance-cases.json"),
    ],
)
def test_release_rejects_rehashed_manifest_owner_or_contract_drift(
    acceptance: dict[str, Any], field: str, value: str
) -> None:
    acceptance["revision"].manifest[field] = value
    _rehash_manifest(acceptance)
    with pytest.raises(ControlPlaneError) as failure:
        _require(acceptance)
    assert failure.value.code == "CONTROL_VALIDATION_EVIDENCE_MISMATCH"
    assert not acceptance["freshness_calls"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("file_name", "stale-cases.json"),
        ("file_name", ["acceptance-cases.json"]),
        ("sha256", "sha256:" + "7" * 64),
        ("bytes", 0),
        ("schema_ref", "eom://schemas/workflow/other/1.0"),
        ("media_type", "text/plain"),
    ],
)
def test_release_rejects_stale_or_rehashed_secondary_member(
    acceptance: dict[str, Any], field: str, value: Any
) -> None:
    _cases_member(acceptance)[field] = value
    _rehash_manifest(acceptance)
    with pytest.raises(ControlPlaneError) as failure:
        _require(acceptance)
    assert failure.value.code == "CONTROL_VALIDATION_EVIDENCE_MISMATCH"
    assert not acceptance["freshness_calls"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "manifest_hash", "revision_job"])
def test_release_rejects_missing_duplicate_or_unpinned_members(
    acceptance: dict[str, Any], change: str
) -> None:
    revision = acceptance["revision"]
    if change == "missing":
        revision.manifest["files"] = [
            member
            for member in revision.manifest["files"]
            if member["file_name"] != "acceptance-cases.json"
        ]
    elif change == "duplicate":
        revision.manifest["files"].append(dict(_cases_member(acceptance)))
    elif change == "manifest_hash":
        revision.manifest_hash = "sha256:" + "7" * 64
    else:
        revision.job_id = "job_" + "7" * 32
    if change != "manifest_hash":
        _rehash_manifest(acceptance)
    with pytest.raises(ControlPlaneError) as failure:
        _require(acceptance)
    assert failure.value.code == "CONTROL_VALIDATION_EVIDENCE_MISMATCH"


def test_release_rejects_changed_current_baseline_before_resolving_evidence(
    acceptance: dict[str, Any],
) -> None:
    acceptance["logical"].current_revision_id = "execpresetrev_" + "7" * 32
    with pytest.raises(ControlPlaneError) as failure:
        _require(acceptance)
    assert failure.value.code == "CONTROL_PRESET_BASE_STALE"
    assert not any(model is ArtifactRevisionRecord for model, _identity in acceptance["lookups"])
    assert not acceptance["freshness_calls"]


def test_release_rejects_rehashed_checkpoint_completion_before_request(
    acceptance: dict[str, Any],
) -> None:
    completed = (
        (acceptance["command"].requested_at - timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z")
    )
    for target, hash_field in (("report", "report_sha256"), ("cases", "cases_sha256")):
        acceptance[target]["completed_at"] = completed
        _self_hash(acceptance[target], hash_field)
    with pytest.raises(ControlPlaneError) as failure:
        _require(acceptance)
    assert failure.value.code == "CONTROL_VALIDATION_CHECKPOINT_INVALID"


def test_release_rechecks_fresh_admission_after_resolving_exact_manifest(
    acceptance: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise ControlPlaneError(
            "CONTROL_PRESET_MODEL_UNAVAILABLE", "fresh slot no longer admits model"
        )

    monkeypatch.setattr(
        "eom_orchestrator.preset_model_release.validate_model_selection", unavailable
    )
    with pytest.raises(ControlPlaneError) as failure:
        _require(acceptance)
    assert failure.value.code == "CONTROL_PRESET_MODEL_UNAVAILABLE"


def test_historical_report_lineage_does_not_gain_new_secondary_requirements(
    acceptance: dict[str, Any],
) -> None:
    acceptance["job"].protocol_version = "execution-preset-evaluation-request/1.0"
    acceptance["revision"].manifest = {}
    _require(acceptance)
    assert not acceptance["lookups"]
    assert not acceptance["freshness_calls"]
