"""Synthetic control metadata only; no DB, NAS, worker or model execution."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import inference_transfer_resolution as resolution
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetRolePolicyRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    resolve_released_instruction_bundle,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, ProtocolVersionRecord
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.inference_transfer import TRANSFER_PAIR_PROTOCOL
from sqlalchemy.exc import IntegrityError

from tests.unit.inference_transfer_execution_fixtures import transfer_instruction, transfer_plan
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.inference_transfer_workflow_fixtures import workflow_request


class FakeSession:
    def __init__(self) -> None:
        self.records: dict[tuple[type[object], str], Any] = {}
        self.existing: Any = None
        self.role_rows: list[Any] = []
        self.step_rows: list[Any] = []
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.flush_count = 0

    def get(self, model: type[object], identity: str) -> Any:
        return self.records.get((model, identity))

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        model = statement.column_descriptions[0]["entity"]
        if model is ResolvedExecutionPlanRecord:
            return self.existing
        if model is ExecutionPresetRecord:
            return next(value for (kind, _), value in self.records.items() if kind is model)
        raise AssertionError("unexpected scalar query")

    def scalars(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        model = statement.column_descriptions[0]["entity"]
        if model is ExecutionPresetRolePolicyRecord:
            return self.role_rows
        if model is ResolvedExecutionPlanStepRecord:
            return self.step_rows
        raise AssertionError("unexpected projection query")

    def add(self, row: Any) -> None:
        self.added.append(row)
        if isinstance(row, ResolvedExecutionPlanRecord):
            self.existing = row
            self.records[(ResolvedExecutionPlanRecord, row.plan_id)] = row
        elif isinstance(row, ResolvedExecutionPlanStepRecord):
            self.step_rows.append(row)
        else:
            raise AssertionError("resolver may write only its plan and step")

    def flush(self) -> None:
        self.flush_count += 1


def rehash(document: dict[str, Any], key: str = "content_sha256") -> None:
    document[key] = content_sha256(
        {field: value for field, value in document.items() if field != key}
    )


def fixture(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    request = workflow_request()
    instruction = transfer_instruction(request.comparison)
    example = transfer_plan(request.comparison)
    pointer = example.steps[0].instruction_bundle
    session = FakeSession()

    def member(value: Any) -> None:
        session.records[(ArtifactRecord, value.artifact_id)] = SimpleNamespace(approved=True)
        session.records[(ArtifactRevisionRecord, value.artifact_revision_id)] = SimpleNamespace(
            approved=True,
            logical_artifact_id=value.artifact_id,
            content_hash=value.sha256,
            manifest={
                "files": [
                    {
                        "file_name": value.logical_name,
                        "sha256": value.sha256,
                        "schema_ref": value.schema_ref,
                        "media_type": value.media_type,
                    }
                ]
            },
        )

    member(pointer.manifest_artifact)
    for component in instruction.components:
        member(component.artifact)
    bundle_row = SimpleNamespace(
        **instruction.model_dump(),
        bundle_kind="INSTRUCTION",
        manifest_artifact_id=pointer.manifest_artifact.artifact_id,
        manifest_artifact_revision_id=pointer.manifest_artifact.artifact_revision_id,
        manifest_sha256=pointer.manifest_sha256,
        canonical_document=instruction.model_dump(mode="json"),
    )
    session.records[(ExecutionBundleRevisionRecord, instruction.bundle_revision_id)] = bundle_row
    policy = {
        "role": "support",
        "model_candidates": [{"model": "gpt-fixture-future", "reasoning_effort": "high"}],
        "instruction_bundle": pointer.model_dump(mode="json"),
        "reference_bundle": None,
        "worker_pool_key": "customer-support",
        "timeout_seconds": 300,
        "sandbox": "read-only",
        "network": "disabled",
    }
    body = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": example.preset_id,
        "preset_revision_id": example.preset_revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "Synthetic comparison controls",
        "description": "Not published or authorized for real sources.",
        "role_policies": [policy],
        "capacity_policy_revision_id": example.capacity_policy_revision_id,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": [TRANSFER_PAIR_PROTOCOL],
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    rehash(body)
    preset = ExecutionPresetRevision.model_validate(body)
    preset_row = SimpleNamespace(
        **preset.model_dump(), canonical_document=preset.model_dump(mode="json")
    )
    session.records[(ExecutionPresetRevisionRecord, preset.preset_revision_id)] = preset_row
    logical = SimpleNamespace(
        preset_id=preset.preset_id,
        preset_key=resolution.PRESET_KEY,
        state="ACTIVE",
        current_revision_id=preset.preset_revision_id,
    )
    session.records[(ExecutionPresetRecord, preset.preset_id)] = logical
    session.records[(ProtocolVersionRecord, TRANSFER_PAIR_PROTOCOL)] = SimpleNamespace(
        version=TRANSFER_PAIR_PROTOCOL
    )
    role_row = SimpleNamespace(
        preset_revision_id=preset.preset_revision_id,
        role=policy["role"],
        model_candidates=deepcopy(policy["model_candidates"]),
        instruction_bundle_revision_id=pointer.bundle_revision_id,
        reference_bundle_revision_id=None,
        worker_pool_key=policy["worker_pool_key"],
        timeout_seconds=policy["timeout_seconds"],
        sandbox=policy["sandbox"],
        network=policy["network"],
    )
    session.role_rows.append(role_row)
    observations: list[Any] = []

    def options(actual_session: Any, actual_preset: Any, *, observed_at: Any) -> Any:
        assert actual_session is session
        observations.append((actual_preset, observed_at))
        return {"support": preset.role_policies[0].model_candidates}

    monkeypatch.setattr(resolution, "preset_model_options", options)
    kwargs = {
        "workflow_id": example.workflow_id,
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": sha("2"),
        "workflow_role_schema_version": TRANSFER_PAIR_PROTOCOL,
        "workflow_request": request,
        "core_prompt_sha256": sha("5"),
        "prompt_sha256": sha("6"),
        "resolved_at": NOW,
    }
    return SimpleNamespace(
        session=session,
        kwargs=kwargs,
        request=request,
        instruction=instruction,
        pointer=pointer,
        bundle_row=bundle_row,
        preset=preset,
        preset_row=preset_row,
        logical=logical,
        role_row=role_row,
        observations=observations,
    )


def resolve(value: SimpleNamespace, **overrides: Any) -> Any:
    return resolution.resolve_inference_transfer_execution_plan(
        value.session, **(value.kwargs | overrides)
    )


def test_first_resolution_pins_actual_wrapper_and_commits_only_plan_and_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    plan = resolve(value)
    assert plan.steps[0].model == "gpt-fixture-future"
    assert plan.steps[0].timeout_seconds == 300
    assert plan.access_policy_sha256 == value.request.access_policy_sha256
    assert plan.requester_permissions_sha256 == value.request.requester_permissions_sha256
    assert plan.core_prompt_sha256 == sha("5") and plan.prompt_sha256 == sha("6")
    assert plan.rubric_artifact == value.instruction.components[1].artifact
    assert value.session.flush_count == 2
    assert len(value.session.added) == 2
    assert isinstance(value.session.added[0], ResolvedExecutionPlanRecord)
    assert isinstance(value.session.added[1], ResolvedExecutionPlanStepRecord)
    assert (
        value.session.existing.graph_snapshot_revision_id
        == plan.graph_snapshot.graph_snapshot_revision_id
    )
    assert value.session.existing.evidence_bundle_revision_id is None
    assert "content_pack_release_id" not in value.session.existing.canonical_document
    current_query = next(
        statement
        for statement in value.session.statements
        if statement.column_descriptions[0]["entity"] is ExecutionPresetRecord
    )
    assert current_query._for_update_arg is not None
    assert value.observations == [(value.preset, NOW)]


def test_exact_replay_does_not_read_new_current_and_rechecks_fresh_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    plan = resolve(value)
    value.logical.current_revision_id = "execpresetrev_" + "9" * 32
    value.session.statements.clear()
    value.session.added.clear()
    replay = resolve(value, resolved_at=NOW + timedelta(hours=1))
    assert replay == plan
    assert replay.resolved_at == NOW
    assert not value.session.added
    assert all(
        statement.column_descriptions[0]["entity"] is not ExecutionPresetRecord
        for statement in value.session.statements
    )
    assert value.observations[-1][1] == NOW + timedelta(hours=1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_definition_version", "9.0.0"),
        ("workflow_role_schema_version", "workflow-role/1.22.0"),
        ("workflow_definition_sha256", sha("9")),
        ("core_prompt_sha256", sha("9")),
        ("prompt_sha256", sha("9")),
    ],
)
def test_replay_rejects_changed_workflow_and_prompt_pins(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    data = fixture(monkeypatch)
    resolve(data)
    data.session.added.clear()
    with pytest.raises(ControlPlaneError) as error:
        resolve(data, **{field: value})
    assert error.value.code == "CONTROL_TRANSFER_CONTEXT_INVALID"
    assert not data.session.added


def test_forged_frozen_wrapper_is_rejected_before_any_control_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    forged = data.request.model_copy(update={"access_policy_sha256": sha("9")})
    with pytest.raises(ControlPlaneError) as error:
        resolve(data, workflow_request=forged)
    assert error.value.code == "CONTROL_TRANSFER_CONTEXT_INVALID"
    assert not data.session.statements and not data.session.added


@pytest.mark.parametrize(
    "field,value",
    [
        ("access_policy_revision_id", "accessrev_" + "9" * 32),
        ("access_policy_sha256", sha("9")),
        ("requester_permissions_sha256", sha("9")),
    ],
)
def test_replay_rejects_even_valid_rehashed_but_different_actual_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    data = fixture(monkeypatch)
    resolve(data)
    body = data.request.model_dump(mode="json")
    body[field] = value
    rehash(body, "request_sha256")
    wrapper = type(data.request).model_validate(body)
    with pytest.raises(ControlPlaneError) as error:
        resolve(data, workflow_request=wrapper)
    assert error.value.code == "CONTROL_TRANSFER_CONTEXT_INVALID"


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_id", "execplan_" + "9" * 32),
        ("workflow_id", "workflow_" + "9" * 32),
        ("preset_id", "execpreset_" + "9" * 32),
        ("preset_revision_id", "execpresetrev_" + "9" * 32),
        ("capacity_policy_revision_id", "capacityrev_" + "9" * 32),
        ("graph_snapshot_revision_id", "graphrev_" + "9" * 32),
        ("evidence_bundle_revision_id", "evidencerev_" + "9" * 32),
        ("plan_sha256", sha("9")),
        ("resolver_version", "1.0.0"),
        ("resolved_at", NOW + timedelta(seconds=1)),
    ],
)
def test_replay_checks_complete_plan_row_projection(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    data = fixture(monkeypatch)
    resolve(data)
    setattr(data.session.existing, field, value)
    with pytest.raises(ControlPlaneError) as error:
        resolve(data)
    assert error.value.code == "CONTROL_PLAN_CONFLICT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_id", "execplan_" + "9" * 32),
        ("step_key", "diagnose"),
        ("role", "authoring"),
        ("model", "guess-fallback"),
        ("reasoning_effort", "medium"),
        ("instruction_bundle_revision_id", "instrrev_" + "9" * 32),
        ("reference_bundle_revision_id", "refrev_" + "9" * 32),
        ("worker_pool_key", "authoring"),
        ("timeout_seconds", 900),
        ("sandbox", "workspace-write"),
        ("network", "enabled"),
        ("general_knowledge_mode", "ALLOWED_WITH_PROVENANCE"),
    ],
)
def test_replay_checks_every_step_projection_pin(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    data = fixture(monkeypatch)
    resolve(data)
    setattr(data.session.step_rows[0], field, value)
    with pytest.raises(ControlPlaneError) as error:
        resolve(data)
    assert error.value.code == "CONTROL_PLAN_CONFLICT"


@pytest.mark.parametrize("count", [0, 2])
def test_replay_requires_exactly_one_step(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    data = fixture(monkeypatch)
    resolve(data)
    data.session.step_rows *= count
    with pytest.raises(ControlPlaneError) as error:
        resolve(data)
    assert error.value.code == "CONTROL_PLAN_CONFLICT"


@pytest.mark.parametrize("replay", [False, True])
def test_unavailable_candidate_never_falls_back_or_writes_new_plan(
    monkeypatch: pytest.MonkeyPatch,
    replay: bool,
) -> None:
    data = fixture(monkeypatch)
    if replay:
        resolve(data)
    data.session.added.clear()
    monkeypatch.setattr(resolution, "preset_model_options", lambda *a, **k: {"support": ()})
    with pytest.raises(ControlPlaneError) as error:
        resolve(data)
    assert error.value.code == "CONTROL_PRESET_MODEL_UNAVAILABLE"
    assert not data.session.added


def test_unregistered_protocol_is_not_admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    data = fixture(monkeypatch)
    del data.session.records[(ProtocolVersionRecord, TRANSFER_PAIR_PROTOCOL)]
    with pytest.raises(ControlPlaneError) as error:
        resolve(data)
    assert error.value.code == "CONTROL_PROTOCOL_MISSING"


@pytest.mark.parametrize(
    "change", ["missing_current", "capacity_projection", "role_projection", "extra_candidate"]
)
def test_first_resolution_rejects_missing_or_inconsistent_preset_metadata(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    data = fixture(monkeypatch)
    if change == "missing_current":
        data.logical.current_revision_id = None
    elif change == "capacity_projection":
        data.preset_row.capacity_policy_revision_id = "capacityrev_" + "9" * 32
    elif change == "role_projection":
        data.role_row.model_candidates = [{"model": "unpublished", "reasoning_effort": "high"}]
    else:
        data.preset_row.canonical_document["role_policies"][0]["model_candidates"].append(
            {"model": "other-candidate", "reasoning_effort": "high"}
        )
        rehash(data.preset_row.canonical_document)
        data.preset_row.content_sha256 = data.preset_row.canonical_document["content_sha256"]
    with pytest.raises(ControlPlaneError):
        resolve(data)
    assert not data.session.added


@pytest.mark.parametrize(
    "field,value",
    [
        ("manifest_artifact_id", "artifact_" + "9" * 32),
        ("manifest_artifact_revision_id", "rev_" + "9" * 32),
        ("bundle_kind", "REFERENCE"),
        ("state", "DEPRECATED"),
        ("manifest_sha256", sha("9")),
        ("content_sha256", sha("9")),
        ("revision_number", 2),
        ("schema_version", "instruction-bundle-manifest/9.0"),
    ],
)
def test_public_instruction_resolution_checks_exact_released_row(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    data = fixture(monkeypatch)
    setattr(data.bundle_row, field, value)
    with pytest.raises(ControlPlaneError):
        resolve_released_instruction_bundle(data.session, data.pointer)


def test_public_instruction_resolution_checks_nested_approval_and_copied_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    assert resolve_released_instruction_bundle(data.session, data.pointer) == data.instruction
    member = data.instruction.components[1].artifact
    data.session.records[(ArtifactRevisionRecord, member.artifact_revision_id)].approved = False
    with pytest.raises(ControlPlaneError) as error:
        resolve(data)
    assert error.value.code == "CONTROL_POINTER_NOT_APPROVED"
    copied = data.pointer.model_copy(update={"bundle_revision_id": "unsafe"})
    with pytest.raises(ControlPlaneError) as error:
        resolve_released_instruction_bundle(data.session, copied)
    assert error.value.code == "CONTROL_BUNDLE_POINTER_INVALID"


@pytest.mark.parametrize("change", ["malformed", "wrong_bundle", "wrong_member", "wrong_layer"])
def test_invalid_instruction_or_rubric_cannot_publish_plan(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    data = fixture(monkeypatch)
    body = data.bundle_row.canonical_document
    if change == "malformed":
        body["unexpected"] = "reject"
    elif change == "wrong_bundle":
        body["bundle_id"] = "instrbundle_" + "9" * 32
    elif change == "wrong_member":
        body["components"][1]["relative_path"] = "instructions/different.md"
    else:
        body["components"][1]["layer"] = "PLATFORM"
    rehash(body)
    data.bundle_row.content_sha256 = body["content_sha256"]
    with pytest.raises(ControlPlaneError):
        resolve(data)
    assert not data.session.added


def test_pinned_preset_release_revocation_is_explicit_not_repaired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    resolve(data)
    data.preset_row.state = "DEPRECATED"
    data.session.added.clear()
    with pytest.raises(ControlPlaneError):
        resolve(data)
    assert not data.session.added


@pytest.mark.parametrize("constraint", ["uq_execution_plan_workflow", "fk_actual_workflow"])
def test_only_known_unique_workflow_conflict_is_classified_without_repair(
    monkeypatch: pytest.MonkeyPatch, constraint: str
) -> None:
    data = fixture(monkeypatch)
    original = RuntimeError("synthetic DB integrity failure")
    original.diag = SimpleNamespace(constraint_name=constraint)  # type: ignore[attr-defined]
    failure = IntegrityError("synthetic INSERT", {}, original)

    def fails() -> None:
        raise failure

    data.session.flush = fails
    if constraint == "uq_execution_plan_workflow":
        with pytest.raises(ControlPlaneError) as error:
            resolve(data)
        assert error.value.code == "CONTROL_PLAN_CONFLICT"
        assert error.value.__cause__ is failure
    else:
        with pytest.raises(IntegrityError) as error:
            resolve(data)
        assert error.value is failure
    assert not data.session.step_rows
    assert len(data.session.added) == 1
