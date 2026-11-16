"""Closed collection intent metadata, without browser actions or fabricated authority."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from eom_catalog_contracts.kakao_collection import (
    AcceptedKakaoRoomCollection,
    CollectionState,
    KakaoCollectionStatus,
    KakaoRoomCollectionCreate,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import CollectionState as WorkerCollectionState


def request():
    return KakaoRoomCollectionCreate(
        source_binding_id="kakaobinding_" + "1" * 32,
        room_id="kakaoroom_" + "2" * 32,
        capability_revision_id="kakaocapabilityrev_" + "3" * 32,
        expected_binding_version=1,
        expected_policy_revision_id="kakaopolicyrev_" + "4" * 32,
    )


def receipt():
    command = request()
    return AcceptedKakaoRoomCollection(
        request=command,
        run_id="kakaorun_" + "5" * 32,
        task_id="kakaotask_" + "6" * 32,
        request_sha256=sha256_bytes(canonical_json_bytes(command.model_dump(mode="json"))),
        policy_sha256="sha256:" + "7" * 64,
        adapter_release_sha256="sha256:" + "8" * 64,
        created_at=datetime.now(UTC),
        replayed=False,
    )


def test_schema_mirror_and_source_worker_state_vocabulary_remain_aligned():
    root = Path(__file__).resolve().parents[2]
    spec = CATALOG_SCHEMA_RESOURCES["kakao-collection-intent-v1"]
    raw = (root / spec.canonical_path).read_bytes()
    assert sha256_bytes(raw) == spec.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / spec.resource_path
        ).read_bytes()
    )
    assert get_args(CollectionState) == get_args(WorkerCollectionState)
    assert AcceptedKakaoRoomCollection.model_validate_json(receipt().model_dump_json())


@pytest.mark.parametrize(
    "extra",
    [
        dict(owner_operator_id="operator_" + "a" * 32),
        dict(permissions=["ADMIN"]),
        dict(profile_id="kakaoprofile_" + "a" * 32),
        dict(adapter_release_sha256="sha256:" + "a" * 64),
        dict(capability=dict(channel_verified=True)),
        dict(click="send"),
        dict(session_id="apisession_" + "a" * 32),
        dict(nas_path="/mnt/nas/private"),
        dict(expected_binding_version=True),
        dict(expected_binding_version=0),
        dict(room_id="kakaoroom_not-an-id"),
        dict(expected_policy_revision_id="latest"),
    ],
)
def test_caller_cannot_supply_authority_paths_actions_or_implicit_latest(extra):
    with pytest.raises(ValueError):
        KakaoRoomCollectionCreate.model_validate(request().model_dump(mode="json") | extra)


@pytest.mark.parametrize(
    "change",
    [
        dict(request_sha256="sha256:" + "f" * 64),
        dict(replayed=1),
        dict(created_at=datetime.now()),
        dict(state="COMPLETED"),
        dict(output=b"large payload"),
    ],
)
def test_acceptance_is_frozen_exact_request_not_mutable_state_or_output(change):
    with pytest.raises(ValueError):
        AcceptedKakaoRoomCollection.model_validate(receipt().model_dump() | change)


def test_status_is_metadata_not_execution_or_collection_completion():
    value = receipt()
    status = KakaoCollectionStatus(
        run_id=value.run_id,
        source_binding_id=value.request.source_binding_id,
        state="QUEUED",
        resource_version=1,
        created_at=value.created_at,
        updated_at=value.created_at,
    )
    assert KakaoCollectionStatus.model_validate_json(status.model_dump_json()) == status
    with pytest.raises(ValueError):
        status.state = "COMPLETED"
    with pytest.raises(ValueError):
        KakaoCollectionStatus.model_validate(
            status.model_dump() | dict(updated_at=value.created_at - timedelta(seconds=1))
        )
