from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts import (
    EducationalRetrievalRequirement,
    EvidenceBundlePublicationResultV2,
    EvidenceBundlePublicationResultV4,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError, ResolvedPlanDependencyEvidence
from eom_orchestrator.execution_resolver import (
    ExecutionStepRequirement,
    resolve_knowledge_backed_execution_plan,
    validate_educational_retrieval_policy,
)
from eom_workflow import ExecutionPresetRevisionV2
from eom_workflow.control_plane import WorkerRole

NOW = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)


def _artifact(seed: str, *, member_path: str, media_type: str, schema_ref: str) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "logical_name": member_path.rsplit("/", 1)[-1],
        "member_path": member_path,
    }


def _bundle(seed: str, family: str) -> dict[str, object]:
    manifest_artifact = _artifact(
        seed,
        member_path="projections/manifest.json",
        media_type="application/json",
        schema_ref="eom://schemas/workflow/bundle-manifest/1.0",
    )
    return {
        "bundle_id": f"{family}bundle_" + seed * 32,
        "bundle_revision_id": f"{family}rev_" + seed * 32,
        "manifest_artifact": {
            key: value for key, value in manifest_artifact.items() if key != "member_path"
        },
        "manifest_sha256": "sha256:" + seed * 64,
    }


def _requirement() -> EducationalRetrievalRequirement:
    return EducationalRetrievalRequirement(
        corpus_key="science-core",
        query_kind="ITEM_PREPARATION",
        curriculum_root_key="earth.plate-boundary",
        topic_keys=("earth.plate-boundary",),
        required_item_elements=("statement_set", "table"),
        source_classes=("APPROVED_ITEM", "TEXTBOOK"),
    )


def _preset() -> ExecutionPresetRevisionV2:
    value: dict[str, Any] = {
        "schema_version": "execution-preset-revision/2.0",
        "preset_id": "execpreset_" + "1" * 32,
        "preset_revision_id": "execpresetrev_" + "1" * 32,
        "revision_number": 2,
        "state": "RELEASED",
        "display_name": "Grounded item",
        "description": "Pins bounded evidence before a fresh item workflow.",
        "role_policies": [
            {
                "role": "authoring",
                "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
                "instruction_bundle": _bundle("2", "instr"),
                "reference_bundle": None,
                "worker_pool_key": "authoring",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
                "evidence_access": "EVIDENCE_CONTEXT",
            }
        ],
        "capacity_policy_revision_id": "capacityrev_" + "3" * 32,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": ["workflow-role/1.3.0"],
        "retrieval_policy": {
            "access_policy_revision_id": "accessrev_" + "4" * 32,
            "access_policy_sha256": "sha256:" + "4" * 64,
            "allowed_corpus_keys": ["science-core"],
            "allowed_query_kinds": ["ITEM_PREPARATION"],
            "allowed_source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
            "maximum_budget": {
                "max_documents": 4,
                "max_item_revisions": 4,
                "max_graph_nodes": 32,
                "max_claims": 16,
                "max_context_tokens": 8000,
            },
        },
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    value["content_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "content_sha256"}
    )
    return ExecutionPresetRevisionV2.model_validate(value)


def _evidence(
    *, manifest_schema_version: str = "2.0"
) -> EvidenceBundlePublicationResultV2 | EvidenceBundlePublicationResultV4:
    if manifest_schema_version not in {"2.0", "4.0"}:
        raise ValueError("unsupported test manifest schema version")
    graph = {
        "graph_id": "graph_" + "5" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "5" * 32,
        "manifest_artifact": _artifact(
            "5",
            member_path="projections/manifest.json",
            media_type="application/json",
            schema_ref="eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
        ),
        "manifest_sha256": "sha256:" + "5" * 64,
    }
    value: dict[str, Any] = {
        "schema_version": (
            "evidence-bundle-publication-result/4.0"
            if manifest_schema_version == "4.0"
            else "evidence-bundle-publication-result/2.0"
        ),
        "evidence_bundle_id": "evidence_" + "6" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "6" * 32,
        "revision_number": 1,
        "state": "PUBLISHED",
        "retrieval_request_id": "retrieval_" + "7" * 32,
        "retrieval_request_sha256": "sha256:" + "7" * 64,
        "graph_snapshot": graph,
        "access_policy_revision_id": "accessrev_" + "4" * 32,
        "access_policy_sha256": "sha256:" + "4" * 64,
        "requester_permissions_sha256": "sha256:" + "8" * 64,
        "manifest_artifact": _artifact(
            "9",
            member_path="evidence/manifest.json",
            media_type="application/json",
            schema_ref=f"eom://schemas/knowledge/evidence-bundle-manifest/{manifest_schema_version}",
        ),
        "manifest_sha256": "sha256:" + "a" * 64,
        "context_artifact": _artifact(
            "b",
            member_path="evidence/context.md",
            media_type="text/markdown",
            schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
        ),
        "budget": {
            "document_count": 1,
            "item_revision_count": 1,
            "graph_node_count": 2,
            "claim_count": 1,
            "estimated_context_tokens": 500,
        },
        "published_at": NOW.isoformat().replace("+00:00", "Z"),
        "result_sha256": "sha256:" + "0" * 64,
    }
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    if manifest_schema_version == "4.0":
        return EvidenceBundlePublicationResultV4.model_validate(value)
    return EvidenceBundlePublicationResultV2.model_validate(value)


class _Session:
    def __init__(self, preset: ExecutionPresetRevisionV2) -> None:
        self.preset = SimpleNamespace(
            preset_id=preset.preset_id,
            state="RELEASED",
            canonical_document=preset.model_dump(mode="json"),
        )

    def scalar(self, _statement: object) -> None:
        return None

    def get(self, model: type[object], identity: str) -> object | None:
        if (
            model is ExecutionPresetRevisionRecord
            and identity == self.preset.canonical_document["preset_revision_id"]
        ):
            return self.preset
        return None


def test_v2_preset_rejects_unapproved_retrieval_scope_before_publication() -> None:
    preset = _preset()
    denied = _requirement().model_copy(update={"corpus_key": "unapproved-corpus"})
    with pytest.raises(ControlPlaneError) as captured:
        validate_educational_retrieval_policy(preset, denied)
    assert captured.value.code == "CONTROL_RETRIEVAL_POLICY_DENIED"


def test_resolved_v3_plan_pins_evidence_and_role_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _preset()
    evidence = _evidence()
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "c" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.4.0",
        workflow_definition_sha256="sha256:" + "d" * 64,
        workflow_role_schema_version="workflow-role/1.3.0",
        content_pack_release_id="packrel_" + "e" * 32,
        content_pack_sha256="sha256:" + "f" * 64,
        graph_snapshot_revision_id=evidence.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=evidence.evidence_bundle_revision_id,
    )
    captured: dict[str, Any] = {}

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        captured.update(document)
        assert dependencies is not None
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    plan = resolve_knowledge_backed_execution_plan(
        _Session(preset),  # type: ignore[arg-type]
        preset_revision_id=preset.preset_revision_id,
        requirement=_requirement(),
        evidence=evidence,
        dependencies=dependencies,
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW,
    )
    assert plan.evidence_bundle_revision_id == evidence.evidence_bundle_revision_id
    assert plan.graph_snapshot == evidence.graph_snapshot
    assert plan.steps[0].evidence_access == "EVIDENCE_CONTEXT"
    assert plan.plan_sha256 == content_sha256(
        {key: item for key, item in captured.items() if key != "plan_sha256"}
    )


def test_resolved_v3_plan_accepts_current_multimodal_evidence_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _preset()
    evidence = _evidence(manifest_schema_version="4.0")
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "c" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.5.0",
        workflow_definition_sha256="sha256:" + "d" * 64,
        workflow_role_schema_version="workflow-role/1.12.0",
        content_pack_release_id="packrel_" + "e" * 32,
        content_pack_sha256="sha256:" + "f" * 64,
        graph_snapshot_revision_id=evidence.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=evidence.evidence_bundle_revision_id,
    )

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        assert document["evidence_manifest_artifact"]["schema_ref"] == (
            "eom://schemas/knowledge/evidence-bundle-manifest/4.0"
        )
        assert dependencies is not None
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    plan = resolve_knowledge_backed_execution_plan(
        _Session(preset),  # type: ignore[arg-type]
        preset_revision_id=preset.preset_revision_id,
        requirement=_requirement(),
        evidence=evidence,
        dependencies=dependencies,
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW,
    )

    assert plan.evidence_manifest_artifact.schema_ref == (
        "eom://schemas/knowledge/evidence-bundle-manifest/4.0"
    )


def test_v3_plan_rejects_stale_evidence_policy_before_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted = False

    def record(*_args: object, **_kwargs: object) -> object:
        nonlocal persisted
        persisted = True
        raise AssertionError("must not persist")

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    preset = _preset()
    evidence = _evidence().model_copy(update={"access_policy_sha256": "sha256:" + "0" * 64})
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "c" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.4.0",
        workflow_definition_sha256="sha256:" + "d" * 64,
        workflow_role_schema_version="workflow-role/1.3.0",
        content_pack_release_id="packrel_" + "e" * 32,
        content_pack_sha256="sha256:" + "f" * 64,
        graph_snapshot_revision_id=evidence.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=evidence.evidence_bundle_revision_id,
    )
    with pytest.raises(ControlPlaneError) as captured:
        resolve_knowledge_backed_execution_plan(
            _Session(preset),  # type: ignore[arg-type]
            preset_revision_id=preset.preset_revision_id,
            requirement=_requirement(),
            evidence=evidence,
            dependencies=dependencies,
            steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
            resolved_at=NOW,
        )
    assert captured.value.code == "CONTROL_PLAN_DEPENDENCY_MISMATCH"
    assert not persisted


def test_v3_plan_replay_uses_only_the_pinned_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _preset()
    evidence = _evidence()
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "c" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.4.0",
        workflow_definition_sha256="sha256:" + "d" * 64,
        workflow_role_schema_version="workflow-role/1.3.0",
        content_pack_release_id="packrel_" + "e" * 32,
        content_pack_sha256="sha256:" + "f" * 64,
        graph_snapshot_revision_id=evidence.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=evidence.evidence_bundle_revision_id,
    )
    recorded: dict[str, Any] = {}

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        del dependencies
        recorded.update(document)
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    original = resolve_knowledge_backed_execution_plan(
        _Session(preset),  # type: ignore[arg-type]
        preset_revision_id=preset.preset_revision_id,
        requirement=_requirement(),
        evidence=evidence,
        dependencies=dependencies,
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW,
    )

    class ReplaySession:
        def scalar(self, _statement: object) -> object:
            return SimpleNamespace(canonical_document=dict(recorded))

        def get(self, _model: type[object], _identity: str) -> object:
            raise AssertionError("replay must not resolve a current preset")

    replayed = resolve_knowledge_backed_execution_plan(
        ReplaySession(),  # type: ignore[arg-type]
        preset_revision_id="execpresetrev_" + "0" * 32,
        requirement=_requirement().model_copy(update={"corpus_key": "changed-corpus"}),
        evidence=evidence.model_copy(
            update={"evidence_bundle_revision_id": "evidencerev_" + "0" * 32}
        ),
        dependencies=dependencies,
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW,
    )
    assert replayed == original
    assert replayed.evidence_bundle_revision_id == evidence.evidence_bundle_revision_id
    assert replayed.preset_revision_id == preset.preset_revision_id
