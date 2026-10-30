"""Clones retain exact instructions and model policy; no inference is performed."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.creative_parallel_controls import (
    creative_report_capacity_document,
    parallel_role_policies,
)
from eom_workflow.control_plane import ExecutionPresetRevision, WorkerCapacityPolicyV5

from tests.unit.test_external_item_learning_execution_resolver import _published_preset


def baseline():
    _, row = _published_preset(successor=True)
    return ExecutionPresetRevision.model_validate(row.canonical_document)


def test_parallel_clone_changes_pool_only_and_capacity_never_expands_past_three():
    old = baseline()
    before = old.model_dump(mode="json")
    policies = parallel_role_policies(old)
    expected = deepcopy(before["role_policies"])
    expected[0]["worker_pool_key"] = "support"
    assert policies == expected
    assert old.model_dump(mode="json") == before
    capacity = WorkerCapacityPolicyV5.model_validate(
        creative_report_capacity_document(created_at=datetime.now(UTC))
    )
    assert capacity.max_active_codex == capacity.max_active_knowledge_analysis == 3
    assert capacity.pools[0].slot_keys == ("slot04", "slot05", "slot06")


@pytest.mark.parametrize(
    "change", ["pool", "role", "timeout", "network", "sandbox", "state", "extra"]
)
def test_unrelated_baseline_cannot_borrow_the_creative_purpose(change):
    document = baseline().model_dump(mode="json")
    role = document["role_policies"][0]
    if change == "pool":
        role["worker_pool_key"] = "authoring"
    elif change == "role":
        role["role"] = "review"
    elif change == "timeout":
        role["timeout_seconds"] = 1800
    elif change == "network":
        # The closed preset model itself can reject an unsupported network.
        role["network"] = "enabled"
    elif change == "sandbox":
        role["sandbox"] = "workspace-write"
    elif change == "state":
        document["state"] = "DRAFT"
    else:
        document["role_policies"].append({**role, "role": "review"})
    document["content_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "content_sha256"}
    )
    with pytest.raises((ControlPlaneError, ValueError)):
        parallel_role_policies(ExecutionPresetRevision.model_validate(document))
