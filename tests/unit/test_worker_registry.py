from pathlib import Path

import pytest
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.worker_registry import (
    FIXED_WORKER_LAYOUT,
    FIXED_WORKER_SLOT_IDS,
    FIXED_WORKER_SLOT_ROLES,
    WorkerRegistry,
)
from eom_workflow.control_schemas import load_control_schema


def test_example_registry_selects_authoring_slot() -> None:
    registry = WorkerRegistry.load(Path("config/worker-slots.example.yaml").resolve())
    slot = registry.select("authoring")
    assert slot.slot_id == "01"
    assert slot.linux_user == "eom-cdx-01"
    assert registry.global_codex_concurrency == 3


def test_registry_rejects_missing_role() -> None:
    registry = WorkerRegistry.load(Path("config/worker-slots.example.yaml").resolve())
    with pytest.raises(PlatformError, match="no enabled worker"):
        registry.select("missing")


def test_shared_fixed_layout_matches_released_inventory_and_v3_role_schema() -> None:
    registry = WorkerRegistry.load(Path("config/worker-slots.example.yaml").resolve())
    assert {
        slot.slot_id: (slot.linux_user, slot.role, slot.gpu) for slot in registry.config.slots
    } == FIXED_WORKER_LAYOUT
    assert tuple(FIXED_WORKER_LAYOUT) == FIXED_WORKER_SLOT_IDS
    inventory = load_control_schema("worker-slot-inventory-v2")
    role_branches = load_control_schema("codex-reviewed-capability-policy-v3")["properties"][
        "models"
    ]["items"]["properties"]["bindings"]["anyOf"][1]["items"]["oneOf"]
    for slot_id, (user, role, gpu) in FIXED_WORKER_LAYOUT.items():
        properties = inventory["$defs"]["slot" + slot_id]["properties"]
        assert properties["linux_user"]["const"] == user
        assert properties["role"]["const"] == FIXED_WORKER_SLOT_ROLES[slot_id] == role
        assert properties["gpu"]["const"] is gpu
        matching = [
            branch["properties"]
            for branch in role_branches
            if slot_id
            in branch["properties"]["slot_id"].get(
                "enum", [branch["properties"]["slot_id"].get("const")]
            )
        ]
        assert len(matching) == 1 and matching[0]["role"]["const"] == role


def test_shared_fixed_layout_metadata_is_immutable() -> None:
    with pytest.raises(TypeError):
        FIXED_WORKER_LAYOUT["01"] = ("invented", "support", False)  # type: ignore[index]
    with pytest.raises(TypeError):
        FIXED_WORKER_SLOT_ROLES["01"] = "support"  # type: ignore[index]
