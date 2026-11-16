"""Manual-login values expose no profile path, authority or activation toggle."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_manual import (
    KakaoManualClosureObservation,
    KakaoManualEnd,
    KakaoManualFreshProfile,
    KakaoManualIntent,
    KakaoManualRenew,
    KakaoManualSession,
    KakaoManualStart,
)
from eom_catalog_service.kakao_archive_commands import kakao_command_sha256
from eom_catalog_service.kakao_manual_service import manual_gateway_grant, manual_profile_fence
from eom_kakao_archive_contracts import canonical_bytes
from pydantic import ValidationError

NOW = datetime(2026, 11, 16, tzinfo=UTC)
BOOT = "12345678-1234-1234-1234-123456789abc"


def intent(**changes: object) -> KakaoManualIntent:
    fields = dict(
        lease_id="kakaoremotelease_" + "1" * 32,
        source_binding_id="kakaobinding_" + "2" * 32,
        profile_id="kakaoprofile_" + "3" * 32,
        browser_run_id="kakaobrowserrun_" + "4" * 32,
        command_sha256="sha256:" + "5" * 64,
        fence_epoch=1,
        gateway_epoch=1,
        owner_operator_id="operator_" + "6" * 32,
        identity_session_id="apisession_" + "7" * 32,
        dispatch_boot_id=BOOT,
        phase="PREPARING",
        resource_version=1,
        grant_revision=0,
        created_at=NOW,
        authorized_at=None,
        expires_at=None,
        absolute_expires_at=NOW + timedelta(minutes=20),
        browser=None,
    )
    fields.update(changes)
    return KakaoManualIntent.model_validate(fields)


@pytest.mark.parametrize("name", ["manual-session-v1", "manual-execution-v1"])
def test_schema_mirror(name: str) -> None:
    root = Path(__file__).resolve().parents[2]
    canonical = root / "schemas/kakao-archive" / (name + ".schema.json")
    mirror = (
        root
        / "packages/catalog_contracts/eom_catalog_contracts/resources/kakao-archive"
        / canonical.name
    )
    assert canonical.read_bytes() == mirror.read_bytes()


@pytest.mark.parametrize(
    "field", ["profile_id", "owner_operator_id", "ready", "channel_verified", "browser_path"]
)
def test_public_start_does_not_accept_authority(field: str) -> None:
    with pytest.raises(ValidationError):
        KakaoManualStart.model_validate(
            {"source_binding_id": "kakaobinding_" + "1" * 32, field: True}
        )


def test_separate_cas_counters_and_strict_numbers() -> None:
    assert KakaoManualRenew(expected_grant_revision=1).action == "RENEW"
    assert KakaoManualEnd(expected_resource_version=3).action == "END"
    with pytest.raises(ValidationError):
        KakaoManualRenew(expected_grant_revision=True)
    with pytest.raises(ValidationError):
        KakaoManualEnd.model_validate({"expected_grant_revision": 1})


def test_preparing_has_no_grant_and_exact_profile_command_hash() -> None:
    value = intent()
    command = manual_profile_fence(value)
    assert (
        kakao_command_sha256(command)
        == "sha256:" + sha256(canonical_bytes(command.model_dump(mode="json"))).hexdigest()
    )
    with pytest.raises(ValueError, match="NOT_READY"):
        manual_gateway_grant(value)
    granted = intent(grant_revision=1, authorized_at=NOW, expires_at=NOW + timedelta(seconds=30))
    assert manual_gateway_grant(granted).expires_at == NOW + timedelta(seconds=30)


@pytest.mark.parametrize(
    "changes",
    [
        {"grant_revision": 1},
        {"authorized_at": NOW},
        {"absolute_expires_at": NOW + timedelta(minutes=21)},
        {"grant_revision": 1, "authorized_at": NOW, "expires_at": NOW + timedelta(seconds=31)},
        {"dispatch_boot_id": None},
    ],
)
def test_invalid_lease_windows_and_missing_dispatch_pin(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        intent(**changes)


def test_profile_negative_evidence_is_explicit_not_a_permission_grant() -> None:
    proof = KakaoManualFreshProfile(
        profile_id="kakaoprofile_" + "3" * 32,
        observed_at=NOW,
        boot_id=BOOT,
        never_used=False,
        profile_empty=False,
        browser_stopped=False,
        gateway_stopped=False,
        profile_lock_released=False,
    )
    assert not proof.never_used


def test_reboot_receipt_cannot_claim_same_boot() -> None:
    pins = intent().model_dump(
        include={
            "lease_id",
            "profile_id",
            "browser_run_id",
            "command_sha256",
            "fence_epoch",
            "gateway_epoch",
            "dispatch_boot_id",
        }
    )
    with pytest.raises(ValueError, match="REBOOT_OBSERVATION"):
        KakaoManualClosureObservation.model_validate(
            {
                **pins,
                "observed_at": NOW,
                "kind": "REBOOT_UNCLEAN",
                "observed_boot_id": BOOT,
                "browser_stopped": True,
                "gateway_stopped": True,
                "profile_lock_released": True,
            }
        )


def test_ready_is_not_implied_by_pending_or_closed() -> None:
    data = dict(
        lease_id="kakaoremotelease_" + "1" * 32,
        source_binding_id="kakaobinding_" + "2" * 32,
        phase="PREPARING",
        resource_version=1,
        grant_revision=0,
        created_at=NOW,
        expires_at=None,
        absolute_expires_at=NOW + timedelta(minutes=20),
        ready=False,
        last_error=None,
        ended_reason=None,
        closed_at=None,
    )
    assert not KakaoManualSession.model_validate(data).ready
    with pytest.raises(ValueError, match="READY_INVALID"):
        KakaoManualSession.model_validate({**data, "ready": True})
