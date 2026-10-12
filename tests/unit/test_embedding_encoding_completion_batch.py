"""Pure exact-set/linear-cost proof; no binary, source authority, DB or native runtime."""

from __future__ import annotations

from collections import Counter
from typing import Any, cast

import pytest
from eom_catalog_contracts import inference_transfer_embedding as catalog
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
)
from eom_identifiers import sha256_bytes
from eom_workflow import local_embedding_encoding_job as workflow
from eom_workflow import validate_embedding_encoding_completions
from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingCompletedEvent

from tests.unit.embedding_encoding_reservation_fixtures import large_completion_fixture
from tests.unit.local_embedding_admission_fixtures import native_fixture


def test_batch_and_scalar_share_exact_semantic_leaf(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = native_fixture("a", "b")
    seen = []
    original = workflow._validate_completion_event

    def leaf(event: EmbeddingEncodingCompletedEvent, context: workflow._CompletionContext) -> None:
        seen.append(event.owned_job.job_reference.job_id)
        original(event, context)

    monkeypatch.setattr(workflow, "_validate_completion_event", leaf)
    validate_embedding_encoding_completions(
        fixture.completions, fixture.association, fixture.native_input, fixture.result
    )
    workflow.validate_embedding_encoding_completion(
        fixture.completions[0], fixture.association, fixture.native_input, fixture.result
    )
    assert seen == [event.owned_job.job_reference.job_id for event in fixture.completions] + [
        fixture.completions[0].owned_job.job_reference.job_id
    ]


@pytest.mark.parametrize("count", [1, 16, 1024])
def test_batch_actual_full_parses_and_raw_hashes_constant_not_per_row(
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = large_completion_fixture(count)
    calls: Counter[str] = Counter()
    original_input = catalog.parse_incremental_embedding_input
    original_result = catalog.parse_incremental_embedding_result
    original_sha = sha256_bytes
    original_leaf = workflow._validate_completion_event

    def parse_input(value: dict[str, Any]) -> IncrementalEmbeddingInput:
        calls["full_input_parse"] += 1
        return original_input(value)

    def parse_result(value: dict[str, Any]) -> IncrementalEmbeddingResult:
        calls["full_result_parse"] += 1
        return original_result(value)

    def raw_sha(value: bytes) -> str:
        calls["raw_member_hash"] += 1
        return original_sha(value)

    def leaf(event: EmbeddingEncodingCompletedEvent, context: workflow._CompletionContext) -> None:
        calls["event_leaf"] += 1
        original_leaf(event, context)

    monkeypatch.setattr(workflow, "parse_incremental_embedding_input", parse_input)
    monkeypatch.setattr(catalog, "parse_incremental_embedding_input", parse_input)
    monkeypatch.setattr(workflow, "parse_incremental_embedding_result", parse_result)
    monkeypatch.setattr(catalog, "parse_incremental_embedding_result", parse_result)
    monkeypatch.setattr(workflow, "sha256_bytes", raw_sha)
    monkeypatch.setattr(workflow, "_validate_completion_event", leaf)
    validate_embedding_encoding_completions(
        fixture.completions, fixture.association, fixture.native_input, fixture.result
    )
    assert calls == {
        "full_input_parse": 2,
        "full_result_parse": 2,
        "raw_member_hash": 3,
        "event_leaf": count,
    }


@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "reversed", "foreign", "oversized", "list"]
)
def test_batch_requires_exact_whole_sorted_unique_owned_set(failure: str) -> None:
    fixture = native_fixture("a", "b")
    events = fixture.completions
    if failure == "missing":
        events = events[:1]
    elif failure == "duplicate":
        events = (events[0], events[0])
    elif failure == "reversed":
        events = tuple(reversed(events))
    elif failure == "foreign":
        events = (native_fixture("c").completions[0], events[1])
    elif failure == "oversized":
        events = (events[0],) * 1025
    else:
        with pytest.raises(ValueError):
            validate_embedding_encoding_completions(
                cast(tuple[EmbeddingEncodingCompletedEvent, ...], list(events)),
                fixture.association,
                fixture.native_input,
                fixture.result,
            )
        return
    with pytest.raises(ValueError):
        validate_embedding_encoding_completions(
            events, fixture.association, fixture.native_input, fixture.result
        )


@pytest.mark.parametrize(
    "failure", ["copied_event", "constructed_event", "copied_row", "copied_output", "stale_pointer"]
)
def test_scalar_and_batch_both_reject_invalid_frozen_copy_or_construct(failure: str) -> None:
    fixture = native_fixture("a", "b")
    event, native_input, result = fixture.completions[0], fixture.native_input, fixture.result
    if failure == "copied_event":
        event = event.model_copy(update={"event_sha256": "sha256:" + "0" * 64})
    elif failure == "constructed_event":
        event = EmbeddingEncodingCompletedEvent.model_construct(
            **(event.__dict__ | {"event_sha256": "sha256:" + "0" * 64})
        )
    elif failure == "copied_row":
        row = native_input.rows[0].model_copy(update={"text": "forged"})
        native_input = native_input.model_copy(update={"rows": (row, *native_input.rows[1:])})
    elif failure == "copied_output":
        result = result.model_copy(update={"result_sha256": "sha256:" + "0" * 64})
    else:
        pointer = event.receipt.result_manifest.model_copy(update={"sha256": "sha256:" + "0" * 64})
        event = event.model_copy(
            update={"receipt": event.receipt.model_copy(update={"result_manifest": pointer})}
        )
    events = (event, *fixture.completions[1:])
    with pytest.raises(ValueError):
        workflow.validate_embedding_encoding_completion(
            event, fixture.association, native_input, result
        )
    with pytest.raises(ValueError):
        validate_embedding_encoding_completions(events, fixture.association, native_input, result)
