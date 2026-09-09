from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import eom_catalog_service.legacy_extraction_preset_resolution as resolution_module
import eom_orchestrator.legacy_item_extraction_bootstrap as bootstrap_module
import pytest
from eom_catalog_contracts import LegacyExtractionPresetPointer
from eom_catalog_service.legacy_extraction_preset_resolution import (
    LegacyExtractionPresetResolutionError,
    resolve_legacy_extraction_preset_pointer,
)
from eom_orchestrator.control_models import (
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.legacy_item_extraction_bootstrap import (
    LegacyItemExtractionBootstrapManifest,
    LegacyItemExtractionBootstrapPredecessor,
    _require_successor_preflight,
)
from eom_orchestrator.models import ProtocolVersionRecord
from eom_orchestrator.preset_lifecycle import execution_preset_policy_sha256
from eom_workflow import compile_definition_data
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import WorkflowDefinitionRecord
from sqlalchemy.orm import Session


class _PointerSession:
    def __init__(self, rows: dict[tuple[object, str], SimpleNamespace]) -> None:
        self.rows = rows

    def get(self, model: object, identity: str) -> object | None:
        return self.rows.get((model, identity))


class _PreflightSession(_PointerSession):
    def __init__(
        self,
        rows: dict[tuple[object, str], SimpleNamespace],
        *,
        preset_id: str,
    ) -> None:
        super().__init__(rows)
        self.preset_id = preset_id

    def scalar(self, _statement: object) -> object | None:
        return self.rows.get((ExecutionPresetRecord, self.preset_id))


def _artifact_pointer(
    seed: str, *, logical_name: str, schema_ref: str, media_type: str
) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "logical_name": logical_name,
    }


def _fixture() -> tuple[
    LegacyExtractionPresetPointer,
    dict[tuple[object, str], SimpleNamespace],
]:
    preset_id = "execpreset_" + "1" * 32
    preset_revision_id = "execpresetrev_" + "2" * 32
    bundle_id = "instrbundle_" + "3" * 32
    bundle_revision_id = "instrrev_" + "4" * 32
    capacity_id = "capacity_" + "5" * 32
    capacity_revision_id = "capacityrev_" + "6" * 32
    workflow_id = "wfdef_" + "7" * 32
    role_schema_version = "workflow-role/1.14.0"

    platform = _artifact_pointer(
        "8",
        logical_name="platform.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        media_type="text/markdown",
    )
    role = _artifact_pointer(
        "9",
        logical_name="legacy-item-extraction.md",
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        media_type="text/markdown",
    )
    instruction: dict[str, Any] = {
        "schema_version": "instruction-bundle-manifest/1.0",
        "bundle_id": bundle_id,
        "bundle_revision_id": bundle_revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "components": [
            {
                "layer": "PLATFORM",
                "relative_path": "instructions/platform.md",
                "artifact": platform,
            },
            {
                "layer": "ROLE",
                "relative_path": "instructions/legacy-item-extraction.md",
                "artifact": role,
            },
        ],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": "2026-09-09T05:30:00Z",
    }
    instruction["content_sha256"] = compute_control_document_hash(
        instruction,
        "content_sha256",
    )
    manifest_artifact = _artifact_pointer(
        "a",
        logical_name="instruction-bundle.json",
        schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
        media_type="application/json",
    )

    capacity: dict[str, Any] = {
        "schema_version": "worker-capacity-policy/1.2",
        "capacity_policy_id": capacity_id,
        "capacity_policy_revision_id": capacity_revision_id,
        "revision_number": 3,
        "state": "RELEASED",
        "max_configured_slots": 6,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 2,
        "pools": [
            {
                "pool_key": "authoring",
                "roles": ["authoring"],
                "slot_keys": ["slot01"],
                "max_active": 1,
            },
            {"pool_key": "review", "roles": ["review"], "slot_keys": ["slot02"], "max_active": 1},
            {"pool_key": "image", "roles": ["image"], "slot_keys": ["slot03"], "max_active": 1},
            {
                "pool_key": "item-management",
                "roles": ["item_management"],
                "slot_keys": ["slot04"],
                "max_active": 1,
            },
            {"pool_key": "support", "roles": ["support"], "slot_keys": ["slot05"], "max_active": 1},
            {
                "pool_key": "legacy-extraction",
                "roles": ["support"],
                "slot_keys": ["slot06"],
                "max_active": 1,
            },
        ],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": "2026-09-01T00:00:00Z",
    }
    capacity["content_sha256"] = compute_control_document_hash(capacity, "content_sha256")

    workflow: dict[str, Any] = {
        "schema_version": "1.0",
        "definition_key": "legacy-item-extraction",
        "definition_version": "1.0.0",
        "start_step": "extract",
        "limits": {"max_rework_cycles": 0, "max_step_attempts": 1},
        "steps": [
            {
                "key": "extract",
                "type": "agent",
                "worker_role": "support",
                "result_schema": "legacy-item-extraction-result@1.0",
                "on_success": "complete",
            },
            {"key": "complete", "type": "terminal", "terminal_status": "COMPLETED"},
        ],
    }
    workflow_hash = compile_definition_data(workflow, "fixture", {"support"}).sha256

    preset: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": preset_id,
        "preset_revision_id": preset_revision_id,
        "revision_number": 4,
        "state": "RELEASED",
        "display_name": "Legacy extraction",
        "description": "Exact validation recovery fixture",
        "role_policies": [
            {
                "role": "support",
                "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"}],
                "instruction_bundle": {
                    "bundle_id": bundle_id,
                    "bundle_revision_id": bundle_revision_id,
                    "manifest_artifact": manifest_artifact,
                    "manifest_sha256": manifest_artifact["sha256"],
                },
                "reference_bundle": None,
                "worker_pool_key": "legacy-extraction",
                "timeout_seconds": 7200,
                "sandbox": "read-only",
                "network": "disabled",
            }
        ],
        "capacity_policy_revision_id": capacity_revision_id,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": [role_schema_version],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": "2026-09-09T05:32:00Z",
    }
    preset["content_sha256"] = compute_control_document_hash(preset, "content_sha256")
    preset_policy_sha256 = execution_preset_policy_sha256(preset)
    pointer = LegacyExtractionPresetPointer(
        preset_id=preset_id,
        preset_revision_id=preset_revision_id,
        preset_revision_number=4,
        preset_sha256=cast(str, preset["content_sha256"]),
        preset_policy_sha256=preset_policy_sha256,
        capacity_policy_revision_id=capacity_revision_id,
        capacity_policy_sha256=cast(str, capacity["content_sha256"]),
        instruction_bundle_id=bundle_id,
        instruction_bundle_revision_id=bundle_revision_id,
        instruction_revision_number=1,
        instruction_manifest_sha256=manifest_artifact["sha256"],
        instruction_content_sha256=cast(str, instruction["content_sha256"]),
        workflow_definition_id=workflow_id,
        workflow_definition_version="1.0.0",
        workflow_definition_sha256=workflow_hash,
        role_schema_version=role_schema_version,
        role_schema_sha256=role_schema_bundle_hash(role_schema_version),
    )
    rows: dict[tuple[object, str], SimpleNamespace] = {
        (ExecutionPresetRecord, preset_id): SimpleNamespace(
            preset_id=preset_id,
            preset_key="legacy-item-extraction",
            current_revision_id=preset_revision_id,
            state="ACTIVE",
        ),
        (ExecutionPresetRevisionRecord, preset_revision_id): SimpleNamespace(
            preset_revision_id=preset_revision_id,
            preset_id=preset_id,
            revision_number=4,
            schema_version=preset["schema_version"],
            state="RELEASED",
            display_name=preset["display_name"],
            description=preset["description"],
            capacity_policy_revision_id=capacity_revision_id,
            general_knowledge_policy="DENY",
            compatible_workflow_protocols=[role_schema_version],
            content_sha256=preset["content_sha256"],
            canonical_document=preset,
        ),
        (ExecutionBundleRecord, bundle_id): SimpleNamespace(
            bundle_id=bundle_id,
            bundle_kind="INSTRUCTION",
            bundle_key="legacy-item-extraction-support",
            current_revision_id=bundle_revision_id,
            state="ACTIVE",
        ),
        (ExecutionBundleRevisionRecord, bundle_revision_id): SimpleNamespace(
            bundle_revision_id=bundle_revision_id,
            bundle_id=bundle_id,
            bundle_kind="INSTRUCTION",
            revision_number=1,
            schema_version=instruction["schema_version"],
            state="RELEASED",
            manifest_artifact_id=manifest_artifact["artifact_id"],
            manifest_artifact_revision_id=manifest_artifact["artifact_revision_id"],
            manifest_sha256=manifest_artifact["sha256"],
            content_sha256=instruction["content_sha256"],
            canonical_document=instruction,
        ),
        (WorkerCapacityPolicyRevisionRecord, capacity_revision_id): SimpleNamespace(
            capacity_policy_revision_id=capacity_revision_id,
            capacity_policy_id=capacity_id,
            revision_number=3,
            schema_version=capacity["schema_version"],
            state="RELEASED",
            max_configured_slots=6,
            max_active_codex=3,
            max_active_per_slot=1,
            max_active_gpu=1,
            max_active_knowledge_analysis=2,
            content_sha256=capacity["content_sha256"],
            canonical_document=capacity,
        ),
        (ProtocolVersionRecord, role_schema_version): SimpleNamespace(
            version=role_schema_version,
            schema_sha256=pointer.role_schema_sha256,
        ),
        (WorkflowDefinitionRecord, workflow_id): SimpleNamespace(
            definition_id=workflow_id,
            definition_key="legacy-item-extraction",
            definition_version="1.0.0",
            schema_version="1.0",
            canonical_definition=workflow,
            definition_hash=workflow_hash,
            active=True,
            source_path="fixture",
        ),
    }
    return pointer, rows


def _allow_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resolution_module,
        "resolve_control_artifact_pointer",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )


def _successor_manifest(
    pointer: LegacyExtractionPresetPointer,
    rows: dict[tuple[object, str], SimpleNamespace],
) -> LegacyItemExtractionBootstrapManifest:
    instruction = rows[
        (ExecutionBundleRevisionRecord, pointer.instruction_bundle_revision_id)
    ].canonical_document
    components = {component["layer"]: component for component in instruction["components"]}
    predecessor = LegacyItemExtractionBootstrapPredecessor(
        preset_id=pointer.preset_id,
        preset_revision_id=pointer.preset_revision_id,
        preset_revision_number=pointer.preset_revision_number,
        preset_content_sha256=pointer.preset_sha256,
        preset_policy_sha256=pointer.preset_policy_sha256,
        capacity_policy_revision_id=pointer.capacity_policy_revision_id,
        capacity_policy_sha256=pointer.capacity_policy_sha256,
        instruction_bundle_id=pointer.instruction_bundle_id,
        instruction_bundle_revision_id=pointer.instruction_bundle_revision_id,
        instruction_revision_number=pointer.instruction_revision_number,
        instruction_manifest_sha256=pointer.instruction_manifest_sha256,
        instruction_content_sha256=pointer.instruction_content_sha256,
        platform_instruction_sha256=components["PLATFORM"]["artifact"]["sha256"],
        role_instruction_sha256=components["ROLE"]["artifact"]["sha256"],
        workflow_definition_id=pointer.workflow_definition_id,
        workflow_definition_version="1.0.0",
        workflow_definition_sha256=pointer.workflow_definition_sha256,
        role_schema_version="workflow-role/1.14.0",
        role_schema_sha256=pointer.role_schema_sha256,
    )
    preset = rows[(ExecutionPresetRevisionRecord, pointer.preset_revision_id)]
    return LegacyItemExtractionBootstrapManifest(
        schema_version="legacy-item-extraction-control-bootstrap/2.0",
        preset_key="legacy-item-extraction",
        display_name=preset.display_name,
        description=preset.description,
        created_at=datetime(2026, 9, 9, 5, 30, tzinfo=UTC),
        model="gpt-5.6-terra",
        reasoning_effort="xhigh",
        general_knowledge_policy="DENY",
        compatible_workflow_protocols=("workflow-role/1.14.0",),
        platform_instruction_path="instructions/platform.md",
        role_instruction_path="instructions/legacy-item-extraction.md",
        slot_key="slot06",
        worker_pool_key="legacy-extraction",
        timeout_seconds=7200,
        instruction_revision_number=pointer.instruction_revision_number + 1,
        predecessor=predecessor,
    )


def _resolve(
    pointer: LegacyExtractionPresetPointer,
    rows: dict[tuple[object, str], SimpleNamespace],
    *,
    require_current: bool = True,
) -> object:
    return resolve_legacy_extraction_preset_pointer(
        cast(Session, _PointerSession(rows)),
        pointer,
        require_current=require_current,
    )


def test_exact_preset_dependency_graph_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)

    resolved = _resolve(pointer, rows)

    assert resolved.preset_revision_id == pointer.preset_revision_id
    assert resolved.content_sha256 == pointer.preset_sha256


@pytest.mark.parametrize(
    ("model", "identity_field"),
    (
        (ExecutionPresetRecord, "preset_id"),
        (ExecutionPresetRevisionRecord, "preset_revision_id"),
        (ExecutionBundleRecord, "instruction_bundle_id"),
        (ExecutionBundleRevisionRecord, "instruction_bundle_revision_id"),
        (WorkerCapacityPolicyRevisionRecord, "capacity_policy_revision_id"),
        (ProtocolVersionRecord, "role_schema_version"),
        (WorkflowDefinitionRecord, "workflow_definition_id"),
    ),
)
def test_exact_preset_dependency_graph_rejects_each_missing_pointer(
    monkeypatch: pytest.MonkeyPatch,
    model: object,
    identity_field: str,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    rows.pop((model, cast(str, getattr(pointer, identity_field))))

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_POINTER_STALE"


@pytest.mark.parametrize(
    "target",
    (
        "PRESET_LOGICAL",
        "PRESET_REVISION",
        "BUNDLE_LOGICAL",
        "INSTRUCTION_REVISION",
        "CAPACITY",
        "PROTOCOL",
        "WORKFLOW",
    ),
)
def test_exact_preset_dependency_graph_rejects_stale_rows(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    if target == "PRESET_LOGICAL":
        rows[(ExecutionPresetRecord, pointer.preset_id)].preset_id = "execpreset_" + "f" * 32
    elif target == "PRESET_REVISION":
        rows[(ExecutionPresetRevisionRecord, pointer.preset_revision_id)].preset_id = (
            "execpreset_" + "f" * 32
        )
    elif target == "BUNDLE_LOGICAL":
        rows[(ExecutionBundleRecord, pointer.instruction_bundle_id)].bundle_id = (
            "instrbundle_" + "f" * 32
        )
    elif target == "INSTRUCTION_REVISION":
        rows[(ExecutionBundleRevisionRecord, pointer.instruction_bundle_revision_id)].bundle_id = (
            "instrbundle_" + "f" * 32
        )
    elif target == "CAPACITY":
        rows[
            (WorkerCapacityPolicyRevisionRecord, pointer.capacity_policy_revision_id)
        ].state = "DRAFT"
    elif target == "PROTOCOL":
        rows[(ProtocolVersionRecord, pointer.role_schema_version)].schema_sha256 = (
            "sha256:" + "f" * 64
        )
    else:
        rows[(WorkflowDefinitionRecord, pointer.workflow_definition_id)].active = False

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_POINTER_STALE"


@pytest.mark.parametrize("target", ("PRESET", "INSTRUCTION"))
def test_exact_preset_dependency_graph_rejects_current_pointer_drift(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    if target == "PRESET":
        rows[(ExecutionPresetRecord, pointer.preset_id)].current_revision_id = (
            "execpresetrev_" + "f" * 32
        )
    else:
        rows[(ExecutionBundleRecord, pointer.instruction_bundle_id)].current_revision_id = (
            "instrrev_" + "f" * 32
        )

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_CURRENT_MISMATCH"


@pytest.mark.parametrize("target", ("PRESET", "INSTRUCTION", "CAPACITY", "WORKFLOW"))
def test_exact_preset_dependency_graph_rejects_row_document_hash_split(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    if target == "PRESET":
        document = rows[
            (ExecutionPresetRevisionRecord, pointer.preset_revision_id)
        ].canonical_document
        document["description"] = "different valid immutable document"
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    elif target == "INSTRUCTION":
        document = rows[
            (ExecutionBundleRevisionRecord, pointer.instruction_bundle_revision_id)
        ].canonical_document
        document["created_at"] = "2026-09-09T05:30:01Z"
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    elif target == "CAPACITY":
        document = rows[
            (WorkerCapacityPolicyRevisionRecord, pointer.capacity_policy_revision_id)
        ].canonical_document
        document["created_at"] = "2026-09-01T00:00:01Z"
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    else:
        document = rows[
            (WorkflowDefinitionRecord, pointer.workflow_definition_id)
        ].canonical_definition
        document["limits"]["max_step_attempts"] = 2

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_HASH_MISMATCH"


def _split_nested_instruction_manifest_artifact_hash(
    pointer: LegacyExtractionPresetPointer,
    rows: dict[tuple[object, str], SimpleNamespace],
) -> LegacyExtractionPresetPointer:
    preset_row = rows[(ExecutionPresetRevisionRecord, pointer.preset_revision_id)]
    preset_document = preset_row.canonical_document
    preset_document["role_policies"][0]["instruction_bundle"]["manifest_artifact"]["sha256"] = (
        "sha256:" + "e" * 64
    )
    preset_document["content_sha256"] = compute_control_document_hash(
        preset_document,
        "content_sha256",
    )
    preset_row.content_sha256 = preset_document["content_sha256"]
    return pointer.model_copy(
        update={
            "preset_sha256": preset_row.content_sha256,
            "preset_policy_sha256": execution_preset_policy_sha256(preset_document),
        }
    )


def test_exact_preset_dependency_graph_rejects_nested_manifest_artifact_hash_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    pointer = _split_nested_instruction_manifest_artifact_hash(pointer, rows)

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_POLICY_MISMATCH"


@pytest.mark.parametrize("target", ("PRESET", "INSTRUCTION", "CAPACITY", "WORKFLOW"))
def test_exact_preset_dependency_graph_rejects_canonical_identity_split(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    if target == "PRESET":
        row = rows[(ExecutionPresetRevisionRecord, pointer.preset_revision_id)]
        row.canonical_document["preset_revision_id"] = "execpresetrev_" + "e" * 32
        row.canonical_document["content_sha256"] = compute_control_document_hash(
            row.canonical_document,
            "content_sha256",
        )
        row.content_sha256 = row.canonical_document["content_sha256"]
        pointer = pointer.model_copy(update={"preset_sha256": row.content_sha256})
    elif target == "INSTRUCTION":
        row = rows[(ExecutionBundleRevisionRecord, pointer.instruction_bundle_revision_id)]
        row.canonical_document["bundle_revision_id"] = "instrrev_" + "e" * 32
        row.canonical_document["content_sha256"] = compute_control_document_hash(
            row.canonical_document,
            "content_sha256",
        )
        row.content_sha256 = row.canonical_document["content_sha256"]
        pointer = pointer.model_copy(update={"instruction_content_sha256": row.content_sha256})
    elif target == "CAPACITY":
        row = rows[(WorkerCapacityPolicyRevisionRecord, pointer.capacity_policy_revision_id)]
        row.canonical_document["capacity_policy_revision_id"] = "capacityrev_" + "e" * 32
        row.canonical_document["content_sha256"] = compute_control_document_hash(
            row.canonical_document,
            "content_sha256",
        )
        row.content_sha256 = row.canonical_document["content_sha256"]
        pointer = pointer.model_copy(update={"capacity_policy_sha256": row.content_sha256})
    else:
        row = rows[(WorkflowDefinitionRecord, pointer.workflow_definition_id)]
        row.canonical_definition["definition_key"] = "legacy-item-extraction-alternate"
        updated_hash = compile_definition_data(
            row.canonical_definition,
            "fixture",
            {"support"},
        ).sha256
        row.definition_hash = updated_hash
        pointer = pointer.model_copy(update={"workflow_definition_sha256": updated_hash})

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_POINTER_STALE"


@pytest.mark.parametrize("target", ("CAPACITY", "WORKFLOW"))
def test_exact_canonical_document_must_pass_schema_and_pydantic(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    if target == "CAPACITY":
        document = rows[
            (WorkerCapacityPolicyRevisionRecord, pointer.capacity_policy_revision_id)
        ].canonical_document
    else:
        document = rows[
            (WorkflowDefinitionRecord, pointer.workflow_definition_id)
        ].canonical_definition
    document["unexpected"] = True

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_DOCUMENT_INVALID"


@pytest.mark.parametrize("target", ("PRESET", "INSTRUCTION", "CAPACITY", "WORKFLOW"))
def test_successor_bootstrap_rejects_row_document_hash_split(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    pointer, rows = _fixture()
    manifest = _successor_manifest(pointer, rows)
    predecessor = manifest.predecessor
    assert predecessor is not None
    monkeypatch.setattr(
        bootstrap_module,
        "resolve_control_artifact_pointer",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    if target == "PRESET":
        document = rows[
            (ExecutionPresetRevisionRecord, pointer.preset_revision_id)
        ].canonical_document
        document["description"] = "different valid immutable document"
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    elif target == "INSTRUCTION":
        document = rows[
            (ExecutionBundleRevisionRecord, pointer.instruction_bundle_revision_id)
        ].canonical_document
        document["created_at"] = "2026-09-09T05:30:01Z"
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    elif target == "CAPACITY":
        document = rows[
            (WorkerCapacityPolicyRevisionRecord, pointer.capacity_policy_revision_id)
        ].canonical_document
        document["created_at"] = "2026-09-01T00:00:01Z"
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    else:
        document = rows[
            (WorkflowDefinitionRecord, pointer.workflow_definition_id)
        ].canonical_definition
        document["limits"]["max_step_attempts"] = 2

    with pytest.raises(ControlPlaneError) as captured:
        _require_successor_preflight(
            cast(Session, _PreflightSession(rows, preset_id=pointer.preset_id)),
            manifest=manifest,
            platform_sha256=predecessor.platform_instruction_sha256,
            role_sha256="sha256:" + "b" * 64,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_PREDECESSOR_STALE"


def test_successor_bootstrap_rejects_nested_manifest_artifact_hash_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer, rows = _fixture()
    pointer = _split_nested_instruction_manifest_artifact_hash(pointer, rows)
    manifest = _successor_manifest(pointer, rows)
    predecessor = manifest.predecessor
    assert predecessor is not None
    monkeypatch.setattr(
        bootstrap_module,
        "resolve_control_artifact_pointer",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    with pytest.raises(ControlPlaneError) as captured:
        _require_successor_preflight(
            cast(Session, _PreflightSession(rows, preset_id=pointer.preset_id)),
            manifest=manifest,
            platform_sha256=predecessor.platform_instruction_sha256,
            role_sha256="sha256:" + "b" * 64,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_PREDECESSOR_STALE"


def test_successor_bootstrap_accepts_exact_predecessor_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer, rows = _fixture()
    manifest = _successor_manifest(pointer, rows)
    predecessor = manifest.predecessor
    assert predecessor is not None
    monkeypatch.setattr(
        bootstrap_module,
        "resolve_control_artifact_pointer",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    platform = _require_successor_preflight(
        cast(Session, _PreflightSession(rows, preset_id=pointer.preset_id)),
        manifest=manifest,
        platform_sha256=predecessor.platform_instruction_sha256,
        role_sha256="sha256:" + "b" * 64,
    )

    assert platform.sha256 == predecessor.platform_instruction_sha256


def test_exact_preset_dependency_graph_rejects_artifact_pointer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer, rows = _fixture()

    def reject(*_args: object, **_kwargs: object) -> None:
        raise ControlPlaneError("CONTROL_POINTER_MISSING", "artifact pointer missing")

    monkeypatch.setattr(resolution_module, "resolve_control_artifact_pointer", reject)

    with pytest.raises(LegacyExtractionPresetResolutionError) as captured:
        _resolve(pointer, rows)

    assert captured.value.code == "LEGACY_EXTRACTION_PRESET_ARTIFACT_STALE"


def test_historical_pointer_resolution_does_not_require_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer, rows = _fixture()
    _allow_artifacts(monkeypatch)
    rows[(ExecutionPresetRecord, pointer.preset_id)].current_revision_id = (
        "execpresetrev_" + "f" * 32
    )
    rows[(ExecutionBundleRecord, pointer.instruction_bundle_id)].current_revision_id = (
        "instrrev_" + "f" * 32
    )

    resolved = _resolve(pointer, rows, require_current=False)

    assert resolved.preset_revision_id == pointer.preset_revision_id
