"""Synthetic routing/replay on the guarded chat disposable database only."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from eom_orchestrator.chat_support_routing import (
    SupportRoutingPredecessors,
    release_slot05_support_routing,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    compute_control_document_hash,
    publish_capacity_policy_revision,
    publish_execution_preset_revision,
    record_capacity_policy_revision,
    record_execution_preset_revision,
)
from eom_workflow.control_plane import WorkerRole
from sqlalchemy import func, select

from tests.integration.test_control_plane_persistence import _complete_control_plane
from tests.unit.test_chat_support_routing import capacity_source, legacy_capacity_source

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_support_routing_publishes_once_preserving_source_and_invocations(chat):
    sessions = chat.repository.sessions
    with sessions.begin() as session:
        plan_id, _, _ = _complete_control_plane(
            session, roles=(WorkerRole.SUPPORT,), slot_id_by_role={WorkerRole.SUPPORT: "06"}
        )
        plan = session.get(ResolvedExecutionPlanRecord, plan_id)
        source = session.get(ExecutionPresetRevisionRecord, plan.preset_revision_id)
        assert source is not None
        capacity = capacity_source().model_dump(mode="json")
        capacity["capacity_policy_id"] = "capacity_" + uuid4().hex
        capacity["capacity_policy_revision_id"] = "capacityrev_" + uuid4().hex
        capacity["content_sha256"] = compute_control_document_hash(capacity, "content_sha256")
        capacity_key = "chat-routing-fixture-" + uuid4().hex
        record_capacity_policy_revision(
            session,
            policy_key=capacity_key,
            document=capacity,
            created_by="disposable-test",
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=capacity["capacity_policy_id"],
            capacity_policy_revision_id=capacity["capacity_policy_revision_id"],
        )
        legacy_capacity = legacy_capacity_source().model_dump(mode="json")
        legacy_capacity["capacity_policy_id"] = capacity["capacity_policy_id"]
        legacy_capacity["capacity_policy_revision_id"] = "capacityrev_" + uuid4().hex
        legacy_capacity["content_sha256"] = compute_control_document_hash(
            legacy_capacity, "content_sha256"
        )
        record_capacity_policy_revision(
            session,
            policy_key=capacity_key,
            document=legacy_capacity,
            created_by="disposable-test",
        )
        sources = []
        for key, timeout in (
            ("customer-support", 900),
            ("pdf-document-review", 3600),
            ("item-inference-transfer-comparison-axes", 900),
            ("legacy-item-extraction", 7200),
        ):
            document = dict(source.canonical_document)
            document["role_policies"] = [dict(document["role_policies"][0])]
            document["role_policies"][0]["worker_pool_key"] = (
                "legacy-extraction" if key == "legacy-item-extraction" else "customer-support"
            )
            document["role_policies"][0]["timeout_seconds"] = timeout
            document["preset_id"] = "execpreset_" + uuid4().hex
            document["preset_revision_id"] = "execpresetrev_" + uuid4().hex
            document["capacity_policy_revision_id"] = (
                legacy_capacity["capacity_policy_revision_id"]
                if key == "legacy-item-extraction"
                else capacity["capacity_policy_revision_id"]
            )
            document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
            row = record_execution_preset_revision(
                session, preset_key=key, document=document, created_by="disposable-test"
            )
            publish_execution_preset_revision(
                session, preset_id=row.preset_id, preset_revision_id=row.preset_revision_id
            )
            sources.append((row.preset_revision_id, row.content_sha256, row.canonical_document))

    expected = SupportRoutingPredecessors(
        capacity["capacity_policy_revision_id"],
        *(source[0] for source in sources),
        legacy_capacity["capacity_policy_revision_id"],
    )
    publisher = ControlArtifactPublisher(chat.engine, chat.evidence.publisher.settings)

    def run():
        return release_slot05_support_routing(
            sessions,
            publisher,
            predecessors=expected,
            actor_id="disposable-routing-test",
            source_commit="a" * 40,
        )

    # Both callers use identical predecessors and may race before/after publication.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: run(), range(2)))
    assert results[0] == results[1] == run()
    with sessions() as session:
        for (revision_id, digest, document), new_id in zip(
            sources,
            (
                results[0].customer_support_revision_id,
                results[0].document_review_revision_id,
                results[0].inference_transfer_revision_id,
                results[0].legacy_extraction_revision_id,
            ),
            strict=True,
        ):
            old = session.get(ExecutionPresetRevisionRecord, revision_id)
            new = session.get(ExecutionPresetRevisionRecord, new_id)
            assert old.content_sha256 == digest and old.canonical_document == document
            assert new.canonical_document["role_policies"] == document["role_policies"]
            assert (
                new.canonical_document["compatible_workflow_protocols"]
                == document["compatible_workflow_protocols"]
            )
            assert session.get(ExecutionPresetRecord, new.preset_id).current_revision_id == new_id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ExecutionPresetRevisionRecord)
                    .where(ExecutionPresetRevisionRecord.preset_id == new.preset_id)
                )
                == 3
            )
        routed = session.get(WorkerCapacityPolicyRevisionRecord, results[0].capacity_revision_id)
        assert routed.canonical_document["pools"][0]["slot_keys"] == ["slot05"]
        assert routed.canonical_document["pools"][1]["slot_keys"] == ["slot05"]
        from eom_catalog_service.legacy_item_extraction_service import (
            LegacyItemExtractionApplicationService,
        )

        service = LegacyItemExtractionApplicationService(chat.engine)
        assert service._require_dedicated_slot(session, results[0].capacity_revision_id) == "05"
        assert (
            service._require_dedicated_slot(session, legacy_capacity["capacity_policy_revision_id"])
            == "06"
        )
