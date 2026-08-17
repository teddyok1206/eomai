from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from eom_api.errors import ApiError
from eom_api.services.idempotency_service import IdempotencyClaim, IdempotencyService
from eom_identity_service.models import ApiIdempotencyRecord, OperatorRecord
from eom_identity_service.service import OperatorService
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from sqlalchemy import delete, func, select

from tests.api.helpers import TEST_TOKEN_KEY

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_concurrent_idempotency_claim_has_one_owner() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_API_INTEGRATION=1 with an isolated PostgreSQL database")
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        if int(session.scalar(select(func.count(OperatorRecord.operator_id))) or 0):
            pytest.skip("API concurrency requires a database without existing Operators")
    bootstrap = OperatorService(engine).bootstrap_admin(username="admin", display_name="관리자")
    service = IdempotencyService(engine, TEST_TOKEN_KEY.encode("utf-8"))
    barrier = Barrier(2)

    def claim(number: int) -> IdempotencyClaim | ApiError:
        barrier.wait(timeout=5)
        try:
            return service.claim(
                operator_id=bootstrap.operator.operator_id,
                endpoint_key="test_concurrent_claim",
                raw_key="concurrent-key-0001",
                request_sha256="sha256:" + "a" * 64,
                lease_owner=f"req_concurrent_{number}",
            )
        except ApiError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(claim, range(2)))
        assert sum(isinstance(value, IdempotencyClaim) for value in outcomes) == 1
        rejected = [value for value in outcomes if isinstance(value, ApiError)]
        assert len(rejected) == 1
        assert rejected[0].error_code == "API_IDEMPOTENCY_IN_PROGRESS"
    finally:
        with transaction(sessions) as session:
            session.execute(
                delete(ApiIdempotencyRecord).where(
                    ApiIdempotencyRecord.operator_id == bootstrap.operator.operator_id
                )
            )
            from tests.api.test_api_integration import _cleanup

        _cleanup(engine)
        engine.dispose()
