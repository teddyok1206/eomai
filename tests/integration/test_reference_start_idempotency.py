"""Existing API-claim lease yield on a marker-guarded disposable PostgreSQL DB."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.services.idempotency_service import IdempotencyService
from eom_identity_service.models import ApiIdempotencyRecord, OperatorRecord
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def claim_case(guarded_engine: Engine):
    operator_id = "operator_" + uuid4().hex
    username = "pending-claim-" + uuid4().hex
    with Session(guarded_engine) as session, session.begin():
        session.add(
            OperatorRecord(
                operator_id=operator_id,
                username=username,
                normalized_username=username,
                display_name="Synthetic deferred API claim",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="synthetic-reference-start-test",
            )
        )
    service = IdempotencyService(guarded_engine, b"synthetic-disposable-only" * 2)
    return SimpleNamespace(
        engine=guarded_engine,
        service=service,
        operator=operator_id,
        endpoint="synthetic_reference_start",
        key="synthetic:" + uuid4().hex,
        digest="sha256:" + "1" * 64,
    )


def acquire(case, *, digest=None):
    return case.service.claim(
        operator_id=case.operator,
        endpoint_key=case.endpoint,
        raw_key=case.key,
        request_sha256=digest or case.digest,
    )


def test_deferred_pending_has_no_success_failure_or_cached_response(claim_case):
    case = claim_case
    original = acquire(case)
    case.service.defer(original)
    with Session(case.engine) as session:
        row = session.get(ApiIdempotencyRecord, original.record_id)
        assert row.state == "PROCESSING" and row.lease_owner is None
        assert row.lease_expires_at <= datetime.now(UTC)
        assert row.response_body is None and row.response_status is None
        assert row.completed_at is None and row.error_code is None
        assert row.request_sha256 == case.digest
    with pytest.raises(ApiError, match="API_IDEMPOTENCY_CLAIM_LOST"):
        case.service.complete(
            original, status=202, body={}, resource_type="workflow", resource_id="late"
        )
    case.service.fail_final(original, "LATE_FAILURE")
    second = acquire(case)
    assert second.record_id == original.record_id and second.lease_owner != original.lease_owner
    body = {"resource_id": "workflow_" + "2" * 32}
    case.service.complete(
        second, status=202, body=body, resource_type="workflow", resource_id=body["resource_id"]
    )
    replay = acquire(case)
    assert replay.replayed and replay.replay_body == body
    with Session(case.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ApiIdempotencyRecord)
                .where(ApiIdempotencyRecord.operator_id == case.operator)
            )
            == 1
        )


def test_body_change_during_pending_is_not_a_new_preparation(claim_case):
    case = claim_case
    case.service.defer(acquire(case))
    with pytest.raises(ApiError, match="API_IDEMPOTENCY_CONFLICT"):
        acquire(case, digest="sha256:" + "3" * 64)


def test_stale_defer_cannot_release_another_requests_current_lease(claim_case):
    case = claim_case
    old = acquire(case)
    case.service.defer(old)
    current = acquire(case)
    with pytest.raises(ApiError, match="API_IDEMPOTENCY_CLAIM_LOST"):
        case.service.defer(old)
    with Session(case.engine) as session:
        assert session.get(ApiIdempotencyRecord, old.record_id).lease_owner == current.lease_owner


def test_two_reobservers_cannot_both_own_a_yielded_request(claim_case):
    case = claim_case
    case.service.defer(acquire(case))
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        try:
            return acquire(case)
        except ApiError as error:
            assert error.error_code == "API_IDEMPOTENCY_IN_PROGRESS"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert sum(result is not None for result in results) == 1


def test_completed_receipt_cannot_be_reopened_by_an_old_pending_callback(claim_case):
    case = claim_case
    original = acquire(case)
    case.service.complete(
        original,
        status=202,
        body={"accepted": True},
        resource_type="workflow",
        resource_id="synthetic",
    )
    with pytest.raises(ApiError, match="API_IDEMPOTENCY_CLAIM_LOST"):
        case.service.defer(original)
    assert acquire(case).replay_body == {"accepted": True}
