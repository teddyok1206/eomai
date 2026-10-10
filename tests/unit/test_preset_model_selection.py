from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_commands import _terminalize_record
from eom_orchestrator.control_models import (
    CodexCapabilitySnapshotRecord,
    CodexControlCommandRecord,
    WorkerCapacityPoolRoleRecord,
    WorkerCapacityPoolSlotRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.preset_model_selection import (
    capacity_pool_model_options,
    non_live_invocation_cases,
    preset_model_options,
    require_model_only_successor,
    validate_model_selection,
    validated_preset,
)
from eom_orchestrator.worker_exec import codex_command
from eom_orchestrator.worker_usage_exec import (
    _catalog_snapshot,
    _normalized_model,
    _observation_document,
)
from eom_workflow import CodexUsageObservationV2, ExecutionPresetRevision, ExecutionPresetRevisionV2

from tests.unit.test_execution_control_contracts import _preset as _base_document

NOW = datetime.now(UTC) + timedelta(minutes=5)


def _self_hash(document: dict[str, Any], field: str = "content_sha256") -> dict[str, Any]:
    document[field] = content_sha256(
        {key: value for key, value in document.items() if key != field}
    )
    return document


def _preset(*, knowledge: bool = False) -> ExecutionPresetRevision | ExecutionPresetRevisionV2:
    document = _base_document()
    if knowledge:
        document["schema_version"] = "execution-preset-revision/2.0"
        document["role_policies"][0]["evidence_access"] = "EVIDENCE_CONTEXT"  # type: ignore[index]
        document["retrieval_policy"] = {
            "access_policy_revision_id": "accessrev_" + "6" * 32,
            "access_policy_sha256": "sha256:" + "6" * 64,
            "allowed_corpus_keys": ["science-corpus"],
            "allowed_query_kinds": ["ITEM_PREPARATION"],
            "allowed_source_classes": ["PAST_EXAM", "TEXTBOOK"],
            "maximum_budget": {
                "max_documents": 4,
                "max_item_revisions": 8,
                "max_graph_nodes": 32,
                "max_claims": 16,
                "max_context_tokens": 4000,
            },
        }
    _self_hash(document)
    kind = ExecutionPresetRevisionV2 if knowledge else ExecutionPresetRevision
    return kind.model_validate(document)


def _draft(base: Any, edit: Any = None) -> Any:
    document = base.model_dump(mode="json")
    document.update(
        {
            "preset_revision_id": "execpresetrev_" + "3" * 32,
            "revision_number": 2,
            "state": "DRAFT",
            "display_name": "New model policy",
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        }
    )
    document["role_policies"][0]["model_candidates"][0]["reasoning_effort"] = "medium"
    if edit is not None:
        edit(document)
    _self_hash(document)
    return type(base).model_validate(document)


@pytest.mark.parametrize("knowledge", [False, True])
def test_only_authoring_review_model_changes_preserve_every_other_pin(knowledge: bool) -> None:
    base = _preset(knowledge=knowledge)
    before = base.model_dump(mode="json")
    draft = _draft(base)
    require_model_only_successor(base, draft)
    assert base.model_dump(mode="json") == before
    assert draft.role_policies[0].instruction_bundle == base.role_policies[0].instruction_bundle
    assert draft.capacity_policy_revision_id == base.capacity_policy_revision_id


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update({"preset_id": "execpreset_" + "9" * 32}),
        lambda d: d.update({"capacity_policy_revision_id": "capacityrev_" + "9" * 32}),
        lambda d: d.update({"general_knowledge_policy": "DENY"}),
        lambda d: d.update({"compatible_workflow_protocols": ["workflow-role/1.4.0"]}),
        lambda d: d["role_policies"][0].update({"timeout_seconds": 60}),
        lambda d: d["role_policies"][0].update({"worker_pool_key": "different-pool"}),
        lambda d: d["role_policies"][0].update({"reference_bundle": None}),
        lambda d: d["role_policies"][0]["instruction_bundle"].update(
            {"manifest_sha256": "sha256:" + "9" * 64}
        ),
        lambda d: d["role_policies"][0]["model_candidates"].append(
            {"model": "new-fallback", "reasoning_effort": "high"}
        ),
    ],
)
def test_model_selection_rejects_fixed_policy_changes(change: Any) -> None:
    base = _preset()
    with pytest.raises(ControlPlaneError) as exc:
        require_model_only_successor(base, _draft(base, change))
    assert exc.value.code == "CONTROL_PRESET_FIXED_POLICY_CHANGED"


def test_model_selection_does_not_broaden_graphrag_policy() -> None:
    base = _preset(knowledge=True)
    draft = _draft(
        base, lambda d: d["retrieval_policy"].update({"allowed_source_classes": ["PAST_EXAM"]})
    )
    with pytest.raises(ControlPlaneError, match="fixed policy"):
        require_model_only_successor(base, draft)


def test_three_model_selectors_preserve_review_order_and_noneditable_roles() -> None:
    document = _preset().model_dump(mode="json")
    authoring = document["role_policies"][0]
    review = deepcopy(authoring)
    review.update(
        {
            "role": "review",
            "worker_pool_key": "review",
            "model_candidates": [
                {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
                {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
            ],
        }
    )
    image = deepcopy(authoring)
    image.update({"role": "image", "worker_pool_key": "image"})
    registration = deepcopy(authoring)
    registration.update({"role": "item_management", "worker_pool_key": "item-management"})
    document["role_policies"] = [authoring, review, image, registration]
    base = ExecutionPresetRevision.model_validate(_self_hash(document))
    changed = _draft(base).model_dump(mode="json")
    changed["role_policies"][1]["model_candidates"] = [
        {"model": "basic-model", "reasoning_effort": "medium"},
        {"model": "enhanced-model", "reasoning_effort": "xhigh"},
    ]
    draft = ExecutionPresetRevision.model_validate(_self_hash(changed))
    require_model_only_successor(base, draft)
    assert draft.role_policies[1].model_candidates[0].model == "basic-model"
    assert draft.role_policies[1].model_candidates[1].model == "enhanced-model"
    assert draft.role_policies[2:] == base.role_policies[2:]
    changed["role_policies"][2]["model_candidates"][0]["model"] = "not-editable"
    bad = ExecutionPresetRevision.model_validate(_self_hash(changed))
    with pytest.raises(ControlPlaneError, match="fixed policy"):
        require_model_only_successor(base, bad)


def test_preset_resolution_checks_schema_hash_and_db_revision_identity() -> None:
    preset = _preset()
    row = SimpleNamespace(**preset.model_dump(), canonical_document=preset.model_dump(mode="json"))
    assert validated_preset(row) == preset  # type: ignore[arg-type]
    row.revision_number += 1
    with pytest.raises(ControlPlaneError) as exc:
        validated_preset(row)  # type: ignore[arg-type]
    assert exc.value.code == "CONTROL_PRESET_HASH_MISMATCH"
    row.revision_number -= 1
    row.canonical_document["role_policies"][0]["model_candidates"][0]["reasoning_effort"] = "max"
    with pytest.raises(ControlPlaneError) as exc:
        validated_preset(row)  # type: ignore[arg-type]
    assert exc.value.code == "CONTROL_PRESET_DOCUMENT_INVALID"


def test_non_live_acceptance_executes_real_adapter_fixtures_without_launching_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    def real_adapter(workspace: Path, invocation: dict[str, str]) -> tuple[str, ...]:
        calls.append(invocation)
        return codex_command(workspace, invocation)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("non-live validation must not launch inference")

    monkeypatch.setattr("eom_orchestrator.preset_model_selection.codex_command", real_adapter)
    monkeypatch.setattr("eom_orchestrator.worker_exec.subprocess.run", forbidden)
    cases = non_live_invocation_cases(_preset())
    assert len(calls) == 1
    assert calls[0] == {"model": "gpt-5.6-terra", "reasoning_effort": "high"}
    assert len(cases) == 8
    assert len(set(cases)) == len(cases)
    assert "authoring:0:SCHEMA_OUTPUT_PIN" in cases
    assert "REJECT_UNSUPPORTED_MAX" in cases and "REJECT_UNSUPPORTED_ULTRA" in cases


def test_non_live_acceptance_detects_actual_adapter_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def drifted(workspace: Path, invocation: dict[str, str]) -> tuple[str, ...]:
        values = list(codex_command(workspace, invocation))
        values[values.index("--model") + 1] = "wrong-model"
        return tuple(values)

    monkeypatch.setattr("eom_orchestrator.preset_model_selection.codex_command", drifted)
    with pytest.raises(ControlPlaneError) as exc:
        non_live_invocation_cases(_preset())
    assert exc.value.code == "CONTROL_PRESET_INVOCATION_CASE_FAILED"


class _OptionSession:
    def __init__(self) -> None:
        capacity = _self_hash(
            {
                "schema_version": "worker-capacity-policy/1.0",
                "capacity_policy_id": "capacity_" + "1" * 32,
                "capacity_policy_revision_id": "capacityrev_" + "1" * 32,
                "revision_number": 1,
                "state": "RELEASED",
                "max_configured_slots": 5,
                "max_active_codex": 3,
                "max_active_per_slot": 1,
                "max_active_gpu": 1,
                "max_active_knowledge_analysis": 1,
                "pools": [
                    {
                        "pool_key": "authoring",
                        "roles": ["authoring"],
                        "slot_keys": ["slot01"],
                        "max_active": 1,
                    }
                ],
                "created_at": NOW.isoformat().replace("+00:00", "Z"),
            }
        )
        self.capacity = SimpleNamespace(**capacity, canonical_document=capacity)
        self.binding = SimpleNamespace(
            binding_id="authbinding_" + "2" * 32,
            state="READY",
            observed_at=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=30),
            codex_cli_version="0.160.0",
            worker_slot_id="01",
            resource_version=2,
        )
        self.slot = SimpleNamespace(slot_id="01", role="authoring", enabled=True)
        capability = _self_hash(
            {
                "schema_version": "codex-capability-snapshot/1.0",
                "capability_snapshot_id": "capsnap_" + "2" * 32,
                "binding_id": self.binding.binding_id,
                "codex_cli_version": "0.160.0",
                "source": "LOCAL_OBSERVATION",
                "observed_at": (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "valid_until": (NOW + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
                "capabilities": [
                    {
                        "model": "gpt-5.6-terra",
                        "reasoning_efforts": ["medium", "high", "xhigh"],
                        "state": "AVAILABLE",
                    }
                ],
            },
            "snapshot_sha256",
        )
        self.snapshot = SimpleNamespace(
            **(
                capability
                | {
                    "observed_at": NOW - timedelta(minutes=1),
                    "valid_until": NOW + timedelta(minutes=30),
                }
            ),
            canonical_document=capability,
        )
        models = tuple(
            _normalized_model(
                {
                    "id": model,
                    "model": model,
                    "displayName": model,
                    "hidden": False,
                    "isDefault": False,
                    "defaultReasoningEffort": "high",
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": effort} for effort in ("medium", "high", "ultra")
                    ],
                    "inputModalities": ["text", "image"],
                }
            )
            for model in ("gpt-5.6-terra", "native-only")
        )
        catalog = _catalog_snapshot(cli_version="0.160.0", models=models, reason_code=None)
        usage = _observation_document(
            command_id="codexcmd_" + "3" * 32,
            binding_id=self.binding.binding_id,
            slot_id="01",
            account_result={"account": {"type": "chatgpt", "planType": "plus"}},
            usage_result={"rateLimits": {"primary": {"usedPercent": 1}}},
            model_catalog=catalog,
        )
        self.observation = SimpleNamespace(
            command_id=usage["command_id"],
            binding_id=self.binding.binding_id,
            command_type="OBSERVE",
        )
        _terminalize_record(
            self.observation,
            outcome="SUCCEEDED",
            result_resource_version=2,
            binding_state="READY",
            reason_code=None,
            processed_at=NOW - timedelta(seconds=1),
            usage_observation=CodexUsageObservationV2.model_validate(usage),
        )
        self.records: dict[Any, list[Any]] = {
            WorkerCapacityPoolRoleRecord: [SimpleNamespace(pool_key="authoring", role="authoring")],
            WorkerCapacityPoolSlotRecord: [SimpleNamespace(pool_key="authoring", slot_id="01")],
            CodexCapabilitySnapshotRecord: [self.snapshot],
            CodexControlCommandRecord: [self.observation],
        }

    def get(self, _kind: Any, _key: str) -> Any:
        return self.capacity

    def execute(self, _statement: Any) -> Any:
        return SimpleNamespace(all=lambda: [(self.binding, self.slot)])

    def scalars(self, statement: Any) -> Any:
        return self.records[statement.column_descriptions[0]["entity"]]


def test_candidates_intersect_catalog_reviewed_policy_and_exact_pool_role() -> None:
    session = _OptionSession()
    options = preset_model_options(session, _preset(), observed_at=NOW)  # type: ignore[arg-type]
    assert [(item.model, item.reasoning_effort) for item in options["authoring"]] == [
        ("gpt-5.6-terra", "high"),
        ("gpt-5.6-terra", "medium"),
    ]


@pytest.mark.parametrize(
    "reason",
    [
        "legacy",
        "absent",
        "empty",
        "auth_expired",
        "native_expired",
        "auth_revision",
        "slot_disabled",
        "role_changed",
    ],
)
def test_unknown_or_ineligible_native_catalog_yields_no_guessed_options(reason: str) -> None:
    session = _OptionSession()
    as_of = NOW
    if reason == "legacy":
        session.observation.result_document = {"schema_version": "codex-control-command-result/1.1"}
    elif reason == "absent":
        session.records[CodexControlCommandRecord] = []
    elif reason == "empty":
        document = session.observation.result_document
        catalog = document["usage_observation"]["model_catalog"]
        catalog["models"] = []
        _self_hash(catalog, "catalog_sha256")
        _self_hash(document["usage_observation"], "observation_sha256")
        _self_hash(document, "result_sha256")
    elif reason == "auth_expired":
        session.binding.valid_until = NOW
    elif reason == "native_expired":
        as_of = NOW + timedelta(hours=2)
        session.binding.valid_until = as_of + timedelta(hours=1)
        session.snapshot.valid_until = as_of + timedelta(hours=1)
        session.snapshot.canonical_document["valid_until"] = (
            session.snapshot.valid_until.isoformat().replace("+00:00", "Z")
        )
        _self_hash(session.snapshot.canonical_document, "snapshot_sha256")
        session.snapshot.snapshot_sha256 = session.snapshot.canonical_document["snapshot_sha256"]
    elif reason == "auth_revision":
        session.binding.resource_version += 1
    elif reason == "slot_disabled":
        session.slot.enabled = False
    else:
        session.slot.role = "review"
    assert preset_model_options(session, _preset(), observed_at=as_of) == {"authoring": ()}  # type: ignore[arg-type]


@pytest.mark.parametrize("column", ["observed_at", "valid_until", "source", "codex_cli_version"])
def test_capability_column_canonical_drift_is_rejected(column: str) -> None:
    session = _OptionSession()
    if column in {"observed_at", "valid_until"}:
        setattr(session.snapshot, column, getattr(session.snapshot, column) + timedelta(seconds=1))
    elif column == "source":
        session.snapshot.source = "OPERATOR_ASSERTED"
    else:
        session.snapshot.canonical_document["codex_cli_version"] = "0.159.0"
        _self_hash(session.snapshot.canonical_document, "snapshot_sha256")
        session.snapshot.snapshot_sha256 = session.snapshot.canonical_document["snapshot_sha256"]
    with pytest.raises(ControlPlaneError) as exc:
        preset_model_options(session, _preset(), observed_at=NOW)  # type: ignore[arg-type]
    assert exc.value.code == "CONTROL_CAPABILITY_HASH_MISMATCH"


def test_native_hash_and_pool_projection_drift_fail_explicitly() -> None:
    session = _OptionSession()
    session.observation.result_document["result_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ControlPlaneError) as exc:
        preset_model_options(session, _preset(), observed_at=NOW)  # type: ignore[arg-type]
    assert exc.value.code == "CONTROL_NATIVE_CATALOG_HASH_MISMATCH"
    session = _OptionSession()
    session.records[WorkerCapacityPoolSlotRecord][0].slot_id = "02"
    with pytest.raises(ControlPlaneError) as exc:
        preset_model_options(session, _preset(), observed_at=NOW)  # type: ignore[arg-type]
    assert exc.value.code == "CONTROL_CAPACITY_POINTER_INVALID"


@pytest.mark.parametrize("target", ["capacity", "catalog"])
def test_non_object_stored_metadata_returns_stable_failure(target: str) -> None:
    session = _OptionSession()
    if target == "capacity":
        session.capacity.canonical_document = ["not-a-document"]
    else:
        session.observation.result_document = ["not-a-document"]
    with pytest.raises(ControlPlaneError) as exc:
        preset_model_options(session, _preset(), observed_at=NOW)  # type: ignore[arg-type]
    assert exc.value.code == (
        "CONTROL_CAPACITY_POINTER_INVALID"
        if target == "capacity"
        else "CONTROL_NATIVE_CATALOG_INVALID"
    )


@pytest.mark.parametrize("empty_catalog", [False, True])
def test_new_draft_requires_real_fresh_catalog_before_adapter_acceptance(
    empty_catalog: bool,
) -> None:
    session = _OptionSession()
    if empty_catalog:
        document = session.observation.result_document
        catalog = document["usage_observation"]["model_catalog"]
        catalog["models"] = []
        _self_hash(catalog, "catalog_sha256")
        _self_hash(document["usage_observation"], "observation_sha256")
        _self_hash(document, "result_sha256")
    else:
        session.records[CodexControlCommandRecord] = []
    base = _preset()
    with pytest.raises(ControlPlaneError) as exc:
        validate_model_selection(session, base, _draft(base), observed_at=NOW)  # type: ignore[arg-type]
    assert exc.value.code == "CONTROL_PRESET_MODEL_CATALOG_REQUIRED"


def test_positive_selection_runs_pointer_checks_and_real_non_live_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _OptionSession()
    pointers: list[tuple[object, str]] = []
    monkeypatch.setattr(
        "eom_orchestrator.preset_model_selection._validate_bundle_pointer",
        lambda _session, pointer, *, expected_kind: pointers.append((pointer, expected_kind)),
    )
    base = _preset()
    draft = _draft(base)
    cases = validate_model_selection(session, base, draft, observed_at=NOW)  # type: ignore[arg-type]
    assert len(cases) == 11
    assert pointers == [
        (draft.role_policies[0].instruction_bundle, "INSTRUCTION"),
        (draft.role_policies[0].reference_bundle, "REFERENCE"),
    ]
    assert cases[-1] == "REJECT_UNSUPPORTED_ULTRA"


def test_native_support_without_reviewed_admission_is_not_a_valid_new_candidate() -> None:
    session = _OptionSession()
    base = _preset()
    draft = _draft(
        base,
        lambda d: d["role_policies"][0]["model_candidates"][0].update({"model": "native-only"}),
    )
    with pytest.raises(ControlPlaneError) as exc:
        validate_model_selection(session, base, draft, observed_at=NOW)  # type: ignore[arg-type]
    assert exc.value.code == "CONTROL_PRESET_MODEL_UNAVAILABLE"


def test_prepublication_options_share_the_legacy_authoritative_intersection() -> None:
    session = _OptionSession()
    existing = preset_model_options(session, _preset(), observed_at=NOW)  # type: ignore[arg-type]
    options = capacity_pool_model_options(
        session,  # type: ignore[arg-type]
        capacity_policy_revision_id=session.capacity.capacity_policy_revision_id,
        role="authoring",
        worker_pool_key="authoring",
        observed_at=NOW,
    )
    assert options == existing["authoring"] and options
    session.binding.valid_until = NOW
    assert (
        capacity_pool_model_options(
            session,  # type: ignore[arg-type]
            capacity_policy_revision_id=session.capacity.capacity_policy_revision_id,
            role="authoring",
            worker_pool_key="authoring",
            observed_at=NOW,
        )
        == ()
    )


def test_prepublication_options_do_not_broaden_to_an_unadmitted_role_pool() -> None:
    session = _OptionSession()
    with pytest.raises(ControlPlaneError, match="not admitted"):
        capacity_pool_model_options(
            session,  # type: ignore[arg-type]
            capacity_policy_revision_id=session.capacity.capacity_policy_revision_id,
            role="support",
            worker_pool_key="customer-support",
            observed_at=NOW,
        )


def test_prepublication_options_reject_native_capacity_schema_column_drift() -> None:
    session = _OptionSession()
    session.capacity.schema_version = "worker-capacity-policy/1.3"
    with pytest.raises(ControlPlaneError) as exc:
        capacity_pool_model_options(
            session,  # type: ignore[arg-type]
            capacity_policy_revision_id=session.capacity.capacity_policy_revision_id,
            role="authoring",
            worker_pool_key="authoring",
            observed_at=NOW,
        )
    assert exc.value.code == "CONTROL_CAPACITY_POINTER_INVALID"


def test_prepublication_options_reject_foreign_exact_capacity_revision() -> None:
    session = _OptionSession()
    with pytest.raises(ControlPlaneError) as exc:
        capacity_pool_model_options(
            session,  # type: ignore[arg-type]
            capacity_policy_revision_id="capacityrev_" + "f" * 32,
            role="authoring",
            worker_pool_key="authoring",
            observed_at=NOW,
        )
    assert exc.value.code == "CONTROL_CAPACITY_POINTER_INVALID"
