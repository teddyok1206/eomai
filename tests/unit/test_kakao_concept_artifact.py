"""Numeric Artifact values do not relax integer-only protocol/control messages."""

import json

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts import canonical_bytes
from eom_orchestrator.artifacts import (
    commit_artifact,
    stage_serialized_artifact,
    stage_structured_artifact,
)

JOB = "job_" + "1" * 32
ARTIFACT = "artifact_" + "2" * 32
REVISION = "rev_" + "3" * 32


def body():
    return {
        "job_id": JOB,
        "artifact": {"logical_artifact_id": ARTIFACT, "revision_id": REVISION},
        "output": {"rectangle": {"x": 0.125, "y": 0.25, "width": 0.5, "height": 0.5}},
    }


def stage(raw, tmp_path):
    return stage_serialized_artifact(
        result_bytes=raw,
        job_id=JOB,
        logical_artifact_id=ARTIFACT,
        revision_id=REVISION,
        staging=tmp_path / "stage",
        worker_slot="05",
    )


def test_finite_crop_bytes_commit_and_replay_without_relaxing_message_encoding(tmp_path):
    data = body()
    with pytest.raises(TypeError, match="floats"):
        canonical_json_bytes(data)
    with pytest.raises(TypeError, match="floats"):
        stage_structured_artifact(
            result=data,
            job_id=JOB,
            logical_artifact_id=ARTIFACT,
            revision_id=REVISION,
            staging=tmp_path / "ordinary",
            worker_slot="05",
        )
    raw = canonical_bytes(data)
    staged = stage(raw, tmp_path)
    nas = tmp_path / "nas"
    nas.mkdir()
    target = commit_artifact(staged, nas)
    assert (target / "result.json").read_bytes() == raw
    assert staged.content_hash == sha256_bytes(raw)
    assert commit_artifact(staged, nas) == target
    assert json.loads(raw)["output"]["rectangle"]["x"] == 0.125


@pytest.mark.parametrize("change", ["identity", "duplicates", "nan", "spaces", "array"])
def test_numeric_artifact_cannot_smuggle_invalid_payload_or_other_identity(tmp_path, change):
    data = body()
    raw = canonical_bytes(data)
    if change == "identity":
        data["job_id"] = "job_" + "f" * 32
        raw = canonical_bytes(data)
    elif change == "duplicates":
        raw = raw.replace(b'{"artifact":', b'{"job_id":"unrelated","artifact":', 1)
    elif change == "nan":
        raw = raw.replace(b"0.125", b"NaN")
    elif change == "spaces":
        raw = b" " + raw
    else:
        raw = b"[]"
    with pytest.raises(ValueError):
        stage(raw, tmp_path)
    assert not (tmp_path / "stage/result.json").exists()
