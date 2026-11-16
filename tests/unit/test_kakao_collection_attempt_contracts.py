"""Private attempt identity, schema parity and compatibility with the released worker command."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_collection_attempt import KakaoCollectionAttempt
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_identifiers import sha256_bytes
from eom_kakao_archive_contracts.execution import WorkerExecution


def value():
    return dict(
        run_id="kakaorun_" + "1" * 32,
        task_id="kakaotask_" + "2" * 32,
        attempt_id="kakaoattempt_" + "3" * 32,
        command_id="kakaocommand_" + "4" * 32,
        attempt_number=1,
        source_binding_id="kakaobinding_" + "5" * 32,
        room_id="kakaoroom_" + "6" * 32,
        profile_id="kakaoprofile_" + "7" * 32,
        browser_run_id="kakaobrowserrun_" + "8" * 32,
        fence=2,
        snapshot_revision_id="kakaosnapshotrev_" + "9" * 32,
        normalization_revision_id="kakaonormalizationrev_" + "a" * 32,
        created_at=datetime.now(UTC),
        state="RESERVED",
    )


def test_closed_schema_mirror_and_released_worker_execution_identity():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["kakao-collection-attempt-v1"]
    raw = (root / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    attempt = KakaoCollectionAttempt.model_validate(value())
    assert KakaoCollectionAttempt.model_validate_json(attempt.model_dump_json()) == attempt
    execution = WorkerExecution(
        **{name: getattr(attempt, name) for name in WorkerExecution.model_fields}
    )
    assert execution.fence == attempt.fence and execution.command_id == attempt.command_id
    with pytest.raises(ValueError):
        attempt.state = "RESULT_ACCEPTED"


@pytest.mark.parametrize(
    "change",
    [
        dict(attempt_number=2),
        dict(attempt_number=True),
        dict(fence=True),
        dict(fence=0),
        dict(room_id="name-not-identity"),
        dict(created_at=datetime.now()),
        dict(state="COMPLETED"),
        dict(cookie="forged"),
        dict(owner_operator_id="forged"),
        dict(command_sha256="forged"),
    ],
)
def test_no_permission_payload_or_implicit_retry_identity(change):
    with pytest.raises(ValueError):
        KakaoCollectionAttempt.model_validate(value() | change)
