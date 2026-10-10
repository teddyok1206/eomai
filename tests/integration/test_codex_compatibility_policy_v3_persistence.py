"""Opt-in V3 SQL resolution/snapshot tests in a marker-guarded disposable DB only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import codex_compatibility_policy as admission
from eom_orchestrator.capability_observer import (
    COMPATIBILITY_SLOT_ROLES,
    REQUIRED_EXEC_HELP_FLAGS,
    ReviewedCapabilityPolicy,
    record_reviewed_capability_snapshot,
)
from eom_orchestrator.codex_compatibility_policy import (
    current_admission_bindings,
    render_compatibility_policy,
)
from eom_orchestrator.control_models import CodexAuthBindingRecord, CodexCapabilitySnapshotRecord
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    record_auth_health,
)
from eom_orchestrator.models import WorkerSlotRecord
from eom_workflow.codex_compatibility import load_compatibility_report
from eom_workflow.control_plane import WorkerRole
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from tests.integration import test_control_plane_persistence as control_fixture
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_codex_compatibility_policy_install import NOW, _baseline
from tests.unit.test_codex_compatibility_policy_v3 import _role_report

pytestmark = pytest.mark.integration


@pytest.fixture
def policy_session(guarded_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    with Session(guarded_engine) as session, session.begin():
        control_fixture._seed_protocols_and_slots(
            session, additional_slots={WorkerRole.SUPPORT: "06"}
        )
        for slot in COMPATIBILITY_SLOT_ROLES:
            existing = session.scalar(
                select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == slot)
            )
            if existing is None:
                record_auth_health(
                    session,
                    document={
                        "schema_version": "codex-auth-health-view/1.0",
                        "binding_id": "authbinding_" + uuid4().hex,
                        "slot_key": "slot" + slot,
                        "account_label": "disposable-compatibility-" + slot,
                        "state": "READY",
                        "reason_code": None,
                        "codex_cli_version": "0.147.0",
                        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                        "valid_until": (NOW + timedelta(hours=1))
                        .isoformat()
                        .replace("+00:00", "Z"),
                    },
                )
        session.flush()

        @contextmanager
        def same_read_transaction() -> Iterator[Session]:
            yield session

        # Reuse the transaction-owned connection so fixture rows remain rollback-only.
        # All admission statements are actual PostgreSQL queries, not stubbed rows.
        monkeypatch.setattr(
            admission, "build_session_factory", lambda _engine: same_read_transaction
        )
        yield session
        session.rollback()


def _actual_report(session: Session) -> dict[str, Any]:
    document = _role_report(
        tuple(
            (slot, "synthetic-model" if slot in {"01", "02"} else "role-model-" + slot, "medium")
            for slot in COMPATIBILITY_SLOT_ROLES
        )
    )
    bindings = {row.worker_slot_id: row for row in session.scalars(select(CodexAuthBindingRecord))}
    for case in (*document["request"]["cases"], *document["cases"]):
        row = bindings[case["slot_id"]]
        case.update(
            binding_id=row.binding_id,
            assignment_revision_id=row.current_assignment_revision_id,
            expected_resource_version=row.resource_version,
        )
    document["request_sha256"] = content_sha256(document["request"])
    return document


def _policy(engine: Engine, session: Session) -> ReviewedCapabilityPolicy:
    report = load_compatibility_report(_actual_report(session))
    pins = current_admission_bindings(engine, runtime=report.runtime, now=NOW)
    return render_compatibility_policy(
        report,
        baseline_policy=_baseline("0.146.0"),
        current_runtime=report.runtime,
        bindings=pins,
        now=NOW,
    )


def test_current_six_bindings_resolve_in_one_real_sql_query(
    guarded_engine: Engine, policy_session: Session
) -> None:
    statements: list[str] = []

    def capture(
        _connection: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
    ) -> None:
        statements.append(statement)

    report = load_compatibility_report(_actual_report(policy_session))
    event.listen(guarded_engine, "before_cursor_execute", capture)
    try:
        pins = current_admission_bindings(guarded_engine, runtime=report.runtime, now=NOW)
    finally:
        event.remove(guarded_engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "JOIN" in statements[0] and " IN " in statements[0]
    assert [pin.slot_id for pin in pins] == list(COMPATIBILITY_SLOT_ROLES)


@pytest.mark.parametrize("slot", tuple(COMPATIBILITY_SLOT_ROLES))
def test_v3_actual_binding_persists_only_its_scoped_metadata_snapshot(
    guarded_engine: Engine, policy_session: Session, monkeypatch: pytest.MonkeyPatch, slot: str
) -> None:
    policy = _policy(guarded_engine, policy_session)
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: policy.compatibility_runtime,
    )
    binding = policy_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == slot)
    )
    assert binding is not None
    row = record_reviewed_capability_snapshot(
        policy_session,
        binding_id=binding.binding_id,
        policy=policy,
        observed_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=15),
        cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
    )
    policy_session.flush()
    expected_model = "synthetic-model" if slot in {"01", "02"} else "role-model-" + slot
    assert [entry["model"] for entry in row.canonical_document["capabilities"]] == [expected_model]
    assert row.snapshot_sha256 == compute_control_document_hash(
        row.canonical_document, "snapshot_sha256"
    )
    assert len(json.dumps(row.canonical_document)) < 8192
    assert policy_session.get(CodexCapabilitySnapshotRecord, row.capability_snapshot_id) is row


@pytest.mark.parametrize("mutation", ("assignment", "slot", "role", "disabled", "runtime"))
def test_v3_real_resolution_refuses_stale_scope_without_snapshot_write(
    guarded_engine: Engine, policy_session: Session, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    policy = _policy(guarded_engine, policy_session)
    binding = policy_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "03")
    )
    assert binding is not None
    runtime = policy.compatibility_runtime
    assert runtime is not None
    document = policy.model_dump(mode="json")
    image_entry = next(item for item in document["models"] if item["model"] == "role-model-03")
    if mutation == "assignment":
        image_entry["bindings"][0]["assignment_revision_id"] = "authassignrev_" + "f" * 32
    elif mutation == "slot":
        image_entry["bindings"][0].update(slot_id="04", role="item_management")
    elif mutation in {"role", "disabled"}:
        slot = policy_session.get(WorkerSlotRecord, "03")
        assert slot is not None
        if mutation == "role":
            slot.role = "support"
        else:
            slot.enabled = False
        policy_session.flush()
    else:
        runtime = runtime.model_copy(update={"cli_binary_sha256": "sha256:" + "f" * 64})
    policy = ReviewedCapabilityPolicy.model_validate(document)
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: runtime,
    )
    before = policy_session.scalar(select(func.count()).select_from(CodexCapabilitySnapshotRecord))
    with pytest.raises(ControlPlaneError):
        record_reviewed_capability_snapshot(
            policy_session,
            binding_id=binding.binding_id,
            policy=policy,
            observed_at=NOW + timedelta(minutes=1),
            ttl=timedelta(minutes=15),
            cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
        )
    assert (
        policy_session.scalar(select(func.count()).select_from(CodexCapabilitySnapshotRecord))
        == before
    )


def test_v3_real_current_pin_refuses_resource_version_regression(
    guarded_engine: Engine, policy_session: Session
) -> None:
    document = _actual_report(policy_session)
    report = load_compatibility_report(document)
    pins = current_admission_bindings(guarded_engine, runtime=report.runtime, now=NOW)
    for case in (*document["request"]["cases"], *document["cases"]):
        if case["slot_id"] == "06":
            case["expected_resource_version"] += 1
    document["request_sha256"] = content_sha256(document["request"])
    with pytest.raises(ControlPlaneError, match="binding pins"):
        render_compatibility_policy(
            load_compatibility_report(document),
            baseline_policy=_baseline(),
            current_runtime=report.runtime,
            bindings=pins,
            now=NOW,
        )


def test_prior_v2_real_snapshot_remains_compatible(
    guarded_engine: Engine, policy_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(guarded_engine, policy_session)
    document = policy.model_dump(mode="json")
    document["version"] = 2
    for item in document["models"]:
        for pin in item["bindings"] or ():
            del pin["slot_id"]
            del pin["role"]
    policy = ReviewedCapabilityPolicy.model_validate(document)
    monkeypatch.setattr(
        "eom_orchestrator.codex_compatibility_runtime.observe_compatibility_runtime",
        lambda: policy.compatibility_runtime,
    )
    binding = policy_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "03")
    )
    assert binding is not None
    row = record_reviewed_capability_snapshot(
        policy_session,
        binding_id=binding.binding_id,
        policy=policy,
        observed_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=15),
        cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
    )
    assert row.canonical_document["capabilities"][0]["model"] == "role-model-03"
