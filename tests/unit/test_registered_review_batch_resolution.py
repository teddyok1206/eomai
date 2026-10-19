"""Bounded real local members/public receipts; no production DB/model/runtime."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2
from eom_catalog_service.evidence_usage_receipts import (
    EvidenceUsagePairRequest,
    EvidenceUsageReceiptResolutionError,
    OrchestratorEvidenceUsageReceiptResolver,
)
from eom_catalog_service.registered_item_review_solution_resolver import (
    RegisteredItemReviewSolutionResolutionError,
    resolve_registered_item_review_solutions,
)
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.models import ArtifactRevisionRecord

from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_registered_item_review_solution_resolver import _Artifacts, _fixture, _Session


def _batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    *,
    families: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    knowledge_root = tmp_path / "shared-knowledge"
    knowledge_root.mkdir()
    knowledge = _knowledge_fixture(
        knowledge_root,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    session = _Session()
    fixtures = []
    for index in range(1, count + 1):
        root = tmp_path / str(index)
        root.mkdir()
        fixture = _fixture(
            root,
            monkeypatch,
            family=families[index - 1] if families else 11,
            ordinal=index,
            knowledge_fixture=knowledge,
        )
        fixtures.append(fixture)
        original = fixture["session"]
        assert not set(session.records).intersection(original.records)
        session.records.update(original.records)
        session.components.extend(original.components)
        session.steps.extend(original.steps)
        session.events.extend(original.events)
    return {
        "session": session,
        "fixtures": fixtures,
        "sources": tuple(fixture["source"] for fixture in fixtures),
        "artifacts": _Artifacts(tmp_path, session),
        "receipts": OrchestratorEvidenceUsageReceiptResolver(cast(Any, lambda: session)),
        "auth": [],
    }


def _resolve(batch: dict[str, Any], **kwargs: Any) -> Any:
    return resolve_registered_item_review_solutions(
        cast(Any, batch["session"]),
        sources=batch["sources"],
        artifacts=batch["artifacts"],
        receipts=batch["receipts"],
        authorize_source=kwargs.get("authorize_source", batch["auth"].append),
    )


@pytest.mark.parametrize("count", [1, 2, 1024])
def test_full_batch_has_constant_indexed_queries_and_no_scalar_resolver_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    batch = _batch(tmp_path, monkeypatch, count)

    def no_single(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("batch attempted per-source resolver/receipt/member API")

    monkeypatch.setattr(
        "eom_catalog_service.registered_item_review_solution_resolver.resolve_registered_item_review_solution",
        no_single,
    )
    monkeypatch.setattr(batch["receipts"], "resolve_mock_exam_pair", no_single)
    monkeypatch.setattr(batch["artifacts"], "load_json_revision", no_single)
    # Reversed caller order must survive SQL ordering and map lookup.
    batch["sources"] = tuple(reversed(batch["sources"]))
    resolved = _resolve(batch)
    assert tuple(row.evidence.source for row in resolved) == batch["sources"]
    assert len(resolved) == count
    assert batch["auth"] == [*batch["sources"], *batch["sources"]]
    assert len(batch["artifacts"].reads) == 3 * count
    assert batch["session"].gets == []
    assert len(batch["session"].queries) == 17
    assert batch["session"].queries.count("ArtifactJsonJoin") == 1
    for statement in batch["session"].statements:
        assert statement.whereclause is not None
        assert " IN " in str(statement)
        assert statement.get_execution_options()["populate_existing"] is True


def test_one_batch_preserves_both_released_role_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = _batch(tmp_path, monkeypatch, 2, families=(11, 12))
    result = _resolve(batch)
    assert tuple(row.evidence.review.artifact.schema_ref for row in result) == (
        "review-result@11.0",
        "review-result@12.0",
    )
    assert tuple(row.evidence.source for row in result) == batch["sources"]
    assert len(batch["session"].queries) == 17


@pytest.mark.parametrize(
    "failure",
    ["last_approval", "missing_plan", "duplicate_event", "missing_member", "duplicate_final"],
)
def test_one_invalid_member_fails_whole_batch_without_skipping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    batch = _batch(tmp_path, monkeypatch, 2)
    last = batch["fixtures"][-1]
    session = batch["session"]
    if failure == "last_approval":
        revision = next(
            row
            for (kind, key), row in session.records.items()
            if key == last["source"].item_revision_id
        )
        revision.revision_state = "IN_REVIEW"
    elif failure == "missing_plan":
        key = next(
            key
            for key, row in session.records.items()
            if key[0] is ResolvedExecutionPlanRecord and row.workflow_id == last["workflow_id"]
        )
        del session.records[key]
    elif failure == "duplicate_event":
        session.events.append(session.events[-1])
    elif failure == "missing_member":
        revision = session.records[ArtifactRevisionRecord, last["review_pointer"].revision_id]
        (Path(revision.nas_path) / "result.json").unlink()
    else:
        session.steps.append(last["review_step"])
    with pytest.raises(RegisteredItemReviewSolutionResolutionError):
        _resolve(batch)
    assert batch["auth"] == list(batch["sources"])


def test_late_actual_permission_denial_rejects_whole_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch(tmp_path, monkeypatch, 2)
    calls = []

    def authorize(source: ApprovedItemKnowledgeSourceV2) -> None:
        calls.append(source)
        if len(calls) == 4:
            raise PermissionError("late actual operator denial")

    with pytest.raises(PermissionError, match="late actual operator denial"):
        _resolve(batch, authorize_source=authorize)
    assert calls == [*batch["sources"], *batch["sources"]]


def test_selection_bounds_duplicates_and_empty_have_no_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch(tmp_path, monkeypatch, 1)
    source = batch["sources"][0]
    for sources, code in (
        ((source,) * 1025, "BATCH_INVALID"),
        ((source, source), "DUPLICATE_SOURCE"),
    ):
        batch["sources"] = sources
        with pytest.raises(RegisteredItemReviewSolutionResolutionError, match=code):
            _resolve(batch)
    batch["sources"] = ()
    assert _resolve(batch) == ()
    assert batch["auth"] == [] and batch["session"].queries == []


def _request(fixture: dict[str, Any]) -> EvidenceUsagePairRequest:
    return EvidenceUsagePairRequest(
        fixture["workflow_id"],
        fixture["authoring_step"].step_run_id,
        fixture["authoring_pointer"],
        fixture["review_step"].step_run_id,
        fixture["review_pointer"],
        expected_authoring_receipt_sha256=fixture["authoring_receipt"].receipt_sha256,
        expected_review_receipt_sha256=fixture["review_receipt"].receipt_sha256,
    )


def test_public_receipt_batch_is_exact_and_five_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch(tmp_path, monkeypatch, 2)
    requests = tuple(_request(fixture) for fixture in reversed(batch["fixtures"]))
    result = batch["receipts"].resolve_pairs_in_session(batch["session"], requests)
    assert tuple(pair.review.receipt_sha256 for pair in result) == tuple(
        request.expected_review_receipt_sha256 for request in requests
    )
    assert len(batch["session"].queries) == 5 and batch["session"].gets == []
    batch["session"].queries.clear()
    with pytest.raises(EvidenceUsageReceiptResolutionError, match="duplicate"):
        batch["receipts"].resolve_pairs_in_session(batch["session"], (requests[0], requests[0]))
    with pytest.raises(EvidenceUsageReceiptResolutionError, match="bound"):
        batch["receipts"].resolve_pairs_in_session(batch["session"], (requests[0],) * 1025)
    assert batch["receipts"].resolve_pairs_in_session(batch["session"], ()) == ()
    assert batch["session"].queries == []


@pytest.mark.parametrize("failure", ["mixed_family", "swapped_roles", "forged_extra", "same_job"])
def test_public_receipt_batch_rejects_invalid_pair_before_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    batch = _batch(tmp_path, monkeypatch, 1)
    request = _request(batch["fixtures"][0])
    if failure == "mixed_family":
        request = replace(
            request,
            review=request.review.model_copy(update={"result_schema": "review-result@12.0"}),
        )
    elif failure == "swapped_roles":
        request = replace(request, authoring=request.review, review=request.authoring)
    elif failure == "forged_extra":
        request = replace(
            request, review=request.review.model_copy(update={"undeclared_authority": "ADMIN"})
        )
    else:
        request = replace(
            request, review=request.review.model_copy(update={"job_id": request.authoring.job_id})
        )
    with pytest.raises(EvidenceUsageReceiptResolutionError, match="pointer"):
        batch["receipts"].resolve_pairs_in_session(batch["session"], (request,))
    assert batch["session"].queries == []
