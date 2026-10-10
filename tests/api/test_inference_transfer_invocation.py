"""Fake-principal API contracts, not HTTPS, session, or installed/live acceptance."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, cast

import pytest
from eom_api.errors import ApiError
from eom_catalog_contracts.inference_transfer_experiment import SuppliedGraphBaseline
from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotChunkBudget,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import content_sha256
from eom_operator_identity import ActorSource, PermissionKey
from fastapi import FastAPI

from tests.unit.inference_transfer_api_fixtures import (
    ACTOR_ID,
    PERMISSIONS,
    ApiHarness,
    SnapshotReader,
    authentication,
    harness,
    selection,
)
from tests.unit.inference_transfer_fixtures import profile
from tests.unit.inference_transfer_invocation_fixtures import WORKFLOW_ID, read_result, rehash
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_prepare,
    snapshot_read_result,
    snapshot_records,
)

SUBMIT = "/api/v1/knowledge/inference-transfer/comparisons"
READ = f"/api/v1/knowledge/inference-transfer/workflows/{WORKFLOW_ID}"
KEY = {"Idempotency-Key": "synthetic-transfer-comparison-0001"}


@contextmanager
def api(reader: SnapshotReader | None = None) -> Iterator[ApiHarness]:
    value = harness(reader)
    try:
        with value.client:
            yield value
    finally:
        value.services.engine.dispose()


def test_submit_resolves_index_order_but_preserves_direction_and_actual_permission_provenance() -> (
    None
):
    with api() as value:
        body = selection(value.snapshots, reverse=True)
        response = value.client.post(SUBMIT, headers=KEY, json=body.model_dump(mode="json"))
        assert response.status_code == 202
        assert response.json()["data"]["status_url"] == READ
        assert response.json()["data"]["resource_id"] == WORKFLOW_ID
        submission, actor, key = value.starter.calls[0]
        wrapper = submission.workflow_request
        assert actor.actor_id == submission.operator_id == ACTOR_ID
        assert actor.source == ActorSource.APPLICATION_API
        assert actor.permissions == PERMISSIONS
        assert wrapper.requester_permissions_sha256 == content_sha256(
            sorted(permission.value for permission in PERMISSIONS)
        )
        assert wrapper.comparison == body.comparison
        assert wrapper.left_profile.profile_id == body.comparison.left_profile.profile_id
        assert wrapper.right_profile.profile_id == body.comparison.right_profile.profile_id
        assert wrapper.execution_preset_key == "item-inference-transfer-comparison"
        assert wrapper.access_policy_revision_id == body.snapshot_prepare.access_policy_revision_id
        assert wrapper.access_policy_sha256 == body.snapshot_prepare.access_policy_sha256
        assert key == value.idempotency.submission_key(
            operator_id=ACTOR_ID,
            endpoint_key="inference_transfer_pair_submit",
            raw_key=KEY["Idempotency-Key"],
        )
        reads = [
            request
            for _, request in value.snapshots.calls
            if isinstance(request, InferenceTransferSnapshotReadRequest)
        ]
        assert [read.selected_index_entries[0].source_item_revision_id for read in reads] == [
            row.source_item_revision_id for row in value.snapshots.prepared.index[:2]
        ]
        assert len(reads) == 2 and all(len(read.selected_index_entries) == 1 for read in reads)
        assert {actor_id for actor_id, _ in value.snapshots.calls} == {ACTOR_ID}


def test_cached_http_success_is_returned_only_after_current_exact_source_reads() -> None:
    with api() as value:
        body = selection(value.snapshots).model_dump(mode="json")
        first = value.client.post(SUBMIT, headers=KEY, json=body)
        replay = value.client.post(SUBMIT, headers=KEY, json=body)
        assert first.status_code == replay.status_code == 202
        assert first.json()["data"] == replay.json()["data"]
        assert len(value.starter.calls) == 1
        assert [request.phase for _, request in value.snapshots.calls] == [
            "PREPARE",
            "READ",
            "READ",
            "PREPARE",
            "READ",
            "READ",
        ]
        assert len(value.idempotency.claims) == 2


@pytest.mark.parametrize("revocation", ("SOURCE", "PERMISSION"))
def test_revoked_source_or_permission_blocks_cached_replay_before_claim(revocation: str) -> None:
    with api() as value:
        body = selection(value.snapshots).model_dump(mode="json")
        assert value.client.post(SUBMIT, headers=KEY, json=body).status_code == 202
        before = dict(value.idempotency.responses)
        if revocation == "SOURCE":
            value.snapshots.failure = "INFERENCE_TRANSFER_FORBIDDEN"
        else:
            value.authentication = authentication(PERMISSIONS - {PermissionKey.ITEM_READ})
        denied = value.client.post(SUBMIT, headers=KEY, json=body)
        assert denied.status_code == 403
        assert len(value.starter.calls) == len(value.idempotency.claims) == 1
        assert value.idempotency.responses == before
        assert not value.idempotency.failures


@pytest.mark.parametrize(
    "extra", ("actor_id", "requester_role", "permissions", "execution_preset_key", "left_profile")
)
def test_public_selection_cannot_supply_authority_preset_or_full_profiles(extra: str) -> None:
    with api() as value:
        body = selection(value.snapshots).model_dump(mode="json") | {extra: "ADMIN"}
        response = value.client.post(SUBMIT, headers=KEY, json=body)
        assert response.status_code == 422
        assert (
            not value.snapshots.calls and not value.starter.calls and not value.idempotency.claims
        )


@pytest.mark.parametrize("permission", tuple(PERMISSIONS - {PermissionKey.WORKFLOW_READ}))
def test_start_and_each_source_permission_are_checked_before_owner_read(
    permission: PermissionKey,
) -> None:
    with api() as value:
        value.authentication = authentication(PERMISSIONS - {permission})
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(value.snapshots).model_dump(mode="json")
        )
        assert response.status_code == 403
        assert (
            not value.snapshots.calls and not value.starter.calls and not value.idempotency.claims
        )


@pytest.mark.parametrize("change", ({"status": "DISABLED"}, {"must_change_password": True}))
def test_inactive_or_must_change_operator_is_not_a_submission_capability(
    change: dict[str, Any],
) -> None:
    with api() as value:
        value.authentication = replace(
            value.authentication, operator=value.authentication.operator.model_copy(update=change)
        )
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(value.snapshots).model_dump(mode="json")
        )
        assert response.status_code == 403
        assert not value.snapshots.calls and not value.starter.calls


def test_independent_authentication_password_change_flag_blocks_submission() -> None:
    with api() as value:
        value.authentication = replace(value.authentication, password_change_required=True)
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(value.snapshots).model_dump(mode="json")
        )
        assert response.status_code == 403 and not value.snapshots.calls


@pytest.mark.parametrize("field", ("profile_revision_id", "profile_sha256"))
def test_missing_or_foreign_exact_profile_is_not_replaced_with_latest(field: str) -> None:
    with api() as value:
        body = selection(value.snapshots).model_dump(mode="json")
        body["comparison"]["left_profile"][field] = (
            "inferenceprofilerev_" + "f" * 32
            if field == "profile_revision_id"
            else content_sha256("foreign")
        )
        body["comparison"] = rehash(body["comparison"], "request_sha256")
        body = rehash(body, "submission_sha256")
        response = value.client.post(SUBMIT, headers=KEY, json=body)
        assert response.status_code == 409
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID"
        assert (
            len(value.snapshots.calls) == 1
            and not value.starter.calls
            and not value.idempotency.claims
        )


def test_missing_solution_report_does_not_fabricate_a_profile() -> None:
    with api(SnapshotReader(records=snapshot_records(missing_seed="a"))) as value:
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(value.snapshots).model_dump(mode="json")
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID"
        assert len(value.snapshots.calls) == 1 and not value.starter.calls


def test_changed_expected_header_stops_before_read_or_http_claim() -> None:
    with api() as value:
        body = selection(value.snapshots).model_dump(mode="json")
        body["expected_header_sha256"] = content_sha256("obsolete header")
        response = value.client.post(SUBMIT, headers=KEY, json=rehash(body, "submission_sha256"))
        assert response.status_code == 409
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_SNAPSHOT_CHANGED"
        assert (
            len(value.snapshots.calls) == 1
            and not value.starter.calls
            and not value.idempotency.claims
        )


def test_current_operator_cannot_consume_another_operator_prepared_header() -> None:
    with api() as value:
        value.authentication = replace(
            value.authentication,
            operator=value.authentication.operator.model_copy(
                update={"operator_id": "operator_" + "f" * 32}
            ),
        )
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(value.snapshots).model_dump(mode="json")
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID"
        assert value.snapshots.calls[0][0] == value.authentication.operator.operator_id
        assert not value.starter.calls


def test_valid_one_entry_budget_is_not_expanded_or_misclassified_as_internal_error() -> None:
    reader = SnapshotReader(
        prepare=snapshot_prepare(
            chunk_budget=InferenceTransferSnapshotChunkBudget(
                max_entries=1, max_encoded_bytes=3 * 1024**2
            )
        )
    )
    with api(reader) as value:
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(reader).model_dump(mode="json")
        )
        assert response.status_code == 202
        reads = [
            request
            for _, request in reader.calls
            if isinstance(request, InferenceTransferSnapshotReadRequest)
        ]
        assert len(reads) == 2 and all(len(read.selected_index_entries) == 1 for read in reads)
        assert all(read.header.prepare.chunk_budget.max_entries == 1 for read in reads)


def test_too_small_pinned_read_byte_budget_is_422_without_side_effect() -> None:
    reader = SnapshotReader(
        prepare=snapshot_prepare(
            chunk_budget=InferenceTransferSnapshotChunkBudget(max_entries=1, max_encoded_bytes=1024)
        )
    )
    with api(reader) as value:
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(reader).model_dump(mode="json")
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED"
        assert len(reader.calls) == 1 and not value.starter.calls and not value.idempotency.claims


def test_model_copy_nested_request_tampering_fails_before_catalog_read() -> None:
    with api() as value:
        original = selection(value.snapshots)
        request = original.model_copy(
            update={
                "comparison": original.comparison.model_copy(
                    update={"request_sha256": content_sha256("tampered")}
                )
            }
        )
        with pytest.raises(ApiError) as error:
            value.services.inference_transfer_submissions.authorize_submission(
                value.authentication, request
            )
        assert error.value.error_code == "INFERENCE_TRANSFER_SUBMISSION_INVALID"
        assert not value.snapshots.calls and not value.starter.calls


def test_missing_http_idempotency_key_prevents_source_read_and_submission() -> None:
    with api() as value:
        response = value.client.post(
            SUBMIT, json=selection(value.snapshots).model_dump(mode="json")
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "API_IDEMPOTENCY_REQUIRED"
        assert not value.snapshots.calls and not value.starter.calls


@pytest.mark.parametrize("change", ("OUTER_HASH", "HEADER_HASH", "PROFILE_TEXT"))
def test_read_profile_or_context_drift_prevents_workflow_creation(change: str) -> None:
    with api() as value:
        reader = value.snapshots
        query = hashed(
            InferenceTransferSnapshotReadRequest,
            "read_sha256",
            header=reader.prepared.header,
            selected_index_entries=reader.prepared.index[:1],
        )
        reply = snapshot_read_result(reader.records[:1], request=query, baselines=())
        if change == "OUTER_HASH":
            reader.read_reply = reply.model_copy(update={"result_sha256": content_sha256("drift")})
        elif change == "HEADER_HASH":
            reader.read_reply = hashed(
                InferenceTransferSnapshotReadResult,
                "result_sha256",
                **(
                    reply.model_dump(mode="json", exclude={"result_sha256"})
                    | {"header_sha256": content_sha256("other header")}
                ),
            )
        else:
            record = reply.records[0]
            staged = record.staged_entry
            assert staged is not None
            claims = staged.profile.claims
            modified = staged.profile.model_copy(
                update={
                    "claims": (
                        claims[0].model_copy(update={"text": "uncommitted replacement"}),
                        *claims[1:],
                    )
                }
            )
            copied = record.model_copy(
                update={"staged_entry": staged.model_copy(update={"profile": modified})}
            )
            changed = reply.model_copy(update={"records": (copied,)})
            # A newly hashed transport cannot authorize modified canonical profile bytes.
            reader.read_reply = changed.model_copy(
                update={
                    "result_sha256": content_sha256(
                        changed.model_dump(mode="json", exclude={"result_sha256"})
                    )
                }
            )
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(reader).model_dump(mode="json")
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID"
        assert not value.starter.calls and not value.idempotency.claims


def test_full_index_rejects_foreign_baseline_despite_valid_chunk_hash() -> None:
    with api() as value:
        reader = value.snapshots
        query = hashed(
            InferenceTransferSnapshotReadRequest,
            "read_sha256",
            header=reader.prepared.header,
            selected_index_entries=reader.prepared.index[:1],
        )
        pointer = reader.prepared.index[0].profile
        assert pointer is not None
        foreign = InferenceTransferProfilePointer.from_profile(profile("f"))
        baseline = hashed(
            SuppliedGraphBaseline,
            "result_sha256",
            query=pointer,
            command_sha256=content_sha256("synthetic command"),
            ordered_candidates=(foreign,),
        )
        reader.read_reply = snapshot_read_result(
            reader.records[:1], request=query, baselines=(baseline,)
        )
        response = value.client.post(
            SUBMIT, headers=KEY, json=selection(reader).model_dump(mode="json")
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH"
        assert not value.starter.calls and not value.idempotency.claims


@pytest.mark.parametrize("mode", ("STATUS_ONLY", "CANONICAL_RESULT"))
def test_workflow_read_passes_actual_principal_and_preserves_member_resolution_mode(
    mode: str,
) -> None:
    with api() as value:
        response = value.client.get(READ, params={"mode": mode})
        assert response.status_code == 200
        assert response.json()["data"]["result_state"] == (
            "POINTER_ONLY" if mode == "STATUS_ONLY" else "MEMBER_VERIFIED"
        )
        assert (response.json()["data"]["result"] is None) == (mode == "STATUS_ONLY")
        actor_id, query = value.workflows.calls[0]
        assert actor_id == ACTOR_ID and query.workflow_id == WORKFLOW_ID and query.mode == mode
        assert not value.idempotency.claims and not value.snapshots.calls


@pytest.mark.parametrize(
    "permission",
    (
        PermissionKey.WORKFLOW_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
    ),
)
def test_generic_workflow_read_permission_alone_does_not_grant_pair_content(
    permission: PermissionKey,
) -> None:
    with api() as value:
        value.authentication = authentication(PERMISSIONS - {permission})
        response = value.client.get(READ)
        assert response.status_code == 403 and not value.workflows.calls


@pytest.mark.parametrize(
    "code,status",
    (
        ("INFERENCE_TRANSFER_FORBIDDEN", 403),
        ("INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND", 404),
        ("INFERENCE_TRANSFER_WORKFLOW_CHANGED", 409),
        ("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH", 409),
        ("INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID", 422),
        ("INFERENCE_TRANSFER_WORKFLOW_BUDGET_EXCEEDED", 422),
        ("INFERENCE_TRANSFER_RESULT_INVALID", 503),
        ("UNKNOWN_PRIVATE_DETAIL", 503),
    ),
)
def test_owner_read_errors_preserve_closed_safe_codes(code: str, status: int) -> None:
    with api() as value:
        value.workflows.failure = code
        response = value.client.get(READ)
        assert response.status_code == status
        assert response.json()["error_code"] == (
            "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE" if code == "UNKNOWN_PRIVATE_DETAIL" else code
        )


@pytest.mark.parametrize("change", ("HASH", "WORKFLOW", "MODE"))
def test_invalid_owner_read_hash_lineage_or_mode_is_rejected(change: str) -> None:
    with api() as value:
        reply = read_result(verified=False)
        if change == "HASH":
            value.workflows.reply = reply.model_copy(
                update={"result_sha256": content_sha256("tampered")}
            )
        elif change == "WORKFLOW":
            value.workflows.reply = hashed(
                InferenceTransferWorkflowReadResult,
                "result_sha256",
                **(
                    reply.model_dump(mode="json", exclude={"result_sha256"})
                    | {"workflow_id": "workflow_" + "f" * 32}
                ),
            )
        else:
            value.workflows.reply = read_result(verified=True)
        response = value.client.get(READ)
        assert response.status_code == 503
        assert response.json()["error_code"] == "INFERENCE_TRANSFER_RESULT_INVALID"


@pytest.mark.parametrize(
    "path", (READ + "?mode=ADMIN", "/api/v1/knowledge/inference-transfer/workflows/not-an-id")
)
def test_invalid_read_mode_or_identity_never_reaches_owner(path: str) -> None:
    with api() as value:
        response = value.client.get(path)
        assert response.status_code == 422 and not value.workflows.calls


def test_openapi_keeps_submission_and_current_read_authority_out_of_public_values() -> None:
    with api() as value:
        schema = cast(FastAPI, value.client.app).openapi()
        submit = schema["paths"][SUBMIT]["post"]
        read = schema["paths"]["/api/v1/knowledge/inference-transfer/workflows/{workflow_id}"][
            "get"
        ]
        assert submit["operationId"] == "inference_transfer_pair_submit"
        assert submit["x-eom-permission"] == PermissionKey.WORKFLOW_START.value
        assert read["x-eom-permission"] == PermissionKey.WORKFLOW_READ.value
        assert read["x-eom-read-only"] is True
        assert submit["x-eom-admin-only"] is False
        assert {field["name"] for field in read.get("parameters", ())} == {"workflow_id", "mode"}
        public = schema["components"]["schemas"]["InferenceTransferPairSubmitRequest"]["properties"]
        assert not {
            "actor_id",
            "permissions",
            "requester_role",
            "execution_preset_key",
            "left_profile",
        }.intersection(public)
