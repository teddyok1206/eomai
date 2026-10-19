"""Source-only real ORM fixture: fixed proof read locks, no DB/runtime calls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.evidence_usage_receipts import (
    EvidenceUsagePairRequest,
    EvidenceUsageReceiptPair,
    EvidenceUsageReceiptResolutionError,
    OrchestratorEvidenceUsageReceiptResolver,
)
from eom_catalog_service.registered_item_review_solution_resolver import (
    RegisteredItemReviewSolutionResolutionError,
    lock_registered_item_review_sources,
)
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy.dialects import postgresql

from tests.unit.similarity_plan_fixtures import ordinary_similarity_case, similarity_case
from tests.unit.test_registered_review_batch_resolution import _batch, _resolve


@pytest.mark.parametrize("count", [1, 2])
def test_fixed_bounded_proof_locks_then_existing_public_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    batch = _batch(tmp_path, monkeypatch, count)
    session = batch["session"]
    session.get_nested_transaction = lambda: None
    held = lock_registered_item_review_sources(cast(Any, session), sources=batch["sources"])
    held.assert_current(cast(Any, session))
    assert len(held.item_revisions) == count
    assert len(held.workflows) == count and len(held.steps) == 3 * count
    assert len(held.receipt_events) == 2 * count
    assert len(session.statements) == 8
    for statement in session.statements:
        assert "FOR SHARE" in str(statement.compile(dialect=postgresql.dialect()))
        assert statement.get_execution_options()["populate_existing"] is True
    before = len(session.statements)
    resolved = _resolve(batch)
    assert tuple(row.evidence.source for row in resolved) == batch["sources"]
    # Read-only resolver itself is unchanged; locks are an explicit caller choice.
    for statement in session.statements[before:]:
        assert "FOR SHARE" not in str(statement.compile(dialect=postgresql.dialect()))
    held.assert_current(cast(Any, session))


@pytest.mark.parametrize("change", ["root", "closed", "thread", "nested", "session"])
def test_retained_rows_never_cross_root_thread_or_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    batch = _batch(tmp_path, monkeypatch, 1)
    session = batch["session"]
    session.get_nested_transaction = lambda: None
    held = lock_registered_item_review_sources(cast(Any, session), sources=batch["sources"])
    if change == "root":
        session.root = object()
    elif change == "closed":
        session.root.is_active = False
    elif change == "nested":
        session.get_nested_transaction = lambda: object()
    elif change == "thread":
        monkeypatch.setattr(
            "eom_catalog_service.registered_item_review_solution_resolver.threading.get_ident",
            lambda: -1,
        )
    with pytest.raises(RegisteredItemReviewSolutionResolutionError, match="LOCK_ROOT_CHANGED"):
        held.assert_current(cast(Any, object() if change == "session" else session))


@pytest.mark.parametrize("change", ["rollback", "release", "replace"])
def test_exact_active_savepoint_is_supported_but_never_reused_after_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    batch = _batch(tmp_path, monkeypatch, 1)
    session = batch["session"]
    nested = SimpleNamespace(is_active=True)
    session.get_nested_transaction = lambda: nested
    held = lock_registered_item_review_sources(cast(Any, session), sources=batch["sources"])
    held.assert_current(cast(Any, session))
    if change == "rollback":
        nested.is_active = False
    elif change == "release":
        session.get_nested_transaction = lambda: None
    else:
        session.get_nested_transaction = lambda: SimpleNamespace(is_active=True)
    with pytest.raises(RegisteredItemReviewSolutionResolutionError, match="LOCK_ROOT_CHANGED"):
        held.assert_current(cast(Any, session))


@pytest.mark.parametrize("change", ["missing_artifact", "component_budget", "pending", "duplicate"])
def test_publication_lock_selection_and_dangling_proof_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    batch = _batch(tmp_path, monkeypatch, 1)
    session = batch["session"]
    session.get_nested_transaction = lambda: None
    if change == "missing_artifact":
        key = next(key for key in session.records if key[0] is ArtifactRevisionRecord)
        del session.records[key]
    elif change == "component_budget":
        session.components *= 101
    elif change == "pending":
        session.dirty.add(object())
    else:
        batch["sources"] *= 2
    with pytest.raises(RegisteredItemReviewSolutionResolutionError):
        lock_registered_item_review_sources(cast(Any, session), sources=batch["sources"])


@pytest.mark.parametrize("ordinary", [False, True])
def test_post_registration_plan23_and24_reuse_exact_receipt_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ordinary: bool,
) -> None:
    case = (ordinary_similarity_case if ordinary else similarity_case)(tmp_path, monkeypatch)
    plan = case["plan"]
    record = SimpleNamespace(
        **{
            name: getattr(plan, name)
            for name in (
                "plan_id",
                "workflow_id",
                "preset_id",
                "preset_revision_id",
                "capacity_policy_revision_id",
                "evidence_bundle_revision_id",
                "plan_sha256",
                "resolved_at",
            )
        },
        graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        canonical_document=plan.model_dump(mode="json"),
    )
    receipt = SimpleNamespace(
        **{
            name: getattr(plan, name)
            for name in (
                "plan_id",
                "plan_sha256",
                "evidence_bundle_id",
                "evidence_bundle_revision_id",
                "retrieval_request_id",
                "retrieval_request_sha256",
                "evidence_manifest_artifact",
                "evidence_manifest_sha256",
                "evidence_context_artifact",
            )
        },
        graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        graph_snapshot_sha256=plan.graph_snapshot.manifest_sha256,
    )
    owner = object.__new__(OrchestratorEvidenceUsageReceiptResolver)
    request = cast(
        EvidenceUsagePairRequest,
        SimpleNamespace(workflow_id=plan.workflow_id, expected_provenance=None),
    )
    pair = EvidenceUsageReceiptPair(cast(Any, receipt), cast(Any, receipt))
    owner._validate_plan_record(request, pair, cast(Any, record))
    receipt.plan_sha256 = "sha256:" + "0" * 64
    with pytest.raises(EvidenceUsageReceiptResolutionError, match="immutable knowledge plan"):
        owner._validate_plan_record(request, pair, cast(Any, record))
