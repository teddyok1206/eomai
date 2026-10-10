"""Fake-port source evidence only: no live principal, publisher, DB or model calls."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta, timezone
from typing import Any, cast

import pytest
from eom_catalog_contracts.inference_transfer_human_review import (
    HUMAN_REVIEW_BUNDLE_SCHEMA_REF,
    HUMAN_REVIEW_RECORD_SCHEMA_REF,
    MAX_HUMAN_REVIEW_BYTES,
    InferenceTransferHumanReviewBundle,
    parse_human_bundle,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.models import FrozenModel
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_artifacts import ControlArtifactPublisher, PublishedControlArtifact
from eom_orchestrator.control_service import ControlPlaneError
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine

from tests.unit.inference_transfer_human_review_fixtures import (
    ACTOR,
    NOW,
    REQUIRED_PERMISSIONS,
    SOURCE_COMMIT,
    Harness,
    member,
    principal,
)
from tests.unit.inference_transfer_snapshot_fixtures import (
    snapshot_header,
    snapshot_prepare_result,
)


def rehashed[T: FrozenModel](value: T, field: str, **changes: Any) -> T:
    body = value.model_dump(mode="json", exclude={field}) | changes
    return type(value).model_validate(body | {field: content_sha256(body)})


def assert_error(code: str, action: Any) -> None:
    with pytest.raises(ControlPlaneError) as caught:
        action()
    assert caught.value.code == "INFERENCE_TRANSFER_HUMAN_" + code


def publish(harness: Harness) -> PublishedControlArtifact:
    return harness.owner.publish_bundle(harness.command, source_commit=SOURCE_COMMIT)


def stored_bundle(
    harness: Harness, published: PublishedControlArtifact
) -> InferenceTransferHumanReviewBundle:
    return parse_human_bundle(
        json.loads(
            harness.artifacts.payloads[
                (published.pointer.artifact_id, published.pointer.artifact_revision_id)
            ]
        )
    )


def test_bundle_materializes_exact_pair_without_creating_a_human_label() -> None:
    h = Harness()
    published = publish(h)
    bundle = h.owner.read_bundle(member(published))
    assert bundle.sources == h.snapshots.records[:2]
    assert bundle.command == h.command
    assert bundle.comparison == h.comparisons.value
    assert bundle.prepared_by == ACTOR
    assert bundle.comparison.result is not None
    assert bundle.comparison.result.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
    assert "evaluation" not in bundle.model_dump(mode="json")
    assert published.pointer.schema_ref == HUMAN_REVIEW_BUNDLE_SCHEMA_REF
    assert all(query.mode == "CANONICAL_RESULT" for query, _ in h.comparisons.calls)
    assert all(actor == ACTOR for actor, _ in h.snapshots.calls)
    assert h.artifacts.calls[-1][1] == MAX_HUMAN_REVIEW_BYTES


@pytest.mark.parametrize("width,reads", [(1, 2), (2, 1)])
@pytest.mark.parametrize("reverse", [False, True])
def test_read_chunks_are_sorted_but_materialized_sources_preserve_a_to_b(
    width: int, reads: int, reverse: bool
) -> None:
    h = Harness(width=width, reverse=reverse)
    published = publish(h)
    bundle = stored_bundle(h, published)
    source_reads = [
        query
        for _, query in h.snapshots.calls
        if isinstance(query, InferenceTransferSnapshotReadRequest)
    ]
    assert len(source_reads) == reads
    assert all(len(query.selected_index_entries) <= width for query in source_reads)
    runs = tuple(
        row.base_analysis_run_id for query in source_reads for row in query.selected_index_entries
    )
    assert runs == tuple(sorted(runs))
    expected = h.snapshots.records[:2]
    assert bundle.sources == (tuple(reversed(expected)) if reverse else expected)


def test_manifest_utc_is_owner_time_while_payload_metadata_remains_fixed() -> None:
    h = Harness()
    published = publish(h)
    submitted = h.publisher.calls[0]
    assert submitted["created_at"] == NOW
    assert h.command.created_at == NOW - timedelta(hours=1)
    assert stored_bundle(h, published).command.created_at == h.command.created_at
    assert submitted["artifact_type"] == "control_inference_transfer_human_review"
    assert submitted["logical_name"] == "result.json"
    assert submitted["media_type"] == "application/json"
    assert published.pointer.sha256 == sha256_bytes(submitted["payload"])
    # This pure input check is the real pre-existing Publisher contract, not an
    # unconstrained fake's interpretation of what production might accept.
    ControlArtifactPublisher._validate_input(**submitted)


BAD_PRINCIPALS = [
    {"username": "otheruser"},
    {"roles": ("REVIEWER",)},
    {"password_change_required": True},
    {"authenticated_at": NOW - timedelta(minutes=15, seconds=1)},
    {"authenticated_at": NOW + timedelta(seconds=1)},
    {"access_expires_at": NOW},
    {"operator_id": "operator-invalid"},
    {"session_id": "session-invalid"},
] + [
    {"effective_permissions": tuple(key for key in REQUIRED_PERMISSIONS if key != missing)}
    for missing in REQUIRED_PERMISSIONS
]


@pytest.mark.parametrize("changes", BAD_PRINCIPALS)
def test_invalid_actual_principal_never_reaches_publication(changes: dict[str, Any]) -> None:
    h = Harness()
    h.principal.value = principal(**changes)
    assert_error("AUTHORIZATION_REQUIRED", lambda: publish(h))
    assert h.publisher.calls == []


@pytest.mark.parametrize(
    "changes", [{"operator_id": "operator_" + "9" * 32}, {"session_id": "apisession_" + "9" * 32}]
)
def test_an_owner_session_is_sticky_after_its_first_actual_authorization(
    changes: dict[str, Any],
) -> None:
    h = Harness()
    published = publish(h)
    h.principal.value = principal(**changes)
    assert_error("AUTHORIZATION_REQUIRED", lambda: h.owner.read_bundle(member(published)))
    assert h.artifacts.calls == []


@pytest.mark.parametrize(
    "clock", [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=9)))]
)
def test_owner_clock_requires_utc(clock: Any) -> None:
    h = Harness()
    h.clock = clock
    assert_error("CLOCK_INVALID", lambda: publish(h))
    assert h.publisher.calls == []


def test_freshness_boundary_is_inclusive_and_not_an_input_age_limit() -> None:
    h = Harness()
    h.principal.value = principal(authenticated_at=NOW - timedelta(minutes=15))
    assert publish(h).pointer.schema_ref == HUMAN_REVIEW_BUNDLE_SCHEMA_REF
    assert h.command.created_at < NOW - timedelta(minutes=15)


def test_future_bundle_timestamp_is_not_accepted_as_owner_clock() -> None:
    h = Harness()
    h.command = rehashed(
        h.command,
        "command_sha256",
        created_at=(NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    )
    assert_error("INPUT_INVALID", lambda: publish(h))
    assert h.publisher.calls == []


def test_model_copy_does_not_bypass_command_validation() -> None:
    h = Harness()
    h.command = h.command.model_copy(update={"command_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        publish(h)
    assert h.snapshots.calls == []
    assert h.comparisons.calls == []
    assert h.publisher.calls == []


def test_model_copy_does_not_bypass_actual_principal_validation() -> None:
    h = Harness()
    h.principal.value = h.principal.value.model_copy(update={"authenticated_at": "not-a-time"})
    with pytest.warns(UserWarning, match="Pydantic serializer"):
        assert_error("AUTHORIZATION_REQUIRED", lambda: publish(h))
    assert h.publisher.calls == []


@pytest.mark.parametrize("change", ["role", "session", "operator", "password", "permission"])
def test_prepublication_revocation_cannot_consume_the_publisher(change: str) -> None:
    h = Harness()
    changes: dict[str, dict[str, Any]] = {
        "role": {"roles": ()},
        "session": {"session_id": "apisession_" + "9" * 32},
        "operator": {"operator_id": "operator_" + "9" * 32},
        "password": {"password_change_required": True},
        "permission": {"effective_permissions": ()},
    }

    def revoke(_query: InferenceTransferSnapshotRequest) -> None:
        h.principal.value = principal(**changes[change])

    h.snapshots.on_execute = revoke
    assert_error("AUTHORIZATION_REQUIRED", lambda: publish(h))
    assert h.publisher.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"roles": ()},
        {"session_id": "apisession_" + "9" * 32},
        {"operator_id": "operator_" + "9" * 32},
        {"effective_permissions": ()},
        {"password_change_required": True},
    ],
)
def test_postcommit_revocation_withholds_receipt_and_preserves_history(
    change: dict[str, Any],
) -> None:
    h = Harness()

    def revoke() -> None:
        h.principal.value = principal(**change)

    h.publisher.on_publish = revoke
    assert_error("AUTHORIZATION_REQUIRED", lambda: publish(h))
    assert len(h.publisher.calls) == len(h.publisher.history) == len(h.artifacts.payloads) == 1
    assert h.publisher.calls[0]["payload"] == next(iter(h.artifacts.payloads.values()))


def test_current_member_result_is_rechecked_after_commit() -> None:
    h = Harness()

    def change_result() -> None:
        h.comparisons.value = rehashed(h.comparisons.value, "result_sha256", resource_version=3)

    h.publisher.on_publish = change_result
    assert_error("SOURCE_CHANGED", lambda: publish(h))
    assert len(h.publisher.history) == 1


@pytest.mark.parametrize("pin", ["graph", "policy_revision", "policy_hash"])
def test_current_comparison_must_preserve_exact_graph_and_policy(pin: str) -> None:
    h = Harness()
    change: dict[str, Any]
    if pin == "graph":
        graph = h.comparisons.value.graph_snapshot.model_dump(mode="json")
        graph["graph_snapshot_revision_id"] = "graphrev_" + "9" * 32
        change = {"graph_snapshot": graph}
    elif pin == "policy_revision":
        change = {"access_policy_revision_id": "accessrev_" + "9" * 32}
    else:
        change = {"access_policy_sha256": "sha256:" + "9" * 64}
    h.comparisons.value = rehashed(h.comparisons.value, "result_sha256", **change)
    assert_error("SOURCE_CHANGED", lambda: publish(h))
    assert h.publisher.calls == []


def test_comparison_result_must_belong_to_the_selected_exact_workflow() -> None:
    h = Harness()
    h.comparisons.value = rehashed(
        h.comparisons.value, "result_sha256", workflow_id="workflow_" + "9" * 32
    )
    with pytest.raises(ValueError):
        publish(h)
    assert h.publisher.calls == []


def test_comparison_revocation_after_commit_never_rewrites_failed_history() -> None:
    h = Harness()

    def revoke() -> None:
        h.comparisons.failure = ControlPlaneError(
            "INFERENCE_TRANSFER_FORBIDDEN", "synthetic revoke"
        )

    h.publisher.on_publish = revoke
    with pytest.raises(ControlPlaneError) as caught:
        publish(h)
    assert caught.value.code == "INFERENCE_TRANSFER_FORBIDDEN"
    assert len(h.publisher.history) == 1
    assert len(h.publisher.calls) == 1


@pytest.mark.parametrize("actor", ["operator_" + "9" * 32, "model-declared-admin"])
def test_snapshot_actor_must_be_actual_operator_not_caller_or_model(actor: str) -> None:
    h = Harness()
    header = snapshot_header(h.snapshots.records, prepare=h.snapshots.prepare, actor_id=actor)
    h.snapshots.prepared = snapshot_prepare_result(h.snapshots.records, header=header)
    assert_error("SOURCE_CHANGED", lambda: publish(h))
    assert h.publisher.calls == []


def test_snapshot_changed_header_is_not_silently_replaced_by_latest() -> None:
    h = Harness()
    header = rehashed(
        h.snapshots.prepared.header, "header_sha256", population_sha256="sha256:" + "8" * 64
    )
    h.snapshots.prepared = rehashed(
        h.snapshots.prepared, "result_sha256", header=header.model_dump(mode="json")
    )
    assert_error("SOURCE_CHANGED", lambda: publish(h))
    assert h.publisher.calls == []


def test_missing_selected_profile_is_not_backfilled_or_reselected() -> None:
    h = Harness()
    records = h.snapshots.records[1:]
    h.snapshots.prepared = snapshot_prepare_result(
        records, header=snapshot_header(records, prepare=h.snapshots.prepare, actor_id=ACTOR)
    )
    h.selection = rehashed(
        h.selection,
        "submission_sha256",
        expected_header_sha256=h.snapshots.prepared.header.header_sha256,
    )
    h.command = rehashed(h.command, "command_sha256", selection=h.selection.model_dump(mode="json"))
    assert_error("SOURCE_CHANGED", lambda: publish(h))
    assert h.publisher.calls == []


def test_unchecked_snapshot_reply_is_reparsed_before_publication() -> None:
    h = Harness()

    def tamper(
        _query: InferenceTransferSnapshotRequest, value: InferenceTransferSnapshotResult
    ) -> InferenceTransferSnapshotResult:
        return value.model_copy(update={"result_sha256": "sha256:" + "0" * 64})

    h.snapshots.transform = tamper
    with pytest.raises(ValueError):
        publish(h)
    assert h.publisher.calls == []


def test_foreign_read_record_is_rejected_even_when_self_hashed() -> None:
    h = Harness()

    def foreign(
        query: InferenceTransferSnapshotRequest, value: InferenceTransferSnapshotResult
    ) -> InferenceTransferSnapshotResult:
        if not isinstance(query, InferenceTransferSnapshotReadRequest):
            return value
        assert isinstance(value, InferenceTransferSnapshotReadResult)
        return rehashed(
            value, "result_sha256", records=[h.snapshots.records[2].model_dump(mode="json")]
        )

    h.snapshots.transform = foreign
    with pytest.raises(ValueError):
        publish(h)
    assert h.publisher.calls == []


@pytest.mark.parametrize("state", ["PENDING", "POINTER_ONLY", "NO_RESULT"])
def test_noncanonical_comparison_is_not_a_human_review_bundle(state: str) -> None:
    h = Harness()
    changes: dict[str, Any] = {"result_state": state, "result": None}
    if state == "PENDING":
        changes |= {"workflow_state": "RUNNING", "result_artifact": None}
    if state == "NO_RESULT":
        changes |= {
            "workflow_state": "FAILED",
            "result_artifact": None,
            "failure_code": "WORKER_RESULT_INVALID",
        }
    h.comparisons.value = rehashed(h.comparisons.value, "result_sha256", **changes)
    with pytest.raises(ValueError):
        publish(h)
    assert h.publisher.calls == []


def test_exact_bundle_replay_reuses_key_and_immutable_artifact() -> None:
    h = Harness()
    first = publish(h)
    h.clock = NOW + timedelta(minutes=1)
    second = publish(h)
    assert first == second
    assert len(h.publisher.calls) == 2
    assert len(h.publisher.history) == 1
    assert h.publisher.calls[0]["idempotency_key"] == h.publisher.calls[1]["idempotency_key"]
    assert h.publisher.calls[0]["payload"] == h.publisher.calls[1]["payload"]
    assert h.publisher.calls[0]["created_at"] != h.publisher.calls[1]["created_at"]


def test_changed_payload_under_same_logical_revision_conflicts() -> None:
    h = Harness()
    first = publish(h)
    original = h.artifacts.payloads[(first.pointer.artifact_id, first.pointer.artifact_revision_id)]
    h.command = rehashed(
        h.command,
        "command_sha256",
        created_at=(NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
    )
    with pytest.raises(ControlPlaneError) as caught:
        publish(h)
    assert caught.value.code == "CONTROL_ARTIFACT_CONFLICT"
    assert len(h.publisher.history) == 1
    assert (
        h.artifacts.payloads[(first.pointer.artifact_id, first.pointer.artifact_revision_id)]
        == original
    )


def test_new_bundle_revision_gets_its_own_identity_without_overwriting_prior() -> None:
    h = Harness()
    first = publish(h)
    h.command = rehashed(
        h.command, "command_sha256", bundle_revision_id="transferreviewbundlerev_" + "9" * 32
    )
    second = publish(h)
    assert first.pointer != second.pointer
    assert len(h.publisher.history) == 2


def test_unknown_publication_timeout_never_automatically_resubmits() -> None:
    h = Harness()
    h.publisher.failure_after_commit = TimeoutError("synthetic unknown delivery")
    with pytest.raises(TimeoutError):
        publish(h)
    assert len(h.publisher.calls) == len(h.publisher.history) == 1
    h.publisher.failure_after_commit = None
    replay = publish(h)
    assert replay == next(iter(h.publisher.history.values()))[1]
    assert len(h.publisher.calls) == 2 and len(h.publisher.history) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("pointer.sha256", "sha256:" + "0" * 64),
        ("pointer.schema_ref", HUMAN_REVIEW_RECORD_SCHEMA_REF),
        ("pointer.logical_name", "other.json"),
        ("pointer.media_type", "text/plain"),
        ("job_id", "unregistered-job"),
        ("manifest_sha256", "unvalidated-manifest"),
    ],
)
def test_publisher_receipt_is_checked_before_delivery(
    field: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness()
    original = h.publisher.publish_bytes

    def tamper(**values: Any) -> PublishedControlArtifact:
        receipt = original(**values)
        if field.startswith("pointer."):
            return replace(
                receipt, pointer=receipt.pointer.model_copy(update={field.split(".")[1]: value})
            )
        if field == "job_id":
            return replace(receipt, job_id=value)
        return replace(receipt, manifest_sha256=value)

    monkeypatch.setattr(h.publisher, "publish_bytes", tamper)
    assert_error("PUBLICATION_INVALID", lambda: publish(h))
    assert len(h.publisher.calls) == len(h.publisher.history) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_ref", HUMAN_REVIEW_RECORD_SCHEMA_REF),
        ("member_path", "other.json"),
        ("media_type", "text/plain"),
    ],
)
def test_wrong_bundle_member_identity_is_rejected_before_materialization(
    field: str, value: str
) -> None:
    h = Harness()
    published = publish(h)
    pointer = member(published).model_copy(update={field: value})
    assert_error("ARTIFACT_INVALID", lambda: h.owner.read_bundle(pointer))
    assert h.artifacts.calls == []


@pytest.mark.parametrize("raw", [b"", b"wrong raw bytes", b" " * (MAX_HUMAN_REVIEW_BYTES + 1)])
def test_artifact_raw_bytes_require_nonempty_bound_and_pinned_sha(raw: bytes) -> None:
    h = Harness()
    published = publish(h)
    pointer = member(published)
    h.artifacts.payloads[(pointer.artifact_id, pointer.artifact_revision_id)] = raw
    assert_error("ARTIFACT_INVALID", lambda: h.owner.read_bundle(pointer))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"duplicate":1,"duplicate":2}',
        b'{"number":NaN}',
        b'{"number":Infinity}',
        b'{"not":"a review"}',
        b"[]",
    ],
)
def test_hash_matched_untrusted_json_still_requires_closed_schema(raw: bytes) -> None:
    h = Harness()
    published = publish(h)
    pointer = member(published).model_copy(update={"sha256": sha256_bytes(raw)})
    h.artifacts.payloads[(pointer.artifact_id, pointer.artifact_revision_id)] = raw
    with pytest.raises((ValueError, JsonSchemaValidationError)):
        h.owner.read_bundle(pointer)


def test_artifact_metadata_and_record_payload_do_not_substitute_each_other() -> None:
    h = Harness()
    published = publish(h)
    pointer = member(published)
    raw = canonical_json_bytes(h.command.model_dump(mode="json"))
    h.artifacts.payloads[(pointer.artifact_id, pointer.artifact_revision_id)] = raw
    with pytest.raises(ValueError):
        h.owner.read_bundle(pointer.model_copy(update={"sha256": sha256_bytes(raw)}))


def test_bundle_read_rechecks_current_source_instead_of_trusting_hash() -> None:
    h = Harness()
    pointer = member(publish(h))
    h.comparisons.value = rehashed(h.comparisons.value, "result_sha256", resource_version=3)
    assert_error("SOURCE_CHANGED", lambda: h.owner.read_bundle(pointer))


def test_stored_bundle_payload_clock_is_not_accepted_when_future() -> None:
    h = Harness()
    published = publish(h)
    bundle = stored_bundle(h, published)
    command = rehashed(
        bundle.command,
        "command_sha256",
        created_at=(NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    )
    bundle = rehashed(bundle, "bundle_sha256", command=command.model_dump(mode="json"))
    raw = canonical_json_bytes(bundle.model_dump(mode="json"))
    pointer = member(published).model_copy(update={"sha256": sha256_bytes(raw)})
    h.artifacts.payloads[(pointer.artifact_id, pointer.artifact_revision_id)] = raw
    assert_error("INPUT_INVALID", lambda: h.owner.read_bundle(pointer))


def test_canonical_source_text_is_reconstructed_on_bundle_read() -> None:
    h = Harness()
    pointer = member(publish(h))
    record = h.snapshots.records[0]
    assert record.staged_entry is not None and record.staged_entry.content is not None
    text = record.staged_entry.content.text + "\n새 합성 원문"
    content = record.staged_entry.content.model_copy(
        update={"text": text, "text_sha256": content_sha256(text)}
    )
    changed = type(record).model_validate(
        record.model_dump(mode="json")
        | {"staged_entry": record.staged_entry.model_copy(update={"content": content})}
    )
    h.snapshots.records = (changed, *h.snapshots.records[1:])
    assert_error("SOURCE_CHANGED", lambda: h.owner.read_bundle(pointer))


def test_evaluation_preserves_explicit_label_and_is_small_pointer_record() -> None:
    h = Harness()
    bundle = publish(h)
    command = h.record_command(member(bundle))
    published = h.owner.publish_evaluation(command, source_commit=SOURCE_COMMIT)
    record = h.owner.read_evaluation(member(published))
    assert record.evaluation == command.evaluation
    assert record.bundle == member(bundle)
    assert set(record.model_dump()) == {"schema_version", "bundle", "evaluation", "record_sha256"}
    assert published.pointer.schema_ref == HUMAN_REVIEW_RECORD_SCHEMA_REF
    assert h.publisher.calls[-1]["created_at"] == NOW
    assert record.evaluation.evaluated_at == NOW - timedelta(minutes=2)
    assert "sources" not in record.model_dump()


def test_undetermined_is_explicit_human_input_not_automatic_machine_approval() -> None:
    h = Harness()
    bundle = publish(h)
    evaluation = h.evaluation(
        label="UNDETERMINED", where_helped=(), reason="합성 검토자는 아직 판단하지 못했다"
    )
    published = h.owner.publish_evaluation(
        h.record_command(member(bundle), evaluation=evaluation), source_commit=SOURCE_COMMIT
    )
    record = h.owner.read_evaluation(member(published))
    assert record.evaluation.label == "UNDETERMINED"
    assert record.evaluation.where_helped == ()
    assert "approved" not in record.model_dump(mode="json")


@pytest.mark.parametrize("change", ["reviewer", "reverse", "rubric", "future"])
def test_evaluation_must_match_real_reviewer_exact_pair_rubric_and_time(change: str) -> None:
    h = Harness()
    bundle = publish(h)
    kwargs: dict[str, Any] = {}
    if change == "reviewer":
        kwargs["reviewer_id"] = "operator_" + "9" * 32
    elif change == "reverse":
        kwargs |= {
            "left_profile": h.selection.comparison.right_profile,
            "right_profile": h.selection.comparison.left_profile,
        }
    elif change == "rubric":
        kwargs["rubric"] = h.selection.comparison.rubric.model_copy(
            update={"rubric_revision_id": "transferrubricrev_" + "9" * 32}
        )
    else:
        kwargs["evaluated_at"] = (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    command = h.record_command(member(bundle), evaluation=h.evaluation(**kwargs))
    assert_error(
        "EVALUATION_INVALID",
        lambda: h.owner.publish_evaluation(command, source_commit=SOURCE_COMMIT),
    )
    assert len(h.publisher.calls) == 1


def test_evaluation_timestamp_can_be_old_but_not_future() -> None:
    h = Harness()
    bundle = publish(h)
    evaluation = h.evaluation(
        evaluated_at=(NOW - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    )
    record = h.owner.publish_evaluation(
        h.record_command(member(bundle), evaluation=evaluation), source_commit=SOURCE_COMMIT
    )
    assert (
        h.owner.read_evaluation(member(record)).evaluation.evaluated_at == evaluation.evaluated_at
    )


def test_evaluation_same_identity_replay_and_changed_label_conflict() -> None:
    h = Harness()
    bundle = publish(h)
    command = h.record_command(member(bundle))
    first = h.owner.publish_evaluation(command, source_commit=SOURCE_COMMIT)
    assert h.owner.publish_evaluation(command, source_commit=SOURCE_COMMIT) == first
    changed = h.record_command(
        member(bundle),
        evaluation=h.evaluation(label="SURFACE_ONLY", where_helped=(), reason="합성의 다른 판단"),
    )
    with pytest.raises(ControlPlaneError) as caught:
        h.owner.publish_evaluation(changed, source_commit=SOURCE_COMMIT)
    assert caught.value.code == "CONTROL_ARTIFACT_CONFLICT"
    assert len(h.publisher.history) == 2


def test_unchecked_evaluation_command_hash_is_not_a_validation_shortcut() -> None:
    h = Harness()
    pointer = member(publish(h))
    command = h.record_command(pointer).model_copy(update={"command_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        h.owner.publish_evaluation(command, source_commit=SOURCE_COMMIT)
    assert len(h.publisher.calls) == 1


def test_record_publication_timeout_does_not_duplicate_a_human_judgment() -> None:
    h = Harness()
    bundle = publish(h)
    command = h.record_command(member(bundle))
    h.publisher.failure_after_commit = TimeoutError("synthetic unknown review commit")
    with pytest.raises(TimeoutError):
        h.owner.publish_evaluation(command, source_commit=SOURCE_COMMIT)
    assert len(h.publisher.calls) == len(h.publisher.history) == 2


def test_evaluation_postcommit_revocation_preserves_both_artifacts() -> None:
    h = Harness()
    bundle = publish(h)
    command = h.record_command(member(bundle))

    def revoke() -> None:
        h.principal.value = principal(roles=())

    h.publisher.on_publish = revoke
    assert_error(
        "AUTHORIZATION_REQUIRED",
        lambda: h.owner.publish_evaluation(command, source_commit=SOURCE_COMMIT),
    )
    assert len(h.publisher.history) == len(h.artifacts.payloads) == 2


def test_canonical_record_read_reauthorizes_referenced_bundle() -> None:
    h = Harness()
    bundle = publish(h)
    record = h.owner.publish_evaluation(
        h.record_command(member(bundle)), source_commit=SOURCE_COMMIT
    )
    h.comparisons.failure = ControlPlaneError(
        "INFERENCE_TRANSFER_FORBIDDEN", "synthetic current source denied"
    )
    with pytest.raises(ControlPlaneError) as caught:
        h.owner.read_evaluation(member(record))
    assert caught.value.code == "INFERENCE_TRANSFER_FORBIDDEN"
    assert len(h.publisher.history) == 2


@pytest.mark.parametrize("source_commit", ["main", "d" * 39, "D" * 40])
def test_source_identity_is_exact_commit_not_mutable_branch(source_commit: str) -> None:
    h = Harness()
    assert_error(
        "INPUT_INVALID", lambda: h.owner.publish_bundle(h.command, source_commit=source_commit)
    )
    assert h.publisher.calls == []


def test_bundle_document_encoded_budget_checked_before_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eom_orchestrator import inference_transfer_human_review as application

    h = Harness()
    monkeypatch.setattr(application, "MAX_HUMAN_REVIEW_BYTES", 64)
    assert_error("INPUT_INVALID", lambda: publish(h))
    assert h.publisher.calls == []


def test_existing_artifact_resolution_owner_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    from eom_orchestrator import inference_transfer_human_review_artifacts as adapter

    engine = cast(Engine, object())
    h = Harness()
    pointer = member(publish(h))
    calls: list[tuple[Engine, ArtifactMemberPointer, int]] = []

    def resolve(
        actual_engine: Engine, actual_pointer: ArtifactMemberPointer, *, maximum_bytes: int
    ) -> bytes:
        calls.append((actual_engine, actual_pointer, maximum_bytes))
        return b"synthetic owner bytes"

    monkeypatch.setattr(adapter, "resolve_control_artifact_member", resolve)
    assert (
        adapter.OwnedHumanReviewArtifacts(engine).read(pointer, maximum_bytes=1234)
        == b"synthetic owner bytes"
    )
    assert calls == [(engine, pointer, 1234)]
