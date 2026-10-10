from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import worker_exec
from eom_orchestrator.codex_compatibility_probe import synthetic_probe_png
from eom_orchestrator.worker_exec import _load_compatibility_invocation, codex_command

from tests.unit.test_codex_compatibility_probe import _invocation


def _inputs(root: Path) -> Path:
    invocation = _invocation()
    path = root / "codex-compatibility-invocation.json"
    path.write_text(invocation.model_dump_json())
    path.chmod(0o640)
    image = root / "compatibility-input.png"
    image.write_bytes(synthetic_probe_png())
    image.chmod(0o640)
    return path


def test_maintenance_invocation_pins_exact_model_effort_image_without_plan(tmp_path: Path) -> None:
    path = _inputs(tmp_path)
    invocation, images = _load_compatibility_invocation(
        path, workspace=tmp_path, group_id=os.getgid(), job_id=_invocation().job_id
    )
    assert "plan_id" not in invocation
    assert images == (tmp_path / "compatibility-input.png",)
    command = codex_command(tmp_path, invocation, images)
    assert command[4] == "gpt-6.1-sol"
    assert 'model_reasoning_effort="high"' in command
    assert "--strict-config" in command
    assert "--image" in command
    assert "read-only" in command
    assert "--output-schema" in command
    assert "--ignore-user-config" in command
    assert "--ephemeral" in command


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "codex-invocation/1.0"),
        ("run_id", "execplan_" + "1" * 32),
        ("case_id", "../case"),
        ("job_id", "job_" + "0" * 32),
        ("model", "model --unsafe"),
        ("reasoning_effort", "ultra"),
        ("image_sha256", "sha256:" + "0" * 64),
        ("request_sha256", "arbitrary"),
    ],
)
def test_invalid_compatibility_pins_fail_before_codex(
    tmp_path: Path, field: str, value: str
) -> None:
    path = _inputs(tmp_path)
    document = json.loads(path.read_text())
    document[field] = value
    document["invocation_sha256"] = content_sha256(
        {key: item for key, item in document.items() if key != "invocation_sha256"}
    )
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        _load_compatibility_invocation(
            path, workspace=tmp_path, group_id=os.getgid(), job_id=_invocation().job_id
        )


@pytest.mark.parametrize("mutation", ["changed", "symlink", "hardlink", "oversized", "wrong-mode"])
def test_untrusted_compatibility_image_is_not_attached(tmp_path: Path, mutation: str) -> None:
    path = _inputs(tmp_path)
    image = tmp_path / "compatibility-input.png"
    if mutation == "changed":
        image.write_bytes(synthetic_probe_png() + b"changed")
    elif mutation == "symlink":
        image.rename(tmp_path / "other.png")
        image.symlink_to(tmp_path / "other.png")
    elif mutation == "hardlink":
        os.link(image, tmp_path / "other.png")
    elif mutation == "oversized":
        image.write_bytes(b"x" * (worker_exec.MAX_INPUT_BYTES + 1))
    else:
        image.chmod(0o644)
    with pytest.raises((OSError, ValueError)):
        _load_compatibility_invocation(
            path, workspace=tmp_path, group_id=os.getgid(), job_id=_invocation().job_id
        )


def test_duplicate_invocation_json_fields_are_rejected(tmp_path: Path) -> None:
    path = _inputs(tmp_path)
    original = path.read_text()
    path.write_text('{"model":"other",' + original[1:])
    with pytest.raises(ValueError, match="duplicate"):
        _load_compatibility_invocation(
            path, workspace=tmp_path, group_id=os.getgid(), job_id=_invocation().job_id
        )


def test_invocation_hash_cannot_be_replaced_by_another_case(tmp_path: Path) -> None:
    path = _inputs(tmp_path)
    document = json.loads(path.read_text())
    document["case_id"] = "compatcase_" + "0" * 32
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="hash differs"):
        _load_compatibility_invocation(
            path, workspace=tmp_path, group_id=os.getgid(), job_id=_invocation().job_id
        )


@pytest.mark.parametrize("conflict", ["production-invocation", "production-images"])
def test_worker_cannot_mix_production_and_maintenance_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: str
) -> None:
    root = tmp_path / "worker"
    root.mkdir()
    workspace = root / _invocation().job_id
    workspace.mkdir()
    _inputs(workspace)
    for name in ("worker-input.json", "worker-result.schema.json", "AGENTS.md"):
        path = workspace / name
        path.write_text("{}")
        path.chmod(0o640)
    name = (
        "codex-invocation.json"
        if conflict == "production-invocation"
        else "codex-image-inputs.json"
    )
    (workspace / name).write_text("{}")
    monkeypatch.setattr(
        worker_exec, "expected_workspace", lambda *_args: ("eom-cdx-01", root, workspace)
    )
    monkeypatch.setattr(worker_exec, "_validate_runtime_identity", lambda *_args: None)
    monkeypatch.setattr(worker_exec, "_validate_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker_exec, "_validate_codex_binary", lambda: None)

    def forbidden_launch(*_args: object, **_kwargs: object) -> None:
        pytest.fail("conflicting invocation authority cannot launch Codex")

    monkeypatch.setattr(worker_exec.subprocess, "run", forbidden_launch)
    with pytest.raises(ValueError, match=r"mix|production image"):
        worker_exec.execute("01", _invocation().job_id)
