"""Synthetic admission evidence only; no Codex/model/root/runtime operations."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_orchestrator import capability_observer as observer
from eom_orchestrator import codex_compatibility_policy as admission
from eom_orchestrator import control_artifact_resolution as resolution
from eom_orchestrator import control_command_processor as processor_module
from eom_orchestrator.capability_observer import (
    REQUIRED_EXEC_HELP_FLAGS,
    ReviewedCapabilityPolicy,
    load_reviewed_capability_policy,
    record_reviewed_capability_snapshot,
)
from eom_orchestrator.codex_compatibility_policy import (
    CompatibilityAdmissionBinding,
    current_admission_bindings,
    load_committed_compatibility_report,
    parse_compatibility_report,
    render_compatibility_policy,
)
from eom_orchestrator.codex_compatibility_probe import synthetic_probe_png
from eom_orchestrator.control_commands import terminalize_codex_control_command
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetMember
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobRecord,
)
from eom_orchestrator.worker_auth import WorkerAuthObservation
from eom_orchestrator.worker_registry import WorkerSlot
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.codex_compatibility import load_compatibility_report, load_compatibility_request
from eom_workflow.control_schemas import validate_control_contract
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError
from sqlalchemy import select

from scripts.workflow import install_codex_compatibility_policy as installer
from tests.unit.test_codex_compatibility_contracts import report_document, request_document
from tests.unit.test_control_file_set_publication import _publisher

NOW = datetime(2026, 10, 10, 1, tzinfo=UTC)
ASSIGNMENT = "authassignrev_" + "9" * 32


def _baseline(version: str = "0.147.0") -> ReviewedCapabilityPolicy:
    return ReviewedCapabilityPolicy.model_validate(
        {
            "version": 1,
            "expected_codex_cli_version": version,
            "models": [{"model": "Terra", "reasoning_efforts": ["medium", "high", "xhigh"]}],
        }
    )


def _bindings(document: dict[str, Any]) -> tuple[CompatibilityAdmissionBinding, ...]:
    return tuple(
        CompatibilityAdmissionBinding(
            case["slot_id"],
            case["binding_id"],
            case["assignment_revision_id"],
            case["expected_resource_version"],
        )
        for case in document["request"]["cases"][:2]
    )


def _render(document: dict[str, Any] | None = None, **options: Any) -> ReviewedCapabilityPolicy:
    document = document or report_document()
    report = load_compatibility_report(document)
    return render_compatibility_policy(
        report,
        baseline_policy=options.pop("baseline_policy", _baseline()),
        current_runtime=options.pop("current_runtime", report.runtime),
        bindings=options.pop("bindings", _bindings(document)),
        now=options.pop("now", NOW),
        **options,
    )


def test_policy_retains_baseline_and_scopes_only_live_passed_intersection() -> None:
    policy = _render()
    assert policy.version == 2
    assert policy.models[0] == _baseline().models[0]
    scoped = policy.models[1]
    assert scoped.model == "synthetic-model"
    assert scoped.reasoning_efforts == ("medium",)
    assert scoped.bindings is not None
    assert [(pin.binding_id, pin.assignment_revision_id) for pin in scoped.bindings] == [
        (binding.binding_id, None) for binding in _bindings(report_document())
    ]
    validate_control_contract("codex-reviewed-capability-policy-v2", policy.model_dump(mode="json"))


def test_new_cli_drops_every_untested_global_pair() -> None:
    policy = _render(baseline_policy=_baseline("0.146.0"))
    assert len(policy.models) == 1
    assert policy.models[0].model == "synthetic-model"
    assert policy.models[0].bindings is not None


def test_same_version_native_binary_change_drops_v2_global_pairs() -> None:
    prior = _render()
    document = report_document()
    document["runtime"]["cli_binary_sha256"] = "sha256:" + "f" * 64
    policy = _render(document, baseline_policy=prior)
    assert len(policy.models) == 1 and policy.models[0].bindings is not None


def test_previous_scoped_pairs_are_not_carried_forward() -> None:
    prior = _render()
    document = report_document()
    for container in (document["request"]["cases"], document["cases"]):
        for case in container:
            case["model"] = "next-synthetic-model"
    document["request_sha256"] = content_sha256(document["request"])
    policy = _render(document, baseline_policy=prior)
    assert [item.model for item in policy.models] == ["Terra", "next-synthetic-model"]


def test_new_effort_for_existing_global_model_remains_scoped() -> None:
    document = report_document()
    for container in (document["request"]["cases"], document["cases"]):
        for case in container:
            case.update(model="Terra", reasoning_effort="low")
    document["request_sha256"] = content_sha256(document["request"])
    policy = _render(document)
    assert [item.model for item in policy.models] == ["Terra", "Terra"]
    assert policy.models[0].bindings is None
    assert policy.models[1].reasoning_efforts == ("low",)
    assert policy.models[1].bindings is not None


@pytest.mark.parametrize("difference", ("model", "reasoning_effort", "failed"))
def test_only_one_binding_pass_is_not_admitted(difference: str) -> None:
    document = report_document()
    if difference == "failed":
        document["cases"][1].update(status="FAIL", error_code="WORKER_EXEC_FAILED")
    else:
        value = "different-model" if difference == "model" else "high"
        document["cases"][1][difference] = value
        document["request"]["cases"][1][difference] = value
        document["request_sha256"] = content_sha256(document["request"])
    with pytest.raises(ControlPlaneError, match="no exact model/effort"):
        _render(document)


@pytest.mark.parametrize("change", ("id", "version", "assignment", "slot", "duplicate"))
def test_admission_rejects_changed_current_binding_pins(change: str) -> None:
    document = report_document()
    values = list(_bindings(document))
    pin = values[0]
    replacements = {
        "id": CompatibilityAdmissionBinding(pin.slot_id, "authbinding_" + "8" * 32, None, 7),
        "version": CompatibilityAdmissionBinding(pin.slot_id, pin.binding_id, None, 6),
        "assignment": CompatibilityAdmissionBinding(pin.slot_id, pin.binding_id, ASSIGNMENT, 7),
        "slot": CompatibilityAdmissionBinding("03", pin.binding_id, None, 7),
        "duplicate": CompatibilityAdmissionBinding(pin.slot_id, values[1].binding_id, None, 7),
    }
    values[0] = replacements[change]
    with pytest.raises(ControlPlaneError):
        _render(document, bindings=tuple(values))


def test_observation_only_resource_version_advance_preserves_assignment_admission() -> None:
    document = report_document()
    bindings = tuple(
        CompatibilityAdmissionBinding(pin.slot_id, pin.binding_id, pin.assignment_revision_id, 8)
        for pin in _bindings(document)
    )
    policy = _render(document, bindings=bindings)
    assert policy.models[1].bindings is not None


@pytest.mark.parametrize("age", (timedelta(hours=24, seconds=1), -timedelta(seconds=1)))
def test_stale_or_future_reports_do_not_admit(age: timedelta) -> None:
    report = load_compatibility_report(report_document())
    with pytest.raises(ControlPlaneError):
        _render(now=report.completed_at + age)


def test_report_runtime_must_match_every_current_hash() -> None:
    report = load_compatibility_report(report_document())
    for name in (
        "cli_launcher_sha256",
        "cli_binary_sha256",
        "worker_exec_sha256",
        "contract_sha256",
    ):
        current = report.runtime.model_copy(update={name: "sha256:" + "f" * 64})
        with pytest.raises(ControlPlaneError):
            _render(current_runtime=current)


@pytest.mark.parametrize("value", (None, ASSIGNMENT))
def test_assignment_pin_is_required_nullable_and_preserved(value: str | None) -> None:
    request = request_document()
    request["cases"][0]["assignment_revision_id"] = value
    parsed = load_compatibility_request(request)
    assert parsed.model_dump(mode="json")["cases"][0]["assignment_revision_id"] == value
    del request["cases"][0]["assignment_revision_id"]
    with pytest.raises(SchemaValidationError):
        load_compatibility_request(request)


def test_report_cannot_repin_account_assignment() -> None:
    document = report_document()
    document["cases"][0]["assignment_revision_id"] = ASSIGNMENT
    with pytest.raises(ValidationError, match="ordered requested case pin"):
        load_compatibility_report(document)


@pytest.mark.parametrize(
    "value", (b"{}", b'{"a":1,"a":2}', b"not-json", b"\xff", b"x" * (128 * 1024 + 1))
)
def test_non_live_or_malformed_input_is_not_a_report(value: bytes) -> None:
    with pytest.raises(ControlPlaneError):
        parse_compatibility_report(value)


def test_scoped_policy_load_preserves_null_assignment_and_rejects_unknown_keys(
    tmp_path: Path,
) -> None:
    document = _render().model_dump(mode="json")
    target = tmp_path / "policy.yaml"
    target.write_text(yaml.safe_dump(document))
    target.chmod(0o600)
    parsed = load_reviewed_capability_policy(target, require_root_owned=False)
    assert parsed == _render()
    document["models"][1]["bindings"][0]["invented_authority"] = True
    target.write_text(yaml.safe_dump(document))
    with pytest.raises(ControlPlaneError):
        load_reviewed_capability_policy(target, require_root_owned=False)


@pytest.mark.parametrize("mutation", ("runtime", "scope", "duplicate", "version"))
def test_v1_and_v2_policy_invariants(mutation: str) -> None:
    document = _baseline().model_dump(mode="json")
    if mutation == "runtime":
        document["compatibility_runtime"] = _render().compatibility_runtime
    elif mutation == "scope":
        document["models"][0]["bindings"] = [
            {"binding_id": "authbinding_" + "2" * 32, "assignment_revision_id": None}
        ]
    elif mutation == "duplicate":
        document = _render().model_dump(mode="json")
        document["models"].append(deepcopy(document["models"][1]))
    else:
        document["version"] = True
    with pytest.raises(ValidationError):
        ReviewedCapabilityPolicy.model_validate(document)


def _snapshot(
    monkeypatch: pytest.MonkeyPatch,
    policy: ReviewedCapabilityPolicy,
    binding_id: str,
    assignment: str | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: policy.compatibility_runtime,
    )
    monkeypatch.setattr(
        observer,
        "record_capability_snapshot",
        lambda _session, *, document: captured.update(document) or document,
    )
    session = SimpleNamespace(
        get=lambda *_args: SimpleNamespace(current_assignment_revision_id=assignment)
    )
    record_reviewed_capability_snapshot(
        session,
        binding_id=binding_id,
        policy=policy,
        observed_at=NOW,
        ttl=timedelta(hours=1),
        cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
    )
    return captured


def test_untested_binding_only_gets_legacy_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot(monkeypatch, _render(), "authbinding_" + "6" * 32)
    assert [item["model"] for item in snapshot["capabilities"]] == ["Terra"]


def test_tested_binding_gets_scoped_model_and_legacy_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(monkeypatch, _render(), "authbinding_" + "2" * 32)
    assert [item["model"] for item in snapshot["capabilities"]] == ["Terra", "synthetic-model"]


def test_reassigned_account_loses_scoped_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot(monkeypatch, _render(), "authbinding_" + "2" * 32, ASSIGNMENT)
    assert [item["model"] for item in snapshot["capabilities"]] == ["Terra"]


def test_no_admitted_binding_has_stable_error_and_no_snapshot_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _render(baseline_policy=_baseline("0.146.0"))
    with pytest.raises(ControlPlaneError) as caught:
        _snapshot(monkeypatch, policy, "authbinding_" + "6" * 32)
    assert caught.value.code == "CONTROL_CAPABILITY_BINDING_UNVERIFIED"


def test_scoped_and_global_efforts_merge_once_for_tested_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = report_document()
    for container in (document["request"]["cases"], document["cases"]):
        for case in container:
            case.update(model="Terra", reasoning_effort="low")
    document["request_sha256"] = content_sha256(document["request"])
    policy = _render(document)
    tested = _snapshot(monkeypatch, policy, "authbinding_" + "2" * 32)
    untested = _snapshot(monkeypatch, policy, "authbinding_" + "6" * 32)
    assert len(tested["capabilities"]) == 1
    assert set(tested["capabilities"][0]["reasoning_efforts"]) == {"low", "medium", "high", "xhigh"}
    assert set(untested["capabilities"][0]["reasoning_efforts"]) == {"medium", "high", "xhigh"}


def test_v1_snapshot_order_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot(monkeypatch, _baseline(), "authbinding_" + "2" * 32)
    assert snapshot["capabilities"][0]["reasoning_efforts"] == ["medium", "high", "xhigh"]


def test_v2_runtime_identity_guard_rejects_same_version_changed_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _render()
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: policy.compatibility_runtime.model_copy(
            update={"cli_binary_sha256": "sha256:" + "f" * 64}
        ),
    )
    with pytest.raises(ControlPlaneError) as caught:
        record_reviewed_capability_snapshot(
            SimpleNamespace(),
            binding_id="authbinding_" + "2" * 32,
            policy=policy,
            observed_at=NOW,
            ttl=timedelta(hours=1),
            cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
        )
    assert caught.value.code == "CONTROL_CAPABILITY_POLICY_MISMATCH"


def test_observe_command_terminalizes_unverified_error_without_rewriting_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = SimpleNamespace(
        command_id="codexcmd_" + "1" * 32,
        command_type="OBSERVE",
        binding_id="authbinding_" + "2" * 32,
        expected_resource_version=7,
        canonical_document={},
        state="PROCESSING",
        lease_owner="runner",
        lease_expires_at=NOW + timedelta(minutes=1),
        result_resource_version=None,
        result_document=None,
        error_code=None,
        processed_at=None,
    )
    session = SimpleNamespace(
        execute=lambda *_args: SimpleNamespace(scalar_one_or_none=lambda: record),
        flush=lambda: None,
    )

    @contextmanager
    def transaction(_sessions: object):
        yield session

    monkeypatch.setattr(processor_module, "transaction", transaction)
    monkeypatch.setattr(
        processor_module, "claim_next_codex_control_command", lambda *_args, **_kwargs: record
    )
    processor = processor_module.CodexControlCommandProcessor(
        lambda: session,
        capability_policy_path=tmp_path / "unused",
        runner_id="runner",
        now=lambda: NOW,
    )

    def refuse(**_kwargs: object) -> None:
        raise ControlPlaneError("CONTROL_CAPABILITY_BINDING_UNVERIFIED", "unverified")

    monkeypatch.setattr(processor, "_observe_or_enable", refuse)
    assert processor.process_once() == record.command_id
    assert record.state == "FAILED" and record.error_code == "CONTROL_CAPABILITY_BINDING_UNVERIFIED"
    original = deepcopy(record.result_document)
    record.state = "SUCCEEDED"
    terminalize_codex_control_command(
        session,
        command_id=record.command_id,
        lease_owner="runner",
        outcome="FAILED",
        result_resource_version=None,
        binding_state=None,
        reason_code="CONTROL_CAPABILITY_BINDING_UNVERIFIED",
        processed_at=NOW,
    )
    assert record.state == "SUCCEEDED" and record.result_document == original


def test_current_binding_lookup_allows_old_degraded_observation_but_not_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        (
            SimpleNamespace(
                binding_id=case["binding_id"],
                current_assignment_revision_id=ASSIGNMENT,
                resource_version=7,
                state="DEGRADED",
                codex_cli_version="0.1.0",
                observed_at=None,
                valid_until=None,
            ),
            SimpleNamespace(slot_id=case["slot_id"], role=role, enabled=True),
        )
        for case, role in zip(request_document()["cases"], ("authoring", "review"), strict=True)
    ]

    @contextmanager
    def session():
        yield SimpleNamespace(execute=lambda *_args: SimpleNamespace(all=lambda: rows))

    monkeypatch.setattr(admission, "build_session_factory", lambda _engine: session)
    report = load_compatibility_report(report_document())
    bindings = current_admission_bindings(SimpleNamespace(), runtime=report.runtime, now=NOW)
    assert [pin.assignment_revision_id for pin in bindings] == [ASSIGNMENT, ASSIGNMENT]
    rows[0][0].state = "DISABLED"
    with pytest.raises(ControlPlaneError):
        current_admission_bindings(SimpleNamespace(), runtime=report.runtime, now=NOW)


@pytest.mark.parametrize("unverified", ("untested", "reassigned", "runtime_changed"))
def test_automatic_refresh_degrades_unverified_v2_without_crashing_or_writing_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unverified: str
) -> None:
    policy = _render(baseline_policy=_baseline("0.146.0"))
    runtime = policy.compatibility_runtime
    assert runtime is not None
    binding_id = "authbinding_" + ("6" if unverified == "untested" else "2") * 32
    assignment = ASSIGNMENT if unverified == "reassigned" else None
    if unverified == "runtime_changed":
        runtime = runtime.model_copy(update={"cli_binary_sha256": "sha256:" + "f" * 64})
    binding = SimpleNamespace(
        binding_id=binding_id,
        resource_version=7,
        worker_slot_id="01",
        current_assignment_revision_id=assignment,
    )
    target = SimpleNamespace(
        binding_id=binding_id,
        expected_resource_version=7,
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        account_label="synthetic-account",
    )
    auth = WorkerAuthObservation(
        binding_id,
        "slot01",
        "synthetic-account",
        "READY",
        None,
        "0.147.0",
        NOW,
        NOW + timedelta(hours=1),
        "eom-worker-auth-01.service",
    )
    session = SimpleNamespace(
        get=lambda model, *_args, **_kwargs: (
            binding if model is CodexAuthBindingRecord else SimpleNamespace(enabled=True)
        )
    )

    @contextmanager
    def sessions():
        yield session

    @contextmanager
    def transaction(_sessions: object):
        yield session

    captured = []
    monkeypatch.setattr(processor_module, "transaction", transaction)
    monkeypatch.setattr(
        processor_module, "_next_automatic_observation_target", lambda *_args, **_kwargs: target
    )
    monkeypatch.setattr(
        processor_module, "_automatic_observation_is_due", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(
        processor_module, "_binding_has_held_lease", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(
        processor_module, "_binding_has_pending_command", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(processor_module, "observe_worker_auth", lambda **_kwargs: auth)
    monkeypatch.setattr(processor_module, "load_reviewed_capability_policy", lambda _path: policy)
    monkeypatch.setattr(
        processor_module, "observe_codex_cli_surface", lambda: ("0.147.0", REQUIRED_EXEC_HELP_FLAGS)
    )
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        processor_module,
        "persist_worker_auth_observation",
        lambda _session, observation: captured.append(observation.document()),
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unverified automatic refresh must not write a capability snapshot")

    monkeypatch.setattr(processor_module, "record_reviewed_capability_snapshot", forbidden)
    processor = processor_module.CodexControlCommandProcessor(
        sessions, capability_policy_path=tmp_path / "unused", runner_id="runner", now=lambda: NOW
    )
    assert processor.maintain_once() == binding_id
    assert len(captured) == 1
    assert captured[0]["state"] == "DEGRADED"
    assert captured[0]["reason_code"] == "CAPABILITY_OBSERVATION_FAILED"


def _installed_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, bytes]:
    tmp_path.chmod(0o700)
    target = tmp_path / "codex-capabilities.yaml"
    prior = b"version: 1\n"
    target.write_bytes(prior)
    target.chmod(0o644)
    monkeypatch.setattr(installer, "POLICY_TARGET", target)
    return target, prior


def test_atomic_policy_advance_keeps_verified_backup_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, prior = _installed_target(tmp_path, monkeypatch)
    payload = yaml.safe_dump(_render().model_dump(mode="json"), sort_keys=True).encode()
    options = {"previous_sha256": sha256_bytes(prior), "uid": os.geteuid(), "gid": os.getegid()}
    assert installer.install_policy_bytes(payload, **options) == "INSTALLED"
    assert target.read_bytes() == payload
    assert target.stat().st_mode & 0o777 == 0o644
    assert (
        target.with_name(
            "codex-capabilities.previous." + sha256_bytes(prior)[7:] + ".yaml"
        ).read_bytes()
        == prior
    )
    assert installer.install_policy_bytes(payload, **options) == "REPLAYED"
    assert (
        yaml.safe_load(target.read_bytes())["models"][1]["bindings"][0]["assignment_revision_id"]
        is None
    )
    assert not list(tmp_path.glob(".codex-capabilities.*"))


@pytest.mark.parametrize("unsafe", ("predecessor", "symlink", "writable", "hardlink", "backup"))
def test_policy_target_safety_refuses_and_preserves_prior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    target, prior = _installed_target(tmp_path, monkeypatch)
    expected = sha256_bytes(prior)
    if unsafe == "predecessor":
        expected = "sha256:" + "f" * 64
    elif unsafe == "symlink":
        original = target.with_name("original.yaml")
        target.rename(original)
        target.symlink_to(original)
    elif unsafe == "writable":
        target.chmod(0o666)
    elif unsafe == "hardlink":
        os.link(target, target.with_name("other.yaml"))
    else:
        backup = target.with_name("codex-capabilities.previous." + expected[7:] + ".yaml")
        backup.write_bytes(b"wrong backup")
        backup.chmod(0o644)
    with pytest.raises(ControlPlaneError):
        installer.install_policy_bytes(
            b"version: 2\n", previous_sha256=expected, uid=os.geteuid(), gid=os.getegid()
        )
    assert target.read_bytes() == prior
    assert not list(tmp_path.glob(".codex-capabilities.*"))


def test_failed_atomic_replace_preserves_prior_and_cleans_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, prior = _installed_target(tmp_path, monkeypatch)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(installer.os, "replace", fail)
    with pytest.raises(ControlPlaneError):
        installer.install_policy_bytes(
            b"version: 2\n", previous_sha256=sha256_bytes(prior), uid=os.geteuid(), gid=os.getegid()
        )
    assert target.read_bytes() == prior and not list(tmp_path.glob(".codex-capabilities.*"))


class _SqliteReadConnection:
    """Only adapt PostgreSQL's read-only SET and JSONB decoding for local SQLite."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.result: Any = None

    def execute(self, statement: Any, parameters: Any = None) -> Any:
        if str(statement).startswith("SET TRANSACTION"):
            return None
        self.result = self.connection.execute(statement, parameters or {})
        return self

    def mappings(self) -> _SqliteReadConnection:
        return self

    def _decode(self, row: Any) -> dict[str, Any]:
        result = dict(row)
        result["manifest"] = json.loads(result["manifest"])
        return result

    def one_or_none(self) -> dict[str, Any] | None:
        row = self.result.mappings().one_or_none()
        return self._decode(row) if row is not None else None

    def all(self) -> list[dict[str, Any]]:
        return [self._decode(row) for row in self.result.mappings().all()]


def _published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, wrong_answer: bool = False):
    publisher, engine = _publisher(tmp_path)
    document = report_document()
    files: dict[str, bytes] = {"request.json": canonical_json_bytes(document["request"])}
    for case in document["cases"]:
        invocation = {
            "schema_version": "codex-compatibility-invocation/1.0",
            "run_id": document["request"]["run_id"],
            "case_id": case["case_id"],
            "request_sha256": document["request_sha256"],
            "job_id": case["job_id"],
            "model": case["model"],
            "reasoning_effort": case["reasoning_effort"],
            "image_sha256": sha256_bytes(synthetic_probe_png()),
        }
        result = {
            "schema_version": "codex-compatibility-probe-result/1.0",
            "run_id": invocation["run_id"],
            "case_id": invocation["case_id"],
            "request_sha256": invocation["request_sha256"],
            "arithmetic_sum": 42 if wrong_answer else 43,
            "rectangle_count": 1,
            "outline_circle_count": 1,
            "left_shape": "square",
            "right_shape": "circle",
        }
        payload = canonical_json_bytes(result)
        files[f"{case['case_id']}.output.json"] = payload
        case["invocation_sha256"] = content_sha256(invocation)
        case["result_sha256"] = sha256_bytes(payload)
    files["report.json"] = canonical_json_bytes(document)
    source = tmp_path / "sources"
    source.mkdir()
    members = []
    for name, payload in sorted(files.items()):
        path = source / name
        path.write_bytes(payload)
        path.chmod(0o600)
        schema = (
            "codex-compatibility-request/1.0"
            if name == "request.json"
            else "codex-compatibility-report/1.0"
            if name == "report.json"
            else "codex-compatibility-probe-result/1.0"
        )
        members.append(
            ControlFileSetMember(
                name,
                path,
                sha256_file(path),
                len(payload),
                "eom://schemas/workflow/" + schema,
                "application/json",
            )
        )
    published = publisher.publish(
        members=tuple(members),
        primary_file="report.json",
        artifact_type=admission.COMPATIBILITY_ARTIFACT_TYPE,
        manifest_version=admission.COMPATIBILITY_MANIFEST_VERSION,
        idempotency_key=document["request"]["run_id"],
        source_commit=document["request"]["source_commit"],
        created_at=load_compatibility_report(document).completed_at,
    )

    @contextmanager
    def connection():
        with engine.connect() as underlying:
            yield _SqliteReadConnection(underlying)

    read_engine = SimpleNamespace(connect=connection)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_member",
        lambda _engine, pointer, **options: resolution.resolve_control_artifact_member(
            read_engine, pointer, **options
        ),
    )
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda _engine, reads: resolution.resolve_control_artifact_members(read_engine, reads),
    )
    pointer = ArtifactMemberPointer(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path="report.json",
        schema_ref=admission.COMPATIBILITY_REPORT_SCHEMA,
        media_type="application/json",
        sha256=published.primary_sha256,
    )
    return publisher, engine, published, pointer, document


def test_real_control_file_set_publication_resolves_and_admits_exact_proofs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publisher_value, engine, _published_value, pointer, document = _published(
        tmp_path, monkeypatch
    )
    report = load_committed_compatibility_report(engine, pointer)
    assert report == load_compatibility_report(document)
    assert _render(document).models[1].model == "synthetic-model"


@pytest.mark.parametrize(
    "wrong", ("approval", "status", "task", "protocol", "manifest", "request", "result", "pointer")
)
def test_noncanonical_publication_is_never_admission_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong: str
) -> None:
    publisher, engine, _published_value, pointer, _document = _published(tmp_path, monkeypatch)
    with publisher.sessions.begin() as session:
        artifact = session.scalar(select(ArtifactRecord))
        revision = session.scalar(select(ArtifactRevisionRecord))
        job = session.scalar(select(JobRecord))
        assert artifact is not None and revision is not None and job is not None
        if wrong == "approval":
            revision.approved = False
        elif wrong == "status":
            job.status = "FAILED"
        elif wrong == "task":
            job.task_type = "control_fake_catalog"
        elif wrong == "protocol":
            job.protocol_version = "non-live/1.0"
        elif wrong == "manifest":
            revision.manifest_hash = "sha256:" + "f" * 64
        elif wrong == "request":
            request = deepcopy(job.request)
            request["source_commit"] = "0" * 40
            job.request = request
        elif wrong == "result":
            revision.result = {}
        else:
            pointer = pointer.model_copy(update={"sha256": "sha256:" + "f" * 64})
    with pytest.raises(ControlPlaneError):
        load_committed_compatibility_report(engine, pointer)


def test_committed_pass_claim_with_wrong_probe_answers_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publisher_value, engine, _published_value, pointer, _document = _published(
        tmp_path, monkeypatch, wrong_answer=True
    )
    with pytest.raises(ControlPlaneError, match="result proof is invalid"):
        load_committed_compatibility_report(engine, pointer)


def test_stored_result_hash_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publisher_value, engine, published, pointer, document = _published(tmp_path, monkeypatch)
    path = Path(published.nas_path) / f"{document['cases'][0]['case_id']}.output.json"
    path.chmod(0o600)
    path.write_bytes(b"{}")
    with pytest.raises(resolution.ControlArtifactResolutionError, match="HASH_MISMATCH"):
        load_committed_compatibility_report(engine, pointer)
