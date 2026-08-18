from eom_api.services.idempotency_service import IdempotencyService
from sqlalchemy import create_engine


def test_request_hash_is_canonical_and_secrets_are_one_way() -> None:
    service = IdempotencyService(create_engine("sqlite+pysqlite:///:memory:"), b"k" * 32)
    first = service.request_hash(
        method="POST",
        operation_id="operator_create",
        path_parameters={"b": "2", "a": "1"},
        body={"display_name": "검토자", "roles": ["REVIEWER"]},
        operator_id="operator_" + "a" * 32,
    )
    second = service.request_hash(
        method="POST",
        operation_id="operator_create",
        path_parameters={"a": "1", "b": "2"},
        body={"roles": ["REVIEWER"], "display_name": "검토자"},
        operator_id="operator_" + "a" * 32,
    )
    assert first == second
    raw = "TEST_ONLY temporary password 42"
    digest = service.sensitive_value_hash(raw)
    assert raw not in digest
    assert digest == service.sensitive_value_hash(raw)


def test_submission_key_is_stable_scoped_and_one_way() -> None:
    service = IdempotencyService(create_engine("sqlite+pysqlite:///:memory:"), b"k" * 32)
    raw = "workflow-submission-key-0001"
    first = service.submission_key(
        operator_id="operator_" + "a" * 32,
        endpoint_key="workflow_start",
        raw_key=raw,
    )

    assert first == service.submission_key(
        operator_id="operator_" + "a" * 32,
        endpoint_key="workflow_start",
        raw_key=raw,
    )
    assert first != service.submission_key(
        operator_id="operator_" + "b" * 32,
        endpoint_key="workflow_start",
        raw_key=raw,
    )
    assert first != service.submission_key(
        operator_id="operator_" + "a" * 32,
        endpoint_key="workflow_start",
        raw_key="workflow-submission-key-0002",
    )
    assert raw not in first
    assert len(first) == 68
