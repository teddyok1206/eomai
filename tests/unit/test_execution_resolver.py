from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from eom_orchestrator.control_models import ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    compute_control_document_hash,
)
from eom_orchestrator.execution_resolver import (
    ExecutionStepRequirement,
    resolve_execution_plan,
)
from eom_workflow.control_plane import WorkerRole

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
ZERO_SHA = "sha256:" + "0" * 64


class FakeSession:
    def __init__(self, scalar_values: list[object | None], revision: object | None) -> None:
        self.scalar_values = iter(scalar_values)
        self.revision = revision

    def scalar(self, _statement: object) -> object | None:
        return next(self.scalar_values)

    def get(self, model: type[object], _identity: str) -> object | None:
        assert model is ExecutionPresetRevisionRecord
        return self.revision


def _bundle(seed: str, *, family: str) -> dict[str, object]:
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


def _preset() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "1" * 32,
        "preset_revision_id": "execpresetrev_" + "1" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "Standard item",
        "description": "A measured immutable execution policy.",
        "role_policies": [
            {
                "role": "authoring",
                "model_candidates": [
                    {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
                    {"model": "gpt-5.6-luna", "reasoning_effort": "medium"},
                ],
                "instruction_bundle": _bundle("2", family="instr"),
                "reference_bundle": _bundle("3", family="ref"),
                "worker_pool_key": "authoring",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
            }
        ],
        "capacity_policy_revision_id": "capacityrev_" + "4" * 32,
        "general_knowledge_policy": "ALLOW_WITH_PROVENANCE",
        "compatible_workflow_protocols": ["workflow-role/1.3.0"],
        "content_sha256": ZERO_SHA,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    value["content_sha256"] = compute_control_document_hash(value, "content_sha256")
    return value


def _dependencies() -> ResolvedPlanDependencyEvidence:
    return ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "5" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.4.0",
        workflow_definition_sha256="sha256:" + "6" * 64,
        workflow_role_schema_version="workflow-role/1.3.0",
        content_pack_release_id="packrel_" + "7" * 32,
        content_pack_sha256="sha256:" + "8" * 64,
    )


def test_resolver_selects_only_the_ordered_primary_candidate_and_records_exact_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _preset()
    logical = SimpleNamespace(
        state="ACTIVE",
        current_revision_id=preset["preset_revision_id"],
        preset_id=preset["preset_id"],
    )
    revision = SimpleNamespace(
        preset_id=preset["preset_id"],
        state="RELEASED",
        canonical_document=preset,
    )
    session = FakeSession([None, logical], revision)
    captured: dict[str, object] = {}

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        captured["document"] = document
        captured["dependencies"] = dependencies
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_resolved_execution_plan", record
    )
    result = resolve_execution_plan(
        session,  # type: ignore[arg-type]
        preset_key="standard-item",
        dependencies=_dependencies(),
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW,
    )

    assert result.steps[0].model == "gpt-5.6-terra"
    assert result.steps[0].reasoning_effort == "high"
    assert result.plan_sha256 == compute_control_document_hash(
        captured["document"],  # type: ignore[arg-type]
        "plan_sha256",
    )
    assert result.steps[0].general_knowledge_mode == "ALLOWED_WITH_PROVENANCE"


def test_resolver_fails_closed_when_required_role_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _preset()
    logical = SimpleNamespace(
        state="ACTIVE",
        current_revision_id=preset["preset_revision_id"],
        preset_id=preset["preset_id"],
    )
    revision = SimpleNamespace(
        preset_id=preset["preset_id"],
        state="RELEASED",
        canonical_document=preset,
    )
    session = FakeSession([None, logical], revision)
    persisted = False

    def record(*_args: object, **_kwargs: object) -> object:
        nonlocal persisted
        persisted = True
        raise AssertionError("must not persist")

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_resolved_execution_plan", record
    )
    with pytest.raises(ControlPlaneError) as captured:
        resolve_execution_plan(
            session,  # type: ignore[arg-type]
            preset_key="standard-item",
            dependencies=_dependencies(),
            steps=(ExecutionStepRequirement("review", WorkerRole.REVIEW),),
            resolved_at=NOW,
        )
    assert captured.value.code == "CONTROL_PRESET_ROLE_MISSING"
    assert not persisted


def test_resolver_returns_existing_plan_without_consulting_current_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _preset()
    logical = SimpleNamespace(
        state="ACTIVE",
        current_revision_id=preset["preset_revision_id"],
        preset_id=preset["preset_id"],
    )
    revision = SimpleNamespace(
        preset_id=preset["preset_id"],
        state="RELEASED",
        canonical_document=preset,
    )
    creating = FakeSession([None, logical], revision)
    captured: dict[str, Any] = {}

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        del dependencies
        captured.update(document)
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_resolved_execution_plan", record
    )
    first = resolve_execution_plan(
        creating,  # type: ignore[arg-type]
        preset_key="standard-item",
        dependencies=_dependencies(),
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW,
    )
    existing = SimpleNamespace(canonical_document=first.model_dump(mode="json"))
    replay = resolve_execution_plan(
        FakeSession([existing], None),  # type: ignore[arg-type]
        preset_key="retired-or-renamed",
        dependencies=_dependencies(),
        steps=(ExecutionStepRequirement("review", WorkerRole.REVIEW),),
        resolved_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    assert replay == first
