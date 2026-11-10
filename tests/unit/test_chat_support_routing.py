"""No model/GPU/operational writes: exact support relocation contract."""

from __future__ import annotations

import pytest
from eom_orchestrator.chat_support_routing import slot05_capacity_document
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_workflow import WorkerCapacityPolicy, WorkerCapacityPolicyV3, WorkerCapacityPolicyV4
from eom_workflow.control_schemas import validate_control_contract


def capacity_source():
    pools = [
        {"pool_key": key, "roles": [role], "slot_keys": [f"slot{index:02d}"], "max_active": 1}
        for index, (key, role) in enumerate(
            (
                ("authoring", "authoring"),
                ("review", "review"),
                ("image", "image"),
                ("item-management", "item_management"),
                ("support", "support"),
                ("customer-support", "support"),
            ),
            start=1,
        )
    ]
    document = {
        "schema_version": "worker-capacity-policy/1.3",
        "capacity_policy_id": "capacity_" + "a" * 32,
        "capacity_policy_revision_id": "capacityrev_" + "b" * 32,
        "revision_number": 4,
        "state": "RELEASED",
        "max_configured_slots": 6,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 2,
        "pools": pools,
        "created_at": "2026-11-10T00:00:00Z",
        "content_sha256": "sha256:" + "0" * 64,
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    return WorkerCapacityPolicyV4.model_validate(document)


def legacy_capacity_source():
    document = capacity_source().model_dump(mode="json")
    document.update(
        schema_version="worker-capacity-policy/1.2",
        capacity_policy_revision_id="capacityrev_" + "c" * 32,
        revision_number=3,
    )
    document["pools"][-1]["pool_key"] = "legacy-extraction"
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    return WorkerCapacityPolicyV3.model_validate(document)


def test_only_new_support_policy_routes_to_05_and_preserves_source():
    source = capacity_source()
    legacy = legacy_capacity_source()
    before = source.model_dump_json()
    legacy_before = legacy.model_dump_json()
    document = slot05_capacity_document(source, legacy)
    validate_control_contract("worker-capacity-policy", document)
    actual = WorkerCapacityPolicy.model_validate(document)
    assert actual.pools[0].slot_keys == ("slot05",)
    assert actual.pools[0].pool_key == "customer-support"
    assert actual.pools[0].roles == ("support",)
    assert actual.pools[0].max_active == 1
    assert actual.pools[1].pool_key == "legacy-extraction"
    assert actual.pools[1].slot_keys == ("slot05",)
    assert actual.pools[1].max_active == 1
    assert actual.max_active_codex == source.max_active_codex
    assert actual.capacity_policy_id != source.capacity_policy_id
    assert actual.content_sha256 == compute_control_document_hash(document, "content_sha256")
    assert slot05_capacity_document(source, legacy) == document
    assert source.model_dump_json() == before
    assert legacy.model_dump_json() == legacy_before


def test_unreleased_source_is_not_a_relocation_authority():
    source = capacity_source().model_copy(update={"state": "DRAFT"})
    with pytest.raises(ControlPlaneError, match="routing differs"):
        slot05_capacity_document(source, legacy_capacity_source())


def test_unrelated_legacy_capacity_is_not_a_relocation_authority():
    legacy = legacy_capacity_source().model_copy(
        update={"capacity_policy_id": "capacity_" + "e" * 32}
    )
    with pytest.raises(ControlPlaneError, match="extraction routing differs"):
        slot05_capacity_document(capacity_source(), legacy)
