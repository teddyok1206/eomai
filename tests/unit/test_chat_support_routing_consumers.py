"""Routing successors use existing plan owners; no worker or live database."""

from types import SimpleNamespace

import pytest
from eom_orchestrator.chat_support_routing import slot05_capacity_document
from eom_orchestrator.control_models import (
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import compute_control_document_hash
from eom_orchestrator.execution_resolver import (
    resolve_customer_support_plan,
    resolve_pdf_document_review_plan,
)
from eom_orchestrator.preset_model_selection import resolve_released_capacity_policy
from eom_workflow import ExecutionPresetRevision, build_pdf_document_review_request

from tests.unit.test_chat_support_routing import capacity_source, legacy_capacity_source
from tests.unit.test_customer_support_protocol import _case
from tests.unit.test_inference_transfer_resolution import fixture, rehash, resolve
from tests.unit.test_pdf_document_review_execution import (
    NOW,
    FakeSession,
    _document,
    _preset_document,
)


def _capacity():
    return slot05_capacity_document(capacity_source(), legacy_capacity_source())


def test_routed_capacity_passes_the_official_released_capacity_resolver():
    body = _capacity()
    row = SimpleNamespace(**body, canonical_document=body)

    class Session:
        def get(self, kind, identity):
            assert kind is WorkerCapacityPolicyRevisionRecord
            assert identity == body["capacity_policy_revision_id"]
            return row

    actual = resolve_released_capacity_policy(Session(), body["capacity_policy_revision_id"])
    assert {pool.pool_key: pool.slot_keys for pool in actual.pools} == {
        "customer-support": ("slot05",),
        "legacy-extraction": ("slot05",),
    }


@pytest.mark.parametrize("key", ["customer-support", "pdf-document-review"])
def test_support_and_pdf_new_plans_pin_successor_capacity_without_schema_v4_requirement(key):
    body = _preset_document()
    body["capacity_policy_revision_id"] = _capacity()["capacity_policy_revision_id"]
    body["revision_number"] = 16
    if key == "customer-support":
        body["compatible_workflow_protocols"] = ["workflow-role/1.22.0"]
        body["role_policies"][0]["timeout_seconds"] = 900
        body["role_policies"][0]["model_candidates"][0]["reasoning_effort"] = "medium"
    body["content_sha256"] = compute_control_document_hash(body, "content_sha256")
    session = FakeSession(preset_document=body)
    session.preset_logical.preset_key = key
    kwargs = {
        "workflow_id": "workflow_" + "1" * 32,
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": "sha256:" + "2" * 64,
        "workflow_role_schema_version": body["compatible_workflow_protocols"][0],
        "resolved_at": NOW,
    }
    if key == "customer-support":
        resolver = resolve_customer_support_plan
        kwargs["support_case"] = _case()
    else:
        resolver = resolve_pdf_document_review_plan
        kwargs["review_request"] = build_pdf_document_review_request(
            document=_document(), preset_key="MOCK_EXAM", additional_guidance=None
        )
    first = resolver(session, **kwargs)
    assert resolver(session, **kwargs) == first
    assert first.capacity_policy_revision_id == body["capacity_policy_revision_id"]
    assert first.steps[0].worker_pool_key == "customer-support"
    assert len(session.steps) == 1


def test_comparison_new_plan_accepts_capacity_successor_beyond_initial_revision_two(monkeypatch):
    value = fixture(monkeypatch)
    old = value.preset.model_dump(mode="json")
    body = dict(old)
    body.update(
        preset_revision_id="execpresetrev_" + "f" * 32,
        revision_number=4,
        capacity_policy_revision_id=_capacity()["capacity_policy_revision_id"],
    )
    rehash(body)
    successor = ExecutionPresetRevision.model_validate(body)
    value.session.records[(ExecutionPresetRevisionRecord, successor.preset_revision_id)] = (
        SimpleNamespace(**successor.model_dump(), canonical_document=body)
    )
    value.logical.current_revision_id = successor.preset_revision_id
    value.role_row.preset_revision_id = successor.preset_revision_id
    first = resolve(value)
    assert first.preset_revision_id == successor.preset_revision_id
    assert first.capacity_policy_revision_id == successor.capacity_policy_revision_id
    assert resolve(value) == first
    assert value.preset.model_dump(mode="json") == old
