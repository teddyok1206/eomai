from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import sha256_bytes
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.execution_materializer import materialize_execution_step
from eom_workflow import ControlArtifactPointer

ZERO_SHA = "sha256:" + "0" * 64
GROUP_ID = os.getgid()


class FakeSession:
    def __init__(self, records: dict[tuple[type[object], str], object]) -> None:
        self.records = records

    def get(self, model: type[object], identity: str) -> object | None:
        return self.records.get((model, identity))


def _pointer(
    root: Path,
    revisions: dict[str, object],
    *,
    seed: str,
    name: str,
    payload: bytes,
) -> ControlArtifactPointer:
    artifact_id = "artifact_" + seed * 32
    revision_id = "rev_" + seed * 32
    revision_root = root / artifact_id / revision_id
    revision_root.mkdir(parents=True)
    member = revision_root / name
    member.write_bytes(payload)
    digest = sha256_bytes(payload)
    schema_ref = "eom://schemas/workflow/markdown-member/1.0"
    revisions[revision_id] = SimpleNamespace(
        nas_path=str(revision_root),
        manifest={
            "files": [
                {
                    "file_name": name,
                    "sha256": digest,
                    "bytes": len(payload),
                    "media_type": "text/markdown",
                    "schema_ref": schema_ref,
                }
            ]
        },
    )
    return ControlArtifactPointer(
        artifact_id=artifact_id,
        artifact_revision_id=revision_id,
        sha256=digest,
        schema_ref=schema_ref,
        media_type="text/markdown",
        logical_name=name,
    )


def _manifest_pointer(seed: str, *, family: str) -> dict[str, object]:
    return {
        "bundle_id": f"{family}bundle_" + seed * 32,
        "bundle_revision_id": f"{family}rev_" + seed * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + seed * 32,
            "artifact_revision_id": "rev_" + seed * 32,
            "sha256": "sha256:" + seed * 64,
            "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
        },
        "manifest_sha256": "sha256:" + seed * 64,
    }


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    artifact_root = (tmp_path / "artifacts").resolve()
    artifact_root.mkdir()
    revisions: dict[str, object] = {}
    platform = _pointer(
        artifact_root,
        revisions,
        seed="3",
        name="platform.md",
        payload=b"Platform instructions.\n",
    )
    role = _pointer(
        artifact_root,
        revisions,
        seed="4",
        name="role.md",
        payload=b"Role instructions.\n",
    )
    reference = _pointer(
        artifact_root,
        revisions,
        seed="5",
        name="curriculum.md",
        payload=b"Pinned curriculum evidence.\n",
    )
    instruction_pointer = _manifest_pointer("1", family="instr")
    reference_pointer = _manifest_pointer("2", family="ref")
    revisions["rev_" + "1" * 32] = SimpleNamespace(manifest={})
    revisions["rev_" + "2" * 32] = SimpleNamespace(manifest={})
    instruction_document = {
        "schema_version": "instruction-bundle-manifest/1.0",
        "bundle_id": instruction_pointer["bundle_id"],
        "bundle_revision_id": instruction_pointer["bundle_revision_id"],
        "revision_number": 1,
        "state": "RELEASED",
        "components": [
            {
                "layer": "ROLE",
                "relative_path": "instructions/role.md",
                "artifact": role.model_dump(mode="json"),
            },
            {
                "layer": "PLATFORM",
                "relative_path": "instructions/platform.md",
                "artifact": platform.model_dump(mode="json"),
            },
        ],
        "content_sha256": ZERO_SHA,
        "created_at": "2026-08-23T12:00:00Z",
    }
    instruction_document["content_sha256"] = compute_control_document_hash(
        instruction_document, "content_sha256"
    )
    reference_document = {
        "schema_version": "reference-bundle-manifest/1.0",
        "bundle_id": reference_pointer["bundle_id"],
        "bundle_revision_id": reference_pointer["bundle_revision_id"],
        "revision_number": 1,
        "state": "RELEASED",
        "entries": [
            {
                "reference_key": "curriculum",
                "source_class": "CURRICULUM",
                "relative_path": "references/evidence/curriculum.md",
                "source_logical_id": "document_" + "6" * 32,
                "source_revision_id": "documentrev_" + "6" * 32,
                "rights_policy_revision_id": "rightsrev_" + "6" * 32,
                "artifact": reference.model_dump(mode="json"),
            }
        ],
        "content_sha256": ZERO_SHA,
        "created_at": "2026-08-23T12:00:00Z",
    }
    reference_document["content_sha256"] = compute_control_document_hash(
        reference_document, "content_sha256"
    )
    plan_document = {
        "schema_version": "resolved-execution-plan/1.0",
        "plan_id": "execplan_" + "7" * 32,
        "workflow_id": "workflow_" + "8" * 32,
        "preset_id": "execpreset_" + "9" * 32,
        "preset_revision_id": "execpresetrev_" + "9" * 32,
        "preset_sha256": "sha256:" + "9" * 64,
        "workflow_definition_key": "generic-item-development",
        "workflow_definition_version": "1.4.0",
        "workflow_definition_sha256": "sha256:" + "a" * 64,
        "content_pack_release_id": "packrel_" + "b" * 32,
        "content_pack_sha256": "sha256:" + "b" * 64,
        "capacity_policy_revision_id": "capacityrev_" + "c" * 32,
        "graph_snapshot_revision_id": None,
        "evidence_bundle_revision_id": None,
        "steps": [
            {
                "step_key": "authoring",
                "role": "authoring",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "instruction_bundle": instruction_pointer,
                "reference_bundle": reference_pointer,
                "worker_pool_key": "authoring",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "ALLOWED_WITH_PROVENANCE",
            }
        ],
        "resolver_version": "1.0.0",
        "resolved_at": "2026-08-23T12:00:00Z",
        "plan_sha256": ZERO_SHA,
    }
    plan_document["plan_sha256"] = compute_control_document_hash(plan_document, "plan_sha256")
    records: dict[tuple[type[object], str], object] = {
        (
            ResolvedExecutionPlanRecord,
            str(plan_document["plan_id"]),
        ): SimpleNamespace(
            canonical_document=plan_document,
            plan_sha256=plan_document["plan_sha256"],
        ),
        (
            ExecutionBundleRevisionRecord,
            str(instruction_pointer["bundle_revision_id"]),
        ): SimpleNamespace(
            bundle_id=instruction_pointer["bundle_id"],
            bundle_kind="INSTRUCTION",
            state="RELEASED",
            manifest_sha256=instruction_pointer["manifest_sha256"],
            content_sha256=instruction_document["content_sha256"],
            canonical_document=instruction_document,
        ),
        (
            ExecutionBundleRevisionRecord,
            str(reference_pointer["bundle_revision_id"]),
        ): SimpleNamespace(
            bundle_id=reference_pointer["bundle_id"],
            bundle_kind="REFERENCE",
            state="RELEASED",
            manifest_sha256=reference_pointer["manifest_sha256"],
            content_sha256=reference_document["content_sha256"],
            canonical_document=reference_document,
        ),
    }

    def resolve_pointer(
        _session: object,
        pointer: ControlArtifactPointer,
        *,
        expected_schema_ref: str | None = None,
        expected_media_type: str | None = None,
    ) -> object:
        assert expected_schema_ref is None
        assert expected_media_type in {None, "text/markdown"}
        if expected_media_type is None:
            assert pointer.media_type == "application/json"
        return revisions[pointer.artifact_revision_id]

    monkeypatch.setattr(
        "eom_orchestrator.execution_materializer.resolve_control_artifact_pointer",
        resolve_pointer,
    )
    return {
        "session": FakeSession(records),
        "artifact_root": artifact_root,
        "plan_id": plan_document["plan_id"],
        "authorized": frozenset(revisions),
        "platform": platform,
    }


def _workspace(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir(mode=0o2770)
    path.chmod(0o2770)
    return path


def test_materializer_is_deterministic_bounded_and_path_free_in_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    first = _workspace(tmp_path, "first")
    second = _workspace(tmp_path, "second")
    source = (
        fixture["artifact_root"]
        / fixture["platform"].artifact_id
        / fixture["platform"].artifact_revision_id
        / fixture["platform"].logical_name
    )
    source_before = (source.stat().st_mode, source.stat().st_mtime_ns, source.read_bytes())
    results = [
        materialize_execution_step(
            fixture["session"],
            plan_id=str(fixture["plan_id"]),
            step_key="authoring",
            workspace=workspace,
            canonical_artifact_root=fixture["artifact_root"],
            worker_group_id=GROUP_ID,
            authorized_artifact_revision_ids=fixture["authorized"],
        )
        for workspace in (first, second)
    ]
    assert (first / "AGENTS.md").read_bytes() == (second / "AGENTS.md").read_bytes()
    assert (first / "codex-invocation.json").read_bytes() == (
        second / "codex-invocation.json"
    ).read_bytes()
    agents = (first / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.index("PLATFORM") < agents.index("ROLE")
    assert (first / "references/evidence/curriculum.md").read_text(encoding="utf-8")
    assert stat.S_IMODE((first / "instructions").stat().st_mode) == 0o750
    assert stat.S_IMODE((first / "AGENTS.md").stat().st_mode) == 0o640
    assert json.loads((first / "codex-invocation.json").read_text())["model"] == ("gpt-5.6-terra")
    assert results[0].agents_sha256 == results[1].agents_sha256
    assert results[0].invocation_sha256 == results[1].invocation_sha256
    assert results[0].materialized_member_count == 3
    assert all("path" not in key for key in results[0].event_data())
    assert source_before == (source.stat().st_mode, source.stat().st_mtime_ns, source.read_bytes())


def test_materializer_fails_before_copy_without_explicit_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    workspace = _workspace(tmp_path, "workspace")
    with pytest.raises(ControlPlaneError) as captured:
        materialize_execution_step(
            fixture["session"],
            plan_id=str(fixture["plan_id"]),
            step_key="authoring",
            workspace=workspace,
            canonical_artifact_root=fixture["artifact_root"],
            worker_group_id=GROUP_ID,
            authorized_artifact_revision_ids=frozenset(),
        )
    assert captured.value.code == "CONTROL_POINTER_PERMISSION_DENIED"
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("tamper", ["hash", "symlink"])
def test_materializer_rejects_hash_drift_and_symlink_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    pointer = fixture["platform"]
    source = (
        fixture["artifact_root"]
        / pointer.artifact_id
        / pointer.artifact_revision_id
        / pointer.logical_name
    )
    if tamper == "hash":
        source.write_bytes(b"Different instructions\n")
    else:
        target = tmp_path / "outside.md"
        target.write_text("outside", encoding="utf-8")
        source.unlink()
        source.symlink_to(target)
    with pytest.raises(ControlPlaneError) as captured:
        materialize_execution_step(
            fixture["session"],
            plan_id=str(fixture["plan_id"]),
            step_key="authoring",
            workspace=_workspace(tmp_path, "workspace"),
            canonical_artifact_root=fixture["artifact_root"],
            worker_group_id=GROUP_ID,
            authorized_artifact_revision_ids=fixture["authorized"],
        )
    assert captured.value.code in {"CONTROL_POINTER_FILE_INVALID", "CONTROL_POINTER_HASH_MISMATCH"}


def test_materializer_rejects_preexisting_target_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    workspace = _workspace(tmp_path, "workspace")
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "instructions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ControlPlaneError) as captured:
        materialize_execution_step(
            fixture["session"],
            plan_id=str(fixture["plan_id"]),
            step_key="authoring",
            workspace=workspace,
            canonical_artifact_root=fixture["artifact_root"],
            worker_group_id=GROUP_ID,
            authorized_artifact_revision_ids=fixture["authorized"],
        )
    assert captured.value.code == "CONTROL_WORKSPACE_INVALID"
