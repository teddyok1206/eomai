"""Slot identity, probe distribution, timeout and preset isolation without inference."""

import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.preset_model_selection import require_model_only_successor
from eom_orchestrator.shared_slot_controls import authorize_shared_slot_release
from eom_orchestrator.shared_worker_units import SHARED_WORKER_TEMPLATE_SHA256
from eom_orchestrator.worker_registry import FIXED_WORKER_LAYOUT, WorkerSlot
from eom_orchestrator.worker_systemd import worker_unit_name_for_execution
from eom_workflow import validate_control_contract
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.shared_worker_capacity import (
    ORDINARY_SLOT_IDS,
    ORDINARY_SLOT_KEYS,
    PHYSICAL_ROLES,
    SharedWorkerCapacityPolicy,
    ordinary_slot_probe_order,
)
from pydantic import ValidationError

from tests.unit.test_preset_model_selection import _draft, _preset, _self_hash

ROOT = Path(__file__).resolve().parents[2]


def test_owner_unit_preflight_does_not_read_privileged_polkit_directory(monkeypatch):
    from eom_orchestrator import worker_systemd

    inspected = []

    def check(path, **kwargs):
        inspected.append(path)
        if path.is_relative_to("/etc/polkit-1"):
            raise PermissionError("root-only policy directory")

    monkeypatch.setattr(worker_systemd, "_validate_root_owned_artifact", check)
    worker_systemd.require_shared_worker_units()
    assert len(inspected) == len(SHARED_WORKER_TEMPLATE_SHA256) == 11
    with pytest.raises(PermissionError):
        worker_systemd.require_shared_worker_deployment()


def test_deployment_preflight_includes_polkit_and_all_fixed_units(monkeypatch):
    from eom_orchestrator import worker_systemd

    inspected = []
    monkeypatch.setattr(
        worker_systemd,
        "_validate_root_owned_artifact",
        lambda path, **kwargs: inspected.append((path, kwargs)),
    )
    worker_systemd.require_shared_worker_deployment()
    assert len(inspected) == 12
    assert inspected[0][0] == Path("/etc/polkit-1/rules.d/50-eom-worker-units.rules")
    assert all(options["expected_mode"] == 0o644 for _, options in inspected)


def test_shared_release_requires_the_same_fresh_control_administrator():
    now = datetime(2026, 11, 12, tzinfo=UTC)
    values = dict(
        operator_id="operator-test",
        roles=("ADMIN",),
        effective_permissions=(
            PermissionKey.EXECUTION_PRESET_MANAGE.value,
            PermissionKey.CODEX_ACCOUNT_MANAGE.value,
        ),
        authenticated_at=now,
    )
    authorize_shared_slot_release(
        SimpleNamespace(**values), operator_id="operator-test", observed_at=now
    )
    for change in (
        dict(operator_id="other-operator"),
        dict(roles=("WORKER",)),
        dict(effective_permissions=(PermissionKey.EXECUTION_PRESET_MANAGE.value,)),
        dict(effective_permissions=(PermissionKey.CODEX_ACCOUNT_MANAGE.value,)),
        dict(authenticated_at=now - timedelta(minutes=15, microseconds=1)),
        dict(authenticated_at=now + timedelta(microseconds=1)),
        dict(authenticated_at=now.replace(tzinfo=None)),
        dict(authenticated_at=now.astimezone(timezone(timedelta(hours=9)))),
    ):
        with pytest.raises(ControlPlaneError, match="current administrator required"):
            authorize_shared_slot_release(
                SimpleNamespace(**(values | change)), operator_id="operator-test", observed_at=now
            )


def capacity_value():
    value = dict(
        schema_version="worker-capacity-policy/1.7",
        purpose="SHARED_ORDINARY_SLOTS",
        capacity_policy_id="capacity_" + "1" * 32,
        capacity_policy_revision_id="capacityrev_" + "1" * 32,
        revision_number=1,
        state="RELEASED",
        max_configured_slots=6,
        max_active_codex=4,
        max_active_per_slot=1,
        max_active_gpu=1,
        max_active_knowledge_analysis=4,
        pools=[
            dict(pool_key=role, roles=[role], slot_keys=list(ORDINARY_SLOT_KEYS), max_active=4)
            for role in ("authoring", "review", "image", "item_management", "support")
        ],
        created_at=datetime(2026, 11, 12, tzinfo=UTC).isoformat(),
    )
    return value | {"content_sha256": content_sha256(value)}


def test_schema_mirror_and_hash_registry():
    value = capacity_value()
    validate_control_contract("worker-capacity-policy-v8", value)
    assert SharedWorkerCapacityPolicy.model_validate(value).max_active_codex == 4
    assert (
        ROOT / "schemas/workflow/control-plane/worker-capacity-policy-v8.schema.json"
    ).read_bytes() == (
        ROOT
        / "packages/workflow/eom_workflow/resources/control-plane"
        / "worker-capacity-policy-v8.schema.json"
    ).read_bytes()


@pytest.mark.parametrize("slot", ORDINARY_SLOT_KEYS)
@pytest.mark.parametrize("role", ("authoring", "review", "image", "item_management", "support"))
def test_every_role_can_use_every_ordinary_identity(slot, role):
    policy = SharedWorkerCapacityPolicy.model_validate(capacity_value())
    assert policy.execution_roles_for_slot(
        pool_key=role, slot_key=slot, native_role=PHYSICAL_ROLES[slot]
    ) == (role,)
    with pytest.raises(ValueError):
        policy.execution_roles_for_slot(pool_key=role, slot_key=slot, native_role="wrong")


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(max_active_codex=5),
        lambda d: d.update(max_active_gpu=2),
        lambda d: d.update(max_active_per_slot=2),
        lambda d: d.update(max_configured_slots=5),
        lambda d: d["pools"][0]["slot_keys"].__setitem__(4, "slot06"),
        lambda d: d["pools"][0]["slot_keys"].reverse(),
        lambda d: d["pools"][0]["slot_keys"].__setitem__(4, "slot01"),
        lambda d: d["pools"][0].update(max_active=5),
        lambda d: d["pools"][0].update(roles=["authoring", "authoring"]),
        lambda d: d["pools"].append(deepcopy(d["pools"][0])),
    ],
)
def test_reject_overcapacity_chat_membership_and_duplicate_pools(change):
    value = capacity_value()
    change(value)
    with pytest.raises(ValidationError):
        SharedWorkerCapacityPolicy.model_validate(value)


@pytest.mark.parametrize("number", range(100))
def test_probe_is_deterministic_covers_each_slot_once_and_never_chat(number):
    identity = "job_" + f"{number:032x}"
    order = ordinary_slot_probe_order(identity)
    assert order == ordinary_slot_probe_order(identity)
    assert set(order) == set(ORDINARY_SLOT_IDS) and len(order) == 5


def test_probe_start_does_not_starve_lower_or_higher_slots():
    assert {ordinary_slot_probe_order("job_" + f"{n:032x}")[0] for n in range(100)} == set(
        ORDINARY_SLOT_IDS
    )


@pytest.mark.parametrize(
    "value",
    (
        "",
        "job_" + "A" * 32,
        "job_+" + "1" * 31,
        "job_" + "1" * 31,
        "job_" + "1" * 33,
        "job_" + "한" * 32,
        "xjob_" + "1" * 32,
    ),
)
def test_probe_rejects_noncanonical_job_id(value):
    with pytest.raises(ValueError):
        ordinary_slot_probe_order(value)


@pytest.mark.parametrize("slot,seconds", SHARED_WORKER_TEMPLATE_SHA256)
def test_exact_shared_unit_preserves_account_workspace_isolation_and_timeout(slot, seconds):
    path = ROOT / f"infra/systemd/eom-worker-shared-{slot}-{seconds}@.service"
    source = path.read_text()
    assert sha256(path.read_bytes()).hexdigest() == SHARED_WORKER_TEMPLATE_SHA256[(slot, seconds)]
    native = (ROOT / f"infra/systemd/eom-worker-{slot}@.service").read_text()
    restored = source.replace(
        f"Description=EOM shared ordinary worker slot {slot}, {seconds}s, job %i",
        next(line for line in native.splitlines() if line.startswith("Description=")),
    )
    restored = restored.replace(
        f"TimeoutStartSec={seconds}",
        next(line for line in native.splitlines() if line.startswith("TimeoutStartSec=")),
    )
    assert restored == native
    worker = WorkerSlot(
        slot_id=slot,
        linux_user=FIXED_WORKER_LAYOUT[slot][0],
        role=FIXED_WORKER_LAYOUT[slot][1],
        enabled=True,
        gpu=FIXED_WORKER_LAYOUT[slot][2],
    )
    assert worker_unit_name_for_execution(
        worker, "job_" + "1" * 32, timeout_seconds=seconds
    ).endswith("@job_" + "1" * 32 + ".service")


@pytest.mark.parametrize("slot", ORDINARY_SLOT_IDS)
@pytest.mark.parametrize("seconds", (900, 1800, 3600, 7200))
def test_all_twenty_timeout_combinations_reuse_existing_templates_where_possible(slot, seconds):
    physical = FIXED_WORKER_LAYOUT[slot]
    worker = WorkerSlot(
        slot_id=slot, linux_user=physical[0], role=physical[1], gpu=physical[2], enabled=True
    )
    unit = worker_unit_name_for_execution(worker, "job_" + "a" * 32, timeout_seconds=seconds)
    source = (ROOT / "infra/systemd" / (unit.split("@")[0] + "@.service")).read_text()
    assert f"TimeoutStartSec={seconds}\n" in source
    assert f"User=eom-cdx-{slot}\n" in source


def test_shared_installer_has_only_missing_native_timeout_profiles():
    source = (ROOT / "scripts/workflow/deploy_worker_runtime.sh").read_text()
    pairs = {
        (slot, int(seconds))
        for slot, seconds in re.findall(r"eom-worker-shared-(\d{2})-(\d+)@\.service", source)
    }
    assert pairs == set(SHARED_WORKER_TEMPLATE_SHA256)
    assert len(pairs) == 11


@pytest.mark.parametrize("role", ("authoring", "review", "image", "item_management", "support"))
def test_each_preset_role_model_is_editable_without_mutating_its_other_pins(role):
    document = _preset().model_dump(mode="json")
    document["role_policies"][0]["role"] = role
    document["role_policies"][0]["worker_pool_key"] = role
    base = ExecutionPresetRevision.model_validate(_self_hash(document))
    before = base.model_dump_json()
    draft = _draft(base)
    require_model_only_successor(base, draft)
    assert base.model_dump_json() == before
    assert draft.preset_id == base.preset_id
    assert draft.role_policies[0].instruction_bundle == base.role_policies[0].instruction_bundle
