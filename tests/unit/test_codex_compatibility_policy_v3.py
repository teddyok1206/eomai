"""Exact six-role admission, with synthetic evidence only and immutable predecessors."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import codex_compatibility_policy as admission
from eom_orchestrator.capability_observer import (
    COMPATIBILITY_SLOT_ROLES,
    REQUIRED_EXEC_HELP_FLAGS,
    ReviewedCapabilityBindingV3,
    ReviewedCapabilityPolicy,
    load_reviewed_capability_policy,
    reviewed_capabilities_for_binding,
)
from eom_orchestrator.codex_compatibility_policy import current_admission_bindings
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, validate_control_contract
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tests.unit.test_codex_compatibility_contracts import HASH, report_document
from tests.unit.test_codex_compatibility_policy_install import NOW, _baseline, _bindings, _render


def _role_report(
    selections: tuple[tuple[str, str, str], ...] | None = None,
) -> dict[str, Any]:
    document = report_document()
    selections = selections or tuple(
        (slot, "synthetic-model", "medium") for slot in COMPATIBILITY_SLOT_ROLES
    )
    request = document["request"]
    request["cases"] = [
        {
            "case_id": f"compatcase_{number:032x}",
            "slot_id": slot,
            "binding_id": "authbinding_" + str(int(slot) + 1) * 32,
            "assignment_revision_id": None,
            "expected_resource_version": 7,
            "model": model,
            "reasoning_effort": effort,
        }
        for number, (slot, model, effort) in enumerate(selections, start=1)
    ]
    request["max_model_calls"] = len(selections)
    document["request_sha256"] = content_sha256(request)
    document["model_calls"] = len(selections)
    document["cases"] = [
        {
            **case,
            "job_id": f"job_{number + 100:032x}",
            "status": "PASS",
            "error_code": None,
            "invocation_sha256": HASH,
            "result_sha256": HASH,
            "elapsed_ms": 100,
        }
        for number, case in enumerate(request["cases"], start=1)
    ]
    return document


def _v2_policy() -> ReviewedCapabilityPolicy:
    document = _render().model_dump(mode="json")
    document["version"] = 2
    for item in document["models"]:
        for pin in item["bindings"] or ():
            del pin["slot_id"]
            del pin["role"]
    return ReviewedCapabilityPolicy.model_validate(document)


def test_v3_schema_resource_and_released_v2_bytes_remain_exact() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("codex-reviewed-capability-policy-v2", "codex-reviewed-capability-policy-v3"):
        entry = CONTROL_SCHEMA_RESOURCES[name]
        canonical = (root / entry.canonical_path).read_bytes()
        assert (
            canonical
            == (root / "packages/workflow/eom_workflow" / entry.resource_path).read_bytes()
        )
        assert sha256_bytes(canonical) == entry.sha256
    assert CONTROL_SCHEMA_RESOURCES["codex-reviewed-capability-policy-v2"].sha256 == (
        "sha256:96af2acafd0c19dc4220761ee54e4e8094cc78b4542949f3cb43c4540cc69c69"
    )


def test_changed_cli_admits_actual_passed_six_slots_with_exact_role_pins() -> None:
    policy = _render(_role_report(), baseline_policy=_baseline("0.146.0"))
    assert policy.version == 3 and len(policy.models) == 1
    pins = policy.models[0].bindings
    assert pins is not None and len(pins) == 6
    assert [
        (pin.slot_id, pin.role) for pin in pins if isinstance(pin, ReviewedCapabilityBindingV3)
    ] == list(COMPATIBILITY_SLOT_ROLES.items())
    assert all(pin.assignment_revision_id is None for pin in pins)
    validate_control_contract("codex-reviewed-capability-policy-v3", policy.model_dump(mode="json"))


def test_scopes_do_not_create_untested_effort_binding_cartesian_product() -> None:
    document = _role_report(
        (
            ("01", "synthetic-model", "medium"),
            ("02", "synthetic-model", "medium"),
            ("03", "synthetic-model", "high"),
            ("04", "other-model", "medium"),
            ("05", "synthetic-model", "medium"),
            ("06", "synthetic-model", "high"),
        )
    )
    policy = _render(document, baseline_policy=_baseline("0.146.0"))
    actual = {
        (pin.slot_id, item.model, effort)
        for item in policy.models
        for pin in item.bindings or ()
        if isinstance(pin, ReviewedCapabilityBindingV3)
        for effort in item.reasoning_efforts
    }
    expected = {
        (case["slot_id"], case["model"], case["reasoning_effort"]) for case in document["cases"]
    }
    assert actual == expected


def test_unpaired_authoring_effort_is_not_admitted_but_other_slots_are_independent() -> None:
    document = _role_report(
        (
            ("01", "synthetic-model", "medium"),
            ("02", "synthetic-model", "medium"),
            ("01", "synthetic-model", "high"),
            ("03", "synthetic-model", "high"),
        )
    )
    policy = _render(document, baseline_policy=_baseline("0.146.0"))
    high = next(item for item in policy.models if item.reasoning_efforts == ("high",))
    assert high.bindings is not None
    assert [
        pin.slot_id for pin in high.bindings if isinstance(pin, ReviewedCapabilityBindingV3)
    ] == ["03"]


@pytest.mark.parametrize("status", ("FAIL", "NOT_RUN"))
def test_failed_or_unexecuted_other_binding_is_not_admitted(status: str) -> None:
    document = _role_report()
    case = document["cases"][-1]
    case.update(status=status, result_sha256=None)
    if status == "FAIL":
        case["error_code"] = "WORKER_EXEC_FAILED"
    else:
        case.update(error_code="MAINTENANCE_LOST", invocation_sha256=None, elapsed_ms=0)
        document["model_calls"] -= 1
    policy = _render(document, baseline_policy=_baseline("0.146.0"))
    assert all(
        pin.slot_id != "06"
        for item in policy.models
        for pin in item.bindings or ()
        if isinstance(pin, ReviewedCapabilityBindingV3)
    )


@pytest.mark.parametrize("slot", ("03", "04", "05", "06"))
@pytest.mark.parametrize(
    "field", ("binding_id", "assignment_revision_id", "expected_resource_version")
)
def test_non_authoring_report_pins_are_never_silently_ignored(slot: str, field: str) -> None:
    document = _role_report()
    bindings = _bindings(document)
    replacement: object = {
        "binding_id": "authbinding_" + "f" * 32,
        "assignment_revision_id": "authassignrev_" + "f" * 32,
        "expected_resource_version": 8,
    }[field]
    for case in (*document["request"]["cases"], *document["cases"]):
        if case["slot_id"] == slot:
            case[field] = replacement
    document["request_sha256"] = content_sha256(document["request"])
    with pytest.raises(ControlPlaneError, match="binding pins"):
        _render(document, bindings=bindings)


@pytest.mark.parametrize("slot,role", tuple(COMPATIBILITY_SLOT_ROLES.items()))
def test_v3_slot_role_shape_is_enforced_by_schema_and_pydantic(slot: str, role: str) -> None:
    document = _render(_role_report()).model_dump(mode="json")
    pin = next(pin for pin in document["models"][1]["bindings"] if pin["slot_id"] == slot)
    pin["role"] = "image" if role != "image" else "review"
    with pytest.raises(SchemaValidationError):
        validate_control_contract("codex-reviewed-capability-policy-v3", document)
    with pytest.raises(ValidationError, match="fixed slot"):
        ReviewedCapabilityPolicy.model_validate(document)


def test_v3_render_replay_is_canonical_and_does_not_mutate_report_or_predecessor() -> None:
    document = _role_report()
    baseline = _baseline()
    prior_document = deepcopy(document)
    prior_policy = baseline.model_dump(mode="json")
    first = _render(document, baseline_policy=baseline)
    second = _render(document, baseline_policy=baseline)
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(
        second.model_dump(mode="json")
    )
    assert document == prior_document and baseline.model_dump(mode="json") == prior_policy


def test_v2_loader_and_snapshot_shape_remain_replayable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _v2_policy()
    document = policy.model_dump(mode="json")
    validate_control_contract("codex-reviewed-capability-policy-v2", document)
    target = tmp_path / "legacy-v2.yaml"
    target.write_text(yaml.safe_dump(document))
    target.chmod(0o600)
    assert (
        load_reviewed_capability_policy(target, require_root_owned=False).model_dump(mode="json")
        == document
    )
    assert set(document["models"][1]["bindings"][0]) == {"binding_id", "assignment_revision_id"}
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: policy.compatibility_runtime,
    )
    session = SimpleNamespace(
        get=lambda *_args: SimpleNamespace(current_assignment_revision_id=None)
    )
    capabilities = reviewed_capabilities_for_binding(
        cast(Session, session),
        binding_id="authbinding_" + "2" * 32,
        policy=policy,
        cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
    )
    assert [item.model for item in capabilities] == ["Terra", "synthetic-model"]


@pytest.mark.parametrize("version", (2, 3))
def test_binding_shapes_cannot_cross_policy_versions(version: int) -> None:
    document = (_render() if version == 2 else _v2_policy()).model_dump(mode="json")
    document["version"] = version
    with pytest.raises(ValidationError, match="policy version"):
        ReviewedCapabilityPolicy.model_validate(document)


@pytest.mark.parametrize("mutation", ("missing", "disabled", "role", "duplicate"))
def test_current_binding_resolution_requires_all_six_correct_enabled_roles(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    rows = [
        (
            SimpleNamespace(
                binding_id=pin.binding_id,
                current_assignment_revision_id=None,
                resource_version=7,
                state="DEGRADED",
            ),
            SimpleNamespace(
                slot_id=pin.slot_id, role=COMPATIBILITY_SLOT_ROLES[pin.slot_id], enabled=True
            ),
        )
        for pin in _bindings(_role_report())
    ]
    if mutation == "missing":
        rows.pop()
    elif mutation == "disabled":
        rows[-1][1].enabled = False
    elif mutation == "role":
        rows[-1][1].role = "authoring"
    else:
        rows[-1] = rows[-2]

    @contextmanager
    def session() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(execute=lambda *_args: SimpleNamespace(all=lambda: rows))

    monkeypatch.setattr(admission, "build_session_factory", lambda _engine: session)
    runtime = _render().compatibility_runtime
    assert runtime is not None
    with pytest.raises(ControlPlaneError):
        current_admission_bindings(cast(Engine, SimpleNamespace()), runtime=runtime, now=NOW)


@pytest.mark.parametrize(
    "mutation", ("moved", "role", "disabled", "missing", "assignment", "runtime")
)
def test_v3_snapshot_reauthorizes_actual_binding_slot_role_assignment_and_runtime(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    policy = _render(_role_report(), baseline_policy=_baseline("0.146.0"))
    binding = SimpleNamespace(worker_slot_id="03", current_assignment_revision_id=None)
    slot = SimpleNamespace(slot_id="03", role="image", enabled=True)
    runtime = policy.compatibility_runtime
    assert runtime is not None
    if mutation == "moved":
        binding.worker_slot_id = "04"
        slot.slot_id, slot.role = "04", "item_management"
    elif mutation == "role":
        slot.role = "support"
    elif mutation == "disabled":
        slot.enabled = False
    elif mutation == "assignment":
        binding.current_assignment_revision_id = "authassignrev_" + "f" * 32
    elif mutation == "runtime":
        runtime = runtime.model_copy(update={"worker_exec_sha256": "sha256:" + "f" * 64})
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: runtime,
    )
    session = SimpleNamespace(
        get=lambda model, *_args: (
            binding
            if model is CodexAuthBindingRecord
            else (None if mutation == "missing" else slot)
        )
    )
    with pytest.raises(ControlPlaneError):
        reviewed_capabilities_for_binding(
            cast(Session, session),
            binding_id="authbinding_" + "4" * 32,
            policy=policy,
            cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
        )
