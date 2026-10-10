"""Synthetic protected-file fixtures; no real DB, NAS or worker execution."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
    preflight_inference_transfer_materialization,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_workflow.control_plane import ControlArtifactPointer
from eom_workflow.inference_transfer_materialization import InferenceTransferMaterializationContext

from tests.unit.inference_transfer_execution_fixtures import transfer_instruction
from tests.unit.test_inference_transfer_materialization_context import (
    materialization_context,
    materialization_plan,
)

GROUP_ID = os.getgid()


@contextmanager
def rejects(code: str) -> Iterator[None]:
    with pytest.raises(ControlPlaneError) as error:
        yield
    assert error.value.code == code


class FakeSession:
    def __init__(self, records: dict[tuple[type[object], str], Any]) -> None:
        self.records = records

    def get(self, model: type[object], identity: str) -> Any:
        return self.records.get((model, identity))


def rehash(document: dict[str, Any], field: str) -> None:
    document[field] = content_sha256(
        {key: value for key, value in document.items() if key != field}
    )


def fixture(tmp_path: Path) -> SimpleNamespace:
    artifact_root = (tmp_path / "synthetic-artifacts").resolve()
    artifact_root.mkdir(parents=True)
    records: dict[tuple[type[object], str], Any] = {}

    def member(
        seed: str, name: str, payload: bytes, schema: str, media: str
    ) -> ControlArtifactPointer:
        artifact_id, revision_id = "artifact_" + seed * 32, "rev_" + seed * 32
        revision_root = artifact_root / artifact_id / revision_id
        path = revision_root / name
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        digest = sha256_bytes(payload)
        pointer = ControlArtifactPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            sha256=digest,
            schema_ref=schema,
            media_type=media,
            logical_name=name,
        )
        records[(ArtifactRecord, artifact_id)] = SimpleNamespace(approved=True)
        records[(ArtifactRevisionRecord, revision_id)] = SimpleNamespace(
            approved=True,
            logical_artifact_id=artifact_id,
            content_hash=digest,
            nas_path=str(revision_root),
            manifest={
                "files": [
                    {
                        "file_name": name,
                        "sha256": digest,
                        "bytes": len(payload),
                        "media_type": media,
                        "schema_ref": schema,
                    }
                ]
            },
        )
        return pointer

    rubric_payload = b"# Protected transfer rubric\nCompare exact scientific assumptions.\n"
    rubric = member(
        "4",
        "instructions/transfer-rubric.md",
        rubric_payload,
        "eom://schemas/workflow/instruction-member/1.0",
        "text/markdown",
    )
    context_body = materialization_context().model_dump(mode="json")
    workflow = context_body["workflow_request"]
    workflow["comparison"]["rubric"]["rubric_sha256"] = rubric.sha256
    rehash(workflow["comparison"], "request_sha256")
    rehash(workflow, "request_sha256")
    context_body["worker_input"]["request"] = {
        key: workflow[key]
        for key in ("request_name", "comparison", "left_profile", "right_profile")
    }
    prompt = b"Synthetic prepared comparison prompt.\n"
    context_body["prompt_sha256"] = sha256_bytes(prompt)
    context = InferenceTransferMaterializationContext.model_validate(context_body)
    platform = member(
        "5",
        "instructions/platform.md",
        b"# Platform instructions\nDo not access DB or NAS.\n",
        "eom://schemas/workflow/instruction-member/1.0",
        "text/markdown",
    )
    instruction = transfer_instruction(context.workflow_request.comparison).model_dump(mode="json")
    instruction["components"][0]["artifact"] = platform.model_dump(mode="json")
    rehash(instruction, "content_sha256")
    manifest = member(
        "1",
        "manifest.json",
        canonical_json_bytes(instruction),
        "eom://schemas/workflow/instruction-bundle-manifest/1.0",
        "application/json",
    )
    plan = materialization_plan(context)
    bundle = plan["steps"][0]["instruction_bundle"]
    bundle["manifest_artifact"] = manifest.model_dump(mode="json")
    bundle["manifest_sha256"] = manifest.sha256
    rehash(plan, "plan_sha256")
    plan_record = SimpleNamespace(canonical_document=plan, plan_sha256=plan["plan_sha256"])
    bundle_record = SimpleNamespace(
        bundle_id=bundle["bundle_id"],
        bundle_revision_id=bundle["bundle_revision_id"],
        revision_number=instruction["revision_number"],
        schema_version=instruction["schema_version"],
        bundle_kind="INSTRUCTION",
        state="RELEASED",
        manifest_sha256=manifest.sha256,
        manifest_artifact_id=manifest.artifact_id,
        manifest_artifact_revision_id=manifest.artifact_revision_id,
        content_sha256=instruction["content_sha256"],
        canonical_document=instruction,
    )
    records[(ResolvedExecutionPlanRecord, plan["plan_id"])] = plan_record
    records[(ExecutionBundleRevisionRecord, bundle["bundle_revision_id"])] = bundle_record
    workspace = (tmp_path / "synthetic-workspace").resolve()
    workspace.mkdir(mode=0o2770)
    workspace.chmod(0o2770)
    input_path = workspace / "worker-input.json"
    input_path.write_text(
        json.dumps(context.worker_input.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    prompt_path = workspace / "prompt.txt"
    prompt_path.write_bytes(prompt)
    for path in (input_path, prompt_path):
        path.chmod(0o640)
    return SimpleNamespace(
        session=FakeSession(records),
        records=records,
        artifact_root=artifact_root,
        workspace=workspace,
        context=context,
        plan=plan,
        plan_record=plan_record,
        bundle_record=bundle_record,
        instruction=instruction,
        rubric=rubric,
        rubric_payload=rubric_payload,
        platform=platform,
        manifest=manifest,
    )


def materialize(value: SimpleNamespace, *, authorized: frozenset[str] | None = None) -> Any:
    if authorized is None:
        authorized = preflight_inference_transfer_materialization(
            value.session,
            plan_id=value.plan["plan_id"],
            step_key="compare_pair",
            context=value.context,
        )
    return materialize_execution_step(
        value.session,
        plan_id=value.plan["plan_id"],
        step_key="compare_pair",
        workspace=value.workspace,
        canonical_artifact_root=value.artifact_root,
        worker_group_id=GROUP_ID,
        authorized_artifact_revision_ids=authorized,
        inference_transfer_context=value.context,
    )


def test_v21_preflight_and_actual_bytes_use_only_released_instruction_members(
    tmp_path: Path,
) -> None:
    value = fixture(tmp_path)
    authorized = preflight_inference_transfer_materialization(
        value.session,
        plan_id=value.plan["plan_id"],
        step_key="compare_pair",
        context=value.context,
    )
    assert authorized == frozenset(
        pointer.artifact_revision_id for pointer in (value.manifest, value.platform, value.rubric)
    )
    result = materialize(value, authorized=authorized)
    assert result.model == "gpt-6.1-sol"
    assert result.plan_sha256 == value.plan["plan_sha256"]
    assert result.reference_bundle_revision_id is None
    assert result.materialized_member_count == 2
    assert (
        value.workspace / "instructions/transfer-rubric.md"
    ).read_bytes() == value.rubric_payload
    assert (value.workspace / "AGENTS.md").read_bytes().count(b"Protected transfer rubric") == 1
    assert not (value.workspace / "references").exists()
    assert result.invocation_path.is_file()


@pytest.mark.parametrize("entry", ["authorize", "materialize"])
def test_v21_missing_context_rejects_at_both_dispatch_sites(tmp_path: Path, entry: str) -> None:
    value = fixture(tmp_path)
    with rejects("CONTROL_TRANSFER_CONTEXT_REQUIRED"):
        if entry == "authorize":
            authorized_execution_artifact_revisions(
                value.session, plan_id=value.plan["plan_id"], step_key="compare_pair"
            )
        else:
            materialize_execution_step(
                value.session,
                plan_id=value.plan["plan_id"],
                step_key="compare_pair",
                workspace=value.workspace,
                canonical_artifact_root=value.artifact_root,
                worker_group_id=GROUP_ID,
                authorized_artifact_revision_ids=frozenset(),
            )
    assert not (value.workspace / "instructions").exists()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("access_policy_revision_id", "accessrev_" + "8" * 32),
        ("access_policy_sha256", "sha256:" + "8" * 64),
        ("requester_permissions_sha256", "sha256:" + "8" * 64),
        ("core_prompt_sha256", "sha256:" + "8" * 64),
        ("prompt_sha256", "sha256:" + "8" * 64),
    ],
)
def test_rehashed_independent_pin_mismatch_is_classified_before_staging(
    tmp_path: Path, field: str, replacement: str
) -> None:
    value = fixture(tmp_path)
    value.plan[field] = replacement
    rehash(value.plan, "plan_sha256")
    value.plan_record.plan_sha256 = value.plan["plan_sha256"]
    with rejects("CONTROL_TRANSFER_CONTEXT_INVALID"):
        materialize(value)
    assert not (value.workspace / "instructions").exists()


@pytest.mark.parametrize("change", ["missing", "wrong-layer", "wrong-path", "wrong-member"])
def test_rubric_must_be_exact_released_role_member(tmp_path: Path, change: str) -> None:
    value = fixture(tmp_path)
    components = value.instruction["components"]
    if change == "missing":
        components.pop()
    elif change == "wrong-layer":
        components[1]["layer"] = "PLATFORM"
    elif change == "wrong-path":
        components[1]["relative_path"] = "instructions/other-rubric.md"
    else:
        components[1]["artifact"]["artifact_revision_id"] = "rev_" + "9" * 32
    rehash(value.instruction, "content_sha256")
    value.bundle_record.content_sha256 = value.instruction["content_sha256"]
    with rejects("CONTROL_TRANSFER_RUBRIC_INVALID"):
        materialize(value)
    assert not (value.workspace / "AGENTS.md").exists()


@pytest.mark.parametrize("change", ["missing", "unapproved", "hash", "stale-owner"])
def test_protected_control_resolution_checks_actual_revision_lifecycle(
    tmp_path: Path, change: str
) -> None:
    value = fixture(tmp_path)
    key = (ArtifactRevisionRecord, value.rubric.artifact_revision_id)
    record = value.records[key]
    if change == "missing":
        del value.records[key]
    elif change == "unapproved":
        record.approved = False
    elif change == "hash":
        record.content_hash = "sha256:" + "9" * 64
    else:
        record.logical_artifact_id = "artifact_" + "9" * 32
    with pytest.raises(ControlPlaneError):
        materialize(value)
    assert not (value.workspace / "instructions").exists()


def test_rubric_does_not_authorize_its_own_revision(tmp_path: Path) -> None:
    value = fixture(tmp_path)
    authorized = frozenset(
        pointer.artifact_revision_id for pointer in (value.manifest, value.platform)
    )
    with rejects("CONTROL_POINTER_PERMISSION_DENIED"):
        materialize(value, authorized=authorized)
    assert not (value.workspace / "AGENTS.md").exists()


def test_actual_rubric_byte_hash_is_checked_before_worker_launch(tmp_path: Path) -> None:
    value = fixture(tmp_path)
    path = (
        value.artifact_root
        / value.rubric.artifact_id
        / value.rubric.artifact_revision_id
        / value.rubric.logical_name
    )
    path.write_bytes(b"x" * len(value.rubric_payload))
    with rejects("CONTROL_POINTER_HASH_MISMATCH"):
        materialize(value)
    assert not (value.workspace / "AGENTS.md").exists()


def test_actual_manifest_bytes_not_only_its_typed_record_are_checked(tmp_path: Path) -> None:
    value = fixture(tmp_path)
    value.instruction["created_at"] = "2026-10-09T01:02:03Z"
    rehash(value.instruction, "content_sha256")
    value.bundle_record.content_sha256 = value.instruction["content_sha256"]
    with rejects("CONTROL_TRANSFER_RUBRIC_INVALID"):
        materialize(value)
    assert not (value.workspace / "instructions").exists()


@pytest.mark.parametrize("field", ["job_id", "step_run_id", "attempt", "artifact"])
def test_actual_staged_role_input_must_equal_the_application_value(
    tmp_path: Path, field: str
) -> None:
    value = fixture(tmp_path)
    document = value.context.worker_input.model_dump(mode="json")
    replacements = {
        "job_id": "job_" + "9" * 32,
        "step_run_id": "steprun_" + "9" * 32,
        "attempt": 2,
        "artifact": {
            "logical_artifact_id": "artifact_" + "9" * 32,
            "revision_id": "rev_" + "9" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
    }
    document[field] = replacements[field]
    (value.workspace / "worker-input.json").write_bytes(canonical_json_bytes(document))
    with rejects("CONTROL_TRANSFER_STAGED_INPUT_INVALID"):
        materialize(value)
    assert not (value.workspace / "instructions").exists()


@pytest.mark.parametrize(
    "change",
    [
        "prompt",
        "duplicate-json",
        "symlink",
        "hardlink",
        "mode",
        "missing",
        "oversize",
        "fifo",
        "invalid-utf8",
    ],
)
def test_staged_bytes_and_private_filesystem_shape_fail_closed(tmp_path: Path, change: str) -> None:
    value = fixture(tmp_path)
    path = value.workspace / "prompt.txt"
    if change == "prompt":
        path.write_bytes(b"Different prepared comparison prompt.\n")
    elif change == "duplicate-json":
        input_path = value.workspace / "worker-input.json"
        original = input_path.read_text(encoding="utf-8")
        input_path.write_text('{"role":"support",' + original[1:], encoding="utf-8")
    elif change == "symlink":
        target = tmp_path / "synthetic-target.txt"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    elif change == "hardlink":
        os.link(path, tmp_path / "synthetic-hardlink.txt")
    elif change == "mode":
        path.chmod(0o666)
    elif change == "missing":
        path.unlink()
    elif change == "fifo":
        path.unlink()
        os.mkfifo(path, mode=0o640)
    elif change == "invalid-utf8":
        path.write_bytes(b"\xff\xfe")
    else:
        path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with rejects("CONTROL_TRANSFER_STAGED_INPUT_INVALID"):
        materialize(value)
    assert not (value.workspace / "instructions").exists()


def test_stale_plan_record_and_wrong_manifest_revision_are_not_repaired(tmp_path: Path) -> None:
    value = fixture(tmp_path)
    value.plan_record.plan_sha256 = "sha256:" + "9" * 64
    with rejects("CONTROL_PLAN_HASH_MISMATCH"):
        materialize(value)
    value.plan_record.plan_sha256 = value.plan["plan_sha256"]
    value.bundle_record.manifest_artifact_revision_id = "rev_" + "9" * 32
    with rejects("CONTROL_BUNDLE_POINTER_INVALID"):
        materialize(value)


def test_v21_cannot_request_reference_bundle_or_unbound_step(tmp_path: Path) -> None:
    value = fixture(tmp_path)
    value.plan["steps"][0]["reference_bundle"] = value.plan["steps"][0]["instruction_bundle"]
    rehash(value.plan, "plan_sha256")
    value.plan_record.plan_sha256 = value.plan["plan_sha256"]
    with rejects("CONTROL_TRANSFER_CONTEXT_INVALID"):
        materialize(value)
    value = fixture(tmp_path / "other")
    with rejects("CONTROL_TRANSFER_CONTEXT_INVALID"):
        preflight_inference_transfer_materialization(
            value.session,
            plan_id=value.plan["plan_id"],
            step_key="unbound_step",
            context=value.context,
        )


def test_staged_named_file_replacement_after_final_fd_stat_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = fixture(tmp_path)
    input_path = value.workspace / "worker-input.json"
    replacement = value.workspace / "synthetic-replacement.json"
    replacement.write_bytes(input_path.read_bytes())
    replacement.chmod(0o640)
    original_fstat = os.fstat
    regular_stat_count = 0

    def fstat_then_replace(descriptor: int) -> os.stat_result:
        nonlocal regular_stat_count
        metadata = original_fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            regular_stat_count += 1
            if regular_stat_count == 2:
                # FD metadata has already been sampled, but the launch would open
                # this new inode even though it has identical bytes/owner/mode.
                os.replace(replacement, input_path)
        return metadata

    monkeypatch.setattr(os, "fstat", fstat_then_replace)
    with rejects("CONTROL_TRANSFER_STAGED_INPUT_INVALID"):
        materialize(value)
    assert regular_stat_count == 2
    assert not (value.workspace / "instructions").exists()
