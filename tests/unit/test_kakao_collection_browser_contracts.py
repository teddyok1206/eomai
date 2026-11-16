"""Owner process metadata remains closed, versioned, UTC and free of execution tools."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_collection_browser import (
    KakaoCollectionBrowserIntent,
    KakaoCollectionBrowserObservation,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.kakao_remote import ProfileFence


def intent():
    profile, browser = "kakaoprofile_" + "1" * 32, "kakaobrowserrun_" + "2" * 32
    fence = ProfileFence(
        schema_version="kakao-profile-fence/1.0",
        profile_id=profile,
        browser_run_id=browser,
        fence_epoch=1,
        mode="AUTO",
    )
    return KakaoCollectionBrowserIntent(
        run_id="kakaorun_" + "3" * 32,
        source_binding_id="kakaobinding_" + "4" * 32,
        profile_id=profile,
        browser_run_id=browser,
        fence_epoch=1,
        epoch_number=1,
        command_sha256=sha256_bytes(canonical_json_bytes(fence.model_dump(mode="json"))),
        dispatch_boot_id="12345678-1234-1234-1234-123456789abc",
        phase="PREPARING",
        resource_version=1,
        created_at=datetime.now(UTC),
        closed_at=None,
        browser_invocation_id=None,
        browser_pid=None,
        browser_monotonic_us=None,
        browser_observed_at=None,
        last_error=None,
    )


def observation():
    value = intent()
    return KakaoCollectionBrowserObservation(
        **value.model_dump(
            include={
                "profile_id",
                "browser_run_id",
                "fence_epoch",
                "command_sha256",
                "dispatch_boot_id",
            }
        ),
        observed_boot_id=value.dispatch_boot_id,
        observed_at=value.created_at,
        kind="RUNNING",
        profile_locked=True,
        gateway_stopped=True,
        invocation_id="5" * 32,
        main_pid=123,
        started_monotonic_us=456,
    )


def test_schema_mirror_identity_and_frozen_typed_values():
    root = Path(__file__).resolve().parents[2]
    spec = CATALOG_SCHEMA_RESOURCES["kakao-collection-browser-v1"]
    raw = (root / spec.canonical_path).read_bytes()
    assert sha256_bytes(raw) == spec.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / spec.resource_path
        ).read_bytes()
    )
    value, observed = intent(), observation()
    assert KakaoCollectionBrowserIntent.model_validate_json(value.model_dump_json()) == value
    assert (
        KakaoCollectionBrowserObservation.model_validate_json(observed.model_dump_json())
        == observed
    )
    with pytest.raises(ValueError):
        value.phase = "RUNNING"


@pytest.mark.parametrize(
    "change",
    [
        dict(fence_epoch=True),
        dict(main_pid=0),
        dict(invocation_id=None),
        dict(observed_at=datetime.now()),
        dict(observed_boot_id="00000000-0000-0000-0000-000000000000"),
        dict(kind="REBOOT_UNCLEAN"),
        dict(cookie="secret"),
        dict(session_id="forged"),
        dict(click="send"),
        dict(profile_path="/private/profile"),
        dict(owner_operator_id="fake"),
        dict(process_stopped=True),
        dict(gateway_stopped=1),
        dict(runtime_error="RUNTIME_LOST"),
    ],
)
def test_observation_cannot_smuggle_authority_paths_actions_or_partial_handles(change):
    with pytest.raises(ValueError):
        KakaoCollectionBrowserObservation.model_validate(observation().model_dump() | change)


@pytest.mark.parametrize(
    "change",
    [
        dict(phase="RUNNING"),
        dict(phase="CLOSED"),
        dict(browser_pid=123),
        dict(browser_observed_at=datetime.now(UTC)),
        dict(last_error="private exception with credentials"),
        dict(absolute_expires_at=datetime.now(UTC)),
        dict(epoch_number=0),
        dict(command_sha256="latest"),
    ],
)
def test_intent_does_not_invent_runtime_readiness_or_authentication(change):
    with pytest.raises(ValueError):
        KakaoCollectionBrowserIntent.model_validate(intent().model_dump() | change)
