from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
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


def _analysis_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fixture = _fixture(tmp_path, monkeypatch)
    session = fixture["session"]
    assert isinstance(session, FakeSession)
    old_record = session.records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    old_plan = old_record.canonical_document
    source_artifact_id = "artifact_" + "d" * 32
    source_revision_id = "rev_" + "e" * 32
    source_payload = b"Pinned source data, not worker instructions.\n"
    source_hash = sha256_bytes(source_payload)
    source_root = fixture["artifact_root"] / source_artifact_id / source_revision_id
    source_root.mkdir(parents=True)
    source_path = source_root / "source.txt"
    source_path.write_bytes(source_payload)
    session.records[(ArtifactRecord, source_artifact_id)] = SimpleNamespace(approved=True)
    session.records[(ArtifactRevisionRecord, source_revision_id)] = SimpleNamespace(
        approved=True,
        logical_artifact_id=source_artifact_id,
        nas_path=str(source_root),
        manifest={
            "files": [
                {
                    "file_name": "source.txt",
                    "sha256": source_hash,
                    "bytes": len(source_payload),
                    "media_type": "text/plain",
                }
            ]
        },
    )
    instruction_pointer = old_plan["steps"][0]["instruction_bundle"]
    analysis_plan = {
        "schema_version": "resolved-execution-plan/2.0",
        "plan_id": old_plan["plan_id"],
        "workflow_id": old_plan["workflow_id"],
        "workload_class": "KNOWLEDGE_ANALYSIS",
        "preset_id": old_plan["preset_id"],
        "preset_revision_id": old_plan["preset_revision_id"],
        "preset_sha256": old_plan["preset_sha256"],
        "workflow_definition_key": "knowledge-analysis",
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": old_plan["workflow_definition_sha256"],
        "analysis_request_id": "knowledgeanalysis_" + "1" * 32,
        "analysis_request_sha256": "sha256:" + "2" * 64,
        "source_artifact_id": source_artifact_id,
        "source_artifact_revision_id": source_revision_id,
        "source_member_path": "source.txt",
        "source_materialized_path": "source/source.txt",
        "source_sha256": source_hash,
        "source_bytes": len(source_payload),
        "source_media_type": "text/plain",
        "source_schema_ref": None,
        "capacity_policy_revision_id": old_plan["capacity_policy_revision_id"],
        "steps": [
            {
                "step_key": "analyze",
                "role": "support",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "instruction_bundle": instruction_pointer,
                "reference_bundle": None,
                "worker_pool_key": "support",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "DENIED",
            }
        ],
        "resolver_version": "2.0.0",
        "resolved_at": "2026-08-23T12:00:00Z",
        "plan_sha256": ZERO_SHA,
    }
    analysis_plan["plan_sha256"] = compute_control_document_hash(analysis_plan, "plan_sha256")
    session.records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))] = SimpleNamespace(
        canonical_document=analysis_plan,
        plan_sha256=analysis_plan["plan_sha256"],
    )
    fixture.update(
        {
            "authorized": frozenset((*fixture["authorized"], source_revision_id)),
            "source_path": source_path,
            "source_revision_id": source_revision_id,
            "source_hash": source_hash,
            "source_payload": source_payload,
        }
    )
    return fixture


def test_knowledge_materializer_stages_only_exact_context_and_records_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    authorized = authorized_execution_artifact_revisions(
        fixture["session"], plan_id=str(fixture["plan_id"]), step_key="authoring"
    )
    assert fixture["manifest_revision_id"] in authorized
    assert fixture["context_revision_id"] in authorized
    workspace = _workspace(tmp_path, "knowledge")
    result = materialize_execution_step(
        fixture["session"],
        plan_id=str(fixture["plan_id"]),
        step_key="authoring",
        workspace=workspace,
        canonical_artifact_root=fixture["artifact_root"],
        worker_group_id=GROUP_ID,
        authorized_artifact_revision_ids=authorized,
    )
    assert (workspace / "references/evidence/context.md").read_bytes() == fixture["context_payload"]
    assert not (workspace / "evidence/manifest.json").exists()
    assert result.evidence_bundle_revision_id == fixture["manifest"]["evidence_bundle_revision_id"]
    assert result.evidence_manifest_sha256 == fixture["manifest"]["manifest_sha256"]
    assert result.evidence_context_sha256 == sha256_bytes(fixture["context_payload"])
    assert all("path" not in key for key in result.event_data())


def test_knowledge_materializer_rejects_manifest_hash_drift_before_context_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    manifest_record = fixture["session"].records[
        (ArtifactRevisionRecord, fixture["manifest_revision_id"])
    ]
    manifest_path = Path(manifest_record.nas_path) / "evidence/manifest.json"
    manifest_path.write_bytes(b"{}")
    workspace = _workspace(tmp_path, "knowledge")
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
    assert captured.value.code in {"CONTROL_POINTER_FILE_INVALID", "CONTROL_POINTER_HASH_MISMATCH"}
    assert not (workspace / "references/evidence/context.md").exists()


def _knowledge_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fixture = _fixture(tmp_path, monkeypatch)
    session = fixture["session"]
    assert isinstance(session, FakeSession)
    old_record = session.records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    old_plan = old_record.canonical_document
    for step_pointer, kind in (
        (old_plan["steps"][0]["instruction_bundle"], "INSTRUCTION"),
        (old_plan["steps"][0]["reference_bundle"], "REFERENCE"),
    ):
        bundle_record = session.records[
            (ExecutionBundleRevisionRecord, step_pointer["bundle_revision_id"])
        ]
        assert bundle_record.bundle_kind == kind
        bundle_record.manifest_artifact_revision_id = step_pointer["manifest_artifact"][
            "artifact_revision_id"
        ]
    context_payload = b"# Bounded evidence\n\nPinned pointers only.\n"
    context_hash = sha256_bytes(context_payload)
    context_artifact_id = "artifact_" + "d" * 32
    context_revision_id = "rev_" + "d" * 32
    context_root = fixture["artifact_root"] / context_artifact_id / context_revision_id
    context_root.mkdir(parents=True)
    (context_root / "evidence").mkdir()
    (context_root / "evidence/context.md").write_bytes(context_payload)
    context_pointer = {
        "artifact_id": context_artifact_id,
        "artifact_revision_id": context_revision_id,
        "sha256": context_hash,
        "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
        "media_type": "text/markdown",
        "logical_name": "context.md",
        "member_path": "evidence/context.md",
    }
    graph_pointer = {
        "graph_id": "graph_" + "e" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "e" * 32,
            "artifact_revision_id": "rev_" + "e" * 32,
            "sha256": "sha256:" + "e" * 64,
            "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
            "member_path": "projections/manifest.json",
        },
        "manifest_sha256": "sha256:" + "e" * 64,
    }
    permissions_hash = content_sha256({"permission_keys": ["knowledge_graph:retrieve"]})
    source_member = {
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "a" * 32,
        "member_path": "source/content.json",
        "materialized_path": "source/content.json",
        "sha256": "sha256:" + "a" * 64,
        "bytes": 512,
        "schema_ref": "eom.assessment.item-content/1.0",
        "media_type": "application/json",
        "logical_name": "content.json",
    }
    manifest: dict[str, Any] = {
        "schema_version": "evidence-bundle-manifest/2.0",
        "evidence_bundle_id": "evidence_" + "f" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "f" * 32,
        "revision_number": 1,
        "retrieval_request_id": "retrieval_" + "1" * 32,
        "retrieval_request_sha256": "sha256:" + "1" * 64,
        "graph_snapshot": graph_pointer,
        "access_policy_revision_id": "accessrev_" + "2" * 32,
        "access_policy_sha256": "sha256:" + "2" * 64,
        "requester_permissions_sha256": permissions_hash,
        "materials": {"context_markdown": context_pointer},
        "entries": [
            {
                "evidence_id": "evidenceitem_" + "3" * 32,
                "evidence_kind": "ITEM_REVISION",
                "use": "AVOID_COPY",
                "source": {
                    "source_kind": "APPROVED_ITEM_REVISION",
                    "source_class": "APPROVED_ITEM",
                    "item_id": "item_" + "4" * 32,
                    "item_revision_id": "itemrev_" + "4" * 32,
                    "lifecycle_state": "APPROVED",
                    "artifact_member": source_member,
                },
                "graph_node_ids": ["knode_item"],
                "anchor_ids": ["anchor_item"],
                "relevance_milli": 900,
                "answer_bearing": True,
            }
        ],
        "budget": {
            "document_count": 0,
            "item_revision_count": 1,
            "graph_node_count": 1,
            "claim_count": 0,
            "estimated_context_tokens": 100,
        },
        "manifest_sha256": ZERO_SHA,
        "created_at": "2026-08-24T03:00:00Z",
    }
    manifest["manifest_sha256"] = content_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    manifest_payload = canonical_json_bytes(manifest)
    manifest_content_hash = sha256_bytes(manifest_payload)
    manifest_artifact_id = "artifact_" + "b" * 32
    manifest_revision_id = "rev_" + "b" * 32
    manifest_root = fixture["artifact_root"] / manifest_artifact_id / manifest_revision_id
    manifest_root.mkdir(parents=True)
    (manifest_root / "evidence").mkdir()
    (manifest_root / "evidence/manifest.json").write_bytes(manifest_payload)
    manifest_pointer = {
        "artifact_id": manifest_artifact_id,
        "artifact_revision_id": manifest_revision_id,
        "sha256": manifest_content_hash,
        "schema_ref": "eom://schemas/knowledge/evidence-bundle-manifest/2.0",
        "media_type": "application/json",
        "logical_name": "manifest.json",
        "member_path": "evidence/manifest.json",
    }
    for artifact_id, revision_id, root, payload, pointer in (
        (
            context_artifact_id,
            context_revision_id,
            context_root,
            context_payload,
            context_pointer,
        ),
        (
            manifest_artifact_id,
            manifest_revision_id,
            manifest_root,
            manifest_payload,
            manifest_pointer,
        ),
    ):
        session.records[(ArtifactRecord, artifact_id)] = SimpleNamespace(approved=True)
        session.records[(ArtifactRevisionRecord, revision_id)] = SimpleNamespace(
            approved=True,
            logical_artifact_id=artifact_id,
            content_hash=pointer["sha256"],
            nas_path=str(root),
            manifest={
                "files": [
                    {
                        "file_name": pointer["member_path"],
                        "sha256": pointer["sha256"],
                        "bytes": len(payload),
                        "media_type": pointer["media_type"],
                        "schema_ref": pointer["schema_ref"],
                    }
                ]
            },
        )
    knowledge_plan: dict[str, Any] = {
        "schema_version": "resolved-execution-plan/3.0",
        "plan_id": old_plan["plan_id"],
        "workflow_id": old_plan["workflow_id"],
        "workload_class": "KNOWLEDGE_BACKED_ITEM",
        "preset_id": old_plan["preset_id"],
        "preset_revision_id": old_plan["preset_revision_id"],
        "preset_sha256": old_plan["preset_sha256"],
        "workflow_definition_key": old_plan["workflow_definition_key"],
        "workflow_definition_version": old_plan["workflow_definition_version"],
        "workflow_definition_sha256": old_plan["workflow_definition_sha256"],
        "content_pack_release_id": old_plan["content_pack_release_id"],
        "content_pack_sha256": old_plan["content_pack_sha256"],
        "capacity_policy_revision_id": old_plan["capacity_policy_revision_id"],
        "retrieval_requirement": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "science-core",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": "earth.plate-boundary",
            "topic_keys": ["earth.plate-boundary"],
            "required_item_elements": ["statement_set", "table"],
            "source_classes": ["APPROVED_ITEM"],
        },
        "retrieval_requirement_sha256": ZERO_SHA,
        "retrieval_request_id": manifest["retrieval_request_id"],
        "retrieval_request_sha256": manifest["retrieval_request_sha256"],
        "graph_snapshot": graph_pointer,
        "access_policy_revision_id": manifest["access_policy_revision_id"],
        "access_policy_sha256": manifest["access_policy_sha256"],
        "requester_permissions_sha256": permissions_hash,
        "evidence_bundle_id": manifest["evidence_bundle_id"],
        "evidence_bundle_revision_id": manifest["evidence_bundle_revision_id"],
        "evidence_manifest_artifact": manifest_pointer,
        "evidence_manifest_sha256": manifest["manifest_sha256"],
        "evidence_context_artifact": context_pointer,
        "steps": [{**old_plan["steps"][0], "evidence_access": "EVIDENCE_CONTEXT"}],
        "resolver_version": "3.0.0",
        "resolved_at": "2026-08-24T03:00:00Z",
        "plan_sha256": ZERO_SHA,
    }
    knowledge_plan["retrieval_requirement_sha256"] = content_sha256(
        knowledge_plan["retrieval_requirement"]
    )
    knowledge_plan["plan_sha256"] = content_sha256(
        {key: value for key, value in knowledge_plan.items() if key != "plan_sha256"}
    )
    session.records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))] = SimpleNamespace(
        canonical_document=knowledge_plan,
        plan_sha256=knowledge_plan["plan_sha256"],
    )
    fixture.update(
        {
            "authorized": frozenset(
                (*fixture["authorized"], manifest_revision_id, context_revision_id)
            ),
            "context_payload": context_payload,
            "manifest_revision_id": manifest_revision_id,
            "context_revision_id": context_revision_id,
            "manifest": manifest,
        }
    )
    return fixture


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


def test_analysis_materializer_stages_one_pinned_source_without_reference_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _analysis_fixture(tmp_path, monkeypatch)
    workspace = _workspace(tmp_path, "analysis")
    result = materialize_execution_step(
        fixture["session"],
        plan_id=str(fixture["plan_id"]),
        step_key="analyze",
        workspace=workspace,
        canonical_artifact_root=fixture["artifact_root"],
        worker_group_id=GROUP_ID,
        authorized_artifact_revision_ids=fixture["authorized"],
    )
    assert (workspace / "source/source.txt").read_bytes() == fixture["source_payload"]
    assert not (workspace / "references").exists()
    assert result.source_artifact_revision_id == fixture["source_revision_id"]
    assert result.source_sha256 == fixture["source_hash"]
    assert result.materialized_member_count == 3
    assert stat.S_IMODE((workspace / "source/source.txt").stat().st_mode) == 0o640


def test_analysis_materializer_rejects_hardlinked_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _analysis_fixture(tmp_path, monkeypatch)
    os.link(fixture["source_path"], tmp_path / "second-link")
    with pytest.raises(ControlPlaneError) as captured:
        materialize_execution_step(
            fixture["session"],
            plan_id=str(fixture["plan_id"]),
            step_key="analyze",
            workspace=_workspace(tmp_path, "analysis"),
            canonical_artifact_root=fixture["artifact_root"],
            worker_group_id=GROUP_ID,
            authorized_artifact_revision_ids=fixture["authorized"],
        )
    assert captured.value.code == "CONTROL_POINTER_FILE_INVALID"
