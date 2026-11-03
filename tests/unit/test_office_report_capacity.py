"""Four reports are a closed new purpose; old role defaults and policies stay intact."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import content_sha256
from eom_workflow import WorkerCapacityPolicyV5, WorkerCapacityPolicyV6, validate_control_contract

from tests.unit.test_creative_report_capacity import capacity_value as three_capacity


def capacity_value():
    value = three_capacity()
    value.update(
        schema_version="worker-capacity-policy/1.5",
        purpose="OFFICE_CREATIVE_REPORT_BACKFILL",
        max_active_codex=4,
        max_active_knowledge_analysis=4,
    )
    value["pools"][0].update(slot_keys=["slot03", "slot04", "slot05", "slot06"], max_active=4)
    value["delegated_slot_roles"].insert(
        0,
        {
            "pool_key": "support",
            "slot_key": "slot03",
            "native_role": "image",
            "execution_role": "support",
        },
    )
    value["content_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "content_sha256"}
    )
    return value


def test_four_capacity_is_schema_first_and_does_not_reinterpret_three():
    value = capacity_value()
    validate_control_contract("worker-capacity-policy-v6", value)
    parsed = WorkerCapacityPolicyV6.model_validate(value)
    assert parsed.max_active_codex == parsed.max_active_knowledge_analysis == 4
    assert (
        parsed.execution_role_for_slot(pool_key="support", slot_key="slot03", native_role="image")
        == "support"
    )
    assert (
        parsed.execution_role_for_slot(
            pool_key="support", slot_key="slot04", native_role="item_management"
        )
        == "support"
    )
    assert (
        parsed.execution_role_for_slot(pool_key="other", slot_key="slot03", native_role="image")
        == "image"
    )
    with pytest.raises(ValueError):
        WorkerCapacityPolicyV5.model_validate(value)
    assert WorkerCapacityPolicyV5.model_validate(three_capacity()).max_active_codex == 3
    root = Path(__file__).resolve().parents[2]
    name = "control-plane/worker-capacity-policy-v6.schema.json"
    assert (root / "schemas/workflow" / name).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources" / name
    ).read_bytes()


@pytest.mark.parametrize("change", ["worker-count", "slot", "role", "gpu", "order"])
def test_four_purpose_cannot_be_broadened_or_rewrite_native_roles(change):
    value = deepcopy(capacity_value())
    if change == "worker-count":
        value["max_active_codex"] = 5
    elif change == "slot":
        value["pools"][0]["slot_keys"][0] = "slot01"
    elif change == "role":
        value["delegated_slot_roles"][0]["native_role"] = "authoring"
    elif change == "gpu":
        value["max_active_gpu"] = 2
    else:
        value["delegated_slot_roles"].reverse()
    with pytest.raises(ValueError):
        WorkerCapacityPolicyV6.model_validate(value)
