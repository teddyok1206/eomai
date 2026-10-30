"""A new purpose grants three physical workers, not new credentials or generic role bypass."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError, capacity_worker_role_clause
from eom_orchestrator.models import WorkerSlotRecord
from eom_workflow import WorkerCapacityPolicyV4, WorkerCapacityPolicyV5, validate_control_contract
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def capacity_value():
    body = {
        "schema_version": "worker-capacity-policy/1.4",
        "capacity_policy_id": "capacity_" + "a" * 32,
        "capacity_policy_revision_id": "capacityrev_" + "b" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "purpose": "CREATIVE_REPORT_BACKFILL",
        "max_configured_slots": 6,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 3,
        "pools": [
            {
                "pool_key": "creative-reports",
                "roles": ["support"],
                "slot_keys": ["slot04", "slot05", "slot06"],
                "max_active": 3,
            }
        ],
        "delegated_slot_roles": [
            {
                "pool_key": "creative-reports",
                "slot_key": "slot04",
                "native_role": "item_management",
                "execution_role": "support",
            }
        ],
        "created_at": "2026-10-30T00:00:00Z",
    }
    return {**body, "content_sha256": content_sha256(body)}


def policy_row():
    value = capacity_value()
    return SimpleNamespace(**value, canonical_document=value)


@pytest.fixture
def slots():
    # Only the ordinary worker inventory table is needed for this SQL predicate test.
    # No claim/lease/state-machine concurrency is inferred from SQLite.
    engine = create_engine("sqlite://")
    WorkerSlotRecord.__table__.create(engine)
    with Session(engine) as session, session.begin():
        for number, role in (
            ("01", "authoring"),
            ("04", "item_management"),
            ("05", "support"),
            ("06", "support"),
        ):
            session.add(
                WorkerSlotRecord(
                    slot_id=number,
                    linux_user="eom-cdx-" + number,
                    role=role,
                    enabled=True,
                    gpu=False,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    with Session(engine) as session:
        yield session
    engine.dispose()


def eligible(session, policy, *, pool="creative-reports", role="support"):
    return tuple(
        session.scalars(
            select(WorkerSlotRecord.slot_id)
            .where(capacity_worker_role_clause(policy, pool_key=pool, execution_role=role))
            .order_by(WorkerSlotRecord.slot_id)
        )
    )


def test_schema_model_mirror_and_immutable_roundtrip():
    root = Path(__file__).resolve().parents[2]
    member = "control-plane/worker-capacity-policy-v5.schema.json"
    assert (root / "schemas/workflow" / member).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources" / member
    ).read_bytes()
    value = capacity_value()
    validate_control_contract("worker-capacity-policy-v5", value)
    parsed = WorkerCapacityPolicyV5.model_validate(value)
    assert WorkerCapacityPolicyV5.model_validate_json(parsed.model_dump_json()) == parsed
    with pytest.raises(ValueError):
        parsed.max_active_codex = 4


@pytest.mark.parametrize(
    "field", ["slot", "role", "pool", "global", "knowledge", "extra", "revision"]
)
def test_scope_cannot_be_arbitrarily_broadened(field):
    value = deepcopy(capacity_value())
    if field == "slot":
        value["delegated_slot_roles"][0]["slot_key"] = "slot01"
    elif field == "role":
        value["delegated_slot_roles"][0]["execution_role"] = "authoring"
    elif field == "pool":
        value["pools"][0]["slot_keys"] = ["slot01", "slot05", "slot06"]
    elif field == "global":
        value["max_active_codex"] = 4
    elif field == "knowledge":
        value["max_active_knowledge_analysis"] = 4
    elif field == "extra":
        value["delegated_slot_roles"].append(dict(value["delegated_slot_roles"][0]))
    else:
        value["revision_number"] = 5
    with pytest.raises(ValueError):
        WorkerCapacityPolicyV5.model_validate(value)


def test_exact_new_policy_grants_only_the_reviewed_native_slot_role(slots):
    assert eligible(slots, policy_row()) == ("04", "05", "06")
    assert slots.get(WorkerSlotRecord, "04").role == "item_management"


def test_wrong_pool_or_role_does_not_receive_the_delegation(slots):
    assert eligible(slots, policy_row(), pool="support") == ("05", "06")
    assert eligible(slots, policy_row(), role="authoring") == ("01",)
    # Actual pool membership/role, claim and capability gates apply separately.


def test_predecessor_policy_has_no_delegation(slots):
    row = policy_row()
    row.schema_version = "worker-capacity-policy/1.3"
    assert eligible(slots, row) == ("05", "06")
    with pytest.raises(ValueError):
        WorkerCapacityPolicyV4.model_validate(capacity_value())


def test_rewritten_physical_role_is_not_a_valid_delegation(slots):
    slots.get(WorkerSlotRecord, "04").role = "support"
    slots.flush()
    assert eligible(slots, policy_row()) == ("05", "06")
    with pytest.raises(ValueError, match="default role differs"):
        WorkerCapacityPolicyV5.model_validate(capacity_value()).execution_role_for_slot(
            pool_key="creative-reports", slot_key="slot04", native_role="support"
        )


@pytest.mark.parametrize("field", ["hash", "id", "limit", "state", "document"])
def test_stale_or_unreleased_policy_is_rejected_before_eligibility(slots, field):
    row = policy_row()
    if field == "hash":
        row.content_sha256 = "sha256:" + "0" * 64
    elif field == "id":
        row.capacity_policy_revision_id = "capacityrev_" + "0" * 32
    elif field == "limit":
        row.max_active_knowledge_analysis = 2
    elif field == "state":
        row.state = "DRAFT"
    else:
        row.canonical_document = {**row.canonical_document, "content_sha256": "sha256:" + "0" * 64}
    with pytest.raises(ControlPlaneError):
        eligible(slots, row)
